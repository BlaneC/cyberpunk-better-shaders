#!/usr/bin/env bash
# bda -- Stage 2b (and 2c) from `98` sec 10.3/10.4: get a 64-bit TLAS device
# address into a COMPUTE resolver, where set 1 binding 0 is AtomicCounters and
# the RTAS heap is unreachable (`98` sec 10.2, measured: 0 of 675 compute
# modules can name an acceleration structure).
#
# handoff/103-STAGE-2B.md is the document. Read its section 8 (the
# pre-registered interpretation table) BEFORE looking at a frame.
#
#   ./dev/build_bda.sh              # build + 10 gates (nothing installed)
#   ./dev/build_bda.sh --install    # ALSO park the three rungs
#   ./dev/build_bda.sh --base NAME  # build on a different parked rung
#
# THREE RUNGS on the STANDING selection's own bytes.
#
#   bda-ctl        The patcher emits NOTHING and rewrites nothing, so the
#                  output is BYTE-IDENTICAL to the base (gate 5, resting on
#                  gate 1's round-trip neutrality). Control for the SELECTOR
#                  and the LAYER, not for the splice.
#   bda-probe      STAGE 2b. Every skin (class-1) pixel is painted GREEN if
#                  word 0 of the layer's slot reads back as the magic and RED
#                  if it does not. Nothing else in the frame changes.
#   bda-rq-probe   STAGE 2c. The same, plus ONE inline ray query per painted
#                  write from the resolver's own shading point converted to
#                  TLAS space, straight up, tmin 5 cm, tmax 3 m, flags 517.
#                  Skin is BLUE on a committed hit, AMBER on a miss, and still
#                  RED if the magic is wrong.
#
# THE LAYER IS HALF THE FEATURE. These rungs are inert -- worse, they are a
# wild pointer -- unless swap_layer.c armed the slot and rewrote the two
# marked constants. That is why the layer REJECTS a marker-carrying overlay on
# a device where the slot could not be armed, and the reject falls through to
# the NEXT overlay (`98` sec 7.2), never to vanilla. Prove the layer and the
# driver FIRST, without the game:
#     make layer && ./dev/selftest_bda.sh
set -euo pipefail

MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="${CALLISTO_INSTALL_DIR:-$HOME/.local/lib/callisto}"
PY="$MOD_DIR/dev/patch_bda.py"
VERIFY="$MOD_DIR/dev/verify_bda.py"
WORK="$MOD_DIR/dev/disasm/bda"

BASE=gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog-earglow-cap6-glintdense
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

