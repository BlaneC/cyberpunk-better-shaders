#!/usr/bin/env bash
# earglow-rq -- thin-skin sun transmission (ear/nose glow) on a RAY QUERY.
# handoff/101-EARGLOW-RQ.md is the document. Read its section 7 (the
# pre-registered interpretation table) BEFORE looking at a frame.
#
#   ./dev/build_earglow_rq.sh              # build + 9 gates (nothing installed)
#   ./dev/build_earglow_rq.sh --install    # ALSO park the four rungs
#   ./dev/build_earglow_rq.sh --base NAME  # build on a different parked rung
#
# FOUR RUNGS, one variable each, all on the STANDING selection's own bytes.
# The ladder is DESIGN, not strength: every glow rung is k=0.22 and "do not
# tune k" (70/71) still stands.
#
#   earglow-rq-ctl  k=0. The patcher emits NOTHING, so the output is
#                   BYTE-IDENTICAL to the base (gate 5, resting on gate 1's
#                   round-trip neutrality). This is not a tautology: it is the
#                   control for the SELECTOR and the LAYER. If -ctl does not
#                   look exactly like gi-50b-...-fog, the shader is innocent.
#   earglow-rq-hit  THE FALSIFIER'S INSTRUMENT. Flat additive paint, no
#                   transfer: BLUE where the sunward query commits anything in
#                   [1.5, 18] mm, RED where the gate passed and it committed
#                   nothing. 70 W1's pre-registered risk is that the engine
#                   strips interior backfaces from its BLASes; 98 proved
#                   FRONT-face hits only, so backface availability is UNPROVEN
#                   and this rung reads the miss/hit map independently of any
#                   claim about the transfer being right.
#   earglow-rq      W1 + W3, k=0.22: transfer 0.5*(e^-t/ld + e^-t/4ld),
#                   wrap smoothstep(0, 0.35, -N.S).
#   earglow-rq-hi   the same, softer: second lobe 6x, wrap 0.5. 70's ladder.
#
# THE RAY (70 W1): from the module's own offset NEE origin, along its own sun
# direction S, flags 545 = Opaque | CullFrontFacingTriangles | SkipAABBs, NO
# TerminateOnFirstHit, tmin 1.5 mm, tmax 18 mm. The entering front face is
# culled, so the COMMITTED (closest) hit is the far wall's BACKFACE and its t
# is the sun-path flesh thickness. 98 sec 15 proved this raygen's hit
# positions and its TLAS share one camera-relative space, so NO world offset
# is applied to the origin -- adding one would be the bug.
#
# The 77 compute, the 4 rgs_restirgi and the 2 radiance-write-free reference
# permutations ship BYTE-VERBATIM from the base and are cmp-asserted; only the
# same 10 of 12 rgs_reference_main that 55/56/98 painted are touched.
#
# The rungs REQUIRE a layer that enables VK_KHR_ray_query on the VkDevice
# (swap_layer.c, handoff/98 sec 6/7). Without it the layer's own guard sends
# these modules to the NEXT overlay -- never to vanilla -- and the launch reads
# as the base image with `rayq_reject` in ~/callisto_swap.jsonl. Prove the
# layer and the driver FIRST, without the game:
#     ./dev/selftest_earglow_rq.sh
set -euo pipefail

MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="${CALLISTO_INSTALL_DIR:-$HOME/.local/lib/callisto}"
PY="$MOD_DIR/dev/patch_earglow_rq.py"
VERIFY="$MOD_DIR/dev/verify_earglow_rq.py"
WORK="$MOD_DIR/dev/disasm/earglow_rq"

BASE=gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog
K=0.22
DO_INSTALL=0
while (( $# )); do
    case "$1" in
        --install) DO_INSTALL=1 ;;
        --base) BASE="${2:?--base needs a skin.set name}"; shift ;;
        -h|--help) sed -n '2,50p' "$0"; exit 0 ;;
        *) echo "unknown arg $1" >&2; exit 1 ;;
    esac
    shift
