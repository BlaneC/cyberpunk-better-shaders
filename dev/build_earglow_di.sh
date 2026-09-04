#!/usr/bin/env bash
# earglow-di -- ear glow (skin translucency) from LOCAL lights, spliced into
# the clustered light loop of the 77 compute direct-light resolvers.
# handoff/112-EARGLOW-LOCAL-LIGHT.md is the document. Read its section 8 (the
# pre-registered interpretation table) BEFORE looking at a frame, and shoot
# `bda-probe` FIRST: this rung reaches the TLAS only through swap_layer.c's
# BDA slot (`103`), and hole 4 (the pipeline link in the game) is still open.
#
#   ./dev/build_earglow_di.sh              # build + gates (nothing installed)
#   ./dev/build_earglow_di.sh --install    # ALSO park the four rungs
#   ./dev/build_earglow_di.sh --base NAME  # build on a different parked rung
#
# FOUR RUNGS on the shipped default's bytes (16 raygens verbatim):
#
#   earglow-di       the term at the -hue1 model's own k (7.2787), the same
#                    constants the sun-only raygen glow ships with.
#   earglow-di-hi    the same at 2 k. Louder, nothing else.
#   earglow-di-hit   DIAGNOSTIC. Class-1 pixels, per light: BLUE = accepted
#                    (same-instance wall AND the exit point sees the light),
#                    AMBER = same-instance wall but query C HIT (interior
#                    wall / occluder), RED = the slot magic was wrong (the
#                    layer did not arm). Nothing = B missed, foreign
#                    instance, or the light is out of range.
#   earglow-di-ctl   BYTE-IDENTICAL to the base. Control for the selector.
set -euo pipefail

MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="${CALLISTO_INSTALL_DIR:-$HOME/.local/lib/callisto}"
PY="$MOD_DIR/dev/patch_earglow_di.py"
VERIFY="$MOD_DIR/dev/verify_earglow_di.py"
MODEL_PY="$MOD_DIR/dev/transmit_model.py"
WORK="$MOD_DIR/dev/disasm/earglow_di"

BASE=gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog-earglow-cap6-glintdense-curv-t7hue1
K_HI=2.0
DO_INSTALL=0
while (( $# )); do
    case "$1" in
        --install) DO_INSTALL=1 ;;
        --base) BASE="${2:?--base needs a skin.set name}"; shift ;;
        -h|--help) sed -n '2,26p' "$0"; exit 0 ;;
        *) echo "unknown arg $1" >&2; exit 1 ;;
    esac
    shift
done
SRC="$INSTALL_DIR/skin.set/$BASE"

# Stated HERE, independently of the patcher: what the census must say.
WANT_SPLICED=60      # modules with a shadowed light loop
WANT_SITES=102       # shadowed light loops over those modules
WANT_UNSHADOWED=30   # unshadowed loops, skipped by name (spot factor inside the lit block)
WANT_NOLOOP=15       # sun-only resolvers, byte-identical
WANT_DECLINED=2      # 103's ab0bc2fee876d489 + 99bb7c2698997b2a, byte-identical
WANT_K=7.2787        # the -hue1 model (111): --ref 0.006 --fb-derm 0.01 --no-sensitivity

