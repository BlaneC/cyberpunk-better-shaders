#!/usr/bin/env bash
# oilhi: 72's skin coat retuned now that 117's `cons` takes the energy out.
# handoff/118.  Compute-only, sun-frame, one A/B ladder.
#
#   ./dev/build_oil.sh                 # build + verify (no install)
#   ./dev/build_oil.sh --install       # ALSO park the rungs in skin.set/
#
# The coat is 72's Schlick reshape, already spliced into all 77 resolvers, and
# its strength is two baked constants.  This build moves them and NOTHING else:
# no instruction is added, removed or changed in kind, which gate 7 proves from
# the shipped bytes by comparing opcode multisets against the base.
#
#   oil-ctl     p=4.5  g=1.00   the shipped coat -- must be BYTE-IDENTICAL
#   oilhi       p=4.0  g=1.00   the ladder's own next step (n_s 0.55 -> 0.60)
#   oilhi-g     p=4.5  g=1.25   the other lever, on its own, for attribution
#   oilhi2      p=4.0  g=1.25   both -- the louder candidate, not a diagnostic
#   oil-inert   p=4.5  g=1.00   DECOY: 2-r moved 1.1 -> 1.9.  NClamp(.,0,1)
#               c=1.9           pins it at 1 for every oil rung, so the bytes
#                               MUST differ and the screen MUST NOT.  If this
#                               one is visible, dev/oil_model.py is wrong.
set -euo pipefail

MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="${CALLISTO_INSTALL_DIR:-$HOME/.local/lib/callisto}"
PY="$MOD_DIR/dev/patch_oil.py"
VERIFY="$MOD_DIR/dev/verify_oil.py"
MODEL="$MOD_DIR/dev/oil_model.py"

BASE=micro                 # the shipped default: the ctl must equal it
DO_INSTALL=0
while (( $# )); do
    case "$1" in
        --install) DO_INSTALL=1 ;;
        --base)    BASE="${2:?}"; shift ;;
        *) echo "unknown arg $1" >&2; exit 1 ;;
    esac
    shift
done

SRC="$INSTALL_DIR/skin.set/$BASE"
WORK="$MOD_DIR/dev/disasm/oilhi"
RUNGS=(ctl hi hig hi2 inert)
declare -A NAME=( [ctl]="oil-ctl" [hi]="oilhi" [hig]="oilhi-g"
                  [hi2]="oilhi2"  [inert]="oil-inert" )
declare -A ARGS=( [ctl]="-p 4.5 -g 1.0"   [hi]="-p 4.0 -g 1.0"
                  [hig]="-p 4.5 -g 1.25"  [hi2]="-p 4.0 -g 1.25"
                  [inert]="-p 4.5 -g 1.0 --c2mr 1.9" )
declare -A VARG=( [ctl]="-p 4.5 -g 1.0"   [hi]="-p 4.0 -g 1.0"
                  [hig]="-p 4.5 -g 1.25"  [hi2]="-p 4.0 -g 1.25"
                  [inert]="-p 4.5 -g 1.0 --c2mr 1.9" )
declare -A NDIFF=( [ctl]=0 [hi]=77 [hig]=77 [hi2]=77 [inert]=77 )
declare -A OUT
for k in "${RUNGS[@]}"; do OUT[$k]="$MOD_DIR/swaps.${NAME[$k]}"; done

