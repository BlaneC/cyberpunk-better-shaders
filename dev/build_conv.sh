#!/usr/bin/env bash
# handoff/92 -- the CONVERGED-MODE PROFILE: one rung on the standing selection
# that spends handoff/89's bounce floor and handoff/77's skin sample floor ONLY
# when the frame is being paid for with samples, and is behaviourally the
# standing rung otherwise.
#
# The gate, stated plainly because it is NOT an accumulation flag:
#
#     accum := ( bitcast(cbv[188]).y > 1 )      i.e. RayNumber raised above 1
#
# There is no accumulation flag in these bytes (dev/patch_conv.py's header
# carries the census). This is handoff/92's declared fallback and it is true in
# exactly the configuration 89 sec 5b names -- photo mode with RayNumber raised
# or reference accumulation running -- and false in 1 spp gameplay, which is the
# configuration where both rungs were falsified on screen.
#
# Reach: rgs_reference_main ONLY. All 77 compute and all 4 ReSTIR-GI modules are
# byte-identical to the base and are cmp-asserted so.
#   bounce floor  12/12
#   skin spp      10/12 (6 dyn + 4 baked); the 2 SER permutations carry no class
#                 mask and are pass-through, exactly as in handoff/77's own rung
#                 (`ref=12(6 spp4-dyn + 4 spp4-baked + 2 pass-through)`).
set -euo pipefail

MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="${CALLISTO_INSTALL_DIR:-$HOME/.local/lib/callisto}"
BASE_NAME="gi-50b-bleed-oil-sheen-deep-clothhi-cone2all"
RUNG_NAME="${BASE_NAME}-conv"
GI="$MOD_DIR/swaps.gi.${BASE_NAME#gi-}"
DEST="$MOD_DIR/swaps.gi.${RUNG_NAME#gi-}"
PARK_BASE="$INSTALL_DIR/skin.set/$BASE_NAME"
WORK="$MOD_DIR/dev/disasm/conv12"
OFF="$MOD_DIR/dev/disasm/conv_off"
PY="$MOD_DIR/dev/patch_conv.py"
VERIFY="$MOD_DIR/dev/verify_conv.py"

N="${CALLISTO_CONV_N:-3}"          # bounce-loop floor WHEN ACCUMULATING
SPP="${CALLISTO_CONV_SPP:-4}"      # skin sample floor WHEN ACCUMULATING

DO_INSTALL=0
[[ "${1:-}" == "--install" ]] && DO_INSTALL=1

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

# --- negative control: the base carries neither gated edit ------------------
python3 "$VERIFY" "$GI" "$GI" --n 0 --spp 0
echo "  negative control: base carries no bounce floor and no skin sample select"

rm -rf "$WORK"; mkdir -p "$WORK"
for h in "${REFS[@]}"; do
    spirv-dis "$GI/$h.rgs_reference_main.spv" -o "$WORK/$h.spvasm"
done

jobs="${CALLISTO_JOBS:-$(nproc 2>/dev/null || echo 4)}"

patch_all() {  # $1 destdir  $2 extra args
    printf '%s\0' "${REFS[@]}" | CB_D="$1" CB_P="$PY" CB_W="$WORK" CB_A="$2" \
        xargs -0 -P "$jobs" -n1 bash -c '
            python3 "$CB_P" "$CB_W/$0.spvasm" $CB_A --outdir "$CB_D" \
                > "$CB_D/$0.rgs.report.json"'
}