# --- 0. base provenance -----------------------------------------------------
[[ -f "$SRC/MANIFEST.txt" ]] || { echo "no $SRC/MANIFEST.txt -- the base is not parked" >&2; exit 1; }
n_c=$(ls "$SRC"/*.dxil.spv | wc -l)
n_g=$(ls "$SRC"/*.rgs_restirgi_*.spv | wc -l)
n_r=$(ls "$SRC"/*.rgs_reference_main.spv | wc -l)
[[ "$n_c" == 77 ]] || { echo "$BASE has $n_c compute modules, expected 77" >&2; exit 1; }
[[ "$n_g" == 4  ]] || { echo "$BASE has $n_g restirgi modules, expected 4" >&2; exit 1; }
[[ "$n_r" == 12 ]] || { echo "$BASE has $n_r rgs_reference_main, expected 12" >&2; exit 1; }
mapfile -t TARGETS < <(cd "$SRC" && ls *.dxil.spv | sed 's/\..*//')
(( ${#TARGETS[@]} == 77 )) || { echo "expected 77 compute resolvers" >&2; exit 1; }
echo "=== 0. base: $BASE ($(head -1 "$SRC/MANIFEST.txt" | cut -c1-90))"

rm -rf "$WORK"; mkdir -p "$WORK/asm" "$WORK/rt" "$WORK/model"
for h in "${TARGETS[@]}"; do
    spirv-dis "$SRC/$h.dxil.spv" -o "$WORK/asm/$h.spvasm"
done

# --- 1. round-trip neutrality ----------------------------------------------
echo "=== 1. round-trip neutrality (spirv-dis -> spirv-as == base bytes)"
for h in "${TARGETS[@]}"; do
    spirv-as --target-env spv1.3 "$WORK/asm/$h.spvasm" -o "$WORK/rt/$h.spv"
    cmp -s "$SRC/$h.dxil.spv" "$WORK/rt/$h.spv" \
        || { echo "  !! $h does not round-trip -- no control built on it is meaningful" >&2; exit 1; }
done
echo "  77 of 77 compute resolvers round-trip byte-identically"
rm -rf "$WORK/rt"

# --- 2. the model: the SAME constants the shipped -hue1 raygen glow uses ---
echo "=== 2. the transmittance model (dev/transmit_model.py, -hue1 point)"
MODEL="$WORK/model/r6lo.json"
python3 "$MODEL_PY" --ref 0.006 --fb-derm 0.01 --no-sensitivity --emit "$MODEL" > "$WORK/model/r6lo.txt"
python3 - "$MODEL" "$WANT_K" "$SRC/MANIFEST.txt" <<'PY' || exit 1
import json, re, sys
m = json.load(open(sys.argv[1])); want = float(sys.argv[2])
assert abs(m['k'] - want) < 1e-3, f"k {m['k']}, want {want}"
assert m['f_blood'][0] == 0.01 and m['ref_m'] == 0.006
assert m['tint'][0] == 1.0 and 0 < m['tint'][1] < m['tint'][2] < 1
for a1, a2 in m['rates_1_per_m']:
    assert a1 > a2 > 0
# the base's own MANIFEST names the model it ships with
man = open(sys.argv[3]).read()
if 'r6lo' not in man and 'fb-derm 0.01' not in man and 'hue1' not in man:
    sys.stderr.write('  !! the base MANIFEST does not name the -hue1 model\n'); sys.exit(1)
print('  k = %.4f, tint = [1, %.4f, %.4f], rates R %s' % (m['k'], m['tint'][1], m['tint'][2],
      [round(x, 1) for x in m['rates_1_per_m'][0]]))
PY

jobs="${CALLISTO_JOBS:-$(nproc 2>/dev/null || echo 4)}"

patch_set () {   # $1 = outdir, $2.. = patcher args
    local out="$1"; shift
    mkdir -p "$out"
    printf '%s\n' "$@" > "$WORK/.args"
    # the model path is passed on its own line: the repo path has a SPACE
    [[ " $* " == *" ctl "* ]] || printf -- '--model\n%s\n' "$MODEL" >> "$WORK/.args"
    printf '%s\0' "${TARGETS[@]}" | CB_O="$out" CB_P="$PY" CB_W="$WORK" \
        CB_A="$WORK/.args" xargs -0 -P "$jobs" -n1 bash -c '
            mapfile -t A < "$CB_A"
            python3 "$CB_P" "$CB_W/asm/$0.spvasm" "${A[@]}" --outdir "$CB_O" \
                > "$CB_O/$0.earglow_di.report.json"'
    rm -f "$WORK/.args"
    local n; n=$(ls "$out"/*.spv 2>/dev/null | wc -l)
    [[ "$n" == 77 ]] || { echo "  !! $out produced $n modules, want 77" >&2; exit 1; }
}

assemble () {   # $1 = dest, $2 = patched-compute dir, $3 = want_diff (0 = the control)
    local dest="$1" src="$2" want_diff="$3"
    rm -rf "$dest"; mkdir -p "$dest"
    cp -pf "$src"/*.spv "$src"/*.json "$dest/"
    cp -pf "$SRC"/*.rgs_reference_main.spv "$SRC"/*.rgs_restirgi_*.spv "$dest/"
    for f in "$SRC"/*.rgs_reference_main.spv "$SRC"/*.rgs_restirgi_*.spv; do
        cmp -s "$f" "$dest/$(basename "$f")" \
            || { echo "  !! verbatim copy differs: $(basename "$f")" >&2; exit 1; }
    done
    local d=0
    for h in "${TARGETS[@]}"; do
        cmp -s "$SRC/$h.dxil.spv" "$dest/$h.dxil.spv" || d=$((d+1))
    done
    [[ "$d" == "$want_diff" ]] || { echo "  !! $dest differs on $d compute modules, want $want_diff" >&2; exit 1; }
    local n; n=$(ls "$dest"/*.spv | wc -l)
    [[ "$n" == 93 ]] || { echo "  !! $dest has $n modules, expected 93" >&2; exit 1; }
    for f in "$dest"/*.spv; do
        spirv-val --target-env vulkan1.4 "$f" >/dev/null \
            || { echo "  !! spirv-val --target-env vulkan1.4 FAILED: $f" >&2; exit 1; }
    done
}

# --- 3. patch + assemble ----------------------------------------------------
echo "=== 3. patch + assemble the four rungs"
ORDER=(earglow-di earglow-di-hi earglow-di-hit earglow-di-ctl)
declare -A RUNG_ARGS=(
    [earglow-di]="--mode glow"
    [earglow-di-hi]="--mode glow --k-scale $K_HI"
    [earglow-di-hit]="--mode hit"
    [earglow-di-ctl]="--mode ctl"
)
declare -A RUNG_DIFF=([earglow-di]=$WANT_SPLICED [earglow-di-hi]=$WANT_SPLICED
                      [earglow-di-hit]=$WANT_SPLICED [earglow-di-ctl]=0)
for r in "${ORDER[@]}"; do
    # shellcheck disable=SC2086
    patch_set "$WORK/p.$r" ${RUNG_ARGS[$r]}
    assemble "$MOD_DIR/swaps.$r" "$WORK/p.$r" "${RUNG_DIFF[$r]}"
    echo "  swaps.$r: 93 modules, ${RUNG_DIFF[$r]} compute modules differ from the base, spirv-val (vulkan1.4) clean"
done
for pair in "earglow-di earglow-di-hi" "earglow-di earglow-di-hit" "earglow-di-hi earglow-di-hit"; do
    set -- $pair; d=0
    for h in "${TARGETS[@]}"; do
        cmp -s "$MOD_DIR/swaps.$1/$h.dxil.spv" "$MOD_DIR/swaps.$2/$h.dxil.spv" || d=$((d+1))
    done
    [[ "$d" == "$WANT_SPLICED" ]] || { echo "  !! $1 vs $2 differ on $d modules, want $WANT_SPLICED" >&2; exit 1; }
done
echo "  di / hi / hit differ pairwise on exactly the $WANT_SPLICED spliced modules"

# --- 4. coverage census, from the REPORTS -----------------------------------
echo "=== 4. coverage census (reports)"
python3 - "$MOD_DIR" "$WANT_SPLICED" "$WANT_SITES" "$WANT_UNSHADOWED" "$WANT_NOLOOP" "$WANT_DECLINED" "$WANT_K" "$K_HI" "${ORDER[@]}" <<'PY' || exit 1
import glob, json, os, sys
mod_dir = sys.argv[1]
W_SPL, W_SITES, W_UNSH, W_NOLOOP, W_DEC = map(int, sys.argv[2:7])
W_K, K_HI = float(sys.argv[7]), float(sys.argv[8])
rungs = sys.argv[9:]
SENT, MAGIC = 'ca1157000bda0001', 'ca115701'
bad = []
for r in rungs:
    d = os.path.join(mod_dir, 'swaps.' + r)
    ctl = r.endswith('-ctl')
    spl = sites = unsh = noloop = dec = mods = 0
    other_skips = []
    ids = set()
    for f in sorted(glob.glob(os.path.join(d, '*.earglow_di.report.json'))):
        rep = json.load(open(f))[0]
        q = rep['earglow_di']
        mods += 1
        if rep.get('spirv_val') != 'clean':
            bad.append((r, rep['module'], 'spirv-val not clean'))
        if q.get('decoy'):
            bad.append((r, rep['module'], 'a DECOY build reached a rung'))
        if ctl:
            if q.get('emitted', 0) != 0 or not q.get('control'):
                bad.append((r, rep['module'], 'the control emitted instructions'))
            continue
        if q['declined']:
            dec += 1; continue
        if not q.get('emitted'):
            noloop += 1
            if q.get('skipped'):
                bad.append((r, rep['module'], 'identity module with skipped sites: %s' % q['skipped']))
            continue
        spl += 1
        sites += len(q['sites'])
        for s in q['skipped']:
            if s['why'].startswith('unshadowed loop'):
                unsh += 1
            else:
                other_skips.append((rep['module'], s))
        if q['sentinel'] != SENT or q['magic'] != MAGIC or q['slot_members'] != 8:
            bad.append((r, rep['module'], 'sentinel/magic/slot is not this build'))
        if q['lo_id'] is None or q['hi_id'] is None or q['lo_id'] == q['hi_id']:
            bad.append((r, rep['module'], 'marker ids are not a distinct pair'))
        if q['sentinel_pairs'] != 1:
            bad.append((r, rep['module'], '%d sentinel copies' % q['sentinel_pairs']))
        ids.add((q['lo_id'], q['hi_id']))
        if q['space'] != 'camera_relative' or q['campos_member'] != 0:
            bad.append((r, rep['module'], 'origin is not camera-relative P'))
        if q['cbv_slot'] != [0, 12] or q['matrix_members'] != [69, 70, 71, 72]:
            bad.append((r, rep['module'], 'view CBV / matrix members are not the known ones'))
        if q['flags'] != {'A': 517, 'B': 545, 'C': 517} or q['mask'] != 255:
            bad.append((r, rep['module'], 'flags/mask %s' % q['flags']))
        if (q['tmin_b'], q['tmax_b'], q['push'], q['tmin_c'], q['floor'], q['clamp']) != (0.0015, 0.018, 0.001, 0.001, 0.006, 100.0):
            bad.append((r, rep['module'], 'ray/transfer constants drifted'))
        want_k = W_K * (K_HI if r.endswith('-hi') else 1.0)
        if r != 'earglow-di-hit' and abs(q['k'] - want_k) > 1e-3:
            bad.append((r, rep['module'], 'k %s != %s' % (q['k'], want_k)))
        if any(s['n_masks'] < 1 for s in q['sites']):
            bad.append((r, rep['module'], 'a site without a visibility factor was spliced'))
    if mods != 77:
        bad.append((r, '-', '%d reports, want 77' % mods))
    if ctl:
        print('  %-14s 77 modules, 0 instructions emitted (the identity control)' % r); continue
    for k, got, want in (('spliced', spl, W_SPL), ('sites', sites, W_SITES),
                         ('unshadowed skipped', unsh, W_UNSH), ('no-loop', noloop, W_NOLOOP),
                         ('declined', dec, W_DEC)):
        if got != want:
            bad.append((r, '-', '%s %d != %d' % (k, got, want)))
    if other_skips:
        bad.append((r, '-', 'unexpected skips: %s' % other_skips[:3]))
    print('  %-14s %d spliced modules, %d sites (3 queries each), %d unshadowed loops skipped by name, '
          '%d sun-only + %d declined byte-identical, %d distinct marker id pairs'
          % (r, spl, sites, unsh, noloop, dec, len(ids)))
if bad:
    for b in bad[:12]:
        sys.stderr.write('    %s :: %s :: %s\n' % b)
    sys.exit(1)
PY

# --- 5. instruction census on the SHIPPED bytes -----------------------------
echo "=== 5. instruction census on the SHIPPED bytes"
python3 - "$MOD_DIR" "$SRC" "$WANT_SPLICED" "$WANT_SITES" "${ORDER[@]}" <<'PY' || exit 1
import glob, os, re, subprocess, sys
mod_dir, src = sys.argv[1], sys.argv[2]
W_SPL, W_SITES = int(sys.argv[3]), int(sys.argv[4])
rungs = sys.argv[5:]
sys.path.insert(0, os.path.join(mod_dir, 'dev'))
from verify_bda import binary_marker
bad = []
def dis(p):
    return subprocess.run(['spirv-dis', '--no-color', p], capture_output=True, text=True).stdout
for r in rungs:
    ctl = r.endswith('-ctl')
    d = os.path.join(mod_dir, 'swaps.' + r)
    tot = dict(marker=0, sent=0, init=0, proceed=0, tget=0, idget=0, conv=0, mods=0)
    for f in sorted(glob.glob(os.path.join(d, '*.dxil.spv'))):
        h = os.path.basename(f).split('.')[0]
        m = binary_marker(f)
        a = dis(f); b = dis(os.path.join(src, os.path.basename(f)))
        n = dict(init=a.count('OpRayQueryInitializeKHR'), proceed=a.count('OpRayQueryProceedKHR'),
                 tget=a.count('OpRayQueryGetIntersectionTKHR'),
                 idget=a.count('OpRayQueryGetIntersectionInstanceIdKHR'),
                 conv=a.count('OpConvertUToAccelerationStructureKHR'))
        if ctl:
            if m['markers'] or m['n_lo'] or m['n_hi'] or any(n.values()):
                bad.append('%s/%s: the CONTROL carries a marker or ray-query work' % (r, h))
            continue
        if not m['markers']:
            if any(n.values()):
                bad.append('%s/%s: ray-query work without a marker' % (r, h))
            continue
        if len(m['markers']) != 1 or (m['n_lo'], m['n_hi']) != (1, 1):
            bad.append('%s/%s: marker/sentinel census %d/%d/%d' % (r, h, len(m['markers']), m['n_lo'], m['n_hi']))
        if n['init'] == 0 or n['init'] % 3 or n['init'] != n['proceed'] or n['tget'] * 3 != n['init'] \
                or n['idget'] * 3 != 2 * n['init'] or n['conv'] != 1:
            bad.append('%s/%s: init/proceed/t/id/conv %s' % (r, h, n))
        if a.count('OpTraceRayKHR') != b.count('OpTraceRayKHR'):
            bad.append('%s/%s: OpTraceRayKHR count changed' % (r, h))
        if a.count('OpImageWrite') != b.count('OpImageWrite'):
            bad.append('%s/%s: OpImageWrite count changed' % (r, h))
        tot['mods'] += 1; tot['marker'] += len(m['markers']); tot['sent'] += m['n_lo'] + m['n_hi']
        for k in n: tot[k] += n[k]
    if ctl:
        print('  %-14s 0 markers, 0 sentinel constants, 0 ray-query instructions' % r); continue
    if tot['mods'] != W_SPL or tot['init'] != 3 * W_SITES:
        bad.append('%s: %d marked modules / %d Initialize, want %d / %d' % (r, tot['mods'], tot['init'], W_SPL, 3 * W_SITES))
    print('  %-14s %d markers, %d sentinel constants, %d Initialize (%d sites x A/B/C), %d Proceed, '
          '%d t reads, %d InstanceId reads, %d AS conversions'
          % (r, tot['marker'], tot['sent'], tot['init'], tot['init'] // 3, tot['proceed'], tot['tget'], tot['idget'], tot['conv']))
for r in rungs:
    for f in sorted(glob.glob(os.path.join(mod_dir, 'swaps.' + r, '*.rgs_*.spv'))):
        if binary_marker(f)['markers']:
            bad.append('%s: a RAYGEN carries the marker: %s' % (r, os.path.basename(f)))
if bad:
    for b in bad[:12]:
        sys.stderr.write('    ' + b + '\n')
    sys.exit(1)
PY

# --- 6. the identity control, over the WHOLE set ----------------------------
echo "=== 6. earglow-di-ctl identity"
d=0
for f in "$SRC"/*.spv; do
    cmp -s "$f" "$MOD_DIR/swaps.earglow-di-ctl/$(basename "$f")" || d=$((d+1))
done
[[ "$d" == 0 ]] || { echo "  !! earglow-di-ctl differs from the base on $d files" >&2; exit 1; }
echo "  earglow-di-ctl: 93 of 93 byte-identical to $BASE"

# --- 7. the verifier, on the shipped bytes ---------------------------------
echo "=== 7. verify_earglow_di.py on the shipped .spv"
python3 "$VERIFY" "$MOD_DIR/swaps.earglow-di"     --base "$SRC" --model "$MODEL" --mode glow
python3 "$VERIFY" "$MOD_DIR/swaps.earglow-di-hi"  --base "$SRC" --model "$MODEL" --mode glow --k-scale "$K_HI"
python3 "$VERIFY" "$MOD_DIR/swaps.earglow-di-hit" --base "$SRC" --model "$MODEL" --mode hit
python3 "$VERIFY" --negative "$SRC"
python3 "$VERIFY" --negative "$MOD_DIR/swaps.earglow-di-ctl"

# --- 8. verifier NON-VACUITY: it must REJECT every decoy -------------------
echo "=== 8. verifier non-vacuity (each of these MUST fail)"
mkdir -p "$WORK/decoy"
reject () {  # $1 = label, rest = verifier argv
    local label="$1"; shift
    if python3 "$VERIFY" "$@" >/dev/null 2>&1; then
        echo "  !! VACUOUS: the verifier ACCEPTED $label" >&2; exit 1
    fi
    echo "  rejected: $label"
}
for dec in nomarker badid scan world cullback noc noa flatk spec; do
    patch_set "$WORK/decoy/$dec" --mode glow --decoy "$dec"
done
V=(--base "$SRC" --model "$MODEL" --mode glow)
reject "--decoy nomarker (the pointer with NO marker to authorise the fixup)" "$WORK/decoy/nomarker" "${V[@]}"
reject "--decoy badid (a marker naming ids that do not exist)"               "$WORK/decoy/badid" "${V[@]}"
reject "--decoy scan (a SECOND, unnamed sentinel pair)"                       "$WORK/decoy/scan" "${V[@]}"
reject "--decoy world (raw world P as the origin -- 99 sec 10.6)"             "$WORK/decoy/world" "${V[@]}"
reject "--decoy cullback (query B flags 529: reads the FRONT wall, t = tmin)" "$WORK/decoy/cullback" "${V[@]}"
reject "--decoy noc (no query C: 101 sec 15's defect, glow through shade)"    "$WORK/decoy/noc" "${V[@]}"
reject "--decoy noa (no instance match: 101 sec 13's collar/hair bleed)"      "$WORK/decoy/noa" "${V[@]}"
reject "--decoy flatk (no transmittance: T = 1, thickness ignored)"           "$WORK/decoy/flatk" "${V[@]}"
reject "--decoy spec (the term added at the SPECULAR write)"                  "$WORK/decoy/spec" "${V[@]}"
reject "earglow-di read as the diagnostic"      "$MOD_DIR/swaps.earglow-di" --base "$SRC" --model "$MODEL" --mode hit
reject "earglow-di-hit read as the glow"        "$MOD_DIR/swaps.earglow-di-hit" "${V[@]}"
reject "earglow-di read at k x $K_HI"           "$MOD_DIR/swaps.earglow-di" "${V[@]}" --k-scale "$K_HI"
reject "earglow-di-hi read at k x 1"            "$MOD_DIR/swaps.earglow-di-hi" "${V[@]}"
reject "the unpatched BASE read as a rung"      "$SRC" "${V[@]}"
reject "the CONTROL read as a rung"             "$MOD_DIR/swaps.earglow-di-ctl" "${V[@]}"
reject "earglow-di --negative (a marker-carrying rung read as marker-free)" "$MOD_DIR/swaps.earglow-di" --negative
for other in bda-rq-probe bda-probe; do
    if [[ -d "$INSTALL_DIR/skin.set/$other" ]]; then
        reject "$other (103's slot probe: the marker, but not this splice)" \
               "$INSTALL_DIR/skin.set/$other" "${V[@]}"
    fi
done
rm -rf "$WORK/decoy"

# --- 9. the fixup site survives an arbitrary address -----------------------
echo "=== 9. simulated fixup: rewrite both literals, re-validate"
python3 - "$MOD_DIR" "$WANT_SPLICED" "${ORDER[@]}" <<'PY' || exit 1
import glob, os, struct, subprocess, sys, tempfile
mod_dir, W_SPL, rungs = sys.argv[1], int(sys.argv[2]), sys.argv[3:]
sys.path.insert(0, os.path.join(mod_dir, 'dev'))
from patch_bda import SENT_LO, SENT_HI
ADDR = 0x00007F1234567000
lo, hi = ADDR & 0xffffffff, ADDR >> 32
bad = []
for r in rungs:
    if r.endswith('-ctl'):
        continue
    n_done = 0
    for f in sorted(glob.glob(os.path.join(mod_dir, 'swaps.' + r, '*.dxil.spv'))):
        b = bytearray(open(f, 'rb').read())
        w = list(struct.unpack('<%dI' % (len(b) // 4), bytes(b)))
        i, hits, uint_ty = 5, 0, set()
        while i < len(w):
            ln, op = w[i] >> 16, w[i] & 0xffff
            if ln == 0 or op == 54:
                break
            if op == 21 and ln == 4 and w[i + 2] == 32 and w[i + 3] == 0:
                uint_ty.add(w[i + 1])
            elif op == 43 and ln == 4 and w[i + 1] in uint_ty:
                if w[i + 3] == SENT_LO:
                    struct.pack_into('<I', b, (i + 3) * 4, lo); hits += 1
                elif w[i + 3] == SENT_HI:
                    struct.pack_into('<I', b, (i + 3) * 4, hi); hits += 1
            i += ln
        if hits == 0:
            continue
        if hits != 2:
            bad.append('%s/%s: %d literals rewritten, want 2' % (r, os.path.basename(f), hits)); continue
        with tempfile.NamedTemporaryFile(suffix='.spv', delete=False) as t:
            t.write(bytes(b)); p = t.name
        v = subprocess.run(['spirv-val', '--target-env', 'vulkan1.4', p], capture_output=True, text=True)
        os.unlink(p)
        if v.returncode != 0:
            bad.append('%s/%s: INVALID after the fixup' % (r, os.path.basename(f)))
        n_done += 1
    if n_done != W_SPL:
        bad.append('%s: %d modules rewritten, want %d' % (r, n_done, W_SPL))
    print('  %-14s %d modules rewritten to 0x%016x and re-validated clean' % (r, n_done, ADDR))
if bad:
    for x in bad[:8]:
        sys.stderr.write('    ' + x + '\n')
    sys.exit(1)
PY

# --- 10. MANIFEST provenance ------------------------------------------------
echo "=== 10. MANIFEST provenance"
for r in "${ORDER[@]}"; do
    dest="$MOD_DIR/swaps.$r"
    # line 1 names the rung and its base; the base's own line 1 is an ALIAS
    # line (dev/park_alias.sh) and must NOT be inherited by the glow rungs
    case "$r" in
      *-ctl) l1="$r (ALIAS of $BASE -- byte-identical control; dev/build_earglow_di.sh)" ;;
      *)     l1="$r (BUILT ON $BASE by dev/build_earglow_di.sh -- handoff/112; the compute half differs)" ;;
    esac
    { echo "$l1"; sed -e '1d' "$SRC/MANIFEST.txt"; } > "$dest/MANIFEST.txt"
    grep -q "^$r " "$dest/MANIFEST.txt" || { echo "MANIFEST rewrite failed for $r" >&2; exit 1; }
    {
      echo "# earglow-di (handoff/112): ear glow from LOCAL lights. In $WANT_SPLICED of the 77 compute"
      echo "# resolvers, at the $WANT_SITES shadowed light loops, three inline ray queries per"
      echo "# light per skin pixel (A: primary-surface instance from the camera, B: cull-front"
      echo "# thickness toward the light 1.5-18 mm, C: exit point -> light visibility) drive"
      echo "# 111's v7 transfer (the -hue1 model, k=$WANT_K, 6 mm floor) x the engine's own"
      echo "# attenuation x the light colour, added at the DIFFUSE write. Shadow masks are"
      echo "# deliberately not applied (a backlit ear is what they zero). $WANT_UNSHADOWED unshadowed"
      echo "# loops, $WANT_NOLOOP sun-only resolvers and 103's 2 declined modules are byte-identical."
      echo "# The TLAS arrives through swap_layer.c's BDA slot (103): the module carries"
      echo "# OpString \"CALLISTO_BDA_SLOT_V1 ...\" and the layer rewrites two OpConstant %uint"
      echo "# literals at vkCreateShaderModule. REQUIRES THAT LAYER; shoot bda-probe FIRST."
      case "$r" in
        *-ctl) echo "# THIS RUNG IS THE BASE, BYTE FOR BYTE. Control for the selector." ;;
        *-hi)  echo "# k x $K_HI. Louder, nothing else." ;;
        *-hit) echo "# DIAGNOSTIC: skin BLUE = accepted, AMBER = same-instance wall but C hit, RED = magic wrong." ;;
      esac
      echo "# A/B against $BASE."
    } >> "$dest/MANIFEST.txt"
done
echo "  4 MANIFESTs written, provenance (src_ser/ser_sha/ptq_sha) carried verbatim"

echo
echo "=== shas (content = cat of all 93 .spv in name order)"
setsha () {
    find "$1" -maxdepth 1 -name "$2" -print0 | sort -z | xargs -0 cat | sha256sum | cut -c1-16
}
for r in "${ORDER[@]}"; do
    printf '  %-16s content=%s  compute-half=%s\n' "$r" \
        "$(setsha "$MOD_DIR/swaps.$r" '*.spv')" "$(setsha "$MOD_DIR/swaps.$r" '*.dxil.spv')"
done
printf '  %-16s content=%s  compute-half=%s\n' "(base)" "$(setsha "$SRC" '*.spv')" "$(setsha "$SRC" '*.dxil.spv')"

if (( DO_INSTALL )); then
    for r in "${ORDER[@]}"; do
        park="$INSTALL_DIR/skin.set/$r"
        if [[ -d "$park" && ! -f "$park/.earglow-di-owned" ]]; then
            echo "  !! $park exists and was not created by build_earglow_di.sh -- refusing" >&2
            exit 1
        fi
        mkdir -p "$park"; touch "$park/.earglow-di-owned"
        rm -f "$park"/*.spv "$park"/*.json "$park/MANIFEST.txt"
        cp -pf "$MOD_DIR/swaps.$r"/*.spv "$MOD_DIR/swaps.$r"/*.json "$MOD_DIR/swaps.$r/MANIFEST.txt" "$park/"
        n=$(ls "$park"/*.spv | wc -l)
        [[ "$n" == 93 ]] || { echo "  !! parked $r has $n modules" >&2; exit 1; }
        for f in "$MOD_DIR/swaps.$r"/*.spv; do
            cmp -s "$f" "$park/$(basename "$f")" || { echo "  !! parked $r differs from the build: $(basename "$f")" >&2; exit 1; }
        done
        echo "  parked -> $park (93 modules, cmp-verbatim against the build)"
    done
else
    echo "NOT installed. To park: ./dev/build_earglow_di.sh --install"
fi
echo "select with skinspec=earglow-di | earglow-di-hi | earglow-di-hit | earglow-di-ctl;"
echo "needs ser=class + shadowset=full-shadow ($BASE's contract) AND the BDA layer (shoot bda-probe first)"
