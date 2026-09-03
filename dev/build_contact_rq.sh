#!/usr/bin/env bash
# contact-rq -- TRACED contact occlusion for skin, REPLACING 88's cavity cone.
# handoff/102-CONTACT-RQ.md is the document. Read its section 8 (the
# pre-registered interpretation table) BEFORE looking at a frame.
#
#   ./dev/build_contact_rq.sh              # build + 10 gates (nothing installed)
#   ./dev/build_contact_rq.sh --install    # ALSO park the four rungs
#   ./dev/build_contact_rq.sh --base NAME  # build on a different parked rung
#
# FOUR RUNGS, one variable each, all on the STANDING selection's own bytes.
#
#   contact-rq-ctl  k=0. The patcher emits NOTHING and rewrites nothing, so
#                   the output is BYTE-IDENTICAL to the base (gate 5, resting
#                   on gate 1's round-trip neutrality). Control for the
#                   SELECTOR and the LAYER, not for the splice.
#   contact-rq-hit  THE INSTRUMENT. The same estimator, painted flat as a grey
#                   ramp over the radiance writes on gated skin: white = no
#                   contact, black = fully occluded. Readable INDEPENDENTLY of
#                   the darkening, so "the trace works" and "the darkening
#                   looks right" are two separate questions.
#   contact-rq      K = 4 queries per skin pixel, hemisphere about N,
#                   tmax 10 cm. THE FEATURE.
#   contact-rq-8    K = 8. The quality axis, one variable against contact-rq.
#
# THE RAY: from the cone's own origin lifted 0.1 mm along N, K fixed
# cosine-weighted directions in the hemisphere about N (basis built in-module
# from N, whole set rotated by a gl_LaunchID-seeded angle), flags 517 =
# Opaque | TerminateOnFirstHit | SkipAABBs, NO face culling, tmin 1 mm,
# tmax 10 cm. o = hits/K, and `fac = 1 - 0.85*o` replaces 88's analytic cone
# at the cone's OWN OpFMul with the cone's OWN k. The cone is killed, not
# stacked: its occ is disconnected and its six tap rays get cull mask 0.
#
# All 77 compute and all 4 rgs_restirgi_* ship BYTE-VERBATIM and are
# cmp-asserted. Unlike 101, ALL TWELVE reference permutations are patched --
# the anchor here is 88's own cone, which 88 sec 4 reaches in 12/12.
#
# The rungs REQUIRE a layer that enables VK_KHR_ray_query on the VkDevice
# (swap_layer.c, handoff/98 sec 6/7). Prove the layer and the driver FIRST,
# without the game:
#     ./dev/selftest_contact_rq.sh
set -euo pipefail

MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="${CALLISTO_INSTALL_DIR:-$HOME/.local/lib/callisto}"
PY="$MOD_DIR/dev/patch_contact_rq.py"
VERIFY="$MOD_DIR/dev/verify_contact_rq.py"
WORK="$MOD_DIR/dev/disasm/contact_rq"

BASE=gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog
DO_INSTALL=0
while (( $# )); do
    case "$1" in
        --install) DO_INSTALL=1 ;;
        --base) BASE="${2:?--base needs a skin.set name}"; shift ;;
        -h|--help) sed -n '2,45p' "$0"; exit 0 ;;
        *) echo "unknown arg $1" >&2; exit 1 ;;
    esac
    shift
done

SRC="$INSTALL_DIR/skin.set/$BASE"

