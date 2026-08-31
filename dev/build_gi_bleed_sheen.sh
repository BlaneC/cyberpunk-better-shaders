#!/usr/bin/env bash
# gi-50-bleed + peach fuzz: the standing rung's raygens, byte-verbatim, over a
# compute half carrying the class-1 sheen lobe (A3; gate 58, look plan 51 sec
# 10, rebuilt as a real lobe in 71).
#
#   ./dev/build_gi_bleed_sheen.sh                      # assemble + verify
#   ./dev/build_gi_bleed_sheen.sh --install            # ALSO park the rung
#   ./dev/build_gi_bleed_sheen.sh --install \
#        --parent real-gloss-bleed-oil --name gi-50-bleed-oil-sheen
#
# Composition mirrors build_gi_bleed.sh: gi-50-bleed is gi-50's raygens
# (byte-verbatim) + real-gloss-bleed's 77 compute. The sheen lives only in
# the compute half, so this copies gi-50's SIXTEEN raygen files BYTE-VERBATIM
# (asserted below) and swaps the 77 compute for --parent's, plus the
# class-1-gated Charlie fuzz (dev/patch_subtype_probe.py --tier peach).
# The A/B "<parent's gi rung> vs <this rung>" is one variable by construction.
# Provenance fields (src_ser/ser_sha/ptq_sha) carry over VERBATIM, so gi-50's
# contract with sync_settings.sh's gi_refuse block still holds -- needs
# ser=class + shadowset=full-shadow.
#
# The fuzz (--peach-mode add, the default: spec += k*min(D_charlie*V_neubelt,
# cap)*NoL_site, class-1 gated) is spliced at the site's own D*Vis product, so
# the module's Fresnel, light colour, shadow and firefly clamp all land on it
# too -- unlit skin stays black because the LIGHT is zero, and the 720p tile
# grid of 38 0d cannot appear. --peach-mode mul rebuilds the 58-era
# multiplicative form (see handoff/71 sec 2 for why it read as "extremely
# subtle" on screen).
#
# Knobs are OpConstants baked at build time; override with
#   ./dev/build_gi_bleed_sheen.sh --install --set k_peach=0.35
set -euo pipefail

MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="${CALLISTO_INSTALL_DIR:-$HOME/.local/lib/callisto}"
PY="$MOD_DIR/dev/patch_subtype_probe.py"

# Peach knobs -- fuzz = min(D_charlie*V_neubelt*(2+1/a)/2pi, cap), class-1 gated.
#   a_peach   tightness of the Charlie lobe: smaller = falls off faster with
#             the half-angle, so the fuzz hugs the grazing rim instead of
#             washing the whole face.
#   k_peach   strength of the ADDED lobe, measured at the splice point --
#             upstream of the module's own Fresnel, which is at its f0 floor
#             (~0.028) in the FRONT-LIT band this lobe lives in, so k of
#             order 1 is the right magnitude here. ./dev/fuzz_model.py prints
#             what it costs: at k=1.0 the fuzz is 0-2% of the local diffuse
#             head-on and 5-17% on a cheek rim. Halve it for a softer rung.
#   defres    [0,1]: how much of the module's own Schlick ramp to cancel on
#             the added lobe. 0 = the wide 72-era rung, whose ~30x Fresnel
#             swing put a blown white edge on the BACKLIT silhouette and
#             washed out the terminator bleed's red (the user's A/B read,
#             2026-08-31). 1 = targeted: the front-lit band is bit-for-bit
#             the same response, the rim peak drops 2.5x. See handoff/73.
#   peach_max ceiling on D*V before k. At defres=1 it is also the second half
#             of the rim cut (0.5 -> the worst pixel goes 781% -> 159% of the
#             local diffuse); past ~80 deg of view it is what binds.
# Command-line --set overrides win (argparse keeps the last assignment).
PARENT=real-gloss-bleed
NAME=gi-50-bleed-sheen
GINAME=gi-50
MODE=add
DO_INSTALL=0
# k_peach default 1.0 -> 0.5 (74): the user's on-screen read of the 73 build
# was fuzz-haze on dim/indoor skin -- an achromatic add over a dim rosy
# diffuse desaturates it, and the lobe cannot see radiance to know the light
# is dim. Half is the shipping level; --set k_peach=1.0 rebuilds the 73 rung.
PEACH_SET=(--set k_peach=0.5 --set a_peach=0.35 --set peach_max=0.5 \
            --set defres=1.0)
while (( $# )); do
    case "$1" in
        --install) DO_INSTALL=1 ;;
        --parent)  PARENT="${2:?--parent needs a skin.set name}"; shift ;;
        --name)    NAME="${2:?--name needs a rung name}"; shift ;;
        # 74: which parked gi raygen base to ride (gi-50, or gi-50b = c1 +
        # terminator bleed on BOUNCE light at the ST pair's tail NoL).
        --gi)      GINAME="${2:?--gi needs a parked gi rung name}"; shift ;;
        --peach-mode) MODE="${2:?--peach-mode needs add|mul}"; shift ;;
        --set)     PEACH_SET+=(--set "${2:?--set needs K=V}"); shift ;;
        *)         PEACH_SET+=(--set "$1") ;;   # bare k=v, the old spelling
    esac
    shift
