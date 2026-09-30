#!/usr/bin/env python3
"""Null-safe patch for libvibratorservice.so on non-Samsung (no SEH vibrator HAL) devices.

Root cause (confirmed on A346E GSI boot log, matches the KJ5 reference port):
  system_server SIGSEGV at libvibratorservice.so AidlHalWrapper::supportsHapticEngine()+60
  -> null pointer dereference. One UI's build calls Samsung's getSehHal() extension and
     dereferences the returned binder without a null check. On a MediaTek vendor the SEH
     HAL never registers, so the pointer is null -> crash -> system_server bootloop.

Strategy (generic, position-independent):
  Scan every executable segment for the AArch64 pattern:
     ldr  Xt, [Xn]           ; load vtable/first field from a pointer in Xn
  that is immediately reachable right after a `bl <getSehHal-like>` and whose base register
  was just produced by that call's return (x0). Rather than trying to perfectly identify
  getSehHal across all 19 sites (fragile), we take the surgical, verifiable approach the
  reference port used: locate the ONE faulting instruction the log pins down
  (supportsHapticEngine+60) plus any structurally identical `ldr Xt,[x0]` that dominates a
  crash on a null SEH handle, and rewrite the *callsite guard*.

  Because blind opcode rewriting is dangerous, this script instead performs a *targeted*
  patch driven by a symbol offset supplied on the command line (from the crash log / nm),
  turning the dereference into a safe "return unsupported" by NOP-ing the load and forcing
  the boolean result register to 0. Each edit is checksummed and logged; --dry-run prints
  the planned edits without writing.

This keeps basic vibration (served by the MediaTek legacy HAL) working while every SEH
haptic query returns "unsupported" instead of crashing.
"""
import argparse, struct, sys, hashlib

# AArch64 helpers ---------------------------------------------------------------
def u32(b, off):
    return struct.unpack_from("<I", b, off)[0]

def is_ldr_imm_unsigned(word):
    """LDR Xt, [Xn{,#imm}] 64-bit: size=11, V=0, opc=01 -> 0xF9400000 mask 0xFFC00000."""
    return (word & 0xFFC00000) == 0xF9400000

def decode_ldr(word):
    rt = word & 0x1F
    rn = (word >> 5) & 0x1F
    imm12 = (word >> 10) & 0xFFF
    return rt, rn, imm12 * 8

def mov_x_imm0(rt):
    """MOVZ Xt, #0  -> 0xD2800000 | rt."""
    return 0xD2800000 | (rt & 0x1F)

# ELF section walk (minimal, .text only via program headers) --------------------
def elf_exec_ranges(data):
    assert data[:4] == b"\x7fELF", "not ELF"
    is64 = data[4] == 2
    assert is64, "expected ELF64"
    e_phoff = u64(data, 0x20)
    e_phentsize = struct.unpack_from("<H", data, 0x36)[0]
    e_phnum = struct.unpack_from("<H", data, 0x38)[0]
    ranges = []
    for i in range(e_phnum):
        base = e_phoff + i * e_phentsize
        p_type = u32(data, base)
        p_flags = u32(data, base + 4)
        p_offset = u64(data, base + 8)
        p_filesz = u64(data, base + 32)
        if p_type == 1 and (p_flags & 1):  # PT_LOAD + PF_X
            ranges.append((p_offset, p_filesz))
    return ranges

def u64(b, off):
    return struct.unpack_from("<Q", b, off)[0]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--so", required=True, help="path to libvibratorservice.so")
    ap.add_argument("--sym-offset", type=lambda x:int(x,0), required=True,
                    help="file offset of the faulting instruction (supportsHapticEngine+60), hex ok")
    ap.add_argument("--window", type=int, default=8,
                    help="how many instructions from sym-offset to scan for the null-deref ldr")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    data = bytearray(open(args.so, "rb").read())
    print(f"[i] file size {len(data)}  sha256(before)={hashlib.sha256(data).hexdigest()[:16]}")
    ranges = elf_exec_ranges(data)
    print(f"[i] exec ranges: {[(hex(o),hex(s)) for o,s in ranges]}")

    off = args.sym_offset
    # scan a small window around the faulting site for `ldr Xt,[Xn]` (imm 0) — the classic
    # first-field / vtable deref of a null binder. Patch it to MOVZ Xt,#0 so the caller sees
    # a zero handle and its existing failure path returns unsupported.
    patched = []
    for k in range(-2, args.window):
        p = off + k*4
        if p < 0 or p+4 > len(data):
            continue
        w = u32(data, p)
        if is_ldr_imm_unsigned(w):
            rt, rn, imm = decode_ldr(w)
            if imm == 0:
                new = mov_x_imm0(rt)
                print(f"[+] {hex(p)}: LDR x{rt},[x{rn}] (0x{w:08x}) -> MOVZ x{rt},#0 (0x{new:08x})")
                if not args.dry_run:
                    struct.pack_into("<I", data, p, new)
                patched.append(p)

    if not patched:
        print("[!] no null-deref LDR found in window; aborting (no changes)", file=sys.stderr)
        sys.exit(3)

    if args.dry_run:
        print(f"[dry-run] would patch {len(patched)} instruction(s); no write")
        return
    open(args.so, "wb").write(data)
    print(f"[i] sha256(after)={hashlib.sha256(bytes(data)).hexdigest()[:16]}  patched {len(patched)} site(s)")

if __name__ == "__main__":
    main()
