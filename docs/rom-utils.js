/* ROM identification and validation for the browser demo.
 *
 * Split out of index.html so it can be unit-tested under Node without a DOM or
 * a WASM emulator (test_roms/test_demo_rom_utils.mjs).  The page's save
 * persistence depends entirely on romKey() being stable across visits, and its
 * error reporting depends on validateRom() actually distinguishing the failure
 * modes, so both are worth testing rather than eyeballing (#62).
 */

/** Bytes 0x104-0x107 of every genuine Game Boy cartridge header: the start of
 *  the Nintendo logo the boot ROM checks.  Cheap, decisive rejection of files
 *  that are not Game Boy ROMs at all. */
export const LOGO_PREFIX = [0xce, 0xed, 0x66, 0x66];

/** Smallest possible cart: one 16 KB bank pair. */
export const MIN_ROM_BYTES = 32 * 1024;
/** MBC5 tops out at 8 MB; anything larger is not a GB ROM we can run. */
export const MAX_ROM_BYTES = 8 * 1024 * 1024;

const EXTENSIONS = ['.gb', '.gbc'];

/**
 * Decide whether `bytes` (with original filename `name`) is a loadable GB ROM.
 * Returns {ok:true} or {ok:false, reason, detail} where `reason` is a stable
 * machine-readable tag and `detail` is a sentence for the user.
 *
 * The old page had no validation at all: a dropped directory, a .png, or a
 * text file was appended to chroma.gba and booted, landing on the emulator's
 * "No ROM found!" screen with no explanation.
 */
export function validateRom(name, bytes) {
  const lower = String(name || '').toLowerCase();
  if (!EXTENSIONS.some((ext) => lower.endsWith(ext))) {
    return {
      ok: false,
      reason: 'extension',
      detail: `"${name}" is not a .gb or .gbc file.`,
    };
  }
  if (!bytes || bytes.length < MIN_ROM_BYTES) {
    return {
      ok: false,
      reason: 'too-small',
      detail: `"${name}" is only ${bytes ? bytes.length : 0} bytes; the smallest Game Boy cartridge is ${MIN_ROM_BYTES} bytes.`,
    };
  }
  if (bytes.length > MAX_ROM_BYTES) {
    return {
      ok: false,
      reason: 'too-large',
      detail: `"${name}" is ${(bytes.length / (1024 * 1024)).toFixed(1)} MB; the largest supported cartridge is ${MAX_ROM_BYTES / (1024 * 1024)} MB.`,
    };
  }
  for (let i = 0; i < LOGO_PREFIX.length; i++) {
    if (bytes[0x104 + i] !== LOGO_PREFIX[i]) {
      return {
        ok: false,
        reason: 'header',
        detail: `"${name}" has no Game Boy cartridge header (the boot logo at 0x104 is missing), so it is not a ROM this can run.`,
      };
    }
  }
  return { ok: true };
}

/** The 11-character title from the cart header, for display and save naming. */
export function romTitle(bytes) {
  let title = '';
  for (let i = 0x134; i < 0x144; i++) {
    const c = bytes[i];
    if (c === 0 || c === undefined) break;
    // Later carts reuse 0x13F-0x143 for the manufacturer/CGB flag; keep only
    // printable ASCII so those bytes cannot inject control characters.
    if (c < 0x20 || c > 0x7e) break;
    title += String.fromCharCode(c);
  }
  return title.trim();
}

/**
 * A stable identifier for this ROM's contents.
 *
 * This is the fix for the save-loss bug: the page used to write the ROM under
 * `chroma_<Date.now()>.gba`, and mGBA derives the .sav path from the ROM path,
 * so every visit produced a different save file and no earlier save could ever
 * be found.  Keying on content means the same cartridge always resolves to the
 * same save, and two different games never collide.
 */
export async function romKey(bytes) {
  const subtle = globalThis.crypto && globalThis.crypto.subtle;
  if (subtle) {
    // Copy into a plain ArrayBuffer: a Uint8Array view over a larger buffer
    // would otherwise hash the whole backing store.
    const copy = bytes.slice();
    const digest = await subtle.digest('SHA-256', copy);
    return hex(new Uint8Array(digest)).slice(0, 16);
  }
  return fnv1a64(bytes);
}

function hex(u8) {
  let s = '';
  for (const b of u8) s += b.toString(16).padStart(2, '0');
  return s;
}

/** Non-cryptographic fallback for contexts without SubtleCrypto (plain http).
 *  Only needs to avoid collisions between a handful of ROMs. */
export function fnv1a64(bytes) {
  let h1 = 0x811c9dc5, h2 = 0x01000193;
  for (let i = 0; i < bytes.length; i++) {
    h1 = Math.imul(h1 ^ bytes[i], 0x01000193) >>> 0;
    h2 = Math.imul(h2 ^ bytes[bytes.length - 1 - i], 0x85ebca6b) >>> 0;
  }
  return (h1.toString(16).padStart(8, '0') + h2.toString(16).padStart(8, '0'));
}

/** Filesystem-safe basename for the ROM inside the emulator's virtual FS. */
export function romFileName(key, name) {
  const lower = String(name || '').toLowerCase();
  const ext = lower.endsWith('.gbc') ? 'gbc' : 'gb';
  return `chroma_${key}.${ext}`;
}

/** Name offered when the user exports their battery save. */
export function saveFileName(bytes, fallbackName) {
  const title = romTitle(bytes);
  const base = title ? title.replace(/[^A-Za-z0-9 _-]/g, '').trim() : '';
  if (base) return `${base}.sav`;
  return `${String(fallbackName || 'game').replace(/\.[^.]*$/, '')}.sav`;
}
