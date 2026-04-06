/* Minimal headless mGBA runner for chroma testing.
   Runs a GBA ROM for N frames, captures screenshots as BMP files.
   Avoids PNG to work around bundled libpng version mismatch. */

#include <mgba/flags.h>
#include <mgba/core/core.h>
#include <mgba/core/config.h>
#include <mgba/core/log.h>
#include <mgba-util/image.h>
#include <mgba-util/vfs.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <fcntl.h>

static void silence_log(struct mLogger* logger, int category, enum mLogLevel level, const char* format, va_list args) {
    (void)logger; (void)category;
    if (level == mLOG_INFO) {
        vfprintf(stderr, format, args);
        fprintf(stderr, "\n");
    }
}

static struct mLogger s_logger = { .log = silence_log };

static int write_bmp(const char* path, const mColor* pixels, int width, int height, int stride) {
    FILE* f = fopen(path, "wb");
    if (!f) return -1;

    int row_bytes = width * 3;
    int pad = (4 - (row_bytes % 4)) % 4;
    int data_size = (row_bytes + pad) * height;
    int file_size = 54 + data_size;

    /* BMP header */
    uint8_t header[54] = {0};
    header[0] = 'B'; header[1] = 'M';
    header[2] = file_size; header[3] = file_size >> 8;
    header[4] = file_size >> 16; header[5] = file_size >> 24;
    header[10] = 54; /* pixel data offset */
    header[14] = 40; /* DIB header size */
    header[18] = width; header[19] = width >> 8;
    header[22] = height; header[23] = height >> 8;
    header[26] = 1;  /* planes */
    header[28] = 24; /* bpp */
    header[34] = data_size; header[35] = data_size >> 8;
    header[36] = data_size >> 16; header[37] = data_size >> 24;

    fwrite(header, 1, 54, f);

    /* BMP is bottom-up, mColor is 32-bit ARGB/ABGR */
    uint8_t padding[3] = {0};
    for (int y = height - 1; y >= 0; y--) {
        for (int x = 0; x < width; x++) {
            mColor c = pixels[y * stride + x];
#ifdef COLOR_16_BIT
            uint8_t r = M_R8(c);
            uint8_t g = M_G8(c);
            uint8_t b = M_B8(c);
#else
            /* 32-bit: assume XBGR (mGBA default on most platforms) */
            uint8_t r = (c >> 0) & 0xFF;
            uint8_t g = (c >> 8) & 0xFF;
            uint8_t b = (c >> 16) & 0xFF;
#endif
            uint8_t bgr[3] = {b, g, r};
            fwrite(bgr, 1, 3, f);
        }
        if (pad) fwrite(padding, 1, pad, f);
    }
    fclose(f);
    return 0;
}

static void print_usage(const char* name) {
    fprintf(stderr, "Usage: %s <rom.gba> <frames> <output.bmp> [options]\n", name);
    fprintf(stderr, "  --input frame:keys     Simulate button press (A B Select Start Right Left Up Down R L)\n");
    fprintf(stderr, "  --screenshot frame:path  Capture screenshot at frame\n");
    fprintf(stderr, "  --memdump addr:len:file  Dump memory region after run\n");
    fprintf(stderr, "  --savefile path          Load/save .sav file (created if missing)\n");
    fprintf(stderr, "  Example: %s test.gba 3600 out.bmp --input 300:Start --savefile test.sav\n", name);
}

/* Parse key name to GBA key bit */
static int parse_key(const char* name) {
    if (!strcmp(name, "A")) return 0;
    if (!strcmp(name, "B")) return 1;
    if (!strcmp(name, "Select")) return 2;
    if (!strcmp(name, "Start")) return 3;
    if (!strcmp(name, "Right")) return 4;
    if (!strcmp(name, "Left")) return 5;
    if (!strcmp(name, "Up")) return 6;
    if (!strcmp(name, "Down")) return 7;
    if (!strcmp(name, "R")) return 8;
    if (!strcmp(name, "L")) return 9;
    return -1;
}

struct InputEvent {
    int frame;
    uint32_t keys;
    int press; /* 1=press, 0=release */
};

