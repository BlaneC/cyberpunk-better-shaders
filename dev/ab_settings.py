#!/usr/bin/env python3
"""Pin the game settings that were in force for a capture set — by timestamp.

The game writes UserSettings.json on **Apply**, while it is running (proven
2026-08-30 18:05:41, game still up; handoff/49 §0.1). So the file's mtime
against the capture mtimes decides the question outright:

    settings written BEFORE the first capture -> the file IS the capture state
    settings written BETWEEN captures         -> the set straddles a change
    settings written AFTER the last capture   -> a change landed post-shoot,
                                                 and the live file no longer
                                                 shows what was on screen

Only the third case needs a snapshot taken earlier — `pre`, or the
`UserSettings.atshoot.json` that `check` drops the first time it can prove a
set is pinned.

    dev/ab_settings.py show                 # current critical keys
    dev/ab_settings.py pre   <rung-dir>     # optional: before launching
    dev/ab_settings.py check <rung-dir>     # after the shoot; prints verdict
"""
import json, shutil, sys, os, glob, datetime

US = ("/mnt/f4333173-dd02-4314-9fd0-2ce547a9ba73/SteamLibrary/steamapps/compatdata/"
      "1091500/pfx/drive_c/users/steamuser/AppData/Local/CD Projekt Red/"
      "Cyberpunk 2077/UserSettings.json")

# The keys that change what a capture means.
CRITICAL = ["RayTracedPathTracing", "RayTracedPathTracingForPhotoMode", "DLSS_D",
            "DLSS", "DLSS_NewSharpness", "RayTracedLighting", "RayTracedReflections",
            "RayTracedSunShadows", "RayTracedLocalShadows", "Resolution",
            "TextureQuality", "FieldOfView"]
LABEL = {"DLSS_D": "Ray Reconstruction", "DLSS": "DLSS quality",
         "RayTracedPathTracing": "Path Tracing",
         "RayTracedPathTracingForPhotoMode": "PT in photo mode"}
ATSHOOT = "UserSettings.atshoot.json"
PRE = "UserSettings.pre.json"


def options(path):
    out = {}
    def walk(o):
        if isinstance(o, dict):
            n = o.get("name")
            if isinstance(n, str) and "value" in o:
                out[n] = o["value"]
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(json.load(open(path)))
    return out


def hhmmss(t):
    return datetime.datetime.fromtimestamp(t).strftime("%H:%M:%S")


def show(opts, src):
    print(f"settings in force ({src}):")
    for k in CRITICAL:
        if k in opts:
            print(f"  {LABEL.get(k, k):32s} = {opts[k]}")


def diff(a, b):
    return {k: (a.get(k), b.get(k))
            for k in set(a) | set(b) if a.get(k) != b.get(k)}


def check(dest):
    shots = sorted(glob.glob(os.path.join(dest, "S*.png")))
    if not shots:
        sys.exit(f"no S*.png captures in {dest}")
    times = {os.path.basename(p): os.path.getmtime(p) for p in shots}
    first, last = min(times.values()), max(times.values())
    ts = os.path.getmtime(US)

    for n, t in sorted(times.items(), key=lambda kv: kv[1]):
        print(f"  {n:8s} {hhmmss(t)}")
    print(f"  {'settings':8s} {hhmmss(ts)}  (UserSettings.json last written)")
    print()

    if ts < first:
        # The live file is the capture state. Freeze it so a later exit or
        # Apply write cannot take the proof away.
        if not os.path.exists(os.path.join(dest, ATSHOOT)):
            shutil.copy2(US, os.path.join(dest, ATSHOOT))
        print(f"PINNED -- settings last changed {hhmmss(ts)}, "
              f"{int(first - ts)}s before the first capture.")
        print("No settings change during the shoot; this set is proven, not trusted.")
        show(options(US), "live file, frozen into " + ATSHOOT)
        return 0

    if ts <= last:
        print("*** SUSPECT -- a settings change landed BETWEEN captures ***")
        print(f"    {hhmmss(first)} .. {hhmmss(ts)} .. {hhmmss(last)}")
        for n, t in sorted(times.items(), key=lambda kv: kv[1]):
            print(f"    {n}: {'BEFORE' if t < ts else 'AFTER'} the change")
        print("    Re-shoot, or record which scenes fall on which side.")
        show(options(US), "post-change; the earlier scenes did NOT use this")
        return 1

    # ts > last: something moved after the shoot; the live file is not it.
    for name in (ATSHOOT, PRE):
        p = os.path.join(dest, name)
        if os.path.exists(p):
            was, now = options(p), options(US)
            moved = diff(was, now)
            crit = {k: v for k, v in moved.items() if k in CRITICAL}
            print(f"PINNED via {name} -- settings changed {hhmmss(ts)}, after the "
                  f"last capture at {hhmmss(last)}, so the live file is stale.")
            show(was, name)
            if crit:
                print("\n  changed after the shoot (does not affect these captures):")
                for k, (a, b) in sorted(crit.items()):
                    print(f"    {LABEL.get(k, k):30s} {a!r} -> {b!r}")
            return 0
    note = os.path.join(dest, "PINNING.md")
    if os.path.exists(note):
        print(f"settings changed {hhmmss(ts)}, after the last capture at "
              f"{hhmmss(last)} -- so the live file is stale and no snapshot "
              f"predates the shoot.")
        print(f"See {note} for how this rung's state was established.")
        return 0
    print("*** UNPINNED -- settings changed after the last capture and no "
          "earlier snapshot exists. ***")
    print(f"    last capture {hhmmss(last)}, settings written {hhmmss(ts)}.")
    print("    The live file shows post-change state. Capture state unknown;")
    print(f"    run `{sys.argv[0]} pre <dir>` before the next launch.")
    show(options(US), "live file -- POST-change, NOT the capture state")
    return 2


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cmd = sys.argv[1]
    if not os.path.exists(US):
        sys.exit(f"UserSettings.json not found at {US}")
    if cmd == "show":
        show(options(US), f"live, written {hhmmss(os.path.getmtime(US))}")
        return 0
    if len(sys.argv) < 3:
        sys.exit(f"usage: {sys.argv[0]} {cmd} <rung-dir>")
    dest = sys.argv[2]
    if not os.path.isdir(dest):
        sys.exit(f"no such rung dir: {dest}")
    if cmd == "pre":
        shutil.copy2(US, os.path.join(dest, PRE))
        show(options(US), f"pre-launch; game loads this at startup")
        print(f"\nsnapshot -> {dest}/{PRE}")
        return 0
    if cmd == "check":
        return check(dest)
    sys.exit(f"unknown command: {cmd}")


if __name__ == "__main__":
    sys.exit(main() or 0)
