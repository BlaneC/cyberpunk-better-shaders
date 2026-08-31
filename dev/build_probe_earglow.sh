#!/usr/bin/env bash
# Ear-glow gate-attribution PROBE (handoff/66; scores 65's two-suspect split):
# NOTE: since v4 (handoff/68) the shared patcher emits the v4 one-sided
# consistency gate and albedo 0.25 -- a REBUILD of this probe measures the
# v4 gates. The rung PARKED from the 66 build still carries the v3 gates
# (|Delta|^2 < (5mm)^2, albedo 0.10) -- 67's readings are against those.
# the v3 gate chain evaluated per pixel, but every gate measured
# INDEPENDENTLY (thickness trace fires on class+backlit+bounce0, vis ray on
# that + thin-hit) and the Beer-Lambert glow replaced by an additive
# one-hue-per-pixel paint:
#   MAGENTA (3.2,0,3.2)  thin-hit valid, sun-vis ray FAILS
#   YELLOW  (3.2,3.2,0)  vis passes, consistency AND albedo fail
#   RED     (3.2,0,0)    consistency fails only
#   GREEN   (0,3.2,0)    albedo fails only
#   BLUE    (0,0.4,3.2)  all pass (v3's surviving glow set)
#   nothing              class/backlit/bounce0/thin-hit never fired
# Palette AgX-checked (66 sec 2): dead channels exact 0.0, coordinator's 0.1
# floors dropped -- they only fed AgX inset crosstalk.
#
#   ./dev/build_probe_earglow.sh              # build + verify (no install)
#   ./dev/build_probe_earglow.sh --install    # ALSO park as skin.set/probe-earglow
#
# Selection is the PROBE path (40 sec 7): hand-edit brdf_params.txt to
# skinspec=probe-earglow before EVERY launch (init.lua coerces unknown names
# back to off afterwards -- expected, not a fault). NO init.lua change, NO CET
# registration. Contract unchanged from gi-50-bleed: ser=class,
# shadowset=full-shadow, ptreg ON (rcbm combo, 55 sec 5) -- MANIFEST
# provenance carries over verbatim so sync's gi_refuse holds.
set -euo pipefail

MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="${CALLISTO_INSTALL_DIR:-$HOME/.local/lib/callisto}"
GI="$INSTALL_DIR/skin.set/gi-50-bleed"
WORK="$MOD_DIR/dev/disasm/earglow"
PY="$MOD_DIR/dev/patch_earglow.py"
NAME=probe-earglow

DO_INSTALL=0
[[ "${1:-}" == "--install" ]] && DO_INSTALL=1

PASS=(40c6faab52a13874 ab7f1822eeb0331b)

[[ -f "$GI/MANIFEST.txt" ]] || { echo "no $GI/MANIFEST.txt -- run ./dev/build_gi_bleed.sh --install first" >&2; exit 1; }

