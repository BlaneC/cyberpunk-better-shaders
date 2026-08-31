#!/usr/bin/env bash
# probe-gi: the raygen GI-writer probe (handoff/48 §8, built by handoff/50).
#
#   ./dev/build_probe_gi.sh              # build into swaps.probe.gi (no install)
#   ./dev/build_probe_gi.sh --install    # ALSO park as skin.set/probe-gi
#
# One rung, three families, one launch: class-1-gated hue paint at the raygen
# radiance writes -- rgs_reference_main x12 GREEN, restirgi diffuse x4 RED,
# restirgi specular x4 BLUE. The compute probe is OFF (the rung ships no
# compute files, so the 77 resolve modules serve vanilla for the launch).
#
# SOURCES -- this is the part that keeps the launch interpretable:
#   * The 12 rgs_reference_main come from ser.set/class, which is itself
#     built on ptq/<combo>/base. Serving a dump-based paint would un-patch
#     ptq AND SER for those ids (the skin overlay outranks both; GOTCHAS
#     "an overlay reject must fall through, never to vanilla"). ser=class is
#     required at launch: sync_settings.sh skips materialising swaps.ser when
#     the skin rung owns the raygen ids (swaps.ser would win first-file-wins
#     and the paint would be DEAD), so the SER hints ride these files.
#   * The 8 rgs_restirgi_* come from the dump: with shadowset=full-shadow
#     (the shipping default) nothing else patches those ids. shadowset=full
#     DOES patch them; sync refuses the rung in that case.
#   * Two rgs_reference_main permutations (40c6faab, ab7f1822) accumulate
#     radiance through SSBO atomics and have no image radiance write to
#     paint. They ship as UNPAINTED passthroughs of the ser source, so all
#     12 reference ids still serve from one overlay. Both have 0 recorded
#     dispatches; if the launch journal disagrees, a green null on S2 is not
#     interpretable as "reference does not write it" -- check
#     `./dev/ab_launch_audit.py` for their dispatch lines before reading a
#     null.
#
# The MANIFEST.txt written here is a provenance CONTRACT: sync_settings.sh
# recomputes ser_sha over ser.set/class and compares ptq_sha against the
# materialised swaps.ptq at every launch, and REFUSES the rung on mismatch
# (the swaps.ser staleness guard, applied one overlay up). A PT-switch change
# after this build makes the next launch refuse loudly instead of serving a
# stale combo silently.
set -euo pipefail

MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DUMP_DIR="${CALLISTO_DUMP_DIR:-$HOME/callisto_dump}"
INSTALL_DIR="${CALLISTO_INSTALL_DIR:-$HOME/.local/lib/callisto}"
SER_SRC="$INSTALL_DIR/ser.set/class"
WORK="$MOD_DIR/dev/disasm/probe-gi"
DEST="$MOD_DIR/swaps.probe.gi"
PY="$MOD_DIR/dev/patch_subtype_probe.py"

DO_INSTALL=0
[[ "${1:-}" == "--install" ]] && DO_INSTALL=1

PASS=(40c6faab52a13874 ab7f1822eeb0331b)
RESTIRGI=(006ba4e3c8c05205 038867e9a3bf0626 5e1e98e44d854712 fc60b8a0b56529b8
          1ca55ed0fc70d56f a3b07b0f4f4f79b8 174dee89ec119981 9d117caf3ef46c59)

