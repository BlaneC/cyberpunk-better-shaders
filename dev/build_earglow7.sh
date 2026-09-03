#!/usr/bin/env bash
# earglow7 -- the ear glow's TRANSMITTANCE, replaced with skin's. handoff/111.
#
#   "Mind tweaking the earglow to actually reduce the luminance of the sun and
#    tweak the hue of the light based on the actual transmittance of skin?"
#   "I need the default values we had before baked into
#    gi-50b-...-earglow-cap6-glintdense-curv, but just with better
#    transmittance"
#
# So this builds on the STANDING DEFAULT, and 110's v5/v6 families are neither
# stacked nor used.  NO cutoff, NO fade, the 6 mm floor where 101 sec 18 put
# it, query B's tmax at the shipped 18 mm, all three ray queries untouched.
# Every edit is inside the transfer:
#
#   k       0.22 -> 7.1497    in-place rewrite.  A NORMALISATION, not a
#                             brightness knob: it is chosen so the PEAK RED --
#                             the value at the floor -- is bit-comparable to
#                             the default's 0.094542, which is the level the
#                             user approved.  Gate 8 recomputes it from the
#                             shipped constants.
#   6 rates in-place rewrites the two lobes per channel, fitted by
#                             dev/transmit_model.py to a layered skin slab
#                             (Prahl's haemoglobin table, Jacques' skin fits)
#                             integrated over the sRGB channel bands.  Red's
#                             effective ld: 3.67 mm -> 1.55 mm.
#   tint    2 instructions    the FITTED per-channel amplitude (1, 0.0194,
#                             0.0846).  110 sec 4's machinery, values from the
#                             spectrum instead of from a knob.  R/G at the
#                             floor: 2.48 -> 45.3.
#   cos     1 instruction     w = NMax(-N.S, 0) replaces SmoothStep(0, 0.35,
#                             -N.S), which SATURATED AT 1 over almost the whole
#                             pinna.  This is the "reduce the luminance of the
#                             sun" half: 2.9x less flux at the knee, more below.
#
# +3 instructions, 7 constant rewrites, 2 declarations.  All 81 non-reference
# modules and the two pass-through raygens ship byte-verbatim.
#
#   ./dev/build_earglow7.sh [--install] [--base <skin.set name>]
#
# Ten gates, all offline.  NO DRIVER SELF-TEST: nothing about the ray queries
# changed -- same three objects, same flags, same getters, same counts, same
# tmin/tmax (gates 0 and 6 assert it against the base) -- so
# dev/selftest_earglow_rq.sh's case A/E claims already cover these bytes.
set -euo pipefail

MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="${CALLISTO_INSTALL_DIR:-$HOME/.local/lib/callisto}"
PY="$MOD_DIR/dev/patch_earglow7.py"
VERIFY="$MOD_DIR/dev/verify_earglow7.py"
MODEL="$MOD_DIR/dev/transmit_model.py"
WORK="$MOD_DIR/dev/disasm/earglow7"

BASE=gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog-earglow-cap6-glintdense-curv
DO_INSTALL=0
while (( $# )); do
    case "$1" in
        --install) DO_INSTALL=1 ;;
        --base) BASE="${2:?--base needs a skin.set name}"; shift ;;
        -h|--help) sed -n '2,40p' "$0"; exit 0 ;;
        *) echo "unknown arg $1" >&2; exit 1 ;;
    esac
    shift
done

SRC="$INSTALL_DIR/skin.set/$BASE"
PASS=(40c6faab52a13874 ab7f1822eeb0331b)

