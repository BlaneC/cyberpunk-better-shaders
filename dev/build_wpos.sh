#!/usr/bin/env bash
# hunt-wpos: the probe family that measures which SPACE the compute resolvers'
# surface position P lives in (handoff/99).
#
#   ./dev/build_wpos.sh                # build + verify (no install)
#   ./dev/build_wpos.sh --install      # ALSO park all four rungs in skin.set/
#   ./dev/build_wpos.sh --cell 2.0 --install
#
# dev/hunt_wpos.py established, over the 77 compute modules of the standing
# rung, that 75 of them reconstruct
#     P = (cbv[registers[0]+12][69..72] . (px, py, depth, 1)) / w
#     V = normalize(cbv[registers[0]+12][0].xyz - P)
# with the depth read from registers[1]+0 (the D32 front depth, 38 sec 1.1),
# that 308 of 308 dot-shaped 1e-5-clamped NoV sites are built from that P, and
# that EVERY consumer of P in the whole set is a subtraction -- so the bytes
# cannot say whether P is world or camera-relative.  These rungs measure it.
#
# Rungs built:
#   hunt-wpos        the 1 m hash-cell pattern on P, with a 1 m up-axis stripe
#   hunt-wpos-cam    the same pattern on `P - C`: camera-relative BY
#                    CONSTRUCTION.  The control that must slide.
#   hunt-wpos-frac   RGB = frac(P/cell): reads the up axis and the units off a
#                    single frame
#   hunt-wpos-ctl    gain 0: 93 of 93 modules `cmp`-identical to the base,
#                    non-tautologically (step 2 proves dis -> as is byte-
#                    neutral on all 77 base modules FIRST)
#   (scratch) nostripe   full coverage, no up-axis stripe: the decoy the
#                    verifier MUST reject.
set -euo pipefail

MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="${CALLISTO_INSTALL_DIR:-$HOME/.local/lib/callisto}"
PY="$MOD_DIR/dev/patch_wpos.py"
VERIFY="$MOD_DIR/dev/verify_wpos.py"
HUNT="$MOD_DIR/dev/hunt_wpos.py"

BASE=gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog
NAME=hunt-wpos
DO_INSTALL=0
CELL=1.0
UP=2
EXTRA=()
while (( $# )); do
    case "$1" in
        --install) DO_INSTALL=1 ;;
        --base) BASE="${2:?--base needs a skin.set name}"; shift ;;
        --name) NAME="${2:?--name needs a rung name}"; shift ;;
        --cell) CELL="${2:?--cell needs metres}"; shift ;;
        --up)   UP="${2:?--up needs 0|1|2}"; shift ;;
        *) echo "unknown arg $1" >&2; exit 1 ;;
    esac
    shift
done
EXTRA=(--cell "$CELL" --up "$UP")
VEXTRA=(--cell "$CELL" --up "$UP")

SRC="$INSTALL_DIR/skin.set/$BASE"
WORK="$MOD_DIR/dev/disasm/wpos"
declare -A OUT=( [world]="$MOD_DIR/swaps.huntwpos"
                 [cam]="$MOD_DIR/swaps.huntwpos.cam"
                 [frac]="$MOD_DIR/swaps.huntwpos.frac"
                 [ctl]="$MOD_DIR/swaps.huntwpos.ctl" )