done
GI="$INSTALL_DIR/skin.set/$GINAME"
RGB="$INSTALL_DIR/skin.set/$PARENT"
DEST="$MOD_DIR/swaps.gi.${NAME#gi-}"
WORK="$MOD_DIR/dev/disasm/peach.$NAME"

[[ -f "$GI/MANIFEST.txt" ]] || { echo "no $GI/MANIFEST.txt -- run ./dev/build_gi_rung.sh --install first" >&2; exit 1; }
[[ -d "$RGB" ]] || { echo "no $RGB -- run ./dev/patch_compute_skin.sh --only $PARENT" >&2; exit 1; }
n_rgb=$(ls "$RGB"/*.dxil.spv | wc -l)
[[ "$n_rgb" == 77 ]] || { echo "$RGB has $n_rgb compute modules, expected 77" >&2; exit 1; }

# --- disassemble the 77 compute sources (sequential; shared work dir) ------
rm -rf "$WORK"; mkdir -p "$WORK/asm" "$WORK/out"
for f in "$RGB"/*.dxil.spv; do
    n="$(basename "$f" .dxil.spv)"
    spirv-dis "$f" -o "$WORK/asm/$n.spvasm"
done

# --- patch the peach fuzz into each compute module (parallel) --------------
printf '%s\n' --tier peach --peach-mode "$MODE" "${PEACH_SET[@]}" \
    --outdir "$WORK/out" > "$WORK/.args"
jobs="${CALLISTO_JOBS:-$(nproc 2>/dev/null || echo 4)}"
find "$WORK/asm" -name '*.spvasm' -print0 | \
    CB_ARGS="$WORK/.args" CB_PY="$PY" CB_OUT="$WORK/out" \
    xargs -0 -P "$jobs" -n1 bash -c '
        asm="$1"; n="$(basename "${asm%.spvasm}")"
        mapfile -t A < "$CB_ARGS"
        if python3 "$CB_PY" "$asm" "${A[@]}" > "$CB_OUT/.$n.json" 2>"$CB_OUT/.$n.err"; then
            : > "$CB_OUT/.ok.$n"
        else
            : > "$CB_OUT/.bad.$n"
        fi' _
np=$(find "$WORK/out" -name '.ok.*' | wc -l)
nf=$(find "$WORK/out" -name '.bad.*' | wc -l)
echo "peach: patched $np, failed $nf"
if (( nf > 0 )); then
    for f in "$WORK/out"/.bad.*; do
        n="$(basename "$f")"; n="${n#.bad.}"
        echo "  $n :: $(sed 's/.*error: //' "$WORK/out/.$n.err" 2>/dev/null | head -1 | cut -c1-90)"
    done | sort | head -10
    exit 1
fi

# Coverage from reports, never byte diffs (the 42 rule): every module must
# carry >=1 peach site and zero skipped_dom, or the sheen is absent from a
# module while its byte count still moves (the emitted constants).
python3 - "$WORK/out" <<'PY' || exit 1
import glob, json, os, sys
dest = sys.argv[1]
tot = dict(mods=0, sites=0, ggx=0, shape=0, dom=0, dup=0,
           folded=0, folded_min=0, clamped=0, defres_sites=0)
betas = set()
modes = set()
bad = []
for f in sorted(glob.glob(os.path.join(dest, '.*.json'))):
    try:
        d = json.load(open(f))[0]
    except Exception as e:
        bad.append((os.path.basename(f), 'bad json: %s' % e)); continue
    p = d.get('peach', {})
    modes.add(p.get('mode'))
    tot['mods'] += 1
    tot['sites'] += p.get('peach_sites', 0)
    tot['ggx'] += p.get('ggx_sites', 0)
    tot['shape'] += len(p.get('skipped_shape', []))
    tot['dom'] += len(p.get('skipped_dom', []))
    tot['dup'] += len(p.get('skipped_dup', []))
    for k in ('folded', 'folded_min', 'clamped', 'defres_sites'):
        tot[k] += p.get(k, 0)
    betas.add(p.get('defres', 0.0))
    if d.get('spirv_val') != 'clean':
        bad.append((d.get('module'), 'spirv-val not clean'))
    if p.get('peach_sites', 0) == 0:
        bad.append((d.get('module'), 'no peach site at all'))
print('  peach coverage: %d modules, %d sites over %d GGX sites, '
      '%d skipped_shape, %d skipped_dom, %d skipped_dup' %
      (tot['mods'], tot['sites'], tot['ggx'], tot['shape'], tot['dom'], tot['dup']))
print('  mode %s: %d sites fold the site\'s own light cosine, %d fold '
      'min(c0,c1) at a cheap-Vis site, %d cosine(s) clamped'
      % ('/'.join(sorted(str(m) for m in modes)), tot['folded'],
         tot['folded_min'], tot['clamped']))
print('  defres %s: the Schlick ramp is cancelled at %d of %d sites'
      % ('/'.join('%.2f' % b for b in sorted(betas)), tot['defres_sites'],
         tot['sites']))
if len(betas) != 1:
    bad.append(('defres', 'modules disagree on defres: %s' % sorted(betas)))
if max(betas) > 0 and tot['defres_sites'] != tot['sites']:
    # A site that took the lobe but not the weight would keep the 72-era
    # blown rim on part of the face, and the byte count would not say so.
    bad.append(('defres', '%d of %d sites carry the weight'
                % (tot['defres_sites'], tot['sites'])))
if tot['mods'] != 77:
    bad.append(('coverage', 'only %d module reports, want 77' % tot['mods']))
if tot['dom']:
    bad.append(('gate', '%d skipped_dom -- the class gate does not reach the shading' % tot['dom']))
if tot['dup']:
    # Two GGX sites resolving to ONE D*Vis product: the second splice would be
    # a silent no-op (08-DUAL-LOBE) while still counting as coverage. Census
    # says zero; if it ever fires, read handoff/71 sec 2 before trusting it.
    bad.append(('dup', '%d duplicate spec product(s) -- coverage is not what it looks like' % tot['dup']))
if bad:
    for m, why in bad[:12]:
        sys.stderr.write('    %s :: %s\n' % (m, why))
    sys.exit(1)
PY
rm -f "$WORK/.args"

# --- assemble the rung: gi-50 raygens + the peach'd 77 compute -------------
rm -rf "$DEST"; mkdir -p "$DEST"
cp -pf "$GI"/*.rgs_*.spv "$DEST/"
n_rgs=$(ls "$DEST"/*.rgs_*.spv | wc -l)
[[ "$n_rgs" == 16 ]] || { echo "copied $n_rgs raygen files from $GINAME, expected 16 (12+4)" >&2; exit 1; }
cp -pf "$WORK/out"/*.dxil.spv "$DEST/"
n=$(ls "$DEST"/*.spv | wc -l)
[[ "$n" == 93 ]] || { echo "rung has $n modules, expected 93 (77+12+4)" >&2; exit 1; }

# raygens byte-identical to the named base's -- the one-variable guarantee, half 1
for f in "$GI"/*.rgs_*.spv; do
    cmp -s "$f" "$DEST/$(basename "$f")" || { echo "raygen $(basename "$f") differs from $GINAME -- NOT one variable" >&2; exit 1; }
done
# compute half must differ from the parent's (the sheen reached it) -- half 2.
# Equal-coverage (same file list) asserted too.
diff <(cd "$RGB" && ls *.dxil.spv) <(cd "$DEST" && ls *.dxil.spv) >/dev/null \
    || { echo "compute file lists differ between $PARENT and the rung" >&2; exit 1; }
d=0
for f in "$RGB"/*.dxil.spv; do
    cmp -s "$f" "$DEST/$(basename "$f")" || d=$((d+1))
done
(( d > 0 )) || { echo "compute is byte-identical to $PARENT -- the sheen emitted nothing" >&2; exit 1; }
echo "  compute: $d of 77 modules differ from $PARENT (sheen-covered)"

for f in "$DEST"/*.spv; do spirv-val "$f" || { echo "spirv-val FAILED: $f" >&2; exit 1; }; done

# MANIFEST: the raygen base's provenance verbatim, renamed, compute half
# renamed. (The base's ser_sha/ptq_sha carry over untouched, so the
# gi_refuse contract is unchanged.)
sed -e "1s/^$GINAME /$NAME /" \
    -e "1s/compute=77([^)]*)/compute=77($PARENT-sheen)/" \
    "$GI/MANIFEST.txt" > "$DEST/MANIFEST.txt"
grep -q "^$NAME .*compute=77($PARENT-sheen)" "$DEST/MANIFEST.txt" \
    || { echo "MANIFEST rewrite failed -- check $GI/MANIFEST.txt line 1 format" >&2; exit 1; }
echo "# peach-fuzz sheen (class-1 Charlie lobe, --peach-mode $MODE ${PEACH_SET[*]}) rides the compute half; raygens are $GINAME bytes; see handoff/73 + 74" >> "$DEST/MANIFEST.txt"
echo "  built $DEST: 93 modules, raygens = $GINAME bytes, all spirv-val clean"

if [[ "$DO_INSTALL" == 1 ]]; then
    park="$INSTALL_DIR/skin.set/$NAME"
    mkdir -p "$park"; rm -f "$park"/*.spv "$park/MANIFEST.txt"
    cp -pf "$DEST"/*.spv "$DEST/MANIFEST.txt" "$park/"
    echo "  parked -> $park"
else
    echo "NOT installed. To park: ./dev/build_gi_bleed_sheen.sh --install"
fi
echo "select with skinspec=$NAME; needs ser=class, shadowset=full-shadow ($GINAME's contract)"
