#!/usr/bin/env bash
# Traced-thickness ear glow V5 (handoff/71; 70's W1+W3. history: v4 68,
# probe 66/67, v3 64/65, v2 62/63, v1 59, refusal 61): the thickness ray is
# FLIPPED -- from the module's own offset NEE origin straight TOWARD the
# sun, CullFrontFacingTriangles (flags 32), tmax 18mm. The first hit is the
# flesh's far wall seen from inside: a BACKFACE at t = the true sun-path
# thickness. v3/v4's consistency gate is GONE (leaks die by geometry + a
# 1.5mm min-thickness floor); the albedo gate (0.25) and sun-visibility ray
# stay. Pre-registered falsifier: if the BVH strips interior backfaces,
# everything goes dark -> revert to the v4 machinery (git) + s-band probe.
#
# The ladder is DESIGN, not strength -- all rungs k=0.22 (69 sec 2 / 70):
#   earglow-lo  W1 only, raw Beer-Lambert, no wrap (isolates the flip)
#   earglow     W1+W3: transfer 0.5*(e^-t/ld + e^-t/4ld), wrap 0.35
#   earglow-hi  W1+W3 stronger: second lobe 6x, wrap 0.5
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
K=0.22
# rung -> "wide,wrap" ("" = raw Beer-Lambert, no wrap)
declare -A RUNGS=([earglow-lo]="" [earglow]="4.0,0.35" [earglow-hi]="6.0,0.5")

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