# --- 0. base provenance ----------------------------------------------------
echo "--- 0. base provenance ($BASE) ---"
[[ -f "$SRC/MANIFEST.txt" ]] || { echo "no $SRC/MANIFEST.txt -- the standing selection is not parked" >&2; exit 1; }
n_c=$(ls "$SRC"/*.dxil.spv | wc -l)
n_r=$(ls "$SRC"/*.rgs_*.spv | wc -l)
[[ "$n_c" == 77 ]] || { echo "$BASE has $n_c compute modules, expected 77" >&2; exit 1; }
[[ "$n_r" == 16 ]] || { echo "$BASE has $n_r raygen modules, expected 16" >&2; exit 1; }
echo "  77 compute + 16 raygen"

# --- 1. disassemble --------------------------------------------------------
rm -rf "$WORK"; mkdir -p "$WORK/asm" "$WORK/rt"
for k in world cam frac ctl nostripe; do mkdir -p "$WORK/$k"; done
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
    [[ "$ver" == spv1.3 ]] || echo "  note: $n is $ver, not spv1.3"
    spirv-as --target-env "$ver" "$a" -o "$WORK/rt/$n.spv"
    cmp -s "$SRC/$n.dxil.spv" "$WORK/rt/$n.spv" || { echo "  !! $n does not round-trip -- the control would be meaningless" >&2; exit 1; }
    same=$((same+1))
done
echo "  $same of 77 modules round-trip byte-identically at their own version"
rm -rf "$WORK/rt"

# --- 2b. the offline hunt, re-run on these exact bytes ---------------------
echo "--- 2b. hunt (dev/hunt_wpos.py) ---"
python3 "$HUNT" "$WORK/asm" --md "$MOD_DIR/handoff/99-WORLD-POS-TABLE.md" \
        --json "$WORK/hunt.json" | tail -16

# --- 3. patch --------------------------------------------------------------
patch_all () {   # $1 = outdir, rest = extra args
    local out="$1"; shift
    printf '%s\n' "$@" --outdir "$out" > "$WORK/.args"
    find "$WORK/asm" -name '*.spvasm' -print0 | \
        CB_ARGS="$WORK/.args" CB_PY="$PY" CB_OUT="$out" \
        xargs -0 -P "$jobs" -n1 bash -c '
            asm="$1"; n="$(basename "${asm%.spvasm}")"
            mapfile -t A < "$CB_ARGS"
            if python3 "$CB_PY" "$asm" "${A[@]}" > "$CB_OUT/.$n.json" 2>"$CB_OUT/.$n.err"; then
                : > "$CB_OUT/.ok.$n"
            else
                : > "$CB_OUT/.bad.$n"
            fi' _
    rm -f "$WORK/.args"
}
echo "--- 3. patch ---"
patch_all "$WORK/world" --gain 1.0 --mode hash --space world "${EXTRA[@]}"
patch_all "$WORK/cam"   --gain 1.0 --mode hash --space cam   "${EXTRA[@]}"
patch_all "$WORK/frac"  --gain 1.0 --mode frac --space world "${EXTRA[@]}"
patch_all "$WORK/ctl"   --gain 0.0
patch_all "$WORK/nostripe" --gain 1.0 --mode hash --space world --no-stripe "${EXTRA[@]}"

# --- 4. coverage, from the reports, never from byte counts -----------------
echo "--- 4. coverage ---"
python3 - "$MOD_DIR" "$WORK" <<'PY' || exit 1
import glob, json, os, sys
sys.path.insert(0, os.path.join(sys.argv[1], 'dev'))
import patch_wpos as WP
W = sys.argv[2]
bad = []

def scan(d, want_paint):
    badm = {os.path.basename(f)[5:] for f in glob.glob(os.path.join(d, '.bad.*'))}
    tot = dict(mods=0, writes=0, refetched=0, skipped=0)
    knobs = set()
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
        p = r.get('wpos')
        if p is None:
            bad.append((r.get('module'), 'no wpos report')); continue
        tot['mods'] += 1
        tot['writes'] += len(p['writes'])
        tot['refetched'] += len(p['refetched'])
        tot['skipped'] += len(p['skipped'])
        if want_paint:
            if not p['writes']:
                bad.append((r.get('module'), 'zero painted writes'))
            knobs.add(json.dumps([p['knobs'], p['mode'], p['space'],
                                  p['matrix']['members'], p['cbv_slot'],
                                  p['depth_slot'], p['campos_member']],
                                 sort_keys=True))
    return badm, tot, knobs

C = WP.CENSUS
for rung in ('world', 'cam', 'frac', 'nostripe'):
    badm, tot, knobs = scan(os.path.join(W, rung), True)
    print('  %-8s: %d modules, %d declined, %d writes (%d refetched), %d skipped'
          % (rung, tot['mods'], len(badm), tot['writes'], tot['refetched'],
             tot['skipped']))
    if badm != WP.KNOWN_DECLINE:
        bad.append((rung, 'declines are %s, expected exactly %s'
                    % (sorted(badm), sorted(WP.KNOWN_DECLINE))))
    if tot['mods'] != C['painted_modules']:
        bad.append((rung, '%d painted modules, census says %d' % (tot['mods'], C['painted_modules'])))
    if tot['writes'] != C['writes']:
        bad.append((rung, '%d painted writes, census says %d' % (tot['writes'], C['writes'])))
    if tot['refetched'] != C['refetched']:
        bad.append((rung, '%d refetched sites, census says %d' % (tot['refetched'], C['refetched'])))
    if tot['skipped']:
        bad.append((rung, '%d writes skipped inside PATCHED modules' % tot['skipped']))
    if len(knobs) != 1:
        bad.append((rung, 'modules disagree on knobs/anchors: %d distinct' % len(knobs)))
    else:
        k = json.loads(sorted(knobs)[0])
        if k[3] != [69, 70, 71, 72] or k[4] != [0, 12] or k[5] != [1, 0] or k[6] != 0:
            bad.append((rung, 'anchors moved: matrix=%s cbv=%s depth=%s cam=%s'
                        % (k[3], k[4], k[5], k[6])))

badc, totc, _ = scan(os.path.join(W, 'ctl'), False)
print('  ctl     : %d modules emitted, %d declined, %d writes painted'
      % (totc['mods'], len(badc), totc['writes']))
if totc['mods'] != C['modules'] or badc:
    bad.append(('ctl', 'emitted %d modules and declined %s, want %d / none'
                % (totc['mods'], sorted(badc), C['modules'])))
if totc['writes']:
    bad.append(('ctl', 'the gain-0 control painted %d writes' % totc['writes']))

if bad:
    for m, why in bad[:12]:
        sys.stderr.write('    %s :: %s\n' % (m, why))
    sys.exit(1)
print('  anchors single-valued: matrix cbv[reg0+12][69..72], depth registers[1]+0,'
      ' camera member 0')
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
    for f in "$dest"/*.spv; do spirv-val "$f" >/dev/null || { echo "spirv-val FAILED: $f" >&2; exit 1; }; done
}
echo "--- 5. assemble ---"
for k in world cam frac ctl; do assemble "${OUT[$k]}" "$WORK/$k"; done
NOB="$WORK/rung.nostripe"; assemble "$NOB" "$WORK/nostripe"

for k in world cam frac; do
    d=0; for f in "$SRC"/*.dxil.spv; do cmp -s "$f" "${OUT[$k]}/$(basename "$f")" || d=$((d+1)); done
    echo "  $k: $d of 77 compute modules differ from $BASE"
    [[ "$d" == 75 ]] || { echo "  !! expected exactly 75 (the census)" >&2; exit 1; }
done
d=0; for f in "$SRC"/*.spv; do cmp -s "$f" "${OUT[ctl]}/$(basename "$f")" || d=$((d+1)); done
echo "  ctl: $d of 93 modules differ from $BASE"
[[ "$d" == 0 ]] || { echo "  !! the gain-0 control is NOT byte-identical to the base" >&2; exit 1; }
# the three painted rungs must differ from EACH OTHER, or a rung is a no-op
for pair in "world:cam" "world:frac" "world:$NOB"; do
    a="${pair%%:*}"; b="${pair##*:}"
    [[ "$b" == /* ]] || b="${OUT[$b]}"
    d=0; for f in "${OUT[$a]}"/*.spv; do cmp -s "$f" "$b/$(basename "$f")" || d=$((d+1)); done
    echo "  $a vs $(basename "$b"): $d of 93 differ"
    [[ "$d" -gt 0 ]] || { echo "  !! two rungs are byte-identical" >&2; exit 1; }
done

# --- 6. the verifier, on shipped bytes, proven non-vacuous -----------------
echo "--- 6. verifier (shipped bytes) ---"
python3 "$VERIFY" "${OUT[world]}" --mode hash --space world "${VEXTRA[@]}"
python3 "$VERIFY" "${OUT[cam]}"   --mode hash --space cam   "${VEXTRA[@]}"
python3 "$VERIFY" "${OUT[frac]}"  --mode frac --space world "${VEXTRA[@]}"
reject () {   # $1 = label, rest = verifier args
    local label="$1"; shift
    if python3 "$VERIFY" "$@" >/dev/null 2>&1; then
        echo "  !! the verifier ACCEPTS $label -- it is vacuous" >&2; exit 1; fi
    echo "  rejected: $label"
}
reject "the unpatched base"        "$SRC" --mode hash --space world "${VEXTRA[@]}"
reject "the gain-0 control"        "${OUT[ctl]}" --mode hash --space world "${VEXTRA[@]}"
reject "the no-stripe decoy"       "$NOB" --mode hash --space world "${VEXTRA[@]}"
reject "hunt-wpos read as -cam"    "${OUT[world]}" --mode hash --space cam "${VEXTRA[@]}"
reject "hunt-wpos-cam read as world" "${OUT[cam]}" --mode hash --space world "${VEXTRA[@]}"
reject "hunt-wpos read as frac"    "${OUT[world]}" --mode frac --space world "${VEXTRA[@]}"
reject "a wrong cell size"         "${OUT[world]}" --mode hash --space world --cell 2.0 --up "$UP"
reject "a wrong up axis"           "${OUT[world]}" --mode hash --space world --cell "$CELL" --up 1
reject "a wrong gain"              "${OUT[world]}" --mode hash --space world "${VEXTRA[@]}" --gain 0.5

# --- 7. MANIFESTs ----------------------------------------------------------
manifest () {   # $1 = dest, $2 = rung name, $3 = tail comment
    sed -e "1s/^$BASE /$2 /" -e "1s/compute=77([^)]*)/compute=77($BASE-$2)/" \
        "$SRC/MANIFEST.txt" > "$1/MANIFEST.txt"
    grep -q "^$2 " "$1/MANIFEST.txt" || { echo "MANIFEST rewrite failed" >&2; exit 1; }
    echo "# $3" >> "$1/MANIFEST.txt"
}
manifest "${OUT[world]}" "$NAME" "hunt-wpos probe: 1 m hash cells on the resolvers' own P (cell=$CELL, up=$UP) + 94's class palette, at all 150 radiance writes of 75 compute modules; raygens are $BASE bytes. See handoff/99."
manifest "${OUT[cam]}" "$NAME-cam" "hunt-wpos CAMERA-RELATIVE control: the same pattern on P - cbv[..][0]. Must slide with the camera. See handoff/99 sec 5."
manifest "${OUT[frac]}" "$NAME-frac" "hunt-wpos FRACTIONAL: RGB = frac(P/$CELL). Reads the up axis and the units off one frame. See handoff/99 sec 5."
manifest "${OUT[ctl]}" "$NAME-ctl" "hunt-wpos CONTROL (gain 0): 93 of 93 modules byte-identical to $BASE. Selecting it must be indistinguishable from the base."

echo
for k in world cam frac ctl; do echo "  built ${OUT[$k]} (93 modules)"; done
if (( DO_INSTALL )); then
    for pair in "world:$NAME" "cam:$NAME-cam" "frac:$NAME-frac" "ctl:$NAME-ctl"; do
        s="${OUT[${pair%%:*}]}"; n="${pair##*:}"
        park="$INSTALL_DIR/skin.set/$n"
        mkdir -p "$park"; rm -f "$park"/*.spv "$park/MANIFEST.txt"
        cp -pf "$s"/*.spv "$s/MANIFEST.txt" "$park/"
        echo "  parked -> $park"
    done
else
    echo "NOT installed. To park: ./dev/build_wpos.sh --install"
fi
echo "select with skinspec=$NAME | $NAME-cam | $NAME-frac | $NAME-ctl;"
echo "needs ser=class + shadowset=full-shadow ($BASE's contract)"
