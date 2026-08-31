#!/usr/bin/env bash
# Callisto SKIN BRDF on the GLCompute resolve shaders -- the confirmed-visible
# surface.
#
#   ./dev/patch_compute_skin.sh              # c1 only (the shipping build)
#   ./dev/patch_compute_skin.sh --sets       # the gloss STRENGTH LADDER, parked
#   ./dev/patch_compute_skin.sh --hunt       # 10-class palette (diagnostic)
#
# --sets is the one to use for the Tier-3 skin gloss (handoff/27 Phase 2). The
# gloss is spliced into the same modules as the tier-1 c1, so it cannot be a
# second overlay -- the layer serves the first file it finds for an id
# (GOTCHAS: first-file-wins). And its knobs are OpConstants baked in at build
# time, so no runtime slider can move them: a CET slider claiming to would be
# the inert-slider trap of handoff/26 section 5 all over again.
#
# So strength is a LADDER of pre-built sets. This builds the skin overlay once
# per level plus a gloss-free baseline, parks them in
# $INSTALL_DIR/skin.set/<level>/, and sync_settings.sh materializes whichever
# one `skinspec` names into swaps.skin/ at launch -- exactly how `shadowset`
# picks a shadowcull build. The CET selector offers the same list.
#
# Every set carries an IDENTICAL c1 from the same source in the same run, so
# moving the selector changes the gloss and nothing else.
#
# For a value not on the ladder, --set overrides any level:
#   ./dev/patch_compute_skin.sh --sets --set alpha_max=0.06
#
# Replaces dev/patch_compute_hair.sh (deleted 2026-08-28 with the hair BRDF).
set -euo pipefail

MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DUMP_DIR="${CALLISTO_DUMP_DIR:-$HOME/callisto_dump}"
GAME_DIR="${CALLISTO_GAME_DIR:-/mnt/f4333173-dd02-4314-9fd0-2ce547a9ba73/SteamLibrary/steamapps/common/Cyberpunk 2077}"
SHADERCACHE="${CALLISTO_SHADERCACHE:-/mnt/f4333173-dd02-4314-9fd0-2ce547a9ba73/SteamLibrary/steamapps/shadercache/1091500}"
INSTALL_DIR="${CALLISTO_INSTALL_DIR:-$HOME/.local/lib/callisto}"
SWAPS="${CALLISTO_SWAPS_DIR:-$MOD_DIR/swaps.skin.build}"
WORK="$MOD_DIR/dev/disasm/compute"

