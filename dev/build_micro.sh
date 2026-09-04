#!/usr/bin/env bash
# micro: the other four-fifths of the pore, plus the layer 72 forgot.
# handoff/117.  Compute-only, sun-frame, one A/B.
#
#   ./dev/build_micro.sh                 # build + verify (no install)
#   ./dev/build_micro.sh --install       # ALSO park the rungs in skin.set/
#
# Five halves, all riding 115's albedo height field, all in the 77 resolvers:
#   occ    diffuse *= 1 - KOCC*cav       a pit is shadowed by its own rim
#   rough  alpha   *= 1 + KRGH*cav       pores scatter the oil highlight
#   term   diffuse *= 1 + w - w^2        Chiang 2019; the fix for 115's own
#                                        shading-normal terminator
#   gtso   spec    *= SO(NoV, ao, a^2)   Jimenez 2016; 38 A5 without the bent
#                                        normal it was parked waiting for
#   cons   diffuse *= 1 - F              72's oil layer is a pure ADD
#
# Rungs: micro (all five), one per half so a verdict can be attributed, and
# micro-ctl (none) -- which gate 5 proves is `cmp`-IDENTICAL to the shipped
# default `bump`, module for module.  That is the control: every differing
# byte in every other rung is one of the five halves and nothing else.
set -euo pipefail

MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="${CALLISTO_INSTALL_DIR:-$HOME/.local/lib/callisto}"
PY="$MOD_DIR/dev/patch_micro.py"
VERIFY="$MOD_DIR/dev/verify_micro.py"
MODEL="$MOD_DIR/dev/micro_model.py"

BASE=gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog-earglow-cap6-glintdense-curv-t7hue1-ll
DEFAULT=bump          # the shipped default: BASE + 115.  The ctl must equal it.
DO_INSTALL=0
CREF=0.02
C0=0.05
C1=0.12
KOCC=0.35
KRGH=0.50
while (( $# )); do
    case "$1" in
        --install) DO_INSTALL=1 ;;
        --base)    BASE="${2:?}"; shift ;;
        --cref)    CREF="${2:?}"; shift ;;
        --kocc)    KOCC="${2:?}"; shift ;;
        --krgh)    KRGH="${2:?}"; shift ;;
        *) echo "unknown arg $1" >&2; exit 1 ;;
    esac
    shift
done
KN=(--cref "$CREF" --c0 "$C0" --c1 "$C1" --kocc "$KOCC" --krgh "$KRGH")
VKN=(--cref "$CREF" --kocc "$KOCC" --krgh "$KRGH")

SRC="$INSTALL_DIR/skin.set/$BASE"
DEF="$INSTALL_DIR/skin.set/$DEFAULT"
WORK="$MOD_DIR/dev/disasm/micro"
RUNGS=(all occ rgh trm gts cns ctl)
declare -A ONLY=( [all]="occ,rough,term,gtso,cons" [occ]="occ" [rgh]="rough"
                  [trm]="term" [gts]="gtso" [cns]="cons" [ctl]="" )
declare -A NAME=( [all]="micro" [occ]="micro-occ" [rgh]="micro-rgh"
                  [trm]="micro-trm" [gts]="micro-gts" [cns]="micro-cns"
                  [ctl]="micro-ctl" )
declare -A OUT
for k in "${RUNGS[@]}"; do OUT[$k]="$MOD_DIR/swaps.${NAME[$k]}"; done

