#!/usr/bin/env bash
# handoff/89 -- raise the reference path tracer's BOUNCE-LOOP BOUND to a floor
# of N, in ALL TWELVE rgs_reference_main permutations.
#
# Why a patch and not just the CVar: BounceNumber / BounceNumberScreenshot are
# already in the CET panel and DO move 8 of the 12 permutations, but the other
# 4 constant-folded the bound to 2 at compile time and no CVar can reach them.
# The dispatched permutation changes per launch (88 sec 1), so the CVar alone
# gives a bounce depth that is a coin flip per run.
#
# The edit is UMax(bound, N), so a CVar set ABOVE N still wins: this raises a
# floor, it never caps. Two lines added per module and the verifier asserts
# exactly that.
#
# Reach: rgs_reference_main ONLY. All 77 compute and all 4 ReSTIR-GI modules
# are byte-identical to the base and are cmp-asserted so.
set -euo pipefail

MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="${CALLISTO_INSTALL_DIR:-$HOME/.local/lib/callisto}"
BASE_NAME="gi-50b-bleed-oil-sheen-deep-clothhi"
GI="$MOD_DIR/swaps.gi.${BASE_NAME#gi-}"
PARK_BASE="$INSTALL_DIR/skin.set/$BASE_NAME"
WORK="$MOD_DIR/dev/disasm/bounce12"
PY="$MOD_DIR/dev/patch_bounce.py"
VERIFY="$MOD_DIR/dev/verify_bounce.py"
K0="$MOD_DIR/dev/disasm/bounce_n0"

DO_INSTALL=0
[[ "${1:-}" == "--install" ]] && DO_INSTALL=1

# rung -> N, the MINIMUM bounce-loop iterations. ONE VARIABLE PER STEP.
# The engine ships bound=2 baked, or a CVar that defaults to 2, so -b2 is the
# on-screen control: it must be indistinguishable from the base rung, and if it
# is not, the loop-bound identification is wrong and nothing else here is safe.
RUNG_NAMES=(gi-50b-bleed-oil-sheen-deep-clothhi-b2
            gi-50b-bleed-oil-sheen-deep-clothhi-b3
            gi-50b-bleed-oil-sheen-deep-clothhi-b4)
RUNG_NS=(2 3 4)

[[ -f "$GI/MANIFEST.txt" ]] || { echo "no $GI/MANIFEST.txt" >&2; exit 1; }