# The gloss strength ladder. `alpha_max` is the dominant lever by far: it is a
# GGX-alpha ceiling, and authored skin roughness in this game sits around
# 0.40-0.60, so a cap above ~0.16 (roughness 0.40) barely bites at all. The
# Fresnel half only broadens the falloff -- its saturate(2-r) amplitude term is
# clamped to 1 across this whole direction, so spec_gain is what moves it, and
# F' is clamped to 1 regardless (Fresnel cannot exceed unity).
#
#   level    roughness cap   Fresnel exponent
#   subtle       0.40              4.0     barely past vanilla; a damp sheen
#   medium       0.30              3.0     clearly wet, still plausible skin
#   strong       0.21              2.0     unmistakably oily -- the default
#   extreme      0.14              1.0     diagnostic: answers "is it working"
#                                          rather than "does it look right"
#
# Adding a level is one line here plus one in init.lua's SKIN_LEVELS.
# Format: "name:parent:k=v,k=v". `parent` is the rung this one must differ
# from (the ladder's byte-difference check); every rung must also differ from
# `off`. Since 44-LOW-HANGING-FRUIT the gloss knobs are spelled out in full on
# every rung, because --with-skinspec's KNOBS defaults are NOT identity
# (n_s=0.65, alpha_max=0.2025): a rung that names only its own knob would
# silently carry the default gloss as well.
#
# Realism axes (44), all skin-gated, all identity when absent:
#   alpha_scale    GGX alpha multiplier -- rougher/glossier while KEEPING the
#                  authored roughness variation the cap flattens (33 s5, 43 M2).
#                  alpha = roughness^2, so x1.3 is roughness x1.14, x0.7 is x0.84.
#   dcouple        diffuse/specular energy coupling, (1-s(1-NoL)^5)(1-s(1-NoV)^5)
#                  (43 M4): grazing skin darkens instead of glowing.
#   micro_k        albedo-driven micro-shadowing (43 M5): dark, porous skin
#                  self-shadows at grazing light; pale skin does not.
#   eye_alpha_max  class-8 (eye) alpha ceiling (31 s5, 43 M6): wet/glassy eyes.
G0="n_s=0.5,spec_gain=1.0,alpha_max=1.0"          # gloss OFF -- realism axes only
LEVELS=(
    # the original oily ladder: Fresnel reshape + roughness CEILING
    "subtle:off:n_s=0.60,spec_gain=1.0,alpha_max=0.1600"
    "medium:subtle:n_s=0.70,spec_gain=1.2,alpha_max=0.0900"
    "strong:medium:n_s=0.80,spec_gain=1.5,alpha_max=0.0450"
    "extreme:strong:n_s=0.90,spec_gain=2.0,alpha_max=0.0200"
    # roughness SCALE (keeps variation)
    "rough-1.3:off:$G0,alpha_scale=1.3"
    "rough-1.6:rough-1.3:$G0,alpha_scale=1.6"
    "gloss-0.7:off:$G0,alpha_scale=0.7"
    # single-axis rungs for attribution
    "couple:off:$G0,dcouple=1.0"
    "micro:off:$G0,micro_k=1.0"
    "eyes-wet:off:$G0,eye_alpha_max=0.0064"
    "eyes-glassy:eyes-wet:$G0,eye_alpha_max=0.0016"
    # the combined "realistic skin" candidates
    "real:rough-1.3:$G0,alpha_scale=1.3,dcouple=1.0,micro_k=1.0,eye_alpha_max=0.0064"
    "real-gloss:gloss-0.7:$G0,alpha_scale=0.7,dcouple=1.0,micro_k=1.0,eye_alpha_max=0.0064"
    # terminator colour bleed (43 A7 kept half; handoff/53). bleed-x is the
    # DIAGNOSTIC rung ("is it working"), not a look candidate -- 33's ladder
    # convention. real-gloss-bleed = the standing compute build + one variable,
    # and dev/build_gi_bleed.sh composes it under gi-50's raygens.
    "bleed:off:$G0,bleed_k=1.0"
    "bleed-x:bleed:$G0,bleed_k=3.0"
    "real-gloss-bleed:real-gloss:$G0,alpha_scale=0.7,dcouple=1.0,micro_k=1.0,eye_alpha_max=0.0064,bleed_k=1.0"
)

TIER=skin; EXTRA=(); SETS=0; SKINSPEC=0
while (( $# )); do
    case "$1" in
        --hunt) TIER=hunt ;;
        --tint) TIER=tint ;;
        # forwarded verbatim, so a tuning sweep is one command:
        #   ./dev/patch_compute_skin.sh --sets --set alpha_max=0.12
        --set) EXTRA+=(--set "${2:?--set needs K=V}"); shift ;;
        --with-skinspec) SKINSPEC=1 ;;
        --sets) SETS=1 ;;
        -*) echo "unknown flag: $1" >&2; exit 2 ;;
        *)  DUMP_DIR="$1" ;;
    esac
    shift
done
if (( SETS )) && [[ "$TIER" != skin ]]; then
    echo "--sets only applies to the skin tier" >&2; exit 2
fi
if (( SETS && SKINSPEC )); then
    echo "--sets already builds the with-skinspec variant; drop --with-skinspec" >&2
    exit 2
fi

mapfile -t targets < <(python3 - "$DUMP_DIR" <<'PY'
import glob, struct, sys
pi = struct.pack('<f', 0.318309873)
k = struct.pack('<f', 0.107508637)
for f in sorted(glob.glob(sys.argv[1] + '/*.dxil.spv')):
    d = open(f, 'rb').read()
    if pi in d and k in d:
        print(f)
PY
)
echo "=== tier $TIER | ${#targets[@]} anchored compute libs ==="

mkdir -p "$WORK"
RT_DONE=0

