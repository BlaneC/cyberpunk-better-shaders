#!/usr/bin/env bash
# earglow-rq2 -- ear glow with an INSTANCE-MATCH gate. handoff/101 sec 12/13.
#
# `earglow-rq` was shot and LEAKED: the glow landed at the hairline, under the
# collar, on the far side of the ear and on a shaded eyelid, and barely on the
# ear rim itself. 70 W1's claim -- "the first backface within 18 mm sunward IS
# the far wall of flesh" -- is false wherever another mesh sits within 18 mm:
# hair cards on the scalp, the inner surface of clothing, the eyeball behind an
# eyelid. This build adds ONE variable: a second ray query on the module's own
# primary view ray (98's query, flags 517, +/-0.1% bracket) and an equality on
# the two committed InstanceIds. Same instance -> accept. Different -> reject.
#
# Three rungs. The CONTROL is unchanged and is NOT rebuilt here: earglow-rq-ctl
# is byte-identical to the base and this script asserts that rather than
# re-deriving it (run ./dev/build_earglow_rq.sh first if it is missing).
#
#   ./dev/build_earglow_rq2.sh [--install] [--base <skin.set name>]
#
# Nine gates, all offline, then the driver self-test:
#   0 base provenance 77/4/12         5 identity: ctl 93/93, live 10/93
#   1 dis->as byte-neutral            6 verify_earglow_rq2.py + --negative
#   2 patch + spirv-val vulkan1.4     7 non-vacuity: the decoys must be REJECTED
#   3 coverage census from reports    8 closed-form transfer (numpy)
#   4 instruction census on bytes     9 MANIFEST provenance
#   then: ./dev/selftest_earglow_rq.sh   (layer + driver, no game)
set -euo pipefail

MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="${CALLISTO_INSTALL_DIR:-$HOME/.local/lib/callisto}"
PY="$MOD_DIR/dev/patch_earglow_rq2.py"
VERIFY="$MOD_DIR/dev/verify_earglow_rq2.py"
VERIFY1="$MOD_DIR/dev/verify_earglow_rq.py"
WORK="$MOD_DIR/dev/disasm/earglow_rq2"

BASE=gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog
CTL=earglow-rq-ctl
K=0.22
DO_INSTALL=0
while (( $# )); do
    case "$1" in
        --install) DO_INSTALL=1 ;;
        --base) BASE="${2:?--base needs a skin.set name}"; shift ;;
        -h|--help) sed -n '2,28p' "$0"; exit 0 ;;
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
[[ "$n_c" == 77 && "$n_g" == 4 && "$n_r" == 12 ]] \
    || { echo "$BASE is $n_c/$n_g/$n_r, expected 77/4/12" >&2; exit 1; }
[[ -d "$MOD_DIR/swaps.$CTL" ]] \
    || { echo "swaps.$CTL is missing -- run ./dev/build_earglow_rq.sh first; " \
              "the control is SHARED and is never rebuilt here" >&2; exit 1; }

mapfile -t REFS < <(cd "$SRC" && ls *.rgs_reference_main.spv | sed 's/\..*//')
TARGETS=()
for h in "${REFS[@]}"; do
    skip=0; for p in "${PASS[@]}"; do [[ "$h" == "$p" ]] && skip=1; done
    (( skip )) && continue
    TARGETS+=("$h")
