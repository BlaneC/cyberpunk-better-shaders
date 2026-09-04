#!/usr/bin/env bash
# bump: albedo-derived micro-normal on skin, in the 77 compute resolvers.
# handoff/115.
#
#   ./dev/build_bump.sh                 # build + verify (no install)
#   ./dev/build_bump.sh --install       # ALSO park the four rungs in skin.set/
#   ./dev/build_bump.sh --stack --install   # ALSO park the selectable STACK
#                                       #   <base>-bump (= bump, long name)
#   ./dev/build_bump.sh --height 0.02 --name bump2 --install
#
# Pores are not in the BVH (33, 38 sec 0d), so no ray budget creates a pore
# micro-shadow.  The skin ALBEDO already carries them, painted dark, and the
# shipped micro-shadowing (44 sec 3.4) reads that darkness as a scalar
# occlusion.  This reads its GRADIENT as geometry: h = H * L(albedo), and
#
#     N' = normalize(N - H * grad_t L)
#
# tilts the shading normal every lighting term reads -- the diffuse N.L, the
# specular N.H / N.V, the c1 lobes, the terminator bleed's NoL.  A pore then
# darkens on its lit rim, brightens on its far rim, and BREAKS UP the oil
# highlight, which is what a real pore does.  The gradient comes from three
# albedo taps (centre, +1 x, +1 y) converted to luma/m by the same two depth
# taps 109's curvature estimator already measures.  Three safeguards: an
# edge-kill band (a lip line is an albedo edge, not a pore), a tilt clamp
# (26.6 deg), and 109's silhouette guard.  H = 0 emits nothing.
#
# Rungs built:
#   bump        H = 10 mm/luma: a 0.02-luma pore across 1 mm tilts 11 deg
#   bump-hi     H = 20 mm/luma: twice the relief
#   bump-vis    the diagnostic: |d'|/DMAX painted blue(flat) -> green ->
#               red(clamped) on class-1 pixels only, white where the guard
#               fired, modulated by scene luminance
#   bump-ctl    H = 0: 93 of 93 modules `cmp`-identical to the base, non-
#               tautologically (gate 3 proves dis -> as byte-neutral first)
#   (scratch) noguard, noband: full coverage with one safeguard removed --
#               the decoys the verifier MUST reject.
set -euo pipefail

MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="${CALLISTO_INSTALL_DIR:-$HOME/.local/lib/callisto}"
PY="$MOD_DIR/dev/patch_bump.py"
VERIFY="$MOD_DIR/dev/verify_bump.py"
MODEL="$MOD_DIR/dev/bump_model.py"

BASE=gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog-earglow-cap6-glintdense-curv-t7hue1-ll
NAME=bump
DO_INSTALL=0
DO_STACK=0
HEIGHT=0.010
HEIGHT_HI=0.020
T0=0.05
T1=0.12
DMAX=0.5
JUMP=0.05
STEP=1
while (( $# )); do
    case "$1" in
        --install)   DO_INSTALL=1 ;;
        --stack)     DO_STACK=1 ;;
        --base)      BASE="${2:?--base needs a skin.set name}"; shift ;;
        --name)      NAME="${2:?--name needs a rung name}"; shift ;;
        --height)    HEIGHT="${2:?--height needs m/luma}"; shift ;;
        --height-hi) HEIGHT_HI="${2:?--height-hi needs m/luma}"; shift ;;
        --t0)        T0="${2:?--t0 needs luma}"; shift ;;
        --t1)        T1="${2:?--t1 needs luma}"; shift ;;
        --dmax)      DMAX="${2:?--dmax needs tan}"; shift ;;
        --jump)      JUMP="${2:?--jump needs metres}"; shift ;;
        --step)      STEP="${2:?--step needs texels}"; shift ;;
        *) echo "unknown arg $1" >&2; exit 1 ;;
    esac
    shift
done
KNOBS=(--t0 "$T0" --t1 "$T1" --dmax "$DMAX" --jump "$JUMP" --step "$STEP")

