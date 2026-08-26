#!/usr/bin/env python3
"""Triage a CALLISTO_DUMP_DIR: which modules look like the PT reference raygen?

The dispatched PT raygen turned out to be a whole-library module whose
OpString is just "<hash>.dxil" (no entry name), so the named-permutation
swaps never matched it. This script disassembles every dump and ranks
candidates by the known reference-eval signatures:

  - the 1/pi diffuse constant 0.318309873 at the eval triples
  - the Disney-diffuse anchor 0.107508637 (direct lights)
  - the G-buffer material-class extraction (>> 5, OpIEqual == 1 = skin test)
  - entry points (a whole-library module lists several; names may name rgs)

Usage: dev/scan_dump.py [dumpdir]     (default ~/callisto_dump)
"""
import os, re, subprocess, sys, tempfile

DUMP = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/callisto_dump")

rows = []
for fn in sorted(os.listdir(DUMP)):
    if not fn.endswith(".spv"):
        continue
    path = os.path.join(DUMP, fn)
    size = os.path.getsize(path)
    with tempfile.NamedTemporaryFile(suffix=".spvasm", delete=False) as t:
        tmp = t.name
    try:
        r = subprocess.run(["spirv-dis", path, "-o", tmp], capture_output=True)
        if r.returncode != 0:
            rows.append((fn, size, -1, 0, 0, False, "spirv-dis FAILED"))
            continue
        text = open(tmp, errors="replace").read()
    finally:
        os.unlink(tmp)
    entries = re.findall(r'OpEntryPoint\s+(\w+)\s+%\w+\s+"([^"]+)"', text)
    pi = text.count("0.318309873")
    disney = text.count("0.107508637")
    # class extraction: shift right by 5 of a uint, fed to OpIEqual against 1
    shifts = re.findall(r'(%\d+)\s*=\s*OpShiftRightLogical %uint %\d+ %uint_5\b', text)
    gate = any(re.search(r'%\d+\s*=\s*OpIEqual %bool ' + re.escape(s) + r' %uint_1\b', text)
               for s in shifts)
    models = {}
    for model, _name in entries:
        models[model] = models.get(model, 0) + 1
    ents = " ".join(f"{m}x{c}" for m, c in sorted(models.items()))
    rows.append((fn, size, len(entries), pi, disney, gate, ents))

# rank: reference eval has several 1/pi sites + the Disney anchor + the gate
def score(row):
    _, _, nent, pi, disney, gate, _ = row
    if nent < 0: return -1
    return (3 if gate else 0) + (2 if disney else 0) + min(pi, 6)

rows.sort(key=lambda r: (score(r), r[1]), reverse=True)
print(f"{"module":<44} {"bytes":>8} {"ent":>4} {"1/pi":>5} {"dny":>4} {"gate":>5}  entry models")
for fn, size, nent, pi, disney, gate, rgs in rows[:25]:
    print(f"{fn:<44} {size:>8} {nent:>4} {pi:>5} {disney:>4} {str(gate):>5}  {rgs}")
print(f"\n{len(rows)} modules scanned. Top candidates are the patch targets;")
print("expect ~300 KB, several 1/pi sites, Disney anchor present, gate True.")