mapfile -t REFS < <(cd "$GI" && ls *.rgs_reference_main.spv | sed 's/\..*//')
(( ${#REFS[@]} == 12 )) || { echo "gi-50-bleed has ${#REFS[@]} rgs_reference_main, expected 12" >&2; exit 1; }
TARGETS=()
for h in "${REFS[@]}"; do
    skip=0
    for p in "${PASS[@]}"; do [[ "$h" == "$p" ]] && skip=1; done
    (( skip )) || TARGETS+=("$h")
done
(( ${#TARGETS[@]} == 10 )) || { echo "expected 10 paintable refs, have ${#TARGETS[@]}" >&2; exit 1; }

rm -rf "$WORK"
mkdir -p "$WORK"
for h in "${TARGETS[@]}"; do
    spirv-dis "$GI/$h.rgs_reference_main.spv" -o "$WORK/$h.rgs_reference_main.spvasm"
done

jobs="${CALLISTO_JOBS:-$(nproc 2>/dev/null || echo 4)}"

dest="$MOD_DIR/swaps.$NAME"
rm -rf "$dest"; mkdir -p "$dest"
printf '%s\0' "${TARGETS[@]}" | CB_D="$dest" CB_P="$PY" CB_W="$WORK" \
    xargs -0 -P "$jobs" -n1 bash -c '
        python3 "$CB_P" "$CB_W/$0.rgs_reference_main.spvasm" --k 0 --probe \
            --outdir "$CB_D" > "$CB_D/$0.rgs.report.json"'
# verbatim halves
cp -pf "$GI"/*.dxil.spv "$dest/"
cp -pf "$GI"/*.rgs_restirgi_*.spv "$dest/"
for p in "${PASS[@]}"; do cp -pf "$GI/$p.rgs_reference_main.spv" "$dest/"; done
for f in "$GI"/*.dxil.spv "$GI"/*.rgs_restirgi_*.spv; do
    cmp -s "$f" "$dest/$(basename "$f")" || { echo "verbatim copy differs: $f" >&2; exit 1; }
done
for h in "${TARGETS[@]}"; do
    cmp -s "$GI/$h.rgs_reference_main.spv" "$dest/$h.rgs_reference_main.spv" \
        && { echo "$NAME: $h is byte-identical to base -- splice emitted nothing" >&2; exit 1; }
done
for f in "$dest"/*.spv; do
    spirv-val "$f" || { echo "spirv-val FAILED: $f" >&2; exit 1; }
done
# emitted-instruction re-read from the OUTPUT binaries (39 sec 3.4),
# baseline-aware throughout
python3 - "$dest" "$GI" << 'PYV'
import re, subprocess, sys, glob, os
dest, base = sys.argv[1], sys.argv[2]
PASS = ('40c6faab52a13874', 'ab7f1822eeb0331b')
fails = []
for f in sorted(glob.glob(os.path.join(dest, '*.rgs_reference_main.spv'))):
    h = os.path.basename(f).split('.')[0]
    if h in PASS:
        continue
    asm = subprocess.run(['spirv-dis', f], capture_output=True, text=True).stdout
    van = subprocess.run(['spirv-dis', os.path.join(base, os.path.basename(f))],
                         capture_output=True, text=True).stdout
    traces = re.findall(r'OpTraceRayKHR (.+)', asm)
    if len(traces) != van.count('OpTraceRayKHR') + 2:
        fails.append(f'{h}: trace count {len(traces)} != base+2 (thickness+visibility)'); continue
    inj = [t for t in traces if t.split()[1] == '%uint_16']
    if len(inj) != 1:
        fails.append(f'{h}: {len(inj)} flags-16 injected traces, expected 1'); continue
    tmax = inj[0].split()[9]
    m = re.search(re.escape(tmax) + r' = OpConstant %float ([0-9.e+-]+)', asm)
    if not m or abs(float(m.group(1)) - 0.018) > 1e-6:
        fails.append(f'{h}: injected tmax {tmax} is not 0.018'); continue
    van12 = len([t for t in re.findall(r'OpTraceRayKHR (.+)', van)
                 if t.split()[1] == '%uint_12'])
    now12 = [t for t in traces if t.split()[1] == '%uint_12']
    if len(now12) != van12 + 1:
        fails.append(f'{h}: flags-12 trace count {len(now12)} != base+1')
    ipay = inj[0].split()[10]
    vist = [t for t in now12
            if t.split()[9] == '%float_10000' and t.split()[10] == ipay]
    if len(vist) != 1:
        fails.append(f'{h}: visibility trace (flags 12, tmax 10000, injected payload) not found')
    if len(re.findall(r'OpSelect %uint %\w+ %uint_39 %uint_0', asm)) != 2:
        fails.append(f'{h}: expected exactly 2 gate cullMask selects (thickness + visibility)')
    # value-resolved threshold compares, baseline-aware (as v3)
    def lt_count(text, val, tol):
        cvals = {}
        for cm in re.finditer(r'(%\w+) = OpConstant %float ([0-9.e+-]+)', text):
            try: cvals[cm.group(1)] = float(cm.group(2))
            except ValueError: pass
        n = 0
        for om in re.finditer(r'OpFOrdLessThan %bool %\w+ (%\w+)', text):
            v = cvals.get(om.group(1))
            if v is not None and abs(v - val) <= tol:
                n += 1
        return n
    if lt_count(asm, 0.25, 1e-6) != lt_count(van, 0.25, 1e-6) + 3:
        fails.append(f'{h}: albedo-eps compares at 0.25 != base+3')
    if lt_count(asm, 0.10, 1e-6) != lt_count(van, 0.10, 1e-6):
        fails.append(f'{h}: stale 0.10-threshold compare present')
    if lt_count(asm, 2.5e-5, 1e-9) != lt_count(van, 2.5e-5, 1e-9):
        fails.append(f'{h}: stale v3 2.5e-5 consistency compare present')
    if len(re.findall(r'OpDot %float ', asm)) != \
       len(re.findall(r'OpDot %float ', van)) + 3:
        fails.append(f'{h}: Dot count != base+3')
    if len(re.findall(r'OpExtInst %float %\w+ Sqrt ', asm)) != \
       len(re.findall(r'OpExtInst %float %\w+ Sqrt ', van)) + 1:
        fails.append(f'{h}: Sqrt count != base+1')
    if len(re.findall(r'OpFOrdEqual %bool %\w+ %float_10000\b', asm)) != \
       len(re.findall(r'OpFOrdEqual %bool %\w+ %float_10000\b', van)) + 1:
        fails.append(f'{h}: visibility ==10000 compare count != base+1')
    if not re.search(r'OpIEqual %bool %\w+ %uint_32', asm):
        fails.append(f'{h}: skin class-32 compare missing')
    # probe payoff: NO new Exp/NMin-glow terms; 3 LogicalNots; 15 palette
    # selects on top of the 3 the splice already carries (oct sx/sy + N.z)
    if len(re.findall(r'OpExtInst %float %\w+ Exp ', asm)) != \
       len(re.findall(r'OpExtInst %float %\w+ Exp ', van)):
        fails.append(f'{h}: Exp count changed -- glow term leaked into the probe')
    if len(re.findall(r'OpLogicalNot ', asm)) != \
       len(re.findall(r'OpLogicalNot ', van)) + 3:
        fails.append(f'{h}: LogicalNot count != base+3 (not-vis/not-cons/not-sim)')
    if len(re.findall(r'OpSelect %float ', asm)) != \
       len(re.findall(r'OpSelect %float ', van)) + 18:
        fails.append(f'{h}: float-select count != base+18 (3 splice + 15 palette)')
    for val, what in ((3.2, 'palette dominant 3.2'), (0.4, 'blue-guard 0.4')):
        pat = [c for c in re.findall(r'OpConstant %float ([0-9.e+-]+)', asm)
               if abs(float(c) - val) < 1e-6]
        if not pat:
            fails.append(f'{h}: {what} constant missing')
    n_add_writes = 0
    for wm in re.finditer(r'OpImageWrite %\w+ %\w+ (%\w+)', asm):
        cm = re.search(re.escape(wm.group(1)) +
                       r' = OpCompositeConstruct %v4float (%\w+) (%\w+) (%\w+)', asm)
        if cm and all(re.search(re.escape(cm.group(i)) + r' = OpFAdd %float ', asm)
                      for i in (1, 2, 3)):
            n_add_writes += 1
    if n_add_writes < 1:
        fails.append(f'{h}: no paint-added radiance write found')
if fails:
    print('EMITTED-CODE RE-READ FAILED:\n  ' + '\n  '.join(fails)); sys.exit(1)
print(f'  emitted-code re-read: {dest} clean')
PYV
sed -e "1s/^gi-50-bleed /$NAME /" \
    -e "1s/ref=12(pass-through)/ref=12(10 probe-paint + 2 pass-through)/" \
    "$GI/MANIFEST.txt" > "$dest/MANIFEST.txt"
grep -q "^$NAME " "$dest/MANIFEST.txt" || { echo "MANIFEST rewrite failed" >&2; exit 1; }
cat >> "$dest/MANIFEST.txt" <<'EOF'
# ear-glow gate-attribution PROBE (handoff/66): v3 gates measured independently,
# glow replaced by additive paint. MAGENTA=vis-fail YELLOW=cons+albedo RED=cons
# GREEN=albedo BLUE=all-pass; no paint = pre-v3 gates never fired.
# select: hand-edit brdf_params.txt skinspec=probe-earglow BEFORE EVERY LAUNCH
# (40 sec 7 -- init.lua resets unknown names; the settings-page warning is the
# confirmation, not an error). contract: ser=class shadowset=full-shadow ptreg ON.
# diagnostic rung -- read handoff/66's table BEFORE the screen
EOF
n=$(ls "$dest"/*.spv | wc -l)
[[ "$n" == 93 ]] || { echo "$NAME has $n modules, expected 93 (77+12+4)" >&2; exit 1; }
echo "  built swaps.$NAME: $n modules, all spirv-val clean"

if (( DO_INSTALL )); then
    park="$INSTALL_DIR/skin.set/$NAME"
    mkdir -p "$park"; rm -f "$park"/*.spv "$park"/*.json "$park/MANIFEST.txt"
    cp -pf "$dest"/*.spv "$dest"/*.json "$dest/MANIFEST.txt" "$park/"
    echo "  parked -> $park"
fi
echo "select by HAND-EDITING brdf_params.txt: skinspec=$NAME (before every launch)"
echo "contract: ser=class, shadowset=full-shadow, ptreg ON (rcbm combo) -- gi-50-bleed's"
