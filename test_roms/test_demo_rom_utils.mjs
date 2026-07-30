/* Unit tests for the browser demo's ROM identification and validation
 * (docs/rom-utils.js), the logic behind issue #62.
 *
 * The demo itself needs a browser, a WASM build and a real ROM, so it has
 * never had automated coverage -- which is how "every ROM load deletes the
 * save directory" survived.  The two pieces that actually decide whether a
 * user keeps their save are pure functions, so they can be tested here with
 * nothing but Node.
 *
 * Run: node test_roms/test_demo_rom_utils.mjs
 */

import assert from 'node:assert/strict';
import {
  validateRom, romKey, romTitle, romFileName, saveFileName, fnv1a64,
  MIN_ROM_BYTES, MAX_ROM_BYTES, LOGO_PREFIX,
} from '../docs/rom-utils.js';

let passed = 0;
async function test(name, fn) {
  try {
    await fn();
    passed++;
    console.log('  ok   ' + name);
  } catch (e) {
    console.log('  FAIL ' + name);
    console.log('       ' + e.message);
    process.exitCode = 1;
  }
}

/** A minimal but structurally valid cartridge image. */
function makeRom({ size = MIN_ROM_BYTES, title = 'TESTROM', logo = true, fill = 0 } = {}) {
  const rom = new Uint8Array(size).fill(fill);
  if (logo) LOGO_PREFIX.forEach((b, i) => { rom[0x104 + i] = b; });
  for (let i = 0; i < title.length && i < 16; i++) rom[0x134 + i] = title.charCodeAt(i);
  return rom;
}

console.log('=== demo ROM utils ===');

await test('accepts a well-formed .gb ROM', () => {
  assert.equal(validateRom('game.gb', makeRom()).ok, true);
});

await test('accepts a well-formed .gbc ROM', () => {
  assert.equal(validateRom('game.gbc', makeRom()).ok, true);
});

await test('rejects a non-ROM extension (the drag-drop hole)', () => {
  // The accept="" filter only constrains the file picker; drag-and-drop
  // bypassed it entirely and any file was appended to chroma.gba and booted.
  const v = validateRom('screenshot.png', makeRom());
  assert.equal(v.ok, false);
  assert.equal(v.reason, 'extension');
  assert.match(v.detail, /not a \.gb or \.gbc file/);
});

await test('rejects a file that is too small to be a cartridge', () => {
  const v = validateRom('tiny.gb', new Uint8Array(1024));
  assert.equal(v.ok, false);
  assert.equal(v.reason, 'too-small');
});

await test('rejects a file larger than the biggest supported cartridge', () => {
  const v = validateRom('huge.gb', new Uint8Array(MAX_ROM_BYTES + 1));
  assert.equal(v.ok, false);
  assert.equal(v.reason, 'too-large');
});

await test('rejects a .gb-named file with no cartridge header', () => {
  const v = validateRom('notarom.gb', makeRom({ logo: false }));
  assert.equal(v.ok, false);
  assert.equal(v.reason, 'header');
});

await test('rejects an empty/unreadable buffer without throwing', () => {
  assert.equal(validateRom('x.gb', null).ok, false);
  assert.equal(validateRom('x.gb', new Uint8Array(0)).ok, false);
});

await test('every rejection carries a reason and a human sentence', () => {
  const cases = [
    ['a.png', makeRom()],
    ['a.gb', new Uint8Array(10)],
    ['a.gb', makeRom({ logo: false })],
  ];
  for (const [name, bytes] of cases) {
    const v = validateRom(name, bytes);
    assert.equal(v.ok, false);
    assert.ok(v.reason && v.detail && v.detail.length > 10,
      'expected reason+detail for ' + name);
  }
});

await test('romKey is stable for identical content', async () => {
  // This is the save-persistence guarantee: the same cartridge must produce
  // the same key on a later visit, or its .sav can never be found again.
  const a = makeRom({ title: 'ZELDA' });
  const b = makeRom({ title: 'ZELDA' });
  assert.equal(await romKey(a), await romKey(b));
});

await test('romKey differs for different content', async () => {
  const a = makeRom({ title: 'ZELDA' });
  const b = makeRom({ title: 'METROID' });
  assert.notEqual(await romKey(a), await romKey(b));
});

await test('romKey does not depend on the buffer it is viewed through', async () => {
  // A Uint8Array view over a larger ArrayBuffer must hash only its own bytes,
  // otherwise the key changes with how the file happened to be read.
  const rom = makeRom({ title: 'ZELDA' });
  const backing = new Uint8Array(rom.length + 4096);
  backing.set(rom, 2048);
  const view = backing.subarray(2048, 2048 + rom.length);
  assert.equal(await romKey(rom), await romKey(view));
});

await test('romKey is filesystem-safe', async () => {
  const key = await romKey(makeRom());
  assert.match(key, /^[0-9a-f]+$/);
});

await test('fnv1a64 fallback is stable and content-sensitive', () => {
  const a = makeRom({ title: 'ONE' });
  const b = makeRom({ title: 'TWO' });
  assert.equal(fnv1a64(a), fnv1a64(a.slice()));
  assert.notEqual(fnv1a64(a), fnv1a64(b));
  assert.match(fnv1a64(a), /^[0-9a-f]{16}$/);
});

await test('romTitle reads the header title', () => {
  assert.equal(romTitle(makeRom({ title: 'POKEMON RED' })), 'POKEMON RED');
});

await test('romTitle stops at non-printable bytes (CGB flag reuse)', () => {
  const rom = makeRom({ title: 'GAME' });
  rom[0x138] = 0x80;              // CGB flag territory
  rom[0x139] = 0x41;
  assert.equal(romTitle(rom), 'GAME');
});

await test('romFileName keeps the ROM/save pair keyed to content', () => {
  assert.equal(romFileName('deadbeef', 'x.gbc'), 'chroma_deadbeef.gbc');
  assert.equal(romFileName('deadbeef', 'X.GB'), 'chroma_deadbeef.gb');
  // No timestamp anywhere: that was the bug.
  assert.doesNotMatch(romFileName('deadbeef', 'x.gb'), /\d{10,}/);
});

await test('saveFileName prefers the cart title, falls back to the filename', () => {
  assert.equal(saveFileName(makeRom({ title: 'ZELDA' }), 'whatever.gb'), 'ZELDA.sav');
  assert.equal(saveFileName(makeRom({ title: '' }), 'My Game.gb'), 'My Game.sav');
});

await test('saveFileName strips characters a filesystem would reject', () => {
  const name = saveFileName(makeRom({ title: 'A/B:C' }), 'x.gb');
  assert.doesNotMatch(name, /[/:]/);
});

console.log('\n' + passed + ' checks passed');
if (process.exitCode) console.log('SOME CHECKS FAILED');
