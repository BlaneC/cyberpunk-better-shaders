#!/usr/bin/env bash
# gi-50 / gi-100: tier-1 c1 on bounce-lit skin via the ReSTIR-GI diffuse
# raygens -- the 48 §9 Site A splice, family named on screen by the probe-gi
# launch (handoff/50).
#
#   ./dev/build_gi_rung.sh              # build both rungs (no install)
#   ./dev/build_gi_rung.sh --install    # ALSO park as skin.set/gi-{50,100}
#
# Each rung dir is REAL-GLOSS PLUS ONE VARIABLE:
#   * 77 compute modules  <- skin.set/real-gloss unchanged (the standing look;
#     without them the rung would silently drop the on-screen winner and the
#     A/B would carry two variables)
#   * 12 rgs_reference_main <- ser.set/class unchanged (ptq+SER preserved;
#     ser=class required, sync serves the hints from this overlay -- same
#     contract as probe-gi)
#   * 4 rgs_restirgi diffuse <- dump + patch_gi_c1.py: class-1-gated c1.
#     Spatiotemporal pair: c1's NoL-half at the tail shading triple.
#     Spatial pair: flat E[c1] at the write (no honest angle exists there;
#     both pairs write registers[5]+1 so they are alternative finals, never
#     chained -- no double-scaling).
#   * restirgi SPECULAR ids are NOT shipped: nothing else patches them
#     (full-shadow required, sync enforces), so omitting = vanilla = intended.
#
# gi-50 halves the rho distance to identity (1.175/1.125): 42 §6, start the
# rung below where the eye sits -- mixed-light skin already gets the compute
# resolvers' c1 on its direct term.
#
# MANIFEST.txt is the same provenance contract as probe-gi: sync recomputes
# ser_sha/ptq_sha at every launch and refuses the rung on mismatch.
set -euo pipefail

MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DUMP_DIR="${CALLISTO_DUMP_DIR:-$HOME/callisto_dump}"
INSTALL_DIR="${CALLISTO_INSTALL_DIR:-$HOME/.local/lib/callisto}"
SER_SRC="$INSTALL_DIR/ser.set/class"
RG_SRC="$INSTALL_DIR/skin.set/real-gloss"
WORK="$MOD_DIR/dev/disasm/gi-c1"
PY="$MOD_DIR/dev/patch_gi_c1.py"

DO_INSTALL=0
BOUNCE=0
NORM=0
FLATF=0
FLATF_V=1.0
while (( $# )); do
    a="$1"
    case "$a" in
        --install) DO_INSTALL=1 ;;
        # 78: gi-50bn -- the SAME bounce bleed, holding the triple's Rec.709
        # luminance (m_G no longer 1). Hue and saturation are bit-for-bit
        # gi-50b's; the +10.4% energy the 53 form added at the band floor is
        # gone. One variable vs gi-50b: the 2 ST raygens.
        --luma-neutral) BOUNCE=1; NORM=1 ;;
        # 78: gi-50bnd -- gi-50bn plus c1's grazing-LIGHT lobe pulled to
        # identity (rho_f -> 1.0), the other half of the band lift. The SP
        # pair's flat factor follows (it is E[c1] and must not disagree with
        # the ST pair about what c1 is), so this rung moves FOUR raygens.
        --flat-front) BOUNCE=1; NORM=1; FLATF=1 ;;
        # the half-step, for when identity reads too flat: --flat-front
        # --rho-f 1.09 rebuilds gi-50bnd in place at half the pull.
        --rho-f) FLATF_V="${2:?--rho-f needs a value}"; shift ;;
        # 74: build gi-50b INSTEAD -- gi-50's exact c1 splice plus the
        # terminator bleed (53's closed form, same amplitudes) at the ST
        # pair's tail NoL, i.e. the bleed on BOUNCE light. The SP pair and
        # the 12 reference files are byte-identical to gi-50's (asserted
        # below), so gi-50 vs gi-50b is one variable: two files.
        --bounce-bleed) BOUNCE=1 ;;
        *) echo "unknown flag: $a" >&2; exit 2 ;;
    esac
    shift
done
(( FLATF )) || [[ "$FLATF_V" == 1.0 ]] || { echo "--rho-f needs --flat-front" >&2; exit 2; }

DIFF=(006ba4e3c8c05205 038867e9a3bf0626 5e1e98e44d854712 fc60b8a0b56529b8)

