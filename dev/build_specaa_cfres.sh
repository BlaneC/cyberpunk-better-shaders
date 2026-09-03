#!/usr/bin/env bash
# specaa + cfres: two independent metal-quality features at the compute
# resolvers' direct-light GGX / Schlick sites (handoff/108).
#
#   ./dev/build_specaa_cfres.sh              # build + verify (no install)
#   ./dev/build_specaa_cfres.sh --install    # ALSO park all 8 rungs
#   ./dev/build_specaa_cfres.sh --base <skin.set name>
#
# FEATURE 1  specular AA from the pixel footprint.  Normal variance over the
#            +1 texel neighbours widens alpha (Kaplanyan 2016) on metal, ramped
#            in by the world-space size of a lighting texel so near surfaces
#            are exactly untouched.  75 of 77 modules, 303 alpha ids.
# FEATURE 2  real conductor Fresnel.  Lazanyi-Schlick with Hoffman's F82 edge
#            tint replaces plain Schlick on metal, so copper and gold keep
#            their hue at the silhouette instead of going white.  77 of 77
#            modules, 357 Schlick groups, 1071 channels.
#
# Rungs built (ALL NEW NAMES -- nothing existing is touched or deleted):
#   specaa         kappa 0.5
#   specaa-hi      kappa 1.0 (the kernel doubled)
#   specaa-vis     DIAGNOSTIC: sigma2 painted as a grey ramp on gated pixels,
#                  alpha untouched
#   specaa-ctl     kappa 0: 93 of 93 modules cmp-identical to the base
#   cfres          tint 0.5
#   cfres-strong   tint 1.0 (the edge tint fully saturated)
#   cfres-ctl      tint 0: 93 of 93 modules cmp-identical to the base
#   specaa-cfres   BOTH, spliced in that order -- and both verifiers must pass
#                  on it, which is the non-interference proof
set -euo pipefail

MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="${CALLISTO_INSTALL_DIR:-$HOME/.local/lib/callisto}"
PY_SAA="$MOD_DIR/dev/patch_specaa.py"
PY_CF="$MOD_DIR/dev/patch_cfres.py"
V_SAA="$MOD_DIR/dev/verify_specaa.py"
V_CF="$MOD_DIR/dev/verify_cfres.py"

BASE=gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog-earglow-cap6-glintdense
DO_INSTALL=0
KAPPA=0.5
KAPPA_HI=1.0
TINT=0.5
TINT_HI=1.0
while (( $# )); do
    case "$1" in
        --install) DO_INSTALL=1 ;;
        --base) BASE="${2:?--base needs a skin.set name}"; shift ;;
        --kappa) KAPPA="${2:?}"; shift ;;
        --tint) TINT="${2:?}"; shift ;;
        *) echo "unknown arg $1" >&2; exit 1 ;;
    esac
    shift
done

SRC="$INSTALL_DIR/skin.set/$BASE"
WORK="$MOD_DIR/dev/disasm/specaa_cfres"
RUNGS=(specaa specaa-hi specaa-vis specaa-ctl cfres cfres-strong cfres-ctl specaa-cfres)
declare -A OUT=( [specaa]="$MOD_DIR/swaps.specaa"
                 [specaa-hi]="$MOD_DIR/swaps.specaa.hi"
                 [specaa-vis]="$MOD_DIR/swaps.specaa.vis"
                 [specaa-ctl]="$MOD_DIR/swaps.specaa.ctl"
                 [cfres]="$MOD_DIR/swaps.cfres"
                 [cfres-strong]="$MOD_DIR/swaps.cfres.strong"
                 [cfres-ctl]="$MOD_DIR/swaps.cfres.ctl"
                 [specaa-cfres]="$MOD_DIR/swaps.specaacfres" )