done

SRC="$INSTALL_DIR/skin.set/$BASE"
PASS=(40c6faab52a13874 ab7f1822eeb0331b)

# --- 0. base provenance -----------------------------------------------------
[[ -f "$SRC/MANIFEST.txt" ]] || { echo "no $SRC/MANIFEST.txt -- the standing selection is not parked" >&2; exit 1; }
n_c=$(ls "$SRC"/*.dxil.spv | wc -l)
n_g=$(ls "$SRC"/*.rgs_restirgi_*.spv | wc -l)
n_r=$(ls "$SRC"/*.rgs_reference_main.spv | wc -l)
[[ "$n_c" == 77 ]] || { echo "$BASE has $n_c compute modules, expected 77" >&2; exit 1; }
[[ "$n_g" == 4  ]] || { echo "$BASE has $n_g restirgi modules, expected 4" >&2; exit 1; }
[[ "$n_r" == 12 ]] || { echo "$BASE has $n_r rgs_reference_main, expected 12" >&2; exit 1; }

mapfile -t REFS < <(cd "$SRC" && ls *.rgs_reference_main.spv | sed 's/\..*//')
TARGETS=()
for h in "${REFS[@]}"; do
    skip=0; for p in "${PASS[@]}"; do [[ "$h" == "$p" ]] && skip=1; done
    (( skip )) && continue
    TARGETS+=("$h")
done
(( ${#TARGETS[@]} == 10 )) || { echo "expected 10 paintable refs, have ${#TARGETS[@]}" >&2; exit 1; }

echo "=== 0. base: $BASE ($(head -1 "$SRC/MANIFEST.txt" | cut -c1-90))"

rm -rf "$WORK"; mkdir -p "$WORK/asm" "$WORK/rt"
for h in "${TARGETS[@]}"; do
    spirv-dis "$SRC/$h.rgs_reference_main.spv" -o "$WORK/asm/$h.spvasm"
done

# --- 1. the pipeline is byte-neutral on the reference raygens ---------------
# Everything the -ctl rung claims rests on this: at k=0 the patcher emits no
# instructions and writes the disassembly straight back, so "byte-identical to
# the base" is only true if dis -> as is neutral. 94 sec 11 is the precedent.
echo "=== 1. round-trip neutrality (spirv-dis -> spirv-as == base bytes)"
for h in "${TARGETS[@]}"; do
    spirv-as --target-env spv1.4 "$WORK/asm/$h.spvasm" -o "$WORK/rt/$h.spv"
    cmp -s "$SRC/$h.rgs_reference_main.spv" "$WORK/rt/$h.spv" \
        || { echo "  !! $h does not round-trip -- no control built on it is meaningful" >&2; exit 1; }
done
echo "  10 of 10 reference permutations round-trip byte-identically"
rm -rf "$WORK/rt"

jobs="${CALLISTO_JOBS:-$(nproc 2>/dev/null || echo 4)}"

patch_set () {   # $1 = outdir, $2.. = patcher args
    local out="$1"; shift
    mkdir -p "$out"
    printf '%s\n' "$@" > "$WORK/.args"
    printf '%s\0' "${TARGETS[@]}" | CB_O="$out" CB_P="$PY" CB_W="$WORK" \
        CB_A="$WORK/.args" xargs -0 -P "$jobs" -n1 bash -c '
            mapfile -t A < "$CB_A"
            python3 "$CB_P" "$CB_W/asm/$0.spvasm" "${A[@]}" --outdir "$CB_O" \
                > "$CB_O/$0.earglowrq.report.json"'
    rm -f "$WORK/.args"
    local n; n=$(ls "$out"/*.spv 2>/dev/null | wc -l)
    [[ "$n" == 10 ]] || { echo "  !! $out produced $n modules, want 10" >&2; exit 1; }
}

assemble () {   # $1 = dest, $2 = patched-raygen dir, $3 = 1 if the 10 must be
                #      byte-identical to the base (the k=0 control)
    local dest="$1" src="$2" identical="${3:-0}"
    rm -rf "$dest"; mkdir -p "$dest"
    cp -pf "$src"/*.spv "$src"/*.json "$dest/"
    cp -pf "$SRC"/*.dxil.spv "$SRC"/*.rgs_restirgi_*.spv "$dest/"
    for p in "${PASS[@]}"; do cp -pf "$SRC/$p.rgs_reference_main.spv" "$dest/"; done
    for f in "$SRC"/*.dxil.spv "$SRC"/*.rgs_restirgi_*.spv; do
        cmp -s "$f" "$dest/$(basename "$f")" \
            || { echo "  !! verbatim copy differs: $(basename "$f")" >&2; exit 1; }
    done
    for p in "${PASS[@]}"; do
        cmp -s "$SRC/$p.rgs_reference_main.spv" "$dest/$p.rgs_reference_main.spv" \
            || { echo "  !! pass-through $p differs from the base" >&2; exit 1; }
    done
    for h in "${TARGETS[@]}"; do
        if (( identical )); then
            cmp -s "$SRC/$h.rgs_reference_main.spv" "$dest/$h.rgs_reference_main.spv" \
                || { echo "  !! CONTROL $h is NOT byte-identical to the base" >&2; exit 1; }
        else
            cmp -s "$SRC/$h.rgs_reference_main.spv" "$dest/$h.rgs_reference_main.spv" \
                && { echo "  !! $h is byte-identical to the base -- the splice emitted nothing" >&2; exit 1; }
        fi
    done
    local n; n=$(ls "$dest"/*.spv | wc -l)
    [[ "$n" == 93 ]] || { echo "  !! $dest has $n modules, expected 93" >&2; exit 1; }
    for f in "$dest"/*.spv; do
        spirv-val --target-env vulkan1.4 "$f" >/dev/null \
            || { echo "  !! spirv-val --target-env vulkan1.4 FAILED: $f" >&2; exit 1; }
    done
}

# --- 2. patch + assemble ----------------------------------------------------
echo "=== 2. patch + assemble the four rungs"
ORDER=(earglow-rq-ctl earglow-rq-hit earglow-rq earglow-rq-hi)
declare -A RUNG_ARGS=(
    [earglow-rq-ctl]="--k 0"
    [earglow-rq-hit]="--k $K --mode hit"
    [earglow-rq]="--k $K --wide 4.0 --wrap 0.35"
    [earglow-rq-hi]="--k $K --wide 6.0 --wrap 0.5"
)
declare -A RUNG_IDENT=([earglow-rq-ctl]=1)
for r in "${ORDER[@]}"; do
    # shellcheck disable=SC2086
    patch_set "$WORK/p.$r" ${RUNG_ARGS[$r]}
    assemble "$MOD_DIR/swaps.$r" "$WORK/p.$r" "${RUNG_IDENT[$r]:-0}"
    echo "  swaps.$r: 93 modules, $( (( ${RUNG_IDENT[$r]:-0} )) && echo '10 identity' || echo '10 patched'), spirv-val (vulkan1.4) clean"
done
# The three live rungs must differ from each other on every patched module --
# one variable each, and a rung that silently equals another is not a rung.
for pair in "earglow-rq-hit earglow-rq" "earglow-rq earglow-rq-hi" "earglow-rq-hit earglow-rq-hi"; do
    set -- $pair; d=0
    for h in "${TARGETS[@]}"; do
        cmp -s "$MOD_DIR/swaps.$1/$h.rgs_reference_main.spv" \
               "$MOD_DIR/swaps.$2/$h.rgs_reference_main.spv" || d=$((d+1))
    done
    [[ "$d" == 10 ]] || { echo "  !! only $d of 10 differ between $1 and $2" >&2; exit 1; }
done
echo "  10 of 10 differ between every pair of the three live rungs"

# --- 3. coverage census, from the REPORTS (never from byte counts; 42) ------
echo "=== 3. coverage census"
python3 - "$MOD_DIR" "${ORDER[@]}" <<'PY' || exit 1
import glob, json, os, sys
mod_dir, rungs = sys.argv[1], sys.argv[2:]
# Stated HERE, independently of what the build script asked the patcher for:
# a rung that silently changed its flags or its bracket must fail this gate
# even if the request above changed with it.
WANT = {
    'earglow-rq-ctl': dict(mode='control'),
    'earglow-rq-hit': dict(mode='hit',  flags=545, tmin=0.0015, tmax=0.018, k=0.22, soft=None),
    'earglow-rq':     dict(mode='glow', flags=545, tmin=0.0015, tmax=0.018, k=0.22, soft=dict(wide=4.0, wrap=0.35)),
    'earglow-rq-hi':  dict(mode='glow', flags=545, tmin=0.0015, tmax=0.018, k=0.22, soft=dict(wide=6.0, wrap=0.5)),
}
bad, CENSUS = [], None
for r in rungs:
    d = os.path.join(mod_dir, 'swaps.' + r)
    want = WANT[r]
    mods = writes = skipped = 0
    legacy_wrong = []
    for f in sorted(glob.glob(os.path.join(d, '*.earglowrq.report.json'))):
        rep = json.load(open(f))
        q = rep['earglow_rq']
        mods += 1
        if rep.get('spirv_val') != 'clean':
            bad.append((r, rep['module'], 'spirv-val not clean'))
        if q['mode'] != want['mode']:
            bad.append((r, rep['module'], f"mode {q['mode']} != {want['mode']}"))
        if want['mode'] == 'control':
            if q.get('emitted') != 0:
                bad.append((r, rep['module'], 'the control emitted instructions'))
            continue
        writes += len(q['writes_added'])
        for s in q['writes_skipped']:
            if s['why'] not in ('constant-zero', 'scalar-broadcast'):
                bad.append((r, rep['module'], 'unexpected skip: ' + s['why']))
            skipped += 1
        for key in ('flags', 'tmin', 'tmax', 'k'):
            got = q['ray_flags'] if key == 'flags' else q[key]
            if got != want[key]:
                bad.append((r, rep['module'], f'{key} {got} != {want[key]}'))
        if q['soft'] != want['soft']:
            bad.append((r, rep['module'], f"soft {q['soft']} != {want['soft']}"))
        if q['commit'] != 'closest':
            bad.append((r, rep['module'], 'commit mode is not closest'))
        if q['decoy'] is not None:
            bad.append((r, rep['module'], 'a DECOY build reached a rung'))
        if q['gate_mask'] != 39:
            bad.append((r, rep['module'], f"gate cull mask {q['gate_mask']} != 39"))
        if q['accel'] is None or q['origin'] is None or q['direction'] is None:
            bad.append((r, rep['module'], 'the query did not clone the NEE operands'))
        if q['legacy_helper_was_wrong']:
            legacy_wrong.append(rep['ident'].split('.')[0])
    if mods != 10:
        bad.append((r, '-', f'{mods} patched modules, want 10'))
    if want['mode'] != 'control':
        if CENSUS is None:
            CENSUS = (writes, skipped)
        elif (writes, skipped) != CENSUS:
            bad.append((r, '-', f'painted/skipped {(writes, skipped)} != {CENSUS}'))
        print(f'  {r:16s} 10 modules, {writes} painted writes, {skipped} benign '
              f'skips, flags={want["flags"]}, tmin={want["tmin"]}, '
              f'tmax={want["tmax"]}, k={want["k"]}, soft={want["soft"]}')
        # 90 sec 6: 79's ear glow used the broken helper. Record, per rung,
        # exactly which permutations it would have got wrong.
        print(f'                   legacy find_bounce_counter WOULD HAVE BEEN '
              f'WRONG on {len(legacy_wrong)}/10: {sorted(legacy_wrong)}')
    else:
        print(f'  {r:16s} 10 modules, 0 instructions emitted (the identity control)')
if bad:
    for b in bad[:12]:
        sys.stderr.write('    %s :: %s :: %s\n' % b)
    sys.exit(1)
PY

# --- 4. instruction census on the SHIPPED bytes -----------------------------
echo "=== 4. instruction census on the SHIPPED bytes"
python3 - "$MOD_DIR" "$SRC" "${ORDER[@]}" <<'PY' || exit 1
import glob, os, subprocess, sys
mod_dir, src, rungs = sys.argv[1], sys.argv[2], sys.argv[3:]
PASS = ('40c6faab52a13874', 'ab7f1822eeb0331b')
def dis(p):
    return subprocess.run(['spirv-dis', p], capture_output=True, text=True).stdout
bad = []
for r in rungs:
    ctl = r.endswith('-ctl')
    d = os.path.join(mod_dir, 'swaps.' + r)
    tot = dict(init=0, proceed=0, tget=0, trace_delta=0)
    for f in sorted(glob.glob(os.path.join(d, '*.rgs_reference_main.spv'))):
        h = os.path.basename(f).split('.')[0]
        a = dis(f)
        b = dis(os.path.join(src, os.path.basename(f)))
        n_i = a.count('OpRayQueryInitializeKHR')
        n_p = a.count('OpRayQueryProceedKHR')
        n_t = a.count('OpRayQueryGetIntersectionTKHR')
        dt = a.count('OpTraceRayKHR') - b.count('OpTraceRayKHR')
        want = 0 if (ctl or h in PASS) else 1
        if (n_i, n_p, n_t) != (want, want, want):
            bad.append(f'{r}/{h}: init/proceed/tget {(n_i, n_p, n_t)}, want {want} each')
        if dt != 0:
            bad.append(f'{r}/{h}: OpTraceRayKHR count changed by {dt} -- a QUERY '
                       f'is added, never a ray')
        tot['init'] += n_i; tot['proceed'] += n_p; tot['tget'] += n_t
    print(f"  {r:16s} {tot['init']} Initialize, {tot['proceed']} Proceed, "
          f"{tot['tget']} committed-T getters, 0 added traces")
if bad:
    for b in bad[:12]:
        sys.stderr.write('    ' + b + '\n')
    sys.exit(1)
PY

# --- 5. k=0 identity, over the WHOLE set ------------------------------------
echo "=== 5. k=0 identity control"
d=0
for f in "$SRC"/*.spv; do
    cmp -s "$f" "$MOD_DIR/swaps.earglow-rq-ctl/$(basename "$f")" || d=$((d+1))
done
[[ "$d" == 0 ]] || { echo "  !! earglow-rq-ctl differs from the base on $d files" >&2; exit 1; }
echo "  earglow-rq-ctl: 93 of 93 byte-identical to $BASE"
# and the live rungs must differ on exactly the 10 paintable permutations
for r in earglow-rq-hit earglow-rq earglow-rq-hi; do
    d=0
    for f in "$SRC"/*.spv; do
        cmp -s "$f" "$MOD_DIR/swaps.$r/$(basename "$f")" || d=$((d+1))
    done
    [[ "$d" == 10 ]] || { echo "  !! $r differs from the base on $d files, want exactly 10" >&2; exit 1; }
done
echo "  earglow-rq-hit / earglow-rq / earglow-rq-hi: 10 of 93 differ (the 10 paintable permutations)"

# --- 6. the verifier, on the shipped bytes ---------------------------------
echo "=== 6. verify_earglow_rq.py on the shipped .spv"
python3 "$VERIFY" "$MOD_DIR/swaps.earglow-rq-hit" --base "$SRC" --mode hit
python3 "$VERIFY" "$MOD_DIR/swaps.earglow-rq"     --base "$SRC" --mode glow --k "$K" --wide 4.0 --wrap 0.35
python3 "$VERIFY" "$MOD_DIR/swaps.earglow-rq-hi"  --base "$SRC" --mode glow --k "$K" --wide 6.0 --wrap 0.5
python3 "$VERIFY" --negative "$MOD_DIR/swaps.earglow-rq-ctl"

# --- 7. verifier NON-VACUITY: it must REJECT every decoy -------------------
echo "=== 7. verifier non-vacuity (each of these MUST fail)"
mkdir -p "$WORK/decoy"
reject () {  # $1 = label, rest = verifier argv
    local label="$1"; shift
    if python3 "$VERIFY" "$@" >/dev/null 2>&1; then
        echo "  !! VACUOUS: the verifier ACCEPTED $label" >&2; exit 1
    fi
    echo "  rejected: $label"
}
for dec in flags tmax counter; do
    patch_set "$WORK/decoy/$dec" --k "$K" --wide 4.0 --wrap 0.35 --decoy "$dec"
done
reject "--decoy flags (529 = CullBACK, v4's reversed segment)" \
       "$WORK/decoy/flags" --base "$SRC" --mode glow --k "$K" --wide 4.0 --wrap 0.35
reject "--decoy tmax (0.10 m -- reads through a whole head)" \
       "$WORK/decoy/tmax" --base "$SRC" --mode glow --k "$K" --wide 4.0 --wrap 0.35
reject "--decoy counter (79's legacy find_bounce_counter; 90 sec 1)" \
       "$WORK/decoy/counter" --base "$SRC" --mode glow --k "$K" --wide 4.0 --wrap 0.35
reject "the unpatched BASE read as a rung" \
       "$SRC" --base "$SRC" --mode glow --k "$K" --wide 4.0 --wrap 0.35
reject "the k=0 CONTROL read as a rung" \
       "$MOD_DIR/swaps.earglow-rq-ctl" --base "$SRC" --mode glow --k "$K" --wide 4.0 --wrap 0.35
reject "earglow-rq read as the -hit diagnostic" \
       "$MOD_DIR/swaps.earglow-rq" --base "$SRC" --mode hit
reject "earglow-rq-hit read as the glow rung" \
       "$MOD_DIR/swaps.earglow-rq-hit" --base "$SRC" --mode glow --k "$K" --wide 4.0 --wrap 0.35
reject "earglow-rq-hi read with earglow-rq's transfer (wide 4.0 / wrap 0.35)" \
       "$MOD_DIR/swaps.earglow-rq-hi" --base "$SRC" --mode glow --k "$K" --wide 4.0 --wrap 0.35
reject "a rung read against the WRONG flag word (517, 98's probe)" \
       "$MOD_DIR/swaps.earglow-rq" --base "$SRC" --mode glow --k "$K" --wide 4.0 --wrap 0.35 --flags 517
# 98's own primary ray-query rung, if it is parked: same capability, same
# module family, entirely different query. A free twelfth decoy.
if [[ -d "$INSTALL_DIR/skin.set/hunt-rayq-p" ]]; then
    reject "98's hunt-rayq-p (a ray query, but the WRONG one)" \
           "$INSTALL_DIR/skin.set/hunt-rayq-p" --base "$SRC" --mode glow --k "$K" --wide 4.0 --wrap 0.35
fi
rm -rf "$WORK/decoy"

# --- 8. the transfer, closed form, against the SHIPPED constants -----------
echo "=== 8. closed-form transfer check (numpy) against the shipped 1/ld bytes"
python3 - "$MOD_DIR" <<'PY' || exit 1
import glob, os, re, subprocess, sys
import numpy as np
mod_dir = sys.argv[1]
LD = np.array([0.00367, 0.00137, 0.00068])          # 71 / 52 / 53, metres
RUNGS = {'earglow-rq': 4.0, 'earglow-rq-hi': 6.0}
K = 0.22
bad = []
for rung, wide in RUNGS.items():
    f = sorted(glob.glob(os.path.join(mod_dir, 'swaps.' + rung,
                                      '*.rgs_reference_main.spv')))[0]
    asm = subprocess.run(['spirv-dis', f], capture_output=True, text=True).stdout
    vals = []
    for m in re.finditer(r'OpConstant %float ([0-9.e+-]+)\s*$', asm, re.M):
        try:
            vals.append(float(m.group(1)))
        except ValueError:
            pass
    # The rates the SHIPPED bytes carry, matched back to 1/ld and 1/(wide*ld).
    got1, got2 = [], []
    for ld in LD:
        c1 = [v for v in vals if abs(v - 1.0 / ld) <= 1e-3 * (1.0 / ld)]
        c2 = [v for v in vals if abs(v - 1.0 / (wide * ld)) <= 1e-3 / (wide * ld)]
        if not c1 or not c2:
            bad.append(f'{rung}: 1/ld or 1/({wide}ld) missing for ld={ld}')
            got1.append(1.0 / ld); got2.append(1.0 / (wide * ld))
        else:
            got1.append(c1[0]); got2.append(c2[0])
    a1 = np.array(got1); a2 = np.array(got2)
    t = np.array([1.0, 2.0, 4.0, 8.0, 18.0]) * 1e-3
    T = 0.5 * (np.exp(-np.outer(t, a1)) + np.exp(-np.outer(t, a2)))
    print(f'  {rung} (wide={wide}, rates read back from the .spv): '
          f'k={K}, transfer x k, per channel')
    print('     t(mm)        R          G          B      R/G')
    for i, tt in enumerate(t):
        r, g, b = T[i] * K
        print(f'   {tt*1e3:6.1f}   {r:9.5f}  {g:9.5f}  {b:9.5f}   '
              f'{(r/g if g > 0 else float("inf")):7.2f}')
    # 71 sec 2's claim: red spans ~2-3x over t in [1,6] mm on the soft rungs
    # (vs ~20x raw). That is the whole point of W3 and it is checked, not
    # asserted in prose.
    t2 = np.array([1.0, 6.0]) * 1e-3
    T2 = 0.5 * (np.exp(-np.outer(t2, a1)) + np.exp(-np.outer(t2, a2)))
    span = T2[0, 0] / T2[1, 0]
    raw = np.exp(-t2[0] * a1[0]) / np.exp(-t2[1] * a1[0])
    print(f'   red span over t in [1,6] mm: {span:.2f}x  '
          f'(raw single-lobe would be {raw:.2f}x)')
    if not (1.5 <= span <= 4.0):
        bad.append(f'{rung}: red span {span:.2f}x is outside 71 sec 2\'s '
                   f'~2-3x design window')
    # and hue must still redden with thickness: R/G must GROW with t
    rg = (T[:, 0] / T[:, 1])
    if not np.all(np.diff(rg) > 0):
        bad.append(f'{rung}: R/G does not increase monotonically with t -- '
                   f'the spectral falloff is broken')
if bad:
    for b in bad:
        sys.stderr.write('    ' + b + '\n')
    sys.exit(1)
PY

# --- 9. MANIFEST provenance -------------------------------------------------
echo "=== 9. MANIFEST provenance"
for r in "${ORDER[@]}"; do
    dest="$MOD_DIR/swaps.$r"
    sed -e "1s/^$BASE /$r /" "$SRC/MANIFEST.txt" > "$dest/MANIFEST.txt"
    grep -q "^$r " "$dest/MANIFEST.txt" || { echo "MANIFEST rewrite failed for $r" >&2; exit 1; }
    {
      echo "# earglow-rq (handoff/101): 70 W1 + W3 on a RAY QUERY. From the module's"
      echo "# own offset NEE origin along its own sun direction S; flags 545 ="
      echo "# Opaque|CullFrontFacingTriangles|SkipAABBs, NO TerminateOnFirstHit;"
      echo "# tmin 1.5mm, tmax 18mm; committed t = sun-path flesh thickness."
      echo "# Gate: class-1 skin AND backlit AND path counter == 0 (90's fixed helper)."
      case "$r" in
        *-ctl) echo "# THIS RUNG IS THE BASE, BYTE FOR BYTE (k=0). Control for the selector." ;;
        *-hit) echo "# DIAGNOSTIC: flat BLUE = query committed, flat RED = gate passed, miss." ;;
        *-hi)  echo "# k=$K ld=3.67/1.37/0.68mm; transfer 0.5*(e^-t/ld + e^-t/6ld), wrap 0.5" ;;
        *)     echo "# k=$K ld=3.67/1.37/0.68mm; transfer 0.5*(e^-t/ld + e^-t/4ld), wrap 0.35" ;;
      esac
      echo "# FALSIFIER: all dark on -hit = the BVH has no interior backfaces -> STOP."
      echo "# NEEDS a layer with VK_KHR_ray_query (98 sec 6/7). NOT working until the"
      echo "# screen says so. A/B against $BASE."
    } >> "$dest/MANIFEST.txt"
done
echo "  4 MANIFESTs written, provenance (src_ser/ser_sha/ptq_sha) carried verbatim"

echo
echo "=== shas (content = cat of all 93 .spv in name order)"
setsha () {  # cat every matching file in name order -> one sha
    # NB: -print0/sort -z/xargs -0. The repo path contains a space ("NVIDIA
    # Nsight Graphics"), so `ls | xargs cat` splits it into three nonexistent
    # filenames and hashes NOTHING (e3b0c442..., the sha of the empty string).
    find "$1" -maxdepth 1 -name "$2" -print0 | sort -z |
        xargs -0 cat | sha256sum | cut -c1-16
}
for r in "${ORDER[@]}"; do
    printf '  %-16s content=%s  raygen-half=%s\n' "$r" \
        "$(setsha "$MOD_DIR/swaps.$r" '*.spv')" \
        "$(setsha "$MOD_DIR/swaps.$r" '*.rgs_reference_main.spv')"
done
printf '  %-16s content=%s  raygen-half=%s\n' "(base)" \
    "$(setsha "$SRC" '*.spv')" "$(setsha "$SRC" '*.rgs_reference_main.spv')"

if (( DO_INSTALL )); then
    for r in "${ORDER[@]}"; do
        park="$INSTALL_DIR/skin.set/$r"
        mkdir -p "$park"; rm -f "$park"/*.spv "$park"/*.json "$park/MANIFEST.txt"
        cp -pf "$MOD_DIR/swaps.$r"/*.spv "$MOD_DIR/swaps.$r"/*.json \
               "$MOD_DIR/swaps.$r/MANIFEST.txt" "$park/"
        n=$(ls "$park"/*.spv | wc -l)
        [[ "$n" == 93 ]] || { echo "  !! parked $r has $n modules" >&2; exit 1; }
        for f in "$MOD_DIR/swaps.$r"/*.spv; do
            cmp -s "$f" "$park/$(basename "$f")" \
                || { echo "  !! parked $r differs from the build: $(basename "$f")" >&2; exit 1; }
        done
        echo "  parked -> $park (93 modules, cmp-verbatim against the build)"
    done
fi
echo
echo "select with skinspec=earglow-rq-ctl / -hit / earglow-rq / earglow-rq-hi"
echo "contract: ser=class, shadowset=full-shadow, ptq unchanged; RR OFF;"
echo "          sun LOW and BEHIND the character; photo mode. Read handoff/101 sec 7"
echo "          BEFORE the screen, and shoot -hit in the SAME frame as earglow-rq."