# --- source freshness: ser.set/class against its own recorded source -------
[[ -f "$SER_SRC/MANIFEST.txt" ]] || { echo "no $SER_SRC/MANIFEST.txt -- run ./dev/patch_ser.sh --install" >&2; exit 1; }
ser_from="$(sed -n 's/.*src="\([^"]*\)".*/\1/p' "$SER_SRC/MANIFEST.txt" | head -1)"
ptq_sha="$(sed -n 's/.*src_sha=\([0-9a-f]*\).*/\1/p' "$SER_SRC/MANIFEST.txt" | head -1)"
ptq_now="$(cat "$ser_from"/*.rgs_reference_main.spv 2>/dev/null | sha256sum | cut -c1-16)"
if [[ -z "$ptq_sha" || "$ptq_sha" != "$ptq_now" ]]; then
    echo "ser.set/class is STALE against $ser_from ($ptq_sha vs $ptq_now)" >&2
    echo "re-run: ./dev/patch_ser.sh --install --from $ser_from" >&2
    exit 1
fi
ser_sha="$(cat "$SER_SRC"/*.rgs_reference_main.spv | sha256sum | cut -c1-16)"
[[ -d "$RG_SRC" ]] || { echo "no $RG_SRC -- run ./dev/patch_compute_skin.sh --sets" >&2; exit 1; }
rg_n="$(ls "$RG_SRC"/*.spv | wc -l)"
[[ "$rg_n" == 77 ]] || { echo "$RG_SRC has $rg_n modules, expected 77" >&2; exit 1; }

# --- fresh disassembly of the 4 dump sources -------------------------------
rm -rf "$WORK"; mkdir -p "$WORK"
for h in "${DIFF[@]}"; do
    src=$(ls "$DUMP_DIR/$h".rgs_restirgi_*.spv)
    spirv-dis "$src" -o "$WORK/$(basename "${src%.spv}").spvasm"
done

RUNGS=(50 100)
if (( BOUNCE )); then
    RUNGS=(50b); (( NORM )) && RUNGS=(50bn); (( FLATF )) && RUNGS=(50bnd)
fi
for S in "${RUNGS[@]}"; do
    STR=0.5; BLEED=0.0; NRM=0.0; RHOF=()
    [[ "$S" == 100 ]] && STR=1.0
    case "$S" in 50b*) BLEED=1.0 ;; esac
    case "$S" in 50bn*) NRM=1.0 ;; esac
    [[ "$S" == 50bnd ]] && RHOF=(--rho-f "$FLATF_V")
    DEST="$MOD_DIR/swaps.gi.$S"
    rm -rf "$DEST"; mkdir -p "$DEST"
    python3 "$PY" --strength "$STR" --bleed "$BLEED" --bleed-norm "$NRM" \
        "${RHOF[@]+"${RHOF[@]}"}" --out "$DEST" "$WORK"/*.spvasm

    # --- assertions from the patcher's own reports -------------------------
    python3 - "$DEST" "$BLEED" "$NRM" <<'PYA'
import json, glob, sys
d, bleed, norm = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
reps = [json.load(open(f)) for f in sorted(glob.glob(d + '/*.json'))]
assert len(reps) == 4, f"{len(reps)} reports, want 4"
st = [r for r in reps if r['gi_c1']['mode'] == 'st-lit-arm']
sp = [r for r in reps if r['gi_c1']['mode'] == 'sp-flat']
assert len(st) == 2 and len(sp) == 2, (len(st), len(sp))
for r in reps:
    assert r['spirv_val'] == 'clean', r['ident']
for r in st:
    s = r['gi_c1']['spliced']
    assert len(s) == 3 and all(x['uses_rewritten'] >= 2 for x in s), r['ident']
    assert r['gi_c1'].get('bleed_k', 0.0) == bleed, r['ident']
    if bleed > 0:
        # the bleed is per-channel; a wrong or unproven channel identity
        # must fail the BUILD, never ship a guessed R/B (39's rule).
        assert sorted(x['chan'] for x in s) == [0, 1, 2], r['ident']
    assert r['gi_c1'].get('bleed_norm', 0.0) == norm, r['ident']
for r in sp:
    g = r['gi_c1']
    assert g['painted'] and not g['skipped_dom'], r['ident']
    assert g['flat_factor'] > 1.0, r['ident']
print("  reports: 2 st-lit-arm + 2 sp-flat, all clean"
      + (", bleed chans {0,1,2} on both ST" if bleed > 0 else "")
      + (", luminance held (beta=%.2f)" % norm if norm > 0 else ""))
PYA

    # --- assemble the rung: real-gloss + ser reference + the 4 splices -----
    cp -pf "$RG_SRC"/*.spv "$DEST/"
    cp -pf "$SER_SRC"/*.rgs_reference_main.spv "$DEST/"
    n=$(ls "$DEST"/*.spv | wc -l)
    [[ "$n" == 93 ]] || { echo "rung gi-$S has $n modules, expected 93 (77+12+4)" >&2; exit 1; }
    for f in "$DEST"/*.spv; do spirv-val "$f" || { echo "spirv-val FAILED: $f" >&2; exit 1; }; done

    RHOFARG=None; [[ "$S" == 50bnd ]] && RHOFARG="$FLATF_V"
    flat=$(python3 -c "import sys; sys.path.insert(0,'$MOD_DIR/dev'); from patch_gi_c1 import cbar; print('%.4f' % cbar($STR, rho_f=$RHOFARG))")
    BTOK=""; (( BOUNCE )) && BTOK="bounce_bleed=$BLEED "
    (( NORM )) && BTOK="$BTOK""bleed_norm=$NRM "
    (( FLATF )) && BTOK="$BTOK""rho_f=$FLATF_V "
    {
      printf 'gi-%s restirgi_c1=4(st=2,sp-flat=2) strength=%s flat=%s %scompute=77(real-gloss) ref=12(pass-through) src_ser="ser.set/class" ser_sha=%s ptq_sha=%s restirgi_src=dump declares_ser=1 built=%s\n' \
        "$S" "$STR" "$flat" "$BTOK" "$ser_sha" "$ptq_sha" "$(date -Iseconds)"
      echo '# tier-1 c1 (NoL-half / flat mean) on ReSTIR-GI diffuse skin; see handoff/50'
      (( BOUNCE )) && echo '# + terminator bleed (53 closed form) at the ST tail NoL -- bleed on BOUNCE light; see handoff/74'
      (( NORM )) && echo '# + the bleed holds Rec.709 luminance (hue/saturation identical, the energy add gone); see handoff/78'
      (( FLATF )) && echo "# + c1 grazing-light lobe pulled to rho_f=$FLATF_V, ST shape and SP mean both; see handoff/78"
      echo '# sync_settings.sh verifies ser_sha+ptq_sha at every launch and refuses on mismatch'
    } > "$DEST/MANIFEST.txt"
    echo "  built swaps.gi.$S: 93 modules, all spirv-val clean"

    # gi-50b's one-variable guarantee against the PARKED gi-50: the two ST
    # raygens differ (the bleed reached them), the SP pair and the 12
    # reference files are byte-identical, the 77 compute byte-identical.
    if (( BOUNCE )); then
        # Each rung is ONE variable off the rung below it, so each compares
        # against a different parked base: 50b vs 50 (the bleed), 50bn vs 50b
        # (the luminance hold), 50bnd vs 50bn (c1's front lobe -- which moves
        # the SP pair too, since their flat factor is E[c1]).
        BASE=gi-50; WANT=2
        [[ "$S" == 50bn ]] && BASE=gi-50b
        [[ "$S" == 50bnd ]] && { BASE=gi-50bn; WANT=4; }
        G50="$INSTALL_DIR/skin.set/$BASE"
        [[ -d "$G50" ]] || { echo "no parked $BASE to compare gi-$S against" >&2; exit 1; }
        d=0; dn=""
        for f in "$G50"/*.rgs_*.spv; do
            cmp -s "$f" "$DEST/$(basename "$f")" || { d=$((d+1)); dn="$dn $(basename "$f")"; }
        done
        [[ "$d" == "$WANT" ]] || { echo "gi-$S differs from $BASE in $d of 16 raygens ($dn) -- want exactly $WANT" >&2; exit 1; }
        case "$dn" in *spatiotemporal*spatiotemporal*) ;; *)
            echo "gi-$S's raygen delta does not include the ST pair:$dn" >&2; exit 1 ;; esac
        if [[ "$WANT" == 4 ]]; then
            case "$dn" in *rgs_restirgi_spatial.spv*rgs_restirgi_spatial.spv*) ;; *)
                echo "gi-$S should move the SP pair too (E[c1] follows rho_f):$dn" >&2; exit 1 ;; esac
        fi
        dc=0
        for f in "$G50"/*.dxil.spv; do
            cmp -s "$f" "$DEST/$(basename "$f")" || dc=$((dc+1))
        done
        [[ "$dc" == 0 ]] || { echo "gi-$S's compute differs from $BASE in $dc modules -- NOT one variable" >&2; exit 1; }
        echo "  gi-$S vs $BASE: raygen delta =$dn; compute 0/77 differ (one variable)"
    fi

    if [[ "$DO_INSTALL" == 1 ]]; then
        park="$INSTALL_DIR/skin.set/gi-$S"
        mkdir -p "$park"; rm -f "$park"/*.spv "$park/MANIFEST.txt"
        cp -pf "$DEST"/*.spv "$DEST/MANIFEST.txt" "$park/"
        echo "  parked -> $park"
    fi
done

[[ "$DO_INSTALL" == 1 ]] || echo "NOT installed. To park: ./dev/build_gi_rung.sh --install"
echo "select with skinspec=gi-50 (or gi-100); needs ser=class, shadowset=full-shadow"
