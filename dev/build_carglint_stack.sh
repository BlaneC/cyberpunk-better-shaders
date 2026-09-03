#!/usr/bin/env bash
# Build the STACKED rung:
#   gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog-earglow-glintdense
#
# = `101`'s ear glow (earglow-rq3, three ray queries in 10 of 12
#   rgs_reference_main permutations) WITH `100` sec 6's carglint at the -dense
#   knobs (nu0 = 6e5) spliced on top of the SAME ten modules.
#
# ORDER: rq3 FIRST, glints SECOND. Three reasons, none of them convenience:
#   1. the earglow bytes are what is becoming the standing default and are
#      already shot and gated by their own author. Patching ON TOP of them
#      means the input to this script is those exact bytes, so `--k-glint 0`
#      must reproduce them at 93/93 cmp (gate 4) and anything that differs is
#      provably mine.
#   2. carglint's anchors are all found STRUCTURALLY by scanning the module
#      (the Schlick SG constant for the lobes, the D chain for H, the payload
#      loads, the trace-origin cbv for member 56). The rq3 splice ADDS
#      instructions and rewrites its own transfer; it does not move the GGX
#      blocks, the position triple or the payload. So the finders still
#      resolve -- and gate 3 PROVES it by requiring the census to equal the
#      old base's number for number.
#   3. the converse order would mean re-running `101`'s patcher over
#      glint-patched bytes. That patcher and its gates are not mine to
#      re-prove, and its author owns the default. Not my edit to make.
#
# The rq3 splice must survive this untouched -- gate 6 runs `101`'s own
# verifier on the stacked output, and gate 6b proves that check is not vacuous.
#
#   ./dev/build_carglint_stack.sh [--install]
set -euo pipefail

MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="${CALLISTO_INSTALL_DIR:-$HOME/.local/lib/callisto}"
PY="$MOD_DIR/dev/patch_carglint.py"
VERIFY="$MOD_DIR/dev/verify_carglint.py"
EGVERIFY="$MOD_DIR/dev/verify_earglow_rq3.py"
WORK="$MOD_DIR/dev/disasm/carglint-stack"

OLDBASE=gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog
EGBASE=earglow-rq3                     # the parked bytes this stacks onto
EGLIN=gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog-earglow
RUNG=gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog-earglow-glintdense
NULLRUNG=carglint-stack-null           # gate 4 only, never installed
KNOBS=(--nu0 600000)
DO_INSTALL=0
while (( $# )); do
    case "$1" in
        --install) DO_INSTALL=1 ;;
        -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
        *) echo "unknown arg $1" >&2; exit 1 ;;
    esac
    shift
done

SRC="$INSTALL_DIR/skin.set/$EGBASE"
OLD="$INSTALL_DIR/skin.set/$OLDBASE"
PASS=(40c6faab52a13874 ab7f1822eeb0331b)
[[ -f "$SRC/MANIFEST.txt" ]] || { echo "no $SRC -- earglow-rq3 is not parked" >&2; exit 1; }
[[ -d "$OLD" ]] || { echo "no $OLD" >&2; exit 1; }

echo "=== 0. base: $EGBASE  ($(cat "$SRC"/*.spv | sha256sum | cut -c1-16))"
for want in "$(ls "$SRC"/*.dxil.spv | wc -l):77" \
            "$(ls "$SRC"/*.rgs_restirgi_*.spv | wc -l):4" \
            "$(ls "$SRC"/*.rgs_reference_main.spv | wc -l):12"; do
    [[ "${want%:*}" == "${want#*:}" ]] || { echo "  !! base census $want" >&2; exit 1; }
done
echo "  77 compute + 4 restirgi + 12 reference = 93"

