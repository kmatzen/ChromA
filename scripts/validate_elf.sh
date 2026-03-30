#!/bin/bash
# Validate ELF memory layout constraints before creating GBA ROM.
# Called from Makefile after linking, fails the build if constraints are violated.

set -e

ELF="$1"
if [ -z "$ELF" ] || [ ! -f "$ELF" ]; then
    echo "Usage: validate_elf.sh <path-to-elf>"
    exit 1
fi

SIZE=$(which arm-none-eabi-size 2>/dev/null || echo "${DEVKITARM}/bin/arm-none-eabi-size")
OBJDUMP=$(which arm-none-eabi-objdump 2>/dev/null || echo "${DEVKITARM}/bin/arm-none-eabi-objdump")

ERRORS=0

# Parse section sizes
eval $($OBJDUMP -h "$ELF" | awk '
    /\.iwram / && !/iwram[0-9]/ { printf "IWRAM_CODE=0x%s\n", $3 }
    /\.bss /                     { printf "IWRAM_BSS=0x%s\n", $3 }
    /\.sbss /                    { printf "EWRAM_BSS=0x%s\n", $3 }
    /\.vram1 /                   { printf "VRAM1_CODE=0x%s\n", $3 }
')

IWRAM_CODE=$((IWRAM_CODE))
IWRAM_BSS=$((IWRAM_BSS))
EWRAM_BSS=$((EWRAM_BSS))
VRAM1_CODE=$((VRAM1_CODE))

IWRAM_TOTAL=$((IWRAM_CODE + IWRAM_BSS))
IWRAM_LIMIT=32512  # 32KB minus 256 bytes minimum for stack + IRQ
IWRAM_STACK=$((32768 - IWRAM_TOTAL))

EWRAM_LIMIT=262144  # 256KB
VRAM1_LIMIT=4096    # 4KB

echo "=== Memory Validation ==="
echo "  IWRAM: code=${IWRAM_CODE} bss=${IWRAM_BSS} total=${IWRAM_TOTAL} stack=${IWRAM_STACK}"
echo "  EWRAM BSS: ${EWRAM_BSS}"
echo "  VRAM1: ${VRAM1_CODE}"

# Check IWRAM
if [ $IWRAM_TOTAL -gt $IWRAM_LIMIT ]; then
    echo "ERROR: IWRAM overflow! ${IWRAM_TOTAL} > ${IWRAM_LIMIT} (stack would be < 512 bytes)"
    ERRORS=$((ERRORS + 1))
fi
if [ $IWRAM_STACK -lt 256 ]; then
    echo "ERROR: IWRAM stack critically low! Only ${IWRAM_STACK} bytes"
    ERRORS=$((ERRORS + 1))
elif [ $IWRAM_STACK -lt 400 ]; then
    echo "WARNING: IWRAM stack tight: ${IWRAM_STACK} bytes"
fi

# Check EWRAM
if [ $EWRAM_BSS -gt $EWRAM_LIMIT ]; then
    echo "ERROR: EWRAM overflow! ${EWRAM_BSS} > ${EWRAM_LIMIT}"
    ERRORS=$((ERRORS + 1))
fi

# Check VRAM1
if [ $VRAM1_CODE -gt $VRAM1_LIMIT ]; then
    echo "ERROR: VRAM1 overflow! ${VRAM1_CODE} > ${VRAM1_LIMIT}"
    ERRORS=$((ERRORS + 1))
fi

if [ $ERRORS -gt 0 ]; then
    echo "FAILED: ${ERRORS} constraint violation(s)"
    exit 1
fi

echo "  All constraints OK"