build_rung() {  # $1 = rung name, $2 = "wide,wrap" or ""
    local name="$1" softspec="$2" dest="$MOD_DIR/swaps.$1" softargs=""
    local wide="" wrap=""
    if [[ -n "$softspec" ]]; then
        wide="${softspec%,*}"; wrap="${softspec#*,}"
        softargs="--wide $wide --wrap $wrap"
    fi
    rm -rf "$dest"; mkdir -p "$dest"
    printf '%s\0' "${TARGETS[@]}" | CB_D="$dest" CB_P="$PY" CB_W="$WORK" CB_K="$K" CB_S="$softargs" \
        xargs -0 -P "$jobs" -n1 bash -c '
            python3 "$CB_P" "$CB_W/$0.rgs_reference_main.spvasm" --k "$CB_K" $CB_S \
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
    python3 - "$dest" "$GI" "$K" "$wide" "$wrap" << 'PYV'
import re, subprocess, sys, glob, os
dest, base, k = sys.argv[1], sys.argv[2], float(sys.argv[3])
wide = float(sys.argv[4]) if sys.argv[4] else None
wrap = float(sys.argv[5]) if sys.argv[5] else None
PASS = ('40c6faab52a13874', 'ab7f1822eeb0331b')
LD = [0.00367, 0.00137, 0.00068]
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
    # v5: the injected thickness trace is flags 32 (CullFrontFacingTriangles)
    inj = [t for t in traces if t.split()[1] == '%uint_32']
    if len(inj) != 1:
        fails.append(f'{h}: {len(inj)} flags-32 injected traces, expected 1'); continue
    if any(t.split()[1] == '%uint_16' for t in traces):
        fails.append(f'{h}: stale flags-16 (v4 reversed-segment) trace present'); continue
    tmax = inj[0].split()[9]
    m = re.search(re.escape(tmax) + r' = OpConstant %float ([0-9.e+-]+)', asm)
    if not m or abs(float(m.group(1)) - 0.018) > 1e-6:
        fails.append(f'{h}: injected tmax {tmax} is not 0.018'); continue
    # v5 W1: the flipped ray's origin AND direction must be the sun-NEE
    # trace's own operands VERBATIM (the NEE trace: flags 12, tmax 10000,
    # cullMask defined by Select(cond, 0, 39))
    nee = None
    for t in traces:
        tt = t.split()
        if len(tt) == 11 and tt[1] == '%uint_12' and tt[9] == '%float_10000':
            if re.search(re.escape(tt[2]) + r' = OpSelect %uint %\w+ %uint_0 %uint_39\b', asm):
                nee = tt
    if nee is None:
        fails.append(f'{h}: sun-NEE trace not found for operand cross-check')
    else:
        it = inj[0].split()
        if it[6] != nee[6] or it[8] != nee[8]:
            fails.append(f'{h}: flipped ray origin/dir ({it[6]},{it[8]}) are not '
                         f'the NEE trace operands ({nee[6]},{nee[8]})')
    # v2 (a): ONE new flags-12 trace on the injected payload
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
    # value-resolved constant lookups
    def consts_at(text, val, tol):
        out = set()
        for cm in re.finditer(r'(%\w+) = OpConstant %float ([0-9.e+-]+)', text):
            try:
                if abs(float(cm.group(2)) - val) <= tol:
                    out.add(cm.group(1))
            except ValueError:
                pass
        return out
    def lt_count(text, val, tol):
        ids = consts_at(text, val, tol)
        return sum(1 for om in re.finditer(r'OpFOrdLessThan %bool %\w+ (%\w+)', text)
                   if om.group(1) in ids)
    def gt_count(text, val, tol):
        ids = consts_at(text, val, tol)
        return sum(1 for om in re.finditer(r'OpFOrdGreaterThan %bool %\w+ (%\w+)', text)
                   if om.group(1) in ids)
    # albedo gate stays at v2's 0.25
    if lt_count(asm, 0.25, 1e-6) != lt_count(van, 0.25, 1e-6) + 3:
        fails.append(f'{h}: albedo-eps compares at 0.25 != base+3')
    if lt_count(asm, 0.10, 1e-6) != lt_count(van, 0.10, 1e-6):
        fails.append(f'{h}: stale v3 0.10-threshold compare present')
    # v4's gate machinery must be GONE
    if lt_count(asm, 2.5e-5, 1e-9) != lt_count(van, 2.5e-5, 1e-9):
        fails.append(f'{h}: stale v3 2.5e-5 consistency compare present')
    for val, what in ((0.003, 'eps0'), (0.0022, 'a')):
        if consts_at(asm, val, 1e-7) - consts_at(van, val, 1e-7):
            fails.append(f'{h}: stale v4 gate constant {what}={val} present')
    if len(re.findall(r'OpExtInst %float %\w+ Sqrt ', asm)) != \
       len(re.findall(r'OpExtInst %float %\w+ Sqrt ', van)):
        fails.append(f'{h}: Sqrt count changed -- v4 tan term leaked into v5')
    # v5 min-thickness floor: one new FOrdGreaterThan against 0.0015
    if gt_count(asm, 0.0015, 1e-9) != gt_count(van, 0.0015, 1e-9) + 1:
        fails.append(f'{h}: min-thickness floor compare (>0.0015) != base+1')
    # FOrdGreaterThan total: floor + the offset clone's [N.z>0]
    if len(re.findall(r'OpFOrdGreaterThan %bool ', asm)) != \
       len(re.findall(r'OpFOrdGreaterThan %bool ', van)) + 2:
        fails.append(f'{h}: FOrdGreaterThan count != base+2 (N.z gate + floor)')
    # Dot count: oct-decode vv.vv, +1 for the W3 wrap's N.S
    dots = 2 if wide else 1
    if len(re.findall(r'OpDot %float ', asm)) != \
       len(re.findall(r'OpDot %float ', van)) + dots:
        fails.append(f'{h}: Dot count != base+{dots}')
    if len(re.findall(r'OpFOrdEqual %bool %\w+ %float_10000\b', asm)) != \
       len(re.findall(r'OpFOrdEqual %bool %\w+ %float_10000\b', van)) + 1:
        fails.append(f'{h}: visibility ==10000 compare count != base+1')
    if not re.search(r'OpIEqual %bool %\w+ %uint_32', asm):
        fails.append(f'{h}: skin class-32 compare missing')
    # transfer: 3 Exp (raw) or 6 (W3 dual-lobe); SmoothStep only with W3
    nexp = 6 if wide else 3
    if len(re.findall(r'OpExtInst %float %\w+ Exp ', asm)) != nexp:
        fails.append(f'{h}: expected exactly {nexp} Exp instructions')
    nss = 1 if wide else 0
    if len(re.findall(r'OpExtInst %float %\w+ SmoothStep ', asm)) != nss:
        fails.append(f'{h}: expected exactly {nss} SmoothStep instructions')
    for ld in LD:
        if not consts_at(asm, 1.0 / ld, 1.0 / ld * 1e-3):
            fails.append(f'{h}: 1/ld constant {1/ld:.2f} missing')
        if wide and not consts_at(asm, 1.0 / (wide * ld), 1.0 / (wide * ld) * 1e-3):
            fails.append(f'{h}: 1/(wide*ld) constant {1/(wide*ld):.2f} missing')
    if wrap and not consts_at(asm, wrap, 1e-6):
        fails.append(f'{h}: wrap constant {wrap} missing')
    if not consts_at(asm, k, 1e-6):
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
    local softtxt="raw Beer-Lambert, no wrap (W1 isolated)"
    [[ -n "$softspec" ]] && softtxt="W3 soft: 0.5*(e^-t/ld + e^-t/${wide}ld), wrap smoothstep(0,$wrap,-N.S)"
    sed -e "1s/^gi-50-bleed /$name /" \
        -e "1s/ref=12(pass-through)/ref=12(10 earglow k=$K + 2 pass-through)/" \
        "$GI/MANIFEST.txt" > "$dest/MANIFEST.txt"
    grep -q "^$name " "$dest/MANIFEST.txt" || { echo "MANIFEST rewrite failed" >&2; exit 1; }
    echo "# traced-thickness ear glow V5 (handoff/71): FLIPPED ray -- sunward from the" >> "$dest/MANIFEST.txt"
    echo "# NEE origin, CullFront (32), tmax 18mm; t = true sun-path thickness from the" >> "$dest/MANIFEST.txt"
    echo "# far wall's backface. NO consistency gate; floor t>1.5mm; albedo 0.25; vis ray." >> "$dest/MANIFEST.txt"
    echo "# k=$K ld=3.67/1.37/0.68mm; $softtxt" >> "$dest/MANIFEST.txt"
    echo "# falsifier: all-dark = BVH strips interior backfaces -> revert v4 (git)" >> "$dest/MANIFEST.txt"
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