# --- 0b. the -earglow LINEAGE dir, if the other agent has produced it ------
# The rung name the default will carry is the lineage one; the bytes are meant
# to be earglow-rq3's. Asserted, not assumed.
if [[ -d "$INSTALL_DIR/skin.set/$EGLIN" ]]; then
    d=0; for f in "$SRC"/*.spv; do
        cmp -s "$f" "$INSTALL_DIR/skin.set/$EGLIN/$(basename "$f")" || d=$((d+1)); done
    [[ "$d" == 0 ]] || { echo "  !! $EGLIN differs from $EGBASE on $d of 93 files" >&2; exit 1; }
    echo "  0b. $EGLIN is 93 of 93 cmp-identical to $EGBASE ($(cat "$INSTALL_DIR/skin.set/$EGLIN"/*.spv | sha256sum | cut -c1-16))"
else
    echo "  0b. $EGLIN not parked yet -- stacking on $EGBASE, whose bytes it is to carry"
fi

mapfile -t REFS < <(cd "$SRC" && ls *.rgs_reference_main.spv | sed 's/\..*//')
TARGETS=()
for h in "${REFS[@]}"; do
    skip=0; for p in "${PASS[@]}"; do [[ "$h" == "$p" ]] && skip=1; done
    (( skip )) && continue
    TARGETS+=("$h")
