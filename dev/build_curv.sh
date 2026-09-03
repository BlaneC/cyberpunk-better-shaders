#!/usr/bin/env bash
# curv: curvature-driven skin scattering (Penner 2011) in the 77 compute
# resolvers.  handoff/109.
#
#   ./dev/build_curv.sh                 # build + verify (no install)
#   ./dev/build_curv.sh --install       # ALSO park the four rungs in skin.set/
#   ./dev/build_curv.sh --stack --install   # ALSO park the SHIPPING STACK
#                                       #   <base>-curv (= curv, long name)
#   ./dev/build_curv.sh --gain 1.5 --name curv15 --install
#
# The shipped terminator bleed (97 sec 3.4) hard-codes ONE diffusion band,
# `w = sat(1 - NoL/0.35)^2`, for every skin pixel: the same 0.35 on a nose
# wing (r ~ 8 mm) and on a forehead (r ~ 120 mm).  97 flags that 0.35 as a
# stylisation constant chosen because curvature was not computable.  It is
# computable: Penner's estimator is
#
#     kappa = |dN| / |dP|            [1/m]
#
# and both G-buffers are already bound in every resolver -- depth at
# registers[1]+0 and the packed normal at registers[1]+2 (handoff/99).  This
# builds it from four extra texel fetches per skin pixel and drives the band
# with it:
#
#     s = clamp(1 + g*(clamp(kappa, 0.5, 40)/10 - 1), 0.3, 2.0)
#     W  ->  W * s          (the band widens on flat skin, tightens on ridges)
#     w  ->  w * s          (and the red shift scales with it)
#
# Scaling the single value `w` reaches all THREE of its consumers, which is
# what keeps 78's luminance hold algebraically exact for any s (dev/curv_model.py
# measures the residual at 9e-8).  The specular is untouched.
#
# Rungs built:
#   curv        g = 1: literally clamp(kappa/10, 0.3, 2.0), the brief's mapping
#   curv-hi     g = 2: the same pivot, twice the contrast about the cheek
#   curv-vis    the diagnostic: kappa painted as a blue(flat) -> red(tight)
#               ramp on class-1 pixels only, modulated by scene luminance so
#               it reads independently of the shading
#   curv-ctl    g = 0: 93 of 93 modules `cmp`-identical to the base, non-
#               tautologically (gate 2 proves dis -> as byte-neutral first)
#   (scratch) noguard  full coverage, silhouette fallback removed: the decoy
#               the verifier MUST reject.
set -euo pipefail

MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="${CALLISTO_INSTALL_DIR:-$HOME/.local/lib/callisto}"
PY="$MOD_DIR/dev/patch_curv.py"
VERIFY="$MOD_DIR/dev/verify_curv.py"
MODEL="$MOD_DIR/dev/curv_model.py"

BASE=gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog-earglow-cap6-glintdense
NAME=curv
DO_INSTALL=0
DO_STACK=0
GAIN=1.0
GAIN_HI=2.0
KAPPA0=10.0
JUMP=0.05
STEP=1
while (( $# )); do
    case "$1" in
        --install) DO_INSTALL=1 ;;
        --stack)   DO_STACK=1 ;;
        --base)    BASE="${2:?--base needs a skin.set name}"; shift ;;
        --name)    NAME="${2:?--name needs a rung name}"; shift ;;
        --gain)    GAIN="${2:?--gain needs a number}"; shift ;;
        --gain-hi) GAIN_HI="${2:?--gain-hi needs a number}"; shift ;;
        --kappa0)  KAPPA0="${2:?--kappa0 needs 1/m}"; shift ;;
        --jump)    JUMP="${2:?--jump needs metres}"; shift ;;
        --step)    STEP="${2:?--step needs texels}"; shift ;;
        *) echo "unknown arg $1" >&2; exit 1 ;;
    esac
    shift
done
KNOBS=(--kappa0 "$KAPPA0" --jump "$JUMP" --step "$STEP")

SRC="$INSTALL_DIR/skin.set/$BASE"
WORK="$MOD_DIR/dev/disasm/curv"
declare -A OUT=( [curv]="$MOD_DIR/swaps.curv"
                 [hi]="$MOD_DIR/swaps.curv.hi"
                 [vis]="$MOD_DIR/swaps.curv.vis"
                 [ctl]="$MOD_DIR/swaps.curv.ctl" )

