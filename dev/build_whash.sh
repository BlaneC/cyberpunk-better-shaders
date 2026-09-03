#!/usr/bin/env bash
# 107 -- the world-hash material pack.  Three features on one emitter:
#   B  triplanar micro-detail on rough dielectrics (roughness +-0.08,
#      diffuse reflectance +-6 %, faded out between 6 m and 14 m)
#   C  porous backscatter for concrete (a broad Charlie x Neubelt lobe whose
#      amplitude is the fbm porosity)
#   +  micro-cell, the crawl falsifier: flat hue per 12 mm world cell
#
#   ./dev/build_whash.sh                 # build + verify (no install)
#   ./dev/build_whash.sh --install       # ALSO park the seven rungs
#   ./dev/build_whash.sh --cell 0.02 --install
#
# NEW FILE.  It parks under NEW names only and never touches a parked dir it
# did not create.
#
# Rungs:
#   micro         B at the shipped amplitudes                     (the feature)
#   micro-hi      B at DOUBLE amplitude          (is the effect scaling at all?)
#   micro-cell    flat hue per 12 mm world cell.  THE FALSIFIER: if the cells
#                 crawl across a wall as the camera moves, the P offset is
#                 wrong and every read below it is void (handoff/107 sec 8).
#                 Carries no perturbation, on purpose.
#   micro-ctl     no knobs: 93 of 93 modules cmp-identical to the base
#   porous        C alone
#   porous-ctl    no knobs: identical to micro-ctl and to the base
#   micro-porous  B + C in one rung (the stack)
#
# The two controls are byte-identical to EACH OTHER as well as to the base.
# That is not redundancy: `porous` and `micro` are read on different frames
# and each A/B needs its own named control, or the comparison is between a
# rung and a memory (GOTCHAS 3).
set -euo pipefail

MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="${CALLISTO_INSTALL_DIR:-$HOME/.local/lib/callisto}"
PY="$MOD_DIR/dev/patch_whash.py"
VERIFY="$MOD_DIR/dev/verify_whash.py"

BASE=gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog-earglow-cap6-glintdense
DO_INSTALL=0
# `micro` is ALREADY a shipped skinspec id (init.lua: "Micro-shadowing only --
# dark skin self-shadows", from 44) with a parked dir of 77 pre-raygen-era
# files.  107's rung is a different thing entirely and must not overwrite it,
# so --install parks under PARK_PREFIX + the rung name.  The rung NAMES stay
# as briefed everywhere else -- reports, verifier, this script's output -- and
# only the parked directory and the skinspec id carry the prefix.
PARK_PREFIX=wh-
CELL=0.012
K_ROUGH=0.08
K_ALB=0.06
K_POROUS=0.06
NEAR=6
FAR=14
while (( $# )); do
    case "$1" in
        --install) DO_INSTALL=1 ;;
        --park-prefix) PARK_PREFIX="${2:?--park-prefix needs a string}"; shift ;;
        --base)    BASE="${2:?--base needs a skin.set name}"; shift ;;
        --cell)    CELL="${2:?--cell needs metres}"; shift ;;
        --rough)   K_ROUGH="${2:?}"; shift ;;
        --alb)     K_ALB="${2:?}"; shift ;;
        --porous)  K_POROUS="${2:?}"; shift ;;
        --near)    NEAR="${2:?}"; shift ;;
        --far)     FAR="${2:?}"; shift ;;
        *) echo "unknown arg $1" >&2; exit 1 ;;
    esac
    shift
done
HI_ROUGH=$(python3 -c "print(2*$K_ROUGH)")
HI_ALB=$(python3 -c "print(2*$K_ALB)")
COMMON=(--cell "$CELL" --fade-near "$NEAR" --fade-far "$FAR" --no-roundtrip-check)

SRC="$INSTALL_DIR/skin.set/$BASE"
WORK="$MOD_DIR/dev/disasm/whash"
RUNGS=(micro micro-hi micro-cell micro-ctl porous porous-ctl micro-porous)
declare -A OUT
for r in "${RUNGS[@]}"; do OUT[$r]="$MOD_DIR/swaps.whash.${r//-/.}"; done