# --- 0. base provenance ----------------------------------------------------
echo "--- 0. base provenance ($BASE) ---"
[[ -f "$SRC/MANIFEST.txt" ]] || { echo "no $SRC/MANIFEST.txt" >&2; exit 1; }
grep -q 'src_ser=' "$SRC/MANIFEST.txt" || { echo "$BASE carries no src_ser= provenance" >&2; exit 1; }
n_c=$(ls "$SRC"/*.dxil.spv | wc -l); n_r=$(ls "$SRC"/*.rgs_*.spv | wc -l)
[[ "$n_c" == 77 && "$n_r" == 16 ]] || { echo "$BASE is $n_c compute + $n_r raygen, expected 77 + 16" >&2; exit 1; }
echo "  77 compute + 16 raygen"

# --- 1. the offline model gates itself -------------------------------------
echo "--- 1. offline model (dev/oil_model.py) ---"
python3 "$MODEL" | tail -1

# --- 2. disassemble --------------------------------------------------------
echo "--- 2. disassemble ---"
rm -rf "$WORK"; mkdir -p "$WORK/asm" "$WORK/rt"
for k in "${RUNGS[@]}"; do mkdir -p "$WORK/$k"; done
jobs="${CALLISTO_JOBS:-$(nproc 2>/dev/null || echo 4)}"
ls "$SRC"/*.dxil.spv | xargs -P "$jobs" -I{} bash -c \
    'n=$(basename "$1" .dxil.spv); spirv-dis "$1" -o "'"$WORK"'/asm/$n.spvasm"' _ {}
[[ "$(ls "$WORK/asm" | wc -l)" == 77 ]] || { echo "disassembly lost modules" >&2; exit 1; }

# --- 3. the pipeline is byte-neutral ---------------------------------------
echo "--- 3. round-trip neutrality (dis -> as == base bytes) ---"
same=0
for a in "$WORK"/asm/*.spvasm; do
    n="$(basename "${a%.spvasm}")"
    ver=$(sed -n 's/^; Version: \([0-9]*\)\.\([0-9]*\).*/spv\1.\2/p' "$a" | head -1)
    [[ -n "$ver" ]] || { echo "  !! $n has no '; Version:' header" >&2; exit 1; }
    spirv-as --target-env "$ver" "$a" -o "$WORK/rt/$n.spv"
    cmp -s "$SRC/$n.dxil.spv" "$WORK/rt/$n.spv" || { echo "  !! $n does not round-trip" >&2; exit 1; }
    same=$((same+1))
done
echo "  $same of 77 round-trip byte-identically"
rm -rf "$WORK/rt"

# --- 4. patch --------------------------------------------------------------
echo "--- 4. patch ---"
for k in "${RUNGS[@]}"; do
    printf '%s\n' ${ARGS[$k]} --outdir "$WORK/$k" > "$WORK/.args"
    find "$WORK/asm" -name '*.spvasm' -print0 | \
        CB_ARGS="$WORK/.args" CB_PY="$PY" CB_OUT="$WORK/$k" \
        xargs -0 -P "$jobs" -n1 bash -c '
            asm="$1"; n="$(basename "${asm%.spvasm}")"
            mapfile -t A < "$CB_ARGS"
            python3 "$CB_PY" "$asm" "${A[@]}" --no-roundtrip-check \
                > "$CB_OUT/.$n.json" 2>"$CB_OUT/.$n.err" \
                || { echo "PATCH FAILED $n"; cat "$CB_OUT/.$n.err"; exit 1; }' _ \
        || { echo "  !! ${NAME[$k]} failed to patch" >&2; exit 1; }
    echo "  ${NAME[$k]}: $(ls "$WORK/$k"/*.dxil.spv | wc -l) modules"
done
rm -f "$WORK/.args"

# --- 5. coverage, from the patcher's own reports ---------------------------
echo "--- 5. coverage (from the patcher's own reports) ---"
python3 - "$WORK" <<'PY' || exit 1
import glob, json, os, sys
W = sys.argv[1]
RUNGS = ['ctl', 'hi', 'hig', 'hi2', 'inert']
WRITE = dict(ctl=(0, 0, 0), hi=(1, 0, 0), hig=(0, 1, 0),
             hi2=(1, 1, 0), inert=(0, 0, 1))
base, bad = None, []
for k in RUNGS:
    tot = [0, 0, 0]; g = c = n = 0; per = {}
    for f in sorted(glob.glob(os.path.join(W, k, '.*.json'))):
        for r in json.load(open(f)):
            o = r['oil']; n += 1
            g += o['groups']; c += o['chans']
            per[r['module']] = o['groups']
            tot[0] += o['p_written']; tot[1] += o['g_written']
            tot[2] += o['c_written']
            if o['groups'] == 0:
                bad.append((k, '%s: no coat' % r['module']))
            if o['chans'] != 3 * o['groups']:
                bad.append((k, '%s: %d chans for %d groups'
                            % (r['module'], o['chans'], o['groups'])))
    if base is None:
        base = per
    elif per != base:
        bad.append((k, 'census differs from the first rung'))
    want = [g * w for w in WRITE[k]]
    if tot != want:
        bad.append((k, 'wrote p/g/c %r, expected %r' % (tot, want)))
    print('  %-9s modules=%d groups=%d channels=%d writes(p,g,c)=%r'
          % (k, n, g, c, tuple(tot)))
print('  census identical in every rung: %d modules, %d groups'
      % (len(base), sum(base.values())))
if bad:
    for b in bad[:20]:
        print('  !! %s: %s' % b)
    sys.exit(1)
PY

# --- 6. assemble -----------------------------------------------------------
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
        cmp -s "$f" "$dest/$(basename "$f")" || { echo "raygen $(basename "$f") differs -- not compute-only" >&2; exit 1; }
    done
    for f in "$dest"/*.spv; do
        spirv-val --target-env vulkan1.4 "$f" >/dev/null || { echo "spirv-val FAILED: $f" >&2; exit 1; }
    done
}
echo "--- 6. assemble (16/16 raygen cmp-identical, spirv-val vulkan1.4) ---"
for k in "${RUNGS[@]}"; do assemble "${OUT[$k]}" "$WORK/$k"; done
echo "  93 modules per rung, raygens untouched"

echo "--- 6b. the control IS the shipped default, and the ladder is separated ---"
d=0; for f in "$SRC"/*.spv; do cmp -s "$f" "${OUT[ctl]}/$(basename "$f")" || { d=$((d+1)); echo "  !! $(basename "$f")"; }; done
[[ "$d" == 0 ]] || { echo "  !! oil-ctl differs from the default '$BASE' in $d module(s)" >&2; exit 1; }
echo "  oil-ctl == skin.set/$BASE in all 93 modules"
for k in "${RUNGS[@]}"; do
    d=0; for f in "$SRC"/*.dxil.spv; do cmp -s "$f" "${OUT[$k]}/$(basename "$f")" || d=$((d+1)); done
    echo "  ${NAME[$k]}: $d of 77 compute modules differ from the default"
    [[ "$d" == "${NDIFF[$k]}" ]] || { echo "  !! expected ${NDIFF[$k]}" >&2; exit 1; }
done
for i in "${!RUNGS[@]}"; do for j in "${!RUNGS[@]}"; do
    (( j <= i )) && continue
    a="${RUNGS[$i]}"; b="${RUNGS[$j]}"
    d=0; for f in "${OUT[$a]}"/*.spv; do cmp -s "$f" "${OUT[$b]}/$(basename "$f")" || d=$((d+1)); done
    [[ "$d" -gt 0 ]] || { echo "  !! ${NAME[$a]} and ${NAME[$b]} are byte-identical" >&2; exit 1; }
done; done
echo "  all 10 rung pairs differ"

# --- 7. the verifier, on shipped bytes, proven non-vacuous -----------------
echo "--- 7. verifier (shipped bytes) ---"
for k in "${RUNGS[@]}"; do
    echo "  ${NAME[$k]}:"
    python3 "$VERIFY" "${OUT[$k]}" --base "$SRC" ${VARG[$k]} \
        --expect-differing "${NDIFF[$k]}" | sed 's/^/  /'
done
reject () {   # $1 = label, rest = verifier args
    local label="$1"; shift
    if python3 "$VERIFY" "$@" >/dev/null 2>&1; then
        echo "  !! the verifier ACCEPTS $label -- it is vacuous" >&2; exit 1; fi
    echo "  rejected: $label"
}
reject "the shipped default read as oilhi"   "$SRC"          --base "$SRC" -p 4.0 -g 1.0
reject "oilhi read as the shipped coat"      "${OUT[hi]}"    --base "$SRC" -p 4.5 -g 1.0
reject "oilhi read as oilhi-g"               "${OUT[hi]}"    --base "$SRC" -p 4.5 -g 1.25
reject "oilhi-g read as oilhi"               "${OUT[hig]}"   --base "$SRC" -p 4.0 -g 1.0
reject "oilhi2 read as either half"          "${OUT[hi2]}"   --base "$SRC" -p 4.0 -g 1.0
reject "the inert decoy read as the default" "${OUT[inert]}" --base "$SRC" -p 4.5 -g 1.0
reject "oil-ctl read as differing"           "${OUT[ctl]}"   --base "$SRC" -p 4.5 -g 1.0 --expect-differing 77
reject "oilhi read as unchanged bytes"       "${OUT[hi]}"    --base "$SRC" -p 4.0 -g 1.0 --expect-differing 0

# --- 8. install ------------------------------------------------------------
if (( DO_INSTALL )); then
    echo "--- 8. install ---"
    for k in "${RUNGS[@]}"; do
        cp -pf "$SRC/MANIFEST.txt" "${OUT[$k]}/MANIFEST.txt"
        {   echo "rung=${NAME[$k]}"
            echo "base=$BASE (the shipped default)"
            echo "coat=${ARGS[$k]}   (shipped: p=4.5 g=1.0 c=1.1)"
            echo "handoff=118"
        } >> "${OUT[$k]}/MANIFEST.txt"
        dst="$INSTALL_DIR/skin.set/${NAME[$k]}"
        rm -rf "$dst"; mkdir -p "$dst"
        cp -pf "${OUT[$k]}"/*.spv "${OUT[$k]}/MANIFEST.txt" "$dst/"
        echo "  parked $dst"
    done
    for k in hi hig hi2; do
        echo "  content sha $(cat "${OUT[$k]}"/*.spv | sha256sum | cut -c1-16)  (${NAME[$k]})"
    done
fi
echo "--- oilhi: all gates passed ---"
