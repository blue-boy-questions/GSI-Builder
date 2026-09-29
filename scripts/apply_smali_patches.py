#!/usr/bin/env python3
"""Apply smali text patches to an apktool-decoded services.jar / framework.jar tree.

Each patch is best-effort and logged. Exit code is always 0 unless --strict and a
REQUIRED patch fails. Designed to be resilient: a missing optional patch does not
abort the whole port build.
"""
import argparse, os, re, sys, glob

def find_smali(root, class_path):
    """class_path like com/android/server/health/HealthRegCallbackAidl.smali
    Search across smali, smali_classes2..N directories."""
    hits = []
    for base in sorted(glob.glob(os.path.join(root, "smali*"))):
        p = os.path.join(base, class_path)
        if os.path.isfile(p):
            hits.append(p)
    return hits

def patch_health_nullguard(root, log):
    """Bail out of HealthRegCallbackAidl.onRegistration when the new SEH service
    (p2) is null, so BatteryService cannot NPE on non-Samsung vendors."""
    cp = "com/android/server/health/HealthRegCallbackAidl.smali"
    files = find_smali(root, cp)
    if not files:
        log.append(f"[health] SKIP: {cp} not found")
        return False
    ok = False
    for f in files:
        s = open(f, encoding="utf-8").read()
        m = re.search(r'(\.method\s+[^\n]*\bonRegistration\([^\n]*\)V\n(?:\s*\.\w[^\n]*\n)*)', s)
        if not m:
            log.append(f"[health] SKIP: onRegistration not found in {f}")
            continue
        header = m.group(1)
        if "seh_nullguard" in s:
            log.append(f"[health] already patched: {f}")
            ok = True
            continue
        guard = ("    if-nez p2, :seh_nullguard\n"
                 "    return-void\n"
                 "    :seh_nullguard\n")
        s2 = s[:m.end()] + guard + s[m.end():]
        open(f, "w", encoding="utf-8").write(s2)
        log.append(f"[health] PATCHED null-guard into {f}")
        ok = True
    return ok

def patch_audio_volume_limit(root, log):
    """Step 10: widen VOLUME_LIMIT_INDEX_EFFECT_ON gate (0x5 -> 0xf) in AudioService."""
    cp = "com/android/server/audio/AudioService.smali"
    files = find_smali(root, cp)
    if not files:
        log.append(f"[audio] SKIP: {cp} not found")
        return False
    ok = False
    for f in files:
        s = open(f, encoding="utf-8").read()
        # The clinit builds VOLUME_LIMIT_INDEX_EFFECT_ON via an array-data block.
        # Find array-data blocks and flip a lone 0x5 element to 0xf. To stay safe we
        # only touch an array-data payload that contains exactly the value 0x5.
        def repl(mm):
            body = mm.group(0)
            if re.search(r'^\s*0x5\s*$', body, re.M):
                new = re.sub(r'(^\s*)0x5(\s*$)', r'\g<1>0xf\g<2>', body, flags=re.M)
                return new
            return body
        s2 = re.sub(r'\.array-data 4\n.*?\.end array-data', repl, s, flags=re.S)
        if s2 != s:
            open(f, "w", encoding="utf-8").write(s2)
            log.append(f"[audio] PATCHED VOLUME_LIMIT 0x5->0xf in {f}")
            ok = True
        else:
            log.append(f"[audio] no matching 0x5 array-data in {f} (may already be patched)")
    return ok

def patch_usb_mtp(root, log):
    """Step 11: mirror mCurrentFunctions into mSecCurrentFunctions in setEnabledFunctions."""
    cp = "com/android/server/usb/UsbDeviceManager$UsbHandlerHal.smali"
    files = find_smali(root, cp)
    if not files:
        log.append(f"[usb] SKIP: {cp} not found")
        return False
    ok = False
    needle = ("iput-wide p2, p0, Lcom/android/server/usb/UsbDeviceManager$UsbHandler;"
              "->mCurrentFunctions:J")
    add = ("iput-wide p2, p0, Lcom/android/server/usb/UsbDeviceManager$UsbHandler;"
           "->mSecCurrentFunctions:J")
    for f in files:
        s = open(f, encoding="utf-8").read()
        if add in s:
            log.append(f"[usb] already patched: {f}")
            ok = True; continue
        if needle in s:
            s2 = s.replace(needle, add + "\n\n    " + needle, 1)
            open(f, "w", encoding="utf-8").write(s2)
            log.append(f"[usb] PATCHED mSecCurrentFunctions mirror in {f}")
            ok = True
        else:
            log.append(f"[usb] needle not found in {f}")
    return ok

PATCHES = {
    "health": patch_health_nullguard,
    "audio":  patch_audio_volume_limit,
    "usb":    patch_usb_mtp,
}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="apktool-decoded jar dir")
    ap.add_argument("--patches", required=True, help="comma list: health,audio,usb")
    ap.add_argument("--require", default="", help="comma list of patches that MUST apply")
    args = ap.parse_args()
    log = []
    required = set(x for x in args.require.split(",") if x)
    results = {}
    for name in [x for x in args.patches.split(",") if x]:
        fn = PATCHES.get(name)
        if not fn:
            log.append(f"[{name}] UNKNOWN patch"); results[name]=False; continue
        results[name] = fn(args.root, log)
    print("\n".join(log))
    failed_required = [n for n in required if not results.get(n)]
    if failed_required:
        print(f"REQUIRED PATCHES FAILED: {failed_required}", file=sys.stderr)
        sys.exit(2)
    print("PATCH SUMMARY:", results)

if __name__ == "__main__":
    main()
