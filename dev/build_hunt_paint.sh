#!/usr/bin/env bash
# hunt-paint: the one-frame material probe that decides the car-paint gate.
#
#   ./dev/build_hunt_paint.sh                 # build + verify (no install)
#   ./dev/build_hunt_paint.sh --install       # ALSO park hunt-paint + hunt-paint-ctl
#   ./dev/build_hunt_paint.sh --set r_mid=0.25 --install
#
# handoff/94 sec 1 proved the 3-bit material class has no paint family: the
# populated set is {0 default, 1 skin, 3 normal-decode, 4 hair, 5 vegetation}
# and no clearcoat lobe exists anywhere in the renderer. So the coat's gate
# must be metallic x roughness on class 0. This rung paints that hypothesis
# on screen: class colours for 1/3/4/5 (skin RED = the built-in control, the
# same colour the known-good class hunt used) plus six metallic x roughness
# buckets for class 0, all in ONE frame.
#
# It rides gi-50b-bleed-oil-sheen-deep-clothhi-cone2all, the standing
# selection, and touches ONE family: the 77 compute (resolve) modules --
# the family that owns the primary hit's direct light (94 sec 2, site C).
# The 16 raygens are copied BYTE-VERBATIM and asserted so.
#
# Rungs built:
#   swaps.huntpaint       gain 1  the probe
#   swaps.huntpaint.ctl   gain 0  the control: 93 of 93 modules `cmp`-identical
#                                 to the base. Non-tautological because step 2
#                                 proves spirv-dis -> spirv-as is byte-neutral
#                                 on all 77 base modules FIRST, so the control
#                                 goes through the whole pipeline.
#   (scratch) nobuckets   gain 1, --no-buckets: the deliberately mis-gated
#                                 build the verifier MUST reject.
set -euo pipefail

MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="${CALLISTO_INSTALL_DIR:-$HOME/.local/lib/callisto}"
PY="$MOD_DIR/dev/patch_hunt_paint.py"
VERIFY="$MOD_DIR/dev/verify_hunt_paint.py"

BASE=gi-50b-bleed-oil-sheen-deep-clothhi-cone2all
NAME=hunt-paint
DO_INSTALL=0
SET_ARGS=()
while (( $# )); do
    case "$1" in
        --install) DO_INSTALL=1 ;;
        --base) BASE="${2:?--base needs a skin.set name}"; shift ;;
        --name) NAME="${2:?--name needs a rung name}"; shift ;;
        --set)  SET_ARGS+=(--set "${2:?--set needs K=V}"); shift ;;
        *) echo "unknown arg $1" >&2; exit 1 ;;
    esac
    shift
done

SRC="$INSTALL_DIR/skin.set/$BASE"
DEST="$MOD_DIR/swaps.huntpaint"
CTL="$MOD_DIR/swaps.huntpaint.ctl"
WORK="$MOD_DIR/dev/disasm/huntpaint"

