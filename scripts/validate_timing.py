#!/usr/bin/env python3
"""Validate GBC CPU instruction timing against Pan Docs reference.

Parses fetch costs from gbz80.s/io.s and compares to expected cycle counts.
Exits with error if any mismatches found.
"""

import re
import sys
import os

# Pan Docs reference timing (clock cycles per instruction)
# Conditional branches list (not_taken, taken) — we check not_taken base cost
EXPECTED = {
    # 8-bit loads: LD r,n
    0x06: 8, 0x0E: 8, 0x16: 8, 0x1E: 8, 0x26: 8, 0x2E: 8, 0x3E: 8,
    # LD r,r (0x40-0x7F except 0x76=HALT and (HL) variants)
    **{op: 4 for op in range(0x40, 0x80)
       if op != 0x76 and (op & 0x07) != 6 and (op & 0x38) != 0x30},
    # LD r,(HL)
    0x46: 8, 0x4E: 8, 0x56: 8, 0x5E: 8, 0x66: 8, 0x6E: 8, 0x7E: 8,
    # LD (HL),r
    0x70: 8, 0x71: 8, 0x72: 8, 0x73: 8, 0x74: 8, 0x75: 8, 0x77: 8,
    0x36: 12,  # LD (HL),n
    0x0A: 8, 0x1A: 8, 0xFA: 16,  # LD A,(BC/DE/nn)
    0x02: 8, 0x12: 8, 0xEA: 16,  # LD (BC/DE/nn),A
    0xF2: 8, 0xE2: 8,  # LD A,(C) / LD (C),A
    0xF0: 12, 0xE0: 12,  # LDH A,(n) / LDH (n),A
    0x22: 8, 0x2A: 8, 0x32: 8, 0x3A: 8,  # LDI/LDD
    # 16-bit loads
    0x01: 12, 0x11: 12, 0x21: 12, 0x31: 12,  # LD rr,nn
    0xF9: 8,   # LD SP,HL
    0x08: 20,  # LD (nn),SP
    0xC5: 16, 0xD5: 16, 0xE5: 16, 0xF5: 16,  # PUSH
    0xC1: 12, 0xD1: 12, 0xE1: 12, 0xF1: 12,  # POP
    0xF8: 12,  # LD HL,SP+n
    # ALU r
    **{op: 4 for op in range(0x80, 0xC0) if (op & 0x07) != 6},
    # ALU (HL)
    0x86: 8, 0x8E: 8, 0x96: 8, 0x9E: 8, 0xA6: 8, 0xAE: 8, 0xB6: 8, 0xBE: 8,
    # ALU n
    0xC6: 8, 0xCE: 8, 0xD6: 8, 0xDE: 8, 0xE6: 8, 0xEE: 8, 0xF6: 8, 0xFE: 8,
    # INC/DEC r
    0x04: 4, 0x0C: 4, 0x14: 4, 0x1C: 4, 0x24: 4, 0x2C: 4, 0x34: 12, 0x3C: 4,
    0x05: 4, 0x0D: 4, 0x15: 4, 0x1D: 4, 0x25: 4, 0x2D: 4, 0x35: 12, 0x3D: 4,
    # INC/DEC rr
    0x03: 8, 0x13: 8, 0x23: 8, 0x33: 8,
    0x0B: 8, 0x1B: 8, 0x2B: 8, 0x3B: 8,
    # ADD HL,rr
    0x09: 8, 0x19: 8, 0x29: 8, 0x39: 8,
    0xE8: 16,  # ADD SP,n
    # Rotates (non-CB)
    0x07: 4, 0x0F: 4, 0x17: 4, 0x1F: 4,
    # Control
    0x00: 4, 0x76: 4, 0x10: 4, 0xF3: 4, 0xFB: 4,
    0x27: 4, 0x2F: 4, 0x37: 4, 0x3F: 4,
    # Jumps
    0xC3: 16, 0xE9: 4,
    0xC2: 12, 0xCA: 12, 0xD2: 12, 0xDA: 12,  # JP cc (not taken)
    0x18: 12,  # JR n
    0x20: 8, 0x28: 8, 0x30: 8, 0x38: 8,  # JR cc (not taken)
    # Calls/returns
    0xCD: 24,
    0xC4: 12, 0xCC: 12, 0xD4: 12, 0xDC: 12,  # CALL cc (not taken)
    0xC9: 16, 0xD9: 16,  # RET, RETI
    0xC0: 8, 0xC8: 8, 0xD0: 8, 0xD8: 8,  # RET cc (not taken)
    # RST
    0xC7: 16, 0xCF: 16, 0xD7: 16, 0xDF: 16,
    0xE7: 16, 0xEF: 16, 0xF7: 16, 0xFF: 16,
}


def parse_fetch_costs(filename):
    """Parse opcode handlers and their first fetch cost."""
    costs = {}
    current_op = None
    with open(filename) as f:
        for line in f:
            # New opcode label resets the current tracking
            m = re.match(r'^_([0-9A-Fa-f]{2}[0-9A-Fa-f]*):', line)
            if m:
                hex_str = m.group(1)
                if len(hex_str) == 2:
                    current_op = int(hex_str, 16)
                else:
                    current_op = None  # CB-prefix or other, stop tracking
            m = re.search(r'fetch\s+(\d+)', line)
            if m and current_op is not None:
                if current_op not in costs:
                    costs[current_op] = int(m.group(1))
                current_op = None
    return costs


def parse_macro_fetch(filename, macro_name):
    """Parse fetch cost from a macro definition."""
    in_macro = False
    with open(filename) as f:
        for line in f:
            if f'.macro {macro_name}' in line:
                in_macro = True
            elif in_macro:
                m = re.search(r'fetch\s+(\d+)', line)
                if m:
                    return int(m.group(1))
                if '.endm' in line:
                    in_macro = False
    return None


def main():
    src_dir = os.path.join(os.path.dirname(__file__), '..', 'src')

    # Parse fetch costs from all source files
    actual = {}
    for fname in ['gbz80.s', 'io.s']:
        path = os.path.join(src_dir, fname)
        if os.path.exists(path):
            actual.update(parse_fetch_costs(path))

    # Some opcodes use macros that contain the fetch
    mac_path = os.path.join(src_dir, 'gbz80mac.h')
    if os.path.exists(mac_path):
        # CP A uses opCPA macro
        cpa_cost = parse_macro_fetch(mac_path, 'opCPA')
        if cpa_cost and 0xBF not in actual:
            actual[0xBF] = cpa_cost

    # Compare
    errors = []
    checked = 0
    for op in sorted(EXPECTED):
        exp = EXPECTED[op]
        act = actual.get(op)
        if act is None:
            continue
        checked += 1
        if act != exp:
            errors.append((op, exp, act))

    print(f"=== Instruction Timing Validation ===")
    print(f"  Checked {checked}/{len(EXPECTED)} opcodes")

    if errors:
        print(f"  FOUND {len(errors)} TIMING ERROR(S):")
        for op, exp, act in errors:
            print(f"    0x{op:02X}: expected {exp}, actual {act} ({act-exp:+d} cycles)")
        sys.exit(1)
    else:
        print(f"  All timings correct")


if __name__ == '__main__':
    main()