# --- --off identity control: every detector runs, nothing is emitted --------
rm -rf "$OFF"; mkdir -p "$OFF"
patch_all "$OFF" "--off"
nk=0
for f in "$OFF"/*.spv; do
    cmp -s "$f" "$GI/$(basename "$f")" || {
        echo "--off rebuild DIFFERS from base: $(basename "$f")" >&2; exit 1; }
    nk=$((nk+1))
done
(( nk == 12 )) || { echo "--off control produced $nk modules, expected 12" >&2; exit 1; }
echo "  gate-disabled control: $nk/12 byte-identical to the base rung"

# --- the census, printed once, from the --off reports -----------------------
python3 - "$OFF" << 'PYS'
import glob, json, os, sys
lit = run = 0
tiers = {}
for f in sorted(glob.glob(os.path.join(sys.argv[1], '*.rgs.report.json'))):
    r = json.load(open(f))
    b = r['bounce']
    tiers[r['tier']] = tiers.get(r['tier'], 0) + 1
    if b['bound_kind'] == 'literal':
        lit += 1
    else:
        run += 1
print(f"  bound census: {run}/12 runtime (CVar-reachable), {lit}/12 baked literal")
print("  skin tiers:   " + ', '.join(f"{k}x{v}" for k, v in sorted(tiers.items())))
if lit != 4:
    print("  UNEXPECTED: baked-literal count is not 4 -- 29 secB3, 77 and 89 all "
          "say 4. Re-read before trusting this build."); sys.exit(1)
if tiers.get('dyn') != 6 or tiers.get('baked') != 4 or tiers.get('ser') != 2:
    print("  UNEXPECTED tier split -- 77 shipped 6 dyn + 4 baked + 2 "
          "pass-through."); sys.exit(1)
PYS
rm -rf "$OFF"

# ---------------------------------------------------------------- the rung
rm -rf "$DEST"; mkdir -p "$DEST"
echo "== $RUNG_NAME  (accum gate: cbv[188].y > 1; floor n=$N, skin spp=$SPP)"
patch_all "$DEST" "--n $N --spp $SPP"

python3 - "$DEST" "$N" "$SPP" << 'PYS'
import glob, json, os, sys
d, n, spp = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
mods, bad, nb, ns = 0, [], 0, 0
for f in sorted(glob.glob(os.path.join(d, '*.rgs.report.json'))):
    r = json.load(open(f))
    h = os.path.basename(f).split('.')[0]
    b, s = r['bounce'], r['skin_spp']
    if b.get('n') != n or b.get('emitted') != 1 or 'new_bound' not in b:
        bad.append(f"{h}: bounce floor not emitted ({b.get('emitted')})")
    else:
        nb += 1
    if 'floor_select' not in b or 'accum' not in b:
        bad.append(f"{h}: bounce floor is not gated")
    if r['tier'] == 'ser':
        if s.get('spp') != 0:
            bad.append(f"{h}: SER permutation got a skin edit")
    else:
        if s.get('spp') != spp or 'gated' not in s.get('gate', {}):
            bad.append(f"{h}: skin spp not emitted or not gated")
        else:
            ns += 1
    if r.get('cbv_word') != 188 or r.get('rayn_component') != 1:
        bad.append(f"{h}: gate reads cbv[{r.get('cbv_word')}] component "
                   f"{r.get('rayn_component')}, want 188.y")
    mods += 1
if mods != 12 or nb != 12 or ns != 10 or bad:
    print(f'COVERAGE FAILED: {mods} modules, {nb} bounce, {ns} skin\n  '
          + '\n  '.join(bad))
    sys.exit(1)
print(f'  coverage: {nb}/12 gated bounce floors, {ns}/12 gated skin sample '
      f'floors (2 SER pass-through)')
PYS

# --- verbatim halves: 77 dxil + 4 restirgi, cmp-asserted -------------------
cp -pf "$GI"/*.dxil.spv "$DEST/"
cp -pf "$GI"/*.rgs_restirgi_*.spv "$DEST/"
nv=0
for f in "$GI"/*.dxil.spv "$GI"/*.rgs_restirgi_*.spv; do
    cmp -s "$f" "$DEST/$(basename "$f")" || { echo "verbatim copy differs: $f" >&2; exit 1; }
    nv=$((nv+1))
done
(( nv == 81 )) || { echo "cmp-asserted $nv verbatim, expected 81" >&2; exit 1; }
for h in "${REFS[@]}"; do
    cmp -s "$GI/$h.rgs_reference_main.spv" "$DEST/$h.rgs_reference_main.spv" \
        && { echo "$h identical to base -- the rewrite emitted nothing" >&2; exit 1; }
done
echo "  verbatim halves: $nv/81 cmp-identical; 12/12 raygens differ from base"

nval=0
for f in "$DEST"/*.spv; do
    spirv-val "$f" || { echo "spirv-val FAILED: $f" >&2; exit 1; }
    nval=$((nval+1))
done
(( nval == 93 )) || { echo "spirv-val ran on $nval, expected 93" >&2; exit 1; }
echo "  spirv-val: $nval/93 clean"

# --- the verifier, from the SHIPPED bytes ----------------------------------
python3 "$VERIFY" "$DEST" "$GI" --n "$N" --spp "$SPP" --gate accum

# --- and the proof it is NOT vacuous on the gate axis (handoff/90 sec 2) ----
# Four cross-checks, all of which must come out the way they are named. Two of
# them run against rungs that are ALREADY ON DISK and are the ungated originals
# of the two halves spliced here, so this is not a self-consistency test.
nonvac() {  # $1 label  $2 expect(pass|fail)  $3.. argv
    local label="$1" expect="$2"; shift 2
    if python3 "$VERIFY" "$@" > /dev/null 2>&1; then got=pass; else got=fail; fi
    if [[ "$got" != "$expect" ]]; then
        echo "NON-VACUITY CHECK FAILED: $label expected $expect, got $got" >&2
        python3 "$VERIFY" "$@" 2>&1 | tail -5 >&2
        exit 1
    fi
    echo "    $label -> $got (expected)"
}
echo "  non-vacuity of the gate axis:"
nonvac "this rung under --gate none" fail \
       "$DEST" "$GI" --n "$N" --spp "$SPP" --gate none
B3="$MOD_DIR/swaps.gi.50b-bleed-oil-sheen-deep-clothhi"
if [[ -d "${B3}-b3" ]]; then
    nonvac "89's ungated -b3 under --gate accum" fail \
           "${B3}-b3" "$B3" --n 3 --spp 0 --gate accum
    nonvac "89's ungated -b3 under --gate none " pass \
           "${B3}-b3" "$B3" --n 3 --spp 0 --gate none
else
    echo "    (skipped: swaps.gi.50b-...-clothhi-b3 not present)" >&2
fi
S4="$MOD_DIR/swaps.gi-50b-bleed-oil-sheen-spp4"
S4B="$MOD_DIR/swaps.gi.50b-bleed-oil-sheen"
if [[ -d "$S4" && -d "$S4B" ]]; then
    nonvac "77's ungated -spp4 under --gate accum" fail \
           "$S4" "$S4B" --n 0 --spp 4 --gate accum
    nonvac "77's ungated -spp4 under --gate none " pass \
           "$S4" "$S4B" --n 0 --spp 4 --gate none
else
    echo "    (skipped: swaps.gi-50b-bleed-oil-sheen-spp4 not present)" >&2
fi

# --- MANIFEST + README ------------------------------------------------------
sed -e "1s/^$BASE_NAME /$RUNG_NAME /" \
    -e "1s#ref=12([^)]*)#ref=12(cone + converged profile: gate cbv[188].y>1, bounce floor $N 12/12, skin spp $SPP 10/12 + 2 pass-through)#" \
    -e "1s/ built=.*$/ built=$(date -Iseconds)/" \
    "$GI/MANIFEST.txt" > "$DEST/MANIFEST.txt"
grep -q "^$RUNG_NAME " "$DEST/MANIFEST.txt" || { echo "MANIFEST rewrite failed" >&2; exit 1; }
for tag in src_ser ser_sha=310513f3008cbde4 ptq_sha=55ed4e5c6884ab71; do
    grep -q "$tag" "$DEST/MANIFEST.txt" || { echo "MANIFEST lost $tag" >&2; exit 1; }
done
{
    echo "# CONVERGED-MODE PROFILE (handoff/92). Reference/photo-mode PT only."
    echo "#"
    echo "# The gate, and it is NOT an accumulation flag -- there is none in"
    echo "# these bytes:   accum := bitcast(cbv[188]).y > 1   (RayNumber > 1)."
    echo "#"
    echo "# When accum is FALSE (1 spp gameplay) this rung is BEHAVIOURALLY the"
    echo "# standing rung $BASE_NAME:"
    echo "#   bound' = UMax(bound, 0) is the identity on any uint;"
    echo "#   eff    = rayN (dyn tier); N = 1 and 1/N = 1.0 exactly (baked)."
    echo "# It is NOT byte-identical -- the gate's own instructions are here."
    echo "# The byte-identity control is the build's --off rebuild, 12/12."
    echo "#"
    echo "# When accum is TRUE it costs, together, roughly what -b3 and -spp4"
    echo "# cost separately: ~+50% path work (89 sec 5) and ~+60-90% on the PT"
    echo "# pass in a face close-up (29 sec B7). Both were REVERTED on screen at"
    echo "# 1 spp; 89 sec 5b names raised RayNumber / reference accumulation as"
    echo "# the only configuration where they pay."
    echo "#"
    echo "# A/B: this rung vs $BASE_NAME, same frame, camera"
    echo "# pinned, RayNumber raised the SAME amount in both halves. At"
    echo "# RayNumber = 1 the two halves are the same picture BY CONSTRUCTION"
    echo "# and that launch measures nothing."
    echo "# NOT working until the screen says so."
} > "$DEST/README.txt"
rm -f "$DEST"/*.spvasm
echo "  built $DEST"

if (( DO_INSTALL )); then
    mkdir -p "$INSTALL_DIR/skin.set"
    dst="$INSTALL_DIR/skin.set/$RUNG_NAME"
    rm -rf "$dst"; mkdir -p "$dst"
    cp -pf "$DEST"/*.spv "$DEST"/MANIFEST.txt "$DEST"/README.txt "$dst/"
    echo "  parked skin.set/$RUNG_NAME ($(ls "$dst"/*.spv | wc -l) modules)"
    echo "NOW RUN: make install   (init.lua selector row) -- NOT run here."
fi
echo "OK -- 1 rung. Nothing is working until the screen says so."