# --- 0. base provenance -----------------------------------------------------
[[ -f "$SRC/MANIFEST.txt" ]] || { echo "no $SRC/MANIFEST.txt" >&2; exit 1; }
n_c=$(ls "$SRC"/*.dxil.spv | wc -l)
n_g=$(ls "$SRC"/*.rgs_restirgi_*.spv | wc -l)
n_r=$(ls "$SRC"/*.rgs_reference_main.spv | wc -l)
[[ "$n_c" == 77 && "$n_g" == 4 && "$n_r" == 12 ]] \
    || { echo "$BASE is $n_c/$n_g/$n_r, expected 77/4/12" >&2; exit 1; }
mapfile -t REFS < <(cd "$SRC" && ls *.rgs_reference_main.spv | sed 's/\..*//')
TARGETS=()
for h in "${REFS[@]}"; do
    skip=0; for p in "${PASS[@]}"; do [[ "$h" == "$p" ]] && skip=1; done
    (( skip )) && continue
    TARGETS+=("$h")
done
(( ${#TARGETS[@]} == 10 )) || { echo "expected 10 paintable refs" >&2; exit 1; }
echo "=== 0. base: $BASE"
python3 - "$SRC" "${TARGETS[@]}" <<'PY' || exit 1
import os, subprocess, sys
src, targets = sys.argv[1], sys.argv[2:]
bad = []
for h in targets:
    a = subprocess.run(['spirv-dis', os.path.join(src, h + '.rgs_reference_main.spv')],
                       capture_output=True, text=True).stdout
    got = (a.count('OpRayQueryInitializeKHR'), a.count('OpRayQueryProceedKHR'),
           a.count('OpRayQueryGetIntersectionInstanceIdKHR'),
           a.count('OpRayQueryGetIntersectionTKHR'))
    if got != (3, 3, 2, 1):
        bad.append(f'{h}: {got}, want 3/3/2/1 -- not the earglow-cap6 stack')
    # the untouched default carries all nine of these, and nothing that has
    # been through 110 does
    for c in ('0.219999999', '0.0179999992', '0.00600000005', '272.479553',
              '729.927002', '1470.58826', '68.1198883', '182.48175',
              '367.647064', '0.349999994'):
        if f'OpConstant %float {c}\n' not in a:
            bad.append(f'{h}: no OpConstant %float {c} -- this is not the '
                       f'untouched standing default')
if bad:
    print('\n'.join(bad)); sys.exit(1)
print(f'  {len(targets)} paintable refs: 3/3/2/1 queries, the shipped '
      f'k/tmax/floor/rates/knee all present')
PY

mkdir -p "$WORK/asm"
for h in "${TARGETS[@]}"; do
    spirv-dis --no-color "$SRC/$h.rgs_reference_main.spv" > "$WORK/asm/$h.spvasm"
done

# --- 1. round-trip neutrality ----------------------------------------------
echo "=== 1. round-trip neutrality"
rm -rf "$WORK/rt"; mkdir -p "$WORK/rt"
for h in "${TARGETS[@]}"; do
    spirv-as --target-env spv1.4 "$WORK/asm/$h.spvasm" -o "$WORK/rt/$h.spv"
    cmp -s "$SRC/$h.rgs_reference_main.spv" "$WORK/rt/$h.spv" \
        || { echo "  !! $h does not round-trip" >&2; exit 1; }
done
echo "  ${#TARGETS[@]}/${#TARGETS[@]} dis->as byte-identical"

# --- 2. the model ----------------------------------------------------------
echo "=== 2. the transmittance model (dev/transmit_model.py)"
mkdir -p "$WORK/model"
python3 "$MODEL" --ref 0.006 --fb-derm 0.02 --emit "$WORK/model/r6.json" \
    | tee "$WORK/model/r6.txt" | sed -n '1,12p;/^TWO-LOBE/,/^SHIPPED/p;/^NORMAL/,/^$/p'
python3 "$MODEL" --ref 0.006 --fb-derm 0.01 --no-sensitivity \
    --emit "$WORK/model/r6lo.json" > "$WORK/model/r6lo.txt"
python3 "$MODEL" --ref 0.002 --fb-derm 0.02 --no-sensitivity \
    --emit "$WORK/model/r2.json" > "$WORK/model/r2.txt"
python3 - "$WORK/model" <<'PY' || exit 1
import json, os, sys
d = sys.argv[1]
for n, k, fb, ref in (('r6', 7.1497, 0.02, 0.006), ('r6lo', 7.2787, 0.01, 0.006),
                      ('r2', 0.4402, 0.02, 0.002)):
    m = json.load(open(os.path.join(d, n + '.json')))
    assert abs(m['k'] - k) < 1e-3, f'{n}: k {m["k"]}, expected {k}'
    assert m['f_blood'][0] == fb and m['ref_m'] == ref, n
    assert m['tint'][0] == 1.0 and 0 < m['tint'][1] < m['tint'][2] < 1, n
    for a1, a2 in m['rates_1_per_m']:
        assert a1 > a2 > 0 and abs(a2 - a1 / 4) > 1e-6, n
print('  three models emitted; k, tint order and refitted lobes as expected')
PY

# --- 3. patch + assemble ----------------------------------------------------
jobs="${CALLISTO_JOBS:-$(nproc 2>/dev/null || echo 4)}"
patch_set () {
    local out="$1"; shift
    mkdir -p "$out"
    printf '%s\n' "$@" > "$WORK/.args"
    printf '%s\0' "${TARGETS[@]}" | CB_O="$out" CB_P="$PY" CB_W="$WORK" \
        CB_A="$WORK/.args" xargs -0 -P "$jobs" -n1 bash -c '
            mapfile -t A < "$CB_A"
            python3 "$CB_P" "$CB_W/asm/$0.spvasm" "${A[@]}" --outdir "$CB_O" \
                > "$CB_O/$0.earglow7.report.json"'
    rm -f "$WORK/.args"
    local n; n=$(ls "$out"/*.spv 2>/dev/null | wc -l)
    [[ "$n" == 10 ]] || { echo "  !! $out produced $n modules, want 10" >&2; exit 1; }
}
assemble () {
    local dest="$1" src="$2" live="$3"
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
            || { echo "  !! pass-through $p differs" >&2; exit 1; }
    done
    for h in "${TARGETS[@]}"; do
        if (( live )); then
            cmp -s "$SRC/$h.rgs_reference_main.spv" "$dest/$h.rgs_reference_main.spv" \
                && { echo "  !! $h is byte-identical to the base" >&2; exit 1; }
        else
            cmp -s "$SRC/$h.rgs_reference_main.spv" "$dest/$h.rgs_reference_main.spv" \
                || { echo "  !! CONTROL $h differs from the base" >&2; exit 1; }
        fi
    done
    local n; n=$(ls "$dest"/*.spv | wc -l)
    [[ "$n" == 93 ]] || { echo "  !! $dest has $n modules" >&2; exit 1; }
    for f in "$dest"/*.spv; do
        spirv-val --target-env vulkan1.4 "$f" >/dev/null \
            || { echo "  !! spirv-val FAILED: $f" >&2; exit 1; }
    done
}

ORDER=(earglow7 earglow7-ss earglow7-hue1 earglow7-floor2 earglow7-ctl)
LIVE=(earglow7 earglow7-ss earglow7-hue1 earglow7-floor2)
M6="$WORK/model/r6.json"
M6LO="$WORK/model/r6lo.json"
M2="$WORK/model/r2.json"
# NOT associative arrays of flag STRINGS: MOD_DIR has a space in it
# ("NVIDIA Nsight Graphics"), so an unquoted ${RUNG_ARGS[$r]} splits the model
# path in half and argparse rejects the tail.  Real arrays, filled by name.
rung_args () {
    case "$1" in
        earglow7)        RA=(--model "$M6") ;;
        earglow7-ss)     RA=(--model "$M6" --angular smoothstep) ;;
        earglow7-hue1)   RA=(--model "$M6LO") ;;
        earglow7-floor2) RA=(--model "$M2" --floor 0.002) ;;
        earglow7-ctl)    RA=(--control) ;;
        *) echo "no args for rung $1" >&2; exit 1 ;;
    esac
}
verify_args () {
    case "$1" in
        earglow7)        VA=(--model "$M6") ;;
        earglow7-ss)     VA=(--model "$M6" --angular smoothstep) ;;
        earglow7-hue1)   VA=(--model "$M6LO") ;;
        earglow7-floor2) VA=(--model "$M2" --floor 0.002) ;;
        *) echo "no verify args for rung $1" >&2; exit 1 ;;
    esac
}
echo "=== 3. patch + assemble the ${#ORDER[@]} rungs"
for r in "${ORDER[@]}"; do
    live=1; [[ "$r" == earglow7-ctl ]] && live=0
    rung_args "$r"
    patch_set "$WORK/p.$r" "${RA[@]}"
    assemble "$MOD_DIR/swaps.$r" "$WORK/p.$r" "$live"
    echo "  swaps.$r: 93 modules, $(( live * 10 )) patched, spirv-val clean"
done

# --- 4. coverage census, from the REPORTS ----------------------------------
echo "=== 4. coverage census"
python3 - "$MOD_DIR" "${ORDER[@]}" <<'PY' || exit 1
import glob, json, os, sys
root, rungs = sys.argv[1], sys.argv[2:]
for r in rungs:
    reps = [json.load(open(f)) for f in
            sorted(glob.glob(os.path.join(root, 'swaps.' + r, '*.report.json')))]
    assert len(reps) == 10, f'{r}: {len(reps)} reports'
    assert all(x['spirv_val'] == 'clean' for x in reps), r
    e = [x['earglow7'] for x in reps]
    if e[0].get('mode') == 'control':
        assert all(x['emitted'] == 0 for x in e), r
        print(f'  {r:18s} control: 0 emitted, base asserted in all 10')
        continue
    ins = {x['added_instructions'] for x in e}
    rew = {len(x['rewrites']) for x in e}
    tint = {tuple(round(v, 6) for v in x['tint_applied']) for x in e}
    k = {round(x['k'], 4) for x in e}
    assert len(ins) == len(rew) == len(tint) == len(k) == 1, \
        f'{r}: modules disagree: ins={ins} rew={rew} tint={tint} k={k}'
    assert all(x['query_touched'] == 'nothing' for x in e), r
    assert all(x['cutoff'] is None and x['fade'] is None for x in e), r
    assert all(abs(x['tmax_m'] - 0.018) < 1e-6 for x in e), r
    print(f'  {r:18s} +{ins.pop()} instr, {rew.pop()} rewrites, k={k.pop()}, '
          f'tint={tint.pop()}, tmax untouched, no cutoff, no fade')
PY

# --- 5. instruction census on the SHIPPED bytes ----------------------------
echo "=== 5. instruction census on the SHIPPED bytes (vs the base, op by op)"
python3 - "$MOD_DIR" "$SRC" "${PASS[*]}" "${LIVE[@]}" <<'PY' || exit 1
import collections, os, re, subprocess, sys
root, src, rungs = sys.argv[1], sys.argv[2], sys.argv[4:]
skip = set(sys.argv[3].split())   # the two pass-through raygens carry no glow
def ops(p):
    a = subprocess.run(['spirv-dis', '--no-color', p], capture_output=True,
                       text=True).stdout
    c = collections.Counter()
    for l in a.split('\n'):
        m = re.match(r'\s*(?:%\w+\s*=\s*)?(Op\w+)', l)
        if m:
            c[m.group(1)] += 1
        m2 = re.match(r'\s*%\w+\s*=\s*OpExtInst %\w+ %\w+ (\w+)', l)
        if m2:
            c['ExtInst.' + m2.group(1)] += 1
    return c
for r in rungs:
    d = os.path.join(root, 'swaps.' + r)
    seen = set()
    for f in sorted(os.listdir(d)):
        if not f.endswith('.rgs_reference_main.spv'):
            continue
        h = f.split('.')[0]
        if h in skip:
            continue
        a, b = ops(os.path.join(src, f)), ops(os.path.join(d, f))
        diff = {k: b[k] - a[k] for k in set(a) | set(b) if b[k] != a[k]}
        seen.add(tuple(sorted(diff.items())))
    assert len(seen) == 1, f'{r}: modules differ in their op deltas: {seen}'
    print(f'  {r:18s} {dict(seen.pop())}')
PY

# --- 6. identity: everything outside the transfer is untouched -------------
echo "=== 6. identity control"
for r in "${ORDER[@]}"; do
    d="$MOD_DIR/swaps.$r"
    n=0
    for f in "$SRC"/*.dxil.spv "$SRC"/*.rgs_restirgi_*.spv; do
        cmp -s "$f" "$d/$(basename "$f")" || { echo "  !! $r: $(basename "$f")" >&2; exit 1; }
        n=$((n+1))
    done
    echo "  $r: $n non-raygen modules byte-identical to the base"
done
python3 "$VERIFY" --control "$MOD_DIR/swaps.earglow7-ctl" --base "$SRC"

# --- 7. the verifier --------------------------------------------------------
echo "=== 7. verify_earglow7.py on the shipped .spv"
for r in "${LIVE[@]}"; do
    printf '  %-18s ' "$r"
    verify_args "$r"
    python3 "$VERIFY" "$MOD_DIR/swaps.$r" --base "$SRC" "${VA[@]}"
done

# --- 8. verifier NON-VACUITY ------------------------------------------------
echo "=== 8. verifier non-vacuity (every one of these MUST be rejected)"
python3 "$VERIFY" --negative "$SRC" --model "$WORK/model/r6.json"
H="${TARGETS[0]}"
for dec in flatk flatrate notint tintswap rateswap cosraw cosdot cosboth wide4; do
    rm -rf "$WORK/d.$dec"
    python3 "$PY" "$WORK/asm/$H.spvasm" --outdir "$WORK/d.$dec" \
        --model "$WORK/model/r6.json" --decoy "$dec" > /dev/null
    if python3 "$VERIFY" "$WORK/d.$dec" --base "$SRC" \
            --model "$WORK/model/r6.json" --expect 1 > "$WORK/d.$dec.log" 2>&1; then
        echo "  !! decoy $dec was ACCEPTED" >&2; exit 1
    fi
    echo "  $(printf '%-10s' "$dec") rejected: $(head -1 "$WORK/d.$dec.log" | cut -c1-96)"
done
# cross-reads: each live rung judged against another rung's model must fail
for pair in "earglow7 r2.json 0.002" "earglow7-floor2 r6.json 0.006" \
            "earglow7 r6lo.json 0.006"; do
    set -- $pair
    if python3 "$VERIFY" "$MOD_DIR/swaps.$1" --base "$SRC" \
            --model "$WORK/model/$2" --floor "$3" > /dev/null 2>&1; then
        echo "  !! $1 passed against $2 -- the rungs are not distinguishable" >&2
        exit 1
    fi
    echo "  cross-read $1 vs $2 rejected"
done

# --- 9. closed-form transfer, from the SHIPPED constants -------------------
echo "=== 9. closed-form transfer, read back out of the .spv"
python3 - "$MOD_DIR" "$SRC" "${PASS[*]}" "${LIVE[@]}" <<'PY' || exit 1
import math, os, re, subprocess, sys
root, src, rungs = sys.argv[1], sys.argv[2], sys.argv[4:]
skip = set(sys.argv[3].split())
W709 = (0.2126, 0.7152, 0.0722)


def read(p):
    """The transfer's constants, found the way verify_earglow7 finds them:
    the chains are identified by their sun-radiance component index."""
    lines = subprocess.run(['spirv-dis', '--no-color', p], capture_output=True,
                           text=True).stdout.split('\n')
    d = {}
    for l in lines:
        m = re.match(r'\s*(%\w+)\s*=\s*(.*?)\s*$', l)
        if m:
            d.setdefault(m.group(1), m.group(2))

    def fv(t):
        m = re.match(r'OpConstant %float (\S+)$', d.get(t, ''))
        try:
            return float(m.group(1)) if m else None
        except ValueError:
            return None
    ksel = [t for t in d if re.match(r'OpSelect %float %\w+ %\w+ %\w+$', d[t])
            and re.match(r'OpConstant %float -0$',
                         d.get(d[t].split()[-1], ''))][0]
    k = fv(d[ksel].split()[3])
    # the float32 rounding of 0.006 is 0.00600000005, so this compares with a
    # tolerance -- an `in (0.006, ...)` here silently found nothing
    teff = [t for t in d if re.match(r'OpExtInst %float %\w+ NMax %\w+ %\w+$',
                                     d[t])
            and any(abs((fv(d[t].split()[-1]) or -1) - c) < 1e-8
                    for c in (0.006, 0.003, 0.002))][0]
    floor = fv(d[teff].split()[-1])
    w0 = [t for t in d if re.match(r'OpFMul %float %\w+ %\w+$', d[t])
          and ksel in d[t].split()][0]
    out = {}
    for t in d:
        if not re.match(r'OpFMul %float %\w+ %\w+$', d[t]) or w0 not in d[t].split():
            continue
        pre = [x for x in d[t].split()[2:] if x != w0][0]
        post = [u for u in d if re.match(r'OpFMul %float %\w+ %\w+$', d[u])
                and t in d[u].split()][0]
        srad = [x for x in d[post].split()[2:] if x != t][0]
        ch = int(re.match(r'OpCompositeExtract %float %\w+ (\d)$',
                          d[srad]).group(1))
        tint, half = 1.0, pre
        if not any(re.match(r'OpFAdd %float ', d.get(x, ''))
                   for x in d[half].split()[2:]):
            inner = [x for x in d[half].split()[2:]
                     if re.match(r'OpFMul %float ', d.get(x, ''))][0]
            tint = fv([x for x in d[half].split()[2:] if fv(x) is not None][0])
            half = inner
        add = [x for x in d[half].split()[2:]
               if re.match(r'OpFAdd %float ', d.get(x, ''))][0]
        rates = []
        for e in d[add].split()[2:]:
            mul = d[d[d[e].split()[-1]].split()[-1]]
            rates.append(fv([x for x in mul.split()[2:] if x != teff][0]))
        out[ch] = (tint, sorted(rates, reverse=True))
    return k, floor, out


def T(k, tint, rates, t):
    return k * tint * 0.5 * (math.exp(-rates[0] * t) + math.exp(-rates[1] * t))


SHIP = (0.22, (0.00367, 0.00137, 0.00068))


def ship(t):
    return [SHIP[0] * 0.5 * (math.exp(-t / l) + math.exp(-t / (4 * l)))
            for l in SHIP[1]]


for r in rungs:
    d = os.path.join(root, 'swaps.' + r)
    f = [x for x in sorted(os.listdir(d))
         if x.endswith('.rgs_reference_main.spv')
         and x.split('.')[0] not in skip][0]
    k, floor, ch = read(os.path.join(d, f))
    print(f'  {r}: k={k:.4f} floor={floor*1e3:.0f} mm  '
          f'tint={tuple(round(ch[c][0], 5) for c in (0, 1, 2))}')
    print('     t/mm      R         G         B       R/G     Y709    '
          'vs the default')
    for t in (0.002, 0.004, 0.006, 0.008, 0.012, 0.018):
        te = max(t, floor)
        v = [T(k, ch[c][0], ch[c][1], te) for c in (0, 1, 2)]
        s = ship(max(t, 0.006))
        y = sum(w * x for w, x in zip(W709, v))
        ys = sum(w * x for w, x in zip(W709, s))
        print(f'    {t*1e3:5.1f}  {v[0]:.3e} {v[1]:.3e} {v[2]:.3e} '
              f'{v[0]/max(v[1],1e-30):7.1f}  {y:.3e}  Y {y/ys:6.3f}x  '
              f'R {v[0]/s[0]:6.3f}x')
    peak = T(k, ch[0][0], ch[0][1], floor)
    assert abs(peak - 0.09454246757) < 5e-4 * 0.09454, \
        f'{r}: peak red {peak}, want the default 0.094542'
print('  every rung peaks at the default red, 0.094542')
PY

# --- 10. MANIFEST -----------------------------------------------------------
# THE LAUNCH CONTRACT, learned the hard way on 2026-09-03 17:00: a skin rung
# that ships rgs_* files is a "raygen-bearing rung" to sync_settings.sh, and
# it is REFUSED at launch -- swaps.skin/ wiped, status.txt reads
# skinspec=off:gi-no-manifest, ser materialised over the top -- unless its
# MANIFEST.txt carries src_ser="..." ser_sha=... ptq_sha=... .  Those live in
# the base's `# src:` line, so the base's whole manifest body is carried
# through (build_curv.sh's stack pattern), never re-typed.  110's earglow5/6
# family and 105's thinglow ship WITHOUT them and have never been served.
echo "=== 10. MANIFEST provenance (the sync_settings.sh launch contract)"
for r in "${ORDER[@]}"; do
    dest="$MOD_DIR/swaps.$r"
    rung_args "$r"
    sha=$(cat "$dest"/*.spv | sha256sum | cut -c1-16)
    sed -e "1s/^$BASE /$r /" \
        -e "1s|(base=[^)]*)|(base=$BASE, = the standing default + handoff/111 earglow7)|" \
        -e "1s|handoff/[0-9]* *\$|handoff/111|" \
        -e "/^# content sha /d" \
        "$SRC/MANIFEST.txt" > "$dest/MANIFEST.txt"
    grep -q "^$r " "$dest/MANIFEST.txt" || { echo "  !! MANIFEST rewrite failed for $r" >&2; exit 1; }
    {
        echo "# STACKED (handoff/111): the ear glow's TRANSMITTANCE, from dev/transmit_model.py."
        echo "# NO cutoff, NO fade, query B tmax 18 mm and the 6 mm floor as shipped;"
        echo "# the three ray queries, flags, getters and counts are the base's."
        echo "# rung args: ${RA[*]}"
        echo "# content sha $sha"
    } >> "$dest/MANIFEST.txt"
    echo "  swaps.$r/MANIFEST.txt   content sha $sha"
done

# --- 11. the launch contract, replayed -------------------------------------
# Exactly the three reads sync_settings.sh makes before it decides to serve a
# raygen-bearing rung or wipe it.  If this gate passes and the launch still
# reads off:gi-*, the PT switches moved (ptq combo), not the build.
echo "=== 11. sync_settings.sh's guard, replayed against \$INSTALL_DIR"
base_src=$(sed -n 's/.*src_ser="\([^"]*\)".*/\1/p' "$SRC/MANIFEST.txt" | head -1)
base_ser=$(sed -n 's/.*ser_sha=\([0-9a-f]*\).*/\1/p' "$SRC/MANIFEST.txt" | head -1)
base_ptq=$(sed -n 's/.*ptq_sha=\([0-9a-f]*\).*/\1/p' "$SRC/MANIFEST.txt" | head -1)
[[ -n "$base_src" && -n "$base_ser" && -n "$base_ptq" ]] \
    || { echo "  !! the BASE manifest has no src_ser/ser_sha/ptq_sha -- it could never have been served" >&2; exit 1; }
ser_now=$(cat "$INSTALL_DIR/$base_src"/*.rgs_reference_main.spv 2>/dev/null | sha256sum | cut -c1-16)
[[ "$ser_now" == "$base_ser" ]] \
    || { echo "  !! $base_src is $ser_now, the base was built on $base_ser -- sync_settings will refuse (gi-stale-ser)" >&2; exit 1; }
ptq_combo=$(sed -n 's|.*src="[^"]*/ptq/\([a-z]*\)/base".*|\1|p' "$INSTALL_DIR/$base_src/MANIFEST.txt" | head -1)
ptq_now=$(cat "$INSTALL_DIR/ptq/${ptq_combo:-none}/base"/*.rgs_reference_main.spv 2>/dev/null | sha256sum | cut -c1-16)
[[ "$ptq_now" == "$base_ptq" ]] \
    || { echo "  !! ptq/$ptq_combo/base is $ptq_now, the base was baked against $base_ptq (gi-stale-ptq)" >&2; exit 1; }
for r in "${ORDER[@]}"; do
    m="$MOD_DIR/swaps.$r/MANIFEST.txt"
    for tok in "src_ser=\"$base_src\"" "ser_sha=$base_ser" "ptq_sha=$base_ptq"; do
        grep -q -- "$tok" "$m" || { echo "  !! swaps.$r/MANIFEST.txt lacks $tok -- would be refused as gi-no-manifest" >&2; exit 1; }
    done
done
echo "  src_ser=$base_src ser_sha=$base_ser ptq_sha=$base_ptq (ptq combo $ptq_combo): all ${#ORDER[@]} rungs carry them, both shas match what is installed"
echo "  NOTE: this also needs ser=$(basename "$base_src") on the CET page -- a raygen-bearing rung is refused under ser=off (gi-needs-ser)"

if (( DO_INSTALL )); then
    echo "=== install"
    for r in "${ORDER[@]}"; do
        rm -rf "$INSTALL_DIR/skin.set/$r"
        cp -a "$MOD_DIR/swaps.$r" "$INSTALL_DIR/skin.set/$r"
        n=0
        for f in "$MOD_DIR/swaps.$r"/*.spv; do
            cmp -s "$f" "$INSTALL_DIR/skin.set/$r/$(basename "$f")" \
                || { echo "  !! install differs: $r/$(basename "$f")" >&2; exit 1; }
            n=$((n+1))
        done
        echo "  installed $r ($n modules, cmp clean)"
    done
fi
echo "=== done"