# --- 0. base provenance -----------------------------------------------------
[[ -f "$SRC/MANIFEST.txt" ]] || { echo "no $SRC/MANIFEST.txt -- the standing selection is not parked" >&2; exit 1; }
n_c=$(ls "$SRC"/*.dxil.spv | wc -l)
n_g=$(ls "$SRC"/*.rgs_restirgi_*.spv | wc -l)
n_r=$(ls "$SRC"/*.rgs_reference_main.spv | wc -l)
[[ "$n_c" == 77 ]] || { echo "$BASE has $n_c compute modules, expected 77" >&2; exit 1; }
[[ "$n_g" == 4  ]] || { echo "$BASE has $n_g restirgi modules, expected 4" >&2; exit 1; }
[[ "$n_r" == 12 ]] || { echo "$BASE has $n_r rgs_reference_main, expected 12" >&2; exit 1; }

mapfile -t TARGETS < <(cd "$SRC" && ls *.rgs_reference_main.spv | sed 's/\..*//')
(( ${#TARGETS[@]} == 12 )) || { echo "expected 12 reference raygens" >&2; exit 1; }

echo "=== 0. base: $BASE ($(head -1 "$SRC/MANIFEST.txt" | cut -c1-90))"

rm -rf "$WORK"; mkdir -p "$WORK/asm" "$WORK/rt"
for h in "${TARGETS[@]}"; do
    spirv-dis "$SRC/$h.rgs_reference_main.spv" -o "$WORK/asm/$h.spvasm"
done

# --- 1. the pipeline is byte-neutral on the reference raygens ---------------
# Everything the -ctl rung claims rests on this: at k=0 the patcher emits no
# instructions, rewrites no operand, and writes the disassembly straight back.
echo "=== 1. round-trip neutrality (spirv-dis -> spirv-as == base bytes)"
for h in "${TARGETS[@]}"; do
    spirv-as --target-env spv1.4 "$WORK/asm/$h.spvasm" -o "$WORK/rt/$h.spv"
    cmp -s "$SRC/$h.rgs_reference_main.spv" "$WORK/rt/$h.spv" \
        || { echo "  !! $h does not round-trip -- no control built on it is meaningful" >&2; exit 1; }
done
echo "  12 of 12 reference permutations round-trip byte-identically"
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
                > "$CB_O/$0.contactrq.report.json"'
    rm -f "$WORK/.args"
    local n; n=$(ls "$out"/*.spv 2>/dev/null | wc -l)
    [[ "$n" == 12 ]] || { echo "  !! $out produced $n modules, want 12" >&2; exit 1; }
}

assemble () {   # $1 = dest, $2 = patched-raygen dir, $3 = 1 if the 12 must be
                #      byte-identical to the base (the k=0 control)
    local dest="$1" src="$2" identical="${3:-0}"
    rm -rf "$dest"; mkdir -p "$dest"
    cp -pf "$src"/*.spv "$src"/*.json "$dest/"
    cp -pf "$SRC"/*.dxil.spv "$SRC"/*.rgs_restirgi_*.spv "$dest/"
    for f in "$SRC"/*.dxil.spv "$SRC"/*.rgs_restirgi_*.spv; do
        cmp -s "$f" "$dest/$(basename "$f")" \
            || { echo "  !! verbatim copy differs: $(basename "$f")" >&2; exit 1; }
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
ORDER=(contact-rq-ctl contact-rq-hit contact-rq contact-rq-8)
declare -A RUNG_ARGS=(
    [contact-rq-ctl]="--k 0 --rays 4"
    [contact-rq-hit]="--k 1 --rays 4 --mode hit"
    [contact-rq]="--k 1 --rays 4"
    [contact-rq-8]="--k 1 --rays 8"
)
declare -A RUNG_IDENT=([contact-rq-ctl]=1)
for r in "${ORDER[@]}"; do
    # shellcheck disable=SC2086
    patch_set "$WORK/p.$r" ${RUNG_ARGS[$r]}
    assemble "$MOD_DIR/swaps.$r" "$WORK/p.$r" "${RUNG_IDENT[$r]:-0}"
    echo "  swaps.$r: 93 modules, $( (( ${RUNG_IDENT[$r]:-0} )) && echo '12 identity' || echo '12 patched'), spirv-val (vulkan1.4) clean"
done
for pair in "contact-rq-hit contact-rq" "contact-rq contact-rq-8" \
            "contact-rq-hit contact-rq-8"; do
    set -- $pair; d=0
    for h in "${TARGETS[@]}"; do
        cmp -s "$MOD_DIR/swaps.$1/$h.rgs_reference_main.spv" \
               "$MOD_DIR/swaps.$2/$h.rgs_reference_main.spv" || d=$((d+1))
    done
    [[ "$d" == 12 ]] || { echo "  !! only $d of 12 differ between $1 and $2" >&2; exit 1; }
done
echo "  12 of 12 differ between every pair of the three live rungs"

# --- 3. coverage census, from the REPORTS (never from byte counts; 42) ------
echo "=== 3. coverage census"
python3 - "$MOD_DIR" "${ORDER[@]}" <<'PY' || exit 1
import glob, json, os, sys
mod_dir, rungs = sys.argv[1], sys.argv[2:]
# Stated HERE, independently of what the build script asked the patcher for:
# a rung that silently changed its flags or its bracket must fail this gate
# even if the request above changed with it.
WANT = {
    'contact-rq-ctl': dict(ctl=True),
    'contact-rq-hit': dict(mode='hit',  rays=4, flags=517, tmin=0.001, tmax=0.10),
    'contact-rq':     dict(mode='dark', rays=4, flags=517, tmin=0.001, tmax=0.10),
    'contact-rq-8':   dict(mode='dark', rays=8, flags=517, tmin=0.001, tmax=0.10),
}
bad = []
for r in rungs:
    d = os.path.join(mod_dir, 'swaps.' + r)
    want = WANT[r]
    mods = painted = skipped = cones = taps = 0
    legacy_wrong, base_sample = [], []
    for f in sorted(glob.glob(os.path.join(d, '*.contactrq.report.json'))):
        rep = json.load(open(f))
        q = rep['contact_rq']
        mods += 1
        h = rep['ident'].split('.')[0]
        if rep.get('spirv_val') != 'clean':
            bad.append((r, rep['module'], 'spirv-val not clean'))
        if q['legacy_helper_was_wrong']:
            legacy_wrong.append(h)
        if q['base_cone_gate_was_sample']:
            base_sample.append(h)
        if want.get('ctl'):
            if q.get('emitted') != 0:
                bad.append((r, rep['module'], 'the control emitted instructions'))
            continue
        for key in ('mode', 'rays', 'tmin', 'tmax'):
            if q[key] != want[key]:
                bad.append((r, rep['module'], f'{key} {q[key]} != {want[key]}'))
        if q['ray_flags'] != want['flags']:
            bad.append((r, rep['module'], f"flags {q['ray_flags']} != {want['flags']}"))
        if q['decoy'] is not None:
            bad.append((r, rep['module'], 'a DECOY build reached a rung'))
        if q['gate_mask'] != 39:
            bad.append((r, rep['module'], f"gate cull mask {q['gate_mask']} != 39"))
        if q['cones_replaced'] != 3:
            bad.append((r, rep['module'], f"{q['cones_replaced']} cones replaced, want 3"))
        if q['taps_neutered'] != 6:
            bad.append((r, rep['module'], f"{q['taps_neutered']} taps neutered, want 6"))
        if q['cone_k'] is None:
            bad.append((r, rep['module'], "the cone's own k was not reused"))
        # the tap set: unit, upper hemisphere, and exactly `rays` of them
        for (cx, cy, cz) in q['tap_dirs']:
            if abs(cx*cx + cy*cy + cz*cz - 1.0) > 1e-9:
                bad.append((r, rep['module'], 'a tap direction is not unit'))
            if cz <= 0.0:
                bad.append((r, rep['module'], 'a tap direction leaves the hemisphere'))
        if len(q['tap_dirs']) != want['rays']:
            bad.append((r, rep['module'], 'tap count mismatch'))
        cones += q['cones_replaced']; taps += q['taps_neutered']
        painted += len(q['writes_painted']); skipped += len(q['writes_skipped'])
        for s in q['writes_skipped']:
            if s['why'] not in ('constant-zero', 'scalar-broadcast'):
                bad.append((r, rep['module'], 'unexpected skip: ' + s['why']))
    if mods != 12:
        bad.append((r, '-', f'{mods} patched modules, want 12'))
    if want.get('ctl'):
        print(f'  {r:16s} 12 modules, 0 instructions emitted (the identity control)')
    else:
        print(f'  {r:16s} 12 modules, {cones} cones replaced, {taps} taps neutered, '
              f'{painted} painted writes, {skipped} benign skips, '
              f"K={want['rays']}, flags={want['flags']}, tmin={want['tmin']}, "
              f"tmax={want['tmax']}")
    # 90 sec 1, recorded rather than hidden: the STANDING BASE's own cone gate
    # tested the SAMPLE counter on these permutations, so on them contact-rq
    # differs from the base rung in the counter as well as the estimator.
    print(f'                   base cone gated on the SAMPLE counter on '
          f'{len(base_sample)}/12: {sorted(base_sample)}')
if bad:
    for b in bad[:12]:
        sys.stderr.write('    %s :: %s :: %s\n' % b)
    sys.exit(1)
PY

# --- 4. instruction census on the SHIPPED bytes -----------------------------
echo "=== 4. instruction census on the SHIPPED bytes"
python3 - "$MOD_DIR" "$SRC" "${ORDER[@]}" <<'PY' || exit 1
import glob, os, re, subprocess, sys
mod_dir, src, rungs = sys.argv[1], sys.argv[2], sys.argv[3:]
RAYS = {'contact-rq-hit': 4, 'contact-rq': 4, 'contact-rq-8': 8}
def dis(p):
    return subprocess.run(['spirv-dis', p], capture_output=True, text=True).stdout
bad = []
for r in rungs:
    ctl = r.endswith('-ctl')
    want = 0 if ctl else RAYS[r]
    d = os.path.join(mod_dir, 'swaps.' + r)
    tot = dict(init=0, proceed=0, tget=0, live_taps=0)
    for f in sorted(glob.glob(os.path.join(d, '*.rgs_reference_main.spv'))):
        h = os.path.basename(f).split('.')[0]
        a = dis(f); b = dis(os.path.join(src, os.path.basename(f)))
        n_i = a.count('OpRayQueryInitializeKHR')
        n_p = a.count('OpRayQueryProceedKHR')
        n_t = a.count('OpRayQueryGetIntersectionTypeKHR')
        if (n_i, n_p, n_t) != (want, want, want):
            bad.append(f'{r}/{h}: init/proceed/type {(n_i,n_p,n_t)}, want {want}')
        if a.count('OpRayQueryGetIntersectionTKHR'):
            bad.append(f'{r}/{h}: reads t -- this asks a BOOLEAN')
        dt = a.count('OpTraceRayKHR') - b.count('OpTraceRayKHR')
        if dt != 0:
            bad.append(f'{r}/{h}: OpTraceRayKHR count changed by {dt}')
        # every flags-16 cone tap must be neutered on a live rung
        live = len(re.findall(r'OpTraceRayKHR %\w+ %uint_16 (?!%uint_0\b)', a))
        n16 = len(re.findall(r'OpTraceRayKHR %\w+ %uint_16 ', a))
        if n16 != 6:
            bad.append(f'{r}/{h}: {n16} flags-16 cone taps, want 6')
        if not ctl and live:
            bad.append(f'{r}/{h}: {live} cone taps still carry a live cull mask')
        if ctl and live != 6:
            bad.append(f'{r}/{h}: the CONTROL neutered {6-live} cone taps')
        tot['init'] += n_i; tot['proceed'] += n_p; tot['tget'] += n_t
        tot['live_taps'] += live
    print(f"  {r:16s} {tot['init']} Initialize, {tot['proceed']} Proceed, "
          f"{tot['tget']} committed-type getters, 0 committed-T getters, "
          f"0 added traces, {tot['live_taps']} live cone taps")
if bad:
    for b in bad[:12]:
        sys.stderr.write('    ' + b + '\n')
    sys.exit(1)
PY

# --- 5. k=0 identity, over the WHOLE set ------------------------------------
echo "=== 5. k=0 identity control"
d=0
for f in "$SRC"/*.spv; do
    cmp -s "$f" "$MOD_DIR/swaps.contact-rq-ctl/$(basename "$f")" || d=$((d+1))
done
[[ "$d" == 0 ]] || { echo "  !! contact-rq-ctl differs from the base on $d files" >&2; exit 1; }
echo "  contact-rq-ctl: 93 of 93 byte-identical to $BASE"
for r in contact-rq-hit contact-rq contact-rq-8; do
    d=0
    for f in "$SRC"/*.spv; do
        cmp -s "$f" "$MOD_DIR/swaps.$r/$(basename "$f")" || d=$((d+1))
    done
    [[ "$d" == 12 ]] || { echo "  !! $r differs from the base on $d files, want exactly 12" >&2; exit 1; }
done
echo "  contact-rq-hit / contact-rq / contact-rq-8: 12 of 93 differ (all 12 reference permutations)"

# --- 6. the verifier, on the shipped bytes ---------------------------------
echo "=== 6. verify_contact_rq.py on the shipped .spv"
python3 "$VERIFY" "$MOD_DIR/swaps.contact-rq-hit" --base "$SRC" --mode hit  --rays 4
python3 "$VERIFY" "$MOD_DIR/swaps.contact-rq"     --base "$SRC" --mode dark --rays 4
python3 "$VERIFY" "$MOD_DIR/swaps.contact-rq-8"   --base "$SRC" --mode dark --rays 8
python3 "$VERIFY" --negative "$SRC"

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
for dec in flags tmax counter stack basis; do
    patch_set "$WORK/decoy/$dec" --k 1 --rays 4 --decoy "$dec"
done
reject "--decoy flags (545 = CullFrontFacing, 101's THICKNESS word)" \
       "$WORK/decoy/flags" --base "$SRC" --mode dark --rays 4
reject "--decoy tmax (0.018 m -- 101's T_SEG, an ear, not a reach)" \
       "$WORK/decoy/tmax" --base "$SRC" --mode dark --rays 4
reject "--decoy counter (79/85's legacy find_bounce_counter; 90 sec 1)" \
       "$WORK/decoy/counter" --base "$SRC" --mode dark --rays 4
reject "--decoy stack (the traced term ADDED to a live analytic cone)" \
       "$WORK/decoy/stack" --base "$SRC" --mode dark --rays 4
reject "--decoy basis (a fixed WORLD frame instead of one built from N)" \
       "$WORK/decoy/basis" --base "$SRC" --mode dark --rays 4
reject "the unpatched BASE read as a rung" \
       "$SRC" --base "$SRC" --mode dark --rays 4
reject "the k=0 CONTROL read as a rung" \
       "$MOD_DIR/swaps.contact-rq-ctl" --base "$SRC" --mode dark --rays 4
reject "contact-rq read as the -hit instrument" \
       "$MOD_DIR/swaps.contact-rq" --base "$SRC" --mode hit --rays 4
reject "contact-rq-hit read as the darkening rung" \
       "$MOD_DIR/swaps.contact-rq-hit" --base "$SRC" --mode dark --rays 4
reject "contact-rq-8 read as K=4 (the quality axis cannot be silently swapped)" \
       "$MOD_DIR/swaps.contact-rq-8" --base "$SRC" --mode dark --rays 4
reject "contact-rq read as K=8" \
       "$MOD_DIR/swaps.contact-rq" --base "$SRC" --mode dark --rays 8
reject "contact-rq read against 101's flag word (545)" \
       "$MOD_DIR/swaps.contact-rq" --base "$SRC" --mode dark --rays 4 --flags 545
# Parked rungs that are REAL ray queries in this exact module family, and the
# WRONG one. Free decoys, and the strongest ones available.
for other in earglow-rq earglow-rq-hit hunt-rayq-p; do
    if [[ -d "$INSTALL_DIR/skin.set/$other" ]]; then
        reject "$other (a ray query in this raygen, but the wrong question)" \
               "$INSTALL_DIR/skin.set/$other" --base "$SRC" --mode dark --rays 4
    fi
done
# 88's own analytic cone on the fixed gate: the A/B partner, and it must not
# read as a traced rung.
if [[ -d "$INSTALL_DIR/skin.set/gi-50b-bleed-oil-sheen-deep-clothhi-cone2allgf" ]]; then
    reject "88/90's -cone2allgf (the analytic cone, the A/B partner)" \
           "$INSTALL_DIR/skin.set/gi-50b-bleed-oil-sheen-deep-clothhi-cone2allgf" \
           --base "$SRC" --mode dark --rays 4
fi
rm -rf "$WORK/decoy"

# --- 8. the estimator, closed form, against the SHIPPED direction constants --
echo "=== 8. closed-form estimator check (numpy) against the shipped tap set"
python3 - "$MOD_DIR" <<'PY' || exit 1
import glob, os, re, subprocess, sys
import numpy as np
mod_dir = sys.argv[1]
TMAX, TMIN = 0.10, 0.001
RUNGS = {'contact-rq': 4, 'contact-rq-8': 8}
bad = []


def taps_from_spv(path):
    """Read the K (cx, cy, cz) tap coefficients back OUT of the shipped
    module, by walking each OpRayQueryInitializeKHR's direction operand."""
    asm = subprocess.run(['spirv-dis', '--no-color', path],
                         capture_output=True, text=True).stdout.split('\n')
    d = {}
    for l in asm:
        m = re.match(r'\s*(%\w+)\s*=\s*(.*?)\s*$', l)
        if m:
            d.setdefault(m.group(1), m.group(2))
    def fv(t):
        m = re.match(r'OpConstant %float (\S+)$', d.get(t, ''))
        return float(m.group(1)) if m else None
    out = []
    for l in asm:
        m = re.match(r'\s*OpRayQueryInitializeKHR\s+(.+?)\s*$', l)
        if not m:
            continue
        dirid = m.group(1).split()[6]
        a1 = re.match(r'OpFAdd %v3float (%\w+) (%\w+)$', d.get(dirid, ''))
        a2 = re.match(r'OpFAdd %v3float (%\w+) (%\w+)$', d.get(a1.group(1), ''))
        c = []
        for t in (a2.group(1), a2.group(2), a1.group(2)):
            v = re.match(r'OpVectorTimesScalar %v3float %\w+ (%\w+)$', d.get(t, ''))
            c.append(fv(v.group(1)))
        out.append(tuple(c))
    return out


def occ_discrete(T, dw, npsi=2048):
    """o for a synthetic half-space: an infinite wall standing perpendicular
    to the tangent plane at horizontal distance dw. The per-pixel rotation is
    uniform in psi, so the expectation over pixels is the mean over psi."""
    T = np.asarray(T)
    psi = np.linspace(0.0, 2.0 * np.pi, npsi, endpoint=False)
    # wall normal M = (1, 0, 0) in the (T, B, N) frame; the rotation carries
    # the tap azimuth, so M.dir = cx cos(psi) - cy sin(psi)
    md = np.outer(np.cos(psi), T[:, 0]) - np.outer(np.sin(psi), T[:, 1])
    with np.errstate(divide='ignore', invalid='ignore'):
        t = np.where(md > 0, dw / md, np.inf)
    return float(np.mean((t > TMIN) & (t < TMAX)))


def occ_analytic(dw, n=4096):
    """The same wall against a CONTINUOUS cosine-weighted hemisphere -- what
    the K-tap estimator is estimating."""
    rng = np.random.default_rng(7)
    u1, u2 = rng.random(n * n // 64), rng.random(n * n // 64)
    r, ph = np.sqrt(u1), 2 * np.pi * u2
    x, z = r * np.cos(ph), np.sqrt(1 - u1)
    with np.errstate(divide='ignore', invalid='ignore'):
        t = np.where(x > 0, dw / x, np.inf)
    return float(np.mean((t > TMIN) & (t < TMAX)))


for rung, K in RUNGS.items():
    fs = sorted(glob.glob(os.path.join(mod_dir, 'swaps.' + rung,
                                       '*.rgs_reference_main.spv')))
    sets = {tuple(sorted(taps_from_spv(f))) for f in fs}
    if len(sets) != 1:
        bad.append(f'{rung}: the 12 modules do not share one tap set')
    T = list(sets.pop())
    if len(T) != K:
        bad.append(f'{rung}: {len(T)} taps read back from the .spv, want {K}')
        continue
    for (cx, cy, cz) in T:
        if abs(cx * cx + cy * cy + cz * cz - 1.0) > 2e-6:
            bad.append(f'{rung}: a shipped tap is not unit')
        if cz <= 0:
            bad.append(f'{rung}: a shipped tap leaves the hemisphere')
    print(f'  {rung} (K={K}, tap coefficients read back from the .spv):')
    print('     wall d(cm)   o(K taps)   o(cosine-weighted, continuous)')
    prev = None
    for dcm in (1.0, 5.0, 9.0, 11.0):
        od = occ_discrete(T, dcm * 1e-2)
        oa = occ_analytic(dcm * 1e-2)
        print(f'   {dcm:9.0f}   {od:9.4f}   {oa:9.4f}')
        if dcm == 1.0 and not (0.35 <= od <= 0.55):
            bad.append(f'{rung}: a wall at 1 cm reads o={od:.3f}; a half-space '
                       f'inside tmax should occlude about half the hemisphere')
        if dcm == 11.0 and od != 0.0:
            bad.append(f'{rung}: a wall at 11 cm reads o={od:.3f}, but tmax is '
                       f'10 cm -- the reach is wrong')
        if prev is not None and od > prev + 1e-9:
            bad.append(f'{rung}: o is not monotone decreasing in distance')
        prev = od
    # the K-tap estimator must track the thing it estimates
    err = max(abs(occ_discrete(T, d * 1e-2) - occ_analytic(d * 1e-2))
              for d in (1.0, 5.0, 9.0))
    print(f'   max |K-tap - continuous| over d in [1, 9] cm: {err:.4f}')
    if err > (0.20 if K == 4 else 0.12):
        bad.append(f'{rung}: the K={K} estimator is biased by {err:.3f} '
                   f'against the continuous cosine-weighted answer')
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
      echo "# contact-rq (handoff/102): TRACED contact occlusion, REPLACING 88's"
      echo "# analytic cavity cone at the cone's own site with the cone's own k=0.85."
      echo "# K queries in the hemisphere about N from the cone's own origin + 0.1mm*N;"
      echo "# flags 517 = Opaque|TerminateOnFirstHit|SkipAABBs, no face culling;"
      echo "# tmin 1mm, tmax 10cm; o = hits/K; fac = 1 - 0.85*o."
      echo "# Gate: class-1 skin AND path counter == 0 (90's fixed helper), then"
      echo "# each light's own lit condition at its own site."
      echo "# THE ANALYTIC CONE IS DEAD in this rung: its occ is disconnected and"
      echo "# its six tap rays carry cull mask 0."
      case "$r" in
        *-ctl) echo "# THIS RUNG IS THE BASE, BYTE FOR BYTE (k=0). Control for the selector." ;;
        *-hit) echo "# INSTRUMENT: flat grey ramp on gated skin, white = clear, black = occluded." ;;
        *-8)   echo "# K = 8 queries per skin pixel. The quality axis." ;;
        *)     echo "# K = 4 queries per skin pixel. The feature." ;;
      esac
      echo "# NEEDS a layer with VK_KHR_ray_query (98 sec 6/7). NOT working until the"
      echo "# screen says so. A/B against $BASE."
    } >> "$dest/MANIFEST.txt"
done
echo "  4 MANIFESTs written, provenance (src_ser/ser_sha/ptq_sha) carried verbatim"

echo
echo "=== shas (content = cat of all 93 .spv in name order)"
setsha () {  # cat every matching file in name order -> one sha
    # NB: -print0/sort -z/xargs -0. The repo path contains a space, so
    # `ls | xargs cat` hashes NOTHING (e3b0c442..., the empty string).
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
echo "select with skinspec=contact-rq-ctl / -hit / contact-rq / contact-rq-8"
echo "contract: ser=class, shadowset=full-shadow REQUIRED; ptq unchanged; RR OFF;"
echo "          photo mode, camera pinned, sun HIGH enough that ears, neck and"
echo "          under-chin are DIRECT-lit -- a multiply is invisible in shade."
echo "          Read handoff/102 sec 8 BEFORE the screen, and shoot -hit FIRST."
