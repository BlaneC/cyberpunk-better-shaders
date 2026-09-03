#!/usr/bin/env bash
# carglint -- `94` sec 4.4's metallic-flake GLINTS, parked as selectable rungs.
# handoff/100-GLINTS.md is the document. Read its sec 0 and sec 7's
# pre-registered table BEFORE looking at a frame.
#
#   ./dev/build_carglint.sh                # build + verify (nothing installed)
#   ./dev/build_carglint.sh --install      # ALSO park the five rungs in skin.set/
#   ./dev/build_carglint.sh --base NAME    # build on a different parked rung
#
# FIVE RUNGS, one variable each, all on the STANDING selection's own bytes.
#
#   carglint-ctl     k_glint = 0. The patcher emits NO constants, NO
#                    instructions and NO rewrite, so all 93 modules are
#                    BYTE-IDENTICAL to the base -- through spirv-dis, the
#                    patcher's loader, spirv-as and spirv-val, not by cp.
#                    Selecting it must be indistinguishable from selecting the
#                    base. If it is not, the LAYER is not serving what it
#                    claims and every A/B in this repo inherits the doubt
#                    (`94` sec 11's still-unshot control, now cheap to shoot).
#   carglint         `94` sec 4.4 at its defaults: cell 8 mm, nu0 1.5e5,
#                    theta_bin 0.02 rad, glint_max 16, k_glint 1.
#   carglint-dense   nu0 x4 (6.0e5). ONE variable.
#   carglint-sparse  nu0 /4 (3.75e4). ONE variable.
#   carglint-cell    `94` sec 6.3 step 4's `-glintcell`. No glint anywhere; the
#                    PRIMARY hit's world cell hash painted as eight flat hues,
#                    cell 25 cm so a crawl is legible at conversational range.
#                    THIS IS THE RUNG THAT CAN FALSIFY THE SPLICE, and it is
#                    the only one of the five a still frame can read.
#
# READ `94` sec 2.1 BEFORE EXPECTING TO SEE GLINTS. This raygen evaluates NEE
# at bounces >= 1; it does not shade the primary hit. Glints spliced here land
# on paint seen INSIDE a reflection and on second-bounce lighting, not on the
# car in front of the camera. That is a pre-registered NULL, not a failure.
#
# The 77 compute modules, the 4 rgs_restirgi and the 2 scalar-specular
# reference permutations ship BYTE-VERBATIM from the base and are cmp-asserted.
set -euo pipefail

MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="${CALLISTO_INSTALL_DIR:-$HOME/.local/lib/callisto}"
PY="$MOD_DIR/dev/patch_carglint.py"
VERIFY="$MOD_DIR/dev/verify_carglint.py"
WORK="$MOD_DIR/dev/disasm/carglint"

BASE=gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog
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
# Without this the "-ctl IS the base" claim rests on the patcher rather than on
# the toolchain, and gate 5 below could be satisfied by an assembler artefact.
# `94` sec 11 is the precedent.
echo "=== 1. round-trip neutrality (spirv-dis -> spirv-as == base bytes)"
for h in "${TARGETS[@]}"; do
    spirv-as --target-env spv1.4 "$WORK/asm/$h.spvasm" -o "$WORK/rt/$h.spv"
    cmp -s "$SRC/$h.rgs_reference_main.spv" "$WORK/rt/$h.spv" \
        || { echo "  !! $h does not round-trip -- no control built on it is meaningful" >&2; exit 1; }
done
echo "  10 of 10 reference permutations round-trip byte-identically"
rm -rf "$WORK/rt"

# --- 1b. the two declines, BY NAME -----------------------------------------
# `28` sec 5 / `94` sec 3.4: 40c6faab and ab7f1822 assemble a MONOCHROME
# specular (p*Vis*D, no 1-p lerp, no F0 in the lobe) and additionally carry no
# radiance write. They are declined by name and the reason is printed, never
# skipped silently -- a module count that differs from the ladder's is a
# finding (GOTCHAS).
echo "=== 1b. named declines"
for p in "${PASS[@]}"; do
    spirv-dis "$SRC/$p.rgs_reference_main.spv" -o "$WORK/asm/$p.decl.spvasm"
    python3 "$PY" "$WORK/asm/$p.decl.spvasm" --report --no-roundtrip-check \
        | python3 -c '
import json,sys
r=json.load(sys.stdin)[0]["carglint"]
assert r["ggx_blocks"]==0 and r["sg_sites"]==6, r
print("  %s: %d SG sites, 0 GGX blocks -- %s" % (sys.argv[1], r["sg_sites"], r["variant"]))
' "$p"
done