SRC="$INSTALL_DIR/skin.set/$BASE"
WORK="$MOD_DIR/dev/disasm/bump"
declare -A OUT=( [bump]="$MOD_DIR/swaps.bump"
                 [hi]="$MOD_DIR/swaps.bump.hi"
                 [vis]="$MOD_DIR/swaps.bump.vis"
                 [ctl]="$MOD_DIR/swaps.bump.ctl" )

# --- 0. base provenance ----------------------------------------------------
echo "--- 0. base provenance ($BASE) ---"
[[ -f "$SRC/MANIFEST.txt" ]] || { echo "no $SRC/MANIFEST.txt -- the standing selection is not parked" >&2; exit 1; }
grep -q 'src_ser=' "$SRC/MANIFEST.txt" || { echo "$BASE's MANIFEST carries no src_ser= provenance; sync_settings would refuse the rungs" >&2; exit 1; }
n_c=$(ls "$SRC"/*.dxil.spv | wc -l)
n_r=$(ls "$SRC"/*.rgs_*.spv | wc -l)
[[ "$n_c" == 77 ]] || { echo "$BASE has $n_c compute modules, expected 77" >&2; exit 1; }
[[ "$n_r" == 16 ]] || { echo "$BASE has $n_r raygen modules, expected 16" >&2; exit 1; }
echo "  77 compute + 16 raygen (12 rgs_reference_main + 4 rgs_restirgi_*)"
[[ "$(ls "$SRC"/*.rgs_reference_main.spv | wc -l)" == 12 ]] || { echo "not 12 rgs_reference_main" >&2; exit 1; }
[[ "$(ls "$SRC"/*.rgs_restirgi_*.spv | wc -l)" == 4 ]] || { echo "not 4 rgs_restirgi_*" >&2; exit 1; }

# --- 1. the offline model gates itself -------------------------------------
echo "--- 1. offline model (dev/bump_model.py) ---"
python3 "$MODEL" | tail -3

# --- 2. disassemble --------------------------------------------------------
rm -rf "$WORK"; mkdir -p "$WORK/asm" "$WORK/rt"
for k in bump hi vis ctl noguard noband; do mkdir -p "$WORK/$k"; done
jobs="${CALLISTO_JOBS:-$(nproc 2>/dev/null || echo 4)}"
ls "$SRC"/*.dxil.spv | xargs -P "$jobs" -I{} bash -c \
    'n=$(basename "$1" .dxil.spv); spirv-dis "$1" -o "'"$WORK"'/asm/$n.spvasm"' _ {}
[[ "$(ls "$WORK/asm" | wc -l)" == 77 ]] || { echo "disassembly lost modules" >&2; exit 1; }

# --- 3. the pipeline is byte-neutral, at each module's OWN version ----------
echo "--- 3. round-trip neutrality (dis -> as == base bytes) ---"
same=0
for a in "$WORK"/asm/*.spvasm; do
    n="$(basename "${a%.spvasm}")"
    ver=$(sed -n 's/^; Version: \([0-9]*\)\.\([0-9]*\).*/spv\1.\2/p' "$a" | head -1)
    [[ -n "$ver" ]] || { echo "  !! $n has no '; Version:' header" >&2; exit 1; }
    spirv-as --target-env "$ver" "$a" -o "$WORK/rt/$n.spv"
    cmp -s "$SRC/$n.dxil.spv" "$WORK/rt/$n.spv" || { echo "  !! $n does not round-trip -- the control would be meaningless" >&2; exit 1; }
    same=$((same+1))
done
echo "  $same of 77 modules round-trip byte-identically at their own version"
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
                : > "$CB_OUT/.ok.$n"
            else
                : > "$CB_OUT/.bad.$n"
            fi' _
    rm -f "$WORK/.args"
}
echo "--- 4. patch ---"
patch_all "$WORK/bump"    --tier feature --height "$HEIGHT"    "${KNOBS[@]}"
patch_all "$WORK/hi"      --tier feature --height "$HEIGHT_HI" "${KNOBS[@]}"
patch_all "$WORK/vis"     --tier vis     --height "$HEIGHT"    "${KNOBS[@]}"
patch_all "$WORK/ctl"     --tier feature --height 0.0
patch_all "$WORK/noguard" --tier feature --height "$HEIGHT" "${KNOBS[@]}" --no-guard
patch_all "$WORK/noband"  --tier feature --height "$HEIGHT" "${KNOBS[@]}" --no-band