# --- 0. base provenance -----------------------------------------------------
[[ -f "$SRC/MANIFEST.txt" ]] || { echo "no $SRC/MANIFEST.txt -- the standing selection is not parked" >&2; exit 1; }
n_c=$(ls "$SRC"/*.dxil.spv | wc -l)
n_g=$(ls "$SRC"/*.rgs_restirgi_*.spv | wc -l)
n_r=$(ls "$SRC"/*.rgs_reference_main.spv | wc -l)
[[ "$n_c" == 77 ]] || { echo "$BASE has $n_c compute modules, expected 77" >&2; exit 1; }
[[ "$n_g" == 4  ]] || { echo "$BASE has $n_g restirgi modules, expected 4" >&2; exit 1; }
[[ "$n_r" == 12 ]] || { echo "$BASE has $n_r rgs_reference_main, expected 12" >&2; exit 1; }

mapfile -t TARGETS < <(cd "$SRC" && ls *.dxil.spv | sed 's/\..*//')
(( ${#TARGETS[@]} == 77 )) || { echo "expected 77 compute resolvers" >&2; exit 1; }

echo "=== 0. base: $BASE ($(head -1 "$SRC/MANIFEST.txt" | cut -c1-90))"

rm -rf "$WORK"; mkdir -p "$WORK/asm" "$WORK/rt"
for h in "${TARGETS[@]}"; do
    spirv-dis "$SRC/$h.dxil.spv" -o "$WORK/asm/$h.spvasm"
done

# --- 1. the pipeline is byte-neutral on the compute resolvers ---------------
# Everything the -ctl rung claims rests on this: in --mode ctl the patcher
# emits no instruction, rewrites no operand, and writes the disassembly
# straight back.
echo "=== 1. round-trip neutrality (spirv-dis -> spirv-as == base bytes)"
for h in "${TARGETS[@]}"; do
    spirv-as --target-env spv1.3 "$WORK/asm/$h.spvasm" -o "$WORK/rt/$h.spv"
    cmp -s "$SRC/$h.dxil.spv" "$WORK/rt/$h.spv" \
        || { echo "  !! $h does not round-trip -- no control built on it is meaningful" >&2; exit 1; }
done
echo "  77 of 77 compute resolvers round-trip byte-identically"
rm -rf "$WORK/rt"

jobs="${CALLISTO_JOBS:-$(nproc 2>/dev/null || echo 4)}"

patch_set () {   # $1 = outdir, $2.. = patcher args
    local out="$1"; shift
    mkdir -p "$out"
    printf '%s\n' "$@" > "$WORK/.args"
    printf '%s\0' "${TARGETS[@]}" | CB_O="$out" CB_P="$PY" CB_W="$WORK" \
        CB_A="$WORK/.args" xargs -0 -P "$jobs" -n1 bash -c '
            mapfile -t A < "$CB_A"
            python3 "$CB_P" "$CB_W/asm/$0.spvasm" "${A[@]}" --outdir "$CB_O" \
                > "$CB_O/$0.bda.report.json"'
    rm -f "$WORK/.args"
    local n; n=$(ls "$out"/*.spv 2>/dev/null | wc -l)
    [[ "$n" == 77 ]] || { echo "  !! $out produced $n modules, want 77" >&2; exit 1; }
}

assemble () {   # $1 = dest, $2 = patched-compute dir, $3 = 1 if all 77 must be
                #      byte-identical to the base (the ctl rung)
    local dest="$1" src="$2" identical="${3:-0}" want_diff="${4:-0}"
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
    if (( identical )); then
        [[ "$d" == 0 ]] || { echo "  !! CONTROL differs from the base on $d modules" >&2; exit 1; }
    else
        [[ "$d" == "$want_diff" ]] || { echo "  !! $dest differs on $d compute modules, want $want_diff" >&2; exit 1; }
    fi
    local n; n=$(ls "$dest"/*.spv | wc -l)
    [[ "$n" == 93 ]] || { echo "  !! $dest has $n modules, expected 93" >&2; exit 1; }
    for f in "$dest"/*.spv; do
        spirv-val --target-env vulkan1.4 "$f" >/dev/null \
            || { echo "  !! spirv-val --target-env vulkan1.4 FAILED: $f" >&2; exit 1; }
    done
}

# --- 2. patch + assemble ----------------------------------------------------
echo "=== 2. patch + assemble the three rungs"
ORDER=(bda-ctl bda-probe bda-rq-probe)
declare -A RUNG_ARGS=(
    [bda-ctl]="--mode ctl"
    [bda-probe]="--mode probe"
    [bda-rq-probe]="--mode rq"
)
declare -A RUNG_IDENT=([bda-ctl]=1)
declare -A RUNG_DIFF=([bda-probe]=76 [bda-rq-probe]=75)
for r in "${ORDER[@]}"; do
    # shellcheck disable=SC2086
    patch_set "$WORK/p.$r" ${RUNG_ARGS[$r]}
    assemble "$MOD_DIR/swaps.$r" "$WORK/p.$r" "${RUNG_IDENT[$r]:-0}" "${RUNG_DIFF[$r]:-0}"
    echo "  swaps.$r: 93 modules, $( (( ${RUNG_IDENT[$r]:-0} )) && echo '77 identity' || echo "${RUNG_DIFF[$r]} patched"), spirv-val (vulkan1.4) clean"
done
d=0
for h in "${TARGETS[@]}"; do
    cmp -s "$MOD_DIR/swaps.bda-probe/$h.dxil.spv" \
           "$MOD_DIR/swaps.bda-rq-probe/$h.dxil.spv" || d=$((d+1))
done
# 75 carry both splices and differ in the splice; 99bb7c2698997b2a carries the
# probe but is declined by --mode rq (no position chain), so it differs too.
# Only ab0bc2fee876d489, declined in BOTH modes, is common.
[[ "$d" == 76 ]] || { echo "  !! bda-probe and bda-rq-probe differ on $d modules, want 76" >&2; exit 1; }
echo "  bda-probe vs bda-rq-probe: 76 of 77 differ (only ab0bc2fee876d489 is common)"

# --- 3. coverage census, from the REPORTS (never from byte counts; 42) ------
echo "=== 3. coverage census"
python3 - "$MOD_DIR" "${ORDER[@]}" <<'PY' || exit 1
import glob, json, os, sys
mod_dir, rungs = sys.argv[1], sys.argv[2:]
# Stated HERE, independently of what the build script asked the patcher for.
WANT = {
    'bda-ctl':      dict(ctl=True),
    'bda-probe':    dict(mode='probe', painted=76, writes=151, declined=1,
                         refetched=0),
    'bda-rq-probe': dict(mode='rq', painted=75, writes=150, declined=2,
                         refetched=30, flags=517, mask=255, tmin=0.05, tmax=3.0,
                         space='camera_relative', campos_member=0),
}
SENT, MAGIC = 'ca1157000bda0001', 'ca115701'
bad = []
for r in rungs:
    d = os.path.join(mod_dir, 'swaps.' + r)
    want = WANT[r]
    mods = painted = writes = dec = refet = skip = 0
    ids = set()
    for f in sorted(glob.glob(os.path.join(d, '*.bda.report.json'))):
        rep = json.load(open(f))[0]
        q = rep['bda']
        mods += 1
        if rep.get('spirv_val') != 'clean':
            bad.append((r, rep['module'], 'spirv-val not clean'))
        if q.get('decoy'):
            bad.append((r, rep['module'], 'a DECOY build reached a rung'))
        if want.get('ctl'):
            if q.get('emitted', 0) != 0 or not q.get('control'):
                bad.append((r, rep['module'], 'the control emitted instructions'))
            continue
        if q['declined']:
            dec += 1
            continue
        painted += 1
        writes += len(q['writes'])
        refet += len(q['refetched'])
        skip += len(q['skipped'])
        if q['mode'] != want['mode']:
            bad.append((r, rep['module'], 'mode %s' % q['mode']))
        if q['sentinel'] != SENT or q['magic'] != MAGIC:
            bad.append((r, rep['module'], 'sentinel/magic is not this build'))
        if q['slot_members'] != 8:
            bad.append((r, rep['module'], 'slot is not 8 words'))
        if q['lo_id'] is None or q['hi_id'] is None or q['lo_id'] == q['hi_id']:
            bad.append((r, rep['module'], 'the marker ids are not a distinct pair'))
        if q['sentinel_pairs'] != 1:
            bad.append((r, rep['module'],
                        '%d sentinel copies -- a value scan would be ambiguous'
                        % q['sentinel_pairs']))
        ids.add((q['lo_id'], q['hi_id']))
        if want['mode'] == 'rq':
            for k in ('flags', 'mask', 'tmin', 'tmax', 'space', 'campos_member'):
                if q[k] != want[k]:
                    bad.append((r, rep['module'], '%s %s != %s' % (k, q[k], want[k])))
            if q['cbv_slot'] != [0, 12]:
                bad.append((r, rep['module'], 'view CBV is not registers[0]+12'))
            if q['matrix_members'] != [69, 70, 71, 72]:
                bad.append((r, rep['module'], 'matrix members are not 69..72'))
    if mods != 77:
        bad.append((r, '-', '%d patched modules, want 77' % mods))
    if want.get('ctl'):
        print('  %-14s 77 modules, 0 instructions emitted (the identity control)' % r)
        continue
    for k, got in (('painted', painted), ('writes', writes),
                   ('declined', dec), ('refetched', refet)):
        if got != want[k]:
            bad.append((r, '-', '%s %d != %d' % (k, got, want[k])))
    if skip:
        bad.append((r, '-', '%d writes skipped; the census expects none' % skip))
    print('  %-14s %d painted modules, %d declined by name, %d painted writes '
          '(%d site-local refetches), %d distinct marker id pairs'
          % (r, painted, dec, writes, refet, len(ids)))
if bad:
    for b in bad[:12]:
        sys.stderr.write('    %s :: %s :: %s\n' % b)
    sys.exit(1)
PY

# --- 4. instruction census on the SHIPPED bytes -----------------------------
echo "=== 4. instruction census on the SHIPPED bytes"
python3 - "$MOD_DIR" "$SRC" "${ORDER[@]}" <<'PY' || exit 1
import glob, os, re, subprocess, sys
mod_dir, src, rungs = sys.argv[1], sys.argv[2], sys.argv[3:]
sys.path.insert(0, os.path.join(mod_dir, 'dev'))
from verify_bda import binary_marker
WANT_RQ = {'bda-rq-probe': True}
bad = []
def dis(p):
    return subprocess.run(['spirv-dis', '--no-color', p],
                          capture_output=True, text=True).stdout
for r in rungs:
    ctl = r.endswith('-ctl')
    rq = r in WANT_RQ
    d = os.path.join(mod_dir, 'swaps.' + r)
    tot = dict(marker=0, sent=0, bitcast=0, init=0, proceed=0, tget=0, conv=0)
    for f in sorted(glob.glob(os.path.join(d, '*.dxil.spv'))):
        h = os.path.basename(f).split('.')[0]
        m = binary_marker(f)
        a = dis(f); b = dis(os.path.join(src, os.path.basename(f)))
        n_i = a.count('OpRayQueryInitializeKHR')
        n_p = a.count('OpRayQueryProceedKHR')
        n_t = a.count('OpRayQueryGetIntersectionTypeKHR')
        n_c = a.count('OpConvertUToAccelerationStructureKHR')
        n_b = len(re.findall(r'OpBitcast %_ptr_PhysicalStorageBuffer_', a)) \
            - len(re.findall(r'OpBitcast %_ptr_PhysicalStorageBuffer_', b))
        if ctl:
            if m['markers'] or m['n_lo'] or m['n_hi']:
                bad.append('%s/%s: the CONTROL carries a marker' % (r, h))
            if (n_i, n_p, n_t, n_c, n_b) != (0, 0, 0, 0, 0):
                bad.append('%s/%s: the CONTROL emitted instructions' % (r, h))
            continue
        if not m['markers']:
            continue                        # a module declined by name
        if len(m['markers']) != 1:
            bad.append('%s/%s: %d markers' % (r, h, len(m['markers'])))
        if (m['n_lo'], m['n_hi']) != (1, 1):
            bad.append('%s/%s: %d/%d sentinel constants, want 1/1'
                       % (r, h, m['n_lo'], m['n_hi']))
        if n_b != 1:
            bad.append('%s/%s: %d ADDED PhysicalStorageBuffer bitcasts, want 1'
                       % (r, h, n_b))
        if rq:
            if n_c != 1:
                bad.append('%s/%s: %d AS conversions, want 1' % (r, h, n_c))
            if not (n_i == n_p == n_t) or n_i == 0:
                bad.append('%s/%s: init/proceed/type %d/%d/%d' % (r, h, n_i, n_p, n_t))
            if a.count('OpRayQueryGetIntersectionTKHR'):
                bad.append('%s/%s: reads t -- this rung asks a BOOLEAN' % (r, h))
        else:
            if (n_i, n_p, n_t, n_c) != (0, 0, 0, 0):
                bad.append('%s/%s: --mode probe carries ray-query work' % (r, h))
        if a.count('OpTraceRayKHR') != b.count('OpTraceRayKHR'):
            bad.append('%s/%s: OpTraceRayKHR count changed' % (r, h))
        tot['marker'] += len(m['markers']); tot['sent'] += m['n_lo'] + m['n_hi']
        tot['bitcast'] += n_b; tot['init'] += n_i; tot['proceed'] += n_p
        tot['tget'] += n_t; tot['conv'] += n_c
    print('  %-14s %d markers, %d sentinel constants, %d added PSB bitcasts, '
          '%d Initialize, %d Proceed, %d committed-type getters, %d AS conversions'
          % (r, tot['marker'], tot['sent'], tot['bitcast'], tot['init'],
             tot['proceed'], tot['tget'], tot['conv']))
# The raygen half of every rung must be untouched: Stage 2b is a COMPUTE
# feature and the raygens already have the RTAS heap.
for r in rungs:
    for f in sorted(glob.glob(os.path.join(mod_dir, 'swaps.' + r, '*.rgs_*.spv'))):
        if binary_marker(f)['markers']:
            bad.append('%s: a RAYGEN carries the marker: %s'
                       % (r, os.path.basename(f)))
if bad:
    for b in bad[:12]:
        sys.stderr.write('    ' + b + '\n')
    sys.exit(1)
PY

# --- 5. the identity control, over the WHOLE set ----------------------------
echo "=== 5. bda-ctl identity"
d=0
for f in "$SRC"/*.spv; do
    cmp -s "$f" "$MOD_DIR/swaps.bda-ctl/$(basename "$f")" || d=$((d+1))
done
[[ "$d" == 0 ]] || { echo "  !! bda-ctl differs from the base on $d files" >&2; exit 1; }
echo "  bda-ctl: 93 of 93 byte-identical to $BASE"
for pair in "bda-probe 76" "bda-rq-probe 75"; do
    set -- $pair; d=0
    for f in "$SRC"/*.spv; do
        cmp -s "$f" "$MOD_DIR/swaps.$1/$(basename "$f")" || d=$((d+1))
    done
    [[ "$d" == "$2" ]] || { echo "  !! $1 differs from the base on $d of 93 files, want $2" >&2; exit 1; }
    echo "  $1: $2 of 93 differ (all compute; the 16 raygens are verbatim)"
done

# --- 6. the verifier, on the shipped bytes ---------------------------------
echo "=== 6. verify_bda.py on the shipped .spv"
python3 "$VERIFY" "$MOD_DIR/swaps.bda-probe"    --mode probe
python3 "$VERIFY" "$MOD_DIR/swaps.bda-rq-probe" --mode rq
python3 "$VERIFY" --negative "$SRC"
python3 "$VERIFY" --negative "$MOD_DIR/swaps.bda-ctl"

# --- 7. verifier NON-VACUITY: it must REJECT every decoy -------------------
echo "=== 7. verifier non-vacuity (each of these MUST fail)"
mkdir -p "$WORK/decoy"
reject () {  # $1 = label, rest = verifier argv
    local label="$1"; shift
    if python3 "$VERIFY" "$@" >/dev/null 2>&1; then
        echo "  !! VACUOUS: the verifier ACCEPTED $label" >&2; exit 1
    fi
    echo "  rejected: $label"
}
for dec in nomarker badid scan world noflags; do
    patch_set "$WORK/decoy/$dec" --mode rq --decoy "$dec"
    cp -pf "$SRC"/*.rgs_*.spv "$WORK/decoy/$dec/"
done
reject "--decoy nomarker (the pointer, with NO marker to authorise the fixup)" \
       "$WORK/decoy/nomarker" --mode rq
reject "--decoy badid (a well-formed marker naming ids that do not exist)" \
       "$WORK/decoy/badid" --mode rq
reject "--decoy scan (a SECOND, unnamed sentinel pair -- the module on which a \
value-scanning layer would rewrite the wrong constant)" \
       "$WORK/decoy/scan" --mode rq
reject "--decoy world (raw world P as the ray origin -- 99 sec 10.6's two-spaces trap)" \
       "$WORK/decoy/world" --mode rq
reject "--decoy noflags (flags 4: no Opaque, no SkipAABBs)" \
       "$WORK/decoy/noflags" --mode rq
reject "the unpatched BASE read as a rung" "$SRC" --mode probe
reject "the bda-ctl CONTROL read as a rung" "$MOD_DIR/swaps.bda-ctl" --mode probe
reject "bda-probe read as the ray-query rung" \
       "$MOD_DIR/swaps.bda-probe" --mode rq
reject "bda-rq-probe read as the magic-only probe" \
       "$MOD_DIR/swaps.bda-rq-probe" --mode probe
reject "bda-rq-probe read against 102's contact reach (tmax 0.10 m)" \
       "$MOD_DIR/swaps.bda-rq-probe" --mode rq --tmax 0.10
reject "bda-rq-probe read against 101's flag word (545 = CullFrontFacing)" \
       "$MOD_DIR/swaps.bda-rq-probe" --mode rq --flags 545
reject "bda-probe --negative (a marker-carrying rung read as marker-free)" \
       "$MOD_DIR/swaps.bda-probe" --negative
# Parked rungs that paint class-1 skin in these same 77 compute modules, and
# the WRONG ones. Free decoys, and the strongest available.
for other in hunt-paint hunt-wpos hunt-wpos-cam; do
    if [[ -d "$INSTALL_DIR/skin.set/$other" ]]; then
        reject "$other (class-1 paint in this module family, no slot)" \
               "$INSTALL_DIR/skin.set/$other" --mode probe
    fi
done
rm -rf "$WORK/decoy"

# --- 8. the marker and the sentinels are GLOBALLY unique -------------------
# Hole 1 and hole 2 of `98` sec 10.3 are only closed if the discriminator
# discriminates. Measured over every module ever dumped, not just the base.
echo "=== 8. marker uniqueness over the whole dump"
python3 - "$MOD_DIR" "$SRC" <<'PY' || exit 1
import glob, os, struct, sys
mod_dir, src = sys.argv[1], sys.argv[2]
sys.path.insert(0, os.path.join(mod_dir, 'dev'))
from verify_bda import binary_marker
from patch_bda import MARKER, SENT_LO, SENT_HI, MAGIC
roots = [os.path.expanduser('~/callisto_dump'), src]
files = []
for r in roots:
    if os.path.isdir(r):
        files += glob.glob(os.path.join(r, '**', '*.spv'), recursive=True)
files = sorted(set(files))
if len(files) < 500:
    print('  !! only %d dumped modules found; the uniqueness claim needs the '
          'dump' % len(files), file=sys.stderr)
    sys.exit(1)
hit_m = hit_s = bad = 0
for f in files:
    try:
        m = binary_marker(f)
    except Exception:
        bad += 1
        continue
    hit_m += len(m['markers'])
    hit_s += m['n_lo'] + m['n_hi']
print('  %d modules scanned (%d unreadable): %d carry `%s`, %d carry either '
      'sentinel half as an OpConstant %%uint' % (len(files), bad, hit_m, MARKER, hit_s))
print('  sentinel = 0x%016x  (lo 0x%08x = %d, hi 0x%08x = %d), magic = 0x%08x'
      % ((SENT_HI << 32) | SENT_LO, SENT_LO, SENT_LO, SENT_HI, SENT_HI, MAGIC))
if hit_m or hit_s:
    sys.exit(1)
PY

# --- 9. the fixup site survives an arbitrary address -----------------------
# The layer rewrites two literal words in place. If either constant were
# referenced by something that constrains its value (a SpecId, an array
# length, a switch label) the rewrite would produce an INVALID module on the
# device and nothing would say so. Simulate the rewrite with a plausible
# 64-bit BAR address and re-validate every shipped module.
echo "=== 9. simulated fixup: rewrite both literals, re-validate"
python3 - "$MOD_DIR" "${ORDER[@]}" <<'PY' || exit 1
import glob, os, struct, subprocess, sys, tempfile
mod_dir, rungs = sys.argv[1], sys.argv[2:]
sys.path.insert(0, os.path.join(mod_dir, 'dev'))
from patch_bda import SENT_LO, SENT_HI
ADDR = 0x00007F1234567000            # a plausible host-visible device address
lo, hi = ADDR & 0xffffffff, ADDR >> 32
n_done = 0
bad = []
for r in rungs:
    if r.endswith('-ctl'):
        continue
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
            continue                                  # declined by name
        if hits != 2:
            bad.append('%s/%s: %d literals rewritten, want 2'
                       % (r, os.path.basename(f), hits))
            continue
        with tempfile.NamedTemporaryFile(suffix='.spv', delete=False) as t:
            t.write(bytes(b)); p = t.name
        v = subprocess.run(['spirv-val', '--target-env', 'vulkan1.4', p],
                           capture_output=True, text=True)
        os.unlink(p)
        if v.returncode != 0:
            bad.append('%s/%s: INVALID after the fixup: %s'
                       % (r, os.path.basename(f), v.stderr.splitlines()[:1]))
        n_done += 1
print('  %d modules rewritten to addr 0x%016x and re-validated clean '
      '(spirv-val --target-env vulkan1.4)' % (n_done, ADDR))
if bad:
    for x in bad[:8]:
        sys.stderr.write('    ' + x + '\n')
    sys.exit(1)
PY

# --- 10. MANIFEST provenance ------------------------------------------------
echo "=== 10. MANIFEST provenance"
for r in "${ORDER[@]}"; do
    dest="$MOD_DIR/swaps.$r"
    sed -e "1s/^$BASE /$r /" "$SRC/MANIFEST.txt" > "$dest/MANIFEST.txt"
    grep -q "^$r " "$dest/MANIFEST.txt" || { echo "MANIFEST rewrite failed for $r" >&2; exit 1; }
    {
      echo "# bda (handoff/103): Stage 2b -- a 64-bit TLAS device address delivered"
      echo "# to a COMPUTE resolver through a layer-owned 256-byte slot, read via"
      echo "# PhysicalStorageBuffer with NO Int64 capability (the game's own idiom)."
      echo "# The module carries OpString \"CALLISTO_BDA_SLOT_V1 lo=%<id> hi=%<id>"
      echo "# sent=ca1157000bda0001 magic=ca115701\"; swap_layer.c rewrites those two"
      echo "# OpConstant %uint literals to the slot's address at vkCreateShaderModule."
      echo "# THESE RUNGS REQUIRE THAT LAYER. Without it the address is the sentinel"
      echo "# and the shader would fault: the layer REJECTS a marker-carrying overlay"
      echo "# it cannot fix up, and falls through to the NEXT overlay (98 sec 7.2)."
      case "$r" in
        *-ctl)      echo "# THIS RUNG IS THE BASE, BYTE FOR BYTE. Control for the selector." ;;
        *-rq-probe) echo "# STAGE 2c: + one inline ray query per painted write, from P - C" \
                         "(99 sec 10.6), straight up, flags 517, tmin 5cm, tmax 3m." \
                         "Skin: BLUE = committed hit, AMBER = miss, RED = magic wrong." ;;
        *)          echo "# STAGE 2b: skin GREEN = slot word 0 == magic, RED = it does not." ;;
      esac
      echo "# Prove the layer first: make layer && ./dev/selftest_bda.sh"
      echo "# A/B against $BASE."
    } >> "$dest/MANIFEST.txt"
done
echo "  3 MANIFESTs written, provenance (src_ser/ser_sha/ptq_sha) carried verbatim"

echo
echo "=== shas (content = cat of all 93 .spv in name order)"
setsha () {  # cat every matching file in name order -> one sha
    # NB: -print0/sort -z/xargs -0. The repo path contains a space, so
    # `ls | xargs cat` hashes NOTHING (e3b0c442..., the empty string).
    find "$1" -maxdepth 1 -name "$2" -print0 | sort -z |
        xargs -0 cat | sha256sum | cut -c1-16
}
for r in "${ORDER[@]}"; do
    printf '  %-14s content=%s  compute-half=%s\n' "$r" \
        "$(setsha "$MOD_DIR/swaps.$r" '*.spv')" \
        "$(setsha "$MOD_DIR/swaps.$r" '*.dxil.spv')"
done
printf '  %-14s content=%s  compute-half=%s\n' "(base)" \
    "$(setsha "$SRC" '*.spv')" "$(setsha "$SRC" '*.dxil.spv')"

if (( DO_INSTALL )); then
    for r in "${ORDER[@]}"; do
        park="$INSTALL_DIR/skin.set/$r"
        # NEW names only. Never touch a parked dir this script did not make.
        if [[ -d "$park" && ! -f "$park/.bda-owned" ]]; then
            echo "  !! $park exists and was not created by build_bda.sh -- refusing" >&2
            exit 1
        fi
        mkdir -p "$park"; touch "$park/.bda-owned"
        rm -f "$park"/*.spv "$park"/*.json "$park/MANIFEST.txt"
        cp -pf "$MOD_DIR/swaps.$r"/*.spv "$MOD_DIR/swaps.$r"/*.json \
               "$MOD_DIR/swaps.$r/MANIFEST.txt" "$park/"
        n=$(ls "$park"/*.spv | wc -l)
        [[ "$n" == 93 ]] || { echo "  !! parked $r has $n modules" >&2; exit 1; }
        for f in "$MOD_DIR/swaps.$r"/*.spv; do
            cmp -s "$f" "$park/$(basename "$f")" \
                || { echo "  !! parked $r differs from the build: $(basename "$f")" >&2; exit 1; }
        done
        echo "  parked -> $park (93 modules, cmp-verbatim against the build)"
    done
fi