# --- 0. base provenance ----------------------------------------------------
echo "--- 0. base provenance ($BASE) ---"
[[ -f "$SRC/MANIFEST.txt" ]] || { echo "no $SRC/MANIFEST.txt -- the standing selection is not parked" >&2; exit 1; }
n_c=$(ls "$SRC"/*.dxil.spv | wc -l)
n_r=$(ls "$SRC"/*.rgs_*.spv | wc -l)
[[ "$n_c" == 77 ]] || { echo "$BASE has $n_c compute modules, expected 77" >&2; exit 1; }
[[ "$n_r" == 16 ]] || { echo "$BASE has $n_r raygen modules, expected 16" >&2; exit 1; }
echo "  77 compute + 16 raygen; base content sha $(cat "$SRC"/*.spv | sha256sum | cut -c1-16)"

# --- 1. disassemble --------------------------------------------------------
rm -rf "$WORK"; mkdir -p "$WORK/asm" "$WORK/rt" "$WORK/stackin"
for k in "${RUNGS[@]}"; do mkdir -p "$WORK/$k"; done
jobs="${CALLISTO_JOBS:-$(nproc 2>/dev/null || echo 4)}"
ls "$SRC"/*.dxil.spv | xargs -P "$jobs" -I{} bash -c \
    'n=$(basename "$1" .dxil.spv); spirv-dis "$1" -o "'"$WORK"'/asm/$n.spvasm"' _ {}
[[ "$(ls "$WORK/asm" | wc -l)" == 77 ]] || { echo "disassembly lost modules" >&2; exit 1; }

# --- 2. the pipeline is byte-neutral, at each module's OWN version ----------
echo "--- 2. round-trip neutrality (dis -> as == base bytes) ---"
same=0
for a in "$WORK"/asm/*.spvasm; do
    n="$(basename "${a%.spvasm}")"
    ver=$(sed -n 's/^; Version: \([0-9]*\)\.\([0-9]*\).*/spv\1.\2/p' "$a" | head -1)
    [[ -n "$ver" ]] || { echo "  !! $n has no '; Version:' header" >&2; exit 1; }
    spirv-as --target-env "$ver" "$a" -o "$WORK/rt/$n.spv"
    cmp -s "$SRC/$n.dxil.spv" "$WORK/rt/$n.spv" || { echo "  !! $n does not round-trip -- the controls would be meaningless" >&2; exit 1; }
    same=$((same+1))
done
echo "  $same of 77 modules round-trip byte-identically at their own version"
rm -rf "$WORK/rt"

# --- 2b. the offline Fresnel model's own gates -----------------------------
echo "--- 2b. dev/cfres_model.py gates ---"
python3 "$MOD_DIR/dev/cfres_model.py" --gate --tint "$TINT" | tail -6
python3 "$MOD_DIR/dev/cfres_model.py" --gate --tint "$TINT_HI" | tail -4

# --- 3. patch --------------------------------------------------------------
patch_all () {   # $1 = python patcher, $2 = indir, $3 = outdir, rest = args
    local py="$1" ind="$2" out="$3"; shift 3
    printf '%s\n' "$@" --outdir "$out" > "$WORK/.args"
    find "$ind" -name '*.spvasm' -print0 | \
        CB_ARGS="$WORK/.args" CB_PY="$py" CB_OUT="$out" \
        xargs -0 -P "$jobs" -n1 bash -c '
            asm="$1"; n="$(basename "${asm%.spvasm}")"; n="${n%.dxil}"
            mapfile -t A < "$CB_ARGS"
            if python3 "$CB_PY" "$asm" "${A[@]}" > "$CB_OUT/.$n.json" 2>"$CB_OUT/.$n.err"; then
                : > "$CB_OUT/.ok.$n"
            else
                : > "$CB_OUT/.bad.$n"
            fi' _
    rm -f "$WORK/.args"
}
echo "--- 3. patch ---"
patch_all "$PY_SAA" "$WORK/asm" "$WORK/specaa"      --kappa "$KAPPA"
patch_all "$PY_SAA" "$WORK/asm" "$WORK/specaa-hi"   --kappa "$KAPPA_HI"
patch_all "$PY_SAA" "$WORK/asm" "$WORK/specaa-vis"  --kappa "$KAPPA" --mode vis
patch_all "$PY_SAA" "$WORK/asm" "$WORK/specaa-ctl"  --kappa 0
patch_all "$PY_CF"  "$WORK/asm" "$WORK/cfres"        --tint "$TINT"
patch_all "$PY_CF"  "$WORK/asm" "$WORK/cfres-strong" --tint "$TINT_HI"
patch_all "$PY_CF"  "$WORK/asm" "$WORK/cfres-ctl"    --tint 0
# the stack: cfres over specaa's OWN output, with the two specaa-declined
# modules taken from the base disassembly so cfres still reaches all 77.
for f in "$WORK"/specaa/*.dxil.spvasm; do
    n="$(basename "${f%.dxil.spvasm}")"; cp -pf "$f" "$WORK/stackin/$n.spvasm"
done
for f in "$WORK"/asm/*.spvasm; do
    n="$(basename "${f%.spvasm}")"
    [[ -f "$WORK/stackin/$n.spvasm" ]] || cp -pf "$f" "$WORK/stackin/$n.spvasm"
done
[[ "$(ls "$WORK/stackin" | wc -l)" == 77 ]] || { echo "stack input is not 77 modules" >&2; exit 1; }
patch_all "$PY_CF" "$WORK/stackin" "$WORK/specaa-cfres" --tint "$TINT"

# --- 4. coverage, from the reports, never from byte counts -----------------
echo "--- 4. coverage ---"
python3 - "$MOD_DIR" "$WORK" "$KAPPA" "$KAPPA_HI" "$TINT" "$TINT_HI" <<'PY' || exit 1
import glob, json, os, sys
sys.path.insert(0, os.path.join(sys.argv[1], 'dev'))
import patch_specaa as SA
import patch_cfres as CF
W = sys.argv[2]
bad = []

def load(d):
    badm = {os.path.basename(f)[5:] for f in glob.glob(os.path.join(d, '.bad.*'))}
    reps = []
    for f in sorted(glob.glob(os.path.join(d, '.*.json'))):
        n = os.path.basename(f)[1:-5]
        if n in badm:
            continue
        try:
            r = json.load(open(f))[0]
        except Exception as e:
            bad.append((os.path.basename(f), 'bad json: %s' % e)); continue
        if r.get('spirv_val') != 'clean':
            bad.append((r.get('module'), 'spirv-val not clean'))
        reps.append(r)
    return badm, reps

def sum_saa(rung, key, want_mode, knobs):
    badm, reps = load(os.path.join(W, rung))
    tot = dict(alphas=0, sites=0, writes=0, estimators=0)
    for r in reps:
        p = r.get('specaa')
        if p is None:
            bad.append((r.get('module'), 'no specaa report')); continue
        for k in ('skipped_dom', 'skipped_leaf', 'skipped'):
            if p.get(k):
                bad.append((r.get('module'), '%s: %s' % (k, p[k][:2])))
        for k in tot:
            tot[k] += p.get(k, 0)
        if want_mode and p.get('mode') != want_mode:
            bad.append((r.get('module'), 'mode %s, want %s' % (p.get('mode'), want_mode)))
        for kk, vv in knobs.items():
            if abs(float(p.get(kk, -1)) - vv) > 1e-9:
                bad.append((r.get('module'), '%s=%s, want %s' % (kk, p.get(kk), vv)))
    print('  %-13s: %d modules, %d declined, %d alphas, %d GGX sites, '
          '%d estimators, %d writes'
          % (rung, len(reps), len(badm), tot['alphas'], tot['sites'],
             tot['estimators'], tot['writes']))
    return badm, len(reps), tot

C = SA.CENSUS
for rung, mode, kn in (('specaa', 'feature', dict(kappa=float(sys.argv[3]))),
                       ('specaa-hi', 'feature', dict(kappa=float(sys.argv[4]))),
                       ('specaa-vis', 'vis', dict(kappa=float(sys.argv[3])))):
    badm, nm, tot = sum_saa(rung, None, mode, kn)
    if badm != set(SA.KNOWN_DECLINE):
        bad.append((rung, 'declines are %s, expected %s'
                    % (sorted(badm), sorted(SA.KNOWN_DECLINE))))
    if nm != C['modules']:
        bad.append((rung, '%d modules, census says %d' % (nm, C['modules'])))
    if mode == 'feature':
        if tot['alphas'] != C['alphas'] or tot['sites'] != C['sites']:
            bad.append((rung, '%d alphas / %d sites, census says %d / %d'
                        % (tot['alphas'], tot['sites'], C['alphas'], C['sites'])))
    else:
        if tot['writes'] != C['writes']:
            bad.append((rung, '%d painted writes, census says %d'
                        % (tot['writes'], C['writes'])))

badm, nm, tot = sum_saa('specaa-ctl', None, 'control', {})
if badm or nm != 77:
    bad.append(('specaa-ctl', 'emitted %d modules, declined %s; want 77 / none'
                % (nm, sorted(badm))))
if tot['alphas'] or tot['writes']:
    bad.append(('specaa-ctl', 'the kappa-0 control emitted a splice'))

CC = CF.CENSUS
def sum_cf(rung, tint):
    badm, reps = load(os.path.join(W, rung))
    tot = dict(groups=0, chans=0, form_m=0, form_s=0, metal_lifted=0)
    for r in reps:
        p = r.get('cfres')
        if p is None:
            bad.append((r.get('module'), 'no cfres report')); continue
        for k in ('skipped_link', 'skipped_dom', 'skipped_block', 'skipped_shape'):
            if p.get(k):
                bad.append((r.get('module'), '%s: %s' % (k, p[k][:2])))
        for k in tot:
            tot[k] += p.get(k, 0)
        if abs(float(p.get('tint', -1)) - tint) > 1e-9:
            bad.append((r.get('module'), 'tint=%s, want %s' % (p.get('tint'), tint)))
    print('  %-13s: %d modules, %d declined, %d groups, %d channels '
          '(%d form-M, %d form-S, %d metal lifts)'
          % (rung, len(reps), len(badm), tot['groups'], tot['chans'],
             tot['form_m'], tot['form_s'], tot['metal_lifted']))
    return badm, len(reps), tot

for rung, tint in (('cfres', float(sys.argv[5])),
                   ('cfres-strong', float(sys.argv[6])),
                   ('specaa-cfres', float(sys.argv[5]))):
    badm, nm, tot = sum_cf(rung, tint)
    if badm:
        bad.append((rung, 'declined %s, expected none' % sorted(badm)))
    if nm != CC['modules']:
        bad.append((rung, '%d modules, census says %d' % (nm, CC['modules'])))
    for k in ('groups', 'chans', 'form_m', 'form_s', 'metal_lifted'):
        if tot[k] != CC[k]:
            bad.append((rung, '%s=%d, census says %d' % (k, tot[k], CC[k])))

badm, nm, tot = sum_cf('cfres-ctl', 0.0)
if badm or nm != 77:
    bad.append(('cfres-ctl', 'emitted %d modules, declined %s; want 77 / none'
                % (nm, sorted(badm))))
if tot['chans']:
    bad.append(('cfres-ctl', 'the tint-0 control emitted %d channels' % tot['chans']))

if bad:
    for m, why in bad[:12]:
        sys.stderr.write('    %s :: %s\n' % (m, why))
    sys.exit(1)
print('  census held: specaa 75/303/351, cfres 77/357/1071 (64 metal lifts)')
PY

# --- 5. assemble -----------------------------------------------------------
assemble () {   # $1 = dest, $2 = patched-compute dir
    local dest="$1" src="$2"
    rm -rf "$dest"; mkdir -p "$dest"
    cp -pf "$SRC"/*.rgs_*.spv "$dest/"
    cp -pf "$src"/*.dxil.spv "$dest/" 2>/dev/null || true
    for f in "$SRC"/*.dxil.spv; do
        [[ -f "$dest/$(basename "$f")" ]] || cp -pf "$f" "$dest/"
    done
    local n; n=$(ls "$dest"/*.spv | wc -l)
    [[ "$n" == 93 ]] || { echo "$dest has $n modules, expected 93" >&2; exit 1; }
    for f in "$SRC"/*.rgs_*.spv; do
        cmp -s "$f" "$dest/$(basename "$f")" || { echo "raygen $(basename "$f") differs from $BASE -- NOT one variable" >&2; exit 1; }
    done
    for f in "$dest"/*.spv; do spirv-val --target-env vulkan1.4 "$f" >/dev/null || { echo "spirv-val FAILED: $f" >&2; exit 1; }; done
}
echo "--- 5. assemble (spirv-val --target-env vulkan1.4 on every module) ---"
for k in "${RUNGS[@]}"; do assemble "${OUT[$k]}" "$WORK/$k"; done

diffcount () {   # $1 = dir A (or base), $2 = dir B -> prints the count
    local a="$1" b="$2" d=0 f
    for f in "$a"/*.dxil.spv; do cmp -s "$f" "$b/$(basename "$f")" || d=$((d+1)); done
    echo "$d"
}
for k in specaa specaa-hi specaa-vis; do
    d=$(diffcount "$SRC" "${OUT[$k]}")
    echo "  $k: $d of 77 compute modules differ from $BASE"
    [[ "$d" == 75 ]] || { echo "  !! expected exactly 75 (the census)" >&2; exit 1; }
done
for k in cfres cfres-strong specaa-cfres; do
    d=$(diffcount "$SRC" "${OUT[$k]}")
    echo "  $k: $d of 77 compute modules differ from $BASE"
    [[ "$d" == 77 ]] || { echo "  !! expected exactly 77 (the census)" >&2; exit 1; }
done
for k in specaa-ctl cfres-ctl; do
    d=0; for f in "$SRC"/*.spv; do cmp -s "$f" "${OUT[$k]}/$(basename "$f")" || d=$((d+1)); done
    echo "  $k: $d of 93 modules differ from $BASE"
    [[ "$d" == 0 ]] || { echo "  !! the control is NOT byte-identical to the base" >&2; exit 1; }
done
# every feature rung must differ from every other, or a rung is a no-op
for pair in "specaa:specaa-hi" "specaa:specaa-vis" "specaa:cfres" \
            "cfres:cfres-strong" "specaa:specaa-cfres" "cfres:specaa-cfres"; do
    a="${pair%%:*}"; b="${pair##*:}"
    d=$(diffcount "${OUT[$a]}" "${OUT[$b]}")
    echo "  $a vs $b: $d of 77 differ"
    [[ "$d" -gt 0 ]] || { echo "  !! two rungs are byte-identical" >&2; exit 1; }
done

# --- 6. the verifiers, on shipped bytes, proven non-vacuous ----------------
echo "--- 6. verifiers (shipped bytes) ---"
python3 "$V_SAA" "${OUT[specaa]}"      --kappa "$KAPPA"
python3 "$V_SAA" "${OUT[specaa-hi]}"   --kappa "$KAPPA_HI"
python3 "$V_SAA" "${OUT[specaa-vis]}"  --mode vis --kappa "$KAPPA"
python3 "$V_SAA" "${OUT[specaa-ctl]}"  --mode none
python3 "$V_CF"  "${OUT[cfres]}"        --tint "$TINT"
python3 "$V_CF"  "${OUT[cfres-strong]}" --tint "$TINT_HI"
python3 "$V_CF"  "${OUT[cfres-ctl]}"    --expect-none
echo "--- 6b. NON-INTERFERENCE: both verifiers pass on the stack ---"
python3 "$V_SAA" "${OUT[specaa-cfres]}" --kappa "$KAPPA"
python3 "$V_CF"  "${OUT[specaa-cfres]}" --tint "$TINT"
echo "--- 6c. each feature is invisible to the other's verifier ---"
python3 "$V_SAA" "${OUT[cfres]}" --mode none
python3 "$V_CF"  "${OUT[specaa]}" --expect-none

reject () {   # $1 = label, $2 = verifier, rest = args
    local label="$1" v="$2"; shift 2
    if python3 "$v" "$@" >/dev/null 2>&1; then
        echo "  !! the verifier ACCEPTS $label -- it is vacuous" >&2; exit 1; fi
    echo "  rejected: $label"
}
echo "--- 6d. rejections ---"
reject "the base, read as specaa"        "$V_SAA" "$SRC" --kappa "$KAPPA"
reject "specaa-ctl, read as specaa"      "$V_SAA" "${OUT[specaa-ctl]}" --kappa "$KAPPA"
reject "specaa, read as --mode none"     "$V_SAA" "${OUT[specaa]}" --mode none
reject "specaa, read at the -hi kernel"  "$V_SAA" "${OUT[specaa]}" --kappa "$KAPPA_HI"
reject "specaa-hi, read at the base kernel" "$V_SAA" "${OUT[specaa-hi]}" --kappa "$KAPPA"
reject "specaa, read as vis"             "$V_SAA" "${OUT[specaa]}" --mode vis
reject "specaa-vis, read as the feature" "$V_SAA" "${OUT[specaa-vis]}" --kappa "$KAPPA"
reject "specaa at a wrong sigma2 ceiling" "$V_SAA" "${OUT[specaa]}" --kappa "$KAPPA" --sigma2-max 0.3
reject "specaa at a wrong metal gate"    "$V_SAA" "${OUT[specaa]}" --kappa "$KAPPA" --metal-min 0.5
reject "specaa at a wrong ramp"          "$V_SAA" "${OUT[specaa]}" --kappa "$KAPPA" --foot1 0.1
reject "the base, read as cfres"         "$V_CF"  "$SRC" --tint "$TINT"
reject "cfres-ctl, read as cfres"        "$V_CF"  "${OUT[cfres-ctl]}" --tint "$TINT"
reject "cfres, read as --expect-none"    "$V_CF"  "${OUT[cfres]}" --expect-none
reject "cfres, read at the strong tint"  "$V_CF"  "${OUT[cfres]}" --tint "$TINT_HI"
reject "cfres-strong, read at the base tint" "$V_CF" "${OUT[cfres-strong]}" --tint "$TINT"
reject "cfres at a wrong metal gate"     "$V_CF"  "${OUT[cfres]}" --tint "$TINT" --metal-min 0.3
reject "the stack, read at the wrong kernel" "$V_SAA" "${OUT[specaa-cfres]}" --kappa "$KAPPA_HI"
reject "the stack, read at the wrong tint"   "$V_CF"  "${OUT[specaa-cfres]}" --tint "$TINT_HI"

# --- 7. MANIFESTs ----------------------------------------------------------
manifest () {   # $1 = dest, $2 = rung name, $3 = tail comment
    sed -e "1s/^$BASE /$2 /" -e "1s/compute=77([^)]*)/compute=77($BASE-$2)/" \
        "$SRC/MANIFEST.txt" > "$1/MANIFEST.txt"
    grep -q "^$2 " "$1/MANIFEST.txt" || { echo "MANIFEST rewrite failed" >&2; exit 1; }
    echo "# $3" >> "$1/MANIFEST.txt"
}
echo "--- 7. MANIFESTs ---"
manifest "${OUT[specaa]}" "specaa" "specular AA from the pixel footprint: alpha' = sqrt(alpha^2 + s2), kappa=$KAPPA, s2<=0.18, metallic>0.3, ramped over 1..5 cm of texel footprint; 303 alpha ids in 75 compute modules; raygens are $BASE bytes. See handoff/108."
manifest "${OUT[specaa-hi]}" "specaa-hi" "specaa with the kernel doubled (kappa=$KAPPA_HI). The A/B rung that says whether the effect is strength-limited."
manifest "${OUT[specaa-vis]}" "specaa-vis" "specaa DIAGNOSTIC: sigma2/0.18 painted as grey on metallic>0.3 pixels at all 150 radiance writes. Alpha untouched. Meant to look wrong."
manifest "${OUT[specaa-ctl]}" "specaa-ctl" "specaa CONTROL (kappa 0): 93 of 93 modules byte-identical to $BASE."
manifest "${OUT[cfres]}" "cfres" "real conductor Fresnel: Lazanyi-Schlick with Hoffman's F82 edge tint (tint=$TINT) on metallic>0.5; 1071 channels in 357 Schlick groups across 77 compute modules. See handoff/108 sec 3."
manifest "${OUT[cfres-strong]}" "cfres-strong" "cfres with the edge tint fully saturated (tint=$TINT_HI): f82 = the F0 hue itself."
manifest "${OUT[cfres-ctl]}" "cfres-ctl" "cfres CONTROL (tint 0): 93 of 93 modules byte-identical to $BASE."
manifest "${OUT[specaa-cfres]}" "specaa-cfres" "THE STACK: specaa (kappa=$KAPPA) and cfres (tint=$TINT) in one selection. Both verifiers pass on these bytes, which is the non-interference proof."

echo
for k in "${RUNGS[@]}"; do echo "  built ${OUT[$k]} (93 modules)"; done
if (( DO_INSTALL )); then
    for k in "${RUNGS[@]}"; do
        park="$INSTALL_DIR/skin.set/$k"
        if [[ -e "$park" && ! -f "$park/.specaa_cfres" ]]; then
            echo "  !! $park exists and was not created by this script -- refusing to touch it" >&2
            exit 1
        fi
        mkdir -p "$park"; rm -f "$park"/*.spv "$park/MANIFEST.txt"
        cp -pf "${OUT[$k]}"/*.spv "${OUT[$k]}/MANIFEST.txt" "$park/"
        : > "$park/.specaa_cfres"
        echo "  parked -> $park"
    done
else
    echo "NOT installed. To park: ./dev/build_specaa_cfres.sh --install"
fi
echo "select with skinspec=specaa | specaa-hi | specaa-vis | specaa-ctl | cfres | cfres-strong | cfres-ctl | specaa-cfres;"
echo "needs ser=class + shadowset=full-shadow ($BASE's contract)"
