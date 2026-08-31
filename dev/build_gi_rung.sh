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
[[ "${1:-}" == "--install" ]] && DO_INSTALL=1

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

for S in 50 100; do
    if [[ "$S" == 100 ]]; then STR=1.0; else STR=0.5; fi
    DEST="$MOD_DIR/swaps.gi.$S"
    rm -rf "$DEST"; mkdir -p "$DEST"
    python3 "$PY" --strength "$STR" --out "$DEST" "$WORK"/*.spvasm

    # --- assertions from the patcher's own reports -------------------------
    python3 - "$DEST" <<'PYA'
import json, glob, sys
d = sys.argv[1]
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
for r in sp:
    g = r['gi_c1']
    assert g['painted'] and not g['skipped_dom'], r['ident']
    assert g['flat_factor'] > 1.0, r['ident']
print("  reports: 2 st-lit-arm + 2 sp-flat, all clean")
PYA

    # --- assemble the rung: real-gloss + ser reference + the 4 splices -----
    cp -pf "$RG_SRC"/*.spv "$DEST/"
    cp -pf "$SER_SRC"/*.rgs_reference_main.spv "$DEST/"
    n=$(ls "$DEST"/*.spv | wc -l)
    [[ "$n" == 93 ]] || { echo "rung gi-$S has $n modules, expected 93 (77+12+4)" >&2; exit 1; }
    for f in "$DEST"/*.spv; do spirv-val "$f" || { echo "spirv-val FAILED: $f" >&2; exit 1; }; done

    flat=$(python3 -c "import sys; sys.path.insert(0,'$MOD_DIR/dev'); from patch_gi_c1 import cbar; print('%.4f' % cbar($STR))")
    {
      printf 'gi-%s restirgi_c1=4(st=2,sp-flat=2) strength=%s flat=%s compute=77(real-gloss) ref=12(pass-through) src_ser="ser.set/class" ser_sha=%s ptq_sha=%s restirgi_src=dump declares_ser=1 built=%s\n' \
        "$S" "$STR" "$flat" "$ser_sha" "$ptq_sha" "$(date -Iseconds)"
      echo '# tier-1 c1 (NoL-half / flat mean) on ReSTIR-GI diffuse skin; see handoff/50'
      echo '# sync_settings.sh verifies ser_sha+ptq_sha at every launch and refuses on mismatch'
    } > "$DEST/MANIFEST.txt"
    echo "  built swaps.gi.$S: 93 modules, all spirv-val clean"

    if [[ "$DO_INSTALL" == 1 ]]; then
        park="$INSTALL_DIR/skin.set/gi-$S"
        mkdir -p "$park"; rm -f "$park"/*.spv "$park/MANIFEST.txt"
        cp -pf "$DEST"/*.spv "$DEST/MANIFEST.txt" "$park/"
        echo "  parked -> $park"
    fi
done

[[ "$DO_INSTALL" == 1 ]] || echo "NOT installed. To park: ./dev/build_gi_rung.sh --install"
echo "select with skinspec=gi-50 (or gi-100); needs ser=class, shadowset=full-shadow"
