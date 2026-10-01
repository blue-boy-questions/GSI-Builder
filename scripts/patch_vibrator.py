#!/usr/bin/env python3
"""Deterministic null-safe patch for libvibratorservice.so (A346E / algiz GSI port).

Confirmed on the A346E GSI boot log (matches the KJ5 reference port, bug #2):
  system_server SIGSEGV, fault addr 0x0, at
  libvibratorservice.so  AidlHalWrapper::supportsHapticEngine()+60

Disassembly of supportsHapticEngine (va 0x17250) shows:
  0x17280: bl   #0x20a80       ; obtain the SEH HAL handle
  0x17284: ldr  x0, [sp,#8]    ; x0 = handle (ALWAYS null on a non-Samsung MTK vendor)
  0x17288: sub  x1, x29,#0xc
  0x1728c: ldr  x8, [x0]       ; <-- crash: dereference null x0
  ...
  0x17310:                     ; clean "unsupported / empty HalResult" return path
                               ; (sp+0x18 was already zeroed at 0x1727c)

Patch: replace the faulting  `ldr x8,[x0]` (080040f9) at file-offset 0x1728c with
`cbz x0, #0x17310` (200400b4). On algiz the SEH handle is always null, so the branch
is always taken into the existing unsupported-return path -> no deref, no crash, basic
MediaTek vibration keeps working.

This is a surgical 4-byte in-place edit: file size is unchanged. The script refuses to
run unless the original bytes match exactly (guards against a different build/offset).
"""
import argparse, struct, sys, hashlib

PATCH_OFFSET = 0x1728C
ORIG_BYTES   = bytes.fromhex("080040f9")   # ldr x8, [x0]
# cbz x0, #0x17310  (computed + capstone-verified)
NEW_BYTES    = bytes.fromhex("200400b4")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--so", required=True, help="path to libvibratorservice.so")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    data = bytearray(open(args.so, "rb").read())
    before = hashlib.sha256(data).hexdigest()
    print(f"[i] size={len(data)}  sha256(before)={before}")

    cur = bytes(data[PATCH_OFFSET:PATCH_OFFSET+4])
    if cur == NEW_BYTES:
        print("[=] already patched; nothing to do")
        return
    if cur != ORIG_BYTES:
        print(f"[!] REFUSING: bytes at {PATCH_OFFSET:#x} are {cur.hex()}, "
              f"expected {ORIG_BYTES.hex()} (wrong build/offset)", file=sys.stderr)
        sys.exit(3)

    print(f"[+] {PATCH_OFFSET:#x}: {cur.hex()} (ldr x8,[x0]) -> {NEW_BYTES.hex()} (cbz x0,#0x17310)")
    if args.dry_run:
        print("[dry-run] no write")
        return
    data[PATCH_OFFSET:PATCH_OFFSET+4] = NEW_BYTES
    open(args.so, "wb").write(data)
    after = hashlib.sha256(data).hexdigest()
    print(f"[i] sha256(after)={after}  size={len(data)} (unchanged)")

if __name__ == "__main__":
    main()
