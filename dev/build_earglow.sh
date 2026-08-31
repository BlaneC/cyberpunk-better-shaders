#!/usr/bin/env bash
# Traced-thickness ear glow V4 (handoff/68; probe: 66/67, v3: 64/65, v2:
# 62/63, v1: 59, refusal: 61): gi-50-bleed plus the thickness ray +
# Beer-Lambert transmission, gated by the ONE-SIDED distance-aware
# consistency compare (68), a sun-visibility ray, and an albedo compare at
# v2's 0.25. Three strength rungs, same physics.
#
#   ./dev/build_earglow.sh              # build + verify (no install)
#   ./dev/build_earglow.sh --install    # ALSO park as skin.set/earglow{-lo,,-hi}
#
# Composition mirrors build_sentinel.sh, based on skin.set/gi-50-bleed (the
# standing rung): its 77 compute (real-gloss-bleed) + 4 restirgi splices + 2
# atomic reference files ship BYTE-VERBATIM (cmp-asserted); only the 10
# paintable rgs_reference_main are patched. The A/B "gi-50-bleed vs earglow"
# is one variable by construction. MANIFEST provenance (src_ser/ser_sha/
# ptq_sha) carries over verbatim, so sync's gi_refuse contract holds
# unchanged: needs ser=class + shadowset=full-shadow + the rcbm ptq combo.
set -euo pipefail

MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="${CALLISTO_INSTALL_DIR:-$HOME/.local/lib/callisto}"
GI="$INSTALL_DIR/skin.set/gi-50-bleed"
WORK="$MOD_DIR/dev/disasm/earglow"
PY="$MOD_DIR/dev/patch_earglow.py"

DO_INSTALL=0
[[ "${1:-}" == "--install" ]] && DO_INSTALL=1

PASS=(40c6faab52a13874 ab7f1822eeb0331b)
declare -A RUNGS=([earglow-lo]=0.10 [earglow]=0.22 [earglow-hi]=0.45)

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

