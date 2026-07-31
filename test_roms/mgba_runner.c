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
#include <limits.h>
#include <errno.h>
#include <fcntl.h>

#define MAX_INPUTS      8192
#define MAX_SCREENSHOTS 64
#define MAX_MEMDUMPS    16
#define MAX_PATH_LEN    512

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
    if (!f) {
        fprintf(stderr, "ERROR: cannot open '%s' for writing: %s\n", path, strerror(errno));
        return -1;
    }

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
    /* A short write (full disk, bad path) used to be invisible: the caller
       ignored the return value entirely and the run still exited 0, leaving a
       truncated or absent BMP for the comparison step to shrug off. */
    int bad = ferror(f);
    if (fclose(f) != 0 || bad) {
        fprintf(stderr, "ERROR: failed writing '%s': %s\n", path, strerror(errno));
        return -1;
    }
    return 0;
}

static void print_usage(const char* name) {
    fprintf(stderr, "Usage: %s <rom.gba> <frames> <output.bmp> [options]\n", name);
    fprintf(stderr, "  --input frame:keys[:hold]  Press keys at frame, release\n");
    fprintf(stderr, "                         after `hold` frames (default 15).\n");
    fprintf(stderr, "                         Keys: A B Select Start Right Left Up Down R L\n");
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

/* Strict integer parse. atoi() maps any garbage to 0, so a typo'd frame number
   used to silently become "frame 0" -- the screenshot was taken at the boot
   logo, matched nothing anyone intended, and nothing reported a problem.
   Returns -1 and complains on anything that is not a whole non-negative
   decimal number. `base` 0 additionally accepts 0x-prefixed hex. */
static long parse_uint(const char* s, int base, const char* what) {
    char* end;
    errno = 0;
    long v = strtol(s, &end, base);
    if (end == s || *end != '\0' || errno == ERANGE || v < 0) {
        fprintf(stderr, "ERROR: %s: expected a non-negative integer, got '%s'\n", what, s);
        return -1;
    }
    return v;
}

/* Copy an argument into a fixed buffer, refusing to truncate. strncpy would
   quietly cut an over-long path down to something that then gets written to
   the wrong file (or read back as "missing"). */
static int copy_arg(char* dst, size_t dstsz, const char* src, const char* what) {
    if (strlen(src) >= dstsz) {
        fprintf(stderr, "ERROR: %s: argument too long (max %zu chars): '%s'\n",
                what, dstsz - 1, src);
        return -1;
    }
    strcpy(dst, src);
    return 0;
}

int main(int argc, char** argv) {
    if (argc < 4) {
        print_usage(argv[0]);
        return 1;
    }

    const char* rom_path = argv[1];
    long total_frames = parse_uint(argv[2], 10, "<frames>");
    const char* output_path = argv[3];
    if (total_frames < 1) {
        fprintf(stderr, "ERROR: <frames> must be at least 1 (got '%s')\n", argv[2]);
        return 1;
    }
    /* Frame numbers are stored as int below, so keep the run length inside
       that range rather than letting the cast wrap into a negative frame. */
    if (total_frames > INT_MAX) {
        fprintf(stderr, "ERROR: <frames> too large (max %d)\n", INT_MAX);
        return 1;
    }

    /* Parse optional --input arguments and --screenshot arguments.
       Every malformed or unrecognized option below is a hard error. This
       parser used to `continue` past anything it could not understand -- a
       missing colon, a misspelled key name, a typo'd flag, an over-full
       array -- so a test could ask for inputs and screenshots that were
       never applied and still exit 0 with a plausible-looking BMP. */
    struct InputEvent inputs[MAX_INPUTS];
    int num_inputs = 0;

    struct { int frame; char path[MAX_PATH_LEN]; int fired; } screenshots[MAX_SCREENSHOTS];
    int num_screenshots = 0;

    struct { uint32_t addr, len; char path[MAX_PATH_LEN]; } memdumps[MAX_MEMDUMPS];
    int num_memdumps = 0;

    const char* savefile_path = NULL;

    for (int i = 4; i < argc; i++) {
        if (!strcmp(argv[i], "--input")) {
            if (++i >= argc) {
                fprintf(stderr, "ERROR: --input requires an argument (frame:keys)\n");
                return 1;
            }
            char buf[256];
            if (copy_arg(buf, sizeof(buf), argv[i], "--input") < 0) return 1;
            char* colon = strchr(buf, ':');
            if (!colon) {
                fprintf(stderr, "ERROR: --input '%s': expected frame:keys\n", argv[i]);
                return 1;
            }
            *colon = 0;
            long frame = parse_uint(buf, 10, "--input frame");
            if (frame < 0) return 1;
            char* keystr = colon + 1;

            /* Optional third field: how many frames to hold the keys down.
               The fixed 15-frame auto-release below makes some settings
               untestable -- A autofire re-triggers while the button is held,
               so with a 15-frame press the screenshot 300 frames later looks
               the same whether autofire fired once or five times (#91).
               Split this off before strtok, which would otherwise run the key
               list straight through the second colon. */
            long hold = 15;
            char* colon2 = strchr(keystr, ':');
            if (colon2) {
                *colon2 = 0;
                hold = parse_uint(colon2 + 1, 10, "--input duration");
                if (hold < 0) return 1;
                if (hold == 0) {
                    fprintf(stderr, "ERROR: --input '%s': duration must be at "
                                    "least 1 frame\n", argv[i]);
                    return 1;
                }
            }

            uint32_t keys = 0;
            char* tok = strtok(keystr, "+,");
            if (!tok) {
                fprintf(stderr, "ERROR: --input '%s': no key names given\n", argv[i]);
                return 1;
            }
            while (tok) {
                int k = parse_key(tok);
                if (k < 0) {
                    fprintf(stderr, "ERROR: --input '%s': unknown key '%s'\n", argv[i], tok);
                    return 1;
                }
                keys |= (1u << k);
                tok = strtok(NULL, "+,");
            }
            if (num_inputs + 2 > MAX_INPUTS) {
                fprintf(stderr, "ERROR: too many --input events (max %d)\n", MAX_INPUTS / 2);
                return 1;
            }
            inputs[num_inputs].frame = (int)frame;
            inputs[num_inputs].keys = keys;
            inputs[num_inputs].press = 1;
            num_inputs++;
            /* Release after the hold duration (15 frames, ~250ms, unless
               the spec asked for something else) */
            inputs[num_inputs].frame = (int)frame + (int)hold;
            inputs[num_inputs].keys = keys;
            inputs[num_inputs].press = 0;
            num_inputs++;
        } else if (!strcmp(argv[i], "--savefile")) {
            if (++i >= argc) {
                fprintf(stderr, "ERROR: --savefile requires a path\n");
                return 1;
            }
            savefile_path = argv[i];
        } else if (!strcmp(argv[i], "--screenshot")) {
            if (++i >= argc) {
                fprintf(stderr, "ERROR: --screenshot requires an argument (frame:path)\n");
                return 1;
            }
            char buf[MAX_PATH_LEN + 32];
            if (copy_arg(buf, sizeof(buf), argv[i], "--screenshot") < 0) return 1;
            char* colon = strchr(buf, ':');
            if (!colon) {
                fprintf(stderr, "ERROR: --screenshot '%s': expected frame:path\n", argv[i]);
                return 1;
            }
            *colon = 0;
            long frame = parse_uint(buf, 10, "--screenshot frame");
            if (frame < 0) return 1;
            /* The run loop only reaches frames [0, total_frames), so a spec at
               or past the frame count can never fire. Catching it here is the
               whole point: it used to produce no file, no message, and exit 0,
               which read downstream as "nothing to compare". */
            if (frame >= total_frames) {
                fprintf(stderr, "ERROR: --screenshot '%s': frame %ld is past the "
                        "run length of %ld frames; it would never be captured\n",
                        argv[i], frame, total_frames);
                return 1;
            }
            if (num_screenshots >= MAX_SCREENSHOTS) {
                fprintf(stderr, "ERROR: too many --screenshot specs (max %d)\n", MAX_SCREENSHOTS);
                return 1;
            }
            if (copy_arg(screenshots[num_screenshots].path, MAX_PATH_LEN,
                         colon + 1, "--screenshot path") < 0) return 1;
            screenshots[num_screenshots].frame = (int)frame;
            screenshots[num_screenshots].fired = 0;
            num_screenshots++;
        } else if (!strcmp(argv[i], "--memdump")) {
            if (++i >= argc) {
                fprintf(stderr, "ERROR: --memdump requires an argument (addr:len:file)\n");
                return 1;
            }
            char buf[MAX_PATH_LEN + 64];
            if (copy_arg(buf, sizeof(buf), argv[i], "--memdump") < 0) return 1;
            char* p1 = strchr(buf, ':');
            char* p2 = p1 ? strchr(p1 + 1, ':') : NULL;
            if (!p1 || !p2) {
                fprintf(stderr, "ERROR: --memdump '%s': expected addr:len:file\n", argv[i]);
                return 1;
            }
            *p1++ = 0;
            *p2++ = 0;
            long addr = parse_uint(buf, 0, "--memdump addr");
            long len = parse_uint(p1, 0, "--memdump len");
            if (addr < 0 || len < 0) return 1;
            if (len == 0) {
                fprintf(stderr, "ERROR: --memdump '%s': length must be non-zero\n", argv[i]);
                return 1;
            }
            if (num_memdumps >= MAX_MEMDUMPS) {
                fprintf(stderr, "ERROR: too many --memdump specs (max %d)\n", MAX_MEMDUMPS);
                return 1;
            }
            if (copy_arg(memdumps[num_memdumps].path, MAX_PATH_LEN,
                         p2, "--memdump file") < 0) return 1;
            memdumps[num_memdumps].addr = (uint32_t)addr;
            memdumps[num_memdumps].len = (uint32_t)len;
            num_memdumps++;
        } else {
            fprintf(stderr, "ERROR: unrecognized argument '%s'\n", argv[i]);
            print_usage(argv[0]);
            return 1;
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

    int failed = 0;

    for (long frame = 0; frame < total_frames; frame++) {
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
                if (write_bmp(screenshots[j].path, framebuffer, width, height, stride) < 0) {
                    failed = 1;
                } else {
                    screenshots[j].fired = 1;
                    fprintf(stderr, "Screenshot at frame %ld: %s\n", frame, screenshots[j].path);
                }
            }
        }
    }

    /* Final screenshot */
    if (write_bmp(output_path, framebuffer, width, height, stride) < 0) {
        failed = 1;
    } else {
        fprintf(stderr, "Final screenshot at frame %ld: %s\n", total_frames, output_path);
    }

    /* Belt-and-braces against the frame-range check at parse time: if a spec
       somehow never fired, say so and fail rather than leaving the caller to
       infer it from an absent file (run_tests.py) or crash on it
       (test_menu.py's FileNotFoundError). */
    for (int j = 0; j < num_screenshots; j++) {
        if (!screenshots[j].fired) {
            fprintf(stderr, "ERROR: screenshot at frame %d was never captured: %s\n",
                    screenshots[j].frame, screenshots[j].path);
            failed = 1;
        }
    }

    /* Dump memory regions if --memdump specified */
    for (int j = 0; j < num_memdumps; j++) {
        FILE* df = fopen(memdumps[j].path, "wb");
        if (!df) {
            fprintf(stderr, "ERROR: --memdump cannot open '%s' for writing: %s\n",
                    memdumps[j].path, strerror(errno));
            failed = 1;
            continue;
        }
        for (uint32_t a = 0; a < memdumps[j].len; a++) {
            uint8_t byte = core->rawRead8(core, memdumps[j].addr + a, -1);
            fwrite(&byte, 1, 1, df);
        }
        int bad = ferror(df);
        if (fclose(df) != 0 || bad) {
            fprintf(stderr, "ERROR: --memdump failed writing '%s': %s\n",
                    memdumps[j].path, strerror(errno));
            failed = 1;
            continue;
        }
        fprintf(stderr, "Dumped %u bytes from 0x%08X to %s\n",
                memdumps[j].len, memdumps[j].addr, memdumps[j].path);
    }

    core->deinit(core);
    free(framebuffer);
    return failed;
}