# --- 0. base provenance ----------------------------------------------------
echo "--- 0. base provenance ($BASE) ---"
[[ -f "$SRC/MANIFEST.txt" ]] || { echo "no $SRC/MANIFEST.txt" >&2; exit 1; }
[[ -d "$DEF" ]] || { echo "the shipped default $DEFAULT is not parked" >&2; exit 1; }
grep -q 'src_ser=' "$SRC/MANIFEST.txt" || { echo "$BASE carries no src_ser= provenance" >&2; exit 1; }
n_c=$(ls "$SRC"/*.dxil.spv | wc -l); n_r=$(ls "$SRC"/*.rgs_*.spv | wc -l)
[[ "$n_c" == 77 && "$n_r" == 16 ]] || { echo "$BASE is $n_c compute + $n_r raygen, expected 77 + 16" >&2; exit 1; }
echo "  77 compute + 16 raygen; default '$DEFAULT' present"

# --- 1. the offline model gates itself -------------------------------------
echo "--- 1. offline model (dev/micro_model.py) ---"
python3 "$MODEL" | tail -2

# --- 2. disassemble --------------------------------------------------------
rm -rf "$WORK"; mkdir -p "$WORK/asm" "$WORK/rt"
for k in "${RUNGS[@]}" noband noguard; do mkdir -p "$WORK/$k"; done
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
patch_all () {   # $1 = outdir, rest = extra args
    local out="$1"; shift
    printf '%s\n' "$@" --outdir "$out" > "$WORK/.args"
    find "$WORK/asm" -name '*.spvasm' -print0 | \
        CB_ARGS="$WORK/.args" CB_PY="$PY" CB_OUT="$out" \
        xargs -0 -P "$jobs" -n1 bash -c '
            asm="$1"; n="$(basename "${asm%.spvasm}")"
            mapfile -t A < "$CB_ARGS"
            if python3 "$CB_PY" "$asm" "${A[@]}" > "$CB_OUT/.$n.json" 2>"$CB_OUT/.$n.err"; then
                : > "$CB_OUT/.ok.$n"; else : > "$CB_OUT/.bad.$n"; fi' _
    rm -f "$WORK/.args"
}
echo "--- 4. patch ---"
for k in "${RUNGS[@]}"; do
    if [[ -z "${ONLY[$k]}" ]]; then
        patch_all "$WORK/$k" "${KN[@]}" --no-occ --no-rough --no-term --no-gtso --no-cons
    else
        patch_all "$WORK/$k" "${KN[@]}" --only "${ONLY[$k]}"
    fi
done
patch_all "$WORK/noband"  "${KN[@]}" --only "occ,rough,term,gtso,cons" --no-band
patch_all "$WORK/noguard" "${KN[@]}" --only "occ,rough,term,gtso,cons" --no-guard

# --- 5. coverage, from the reports -----------------------------------------
echo "--- 5. coverage (from the patcher's own reports) ---"
python3 - "$MOD_DIR" "$WORK" <<'PY' || exit 1
import glob, json, os, sys, collections
sys.path.insert(0, os.path.join(sys.argv[1], 'dev'))
import patch_bump as PB
W = sys.argv[2]
HALVES = ('occ', 'rough', 'term', 'gtso', 'cons')
ONLY = dict(all=set(HALVES), occ={'occ'}, rgh={'rough'}, trm={'term'},
            gts={'gtso'}, cns={'cons'}, ctl=set())
bad, base_census = [], None
for rung in ('all', 'occ', 'rgh', 'trm', 'gts', 'cns', 'ctl'):
    d = os.path.join(W, rung)
    badm = {os.path.basename(f)[5:] for f in glob.glob(os.path.join(d, '.bad.*'))}
    if badm != PB.KNOWN_DECLINE:
        bad.append((rung, 'declines %s, expected %s' % (sorted(badm), sorted(PB.KNOWN_DECLINE))))
    tot, cen, n = collections.Counter(), collections.Counter(), 0
    for f in sorted(glob.glob(os.path.join(d, '.*.json'))):
        if os.path.basename(f).startswith(('.ok.', '.bad.')) or os.path.getsize(f) == 0:
            continue
        r = json.load(open(f))[0]
        if r.get('spirv_val') != 'clean':
            bad.append((r.get('module'), 'spirv-val not clean'))
        m = r['micro']; n += 1
        for k, v in m['applied'].items():
            tot[k] += v
        for k, v in m['census'].items():
            cen[k] += v
        for h in HALVES:
            if h not in ONLY[rung] and m['applied'][h]:
                bad.append((r['dxil'], '%s applied %d in rung %s' % (h, m['applied'][h], rung)))
        if rung == 'all':
            for k in ('alpha', 'diffuse', 'spec'):
                if not m['census'][k]:
                    bad.append((r['dxil'], 'no %s site found' % k))
    if n != 75:
        bad.append((rung, 'patched %d modules, expected 75' % n))
    if base_census is None:
        base_census = dict(cen)
    elif dict(cen) != base_census:
        bad.append((rung, 'census moved between rungs: %s vs %s' % (dict(cen), base_census)))
    # every half must be applied at EVERY site of its own family
    want = dict(rough=cen['alpha'], occ=cen['diffuse'], gtso=cen['spec'],
                cons=3 * cen['diffuse'])
    for h, w in want.items():
        if h in ONLY[rung] and tot[h] != w:
            bad.append((rung, '%s applied at %d of %d sites' % (h, tot[h], w)))
    if 'term' in ONLY[rung] and not tot['term']:
        bad.append((rung, 'term applied nowhere'))
    print('  %-4s modules=%d %s' % (rung, n, dict(tot)))
print('  census (identical in every rung): %s' % base_census)
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
NOB="$WORK/rung.noband"; assemble "$NOB" "$WORK/noband"
NOG="$WORK/rung.noguard"; assemble "$NOG" "$WORK/noguard"

echo "--- 6b. the control IS the shipped default, byte for byte ---"
d=0; for f in "$DEF"/*.spv; do cmp -s "$f" "${OUT[ctl]}/$(basename "$f")" || { d=$((d+1)); echo "  !! $(basename "$f")"; }; done
[[ "$d" == 0 ]] || { echo "  !! micro-ctl differs from the shipped default '$DEFAULT' in $d module(s)" >&2; exit 1; }
echo "  micro-ctl == skin.set/$DEFAULT in all 93 modules"

for k in all occ rgh trm gts cns; do
    d=0; for f in "$DEF"/*.dxil.spv; do cmp -s "$f" "${OUT[$k]}/$(basename "$f")" || d=$((d+1)); done
    echo "  ${NAME[$k]}: $d of 77 compute modules differ from the default"
    [[ "$d" == 75 ]] || { echo "  !! expected exactly 75 (the census)" >&2; exit 1; }
done
for i in "${!RUNGS[@]}"; do for j in "${!RUNGS[@]}"; do
    (( j <= i )) && continue
    a="${RUNGS[$i]}"; b="${RUNGS[$j]}"
    d=0; for f in "${OUT[$a]}"/*.spv; do cmp -s "$f" "${OUT[$b]}/$(basename "$f")" || d=$((d+1)); done
    [[ "$d" -gt 0 ]] || { echo "  !! ${NAME[$a]} and ${NAME[$b]} are byte-identical" >&2; exit 1; }
done; done
echo "  all 21 rung pairs differ"

# --- 7. the verifier, on shipped bytes, proven non-vacuous -----------------
echo "--- 7. verifier (shipped bytes) ---"
for k in all occ rgh trm gts cns; do
    echo "  ${NAME[$k]}:"
    python3 "$VERIFY" "${OUT[$k]}" "${VKN[@]}" --halves "${ONLY[$k]}" | tr -d '\n ' | sed 's/^/    /'
    echo
done
reject () {   # $1 = label, rest = verifier args
    local label="$1"; shift
    if python3 "$VERIFY" "$@" >/dev/null 2>&1; then
        echo "  !! the verifier ACCEPTS $label -- it is vacuous" >&2; exit 1; fi
    echo "  rejected: $label"
}
reject "the unpatched base"              "$SRC"          "${VKN[@]}"
reject "the shipped default (115 alone)" "$DEF"          "${VKN[@]}"
reject "the all-off control"             "${OUT[ctl]}"   "${VKN[@]}"
reject "the NO-EDGE-BAND decoy"          "$NOB"          "${VKN[@]}"
reject "the NO-SILHOUETTE-GUARD decoy"   "$NOG"          "${VKN[@]}"
reject "micro read as unbanded"          "${OUT[all]}"   "${VKN[@]}" --no-guard
reject "a wrong cavity reference"        "${OUT[all]}"   --cref 0.05 --kocc "$KOCC" --krgh "$KRGH"
reject "a wrong occlusion strength"      "${OUT[all]}"   --cref "$CREF" --kocc 0.6 --krgh "$KRGH"
reject "a wrong roughness strength"      "${OUT[all]}"   --cref "$CREF" --kocc "$KOCC" --krgh 0.9
for k in occ rgh trm gts cns; do
    reject "micro read as ${NAME[$k]}"   "${OUT[all]}"   "${VKN[@]}" --halves "${ONLY[$k]}"
    reject "${NAME[$k]} read as micro"   "${OUT[$k]}"    "${VKN[@]}"
done

# --- 8. install ------------------------------------------------------------
if (( DO_INSTALL )); then
    echo "--- 8. install ---"
    for k in "${RUNGS[@]}"; do
        # the MANIFEST is written into the BUILD dir first: park_alias.sh and
        # sync_settings.sh both read a rung out of swaps.*, and a raygen-bearing
        # rung without one is refused at launch as gi-no-manifest (111 sec 0.1).
        cp -pf "$SRC/MANIFEST.txt" "${OUT[$k]}/MANIFEST.txt"
        {   echo "rung=${NAME[$k]}"
            echo "base=$BASE"
            echo "control=$DEFAULT"
            echo "halves=${ONLY[$k]:-none}"
            echo "cref=$CREF c0=$C0 c1=$C1 kocc=$KOCC krgh=$KRGH"
            echo "handoff=117"
        } >> "${OUT[$k]}/MANIFEST.txt"
        dst="$INSTALL_DIR/skin.set/${NAME[$k]}"
        rm -rf "$dst"; mkdir -p "$dst"
        cp -pf "${OUT[$k]}"/*.spv "${OUT[$k]}/MANIFEST.txt" "$dst/"
        echo "  parked $dst"
    done
    echo "  content sha $(cat "${OUT[all]}"/*.spv | sha256sum | cut -c1-16)  (micro)"
fi
echo "--- micro: all gates passed ---"