# --- 0. base provenance ----------------------------------------------------
echo "--- 0. base provenance ($BASE) ---"
[[ -f "$SRC/MANIFEST.txt" ]] || { echo "no $SRC/MANIFEST.txt -- the standing selection is not parked" >&2; exit 1; }
n_c=$(ls "$SRC"/*.dxil.spv | wc -l)
n_r=$(ls "$SRC"/*.rgs_*.spv | wc -l)
[[ "$n_c" == 77 ]] || { echo "$BASE has $n_c compute modules, expected 77" >&2; exit 1; }
[[ "$n_r" == 16 ]] || { echo "$BASE has $n_r raygen modules, expected 16" >&2; exit 1; }
n_ref=$(ls "$SRC"/*rgs_reference_main*.spv 2>/dev/null | wc -l)
n_res=$(ls "$SRC"/*rgs_restirgi*.spv 2>/dev/null | wc -l)
[[ "$n_ref" == 12 && "$n_res" == 4 ]] || { echo "raygen split is $n_ref/$n_res, expected 12/4" >&2; exit 1; }
echo "  77 compute + 12 rgs_reference_main + 4 rgs_restirgi"

echo "--- 0a. park-name collision pre-flight (prefix '$PARK_PREFIX') ---"
coll=0
for r in "${RUNGS[@]}"; do
    park="$INSTALL_DIR/skin.set/${PARK_PREFIX}$r"
    if [[ -e "$park" && ! -f "$park/.whash" ]]; then
        echo "  !! ${PARK_PREFIX}$r already exists and is not ours"; coll=1
    fi
done
(( coll == 0 )) || { echo "  re-run with --park-prefix <other>" >&2; exit 1; }
echo "  all seven park names are free (or already ours)"

# --- 0b. the offline emitter gate, before anything is patched --------------
echo "--- 0b. whash_core selftest (the emitter vs whash_model, bit-exact) ---"
python3 "$MOD_DIR/dev/whash_core.py" --selftest --cell "$CELL" | sed 's/^/  /'

# --- 1. disassemble --------------------------------------------------------
echo "--- 1. disassemble ---"
rm -rf "$WORK"; mkdir -p "$WORK/asm" "$WORK/rt"
for r in "${RUNGS[@]}"; do mkdir -p "$WORK/$r"; done
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

# --- 3. patch --------------------------------------------------------------
patch_all () {   # $1 = outdir, rest = extra args
    local out="$1"; shift
    printf '%s\n' "$@" --outdir "$out" > "$WORK/.args.$$"
    find "$WORK/asm" -name '*.spvasm' -print0 | \
        CB_ARGS="$WORK/.args.$$" CB_PY="$PY" CB_OUT="$out" \
        xargs -0 -P "$jobs" -n1 bash -c '
            asm="$1"; n="$(basename "${asm%.spvasm}")"
            mapfile -t A < "$CB_ARGS"
            if python3 "$CB_PY" "$asm" "${A[@]}" > "$CB_OUT/.$n.json" 2>"$CB_OUT/.$n.err"; then
                : > "$CB_OUT/.ok.$n"
            else
                : > "$CB_OUT/.bad.$n"
            fi' _
    rm -f "$WORK/.args.$$"
}
echo "--- 3. patch (7 rungs x 77 modules) ---"
patch_all "$WORK/micro"        --micro-rough "$K_ROUGH"  --micro-alb "$K_ALB"  "${COMMON[@]}"
patch_all "$WORK/micro-hi"     --micro-rough "$HI_ROUGH" --micro-alb "$HI_ALB" "${COMMON[@]}"
patch_all "$WORK/micro-cell"   --paint cell "${COMMON[@]}"
patch_all "$WORK/micro-ctl"    "${COMMON[@]}"
patch_all "$WORK/porous"       --porous "$K_POROUS" "${COMMON[@]}"
patch_all "$WORK/porous-ctl"   "${COMMON[@]}"
patch_all "$WORK/micro-porous" --micro-rough "$K_ROUGH" --micro-alb "$K_ALB" \
                               --porous "$K_POROUS" "${COMMON[@]}"

# --- 4. coverage, from the reports, never from byte counts -----------------
echo "--- 4. coverage ---"
python3 - "$MOD_DIR" "$WORK" <<'PY' || exit 1
import glob, json, os, sys
sys.path.insert(0, os.path.join(sys.argv[1], 'dev'))
import patch_whash as PW
W = sys.argv[2]
C = PW.CENSUS
bad = []

def scan(d):
    badm = {os.path.basename(f)[5:] for f in glob.glob(os.path.join(d, '.bad.*'))}
    t = dict(mods=0, rough=0, alb=0, porous=0, paint=0, skipped=0, hoist=0,
             ggx=0, sheen=0, fd=0, writes=0)
    for f in sorted(glob.glob(os.path.join(d, '.*.json'))):
        n = os.path.basename(f)[1:-5]
        if n in badm:
            continue
        try:
            r = json.load(open(f))[0]
        except Exception as e:
            bad.append((os.path.basename(f), 'bad json: %s' % e)); continue
        if r.get('spirv_val') != 'clean':
            bad.append((r.get('module'), 'spirv-val not clean')); continue
        p = r.get('whash')
        if p is None:
            bad.append((r.get('module'), 'no whash report')); continue
        t['mods'] += 1
        if p.get('control'):
            continue
        t['rough'] += len(p['rough_sites']); t['alb'] += len(p['alb_sites'])
        t['porous'] += len(p['porous_sites']); t['paint'] += len(p['paint_sites'])
        t['skipped'] += len(p['skipped_rough']) + len(p['skipped_alb'])
        t['hoist'] += p.get('hoist_instructions', 0)
        c = p['census']
        t['ggx'] += c['ggx_d']; t['sheen'] += c['sheen']; t['fd'] += c['fd']
        t['writes'] += c['writes']
    return badm, t

want = {'micro':        dict(rough=C['alphas'], alb=C['fd']),
        'micro-hi':     dict(rough=C['alphas'], alb=C['fd']),
        'micro-cell':   dict(paint=C['writes']),
        'porous':       dict(porous=C['sheen']),
        'micro-porous': dict(rough=C['alphas'], alb=C['fd'], porous=C['sheen'])}
for rung, w in want.items():
    badm, t = scan(os.path.join(W, rung))
    print('  %-13s: %2d modules, %d declined | rough %3d  albedo %3d  '
          'porous %3d  paint %3d' % (rung, t['mods'], len(badm), t['rough'],
                                     t['alb'], t['porous'], t['paint']))
    if badm != PW.KNOWN_DECLINE:
        bad.append((rung, 'declines are %s, expected exactly %s'
                    % (sorted(badm), sorted(PW.KNOWN_DECLINE))))
    if t['mods'] != C['reached']:
        bad.append((rung, '%d modules reached, census says %d' % (t['mods'], C['reached'])))
    for k, v in w.items():
        if t[k] != v:
            bad.append((rung, '%s: %d sites, census says %d' % (k, t[k], v)))
    for k in ('rough', 'alb', 'porous', 'paint'):
        if k not in w and t[k]:
            bad.append((rung, '%s: %d sites in a rung that does not use it' % (k, t[k])))
    if t['skipped']:
        bad.append((rung, '%d B sites skipped inside reached modules' % t['skipped']))
    if rung == 'micro':
        for k, v in (('ggx', C['ggx_d']), ('sheen', C['sheen']),
                     ('fd', C['fd']), ('writes', C['writes'])):
            if t[k] != v:
                bad.append((rung, 'site census %s = %d, expected %d' % (k, t[k], v)))
        print('     reachable sites: %d GGX D, %d sheen, %d Burley f_d, '
              '%d radiance writes; hoist %d instructions total (%d per module)'
              % (t['ggx'], t['sheen'], t['fd'], t['writes'], t['hoist'],
                 t['hoist'] // max(t['mods'], 1)))

for rung in ('micro-ctl', 'porous-ctl'):
    badm, t = scan(os.path.join(W, rung))
    print('  %-13s: %2d modules emitted, %d declined, %d splices'
          % (rung, t['mods'], len(badm),
             t['rough'] + t['alb'] + t['porous'] + t['paint']))
    if t['mods'] != C['modules'] or badm:
        bad.append((rung, 'emitted %d modules, declined %s; want %d / none'
                    % (t['mods'], sorted(badm), C['modules'])))
    if t['rough'] + t['alb'] + t['porous'] + t['paint']:
        bad.append((rung, 'a control carries splices'))

if bad:
    for m, why in bad[:14]:
        sys.stderr.write('    %s :: %s\n' % (m, why))
    sys.exit(1)
print('  declined BY NAME, both rungs: %s' % ', '.join(sorted(PW.KNOWN_DECLINE)))
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
    for f in "$dest"/*.spv; do spirv-val --target-env vulkan1.4 "$f" >/dev/null \
        || { echo "spirv-val FAILED: $f" >&2; exit 1; }; done
}
echo "--- 5. assemble + spirv-val --target-env vulkan1.4 ---"
for r in "${RUNGS[@]}"; do assemble "${OUT[$r]}" "$WORK/$r"; echo "  ${OUT[$r]}"; done

for r in micro micro-hi micro-cell porous micro-porous; do
    d=0; for f in "$SRC"/*.dxil.spv; do cmp -s "$f" "${OUT[$r]}/$(basename "$f")" || d=$((d+1)); done
    echo "  $r: $d of 77 compute modules differ from $BASE"
    [[ "$d" == 75 ]] || { echo "  !! expected exactly 75 (the census)" >&2; exit 1; }
    for m in 99bb7c2698997b2a ab0bc2fee876d489; do
        cmp -s "$SRC/$m.dxil.spv" "${OUT[$r]}/$m.dxil.spv" \
            || { echo "  !! declined module $m was modified in $r" >&2; exit 1; }
    done
done
for r in micro-ctl porous-ctl; do
    d=0; for f in "$SRC"/*.spv; do cmp -s "$f" "${OUT[$r]}/$(basename "$f")" || d=$((d+1)); done
    echo "  $r: $d of 93 modules differ from $BASE"
    [[ "$d" == 0 ]] || { echo "  !! a CONTROL is not byte-identical to the base" >&2; exit 1; }
done
d=0; for f in "${OUT[micro-ctl]}"/*.spv; do cmp -s "$f" "${OUT[porous-ctl]}/$(basename "$f")" || d=$((d+1)); done
[[ "$d" == 0 ]] || { echo "  !! the two controls differ from each other" >&2; exit 1; }
echo "  micro-ctl vs porous-ctl: 0 of 93 differ (both are the base bytes)"
for pair in micro:micro-hi micro:porous micro:micro-porous porous:micro-porous micro:micro-cell; do
    a="${pair%%:*}"; b="${pair##*:}"
    d=0; for f in "${OUT[$a]}"/*.spv; do cmp -s "$f" "${OUT[$b]}/$(basename "$f")" || d=$((d+1)); done
    echo "  $a vs $b: $d of 93 differ"
    [[ "$d" -gt 0 ]] || { echo "  !! two rungs are byte-identical" >&2; exit 1; }
done

# --- 6. the verifier, on shipped bytes, proven non-vacuous -----------------
echo "--- 6. verifier (shipped bytes, nothing read from a patch report) ---"
for r in micro micro-hi micro-cell porous micro-porous micro-ctl porous-ctl; do
    python3 "$VERIFY" "${OUT[$r]}" --rung "$r" --base "$SRC" | sed 's/^/  /'
done
reject () {   # $1 = label, rest = verifier args
    local label="$1"; shift
    if python3 "$VERIFY" "$@" >/dev/null 2>&1; then
        echo "  !! the verifier ACCEPTS $label -- it is vacuous" >&2; exit 1; fi
    echo "  rejected: $label"
}
reject "the unpatched base as micro"      "$SRC" --rung micro
reject "micro-ctl as micro"               "${OUT[micro-ctl]}" --rung micro
reject "micro read as micro-hi"           "${OUT[micro]}" --rung micro-hi
reject "micro-hi read as micro"           "${OUT[micro-hi]}" --rung micro
reject "porous read as micro"             "${OUT[porous]}" --rung micro
reject "micro read as porous"             "${OUT[micro]}" --rung porous
reject "micro-cell read as micro"         "${OUT[micro-cell]}" --rung micro
reject "micro read as micro-cell"         "${OUT[micro]}" --rung micro-cell

# --- 7. MANIFESTs ----------------------------------------------------------
manifest () {   # $1 = dest, $2 = rung name, $3 = tail comment
    sed -e "1s/^$BASE /$2 /" -e "1s/compute=77([^)]*)/compute=77($BASE-$2)/" \
        "$SRC/MANIFEST.txt" > "$1/MANIFEST.txt"
    grep -q "^$2 " "$1/MANIFEST.txt" || { echo "MANIFEST rewrite failed" >&2; exit 1; }
    echo "# $3" >> "$1/MANIFEST.txt"
}
echo "--- 7. MANIFESTs ---"
manifest "${OUT[micro]}" "micro" "107 B: world-hash micro-detail on rough dielectrics -- roughness +-$K_ROUGH and diffuse reflectance +-$K_ALB from a 3-octave fbm at a ${CELL} m cell, faded to zero between ${NEAR} m and ${FAR} m. 343 alpha + 157 Burley sites in 75 of 77 compute modules; raygens are $BASE bytes. See handoff/107."
manifest "${OUT[micro-hi]}" "micro-hi" "107 B at DOUBLE amplitude (roughness +-$HI_ROUGH, diffuse +-$HI_ALB). The scaling rung: if micro reads NULL and this does not, the amplitude was the problem, not the idea."
manifest "${OUT[micro-cell]}" "micro-cell" "107 FALSIFIER: flat hue per ${CELL} m world cell at all 150 radiance writes, class-gated only, faded like the feature. Cells must stay WELDED to the walls under camera motion; if they crawl, the P offset is wrong and 107 is void. Carries no perturbation."
manifest "${OUT[micro-ctl]}" "micro-ctl" "107 CONTROL: 93 of 93 modules byte-identical to $BASE. Selecting it must be indistinguishable from the base."
manifest "${OUT[porous]}" "porous" "107 C: porous backscatter -- a broad Charlie x Neubelt lobe (alpha 0.9, amplitude $K_POROUS) whose strength is the fbm porosity (0.5-1.5x), on low-saturation dielectrics rougher than 0.75. 376 sheen sites in 75 of 77 compute modules."
manifest "${OUT[porous-ctl]}" "porous-ctl" "107 CONTROL for C: 93 of 93 modules byte-identical to $BASE, and to micro-ctl. Named separately so the C A/B has its own control on its own frame."
manifest "${OUT[micro-porous]}" "micro-porous" "107 STACK: B and C together, on one hoisted noise field. The only rung that carries both."

echo
for r in "${RUNGS[@]}"; do echo "  built ${OUT[$r]} (93 modules)"; done
if (( DO_INSTALL )); then
    for r in "${RUNGS[@]}"; do
        park="$INSTALL_DIR/skin.set/${PARK_PREFIX}$r"
        if [[ -e "$park" && ! -f "$park/.whash" ]]; then
            echo "  !! $park exists and was NOT created by build_whash.sh." >&2
            echo "     Refusing to touch a parked dir this script did not make." >&2
            echo "     Re-run with --park-prefix <something-else>." >&2
            exit 1
        fi
        mkdir -p "$park"; rm -f "$park"/*.spv "$park/MANIFEST.txt"
        cp -pf "${OUT[$r]}"/*.spv "${OUT[$r]}/MANIFEST.txt" "$park/"
        : > "$park/.whash"
        echo "  parked -> $park"
    done
else
    echo "NOT installed. To park: ./dev/build_whash.sh --install"
fi
echo "select with skinspec=${PARK_PREFIX}micro | ${PARK_PREFIX}micro-hi | ${PARK_PREFIX}micro-cell | ${PARK_PREFIX}micro-ctl | ${PARK_PREFIX}porous | ${PARK_PREFIX}porous-ctl | ${PARK_PREFIX}micro-porous;"
echo "needs ser=class + shadowset=full-shadow ($BASE's contract)"