done
(( ${#TARGETS[@]} == 10 )) || { echo "expected 10 paintable refs" >&2; exit 1; }

rm -rf "$WORK"; mkdir -p "$WORK/asm" "$WORK/rt"
for h in "${TARGETS[@]}"; do spirv-dis "$SRC/$h.rgs_reference_main.spv" -o "$WORK/asm/$h.spvasm"; done

echo "=== 1. round-trip neutrality on the EARGLOW bytes"
for h in "${TARGETS[@]}"; do
    spirv-as --target-env spv1.4 "$WORK/asm/$h.spvasm" -o "$WORK/rt/$h.spv"
    cmp -s "$SRC/$h.rgs_reference_main.spv" "$WORK/rt/$h.spv" \
        || { echo "  !! $h does not round-trip -- no null built on it is meaningful" >&2; exit 1; }
done
echo "  10 of 10 round-trip byte-identically (so gate 4's null is real)"
rm -rf "$WORK/rt"

echo "=== 1b. named declines, on the earglow bytes"
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
    mkdir -p "$out"; : > "$WORK/.args"
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
        cmp -s "$f" "$dest/$(basename "$f")" || { echo "  !! verbatim copy differs: $(basename "$f")" >&2; exit 1; }
    done
    for p in "${PASS[@]}"; do
        cmp -s "$SRC/$p.rgs_reference_main.spv" "$dest/$p.rgs_reference_main.spv" \
            || { echo "  !! pass-through $p differs" >&2; exit 1; }
    done
    local d=0
    for h in "${TARGETS[@]}"; do
        cmp -s "$SRC/$h.rgs_reference_main.spv" "$dest/$h.rgs_reference_main.spv" || d=$((d+1))
    done
    if (( must_differ )); then
        [[ "$d" == 10 ]] || { echo "  !! only $d of 10 differ -- the splice emitted nothing" >&2; exit 1; }
    else
        [[ "$d" == 0 ]] || { echo "  !! $d of 10 null modules differ -- k_glint=0 is not a null" >&2; exit 1; }
    fi
    local n; n=$(ls "$dest"/*.spv | wc -l)
    [[ "$n" == 93 ]] || { echo "  !! $dest has $n modules, expected 93" >&2; exit 1; }
    for f in "$dest"/*.spv; do
        spirv-val --target-env vulkan1.4 "$f" >/dev/null \
            || { echo "  !! spirv-val vulkan1.4 FAILED: $f" >&2; exit 1; }
    done
}

echo "=== 2. patch + assemble"
patch_set "$WORK/p.rung" "${KNOBS[@]}"
assemble  "$MOD_DIR/swaps.$RUNG" "$WORK/p.rung" 1
echo "  swaps.$RUNG: 93 modules, spirv-val (vulkan1.4) clean  [${KNOBS[*]}]"
patch_set "$WORK/p.null" --k-glint 0
assemble  "$WORK/rung.null" "$WORK/p.null" 0
echo "  the k_glint=0 null assembles too"

# --- 3. the census must EQUAL the old base's, number for number -----------
# This is the claim that matters: the anchors are structural, so the rq3
# splice sitting in the same modules must not cost a single site.
echo "=== 3. coverage census -- must equal swaps.carglint-dense's on the OLD base"
python3 - "$MOD_DIR/swaps.$RUNG" "$MOD_DIR/swaps.carglint-dense" <<'PY' || exit 1
import glob, json, os, sys
def census(d):
    mods = blocks = sites = emitted = 0
    members, f0, uses = set(), set(), set()
    for f in sorted(glob.glob(os.path.join(d, '*.carglint.report.json'))):
        rep = json.load(open(f))[0]; c = rep['carglint']
        assert rep.get('spirv_val') == 'clean', (d, rep['module'])
        mods += 1; blocks += c['ggx_blocks']; sites += len(c['per_arm'])
        emitted += c['emitted']; members.add(c['world_offset']['member'])
        f0.add(c['f0_metallic_agrees']); uses.add(c['uses_rewritten'])
    return dict(modules=mods, ggx_blocks=blocks, glint_sites=sites,
                instructions=emitted, members=sorted(members),
                f0_agree=sorted(f0), uses=sorted(uses))
a, b = census(sys.argv[1]), census(sys.argv[2]) if os.path.isdir(sys.argv[2]) else None
want = dict(modules=10, ggx_blocks=60, glint_sites=60, instructions=3170,
            members=[56], f0_agree=[18], uses=[18])
bad = [k for k, v in want.items() if a[k] != v]
if bad:
    sys.stderr.write('    stacked census wrong on %s: %s vs %s\n' % (bad, a, want)); sys.exit(1)
print('  stacked  %(modules)d modules, %(ggx_blocks)d GGX blocks, member 56 x10, '
      'F0 metallic 18/18 x10, %(glint_sites)d glint sites, %(instructions)d instructions' % a)
if b is None:
    print('  (swaps.carglint-dense absent -- compared against the literal expectation only)')
elif a != b:
    sys.stderr.write('    census DIFFERS from carglint-dense on the old base: %s vs %s\n' % (a, b)); sys.exit(1)
else:
    print('  IDENTICAL to swaps.carglint-dense on %s -- the rq3 splice costs zero sites' % 'the old base')
PY

# --- 4. k_glint = 0 on the EARGLOW base reproduces earglow-rq3 -------------
echo "=== 4. k_glint = 0 is a REAL null against $EGBASE"
d=0; for f in "$WORK/rung.null"/*.spv; do cmp -s "$SRC/$(basename "$f")" "$f" || d=$((d+1)); done
[[ "$d" == 0 ]] || { echo "  !! $d of 93 null modules differ from $EGBASE" >&2; exit 1; }
echo "  93 of 93 cmp-identical to $EGBASE (through dis -> patcher -> as -> val)"

# --- 5. exactly ten files move, against BOTH lineages ---------------------
echo "=== 5. file-level difference census"
for pair in "$SRC:$EGBASE" "$OLD:$OLDBASE"; do
    ref="${pair%%:*}"; name="${pair#*:}"; d=0; nd=0
    for f in "$MOD_DIR/swaps.$RUNG"/*.spv; do
        if cmp -s "$ref/$(basename "$f")" "$f"; then nd=$((nd+1)); else d=$((d+1)); fi
    done
    [[ "$d" == 10 ]] || { echo "  !! $d of 93 differ from $name, want exactly 10" >&2; exit 1; }
    echo "  10 of 93 differ from $name (the 10 patchable rgs_reference_main), $nd identical"
done
d=0; for h in "${TARGETS[@]}"; do
    cmp -s "$MOD_DIR/swaps.carglint-dense/$h.rgs_reference_main.spv" \
           "$MOD_DIR/swaps.$RUNG/$h.rgs_reference_main.spv" || d=$((d+1)); done
[[ "$d" == 10 ]] || { echo "  !! only $d of 10 differ from carglint-dense -- the glow is missing" >&2; exit 1; }
echo "  10 of 10 differ from swaps.carglint-dense (so the glow really is carried)"

# --- 6. BOTH verifiers, on the shipped stacked bytes ----------------------
echo "=== 6. verifiers"
python3 "$VERIFY" "$MOD_DIR/swaps.$RUNG" "${KNOBS[@]}"
python3 "$EGVERIFY" "$MOD_DIR/swaps.$RUNG" --base "$OLD" --mode glow --wide 4.0 --wrap 0.35
reject () { local what="$1"; shift
    if "$@" >/dev/null 2>&1; then echo "  !! ACCEPTS $what -- vacuous" >&2; exit 1; fi
    echo "  rejects $what, as required"; }
echo "  non-vacuity:"
reject "the earglow base as a glint rung"      python3 "$VERIFY" "$SRC" "${KNOBS[@]}"
reject "the stacked rung read with the DEFAULT knobs" python3 "$VERIFY" "$MOD_DIR/swaps.$RUNG"
reject "the stacked rung read as the control"  python3 "$VERIFY" "$MOD_DIR/swaps.$RUNG" --ctl
reject "the OLD base as an ear-glow rung"      python3 "$EGVERIFY" "$OLD" --base "$OLD" --mode glow --wide 4.0 --wrap 0.35
reject "carglint-dense (no glow) as an ear-glow rung" \
       python3 "$EGVERIFY" "$MOD_DIR/swaps.carglint-dense" --base "$OLD" --mode glow --wide 4.0 --wrap 0.35
reject "the stacked rung read at the WRONG glow knobs" \
       python3 "$EGVERIFY" "$MOD_DIR/swaps.$RUNG" --base "$OLD" --mode glow --wide 2.0 --wrap 0.35

# --- 7. MANIFEST ---------------------------------------------------------
sed -e "1s/^$EGBASE /$RUNG /" \
    -e "1s/ref=12([^)]*)/ref=12(10 earglow-rq3 + carglint --nu0 600000 + 2 scalar-specular pass-through)/" \
    "$SRC/MANIFEST.txt" > "$MOD_DIR/swaps.$RUNG/MANIFEST.txt"
grep -q "^$RUNG " "$MOD_DIR/swaps.$RUNG/MANIFEST.txt" || { echo "MANIFEST rewrite failed" >&2; exit 1; }
{   echo "# STACKED (handoff/100 sec 13): earglow-rq3's three ray queries PLUS"
    echo "# 94 sec 4.4's car-paint glints at the -dense knobs (nu0 = 6e5), both"
    echo "# in the same 10 of 12 rgs_reference_main permutations."
    echo "# Order: rq3 first, glints spliced on top. k_glint=0 on these bytes"
    echo "# reproduces earglow-rq3 at 93/93 cmp, and verify_earglow_rq3.py still"
    echo "# PASSES on this output -- the glow splice is untouched by the rewrite."
    echo "# USER VERDICT 2026-09-03: 'carglint-dense looks incredible too.'"
} >> "$MOD_DIR/swaps.$RUNG/MANIFEST.txt"

echo
printf '  %s\n  content sha %s\n' "$RUNG" \
       "$(cat "$MOD_DIR/swaps.$RUNG"/*.spv | sha256sum | cut -c1-16)"
echo
if (( DO_INSTALL )); then
    park="$INSTALL_DIR/skin.set/$RUNG"
    mkdir -p "$park"; rm -f "$park"/*.spv "$park"/*.json "$park/MANIFEST.txt"
    cp -pf "$MOD_DIR/swaps.$RUNG"/*.spv "$MOD_DIR/swaps.$RUNG"/*.json \
           "$MOD_DIR/swaps.$RUNG/MANIFEST.txt" "$park/"
    echo "  parked -> $park ($(ls "$park"/*.spv | wc -l) modules)"
else
    echo "NOT installed. To park: ./dev/build_carglint_stack.sh --install"
fi
echo
echo "select with skinspec=$RUNG"
echo "contract: ser=class + shadowset=full-shadow. The default skinspec value in"
echo "init.lua is NOT changed here -- 101's author owns that edit."