# --- 5. coverage, from the reports, never from byte counts -----------------
echo "--- 5. coverage ---"
python3 - "$MOD_DIR" "$WORK" "$HEIGHT" "$HEIGHT_HI" "$T0" "$T1" "$DMAX" "$JUMP" "$STEP" <<'PY' || exit 1
import glob, json, os, sys
sys.path.insert(0, os.path.join(sys.argv[1], 'dev'))
import patch_bump as PB
W = sys.argv[2]
height, height_hi = float(sys.argv[3]), float(sys.argv[4])
t0, t1, dmax, jump, step = (float(sys.argv[5]), float(sys.argv[6]),
                            float(sys.argv[7]), float(sys.argv[8]), int(sys.argv[9]))
C = PB.CENSUS
bad = []


def scan(d):
    badm = {os.path.basename(f)[5:] for f in glob.glob(os.path.join(d, '.bad.*'))}
    rows = []
    for f in sorted(glob.glob(os.path.join(d, '.*.json'))):
        if os.path.basename(f).startswith(('.ok.', '.bad.')):
            continue
        if os.path.getsize(f) == 0:          # a declined module writes nothing
            continue
        r = json.load(open(f))[0]
        if r.get('spirv_val') != 'clean':
            bad.append((r.get('module'), 'spirv-val not clean'))
        rows.append(r)
    return badm, rows


for rung, h, tier, guard, band in (('bump', height, 'feature', True, True),
                                   ('hi', height_hi, 'feature', True, True),
                                   ('noguard', height, 'feature', False, True),
                                   ('noband', height, 'feature', True, False),
                                   ('vis', height, 'vis', True, True)):
    badm, rows = scan(os.path.join(W, rung))
    if badm != PB.KNOWN_DECLINE:
        bad.append((rung, 'declines are %s, expected exactly %s'
                    % (sorted(badm), sorted(PB.KNOWN_DECLINE))))
    anchors, modes, instr, refetch, writes, skipped = set(), {'phi': 0, 'raw': 0}, [], 0, 0, 0
    for r in rows:
        p = r['bump']
        if p['tier'] != tier:
            bad.append((r['dxil'], 'wrong tier'))
        anchors.add(json.dumps([p['matrix'], p['cbv_slot'], p['depth_slot'],
                                p['normal_slot'], p['albedo_slot'], p['height'],
                                p['t0'], p['t1'], p['dmax'], p['jump'], p['step'],
                                p['guard'], p['band']]))
        if tier == 'feature':
            modes[p['mode']] += 1
            instr.append(p['bump_instructions'])
            refetch += bool(p['centre_pos_refetched'])
            for k in range(3):
                if p['uses_rewritten'][k] < p['uses_before'][k] - p['curv_taps_kept'][k]:
                    bad.append((r['dxil'], 'component %d: %d of %d uses rewritten'
                                % (k, p['uses_rewritten'][k], p['uses_before'][k])))
            want_taps = 2 if p['mode'] == 'raw' else 0
            if p['curv_taps_kept'] != [want_taps] * 3:
                bad.append((r['dxil'], 'curvature taps kept %s in a %s module'
                            % (p['curv_taps_kept'], p['mode'])))
        else:
            writes += len(p['writes'])
            skipped += len(p['skipped'])
            refetch += len(p['centre_pos_refetched'])
    if len(rows) != C['patched_modules']:
        bad.append((rung, '%d patched modules, census says %d'
                    % (len(rows), C['patched_modules'])))
    if len(anchors) != 1:
        bad.append((rung, 'modules disagree on anchors/knobs: %d distinct'
                    % len(anchors)))
    else:
        a = json.loads(sorted(anchors)[0])
        if a[:5] != [C['matrix_members'], C['cbv_slot'], C['depth_slot'],
                     C['normal_slot'], C['albedo_slot']]:
            bad.append((rung, 'anchors moved: %s' % (a[:5],)))
        if a[5:11] != [h, t0, t1, dmax, jump, step]:
            bad.append((rung, 'knobs are %s, asked for %s'
                        % (a[5:11], [h, t0, t1, dmax, jump, step])))
        if a[11] != guard or a[12] != band:
            bad.append((rung, 'guard/band flags are %s/%s' % (a[11], a[12])))
    if tier == 'feature':
        if (modes['phi'], modes['raw']) != (C['phi_modules'], C['raw_modules']):
            bad.append((rung, 'phi/raw split %s, census %d/%d'
                        % (modes, C['phi_modules'], C['raw_modules'])))
        if min(instr) != max(instr):
            bad.append((rung, 'block size varies: %d..%d' % (min(instr), max(instr))))
        print('  %-8s: %d modules, %d declined, %d phi + %d raw, %d instr/module,'
              ' centre P refetched %d'
              % (rung, len(rows), len(badm), modes['phi'], modes['raw'], instr[0], refetch))
    else:
        if writes != C['writes']:
            bad.append((rung, '%d writes, census says %d' % (writes, C['writes'])))
        if skipped:
            bad.append((rung, '%d writes skipped inside patched modules' % skipped))
        print('  %-8s: %d modules, %d declined, %d writes painted (%d refetched P),'
              ' %d skipped' % (rung, len(rows), len(badm), writes, refetch, skipped))