jobs="${CALLISTO_JOBS:-$(nproc 2>/dev/null || echo 4)}"

patch_set () {   # $1 = outdir, $2.. = patcher args
    local out="$1"; shift
    mkdir -p "$out"
    : > "$WORK/.args"
    if (( $# )); then printf '%s\n' "$@" > "$WORK/.args"; fi
    printf '%s\0' "${TARGETS[@]}" | CB_O="$out" CB_P="$PY" CB_W="$WORK" \
        CB_A="$WORK/.args" xargs -0 -P "$jobs" -n1 bash -c '
            mapfile -t A < "$CB_A"
            python3 "$CB_P" "$CB_W/asm/$0.spvasm" ${A[@]+"${A[@]}"} --outdir "$CB_O" \
                > "$CB_O/$0.carglint.report.json"'
    rm -f "$WORK/.args"
    local n; n=$(ls "$out"/*.spv 2>/dev/null | wc -l)
    [[ "$n" == 10 ]] || { echo "  !! $out produced $n modules, want 10" >&2; exit 1; }
}

assemble () {   # $1 = dest, $2 = patched dir, $3 = 1 if the 10 must DIFFER
    local dest="$1" src="$2" must_differ="$3"
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
    local d=0
    for h in "${TARGETS[@]}"; do
        cmp -s "$SRC/$h.rgs_reference_main.spv" "$dest/$h.rgs_reference_main.spv" || d=$((d+1))
    done
    if (( must_differ )); then
        [[ "$d" == 10 ]] || { echo "  !! only $d of 10 modules differ from the base -- the splice emitted nothing" >&2; exit 1; }
    else
        [[ "$d" == 0 ]] || { echo "  !! $d of 10 CONTROL modules differ from the base -- k_glint=0 is not a null" >&2; exit 1; }
    fi
    local n; n=$(ls "$dest"/*.spv | wc -l)
    [[ "$n" == 93 ]] || { echo "  !! $dest has $n modules, expected 93" >&2; exit 1; }
    for f in "$dest"/*.spv; do
        spirv-val --target-env vulkan1.4 "$f" >/dev/null \
            || { echo "  !! spirv-val --target-env vulkan1.4 FAILED: $f" >&2; exit 1; }
    done
}

echo "=== 2. patch + assemble the five rungs"
declare -A RUNG_ARGS=(
  [carglint-ctl]="--k-glint 0"
  [carglint]=""
  [carglint-dense]="--nu0 600000"
  [carglint-sparse]="--nu0 37500"
  [carglint-cell]="--mode cell --cell 0.25"
)
declare -A RUNG_DIFFER=( [carglint-ctl]=0 [carglint]=1 [carglint-dense]=1
                         [carglint-sparse]=1 [carglint-cell]=1 )
ORDER=(carglint-ctl carglint carglint-dense carglint-sparse carglint-cell)
for r in "${ORDER[@]}"; do
    # shellcheck disable=SC2086
    patch_set "$WORK/p.$r" ${RUNG_ARGS[$r]}
    assemble "$MOD_DIR/swaps.$r" "$WORK/p.$r" "${RUNG_DIFFER[$r]}"
    echo "  swaps.$r: 93 modules, spirv-val (vulkan1.4) clean  [${RUNG_ARGS[$r]:-defaults}]"
done

# one variable per rung: the three glint rungs must differ from EACH OTHER on
# every patched module, or "denser" and "sparser" are not what they say.
for pair in "carglint carglint-dense" "carglint carglint-sparse" \
            "carglint-dense carglint-sparse" "carglint carglint-cell"; do
    set -- $pair
    d=0
    for h in "${TARGETS[@]}"; do
        cmp -s "$MOD_DIR/swaps.$1/$h.rgs_reference_main.spv" \
               "$MOD_DIR/swaps.$2/$h.rgs_reference_main.spv" || d=$((d+1))
    done
    [[ "$d" == 10 ]] || { echo "  !! only $d of 10 modules differ between $1 and $2" >&2; exit 1; }
    echo "  10 of 10 differ: $1 vs $2"
done

# --- 3. coverage, from the REPORTS, never from byte counts (the `42` rule) --
echo "=== 3. coverage census"
python3 - "$MOD_DIR" "${ORDER[@]}" <<'PY' || exit 1
import glob, json, os, sys
mod_dir, rungs = sys.argv[1], sys.argv[2:]
bad = []
for r in rungs:
    d = os.path.join(mod_dir, 'swaps.' + r)
    mods = blocks = sites = emitted = painted = skipped = 0
    members, f0 = set(), set()
    for f in sorted(glob.glob(os.path.join(d, '*.carglint.report.json'))):
        rep = json.load(open(f))[0]
        c = rep['carglint']
        if rep.get('spirv_val') != 'clean':
            bad.append((r, rep['module'], 'spirv-val not clean'))
        mods += 1
        blocks += c['ggx_blocks']
        members.add(c['world_offset']['member'])
        f0.add(c['f0_metallic_agrees'])
        if c['mode'] == 'glint':
            if c.get('emitted'):
                sites += len(c['per_arm'])
                emitted += c['emitted']
                if c['uses_rewritten'] != 18:
                    bad.append((r, rep['module'],
                                f"{c['uses_rewritten']} uses rewritten, want 18"))
        else:
            painted += len(c['painted'])
            for s in c['skipped']:
                if s['why'] not in ('constant-zero', 'scalar-broadcast',
                                    'texel not a v4float construct'):
                    bad.append((r, rep['module'], 'unexpected skip: ' + s['why']))
                skipped += 1
    if mods != 10:
        bad.append((r, '-', f'{mods} patched modules, want 10'))
    if blocks != 60:
        bad.append((r, '-', f'{blocks} GGX blocks, want 60'))
    if members != {56}:
        bad.append((r, '-', f'world-offset members {sorted(members)}, want {{56}}'))
    if f0 != {18}:
        bad.append((r, '-', f'F0-chain metallic agreements {sorted(f0)}, want {{18}}'))
    if r == 'carglint-ctl' and (sites or emitted):
        bad.append((r, '-', 'the control emitted instructions'))
    if r not in ('carglint-ctl', 'carglint-cell') and sites != 60:
        bad.append((r, '-', f'{sites} glint sites, want 60'))
    print(f'  {r:17s} 10 modules, 60 GGX blocks, member 56 x10, F0 metallic '
          f'18/18 x10, {sites} glint sites, {painted} painted writes, '
          f'{skipped} benign skips, {emitted} instructions')
if bad:
    for b in bad[:12]:
        sys.stderr.write('    %s :: %s :: %s\n' % b)
    sys.exit(1)
PY

# --- 4. the control is the base, byte for byte, on all 93 ------------------
echo "=== 4. k_glint = 0 is a REAL null"
d=0
for f in "$MOD_DIR/swaps.carglint-ctl"/*.spv; do
    cmp -s "$SRC/$(basename "$f")" "$f" || d=$((d+1))
done
[[ "$d" == 0 ]] || { echo "  !! $d of 93 control modules differ from the base" >&2; exit 1; }
echo "  93 of 93 modules cmp-identical to $BASE (through dis -> patcher -> as -> val)"

# --- 5. the verifier, on shipped bytes, proven non-vacuous ----------------
echo "=== 5. verifier"
python3 "$VERIFY" "$MOD_DIR/swaps.carglint"
python3 "$VERIFY" "$MOD_DIR/swaps.carglint-dense"  --nu0 600000
python3 "$VERIFY" "$MOD_DIR/swaps.carglint-sparse" --nu0 37500
python3 "$VERIFY" "$MOD_DIR/swaps.carglint-cell"   --mode cell --cell 0.25
python3 "$VERIFY" "$MOD_DIR/swaps.carglint-ctl"    --ctl

reject () {  # $1 = human name, rest = verifier args
    local what="$1"; shift
    if python3 "$VERIFY" "$@" >/dev/null 2>&1; then
        echo "  !! the verifier ACCEPTS $what -- it is vacuous" >&2; exit 1
    fi
    echo "  rejects $what, as required"
}
echo "  non-vacuity:"
reject "the unpatched base"                    "$SRC"
reject "the k_glint=0 control read as a rung"  "$MOD_DIR/swaps.carglint-ctl"
reject "the feature read as the control"       "$MOD_DIR/swaps.carglint" --ctl
reject "the glint rung read as the diagnostic" "$MOD_DIR/swaps.carglint" --mode cell
reject "the diagnostic read as a glint rung"   "$MOD_DIR/swaps.carglint-cell"
reject "carglint read with the dense knobs"    "$MOD_DIR/swaps.carglint" --nu0 600000
reject "carglint-dense read with the defaults" "$MOD_DIR/swaps.carglint-dense"
reject "carglint-sparse read as dense"         "$MOD_DIR/swaps.carglint-sparse" --nu0 600000
for dc in camrel nogate viewbin; do
    patch_set "$WORK/p.decoy_$dc" --decoy "$dc"
    assemble  "$WORK/rung.decoy_$dc" "$WORK/p.decoy_$dc" 1
    reject "a --decoy $dc build" "$WORK/rung.decoy_$dc"
done
# and the diagnostic's own decoy: the crawl test is worthless if the cell hash
# does not actually carry the world offset.
patch_set "$WORK/p.decoy_cellcamrel" --mode cell --cell 0.25 --decoy camrel
assemble  "$WORK/rung.decoy_cellcamrel" "$WORK/p.decoy_cellcamrel" 1
reject "a --mode cell --decoy camrel build" \
       "$WORK/rung.decoy_cellcamrel" --mode cell --cell 0.25

# --- 6. MANIFESTs ---------------------------------------------------------
manifest () {   # $1 = dest, $2 = rung, $3 = tail
    sed -e "1s/^$BASE /$2 /" \
        -e "1s/ref=12([^)]*)/ref=12(10 carglint ${RUNG_ARGS[$2]:-defaults} + 2 scalar-specular pass-through)/" \
        "$SRC/MANIFEST.txt" > "$1/MANIFEST.txt"
    grep -q "^$2 " "$1/MANIFEST.txt" || { echo "MANIFEST rewrite failed" >&2; exit 1; }
    {   echo "# $2 (handoff/100): 94 sec 4.4's metallic-flake glints at the six"
        echo "# GGX specular lobes of 10 of 12 rgs_reference_main. World cell from"
        echo "# hit + cbv[..][56].xyz (98 sec 15), dyadic LOD from the footprint,"
        echo "# world-frame angular bin from H, pcg mix, Bernoulli flake with the"
        echo "# probability-side firefly clamp so E[glint] = 1 EXACTLY."
        echo "# $3"
        echo "# 94 sec 2.1: this site does NOT shade the primary hit. Glints land"
        echo "# inside reflections and on second-bounce light, not on the car in"
        echo "# front of the camera. Read handoff/100 section 7 BEFORE the screen."
    } >> "$1/MANIFEST.txt"
}
manifest "$MOD_DIR/swaps.carglint-ctl"    carglint-ctl    "k_glint = 0: NOTHING emitted, 93 of 93 modules byte-identical to $BASE. Must be indistinguishable from it."
manifest "$MOD_DIR/swaps.carglint"        carglint        "94 sec 4.4 at its defaults: cell 8 mm, nu0 1.5e5, theta_bin 0.02, glint_max 16, k_glint 1."
manifest "$MOD_DIR/swaps.carglint-dense"  carglint-dense  "nu0 x4 = 6.0e5 -- denser flakes. ONE variable against carglint."
manifest "$MOD_DIR/swaps.carglint-sparse" carglint-sparse "nu0 /4 = 3.75e4 -- sparser flakes. ONE variable against carglint."
manifest "$MOD_DIR/swaps.carglint-cell"   carglint-cell   "94 sec 6.3 step 4's -glintcell: no glint; the PRIMARY hit's 25 cm world cell hash painted flat. Cells welded to geometry under camera translation = the offset is right; crawling = it is wrong and the family stops."

echo
for r in "${ORDER[@]}"; do
    printf '  %-17s content sha %s\n' "$r" \
        "$(cat "$MOD_DIR/swaps.$r"/*.spv | sha256sum | cut -c1-16)"
done
echo
if (( DO_INSTALL )); then
    for r in "${ORDER[@]}"; do
        park="$INSTALL_DIR/skin.set/$r"
        mkdir -p "$park"; rm -f "$park"/*.spv "$park"/*.json "$park/MANIFEST.txt"
        cp -pf "$MOD_DIR/swaps.$r"/*.spv "$MOD_DIR/swaps.$r"/*.json \
               "$MOD_DIR/swaps.$r/MANIFEST.txt" "$park/"
        echo "  parked -> $park ($(ls "$park"/*.spv | wc -l) modules)"
    done
else
    echo "NOT installed. To park: ./dev/build_carglint.sh --install"
fi
echo
echo "select with skinspec=carglint-cell (SHOOT THIS FIRST) | carglint"
echo "            | carglint-dense | carglint-sparse | carglint-ctl"
echo "contract: ser=class + shadowset=full-shadow ($BASE's own)."