# --- 0. base provenance ----------------------------------------------------
echo "--- 0. base provenance ($BASE) ---"
[[ -f "$SRC/MANIFEST.txt" ]] || { echo "no $SRC/MANIFEST.txt -- the standing selection is not parked" >&2; exit 1; }
n_c=$(ls "$SRC"/*.dxil.spv | wc -l)
n_r=$(ls "$SRC"/*.rgs_*.spv | wc -l)
[[ "$n_c" == 77 ]] || { echo "$BASE has $n_c compute modules, expected 77" >&2; exit 1; }
[[ "$n_r" == 16 ]] || { echo "$BASE has $n_r raygen modules, expected 16" >&2; exit 1; }
echo "  77 compute + 16 raygen (12 rgs_reference_main + 4 rgs_restirgi_*)"
[[ "$(ls "$SRC"/*.rgs_reference_main.spv | wc -l)" == 12 ]] || { echo "not 12 rgs_reference_main" >&2; exit 1; }
[[ "$(ls "$SRC"/*.rgs_restirgi_*.spv | wc -l)" == 4 ]] || { echo "not 4 rgs_restirgi_*" >&2; exit 1; }

# --- 1. the offline model gates itself -------------------------------------
echo "--- 1. offline model (dev/curv_model.py) ---"
python3 "$MODEL" | tail -4

# --- 2. disassemble --------------------------------------------------------
rm -rf "$WORK"; mkdir -p "$WORK/asm" "$WORK/rt"
for k in curv hi vis ctl noguard; do mkdir -p "$WORK/$k"; done
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
patch_all "$WORK/curv"    --tier bleed --gain "$GAIN"    "${KNOBS[@]}"
patch_all "$WORK/hi"      --tier bleed --gain "$GAIN_HI" "${KNOBS[@]}"
patch_all "$WORK/vis"     --tier vis   --gain "$GAIN"    "${KNOBS[@]}"
patch_all "$WORK/ctl"     --tier bleed --gain 0.0
patch_all "$WORK/noguard" --tier bleed --gain "$GAIN" "${KNOBS[@]}" --no-guard

# --- 5. coverage, from the reports, never from byte counts -----------------
echo "--- 5. coverage ---"
python3 - "$MOD_DIR" "$WORK" "$GAIN" "$GAIN_HI" "$KAPPA0" "$JUMP" "$STEP" <<'PY' || exit 1
import glob, json, os, sys
sys.path.insert(0, os.path.join(sys.argv[1], 'dev'))
import patch_curv as PC
W = sys.argv[2]
gain, gain_hi = float(sys.argv[3]), float(sys.argv[4])
kappa0, jump, step = float(sys.argv[5]), float(sys.argv[6]), int(sys.argv[7])
C = PC.CENSUS
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


for rung, g, tier in (('curv', gain, 'bleed'), ('hi', gain_hi, 'bleed'),
                      ('noguard', gain, 'bleed'), ('vis', gain, 'vis')):
    badm, rows = scan(os.path.join(W, rung))
    if badm != PC.KNOWN_DECLINE:
        bad.append((rung, 'declines are %s, expected exactly %s'
                    % (sorted(badm), sorted(PC.KNOWN_DECLINE))))
    anchors, sites, instr, reuse, refetch, writes, skipped = set(), 0, [], 0, 0, 0, 0
    for r in rows:
        p = r['curv']
        if p['tier'] != tier:
            bad.append((r['dxil'], 'wrong tier'))
        anchors.add(json.dumps([p['matrix'], p['cbv_slot'], p['depth_slot'],
                                p['normal_slot'], p['gain'], p['kappa0'],
                                p['jump'], p['step'], p['guard']]))
        if tier == 'bleed':
            if not p['bleed_sites']:
                bad.append((r['dxil'], 'zero bleed sites in a patched module'))
            sites += p['bleed_sites']
            instr.append(p['curv_instructions'])
            reuse += bool(p['centre_normal_reused'])
            refetch += bool(p['centre_pos_refetched'])
            for st in p['sites']:
                if st['bw_uses'] != 3:
                    bad.append((r['dxil'], 'a bleed amplitude has %d consumers'
                                % st['bw_uses']))
        else:
            writes += len(p['writes'])
            skipped += len(p['skipped'])
            refetch += len(p['centre_pos_refetched'])
            reuse += len(p['centre_normal_reused'])
    if len(rows) != C['patched_modules']:
        bad.append((rung, '%d patched modules, census says %d'
                    % (len(rows), C['patched_modules'])))
    if len(anchors) != 1:
        bad.append((rung, 'modules disagree on anchors/knobs: %d distinct'
                    % len(anchors)))
    else:
        a = json.loads(sorted(anchors)[0])
        if a[:4] != [C['matrix_members'], C['cbv_slot'], C['depth_slot'],
                     C['normal_slot']]:
            bad.append((rung, 'anchors moved: %s' % (a[:4],)))
        if [a[4], a[5], a[6], a[7]] != [g, kappa0, jump, step]:
            bad.append((rung, 'knobs are %s, asked for %s'
                        % (a[4:8], [g, kappa0, jump, step])))
        if a[8] != (rung != 'noguard'):
            bad.append((rung, 'guard flag is %s' % a[8]))
    if tier == 'bleed':
        if sites != C['bleed_sites_reached']:
            bad.append((rung, '%d bleed sites, census says %d'
                        % (sites, C['bleed_sites_reached'])))
        if min(instr) != max(instr):
            bad.append((rung, 'estimator size varies: %d..%d'
                        % (min(instr), max(instr))))
        print('  %-8s: %d modules, %d declined, %d bleed sites, %d instr/module,'
              ' centre N reused %d, centre P refetched %d'
              % (rung, len(rows), len(badm), sites, instr[0], reuse, refetch))
    else:
        if writes != C['writes']:
            bad.append((rung, '%d writes, census says %d' % (writes, C['writes'])))
        if skipped:
            bad.append((rung, '%d writes skipped inside patched modules' % skipped))
        if refetch + reuse != C['writes']:
            bad.append((rung, 'centre-P accounting does not add up'))
        print('  %-8s: %d modules, %d declined, %d writes painted (%d refetched'
              ' P / %d reused), %d skipped'
              % (rung, len(rows), len(badm), writes, refetch, reuse, skipped))

badc, rowsc = scan(os.path.join(W, 'ctl'))
sc = sum(r['curv']['bleed_sites'] for r in rowsc)
print('  ctl     : %d modules emitted, %d declined, %d sites scaled'
      % (len(rowsc), len(badc), sc))
if len(rowsc) != C['modules'] or badc:
    bad.append(('ctl', 'emitted %d modules, declined %s; want %d / none'
                % (len(rowsc), sorted(badc), C['modules'])))
if sc:
    bad.append(('ctl', 'the gain-0 control scaled %d sites' % sc))

if bad:
    for m, why in bad[:12]:
        sys.stderr.write('    %s :: %s\n' % (m, why))
    sys.exit(1)
print('  declined by name: %s  (%d bleed sites left at the shipped 0.35)'
      % (', '.join(sorted(PC.KNOWN_DECLINE)), C['bleed_sites_declined']))
print('  anchors single-valued: matrix cbv[reg0+12][69..72], depth registers[1]+0,'
      ' normal registers[1]+2')
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
    # the two declined resolvers are base bytes too
    for h in $(python3 -c 'import sys;sys.path.insert(0,"'"$MOD_DIR"'/dev");import patch_curv;print(" ".join(sorted(patch_curv.KNOWN_DECLINE)))'); do
        cmp -s "$SRC/$h.dxil.spv" "$dest/$h.dxil.spv" || { echo "declined module $h is not base bytes" >&2; exit 1; }
    done
    for f in "$dest"/*.spv; do
        spirv-val --target-env vulkan1.4 "$f" >/dev/null || { echo "spirv-val FAILED: $f" >&2; exit 1; }
    done
}
echo "--- 6. assemble (16/16 raygen + 2/2 declined cmp-identical, spirv-val vulkan1.4) ---"
for k in curv hi vis ctl; do assemble "${OUT[$k]}" "$WORK/$k"; done
NOG="$WORK/rung.noguard"; assemble "$NOG" "$WORK/noguard"

for k in curv hi vis; do
    d=0; for f in "$SRC"/*.dxil.spv; do cmp -s "$f" "${OUT[$k]}/$(basename "$f")" || d=$((d+1)); done
    echo "  $k: $d of 77 compute modules differ from $BASE"
    [[ "$d" == 75 ]] || { echo "  !! expected exactly 75 (the census)" >&2; exit 1; }
done
d=0; for f in "$SRC"/*.spv; do cmp -s "$f" "${OUT[ctl]}/$(basename "$f")" || d=$((d+1)); done
echo "  ctl: $d of 93 modules differ from $BASE"
[[ "$d" == 0 ]] || { echo "  !! the gain-0 control is NOT byte-identical to the base" >&2; exit 1; }
for pair in "curv:hi" "curv:vis" "hi:vis" "curv:$NOG"; do
    a="${pair%%:*}"; b="${pair##*:}"
    [[ "$b" == /* ]] || b="${OUT[$b]}"
    d=0; for f in "${OUT[$a]}"/*.spv; do cmp -s "$f" "$b/$(basename "$f")" || d=$((d+1)); done
    echo "  $a vs $(basename "$b"): $d of 93 differ"
    [[ "$d" -gt 0 ]] || { echo "  !! two rungs are byte-identical" >&2; exit 1; }
done

# --- 7. the verifier, on shipped bytes, proven non-vacuous -----------------
echo "--- 7. verifier (shipped bytes) ---"
python3 "$VERIFY" "${OUT[curv]}" --gain "$GAIN"    "${KNOBS[@]}"
python3 "$VERIFY" "${OUT[hi]}"   --gain "$GAIN_HI" "${KNOBS[@]}"
reject () {   # $1 = label, rest = verifier args
    local label="$1"; shift
    if python3 "$VERIFY" "$@" >/dev/null 2>&1; then
        echo "  !! the verifier ACCEPTS $label -- it is vacuous" >&2; exit 1; fi
    echo "  rejected: $label"
}
reject "the unpatched base"            "$SRC"          --gain "$GAIN" "${KNOBS[@]}"
reject "the gain-0 control"            "${OUT[ctl]}"   --gain "$GAIN" "${KNOBS[@]}"
reject "the NO-SILHOUETTE-GUARD decoy" "$NOG"          --gain "$GAIN" "${KNOBS[@]}"
reject "curv read as curv-hi"          "${OUT[curv]}"  --gain "$GAIN_HI" "${KNOBS[@]}"
reject "curv-hi read as curv"          "${OUT[hi]}"    --gain "$GAIN" "${KNOBS[@]}"
reject "a wrong kappa0"                "${OUT[curv]}"  --gain "$GAIN" --kappa0 6 --jump "$JUMP" --step "$STEP"
reject "a wrong silhouette threshold"  "${OUT[curv]}"  --gain "$GAIN" --kappa0 "$KAPPA0" --jump 0.02 --step "$STEP"
reject "a wrong neighbour step"        "${OUT[curv]}"  --gain "$GAIN" --kappa0 "$KAPPA0" --jump "$JUMP" --step 2
reject "a wrong s clamp"               "${OUT[curv]}"  --gain "$GAIN" "${KNOBS[@]}" --smax 3.0
reject "curv read as unguarded"        "${OUT[curv]}"  --gain "$GAIN" "${KNOBS[@]}" --no-guard

# --- 8. the diagnostic rung, read back off its own bytes ------------------
echo "--- 8. curv-vis is class-gated and leaves every non-skin pixel alone ---"
python3 - "$MOD_DIR" "${OUT[vis]}" "$SRC" <<'PY' || exit 1
import glob, os, re, subprocess, sys, tempfile
sys.path.insert(0, os.path.join(sys.argv[1], 'dev'))
from patch_chs_brdf import load_lenient
import wpos_core as W
from patch_curv import KNOWN_DECLINE, CENSUS
vis, src = sys.argv[2], sys.argv[3]
tmp = tempfile.mkdtemp(prefix='curv_vis.')
bad = []


def dis(path, tag):
    a = os.path.join(tmp, tag + '.spvasm')
    subprocess.run(['spirv-dis', path, '-o', a], check=True, capture_output=True)
    mod, _ = load_lenient(a)
    return mod, W.defs_index(mod)


def texels(mod):
    """(texel id, its three float components) for every radiance write, in
    program order."""
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
    """Canonical opcode multiset of everything reachable from `roots`.

    SSA numbers are erased (the patched module is renumbered), but every
    named token -- types, and spirv-dis's value-named constants -- survives,
    so two slices compare equal only if they compute the same thing.
    """
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

# --- 9. the shipping stack: <base>-curv ------------------------------------
# handoff/109 sec 13.  curv (g = 1) was shot 2026-09-03 and kept, so it needs a
# name the selector's stack convention understands.  The stack is not a rebuild:
# it is byte-for-byte the `curv` rung, re-parked under the long name, which is
# what makes "the default IS curv" a cmp fact rather than a claim.
STACK="$BASE-curv"
SDIR="$MOD_DIR/swaps.$STACK"
if (( DO_STACK )); then
    echo "--- 9. shipping stack ($STACK) ---"
    rm -rf "$SDIR"; mkdir -p "$SDIR"
    cp -pf "${OUT[curv]}"/*.spv "$SDIR/"
    n=$(ls "$SDIR"/*.spv | wc -l)
    [[ "$n" == 93 ]] || { echo "stack has $n modules, expected 93" >&2; exit 1; }
    # 9a. the 16 raygens are the base's, byte-verbatim
    d=0; for f in "$SRC"/*.rgs_*.spv; do
        cmp -s "$f" "$SDIR/$(basename "$f")" || d=$((d+1)); done
    [[ "$d" == 0 ]] || { echo "  !! $d of 16 raygens differ from $BASE" >&2; exit 1; }
    echo "  16 of 16 raygens (12 rgs_reference_main + 4 rgs_restirgi_*) cmp-verbatim from $BASE"
    # 9b. the 77 compute modules ARE the parked curv rung's
    PARKED="$INSTALL_DIR/skin.set/$NAME"
    if [[ -d "$PARKED" ]]; then
        d=0; for f in "$SDIR"/*.dxil.spv; do
            cmp -s "$f" "$PARKED/$(basename "$f")" || d=$((d+1)); done
        [[ "$d" == 0 ]] || { echo "  !! $d of 77 compute modules differ from the parked $NAME" >&2; exit 1; }
        echo "  77 of 77 compute modules cmp-identical to the parked $NAME rung"
        d=0; for f in "$SDIR"/*.spv; do
            cmp -s "$f" "$PARKED/$(basename "$f")" || d=$((d+1)); done
        [[ "$d" == 0 ]] || { echo "  !! the stack is not 93/93 identical to $NAME" >&2; exit 1; }
        echo "  93 of 93 modules cmp-identical to $NAME -- the stack IS curv"
    else
        echo "  note: $NAME is not parked yet; skipping the parked-rung cmp"
    fi
    # 9c. and it still verifies as a curv rung on its own bytes
    python3 "$VERIFY" "$SDIR" --gain "$GAIN" "${KNOBS[@]}" | tail -2
    for f in "$SDIR"/*.spv; do
        spirv-val --target-env vulkan1.4 "$f" >/dev/null || { echo "spirv-val FAILED: $f" >&2; exit 1; }
    done
    STACK_SHA=$(cat "$SDIR"/*.spv | sha256sum | cut -c1-16)
    echo "  content sha $STACK_SHA   (base was $(cat "$SRC"/*.spv | sha256sum | cut -c1-16))"
fi

# --- 10. MANIFESTs ---------------------------------------------------------
manifest () {   # $1 = dest, $2 = rung name, $3 = tail comment
    sed -e "1s/^$BASE /$2 /" -e "1s/compute=77([^)]*)/compute=77($BASE-$2)/" \
        "$SRC/MANIFEST.txt" > "$1/MANIFEST.txt"
    grep -q "^$2 " "$1/MANIFEST.txt" || { echo "MANIFEST rewrite failed" >&2; exit 1; }
    echo "# $3" >> "$1/MANIFEST.txt"
}
manifest "${OUT[curv]}" "$NAME" "curvature-driven skin scattering: s = clamp(1 + ${GAIN}*(clamp(kappa,0.5,40)/${KAPPA0} - 1), 0.3, 2.0) from 4 extra G-buffer taps (+-${STEP} texel), driving BOTH the terminator band width and its amplitude at 142 sites in 75 compute modules; silhouette fallback |dP| > ${JUMP} m -> s = 1. Raygens are $BASE bytes. See handoff/109."
manifest "${OUT[hi]}" "$NAME-hi" "curv at gain ${GAIN_HI}: the same pivot at ${KAPPA0} /m, twice the contrast. A cheek is unchanged; a nose wing and a forehead move twice as far. See handoff/109 sec 3."
manifest "${OUT[vis]}" "$NAME-vis" "curv DIAGNOSTIC: kappa painted at all 150 radiance writes as blue(flat) -> green -> red(tight), white where the silhouette guard fired, on class-1 pixels ONLY, modulated by scene luminance. Not a shipping rung. See handoff/109 sec 7."
manifest "${OUT[ctl]}" "$NAME-ctl" "curv CONTROL (gain 0): 93 of 93 modules byte-identical to $BASE. Selecting it must be indistinguishable from the base."
if (( DO_STACK )); then
    # Same shape as the base's MANIFEST: the rung name and its base on line 1,
    # the base's own `# src:` provenance line carried through with the compute
    # tag extended, then this rung's comments.
    sed -e "1s/^$BASE /$STACK /" \
        -e "1s|(base=[^)]*)|(base=$BASE, = $BASE + handoff/109 curvature skin at g=$GAIN)|" \
        -e "1s|handoff/[0-9]* sec [0-9]*|handoff/109|" \
        -e "s/compute=77(\([^)]*\))/compute=77(\1+curv)/" \
        -e "/^# UNSHOT\./d" -e "/^# a CHILD and an ADULT/d" \
        "$SRC/MANIFEST.txt" > "$SDIR/MANIFEST.txt"
    grep -q "^$STACK " "$SDIR/MANIFEST.txt" || { echo "MANIFEST rewrite failed" >&2; exit 1; }
    cat >> "$SDIR/MANIFEST.txt" <<EOF
# STACKED (handoff/109): the shipped default PLUS curvature-driven skin
# scattering. kappa = mean over x,y of |dN|/|dP| from 4 extra Lod-0 taps on
# the depth (registers[1]+0) and normal (registers[1]+2) targets at +1 texel;
# s = clamp(1 + ${GAIN}*(clamp(kappa,0.5,40)/${KAPPA0} - 1), 0.3, 2.0) scales BOTH the
# terminator band width and its amplitude at 142 of 150 bleed sites in 75 of
# 77 compute modules. Cheek (kappa = 10 /m) is the pivot and does not move.
# 78's luminance hold rides the same value: neutrality exact (9e-8 measured).
# Silhouette fallback: |dP| > ${JUMP} m across a texel -> s = 1 (the shipped 0.35).
# 93 of 93 modules cmp-identical to skin.set/$NAME; 16 of 16 raygens are
# $BASE bytes. The c1 term and the specular are untouched.
# USER VERDICT 2026-09-03: 'tested the curvature based bleed effect and it
# looks incredible' / 'I'm just preferring using the default curv option'.
# LIVE READ-OUT ONLY -- no frame was captured. See handoff/109 sec 13.
# content sha $STACK_SHA
EOF
fi

echo
for k in curv hi vis ctl; do echo "  built ${OUT[$k]} (93 modules)"; done
if (( DO_INSTALL )); then
    for pair in "curv:$NAME" "hi:$NAME-hi" "vis:$NAME-vis" "ctl:$NAME-ctl"; do
        s="${OUT[${pair%%:*}]}"; n="${pair##*:}"
        park="$INSTALL_DIR/skin.set/$n"
        # NEW names only.  Never touch a parked dir this script did not create.
        if [[ -d "$park" && ! -f "$park/.built-by-build_curv" ]]; then
            echo "  !! $park exists and was not built by build_curv.sh -- refusing" >&2
            exit 1
        fi
        mkdir -p "$park"; rm -f "$park"/*.spv "$park/MANIFEST.txt"
        cp -pf "$s"/*.spv "$s/MANIFEST.txt" "$park/"
        : > "$park/.built-by-build_curv"
        echo "  parked -> $park"
    done
    if (( DO_STACK )); then
        park="$INSTALL_DIR/skin.set/$STACK"
        if [[ -d "$park" && ! -f "$park/.built-by-build_curv" ]]; then
            echo "  !! $park exists and was not built by build_curv.sh -- refusing" >&2
            exit 1
        fi
        mkdir -p "$park"; rm -f "$park"/*.spv "$park/MANIFEST.txt"
        cp -pf "$SDIR"/*.spv "$SDIR/MANIFEST.txt" "$park/"
        : > "$park/.built-by-build_curv"
        d=0; for f in "$SDIR"/*.spv; do
            cmp -s "$f" "$park/$(basename "$f")" || d=$((d+1)); done
        [[ "$d" == 0 ]] || { echo "  !! parked differs from built on $d files" >&2; exit 1; }
        echo "  parked -> $park  (parked == built, 93 of 93 cmp-verbatim, sha $STACK_SHA)"
    fi
else
    echo "NOT installed. To park: ./dev/build_curv.sh --install"
fi
(( DO_STACK )) && echo "SHIPPING STACK: skinspec=$STACK  (content sha $STACK_SHA)"
echo "select with skinspec=$NAME | $NAME-hi | $NAME-vis | $NAME-ctl;"
echo "needs ser=class + shadowset=full-shadow ($BASE's contract)"
