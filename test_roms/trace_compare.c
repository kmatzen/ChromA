/* Instruction-level trace comparison for chroma.
 *
 * Compares GB CPU execution between:
 *   1. Native mGBA GB core (reference) - single-stepped instruction by instruction
 *   2. Jagoombacolor running in mGBA GBA core - trace buffer read from EWRAM
 *
 * Build: make -f test_roms/Makefile.test trace_compare
 * Usage: trace_compare <rom.gb> <chroma_trace.gba> [options]
 *        --frames N        Run GBA for N frames (default: 60)
 *        --max-insns N     Compare at most N instructions (default: 5440)
 *        --input F:keys    Simulate button press at frame F (same as mgba_runner)
 *        --context N       Show N instructions of context around divergence (default: 5)
 *        --verbose         Print every compared instruction
 *        --ref-only        Only generate and print the reference trace
 *
 * Divergences are not failures on their own: the comparison resynchronises the
 * reference core onto chroma's state and keeps going, because the two cores
 * legitimately disagree about I/O timing.  What makes a run a failure is doing
 * that too often, which these budgets bound (see the defaults in main()):
 *        --resync-window N        window for the burst check (default: 100)
 *        --max-window-resyncs N   burst limit within that window (default: 50)
 *        --max-resync-rate P      overall resync percentage (default: 5.0)
 *        --max-state-resyncs N    register-only divergences (default: 8)
 *        --max-stack-resyncs N    call-stack divergences (default: 16)
 * Exit status is 0 only if every budget held.
 */

#include <mgba/flags.h>
#include <mgba/core/core.h>
#include <mgba/core/config.h>
#include <mgba/core/log.h>
#include <mgba/internal/gb/gb.h>
#include <mgba/internal/gb/io.h>
#include <mgba/internal/gb/video.h>
#include <mgba/internal/gb/memory.h>
#include <mgba/gb/interface.h>
#include <mgba/internal/sm83/sm83.h>
#include <mgba-util/image.h>
#include <mgba-util/vfs.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>
#include <fcntl.h>

/* Must match the layout in chroma's trace buffer (equates.h / gbz80.s) */
#define TRACE_BUF_ADDR    0x02010000
#define TRACE_BUF_HDR     8
#define TRACE_ENTRY_SIZE  12
#define TRACE_MAX_ENTRIES 10000

struct trace_entry {
    uint16_t pc;
    uint8_t a;
    uint8_t f;
    uint16_t bc;
    uint16_t de;
    uint16_t hl;
    uint16_t sp;
};

static void silence_log(struct mLogger* logger, int category, enum mLogLevel level,
                        const char* format, va_list args) {
    (void)logger; (void)category; (void)level; (void)format; (void)args;
}
static struct mLogger s_logger = { .log = silence_log };

static const char* flag_str(uint8_t f) {
    static char buf[5];
    buf[0] = (f & 0x80) ? 'Z' : '-';
    buf[1] = (f & 0x40) ? 'N' : '-';
    buf[2] = (f & 0x20) ? 'H' : '-';
    buf[3] = (f & 0x10) ? 'C' : '-';
    buf[4] = 0;
    return buf;
}

static void print_entry(int idx, const struct trace_entry* e, const char* label) {
    printf("  %s[%5d] PC=%04X A=%02X F=%s BC=%04X DE=%04X HL=%04X SP=%04X\n",
           label, idx, e->pc, e->a, flag_str(e->f), e->bc, e->de, e->hl, e->sp);
}

static bool entries_equal(const struct trace_entry* a, const struct trace_entry* b) {
    return a->pc == b->pc && a->a == b->a && a->f == b->f &&
           a->bc == b->bc && a->de == b->de && a->hl == b->hl && a->sp == b->sp;
}

static bool entries_equal_no_a(const struct trace_entry* a, const struct trace_entry* b) {
    return a->pc == b->pc && a->f == b->f &&
           a->bc == b->bc && a->de == b->de && a->hl == b->hl && a->sp == b->sp;
}

/* Check if the instruction at pc in the ROM is a timing-sensitive I/O read.
 * Returns the I/O register offset (e.g., 0x44 for LY) or -1. */