int main(int argc, char** argv) {
    if (argc < 4) {
        print_usage(argv[0]);
        return 1;
    }

    const char* rom_path = argv[1];
    int total_frames = atoi(argv[2]);
    const char* output_path = argv[3];

    /* Parse optional --input arguments and --screenshot arguments */
    struct InputEvent inputs[8192];
    int num_inputs = 0;

    struct { int frame; char path[512]; } screenshots[64];
    int num_screenshots = 0;

    const char* savefile_path = NULL;

    for (int i = 4; i < argc; i++) {
        if (!strcmp(argv[i], "--input") && i + 1 < argc) {
            i++;
            char buf[256];
            strncpy(buf, argv[i], sizeof(buf) - 1);
            buf[sizeof(buf)-1] = 0;
            char* colon = strchr(buf, ':');
            if (!colon) continue;
            *colon = 0;
            int frame = atoi(buf);
            char* keystr = colon + 1;

            uint32_t keys = 0;
            char* tok = strtok(keystr, "+,");
            while (tok) {
                int k = parse_key(tok);
                if (k >= 0) keys |= (1 << k);
                tok = strtok(NULL, "+,");
            }
            if (num_inputs < 8190) {
                inputs[num_inputs].frame = frame;
                inputs[num_inputs].keys = keys;
                inputs[num_inputs].press = 1;
                num_inputs++;
                /* Auto-release after 15 frames (~250ms) */
                inputs[num_inputs].frame = frame + 15;
                inputs[num_inputs].keys = keys;
                inputs[num_inputs].press = 0;
                num_inputs++;
            }
        } else if (!strcmp(argv[i], "--savefile") && i + 1 < argc) {
            i++;
            savefile_path = argv[i];
        } else if (!strcmp(argv[i], "--screenshot") && i + 1 < argc) {
            i++;
            char buf[768];
            strncpy(buf, argv[i], sizeof(buf) - 1);
            buf[sizeof(buf)-1] = 0;
            char* colon = strchr(buf, ':');
            if (!colon) continue;
            *colon = 0;
            if (num_screenshots < 64) {
                screenshots[num_screenshots].frame = atoi(buf);
                strncpy(screenshots[num_screenshots].path, colon + 1, 511);
                num_screenshots++;
            }
        }
    }

    mLogSetDefaultLogger(&s_logger);

    struct mCore* core = mCoreFind(rom_path);
    if (!core) {
        fprintf(stderr, "Failed to find core for %s\n", rom_path);
        return 1;
    }
    core->init(core);
    mCoreInitConfig(core, NULL);

    struct VFile* vf = VFileOpen(rom_path, O_RDONLY);
    if (!vf || !core->loadROM(core, vf)) {
        fprintf(stderr, "Failed to load ROM: %s\n", rom_path);
        return 1;
    }

    if (savefile_path) {
        mCoreLoadSaveFile(core, savefile_path, false);
        fprintf(stderr, "Save file: %s\n", savefile_path);
    }

    unsigned width, height;
    core->currentVideoSize(core, &width, &height);

    size_t stride = width;
    mColor* framebuffer = calloc(width * height, BYTES_PER_PIXEL);
    core->setVideoBuffer(core, framebuffer, stride);
    core->reset(core);

    uint32_t held_keys = 0;

    for (int frame = 0; frame < total_frames; frame++) {
        for (int j = 0; j < num_inputs; j++) {
            if (inputs[j].frame == frame) {
                if (inputs[j].press) {
                    held_keys |= inputs[j].keys;
                } else {
                    held_keys &= ~inputs[j].keys;
                }
            }
        }
        core->setKeys(core, held_keys);
        core->runFrame(core);

        for (int j = 0; j < num_screenshots; j++) {
            if (screenshots[j].frame == frame) {
                write_bmp(screenshots[j].path, framebuffer, width, height, stride);
                fprintf(stderr, "Screenshot at frame %d: %s\n", frame, screenshots[j].path);
            }
        }
    }

    /* Final screenshot */
    write_bmp(output_path, framebuffer, width, height, stride);
    fprintf(stderr, "Final screenshot at frame %d: %s\n", total_frames, output_path);

    /* Dump memory regions if --memdump specified */
    for (int i = 4; i < argc; i++) {
        if (!strcmp(argv[i], "--memdump") && i + 1 < argc) {
            i++;
            /* format: addr:len:file */
            char buf[768];
            strncpy(buf, argv[i], sizeof(buf) - 1);
            buf[sizeof(buf)-1] = 0;
            char *p1 = strchr(buf, ':');
            if (!p1) continue;
            *p1++ = 0;
            char *p2 = strchr(p1, ':');
            if (!p2) continue;
            *p2++ = 0;
            uint32_t addr = strtoul(buf, NULL, 0);
            uint32_t len = strtoul(p1, NULL, 0);
            FILE *df = fopen(p2, "wb");
            if (df) {
                for (uint32_t a = 0; a < len; a++) {
                    uint8_t byte = core->rawRead8(core, addr + a, -1);
                    fwrite(&byte, 1, 1, df);
                }
                fclose(df);
                fprintf(stderr, "Dumped %u bytes from 0x%08X to %s\n", len, addr, p2);
            }
        }
    }

    core->deinit(core);
    free(framebuffer);
    return 0;
}