# Build the whole anchored set into $1 with the base args plus any extras.
# Sets BUILT to the number of modules patched. A function so --sets can run it
# once per rung against the same disassembly and the same base args, which is
# what makes the ladder a clean single-variable comparison: between any two
# levels the ONLY thing that moved is the three gloss knobs.
build_into() {
    local dest="$1"; shift
    local args=(--tier "$TIER")
    args+=("$@")
    # The command-line --set overrides go LAST so they win over a rung's own
    # values (argparse keeps the last assignment). Before 44 they went first,
    # so the documented `--sets --set alpha_max=0.06` was silently a no-op on
    # every rung that named alpha_max itself.
    if (( ${#EXTRA[@]} )); then args+=("${EXTRA[@]}"); fi

    mkdir -p "$dest"
    rm -f "$dest"/*.spv "$dest"/*.spvasm 2>/dev/null || true

    # The roundtrip check re-assembles and validates the UNPATCHED module to
    # prove the tooling is sane. That is worth doing once, not once per rung:
    # the ladder feeds all its builds the same disassembly, so repeating it
    # would multiply the build time for no extra signal.
    if (( RT_DONE )); then args+=(--no-roundtrip-check); fi
    local name asm f n
    rm -f "$dest"/.ok.* "$dest"/.bad.* 2>/dev/null || true

    # Disassemble first, sequentially. spirv-dis writes into $WORK, which is
    # SHARED by every set, so parallel sets racing on the same missing .spvasm
    # would interleave writes into one file. After the first set this is a
    # no-op anyway -- every disassembly is already cached.
    local asms=() missing=()
    for f in "${targets[@]}"; do
        name="$(basename "${f%.spv}")"
        asm="$WORK/$name.spvasm"
        if [[ ! -f "$asm" ]] && ! spirv-dis "$f" -o "$asm" 2>/dev/null; then
            missing+=("$name"); continue
        fi
        asms+=("$asm")
    done

    # The 77 module patches are independent processes sharing nothing but
    # $dest, and each writes only files named after its own module -- so this
    # parallelises with no locking. Serially a 29-set ladder is ~25 min on ONE
    # core with the other 23 idle. Set CALLISTO_JOBS=1 to get the old serial
    # order back when a failure needs reading in sequence.
    local jobs="${CALLISTO_JOBS:-$(nproc 2>/dev/null || echo 4)}"
    local argfile="$dest/.args"
    printf '%s\n' "${args[@]}" > "$argfile"
    printf '%s\0' "${asms[@]}" | \
        CB_DEST="$dest" CB_ARGS="$argfile" \
        CB_PY="$MOD_DIR/dev/patch_compute_skin.py" \
        xargs -0 -P "$jobs" -n1 bash -c '
            asm="$1"; n="$(basename "${asm%.spvasm}")"
            mapfile -t A < "$CB_ARGS"
            if python3 "$CB_PY" "$asm" "${A[@]}" --outdir "$CB_DEST" \
                    > "$CB_DEST/.skin.$n.json" 2>"$CB_DEST/.skin.$n.err"; then
                : > "$CB_DEST/.ok.$n"
            else
                : > "$CB_DEST/.bad.$n"
            fi' _
    rm -f "$argfile"

    local np nf
    np=$(find "$dest" -maxdepth 1 -name '.ok.*' | wc -l)
    nf=$(find "$dest" -maxdepth 1 -name '.bad.*' | wc -l)
    nf=$(( nf + ${#missing[@]} ))
    echo "patched $np, failed $nf${1:+  [$*]}"
    if (( nf > 0 )); then
        for f in "$dest"/.bad.*; do
            [[ -e "$f" ]] || continue
            n="$(basename "$f")"; n="${n#.bad.}"
            echo "  $n :: $(sed 's/.*error: //' "$dest/.skin.$n.err" 2>/dev/null | head -1 | cut -c1-70)"
        done | sort | uniq -c | sort -rn | head -8
    fi
    rm -f "$dest"/.ok.* "$dest"/.bad.* 2>/dev/null || true

    # A module can be "patched", validate clean, differ in bytes from the
    # baseline, and still carry ZERO splice sites -- every site rejected by
    # the dominance check while the knob OpConstants are emitted regardless.
    # That is not hypothetical: it is how the two GI resolvers shipped with
    # the whole skin BRDF silently absent (handoff/42-BOUNCE-LIGHT-GATE.md)
    # while every byte-level check in this script passed. Coverage is
    # asserted from the per-module reports, never inferred from a byte diff.
    python3 - "$dest" <<'COV' || exit 1
import glob, json, os, sys
dest = sys.argv[1]
tot = dict(mods=0, c1=0, chans=0, alphas=0, lifted=0, dcouple=0, micro=0,
           micro_skipped=0, bleed=0, bleed_skipped=0, bleed_dup=0)
bad = []
micro_short = []
for f in sorted(glob.glob(os.path.join(dest, '.skin.*.json'))):
    if os.path.getsize(f) == 0:
        continue                     # module failed to patch; already reported
    d = json.load(open(f))[0]
    di = d.get('diffuse', {})
    sp = d.get('skin_spec', {})
    ac = d.get('alpha_cap', {})
    tot['mods'] += 1
    tot['c1'] += di.get('c1_sites', 0)
    tot['chans'] += sp.get('chans', 0)
    tot['alphas'] += len(ac.get('alphas', []))
    tot['dcouple'] += di.get('dcouple_sites', 0)
    tot['micro'] += di.get('micro_sites', 0)
    nms = len(di.get('micro_skipped', []))
    tot['micro_skipped'] += nms
    if nms:
        micro_short.append('%s:%d/%d' % (d['module'][:8], di.get('micro_sites', 0),
                                         di.get('micro_sites', 0) + nms))
    tot['bleed'] += di.get('bleed_sites', 0)
    tot['bleed_skipped'] += len(di.get('bleed_skipped', []))
    tot['bleed_dup'] += len(di.get('bleed_dup', []))
    if 'OpPhi' in d.get('class_gate', {}).get('def', ''):
        tot['lifted'] += 1
    n = (len(di.get('skipped_dom', [])) + len(sp.get('skipped_dom', []))
         + len(ac.get('skipped_dom', [])))
    if n:
        bad.append((d['module'], '%d site(s) skipped_dom' % n))
    elif di.get('c1_sites', 0) == 0:
        bad.append((d['module'], 'no c1 site at all'))
print('  coverage: %d modules, %d c1 sites, %d gloss channels, %d alphas'
      ' (%d gate(s) lifted onto a class phi)'
      % (tot['mods'], tot['c1'], tot['chans'], tot['alphas'], tot['lifted']))
if tot['dcouple'] or tot['micro'] or tot['micro_skipped']:
    # micro-shadowing needs the site's diffuse colour; ~25 of 181 sites fan
    # out through light*shadow only and have no reachable albedo (44 s3).
    # Those sites keep c1 (and coupling) and skip micro -- reported, never
    # fatal, because the skip is structural, not a gate failure.
    print('  realism: %d coupling sites, %d micro-shadow sites (%d sites have '
          'no reachable albedo: %s)' % (tot['dcouple'], tot['micro'],
                                         tot['micro_skipped'],
                                         ' '.join(micro_short) or '-'))
if tot['bleed'] or tot['bleed_skipped'] or tot['bleed_dup']:
    # bleed shares micro's structural limit: no reachable albedo triple means
    # no channel identity, so those sites skip (never guess a channel). A
    # nonzero dup count would mean two sites share a fan-out FMul -- census
    # says zero; if it ever fires, read handoff/53 before trusting the rung.
    print('  bleed: %d sites, %d skipped (no channel triple), %d dup-guarded'
          % (tot['bleed'], tot['bleed_skipped'], tot['bleed_dup']))
if bad:
    sys.stderr.write('  SITES SKIPPED -- the class gate does not reach the shading:\n')
    for m, why in bad[:10]:
        sys.stderr.write('    %s :: %s\n' % (m, why))
    sys.exit(1)
COV
    BUILT=$np
    RT_DONE=1
    (( BUILT > 0 )) || { echo "nothing patched" >&2; exit 1; }
}

if (( SETS )); then
    echo "--- set 'off' (tier-1 c1 only, the gloss-free baseline) ---"
    build_into "$MOD_DIR/swaps.skin.off"
    off_n=$BUILT
    BUILT_SETS=(off)
    # PARENT[name] is the set this one must differ from: one step down its own
    # axis. Comparing every rung only against `off` would pass a ladder whose
    # top three rungs were identical to each other, which is precisely the
    # "two rungs are the same build under two names" failure the check exists
    # to catch.
    declare -A PARENT=()
    for spec in "${LEVELS[@]}"; do
        IFS=':' read -r lvl parent kv <<< "$spec"
        [[ -n "$kv" ]] || { echo "LEVELS entry '$spec' is not name:parent:k=v" >&2; exit 2; }
        setargs=(--with-skinspec)
        IFS=',' read -ra kvs <<< "$kv"
        for one in "${kvs[@]}"; do setargs+=(--set "$one"); done
        echo "--- set '$lvl' (c1 + $kv; parent $parent) ---"
        build_into "$MOD_DIR/swaps.skin.$lvl" "${setargs[@]}"
        PARENT[$lvl]="$parent"
        BUILT_SETS+=("$lvl")
    done

    # Equal coverage across every set is what makes the ladder attributable: if
    # one level patched a module another did not, moving the selector would also
    # change which modules are vanilla, and the observation would mean nothing.
    ref="$(cd "$MOD_DIR/swaps.skin.off" && ls *.spv 2>/dev/null | sort)"
    for lvl in "${BUILT_SETS[@]}"; do
        cur="$(cd "$MOD_DIR/swaps.skin.$lvl" && ls *.spv 2>/dev/null | sort)"
        if [[ "$cur" != "$ref" ]]; then
            echo "set '$lvl' coverage differs from 'off' -- not a clean A/B" >&2
            diff <(echo "$ref") <(echo "$cur") | head -10 >&2
            exit 1
        fi
    done

    # Every level must differ from the baseline AND from the level below it, or
    # two rungs are the same build under two names and the selector would
    # silently compare nothing. This is what catches a knob that turned out not
    # to reach the shader at all.
    for lvl in "${BUILT_SETS[@]}"; do
        [[ "$lvl" == off ]] && continue
        prev="${PARENT[$lvl]:-off}"
        d_base=0; d_prev=0
        for f in "$MOD_DIR/swaps.skin.off"/*.spv; do
            b="$(basename "$f")"
            cmp -s "$f" "$MOD_DIR/swaps.skin.$lvl/$b" || d_base=$((d_base+1))
            cmp -s "$MOD_DIR/swaps.skin.$prev/$b" "$MOD_DIR/swaps.skin.$lvl/$b" || d_prev=$((d_prev+1))
        done
        printf '  %-16s %3d module(s) differ from off, %3d from %s\n' \
               "$lvl" "$d_base" "$d_prev" "$prev"
        (( d_base > 0 )) || { echo "'$lvl' is byte-identical to 'off'" >&2; exit 1; }
        (( d_prev > 0 )) || { echo "'$lvl' is byte-identical to '$prev'" >&2; exit 1; }
    done
    SWAPS="$MOD_DIR/swaps.skin.off"      # what lands in swaps.skin/ as the default
else
    if (( SKINSPEC )); then
        build_into "$SWAPS" --with-skinspec
        echo "NOTE: this build welds the gloss to the skin overlay -- there is"
        echo "      no way to A/B it against c1 alone. Use --sets for that."
    else
        build_into "$SWAPS"
    fi
fi

DEST="$INSTALL_DIR/swaps.skin"
mkdir -p "$DEST"
rm -f "$DEST"/*.spv
cp -f "$SWAPS"/*.spv "$DEST/"
cp -f "$MOD_DIR/libVkLayer_callisto_spvswap.so" "$INSTALL_DIR/" 2>/dev/null || true
inst=("$DEST"/*.spv)
echo "installed ${#inst[@]} compute swap(s) -> $DEST (overlay 'skin')"

# --sets additionally PARKS every rung in skin.set/<level>/. The layer never
# reads that dir -- it only serves swaps.<name> -- so parking is inert until
# sync_settings.sh copies the level named by skinspec into swaps.skin/ at
# launch. The rm -rf is load-bearing: level names change (the old two-set
# {off,on} became a five-rung ladder), and a stale dir left behind is a level
# the selector can still be pointed at while nothing rebuilds it.
if (( SETS )); then
    # probe-* rungs belong to dev/patch_subtype_probe.sh --install; before 44
    # this rm -rf silently deleted them and the CET selector kept naming them.
    for old in "$INSTALL_DIR/skin.set"/*/; do
        [[ -d "$old" ]] || continue
        case "$(basename "$old")" in probe-*) ;; *) rm -rf "$old" ;; esac
    done
    for v in "${BUILT_SETS[@]}"; do
        vd="$INSTALL_DIR/skin.set/$v"
        mkdir -p "$vd"
        rm -f "$vd"/*.spv
        # -p so the mtime comes from the build, not from this copy: without it
        # every launch would hash a fresh payload and evict the pipeline caches
        # (the cp -p GOTCHA -- it cost a session of "the mod does nothing").
        cp -pf "$MOD_DIR/swaps.skin.$v"/*.spv "$vd/"
    done
    echo "parked ${#BUILT_SETS[@]} sets -> $INSTALL_DIR/skin.set: ${BUILT_SETS[*]}"
    echo "  the CET selector 'Skin build' (skinspec) picks between them"
fi

if [[ -f "$INSTALL_DIR/skin.disable" ]]; then
    echo "NOTE: skin.disable present -- the overlay is currently OFF"
fi

if [[ -z "${CALLISTO_NO_CACHE_CLEAR:-}" ]]; then
    rm -rf "$GAME_DIR/bin/x64/GLCache"/* "$SHADERCACHE"/* 2>/dev/null || true
    echo "caches cleared"
fi
echo "next: : > ~/callisto_swap.jsonl ; launch ; face in frame"