# --- source freshness: ser.set/class against its own recorded source -------
[[ -f "$SER_SRC/MANIFEST.txt" ]] || { echo "no $SER_SRC/MANIFEST.txt -- run ./dev/patch_ser.sh --install" >&2; exit 1; }
ser_from="$(sed -n 's/.*src="\([^"]*\)".*/\1/p' "$SER_SRC/MANIFEST.txt" | head -1)"
ptq_sha="$(sed -n 's/.*src_sha=\([0-9a-f]*\).*/\1/p' "$SER_SRC/MANIFEST.txt" | head -1)"
ptq_now="$(cat "$ser_from"/*.rgs_reference_main.spv 2>/dev/null | sha256sum | cut -c1-16)"
if [[ -z "$ptq_sha" || "$ptq_sha" != "$ptq_now" ]]; then
    echo "ser.set/class is STALE against $ser_from ($ptq_sha vs $ptq_now)" >&2
    echo "rebuild it first: ./dev/patch_ser.sh --install --from $ser_from" >&2
    exit 1
fi
ser_sha="$(cat "$SER_SRC"/*.rgs_reference_main.spv | sha256sum | cut -c1-16)"

# --- disassemble fresh (SER-patched sources differ from dev/disasm/live) ---
rm -rf "$WORK" "$DEST"
mkdir -p "$WORK" "$DEST"
srcs=()
for f in "$SER_SRC"/*.rgs_reference_main.spv; do
    h="$(basename "$f")"; h="${h%%.*}"
    for p in "${PASS[@]}"; do [[ "$h" == "$p" ]] && continue 2; done
    srcs+=("$f")
done
for h in "${RESTIRGI[@]}"; do
    f=("$DUMP_DIR/$h".rgs_restirgi_*.spv)
    [[ -f "${f[0]}" ]] || { echo "missing $h in $DUMP_DIR" >&2; exit 1; }
    srcs+=("${f[0]}")
done
(( ${#srcs[@]} == 18 )) || { echo "expected 18 paint sources, have ${#srcs[@]}" >&2; exit 1; }
for f in "${srcs[@]}"; do
    n="$(basename "${f%.spv}")"
    spirv-dis "$f" -o "$WORK/$n.spvasm"
done

# --- patch, parallel ---------------------------------------------------------
jobs="${CALLISTO_JOBS:-$(nproc 2>/dev/null || echo 4)}"
printf '%s\0' "$WORK"/*.spvasm | \
    CB_DEST="$DEST" CB_PY="$PY" xargs -0 -P "$jobs" -n1 bash -c '
        asm="$1"; n="$(basename "${asm%.spvasm}")"
        if python3 "$CB_PY" "$asm" --tier gi --outdir "$CB_DEST" \
                > "$CB_DEST/.rep.$n.json" 2>"$CB_DEST/.err.$n"; then
            : > "$CB_DEST/.ok.$n"
        else
            : > "$CB_DEST/.bad.$n"
        fi' _

nbad=$(find "$DEST" -maxdepth 1 -name '.bad.*' | wc -l)
if (( nbad > 0 )); then
    echo "!! $nbad module(s) FAILED:" >&2
    for f in "$DEST"/.bad.*; do
        n="${f##*/.bad.}"
        echo "--- $n"; tail -3 "$DEST/.err.$n" | sed 's/^/    /'
    done >&2
    exit 1
fi

# --- passthroughs ------------------------------------------------------------
for h in "${PASS[@]}"; do
    cp -pf "$SER_SRC/$h.rgs_reference_main.spv" "$DEST/"
done

# --- assertions (the site count, not the byte diff -- GOTCHAS) ---------------
python3 - "$DEST" <<'PYA'
import glob, json, os, subprocess, sys
dest = sys.argv[1]
reps = []
for f in sorted(glob.glob(dest + "/.rep.*.json")):
    reps += json.load(open(f))
fams = {"reference": 0, "gi-diffuse": 0, "gi-specular": 0}
fail = 0
for r in reps:
    g = r["gi"]
    fams[g["family"]] += 1
    if r["spirv_val"] != "clean":
        print(f"!! {r['ident']}: spirv_val={r['spirv_val']}"); fail = 1
    if not g["painted"]:
        print(f"!! {r['ident']}: ZERO painted writes"); fail = 1
    if g["skipped_dom"]:
        print(f"!! {r['ident']}: skipped_dom={g['skipped_dom']}"); fail = 1
    kinds = ",".join(sorted({p["kind"] for p in g["painted"]}))
    print(f"  {r['ident'][:44]:44s} {g['family']:12s} painted={len(g['painted'])} ({kinds})"
          f" zero={len(g['skipped_zero'])} scalar={len(g['skipped_scalar'])}")
if len(reps) != 18:
    print(f"!! expected 18 paint reports, have {len(reps)}"); fail = 1
if fams != {"reference": 10, "gi-diffuse": 4, "gi-specular": 4}:
    print(f"!! family split wrong: {fams}"); fail = 1
spvs = sorted(glob.glob(dest + "/*.spv"))
if len(spvs) != 20:
    print(f"!! expected 20 .spv in {dest}, have {len(spvs)}"); fail = 1
for s in spvs:
    v = subprocess.run(["spirv-val", s], capture_output=True)
    if v.returncode != 0:
        print(f"!! spirv-val fails on parked {os.path.basename(s)}"); fail = 1
print(f"  {len(reps)} painted + 2 passthrough = {len(spvs)} modules, all spirv-val clean"
      if not fail else "  BUILD BAD")
sys.exit(fail)
PYA

rm -f "$DEST"/.ok.* "$DEST"/.err.* 2>/dev/null || true

# --- manifest (line 1 is echoed into the layer journal at launch) ------------
printf 'probe-gi ref=12(painted=10,atomic-pass=2) gidiff=4 gispec=4 src_ser="ser.set/class" ser_sha=%s ptq_sha=%s restirgi_src=dump declares_ser=1 built=%s\n' \
    "$ser_sha" "$ptq_sha" "$(date -Is)" > "$DEST/MANIFEST.txt"
{ echo "# paint: reference GREEN x(0.30,3.00,0.30), gi-diffuse RED x(3.00,0.30,0.30), gi-specular BLUE x(0.30,0.30,3.00), gated on class==1"
  echo "# 40c6faab52a13874 + ab7f1822eeb0331b are UNPAINTED (atomic-SSBO accumulators, 0 recorded dispatches)."
  echo "# If the launch journal shows either dispatching, a green null on S2 is uninterpretable -- see dev/build_probe_gi.sh header."
} >> "$DEST/MANIFEST.txt"

if (( DO_INSTALL )); then
    d="$INSTALL_DIR/skin.set/probe-gi"
    mkdir -p "$d"; rm -f "$d"/*.spv "$d/MANIFEST.txt"
    cp -pf "$DEST"/*.spv "$DEST/MANIFEST.txt" "$d/"
    echo "parked -> $d  (select with skinspec=probe-gi; needs ser=class, shadowset=full-shadow)"
else
    echo "NOT installed. To park:  ./dev/build_probe_gi.sh --install"
fi