static int is_timing_io_read(const uint8_t* rom, size_t rom_size, uint16_t pc) {
    if (pc >= rom_size) return -1;
    uint8_t op = rom[pc];

    if (op == 0xF0 && pc + 1 < rom_size) {
        /* LDH A,(FF00+n) — loads A from I/O register */
        uint8_t n = rom[pc + 1];
        /* Timing-sensitive registers: */
        if (n == 0x04) return n;  /* DIV */
        if (n == 0x05) return n;  /* TIMA */
        if (n == 0x41) return n;  /* STAT */
        if (n == 0x44) return n;  /* LY */
        if (n == 0x00) return n;  /* JOYP (input-dependent) */
    }
    if (op == 0xF2) {
        /* LD A,(FF00+C) — I/O read via C register, could be anything */
        return 0xFF;  /* flag as generic I/O read */
    }
    return -1;
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
    int press;
};

int main(int argc, char** argv) {
    if (argc < 3) {
        fprintf(stderr, "Usage: %s <rom.gb> <chroma_trace.gba> [options]\n", argv[0]);
        fprintf(stderr, "  --frames N        GBA frames to run (default 60)\n");
        fprintf(stderr, "  --max-insns N     Max instructions to compare (default %d)\n", TRACE_MAX_ENTRIES);
        fprintf(stderr, "  --input F:keys    Button press at frame F\n");
        fprintf(stderr, "  --context N       Context lines around divergence (default 5)\n");
        fprintf(stderr, "  --resync-window N Sliding window (instructions) for the resync\n");
        fprintf(stderr, "                    density check (default 100)\n");
        fprintf(stderr, "  --max-window-resyncs N  Fail if a window holds more than N\n");
        fprintf(stderr, "                    resyncs (default 50)\n");
        fprintf(stderr, "  --max-resync-rate P   Fail above P%% resyncs overall (default 5.0)\n");
        fprintf(stderr, "  --max-state-resyncs N Fail above N register-only divergences\n");
        fprintf(stderr, "                    (default 8) -- the tight correctness check\n");
        fprintf(stderr, "  --max-stack-resyncs N Fail after N SP divergences (default 16)\n");
        fprintf(stderr, "  --verbose         Print every instruction\n");
        fprintf(stderr, "  --ref-only        Only run the reference trace\n");
        return 1;
    }

    const char* gb_rom_path = argv[1];
    const char* gba_rom_path = argv[2];
    int total_frames = 60;
    int max_insns = TRACE_MAX_ENTRIES;
    int context = 5;
    /* Every divergence case below force-syncs the reference core to chroma's
     * state and carries on, so without a budget the comparison can never
     * report a failure no matter how far apart the two cores drift.  These
     * are the caps that turn "kept going" back into "failed".
     *
     * The defaults come from measuring clean builds against POKEMON
     * RED/BLUE/YELLOW/GOLD, ZELDA, POKEMON PINBALL and the probe ROMs.
     * They differ a lot in how much they legitimately resync, so the caps
     * are not all equally tight:
     *
     *   code-path resyncs are the noisy ones (up to 114 per 5000, 2.3%).
     *     Commercial ROMs sit in a VBlank poll loop whose LY reads get
     *     patched, and a patched read routinely sends the two cores down
     *     different branches.  Only the loose rate/burst backstops apply.
     *
     *   register-only resyncs mean PC and SP agree but a value does not --
     *     chroma computed something different, which is not explained by
     *     the I/O patch list.  Clean builds produce 0 or 1 of these on
     *     every ROM measured, so this cap is the tight one and is what
     *     actually catches correctness regressions. */
    int resync_window = 100;
    int max_window_resyncs = 50;
    double max_resync_rate = 5.0;
    int max_state_resyncs = 8;
    int max_stack_resyncs = 16;
    bool verbose = false;
    bool ref_only = false;

    struct InputEvent inputs[8192];
    int num_inputs = 0;

    for (int i = 3; i < argc; i++) {
        if (!strcmp(argv[i], "--frames") && i + 1 < argc) {
            total_frames = atoi(argv[++i]);
        } else if (!strcmp(argv[i], "--max-insns") && i + 1 < argc) {
            max_insns = atoi(argv[++i]);
            if (max_insns > TRACE_MAX_ENTRIES) max_insns = TRACE_MAX_ENTRIES;
        } else if (!strcmp(argv[i], "--context") && i + 1 < argc) {
            context = atoi(argv[++i]);
        } else if (!strcmp(argv[i], "--resync-window") && i + 1 < argc) {
            resync_window = atoi(argv[++i]);
            if (resync_window < 1) resync_window = 1;
        } else if (!strcmp(argv[i], "--max-window-resyncs") && i + 1 < argc) {
            max_window_resyncs = atoi(argv[++i]);
        } else if (!strcmp(argv[i], "--max-resync-rate") && i + 1 < argc) {
            max_resync_rate = atof(argv[++i]);
        } else if (!strcmp(argv[i], "--max-state-resyncs") && i + 1 < argc) {
            max_state_resyncs = atoi(argv[++i]);
        } else if (!strcmp(argv[i], "--max-stack-resyncs") && i + 1 < argc) {
            max_stack_resyncs = atoi(argv[++i]);
        } else if (!strcmp(argv[i], "--verbose")) {
            verbose = true;
        } else if (!strcmp(argv[i], "--ref-only")) {
            ref_only = true;
        } else if (!strcmp(argv[i], "--input") && i + 1 < argc) {
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
                inputs[num_inputs].frame = frame + 15;
                inputs[num_inputs].keys = keys;
                inputs[num_inputs].press = 0;
                num_inputs++;
            }
        }
    }

    mLogSetDefaultLogger(&s_logger);

    /* Load ROM into memory for opcode decoding during comparison */
    uint8_t* rom_data = NULL;
    size_t rom_size = 0;
    {
        FILE* rf = fopen(gb_rom_path, "rb");
        if (rf) {
            fseek(rf, 0, SEEK_END);
            rom_size = ftell(rf);
            fseek(rf, 0, SEEK_SET);
            rom_data = malloc(rom_size);
            if (rom_data) fread(rom_data, 1, rom_size, rf);
            fclose(rf);
        }
    }

    /* ===== PHASE 1: Generate reference trace from GB core ===== */
    fprintf(stderr, "=== Phase 1: Reference trace (mGBA GB core) ===\n");

    struct mCore* gb_core = mCoreFind(gb_rom_path);
    if (!gb_core) {
        fprintf(stderr, "ERROR: Could not find core for %s\n", gb_rom_path);
        return 1;
    }
    gb_core->init(gb_core);
    mCoreInitConfig(gb_core, NULL);

    /* Skip boot ROM — start at PC=0x100 with post-boot state (matches chroma) */
    mCoreConfigSetOverrideIntValue(&gb_core->config, "useBios", 0);
    mCoreConfigSetOverrideIntValue(&gb_core->config, "skipBios", 1);

    /* Force CGB model to match chroma's behavior for GBC ROMs */
    /* Check ROM header byte 0x143 for CGB flag */
    struct VFile* gb_vf = VFileOpen(gb_rom_path, O_RDONLY);
    if (!gb_vf) {
        fprintf(stderr, "ERROR: Could not open %s\n", gb_rom_path);
        return 1;
    }
    uint8_t cgb_flag = 0;
    gb_vf->seek(gb_vf, 0x143, SEEK_SET);
    gb_vf->read(gb_vf, &cgb_flag, 1);
    gb_vf->seek(gb_vf, 0, SEEK_SET);

    bool is_cgb = (cgb_flag & 0x80) != 0;
    if (is_cgb) {
        /* Jagoombacolor runs CGB ROMs in AGB mode (A=0x11, B=0x01) */
        mCoreConfigSetOverrideIntValue(&gb_core->config, "gb.model", GB_MODEL_AGB);
    } else {
        /* Jagoombacolor always uses DMG registers for non-CGB ROMs, even SGB-capable ones */
        mCoreConfigSetOverrideIntValue(&gb_core->config, "gb.model", GB_MODEL_DMG);
    }
    /* Ensure SGB features are disabled to match chroma's default behavior */
    mCoreConfigSetOverrideIntValue(&gb_core->config, "sgb.model", 0);
    mCoreConfigSetOverrideIntValue(&gb_core->config, "sgb.borders", 0);

    if (!gb_core->loadROM(gb_core, gb_vf)) {
        fprintf(stderr, "ERROR: Could not load GB ROM\n");
        return 1;
    }

    /* Set up video buffer (required even for headless) */
    unsigned gb_w, gb_h;
    gb_core->currentVideoSize(gb_core, &gb_w, &gb_h);
    mColor* gb_fb = calloc(gb_w * gb_h, 4);
    gb_core->setVideoBuffer(gb_core, (mColor*)gb_fb, gb_w);

    gb_core->reset(gb_core);

    struct GB* gb = (struct GB*)gb_core->board;
    struct SM83Core* cpu = gb->cpu;

    /* Force post-boot register state to match chroma exactly.
     * mGBA may auto-detect SGB and use different values. Override here. */
    if (is_cgb) {
        /* Match chroma's emu_reset for CGB/AGB mode:
         * A=0x11, F=Z+C+H (0xB0), B=0x01 (AGB), C=0x13,
         * DE=0x00D8, HL=0x014D — NOT real AGB post-boot values */
        cpu->a = 0x11;
        cpu->f.packed = 0xB0;  /* Z, H, C flags set */
        cpu->b = 0x00;  /* chroma checks gbamode separately */
        cpu->c = 0x13;
        cpu->d = 0x00;
        cpu->e = 0xD8;
        cpu->h = 0x01;
        cpu->l = 0x4D;
    } else {
        cpu->a = 0x01;
        cpu->f.packed = 0xB0;  /* Z, H, C flags set */
        cpu->b = 0x00;
        cpu->c = 0x13;
        cpu->d = 0x00;
        cpu->e = 0xD8;
        cpu->h = 0x01;
        cpu->l = 0x4D;
    }
    cpu->sp = 0xFFFE;
    cpu->pc = 0x100;

    /* Note: mGBA's LCD starts mid-VBlank after GBSkipBIOS while chroma
     * starts at LY=0. LY reads will differ — handled by I/O patching in Phase 3. */

    if (ref_only) {
        fprintf(stderr, "  Stepping %d instructions...\n", max_insns);
        printf("Reference trace (%d instructions):\n", max_insns);
        for (int i = 0; i < max_insns; i++) {
            struct trace_entry e = {
                cpu->pc, cpu->a, cpu->f.packed,
                cpu->bc, cpu->de, cpu->hl, cpu->sp
            };
            print_entry(i, &e, "REF");
            gb_core->step(gb_core);
        }
        gb_core->deinit(gb_core);
        free(gb_fb);
        return 0;
    }
    /* Reference trace will be generated on-the-fly during comparison
     * so we can patch I/O reads to keep the cores in sync. */

    /* ===== PHASE 2: Run chroma and extract trace ===== */
    fprintf(stderr, "=== Phase 2: Jagoombacolor trace (mGBA GBA core) ===\n");

    struct mCore* gba_core = mCoreFind(gba_rom_path);
    if (!gba_core) {
        fprintf(stderr, "ERROR: Could not find core for %s\n", gba_rom_path);
        return 1;
    }
    gba_core->init(gba_core);
    mCoreInitConfig(gba_core, NULL);

    struct VFile* gba_vf = VFileOpen(gba_rom_path, O_RDONLY);
    if (!gba_vf || !gba_core->loadROM(gba_core, gba_vf)) {
        fprintf(stderr, "ERROR: Could not load GBA ROM\n");
        return 1;
    }

    unsigned gba_w, gba_h;
    gba_core->currentVideoSize(gba_core, &gba_w, &gba_h);
    mColor* gba_fb = calloc(gba_w * gba_h, 4);
    gba_core->setVideoBuffer(gba_core, (mColor*)gba_fb, gba_w);

    gba_core->reset(gba_core);

    fprintf(stderr, "  Running %d frames...\n", total_frames);
    uint32_t held_keys = 0;
    for (int frame = 0; frame < total_frames; frame++) {
        for (int j = 0; j < num_inputs; j++) {
            if (inputs[j].frame == frame) {
                if (inputs[j].press)
                    held_keys |= inputs[j].keys;
                else
                    held_keys &= ~inputs[j].keys;
            }
        }
        gba_core->setKeys(gba_core, held_keys);
        gba_core->runFrame(gba_core);
    }

    /* Read trace buffer from EWRAM */
    uint32_t write_index = gba_core->rawRead32(gba_core, TRACE_BUF_ADDR, -1);
    uint32_t buf_max     = gba_core->rawRead32(gba_core, TRACE_BUF_ADDR + 4, -1);

    fprintf(stderr, "  Trace buffer: %u entries written (max %u)\n", write_index, buf_max);

    if (write_index == 0) {
        fprintf(stderr, "ERROR: Trace buffer is empty. Is this a TRACE=1 build?\n");
        gb_core->deinit(gb_core);
        gba_core->deinit(gba_core);
        free(gb_fb); free(gba_fb);
        return 1;
    }

    int jgbc_count = (int)write_index;
    if (jgbc_count > max_insns) jgbc_count = max_insns;

    struct trace_entry* jgbc_trace = calloc(jgbc_count, sizeof(struct trace_entry));
    for (int i = 0; i < jgbc_count; i++) {
        uint32_t addr = TRACE_BUF_ADDR + TRACE_BUF_HDR + i * TRACE_ENTRY_SIZE;
        jgbc_trace[i].pc = (uint16_t)gba_core->rawRead16(gba_core, addr + 0, -1);
        jgbc_trace[i].a  = (uint8_t)gba_core->rawRead8(gba_core, addr + 2, -1);
        jgbc_trace[i].f  = (uint8_t)gba_core->rawRead8(gba_core, addr + 3, -1);
        jgbc_trace[i].bc = (uint16_t)gba_core->rawRead16(gba_core, addr + 4, -1);
        jgbc_trace[i].de = (uint16_t)gba_core->rawRead16(gba_core, addr + 6, -1);
        jgbc_trace[i].hl = (uint16_t)gba_core->rawRead16(gba_core, addr + 8, -1);
        jgbc_trace[i].sp = (uint16_t)gba_core->rawRead16(gba_core, addr + 10, -1);
    }

    /* ===== PHASE 2.5: Align traces ===== */
    /* Jagoombacolor boots its own UI before starting the GB emulator.
     * Find the first entry with PC=0x100 (GB entry point) to align. */
    int jgbc_offset = 0;
    for (int i = 0; i < jgbc_count; i++) {
        if (jgbc_trace[i].pc == 0x0100) {
            jgbc_offset = i;
            break;
        }
    }
    if (jgbc_offset > 0) {
        fprintf(stderr, "  Skipping %d pre-boot entries in chroma trace\n", jgbc_offset);
        jgbc_count -= jgbc_offset;
        memmove(jgbc_trace, jgbc_trace + jgbc_offset, jgbc_count * sizeof(struct trace_entry));
    }

    /* ===== PHASE 3: Interleaved compare with I/O patching ===== */
    /* Step the reference core one instruction at a time, comparing against
     * the chroma trace. When an I/O read produces a different value
     * (due to timing), patch the reference core's A register to match
     * chroma's, keeping both on the same code path. */
    fprintf(stderr, "=== Phase 3: Interleaved comparison ===\n");

    int ji = 0;  /* jgbc trace index */
    int match_count = 0;
    int io_patches = 0;
    int timing_gaps = 0;
    bool has_hard_diverge = false;
    int hard_diverge_ji = -1;
    uint16_t last_pc = 0;  /* PC of previous instruction (for I/O read detection) */

    /* Resyncs split by how badly the cores disagreed, so the report says which
     * kind of drift is being tolerated rather than lumping them together. */
    int state_resyncs = 0;   /* PC and SP agree, other registers do not */
    int path_resyncs = 0;    /* PC diverged (different code path), SP agrees */
    int stack_resyncs = 0;   /* SP diverged -- diverged call stack */

    /* Compare indices of every resync so far, ascending.  window_lo is the
     * oldest one still inside the trailing `resync_window` instructions, so
     * resync_n - window_lo is the current density. */
    int* resync_idx = malloc(sizeof(int) * (size_t)(jgbc_count + 1));
    if (!resync_idx) {
        fprintf(stderr, "ERROR: out of memory for resync tracking\n");
        return 1;
    }
    int resync_n = 0, window_lo = 0;
    int worst_density = 0, worst_density_ji = -1;

    /* Bookkeeping shared by every resync case below. */
    #define NOTE_RESYNC(bucket) do {                                          \
        (bucket)++;                                                           \
        timing_gaps++;                                                        \
        resync_idx[resync_n++] = ji;                                          \
        while (window_lo < resync_n &&                                        \
               resync_idx[window_lo] <= ji - resync_window) window_lo++;      \
        if (resync_n - window_lo > worst_density) {                           \
            worst_density = resync_n - window_lo;                             \
            worst_density_ji = ji;                                            \
        }                                                                     \
    } while (0)

    while (ji < jgbc_count) {
        /* Capture reference state before execution */
        struct trace_entry ref = {
            cpu->pc, cpu->a, cpu->f.packed,
            cpu->bc, cpu->de, cpu->hl, cpu->sp
        };
        struct trace_entry* jgbc = &jgbc_trace[ji];

        if (entries_equal(&ref, jgbc)) {
            if (verbose) {
                printf("  OK  JGC[%5d] PC=%04X A=%02X F=%s BC=%04X DE=%04X HL=%04X SP=%04X\n",
                       ji, ref.pc, ref.a, flag_str(ref.f), ref.bc, ref.de, ref.hl, ref.sp);
            }
            match_count++;
            last_pc = cpu->pc;
            gb_core->step(gb_core);
            ji++;
            continue;
        }

        /* Divergence. Check if only A differs due to a timing-sensitive I/O read. */
        if (entries_equal_no_a(&ref, jgbc) && rom_data) {
            int io_reg = is_timing_io_read(rom_data, rom_size, last_pc);
            if (io_reg >= 0) {
                if (verbose) {
                    printf("  IO  JGC[%5d] PC=%04X A=%02X->%02X (FF%02X read)\n",
                           ji, ref.pc, ref.a, jgbc->a, io_reg);
                }
                /* Patch the reference core's A to match chroma's value.
                 * This keeps the reference on the same code path. */
                cpu->a = jgbc->a;
                io_patches++;
                match_count++;
                last_pc = cpu->pc;
                gb_core->step(gb_core);
                ji++;
                continue;
            }
        }

        /* Check if PC+SP match but other regs differ — likely a memory read
         * from a location that has different contents due to I/O timing
         * propagation. Patch the reference to match. */
        if (ref.pc == jgbc->pc && ref.sp == jgbc->sp) {
            if (verbose) {
                printf("  FIX JGC[%5d] PC=%04X (state diff, syncing)\n", ji, ref.pc);
            }
            cpu->a = jgbc->a;
            cpu->f.packed = jgbc->f;
            cpu->bc = jgbc->bc;
            cpu->de = jgbc->de;
            cpu->hl = jgbc->hl;
            NOTE_RESYNC(state_resyncs);
            match_count++;
            last_pc = cpu->pc;
            gb_core->step(gb_core);
            ji++;
            continue;
        }

        /* PC differs — the traces have diverged onto different code paths.
         * This can happen when a conditional branch was taken differently
         * due to flags set by a previous I/O-dependent computation.
         * Reset the reference core to match chroma's state and continue. */
        if (ref.sp == jgbc->sp) {
            if (verbose) {
                printf("  RESYNC JGC[%5d] REF PC=%04X -> JGC PC=%04X\n",
                       ji, ref.pc, jgbc->pc);
            }
            cpu->pc = jgbc->pc;
            cpu->a = jgbc->a;
            cpu->f.packed = jgbc->f;
            cpu->bc = jgbc->bc;
            cpu->de = jgbc->de;
            cpu->hl = jgbc->hl;
            /* Re-encode PC for mGBA (set the memory mapper to the right bank) */
            NOTE_RESYNC(path_resyncs);
            match_count++;
            last_pc = cpu->pc;
            gb_core->step(gb_core);
            ji++;
            continue;
        }

        /* SP differs. This can happen when an interrupt fires at a different
         * point in each core (chroma's scanline-based timing vs mGBA's
         * cycle-accurate timing). An interrupt pushes PC, changes SP, and
         * jumps to a handler — causing both PC and SP to diverge.
         *
         * A diverged call stack is the case most likely to be a real CPU bug
         * rather than timing jitter, so it gets its own small budget: past
         * that the cores are not meaningfully being compared any more and
         * this falls through to the hard-divergence report below.  The budget
         * is not zero because a handful do occur legitimately (POKEMON
         * PINBALL hits 2 in its first 5000 instructions). */
        if (stack_resyncs < max_stack_resyncs) {
            if (verbose) {
                /* SP decreasing means chroma took an interrupt the reference
                 * has not; increasing means the reverse. */
                printf("  IRQ JGC[%5d] REF PC=%04X SP=%04X -> JGC PC=%04X SP=%04X (interrupt in %s)\n",
                       ji, ref.pc, ref.sp, jgbc->pc, jgbc->sp,
                       jgbc->sp < ref.sp ? "chroma" : "ref");
            }
            cpu->pc = jgbc->pc;
            cpu->sp = jgbc->sp;
            cpu->a = jgbc->a;
            cpu->f.packed = jgbc->f;
            cpu->bc = jgbc->bc;
            cpu->de = jgbc->de;
            cpu->hl = jgbc->hl;
            NOTE_RESYNC(stack_resyncs);
            match_count++;
            last_pc = cpu->pc;
            gb_core->step(gb_core);
            ji++;
            continue;
        }

        /* Unrecoverable divergence: the stack-resync budget is spent. */
        has_hard_diverge = true;
        hard_diverge_ji = ji;
        printf("\n*** HARD DIVERGENCE at JGC[%d] ***\n", ji);
        printf("  REF: PC=%04X A=%02X F=%s BC=%04X DE=%04X HL=%04X SP=%04X\n",
               ref.pc, ref.a, flag_str(ref.f), ref.bc, ref.de, ref.hl, ref.sp);
        printf("  JGC: PC=%04X A=%02X F=%s BC=%04X DE=%04X HL=%04X SP=%04X\n",
               jgbc->pc, jgbc->a, flag_str(jgbc->f), jgbc->bc, jgbc->de, jgbc->hl, jgbc->sp);
        break;
    }

    /* ===== Report results ===== */
    double resync_rate = match_count > 0 ? (100.0 * timing_gaps) / match_count : 0.0;

    /* Every resync above is a divergence that was papered over by dragging the
     * reference core onto chroma's state, so a run is only meaningful while
     * they stay rare.  Check the budgets that make that explicit. */
    bool rate_blown = resync_rate > max_resync_rate;
    bool burst_blown = worst_density > max_window_resyncs;
    bool state_blown = state_resyncs > max_state_resyncs;
    bool failed = has_hard_diverge || rate_blown || burst_blown || state_blown;

    printf("\n");
    printf("=== Results ===\n");
    printf("  Matched: %d instructions\n", match_count);
    printf("  I/O timing patches: %d\n", io_patches);
    printf("  State resyncs: %d (%.2f%% of compared instructions)\n",
           timing_gaps, resync_rate);
    printf("    register-only: %d, code-path: %d, call-stack: %d\n",
           state_resyncs, path_resyncs, stack_resyncs);
    if (worst_density_ji >= 0) {
        printf("  Densest resync burst: %d in %d instructions (near JGC[%d])\n",
               worst_density, resync_window, worst_density_ji);
    }
    printf("  JGC consumed: %d / %d\n", ji, jgbc_count);

    if (has_hard_diverge) {
        printf("\n*** HARD DIVERGENCE (possible CPU bug) at JGC[%d] ***\n", hard_diverge_ji);
        printf("  Call stack diverged %d times (limit %d) — the traces are no\n",
               stack_resyncs, max_stack_resyncs);
        printf("  longer executing the same program. Likely a real bug.\n");
    }
    if (state_blown) {
        printf("\n*** FAIL: %d register-only divergences (limit %d) ***\n",
               state_resyncs, max_state_resyncs);
        printf("  PC and SP agreed but a register value did not, which the I/O\n");
        printf("  timing patch list does not explain — chroma computed a\n");
        printf("  different value. This is the signature of a real bug.\n");
    }
    if (rate_blown) {
        printf("\n*** FAIL: resync rate %.2f%% exceeds the %.2f%% limit ***\n",
               resync_rate, max_resync_rate);
        printf("  The reference core was force-synced to chroma this often, so\n");
        printf("  most of this run was not actually being compared.\n");
    }
    if (burst_blown) {
        printf("\n*** FAIL: %d resyncs within %d instructions near JGC[%d] (limit %d) ***\n",
               worst_density, resync_window, worst_density_ji, max_window_resyncs);
        printf("  A burst this dense means the traces came apart rather than\n");
        printf("  drifting — isolated timing jitter does not cluster.\n");
    }

    if (failed) {
        printf("\nFAIL: comparison did not stay within its divergence budget.\n");
    } else if (match_count > 0 && timing_gaps == 0 && io_patches == 0) {
        printf("\nPASS: All %d instructions match exactly.\n", match_count);
    } else {
        printf("\nPASS: %d instructions match (%d I/O patches, %d resyncs).\n",
               match_count, io_patches, timing_gaps);
    }

    if (write_index >= buf_max) {
        printf("\nNOTE: Trace buffer was full (%u entries). Increase buffer or reduce frames.\n",
               buf_max);
    }

    gb_core->deinit(gb_core);
    gba_core->deinit(gba_core);
    free(gb_fb);
    free(gba_fb);
    free(jgbc_trace);
    free(rom_data);
    free(resync_idx);

    return failed ? 1 : 0;
}
#undef NOTE_RESYNC