# --- base provenance: the repo dir must BE the parked standing rung ---------
if [[ -d "$PARK_BASE" ]]; then
    for f in "$GI"/*.spv; do
        cmp -s "$f" "$PARK_BASE/$(basename "$f")" || {
            echo "base drift: $(basename "$f") differs from $PARK_BASE" >&2; exit 1; }
    done
    echo "  base provenance: $(basename "$GI") == skin.set/$BASE_NAME (93/93)"
else
    echo "  base provenance: $PARK_BASE not parked -- repo dir taken as base" >&2
fi

mapfile -t REFS < <(cd "$GI" && ls *.rgs_reference_main.spv | sed 's/\..*//')
(( ${#REFS[@]} == 12 )) || { echo "base has ${#REFS[@]} rgs_reference_main, expected 12" >&2; exit 1; }
NDX=$(ls "$GI"/*.dxil.spv | wc -l)
(( NDX == 77 )) || { echo "base has $NDX dxil, expected 77" >&2; exit 1; }
NRI=$(ls "$GI"/*.rgs_restirgi_*.spv | wc -l)
(( NRI == 4 )) || { echo "base has $NRI restirgi, expected 4" >&2; exit 1; }

python3 "$VERIFY" --negative "$GI"

rm -rf "$WORK"; mkdir -p "$WORK"
for h in "${REFS[@]}"; do
    spirv-dis "$GI/$h.rgs_reference_main.spv" -o "$WORK/$h.spvasm"
done

jobs="${CALLISTO_JOBS:-$(nproc 2>/dev/null || echo 4)}"

patch_all() {  # $1 destdir  $2 n
    printf '%s\0' "${REFS[@]}" | CB_D="$1" CB_P="$PY" CB_W="$WORK" CB_N="$2" \
        xargs -0 -P "$jobs" -n1 bash -c '
            python3 "$CB_P" "$CB_W/$0.spvasm" --n "$CB_N" --outdir "$CB_D" \
                > "$CB_D/$0.rgs.report.json"'
}

# --- n=0 identity control: every detector runs, nothing is emitted ----------
rm -rf "$K0"; mkdir -p "$K0"
patch_all "$K0" 0
nk=0
for f in "$K0"/*.spv; do
    cmp -s "$f" "$GI/$(basename "$f")" || {
        echo "n=0 rebuild DIFFERS from base: $(basename "$f")" >&2; exit 1; }
    nk=$((nk+1))
done
(( nk == 12 )) || { echo "n=0 control produced $nk modules, expected 12" >&2; exit 1; }
echo "  n=0 identity control: $nk/12 byte-identical to base"

# --- the bound census, printed once, from the n=0 reports -------------------
python3 - "$K0" << 'PYS'
import glob, json, os, sys
lit = run = 0
comp = {}
for f in sorted(glob.glob(os.path.join(sys.argv[1], '*.rgs.report.json'))):
    b = json.load(open(f))['bounce']
    if b['bound_kind'] == 'literal':
        lit += 1
    else:
        run += 1
        comp[b['bound_def'].split()[-1]] = comp.get(b['bound_def'].split()[-1], 0) + 1
print(f"  bound census: {run}/12 runtime (CVar-reachable), {lit}/12 baked "
      f"literal; runtime components " + ', '.join(f"[{k}]x{v}" for k, v in sorted(comp.items())))
if lit == 0:
    print("  UNEXPECTED: no baked-literal permutation -- 29 secB3 and 89 both "
          "say there are 4. Re-read before trusting this build."); sys.exit(1)
PYS
rm -rf "$K0"

build_rung() {  # $1 rung name  $2 n
    local name="$1" n="$2"
    local dest="$MOD_DIR/swaps.gi.${1#gi-}"
    rm -rf "$dest"; mkdir -p "$dest"
    echo "== $name  (bounce floor n=$n)"
    patch_all "$dest" "$n"

    # --- HARD GATE: 12 modules, one rewrite each, no skips ------------------
    python3 - "$dest" "$n" << 'PYS'
import glob, json, os, sys
d, n = sys.argv[1], int(sys.argv[2])
mods, bad = 0, []
for f in sorted(glob.glob(os.path.join(d, '*.rgs.report.json'))):
    r = json.load(open(f))['bounce']
    h = os.path.basename(f).split('.')[0]
    if r['n'] != n:
        bad.append(f"{h}: n {r['n']} != {n}")
    if r.get('emitted') != 1:
        bad.append(f"{h}: emitted {r.get('emitted')}, expected 1")
    if 'new_bound' not in r:
        bad.append(f"{h}: no rewritten bound")
    mods += 1
if mods != 12 or bad:
    print(f'BOUND COVERAGE FAILED: {mods} modules\n  ' + '\n  '.join(bad))
    sys.exit(1)
print(f'  bound coverage: {mods}/12 modules, 1 rewrite each')
PYS

    # --- verbatim halves: 77 dxil + 4 restirgi, cmp-asserted ---------------
    cp -pf "$GI"/*.dxil.spv "$dest/"
    cp -pf "$GI"/*.rgs_restirgi_*.spv "$dest/"
    local nv=0
    for f in "$GI"/*.dxil.spv "$GI"/*.rgs_restirgi_*.spv; do
        cmp -s "$f" "$dest/$(basename "$f")" || { echo "verbatim copy differs: $f" >&2; exit 1; }
        nv=$((nv+1))
    done
    (( nv == 81 )) || { echo "$name: cmp-asserted $nv verbatim, expected 81" >&2; exit 1; }
    for h in "${REFS[@]}"; do
        cmp -s "$GI/$h.rgs_reference_main.spv" "$dest/$h.rgs_reference_main.spv" \
            && { echo "$name: $h identical to base -- rewrite emitted nothing" >&2; exit 1; }
    done

    local nval=0
    for f in "$dest"/*.spv; do
        spirv-val "$f" || { echo "spirv-val FAILED: $f" >&2; exit 1; }
        nval=$((nval+1))
    done
    (( nval == 93 )) || { echo "$name: spirv-val ran on $nval, expected 93" >&2; exit 1; }
    echo "  spirv-val: $nval/93 clean"

    python3 "$VERIFY" "$dest" "$GI" --n "$n"

    sed -e "1s/^$BASE_NAME /$name /" \
        -e "1s/ref=12(pass-through)/ref=12(12 bounce floor n=$n via UMax)/" \
        -e "1s/ built=.*$/ built=$(date -Iseconds)/" \
        "$GI/MANIFEST.txt" > "$dest/MANIFEST.txt"
    grep -q "^$name " "$dest/MANIFEST.txt" || { echo "MANIFEST rewrite failed" >&2; exit 1; }
    for tag in src_ser ser_sha=310513f3008cbde4 ptq_sha=55ed4e5c6884ab71; do
        grep -q "$tag" "$dest/MANIFEST.txt" || { echo "MANIFEST lost $tag" >&2; exit 1; }
    done
    {
        echo "# bounce-loop floor (handoff/89), reference/photo-mode PT ONLY."
        echo "# The loop's exit test becomes  bounce+1 < UMax(bound, $n)."
        echo "# UMax, so BounceNumber/BounceNumberScreenshot set ABOVE $n still"
        echo "# win -- this raises a floor, it never caps. 8 of the 12"
        echo "# permutations read that CVar; the other 4 baked the bound to 2"
        echo "# and are reachable ONLY by this patch."
        echo "# Costs rays: the loop body is a whole path segment, so n=3 is"
        echo "# roughly +50% path work against the shipped 2. Adds indirect"
        echo "# DEPTH, not samples -- it is not a noise fix."
        echo "# A/B against $BASE_NAME; -b2 is the control and must look"
        echo "# identical to it. NOT working until the screen says so."
    } > "$dest/README.txt"
    rm -f "$dest"/*.spvasm
    echo "  built $dest"
}

for i in "${!RUNG_NAMES[@]}"; do
    build_rung "${RUNG_NAMES[$i]}" "${RUNG_NS[$i]}"
done

if (( DO_INSTALL )); then
    mkdir -p "$INSTALL_DIR/skin.set"
    for name in "${RUNG_NAMES[@]}"; do
        src="$MOD_DIR/swaps.gi.${name#gi-}"
        dst="$INSTALL_DIR/skin.set/$name"
        rm -rf "$dst"; mkdir -p "$dst"
        cp -pf "$src"/*.spv "$src"/MANIFEST.txt "$src"/README.txt "$dst/"
        echo "  parked skin.set/$name ($(ls "$dst"/*.spv | wc -l) modules)"
    done
    echo "NOW RUN: make install   (init.lua selector rows)"
fi
echo "OK -- ${#RUNG_NAMES[@]} rungs. Nothing is working until the screen says so."