done
(( ${#TARGETS[@]} == 10 )) || { echo "expected 10 paintable refs, have ${#TARGETS[@]}" >&2; exit 1; }
echo "=== 0. base: $BASE ($(head -1 "$SRC/MANIFEST.txt" | cut -c1-80))"

rm -rf "$WORK"; mkdir -p "$WORK/asm" "$WORK/rt"
for h in "${TARGETS[@]}"; do
    spirv-dis "$SRC/$h.rgs_reference_main.spv" -o "$WORK/asm/$h.spvasm"
done

# --- 1. round-trip neutrality ----------------------------------------------
echo "=== 1. round-trip neutrality (spirv-dis -> spirv-as == base bytes)"
for h in "${TARGETS[@]}"; do
    spirv-as --target-env spv1.4 "$WORK/asm/$h.spvasm" -o "$WORK/rt/$h.spv"
    cmp -s "$SRC/$h.rgs_reference_main.spv" "$WORK/rt/$h.spv" \
        || { echo "  !! $h does not round-trip" >&2; exit 1; }
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
                > "$CB_O/$0.earglowrq2.report.json"'
    rm -f "$WORK/.args"
    local n; n=$(ls "$out"/*.spv 2>/dev/null | wc -l)
    [[ "$n" == 10 ]] || { echo "  !! $out produced $n modules, want 10" >&2; exit 1; }
}

assemble () {   # $1 = dest, $2 = patched-raygen dir
    local dest="$1" src="$2"
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
        cmp -s "$SRC/$h.rgs_reference_main.spv" "$dest/$h.rgs_reference_main.spv" \
            && { echo "  !! $h is byte-identical to the base" >&2; exit 1; }
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
ORDER=(earglow-rq2-hit earglow-rq2-hitw earglow-rq2 earglow-rq2-hi)
declare -A RUNG_ARGS=(
    [earglow-rq2-hit]="--k $K --mode hit"
    # -hitw is -hit with the GLOW RUNG'S OWN wrap envelope on the flat paint --
    # one variable, so its map is the glow's paintable set instead of a superset
    # of it (101 sec 14.3, sec 15). Same wrap as earglow-rq2: 0.35.
    [earglow-rq2-hitw]="--k $K --mode hitw --wide 4.0 --wrap 0.35"
    [earglow-rq2]="--k $K --wide 4.0 --wrap 0.35"
    [earglow-rq2-hi]="--k $K --wide 6.0 --wrap 0.5"
)
for r in "${ORDER[@]}"; do
    # shellcheck disable=SC2086
    patch_set "$WORK/p.$r" ${RUNG_ARGS[$r]}
    assemble "$MOD_DIR/swaps.$r" "$WORK/p.$r"
    echo "  swaps.$r: 93 modules, 10 patched, spirv-val (vulkan1.4) clean"
done
for pair in "earglow-rq2-hit earglow-rq2" "earglow-rq2 earglow-rq2-hi" \
            "earglow-rq2-hit earglow-rq2-hi" "earglow-rq2 earglow-rq" \
            "earglow-rq2-hit earglow-rq2-hitw" "earglow-rq2-hitw earglow-rq2"; do
    set -- $pair; d=0
    [[ -d "$MOD_DIR/swaps.$2" ]] || continue
    for h in "${TARGETS[@]}"; do
        cmp -s "$MOD_DIR/swaps.$1/$h.rgs_reference_main.spv" \
               "$MOD_DIR/swaps.$2/$h.rgs_reference_main.spv" || d=$((d+1))
    done
    [[ "$d" == 10 ]] || { echo "  !! only $d of 10 differ between $1 and $2" >&2; exit 1; }
done
echo "  10 of 10 differ between every pair of rungs, and vs earglow-rq itself"

# --- 3. coverage census, from the REPORTS ----------------------------------
echo "=== 3. coverage census"
python3 - "$MOD_DIR" "${ORDER[@]}" <<'PY' || exit 1
import glob, json, os, sys
mod_dir, rungs = sys.argv[1], sys.argv[2:]
# Stated HERE, independently of the argv above: a rung that silently changed
# its flags, its bracket or its match field must fail even if the request
# changed with it.
WANT = {
 'earglow-rq2-hit': dict(mode='hit',  k=0.22, soft=None),
 'earglow-rq2-hitw': dict(mode='hitw', k=0.22, soft=dict(wide=4.0, wrap=0.35)),
 'earglow-rq2':     dict(mode='glow', k=0.22, soft=dict(wide=4.0, wrap=0.35)),
 'earglow-rq2-hi':  dict(mode='glow', k=0.22, soft=dict(wide=6.0, wrap=0.5)),
}
bad, CENSUS = [], None
for r in rungs:
    d = os.path.join(mod_dir, 'swaps.' + r)
    want = WANT[r]
    mods = writes = skipped = 0
    for f in sorted(glob.glob(os.path.join(d, '*.earglowrq2.report.json'))):
        rep = json.load(open(f)); q = rep['earglow_rq2']; mods += 1
        if rep.get('spirv_val') != 'clean':
            bad.append((r, rep['module'], 'spirv-val not clean'))
        if q['mode'] != want['mode']:
            bad.append((r, rep['module'], f"mode {q['mode']} != {want['mode']}"))
        if q['k'] != want['k'] or q['soft'] != want['soft']:
            bad.append((r, rep['module'], f"k/soft {q['k']}/{q['soft']}"))
        writes += len(q['writes_added'])
        for s in q['writes_skipped']:
            if s['why'] not in ('constant-zero', 'scalar-broadcast'):
                bad.append((r, rep['module'], 'unexpected skip: ' + s['why']))
            skipped += 1
        if q['ray_flags_b'] != 545 or q['ray_flags_a'] != 517:
            bad.append((r, rep['module'], f"flags A/B {q['ray_flags_a']}/{q['ray_flags_b']}"))
        if q['tmin'] != 0.0015 or q['tmax'] != 0.018:
            bad.append((r, rep['module'], f"tmin/tmax {q['tmin']}/{q['tmax']}"))
        if q['bracket'] != [0.999, 1.001, 0.0001]:
            bad.append((r, rep['module'], f"bracket {q['bracket']}"))
        if q['commit_a'] != 'first' or q['commit_b'] != 'closest':
            bad.append((r, rep['module'], 'commit modes wrong'))
        if q['match_getter'] != 'OpRayQueryGetIntersectionInstanceIdKHR':
            bad.append((r, rep['module'], f"match field {q['match_getter']}"))
        if q['match_op'] != 'OpIEqual' or not q['match_gate']:
            bad.append((r, rep['module'], 'the instance match is absent or inverted'))
        if q['decoy'] is not None:
            bad.append((r, rep['module'], 'a DECOY build reached a rung'))
        if q['gate_mask'] != 39:
            bad.append((r, rep['module'], f"gate cull mask {q['gate_mask']}"))
        if want['mode'] == 'hit' and not q['diag_scaled_by_sun_radiance']:
            bad.append((r, rep['module'], 'the -hit paint is NOT scaled by the '
                                          'sun radiance (101 sec 12.3)'))
        if q['primary_line'] >= q['nee_line']:
            bad.append((r, rep['module'], 'query A does not dominate the splice'))
    if mods != 10:
        bad.append((r, '-', f'{mods} patched modules, want 10'))
    if CENSUS is None:
        CENSUS = (writes, skipped)
    elif (writes, skipped) != CENSUS:
        bad.append((r, '-', f'painted/skipped {(writes, skipped)} != {CENSUS}'))
    print(f'  {r:16s} 10 modules, {writes} painted writes, {skipped} benign '
          f'skips, A=517 B=545, tmin=0.0015, tmax=0.018, match=InstanceId, '
          f'k={want["k"]}, soft={want["soft"]}')
if bad:
    for b in bad[:12]:
        sys.stderr.write('    %s :: %s :: %s\n' % b)
    sys.exit(1)
PY

# --- 4. instruction census on the SHIPPED bytes ----------------------------
echo "=== 4. instruction census on the SHIPPED bytes"
python3 - "$MOD_DIR" "$SRC" "${ORDER[@]}" <<'PY' || exit 1
import glob, os, subprocess, sys
mod_dir, src, rungs = sys.argv[1], sys.argv[2], sys.argv[3:]
PASS = ('40c6faab52a13874', 'ab7f1822eeb0331b')
def dis(p):
    return subprocess.run(['spirv-dis', p], capture_output=True, text=True).stdout
bad = []
for r in rungs:
    d = os.path.join(mod_dir, 'swaps.' + r)
    tot = dict(init=0, proceed=0, iid=0, tget=0)
    for f in sorted(glob.glob(os.path.join(d, '*.rgs_reference_main.spv'))):
        h = os.path.basename(f).split('.')[0]
        a = dis(f); b = dis(os.path.join(src, os.path.basename(f)))
        n_i = a.count('OpRayQueryInitializeKHR')
        n_p = a.count('OpRayQueryProceedKHR')
        n_d = a.count('OpRayQueryGetIntersectionInstanceIdKHR')
        n_t = a.count('OpRayQueryGetIntersectionTKHR')
        n_c = a.count('OpRayQueryGetIntersectionInstanceCustomIndexKHR')
        dt = a.count('OpTraceRayKHR') - b.count('OpTraceRayKHR')
        want2 = 0 if h in PASS else 2
        want1 = 0 if h in PASS else 1
        if (n_i, n_p, n_d, n_t) != (want2, want2, want2, want1):
            bad.append(f'{r}/{h}: init/proceed/instanceId/T = '
                       f'{(n_i, n_p, n_d, n_t)}, want {(want2, want2, want2, want1)}')
        if n_c:
            bad.append(f'{r}/{h}: {n_c} x InstanceCustomIndex -- that is the decoy field')
        if dt != 0:
            bad.append(f'{r}/{h}: OpTraceRayKHR count changed by {dt}')
        tot['init'] += n_i; tot['proceed'] += n_p; tot['iid'] += n_d; tot['tget'] += n_t
    print(f"  {r:16s} {tot['init']} Initialize, {tot['proceed']} Proceed, "
          f"{tot['iid']} committed InstanceId, {tot['tget']} committed-T, 0 added traces")
if bad:
    for b in bad[:12]:
        sys.stderr.write('    ' + b + '\n')
    sys.exit(1)
PY

# --- 5. identity, over the WHOLE set ---------------------------------------
echo "=== 5. identity control (shared with 101 sec 6)"
d=0
for f in "$SRC"/*.spv; do
    cmp -s "$f" "$MOD_DIR/swaps.$CTL/$(basename "$f")" || d=$((d+1))
done
[[ "$d" == 0 ]] || { echo "  !! $CTL differs from the base on $d files" >&2; exit 1; }
echo "  $CTL: 93 of 93 byte-identical to $BASE (unchanged, not rebuilt here)"
for r in "${ORDER[@]}"; do
    d=0
    for f in "$SRC"/*.spv; do
        cmp -s "$f" "$MOD_DIR/swaps.$r/$(basename "$f")" || d=$((d+1))
    done
    [[ "$d" == 10 ]] || { echo "  !! $r differs on $d files, want exactly 10" >&2; exit 1; }
done
echo "  the four live rungs: 10 of 93 differ (the 10 paintable permutations)"

# --- 6. the verifier, on the shipped bytes ---------------------------------
echo "=== 6. verify_earglow_rq2.py on the shipped .spv"
python3 "$VERIFY" "$MOD_DIR/swaps.earglow-rq2-hit" --base "$SRC" --mode hit
python3 "$VERIFY" "$MOD_DIR/swaps.earglow-rq2-hitw" --base "$SRC" --mode hitw --wrap 0.35
python3 "$VERIFY" "$MOD_DIR/swaps.earglow-rq2"     --base "$SRC" --mode glow --k "$K" --wide 4.0 --wrap 0.35
python3 "$VERIFY" "$MOD_DIR/swaps.earglow-rq2-hi"  --base "$SRC" --mode glow --k "$K" --wide 6.0 --wrap 0.5
python3 "$VERIFY" --negative "$MOD_DIR/swaps.$CTL"

# --- 7. verifier NON-VACUITY -----------------------------------------------
echo "=== 7. verifier non-vacuity (each of these MUST fail)"
mkdir -p "$WORK/decoy"
reject () {  # $1 = label, rest = verifier argv
    local label="$1"; shift
    if python3 "$@" >/dev/null 2>&1; then
        echo "  !! VACUOUS: the verifier ACCEPTED $label" >&2; exit 1
    fi
    echo "  rejected: $label"
}
for dec in nomatch custom invert; do
    patch_set "$WORK/decoy/$dec" --k "$K" --wide 4.0 --wrap 0.35 --decoy "$dec"
done
G=(--base "$SRC" --mode glow --k "$K" --wide 4.0 --wrap 0.35)
reject "--decoy nomatch (no instance compare at all -- i.e. earglow-rq)" \
       "$VERIFY" "$WORK/decoy/nomatch" "${G[@]}"
reject "--decoy custom (InstanceCustomIndex instead of InstanceId)" \
       "$VERIFY" "$WORK/decoy/custom" "${G[@]}"
reject "--decoy invert (OpINotEqual: the gate accepts exactly what it must reject)" \
       "$VERIFY" "$WORK/decoy/invert" "${G[@]}"
reject "the unpatched BASE read as a rung" "$VERIFY" "$SRC" "${G[@]}"
reject "the k=0 CONTROL read as a rung" "$VERIFY" "$MOD_DIR/swaps.$CTL" "${G[@]}"
reject "earglow-rq2 read as the -hit diagnostic" \
       "$VERIFY" "$MOD_DIR/swaps.earglow-rq2" --base "$SRC" --mode hit
reject "earglow-rq2-hit read as the glow rung" \
       "$VERIFY" "$MOD_DIR/swaps.earglow-rq2-hit" "${G[@]}"
reject "earglow-rq2-hit read as -hitw (no wrap on the paint)" \
       "$VERIFY" "$MOD_DIR/swaps.earglow-rq2-hit" --base "$SRC" --mode hitw --wrap 0.35
reject "earglow-rq2-hitw read as the UNWRAPPED -hit" \
       "$VERIFY" "$MOD_DIR/swaps.earglow-rq2-hitw" --base "$SRC" --mode hit
reject "earglow-rq2-hitw read with the -hi wrap edge (0.5)" \
       "$VERIFY" "$MOD_DIR/swaps.earglow-rq2-hitw" --base "$SRC" --mode hitw --wrap 0.5
reject "earglow-rq2-hi read with earglow-rq2's transfer (wide 4.0 / wrap 0.35)" \
       "$VERIFY" "$MOD_DIR/swaps.earglow-rq2-hi" "${G[@]}"
# The cross-generation pair. Each verifier must reject the OTHER generation:
# one query is not two, and two queries are not one.
if [[ -d "$MOD_DIR/swaps.earglow-rq" ]]; then
    reject "101 sec 2's earglow-rq (ONE query) read as an rq2 rung" \
           "$VERIFY" "$MOD_DIR/swaps.earglow-rq" "${G[@]}"
    reject "earglow-rq2 read by the OLD verify_earglow_rq.py (TWO queries)" \
           "$VERIFY1" "$MOD_DIR/swaps.earglow-rq2" "${G[@]}"
fi
if [[ -d "$INSTALL_DIR/skin.set/hunt-rayq-p" ]]; then
    reject "98's hunt-rayq-p (a primary query, but only one, and no transfer)" \
           "$VERIFY" "$INSTALL_DIR/skin.set/hunt-rayq-p" "${G[@]}"
fi
rm -rf "$WORK/decoy"

# --- 8. the transfer, closed form, against the SHIPPED constants -----------
echo "=== 8. closed-form transfer check (numpy) against the shipped 1/ld bytes"
python3 - "$MOD_DIR" <<'PY' || exit 1
import glob, os, re, subprocess, sys
import numpy as np
mod_dir = sys.argv[1]
LD = np.array([0.00367, 0.00137, 0.00068])
RUNGS = {'earglow-rq2': 4.0, 'earglow-rq2-hi': 6.0}
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
    got1, got2 = [], []
    for ld in LD:
        c1 = [v for v in vals if abs(v - 1.0 / ld) <= 1e-3 * (1.0 / ld)]
        c2 = [v for v in vals if abs(v - 1.0 / (wide * ld)) <= 1e-3 / (wide * ld)]
        if not c1 or not c2:
            bad.append(f'{rung}: 1/ld or 1/({wide}ld) missing for ld={ld}')
            got1.append(1.0 / ld); got2.append(1.0 / (wide * ld))
        else:
            got1.append(c1[0]); got2.append(c2[0])
    a1, a2 = np.array(got1), np.array(got2)
    t = np.array([1.0, 2.0, 4.0, 8.0, 18.0]) * 1e-3
    T = 0.5 * (np.exp(-np.outer(t, a1)) + np.exp(-np.outer(t, a2)))
    print(f'  {rung} (wide={wide}, rates read back from the .spv): k={K}')
    print('     t(mm)        R          G          B      R/G')
    for i, tt in enumerate(t):
        r, g, b = T[i] * K
        print(f'   {tt*1e3:6.1f}   {r:9.5f}  {g:9.5f}  {b:9.5f}   {r/g:7.2f}')
    t2 = np.array([1.0, 6.0]) * 1e-3
    T2 = 0.5 * (np.exp(-np.outer(t2, a1)) + np.exp(-np.outer(t2, a2)))
    span = T2[0, 0] / T2[1, 0]
    raw = np.exp(-t2[0] * a1[0]) / np.exp(-t2[1] * a1[0])
    print(f'   red span over t in [1,6] mm: {span:.2f}x  '
          f'(raw single-lobe would be {raw:.2f}x)')
    if not (1.5 <= span <= 4.0):
        bad.append(f'{rung}: red span {span:.2f}x outside the 71 sec 2 window')
    if not np.all(np.diff(T[:, 0] / T[:, 1]) > 0):
        bad.append(f'{rung}: R/G is not monotonic in t')
if bad:
    for b in bad:
        sys.stderr.write('    ' + b + '\n')
    sys.exit(1)
PY

# --- 9. MANIFEST ------------------------------------------------------------
echo "=== 9. MANIFEST provenance"
src_ser=$(head -1 "$SRC/MANIFEST.txt")
for r in "${ORDER[@]}"; do
    dest="$MOD_DIR/swaps.$r"
    {
      echo "$r (base=$BASE) instance-match ear glow, handoff/101 sec 12/13"
      echo "# query A: flags 517, +/-0.1% bracket on |P|, committed InstanceId"
      echo "# query B: flags 545, tmin 0.0015 m, tmax 0.018 m, committed closest"
      echo "# accept <=> A committed AND B committed AND A.InstanceId == B.InstanceId"
      echo "# k=$K (untuned, 70/71), the ladder is the transfer SHAPE"
      echo "# src: $src_ser"
      grep -E '^# (src_ser|ser_sha|ptq_sha)' "$SRC/MANIFEST.txt" 2>/dev/null || true
      echo "# UNSHOT. Read handoff/101 sec 13 BEFORE the screen; the frame must"
      echo "# be BACKLIT, and -rq2-hit must be shot in the SAME frame."
    } > "$dest/MANIFEST.txt"
done
echo "  3 MANIFESTs written, provenance carried verbatim"

echo
echo "=== shas (content = cat of all 93 .spv in name order)"
setsha () {
    # -print0/sort -z/xargs -0: the repo path contains a space, and
    # `ls | xargs cat` would hash NOTHING (e3b0c442..., the empty string).
    find "$1" -maxdepth 1 -name "$2" -print0 | sort -z |
        xargs -0 cat | sha256sum | cut -c1-16
}
for r in "$CTL" "${ORDER[@]}"; do
    printf '  %-17s content=%s  raygen-half=%s\n' "$r" \
        "$(setsha "$MOD_DIR/swaps.$r" '*.spv')" \
        "$(setsha "$MOD_DIR/swaps.$r" '*.rgs_reference_main.spv')"
done
printf '  %-17s content=%s  raygen-half=%s\n' "(base)" \
    "$(setsha "$SRC" '*.spv')" "$(setsha "$SRC" '*.rgs_reference_main.spv')"

if (( DO_INSTALL )); then
    for r in "${ORDER[@]}"; do
        park="$INSTALL_DIR/skin.set/$r"
        rm -rf "$park"; mkdir -p "$park"
        cp -pf "$MOD_DIR/swaps.$r"/*.spv "$MOD_DIR/swaps.$r/MANIFEST.txt" "$park/"
        n=0
        for f in "$MOD_DIR/swaps.$r"/*.spv; do
            cmp -s "$f" "$park/$(basename "$f")" || { echo "  !! park differs: $f" >&2; exit 1; }
            n=$((n+1))
        done
        echo "  parked -> $park ($n modules, cmp-verbatim against the build)"
    done
fi

echo
echo "select with skinspec=earglow-rq2-hitw / earglow-rq2 / earglow-rq2-hi"
echo "  (earglow-rq2-hit is superseded by -hitw: 101 sec 14.3)"
echo "control: earglow-rq-ctl (unchanged, byte-identical to the base)"
echo "contract: ser=class, shadowset=full-shadow, ptq unchanged; RR OFF;"
echo "          sun LOW and BEHIND the head, camera on the SUN side of the ear;"
echo "          photo mode. Read handoff/101 sec 13 BEFORE the screen and shoot"
echo "          -rq2-hitw in the SAME frame as earglow-rq2."