build_rung() {  # $1 = rung name, $2 = k
    local name="$1" k="$2" dest="$MOD_DIR/swaps.$1"
    rm -rf "$dest"; mkdir -p "$dest"
    printf '%s\0' "${TARGETS[@]}" | CB_D="$dest" CB_P="$PY" CB_W="$WORK" CB_K="$k" \
        xargs -0 -P "$jobs" -n1 bash -c '
            python3 "$CB_P" "$CB_W/$0.rgs_reference_main.spvasm" --k "$CB_K" \
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
            && { echo "$name: $h is byte-identical to base -- splice emitted nothing" >&2; exit 1; }
    done
    for f in "$dest"/*.spv; do
        spirv-val "$f" || { echo "spirv-val FAILED: $f" >&2; exit 1; }
    done
    # emitted-instruction re-read from the OUTPUT binaries (39 sec 3.4)
    python3 - "$dest" "$GI" "$k" << 'PYV'
import re, subprocess, sys, glob, os, math
dest, base, k = sys.argv[1], sys.argv[2], float(sys.argv[3])
PASS = ('40c6faab52a13874', 'ab7f1822eeb0331b')
INV = [1/0.00367, 1/0.00137, 1/0.00068]
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
        fails.append(f'{h}: trace count {len(traces)} != base+2 (v2: thickness+visibility)'); continue
    inj = [t for t in traces if t.split()[1] == '%uint_16']
    if len(inj) != 1:
        fails.append(f'{h}: {len(inj)} flags-16 injected traces, expected 1'); continue
    tmax = inj[0].split()[9]
    m = re.search(re.escape(tmax) + r' = OpConstant %float ([0-9.e+-]+)', asm)
    if not m or abs(float(m.group(1)) - 0.018) > 1e-6:
        fails.append(f'{h}: injected tmax {tmax} is not 0.018'); continue
    # v2 (a): ONE new flags-12 trace -- NEE-shaped, tmax 10000, on the SAME
    # injected payload as the thickness trace (the engine's own NEE has a
    # different payload variable, so this cannot false-positive)
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
    # value-resolved constant lookup for threshold compares.
    # Baseline-aware: the vanilla module may already compare against the
    # same f32 value (0.1 is a common engine constant), so assert deltas.
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
    # v4: 3 new per-channel albedo compares at 0.25 (none left at v3's 0.10)
    if lt_count(asm, 0.25, 1e-6) != lt_count(van, 0.25, 1e-6) + 3:
        fails.append(f'{h}: albedo-eps compares at 0.25 != base+3')
    if lt_count(asm, 0.10, 1e-6) != lt_count(van, 0.10, 1e-6):
        fails.append(f'{h}: stale v3 0.10-threshold compare present')
    # v4: the v3 squared-norm compare must be GONE
    if lt_count(asm, 2.5e-5, 1e-9) != lt_count(van, 2.5e-5, 1e-9):
        fails.append(f'{h}: stale v3 2.5e-5 consistency compare present')
    # v4: 3 injected Dots (oct-decode + s = Delta.D + N.D)
    if len(re.findall(r'OpDot %float ', asm)) != \
       len(re.findall(r'OpDot %float ', van)) + 3:
        fails.append(f'{h}: Dot count != base+3')
    # v4: one Sqrt (the tan slope term) and the one-sided compare + the
    # [N.z>0] select's GreaterThan from the offset clone
    if len(re.findall(r'OpExtInst %float %\w+ Sqrt ', asm)) != \
       len(re.findall(r'OpExtInst %float %\w+ Sqrt ', van)) + 1:
        fails.append(f'{h}: Sqrt count != base+1')
    if len(re.findall(r'OpFOrdGreaterThan %bool ', asm)) != \
       len(re.findall(r'OpFOrdGreaterThan %bool ', van)) + 2:
        fails.append(f'{h}: FOrdGreaterThan count != base+2 (N.z gate + one-sided cons)')
    for val, what in ((0.003, 'eps0'), (0.0015, 'b'), (0.0022, 'a')):
        pat = [c for c in re.findall(r'OpConstant %float ([0-9.e+-]+)', asm)
               if abs(float(c) - val) < 1e-7]
        if not pat:
            fails.append(f'{h}: v4 gate constant {what}={val} missing')
    if len(re.findall(r'OpFOrdEqual %bool %\w+ %float_10000\b', asm)) != \
       len(re.findall(r'OpFOrdEqual %bool %\w+ %float_10000\b', van)) + 1:
        fails.append(f'{h}: visibility ==10000 compare count != base+1')
    if not re.search(r'OpIEqual %bool %\w+ %uint_32', asm):
        fails.append(f'{h}: skin class-32 compare missing')
    if len(re.findall(r'OpExtInst %float %\w+ Exp ', asm)) != 3:
        fails.append(f'{h}: expected exactly 3 Exp instructions')
    for inv in INV:
        pat = [c for c in re.findall(r'OpConstant %float ([0-9.e+-]+)', asm)
               if abs(float(c) - inv) / inv < 1e-3]
        if not pat:
            fails.append(f'{h}: 1/ld constant {inv:.2f} missing')
    kc = [c for c in re.findall(r'OpConstant %float ([0-9.e+-]+)', asm)
          if abs(float(c) - k) < 1e-6]
    if not kc:
        fails.append(f'{h}: strength constant {k} missing')
    # every rewritten radiance write feeds FAdd-composed texels
    n_add_writes = 0
    for wm in re.finditer(r'OpImageWrite %\w+ %\w+ (%\w+)', asm):
        cm = re.search(re.escape(wm.group(1)) +
                       r' = OpCompositeConstruct %v4float (%\w+) (%\w+) (%\w+)', asm)
        if cm and all(re.search(re.escape(cm.group(i)) + r' = OpFAdd %float ', asm)
                      for i in (1, 2, 3)):
            n_add_writes += 1
    if n_add_writes < 1:
        fails.append(f'{h}: no glow-added radiance write found')
if fails:
    print('EMITTED-CODE RE-READ FAILED:\n  ' + '\n  '.join(fails)); sys.exit(1)
print(f'  emitted-code re-read: {dest} clean')
PYV
    sed -e "1s/^gi-50-bleed /$name /" \
        -e "1s/ref=12(pass-through)/ref=12(10 earglow k=$k + 2 pass-through)/" \
        "$GI/MANIFEST.txt" > "$dest/MANIFEST.txt"
    grep -q "^$name " "$dest/MANIFEST.txt" || { echo "MANIFEST rewrite failed" >&2; exit 1; }
    echo "# traced-thickness ear glow V4 (handoff/68): k=$k T_CAP=0.02 ld=3.67/1.37/0.68mm" >> "$dest/MANIFEST.txt"
    echo "# v4 gates: ONE-SIDED consistency s=Delta.D > -(3mm+1.5mm/m+2.2mm/m*tan,cap10x)" >> "$dest/MANIFEST.txt"
    echo "# + sun-visibility ray + albedo (eps 0.25, v2's value)" >> "$dest/MANIFEST.txt"
    echo "# A/B against gi-50-bleed; NOT working until the screen says so" >> "$dest/MANIFEST.txt"
    n=$(ls "$dest"/*.spv | wc -l)
    [[ "$n" == 93 ]] || { echo "$name has $n modules, expected 93 (77+12+4)" >&2; exit 1; }
    echo "  built swaps.$name: $n modules, all spirv-val clean"
}

for r in "${!RUNGS[@]}"; do build_rung "$r" "${RUNGS[$r]}"; done

if (( DO_INSTALL )); then
    for r in "${!RUNGS[@]}"; do
        park="$INSTALL_DIR/skin.set/$r"
        mkdir -p "$park"; rm -f "$park"/*.spv "$park"/*.json "$park/MANIFEST.txt"
        cp -pf "$MOD_DIR/swaps.$r"/*.spv "$MOD_DIR/swaps.$r"/*.json "$MOD_DIR/swaps.$r/MANIFEST.txt" "$park/"
        echo "  parked -> $park"
    done
fi
echo "select with skinspec=earglow (or earglow-lo / earglow-hi)"
echo "contract: ser=class, shadowset=full-shadow, ptreg ON (rcbm combo) -- gi-50-bleed's"