badc, rowsc = scan(os.path.join(W, 'ctl'))
sc = sum(sum(r['bump']['uses_rewritten']) for r in rowsc)
print('  ctl     : %d modules emitted, %d declined, %d uses rewritten'
      % (len(rowsc), len(badc), sc))
if len(rowsc) != C['modules'] or badc:
    bad.append(('ctl', 'emitted %d modules, declined %s; want %d / none'
                % (len(rowsc), sorted(badc), C['modules'])))
if sc:
    bad.append(('ctl', 'the H=0 control rewrote %d uses' % sc))

if bad:
    for m, why in bad[:12]:
        sys.stderr.write('    %s :: %s\n' % (m, why))
    sys.exit(1)
print('  declined by name: %s' % ', '.join(sorted(PB.KNOWN_DECLINE)))
print('  anchors single-valued: matrix cbv[reg0+12][69..72], depth registers[1]+0,'
      ' albedo registers[1]+1, normal registers[1]+2')
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
    # COMPUTE-ONLY, asserted: every raygen is base bytes.
    for f in "$SRC"/*.rgs_*.spv; do
        cmp -s "$f" "$dest/$(basename "$f")" || { echo "raygen $(basename "$f") differs from $BASE -- this rung is not compute-only" >&2; exit 1; }
    done
    for h in $(python3 -c 'import sys;sys.path.insert(0,"'"$MOD_DIR"'/dev");import patch_bump;print(" ".join(sorted(patch_bump.KNOWN_DECLINE)))'); do
        cmp -s "$SRC/$h.dxil.spv" "$dest/$h.dxil.spv" || { echo "declined module $h is not base bytes" >&2; exit 1; }
    done
    for f in "$dest"/*.spv; do
        spirv-val --target-env vulkan1.4 "$f" >/dev/null || { echo "spirv-val FAILED: $f" >&2; exit 1; }
    done
}
echo "--- 6. assemble (16/16 raygen + 2/2 declined cmp-identical, spirv-val vulkan1.4) ---"
for k in bump hi vis ctl; do assemble "${OUT[$k]}" "$WORK/$k"; done
NOG="$WORK/rung.noguard"; assemble "$NOG" "$WORK/noguard"
NOB="$WORK/rung.noband";  assemble "$NOB" "$WORK/noband"

for k in bump hi vis; do
    d=0; for f in "$SRC"/*.dxil.spv; do cmp -s "$f" "${OUT[$k]}/$(basename "$f")" || d=$((d+1)); done
    echo "  $k: $d of 77 compute modules differ from $BASE"
    [[ "$d" == 75 ]] || { echo "  !! expected exactly 75 (the census)" >&2; exit 1; }
done
d=0; for f in "$SRC"/*.spv; do cmp -s "$f" "${OUT[ctl]}/$(basename "$f")" || d=$((d+1)); done
echo "  ctl: $d of 93 modules differ from $BASE"
[[ "$d" == 0 ]] || { echo "  !! the H=0 control is NOT byte-identical to the base" >&2; exit 1; }
for pair in "bump:hi" "bump:vis" "hi:vis" "bump:$NOG" "bump:$NOB"; do
    a="${pair%%:*}"; b="${pair##*:}"
    [[ "$b" == /* ]] || b="${OUT[$b]}"
    d=0; for f in "${OUT[$a]}"/*.spv; do cmp -s "$f" "$b/$(basename "$f")" || d=$((d+1)); done
    echo "  $a vs $(basename "$b"): $d of 93 differ"
    [[ "$d" -gt 0 ]] || { echo "  !! two rungs are byte-identical" >&2; exit 1; }
done

# --- 7. the verifier, on shipped bytes, proven non-vacuous -----------------
echo "--- 7. verifier (shipped bytes) ---"
python3 "$VERIFY" "${OUT[bump]}" --height "$HEIGHT"    "${KNOBS[@]}"
python3 "$VERIFY" "${OUT[hi]}"   --height "$HEIGHT_HI" "${KNOBS[@]}"
reject () {   # $1 = label, rest = verifier args
    local label="$1"; shift
    if python3 "$VERIFY" "$@" >/dev/null 2>&1; then
        echo "  !! the verifier ACCEPTS $label -- it is vacuous" >&2; exit 1; fi
    echo "  rejected: $label"
}
reject "the unpatched base"            "$SRC"          --height "$HEIGHT" "${KNOBS[@]}"
reject "the H=0 control"               "${OUT[ctl]}"   --height "$HEIGHT" "${KNOBS[@]}"
reject "the diagnostic read as bump"   "${OUT[vis]}"   --height "$HEIGHT" "${KNOBS[@]}"
reject "the NO-SILHOUETTE-GUARD decoy" "$NOG"          --height "$HEIGHT" "${KNOBS[@]}"
reject "the NO-EDGE-BAND decoy"        "$NOB"          --height "$HEIGHT" "${KNOBS[@]}"
reject "bump read as bump-hi"          "${OUT[bump]}"  --height "$HEIGHT_HI" "${KNOBS[@]}"
reject "bump-hi read as bump"          "${OUT[hi]}"    --height "$HEIGHT" "${KNOBS[@]}"
reject "a wrong band edge"             "${OUT[bump]}"  --height "$HEIGHT" --t0 "$T0" --t1 0.2 --dmax "$DMAX" --jump "$JUMP" --step "$STEP"
reject "a wrong tilt clamp"            "${OUT[bump]}"  --height "$HEIGHT" --t0 "$T0" --t1 "$T1" --dmax 1.0 --jump "$JUMP" --step "$STEP"
reject "a wrong silhouette threshold"  "${OUT[bump]}"  --height "$HEIGHT" --t0 "$T0" --t1 "$T1" --dmax "$DMAX" --jump 0.02 --step "$STEP"
reject "a wrong neighbour step"        "${OUT[bump]}"  --height "$HEIGHT" --t0 "$T0" --t1 "$T1" --dmax "$DMAX" --jump "$JUMP" --step 2
reject "bump read as unguarded"        "${OUT[bump]}"  --height "$HEIGHT" "${KNOBS[@]}" --no-guard
reject "bump read as unbanded"         "${OUT[bump]}"  --height "$HEIGHT" "${KNOBS[@]}" --no-band

# --- 8. the diagnostic rung, read back off its own bytes ------------------
echo "--- 8. bump-vis is class-gated and leaves every non-skin pixel alone ---"
python3 - "$MOD_DIR" "${OUT[vis]}" "$SRC" <<'PY' || exit 1
import glob, os, re, subprocess, sys, tempfile
sys.path.insert(0, os.path.join(sys.argv[1], 'dev'))
from patch_chs_brdf import load_lenient
import wpos_core as W
from patch_bump import KNOWN_DECLINE, CENSUS
vis, src = sys.argv[2], sys.argv[3]
tmp = tempfile.mkdtemp(prefix='bump_vis.')
bad = []


def dis(path, tag):
    a = os.path.join(tmp, tag + '.spvasm')
    subprocess.run(['spirv-dis', path, '-o', a], check=True, capture_output=True)
    mod, _ = load_lenient(a)
    return mod, W.defs_index(mod)


def texels(mod):
    out = []
    for t in mod.lines:
        m = re.match(r'\s*OpImageWrite (%\w+) (%\w+) (%\w+)', t)
        if m:
            out.append(m.group(3))
    return out


def comps(mod, tex):
    _, d = mod.find_def(tex)
    m = re.match(r'OpCompositeConstruct %v4float (%\w+) (%\w+) (%\w+) (%\w+)',
                 d or '')
    return list(m.groups()[:3]) if m else None


def slice_sig(mod, D, roots):
    seen, stack, sig = set(), list(roots), []
    while stack:
        i = stack.pop()
        if i in seen or i not in D:
            continue
        seen.add(i)
        t = D[i][1].strip()
        sig.append(re.sub(r'%\d+\b', '%_', t))
        for o in re.findall(r'%\w+', t):
            stack.append(o)
    return sorted(sig)


gated = 0
for f in sorted(glob.glob(os.path.join(vis, '*.dxil.spv'))):
    n = os.path.basename(f)[:-9]
    if n in KNOWN_DECLINE:
        continue
    vmod, vD = dis(f, n + '.vis')
    bmod, bD = dis(os.path.join(src, n + '.dxil.spv'), n + '.base')
    vt, bt = texels(vmod), texels(bmod)
    if len(vt) != len(bt):
        bad.append((n, 'write count changed: %d -> %d' % (len(bt), len(vt))))
        continue
    for k, (v, b) in enumerate(zip(vt, bt)):
        vc, bc = comps(vmod, v), comps(bmod, b)
        if vc is None or bc is None:
            bad.append((n, 'write %d: texel is not a v4 construct' % k))
            continue
        cond, fallback = set(), []
        for c in vc:
            _, d = vmod.find_def(c)
            m = re.match(r'OpSelect %float (%\w+) (%\w+) (%\w+)', d or '')
            if not m:
                bad.append((n, 'write %d channel is not class-gated' % k))
                break
            cond.add(m.group(1))
            fallback.append(m.group(3))
        else:
            if len(cond) != 1:
                bad.append((n, 'write %d: channels gated on %d conditions'
                            % (k, len(cond))))
                continue
            _, cd = vmod.find_def(cond.pop())
            if not re.match(r'OpIEqual %bool %\w+ %uint_1\s*$', cd or ''):
                bad.append((n, 'write %d: the gate is not `class == 1` (%s)'
                            % (k, cd)))
                continue
            if slice_sig(vmod, vD, fallback) != slice_sig(bmod, bD, bc):
                bad.append((n, 'write %d: the NON-SKIN value is not the base '
                               'value' % k))
                continue
            gated += 1
if bad:
    for m, why in bad[:12]:
        sys.stderr.write('    %s :: %s\n' % (m, why))
    sys.exit(1)
if gated != CENSUS['writes']:
    sys.exit('  !! %d gated writes, census says %d' % (gated, CENSUS['writes']))
print('  %d of %d radiance writes gate on `(gbuf.y >> 5) == 1`, and every '
      'non-skin' % (gated, CENSUS['writes']))
print('  branch is slice-identical to the base module -- the diagnostic cannot '
      'move a')
print('  non-skin pixel.')
PY

# --- 9. the shipping stack: <base>-bump ----------------------------------
# handoff/115 sec 11.  SHOT 2026-09-04 and kept -- THE DEFAULT.  The stack is
# byte-for-byte the `bump` rung under the long name.
STACK="$BASE-bump"
SDIR="$MOD_DIR/swaps.$STACK"
STACK_SHA=""
if (( DO_STACK )); then
    echo "--- 9. selectable stack ($STACK) ---"
    rm -rf "$SDIR"; mkdir -p "$SDIR"
    cp -pf "${OUT[bump]}"/*.spv "$SDIR/"
    n=$(ls "$SDIR"/*.spv | wc -l)
    [[ "$n" == 93 ]] || { echo "stack has $n modules, expected 93" >&2; exit 1; }
    d=0; for f in "$SRC"/*.rgs_*.spv; do
        cmp -s "$f" "$SDIR/$(basename "$f")" || d=$((d+1)); done
    [[ "$d" == 0 ]] || { echo "  !! $d of 16 raygens differ from $BASE" >&2; exit 1; }
    echo "  16 of 16 raygens (12 rgs_reference_main + 4 rgs_restirgi_*) cmp-verbatim from $BASE"
    python3 "$VERIFY" "$SDIR" --height "$HEIGHT" "${KNOBS[@]}" | tail -2
    for f in "$SDIR"/*.spv; do
        spirv-val --target-env vulkan1.4 "$f" >/dev/null || { echo "spirv-val FAILED: $f" >&2; exit 1; }
    done
    STACK_SHA=$(cat "$SDIR"/*.spv | sha256sum | cut -c1-16)
    echo "  content sha $STACK_SHA   (base was $(cat "$SRC"/*.spv | sha256sum | cut -c1-16))"
fi

# --- 10. MANIFESTs ---------------------------------------------------------
# The base's line 1 is "<name> (ALIAS of ...)"; the `# src:` line carries the
# ser/ptq provenance sync_settings.sh insists on, and its compute=77(...) tag
# is extended so the compute half's lineage stays readable.
manifest () {   # $1 = dest, $2 = rung name, $3 = tail comment
    sed -e "1s/^$BASE /$2 /" -e "1s/(ALIAS of [^)]*)/(= $BASE + handoff\/115 albedo bump)/" \
        -e "s/compute=77(\([^)]*\))/compute=77(\1+$2)/" \
        "$SRC/MANIFEST.txt" > "$1/MANIFEST.txt"
    grep -q "^$2 " "$1/MANIFEST.txt" || { echo "MANIFEST rewrite failed" >&2; exit 1; }
    grep -q 'src_ser=' "$1/MANIFEST.txt" || { echo "MANIFEST lost its provenance" >&2; exit 1; }
    echo "# $3" >> "$1/MANIFEST.txt"
}
manifest "${OUT[bump]}" "$NAME" "albedo-derived micro-normal (handoff/115): N' = normalize(N - ${HEIGHT}*grad_t L(albedo)) from 3 albedo taps (registers[1]+1) and 2 depth taps at +${STEP} texel, replacing the shading normal at its class-switch phi (68 modules) or raw decode (7) in 75 of 77 compute modules; edge-kill band [${T0}, ${T1}] luma/texel, tilt clamp ${DMAX}, silhouette fallback |dP| > ${JUMP} m. Class-1 pixels only. Raygens are $BASE bytes. USER VERDICT 2026-09-04: best thing tested so far, IT LOOKS INCREDIBLE; the DEFAULT stack is these bytes."
manifest "${OUT[hi]}" "$NAME-hi" "bump at H = ${HEIGHT_HI} m/luma: twice the relief of bump, same band, clamp and guard. UNSHOT. See handoff/115 sec 3."
manifest "${OUT[vis]}" "$NAME-vis" "bump DIAGNOSTIC: |d'|/${DMAX} painted at all 150 radiance writes as blue(flat) -> green -> red(clamped), white where the silhouette guard fired, on class-1 pixels ONLY, modulated by scene luminance. Not a shipping rung. See handoff/115 sec 7."
manifest "${OUT[ctl]}" "$NAME-ctl" "bump CONTROL (H = 0): 93 of 93 modules byte-identical to $BASE. Selecting it must be indistinguishable from the base."
if (( DO_STACK )); then
    sed -e "1s/^$BASE /$STACK /" \
        -e "1s/(ALIAS of [^)]*)/(= $BASE + handoff\/115 albedo-derived micro-normal at H=$HEIGHT)/" \
        -e "s/compute=77(\([^)]*\))/compute=77(\1+bump)/" \
        "$SRC/MANIFEST.txt" > "$SDIR/MANIFEST.txt"
    grep -q "^$STACK " "$SDIR/MANIFEST.txt" || { echo "MANIFEST rewrite failed" >&2; exit 1; }
    grep -q 'src_ser=' "$SDIR/MANIFEST.txt" || { echo "MANIFEST lost its provenance" >&2; exit 1; }
    cat >> "$SDIR/MANIFEST.txt" <<EOF
# STACKED (handoff/115): the shipped default PLUS an albedo-derived
# micro-normal on skin. h = H*L(albedo), H = ${HEIGHT} m/luma; the tangential
# luma gradient from 3 albedo taps (registers[1]+1, sqrt decode, Rec.709) at
# (x,y), (x+${STEP},y), (x,y+${STEP}) over the metric dP of 2 depth taps tilts the
# shading normal: N' = normalize(N - H*grad_t L), |tilt| <= atan(${DMAX}).
# Replaces the normal at its class-switch phi (68 modules) or raw decode (7)
# in 75 of 77 compute modules, so the diffuse N.L, the specular N.H/N.V, the
# c1 lobes and the terminator bleed all see the pore. Edge-kill band: a
# per-texel |dL| in [${T0}, ${T1}] fades to 0 (lip lines, brows, eyeliner are
# edges, not pores). 109's curvature estimator keeps reading the RAW normal.
# Silhouette fallback: |dP| > ${JUMP} m across a texel -> N unchanged.
# 93 of 93 modules cmp-identical to skin.set/$NAME; 16 of 16 raygens are
# $BASE bytes.
# USER VERDICT 2026-09-04: 'The bump option was the best thing I've tested so
# far. IT LOOKS INCREDIBLE.' LIVE READ-OUT ONLY -- no frame was captured.
# THE DEFAULT since 2026-09-04 (handoff/115 sec 11). $BASE (= bump-ctl) is the 'before'.
# content sha $STACK_SHA
EOF
fi

echo
for k in bump hi vis ctl; do echo "  built ${OUT[$k]} (93 modules)"; done
if (( DO_INSTALL )); then
    for pair in "bump:$NAME" "hi:$NAME-hi" "vis:$NAME-vis" "ctl:$NAME-ctl"; do
        s="${OUT[${pair%%:*}]}"; n="${pair##*:}"
        park="$INSTALL_DIR/skin.set/$n"
        # NEW names only.  Never touch a parked dir this script did not create.
        if [[ -d "$park" && ! -f "$park/.built-by-build_bump" ]]; then
            echo "  !! $park exists and was not built by build_bump.sh -- refusing" >&2
            exit 1
        fi
        mkdir -p "$park"; rm -f "$park"/*.spv "$park/MANIFEST.txt"
        cp -pf "$s"/*.spv "$s/MANIFEST.txt" "$park/"
        : > "$park/.built-by-build_bump"
        echo "  parked -> $park"
    done
    if (( DO_STACK )); then
        park="$INSTALL_DIR/skin.set/$STACK"
        if [[ -d "$park" && ! -f "$park/.built-by-build_bump" ]]; then
            echo "  !! $park exists and was not built by build_bump.sh -- refusing" >&2
            exit 1
        fi
        mkdir -p "$park"; rm -f "$park"/*.spv "$park/MANIFEST.txt"
        cp -pf "$SDIR"/*.spv "$SDIR/MANIFEST.txt" "$park/"
        : > "$park/.built-by-build_bump"
        d=0; for f in "$SDIR"/*.spv; do
            cmp -s "$f" "$park/$(basename "$f")" || d=$((d+1)); done
        [[ "$d" == 0 ]] || { echo "  !! parked differs from built on $d files" >&2; exit 1; }
        echo "  parked -> $park  (parked == built, 93 of 93 cmp-verbatim, sha $STACK_SHA)"
    fi
else
    echo "NOT installed. To park: ./dev/build_bump.sh --install"
fi
(( DO_STACK )) && echo "SHIPPING STACK: skinspec=$STACK  (content sha $STACK_SHA)"
echo "select with skinspec=$NAME | $NAME-hi | $NAME-vis | $NAME-ctl;"
echo "needs ser=class + shadowset=full-shadow ($BASE's contract)"