[[ -f "$SRC/MANIFEST.txt" ]] || { echo "no $SRC/MANIFEST.txt -- the standing selection is not parked" >&2; exit 1; }
n_c=$(ls "$SRC"/*.dxil.spv | wc -l)
n_r=$(ls "$SRC"/*.rgs_*.spv | wc -l)
[[ "$n_c" == 77 ]] || { echo "$BASE has $n_c compute modules, expected 77" >&2; exit 1; }
[[ "$n_r" == 16 ]] || { echo "$BASE has $n_r raygen modules, expected 16" >&2; exit 1; }

# --- 1. disassemble the 77 compute sources ---------------------------------
rm -rf "$WORK"; mkdir -p "$WORK/asm" "$WORK/out" "$WORK/ctl" "$WORK/nob" "$WORK/rt"
jobs="${CALLISTO_JOBS:-$(nproc 2>/dev/null || echo 4)}"
ls "$SRC"/*.dxil.spv | xargs -P "$jobs" -I{} bash -c \
    'n=$(basename "$1" .dxil.spv); spirv-dis "$1" -o "'"$WORK"'/asm/$n.spvasm"' _ {}
[[ "$(ls "$WORK/asm" | wc -l)" == 77 ]] || { echo "disassembly lost modules" >&2; exit 1; }

# --- 2. the pipeline is byte-neutral ---------------------------------------
# Without this the gain-0 control is a tautology ("we copied the file").
# With it, the control has been through spirv-dis, the patcher's loader, and
# spirv-as, and still matches the shipped base byte for byte.
echo "--- 2. round-trip neutrality (dis -> as == base bytes) ---"
same=0
for a in "$WORK"/asm/*.spvasm; do
    n="$(basename "${a%.spvasm}")"
    spirv-as --target-env spv1.3 "$a" -o "$WORK/rt/$n.spv"
    cmp -s "$SRC/$n.dxil.spv" "$WORK/rt/$n.spv" || { echo "  !! $n does not round-trip -- the control would be meaningless" >&2; exit 1; }
    same=$((same+1))
done
echo "  $same of 77 modules round-trip byte-identically"
rm -rf "$WORK/rt"

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
echo "--- 3. patch (gain 1) ---"
patch_all "$WORK/out" --gain 1.0 "${SET_ARGS[@]}"
echo "--- 3b. control (gain 0) ---"
patch_all "$WORK/ctl" --gain 0.0
echo "--- 3c. mis-gated (--no-buckets, scratch only) ---"
patch_all "$WORK/nob" --gain 1.0 --no-buckets "${SET_ARGS[@]}"

# --- 4. coverage, from the reports, never from byte counts (the 42 rule) ---
echo "--- 4. coverage ---"
python3 - "$MOD_DIR" "$WORK/out" "$WORK/ctl" "$WORK/nob" <<'PY' || exit 1
import glob, json, os, sys
sys.path.insert(0, os.path.join(sys.argv[1], 'dev'))
import patch_hunt_paint as HP
bad = []

def scan(d, want_paint):
    ok = {os.path.basename(f)[4:] for f in glob.glob(os.path.join(d, '.ok.*'))}
    badm = {os.path.basename(f)[5:] for f in glob.glob(os.path.join(d, '.bad.*'))}
    tot = dict(mods=0, writes=0, refetched=0, skipped=0)
    thr = set()
    for f in sorted(glob.glob(os.path.join(d, '.*.json'))):
        n = os.path.basename(f)[1:-5]
        if n in badm:
            # the module declined; its report is the stderr file, not json
            continue
        try:
            r = json.load(open(f))[0]
        except Exception as e:
            bad.append((os.path.basename(f), 'bad json: %s' % e)); continue
        if r.get('spirv_val') != 'clean':
            bad.append((r.get('module'), 'spirv-val not clean'))
        p = r.get('paint')
        if p is None:
            bad.append((r.get('module'), 'no paint report')); continue
        tot['mods'] += 1
        tot['writes'] += len(p['writes'])
        tot['refetched'] += len(p['refetched'])
        tot['skipped'] += len(p['skipped'])
        if want_paint:
            if not p['writes']:
                bad.append((r.get('module'), 'zero painted writes'))
            thr.add(json.dumps(p['thresholds'], sort_keys=True))
    return ok, badm, tot, thr

ok, badm, tot, thr = scan(sys.argv[2], True)
print('  probe : %d modules patched, %d declined, %d writes '
      '(%d refetched), %d skipped'
      % (tot['mods'], len(badm), tot['writes'], tot['refetched'], tot['skipped']))
if badm != HP.KNOWN_DECLINE:
    bad.append(('coverage', 'declines are %s, expected exactly %s'
                % (sorted(badm), sorted(HP.KNOWN_DECLINE))))
C = HP.CENSUS
if tot['mods'] != C['painted_modules']:
    bad.append(('coverage', '%d painted modules, census says %d' % (tot['mods'], C['painted_modules'])))
if tot['writes'] != C['writes']:
    bad.append(('coverage', '%d painted writes, census says %d' % (tot['writes'], C['writes'])))
if tot['refetched'] != C['refetched']:
    bad.append(('coverage', '%d refetched sites, census says %d' % (tot['refetched'], C['refetched'])))
if tot['skipped']:
    bad.append(('coverage', '%d image writes skipped inside PATCHED modules -- '
                'the paint is missing from a site the census counts' % tot['skipped']))
if len(thr) != 1:
    bad.append(('knobs', 'modules disagree on the thresholds: %s' % sorted(thr)))
else:
    print('  thresholds: %s' % sorted(thr)[0])

okc, badc, totc, _ = scan(sys.argv[3], False)
print('  control: %d modules emitted, %d declined, %d writes painted'
      % (totc['mods'], len(badc), totc['writes']))
if totc['mods'] != C['modules'] or badc:
    bad.append(('control', 'control emitted %d modules and declined %s, want %d / none'
                % (totc['mods'], sorted(badc), C['modules'])))
if totc['writes']:
    bad.append(('control', 'the gain-0 control painted %d writes' % totc['writes']))

okn, badn, totn, _ = scan(sys.argv[4], True)
print('  nobkt  : %d modules patched, %d writes (mis-gated decoy)'
      % (totn['mods'], totn['writes']))
if totn['writes'] != C['writes']:
    bad.append(('decoy', 'decoy painted %d writes, want %d' % (totn['writes'], C['writes'])))

if bad:
    for m, why in bad[:12]:
        sys.stderr.write('    %s :: %s\n' % (m, why))
    sys.exit(1)
PY

# --- 5. assemble the rungs (93 files each) ---------------------------------
assemble () {   # $1 = dest, $2 = patched-compute dir
    local dest="$1" src="$2"
    rm -rf "$dest"; mkdir -p "$dest"
    cp -pf "$SRC"/*.rgs_*.spv "$dest/"
    cp -pf "$src"/*.dxil.spv "$dest/" 2>/dev/null || true
    # any compute module the patcher declined rides the base bytes verbatim,
    # so the rung is always a complete 93-file selection.
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
assemble "$DEST" "$WORK/out"
assemble "$CTL" "$WORK/ctl"
NOB="$WORK/rung.nob"; assemble "$NOB" "$WORK/nob"

d=0; for f in "$SRC"/*.dxil.spv; do cmp -s "$f" "$DEST/$(basename "$f")" || d=$((d+1)); done
echo "  probe  : $d of 77 compute modules differ from $BASE"
[[ "$d" == 76 ]] || { echo "  !! expected exactly 76 (the census); the paint did not reach what it claims" >&2; exit 1; }
d=0; for f in "$SRC"/*.spv; do cmp -s "$f" "$CTL/$(basename "$f")" || d=$((d+1)); done
echo "  control: $d of 93 modules differ from $BASE"
[[ "$d" == 0 ]] || { echo "  !! the gain-0 control is NOT byte-identical to the base" >&2; exit 1; }
d=0; for f in "$DEST"/*.spv; do cmp -s "$f" "$NOB/$(basename "$f")" || d=$((d+1)); done
[[ "$d" -gt 0 ]] || { echo "  !! the mis-gated decoy is byte-identical to the probe" >&2; exit 1; }

# --- 6. the verifier, on shipped bytes, proven non-vacuous -----------------
echo "--- 6. verifier ---"
python3 "$VERIFY" "$DEST" || { echo "  !! the verifier rejects its own probe build" >&2; exit 1; }
echo "  non-vacuity 1/3: it must REJECT the unpatched base"
if python3 "$VERIFY" "$SRC" >/dev/null 2>&1; then
    echo "  !! the verifier ACCEPTS the unpatched base -- it is vacuous" >&2; exit 1; fi
echo "    rejected, as required"
echo "  non-vacuity 2/3: it must REJECT the gain-0 control"
if python3 "$VERIFY" "$CTL" >/dev/null 2>&1; then
    echo "  !! the verifier ACCEPTS the gain-0 control -- it is vacuous" >&2; exit 1; fi
echo "    rejected, as required"
echo "  non-vacuity 3/3: it must REJECT the mis-gated --no-buckets build"
if python3 "$VERIFY" "$NOB" >/dev/null 2>&1; then
    echo "  !! the verifier ACCEPTS a build with NO metallic/roughness gate" >&2; exit 1; fi
echo "    rejected, as required"

# --- 7. MANIFESTs ----------------------------------------------------------
manifest () {   # $1 = dest, $2 = rung name, $3 = tail comment
    sed -e "1s/^$BASE /$2 /" -e "1s/compute=77([^)]*)/compute=77($BASE-huntpaint)/" \
        "$SRC/MANIFEST.txt" > "$1/MANIFEST.txt"
    grep -q "^$2 " "$1/MANIFEST.txt" || { echo "MANIFEST rewrite failed" >&2; exit 1; }
    echo "# $3" >> "$1/MANIFEST.txt"
}
manifest "$DEST" "$NAME" "hunt-paint probe: class 1/3/4/5 tints + class-0 metallic x roughness buckets at all 151 radiance writes of the 77 compute modules; raygens are $BASE bytes. ${SET_ARGS[*]:-default thresholds}. See handoff/94 sec 9-11."
manifest "$CTL" "$NAME-ctl" "hunt-paint CONTROL (gain 0): 93 of 93 modules byte-identical to $BASE. Selecting it must be indistinguishable from the base."

echo
echo "  built $DEST (93 modules) and $CTL (93 modules)"
if (( DO_INSTALL )); then
    for pair in "$DEST:$NAME" "$CTL:$NAME-ctl"; do
        s="${pair%%:*}"; n="${pair##*:}"
        park="$INSTALL_DIR/skin.set/$n"
        mkdir -p "$park"; rm -f "$park"/*.spv "$park/MANIFEST.txt"
        cp -pf "$s"/*.spv "$s/MANIFEST.txt" "$park/"
        echo "  parked -> $park"
    done
else
    echo "NOT installed. To park: ./dev/build_hunt_paint.sh --install"
fi
echo "select with skinspec=$NAME (probe) or skinspec=$NAME-ctl (control);"
echo "needs ser=class + shadowset=full-shadow ($BASE's contract)"
