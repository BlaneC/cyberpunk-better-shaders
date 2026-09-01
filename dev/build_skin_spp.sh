#!/usr/bin/env bash
# Skin-only sample count rungs (handoff/29 part B4, build handoff/77).
#
#   ./dev/build_skin_spp.sh              # build both rungs (no install)
#   ./dev/build_skin_spp.sh --install    # ALSO park as skin.set/<base>-spp4{d,}
#
# Two rungs, a one-variable ladder over the standing base:
#   <base>-spp4d  the 6 runtime-bound rgs_reference_main get the skin-gated
#                 sample count (the engine's own live loop, retargeted --
#                 low risk); the 4 baked permutations stay pass-through.
#   <base>-spp4   the same PLUS the 4 baked permutations rewired (the 29
#                 B4 loop surgery -- carries the record-store residual risk,
#                 handoff/77 sec 4). d-vs-full is the attribution A/B.
#
# Base: skin.set/gi-50b-bleed-oil-sheen (override: CALLISTO_SPP_BASE). Its
# 77 compute + 4 restirgi + 2 atomic reference files ship VERBATIM
# (cmp-asserted); its 10 paintable rgs_reference_main are ser.set/class
# pass-throughs (cmp-asserted) and are what gets patched. MANIFEST
# provenance (src_ser/ser_sha/ptq_sha) carries over verbatim, so sync's
# gi_refuse contract holds: needs ser=class + shadowset=full-shadow, and a
# PT-switch change refuses the rung instead of serving it stale.
set -euo pipefail

MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="${CALLISTO_INSTALL_DIR:-$HOME/.local/lib/callisto}"
BASE_NAME="${CALLISTO_SPP_BASE:-gi-50b-bleed-oil-sheen}"
SPP="${CALLISTO_SPP:-4}"
BASE="$INSTALL_DIR/skin.set/$BASE_NAME"
SERC="$INSTALL_DIR/ser.set/class"
WORK="$MOD_DIR/dev/disasm/skinspp"
PY="$MOD_DIR/dev/patch_skin_spp.py"

DO_INSTALL=0
[[ "${1:-}" == "--install" ]] && DO_INSTALL=1

# the atomic pair: no radiance write (55 sec 2) -- never patched, ships verbatim
PASS=(40c6faab52a13874 ab7f1822eeb0331b)

RUNG_D="$BASE_NAME-spp${SPP}d"
RUNG_F="$BASE_NAME-spp${SPP}"

[[ -f "$BASE/MANIFEST.txt" ]] || { echo "no $BASE/MANIFEST.txt -- run the gi rung build first" >&2; exit 1; }

mapfile -t REFS < <(cd "$BASE" && ls *.rgs_reference_main.spv | sed 's/\..*//')
(( ${#REFS[@]} == 12 )) || { echo "$BASE_NAME has ${#REFS[@]} rgs_reference_main, expected 12" >&2; exit 1; }
TARGETS=()
for h in "${REFS[@]}"; do
    skip=0
    for p in "${PASS[@]}"; do [[ "$h" == "$p" ]] && skip=1; done
    (( skip )) && continue
    TARGETS+=("$h")
    cmp -s "$BASE/$h.rgs_reference_main.spv" "$SERC/$h.rgs_reference_main.spv" \
        || { echo "$h.rgs_reference_main in $BASE_NAME differs from ser.set/class -- ref=12(pass-through) broken?" >&2; exit 1; }
done
(( ${#TARGETS[@]} == 10 )) || { echo "expected 10 patchable refs, have ${#TARGETS[@]}" >&2; exit 1; }

rm -rf "$WORK" "$MOD_DIR/swaps.$RUNG_D" "$MOD_DIR/swaps.$RUNG_F"
mkdir -p "$WORK"

for h in "${TARGETS[@]}"; do
    spirv-dis "$BASE/$h.rgs_reference_main.spv" -o "$WORK/$h.rgs_reference_main.spvasm"
done

# tier split comes from the patcher's probe, not from a hardcoded list
DYN=() BAKED=()
for h in "${TARGETS[@]}"; do
    t="$(python3 "$PY" "$WORK/$h.rgs_reference_main.spvasm" --probe | sed -n 's/.*"tier": "\([a-z]*\)".*/\1/p')"
    case "$t" in
        dyn)   DYN+=("$h") ;;
        baked) BAKED+=("$h") ;;
        *) echo "probe failed for $h" >&2; exit 1 ;;
    esac
done
echo "  tier split: ${#DYN[@]} dyn / ${#BAKED[@]} baked"
(( ${#DYN[@]} == 6 && ${#BAKED[@]} == 4 )) || { echo "expected 6 dyn + 4 baked (29 B3's split); refusing" >&2; exit 1; }

jobs="${CALLISTO_JOBS:-$(nproc 2>/dev/null || echo 4)}"

build_rung() {  # $1 = rung name, $2.. = ids to patch
    local name="$1"; shift
    local patch=("$@")
    local dest="$MOD_DIR/swaps.$name"
    mkdir -p "$dest"
    printf '%s\0' "${patch[@]}" | CB_D="$dest" CB_P="$PY" CB_W="$WORK" CB_S="$SPP" \
        xargs -0 -P "$jobs" -n1 bash -c '
            python3 "$CB_P" "$CB_W/$0.rgs_reference_main.spvasm" --spp "$CB_S" \
                --outdir "$CB_D" > "$CB_D/$0.rgs.report.json"'
    # verbatim halves: compute + restirgi + the 2 atomic refs + unpatched refs
    cp -pf "$BASE"/*.dxil.spv "$dest/"
    cp -pf "$BASE"/*.rgs_restirgi_*.spv "$dest/" 2>/dev/null || true
    for h in "${REFS[@]}"; do
        [[ -f "$dest/$h.rgs_reference_main.spv" ]] || cp -pf "$BASE/$h.rgs_reference_main.spv" "$dest/"
    done
    for f in "$BASE"/*.dxil.spv "$BASE"/*.rgs_restirgi_*.spv; do
        [[ -f "$f" ]] || continue
        cmp -s "$f" "$dest/$(basename "$f")" || { echo "verbatim copy differs: $f" >&2; exit 1; }
    done
    # patched halves must DIFFER from base; unpatched must NOT
    for h in "${REFS[@]}"; do
        want_same=1
        for p in "${patch[@]}"; do [[ "$h" == "$p" ]] && want_same=0; done
        if (( want_same )); then
            cmp -s "$BASE/$h.rgs_reference_main.spv" "$dest/$h.rgs_reference_main.spv" \
                || { echo "$name: $h should be pass-through but differs" >&2; exit 1; }
        else
            cmp -s "$BASE/$h.rgs_reference_main.spv" "$dest/$h.rgs_reference_main.spv" \
                && { echo "$name: $h is byte-identical to base -- patch emitted nothing" >&2; exit 1; }
        fi
    done
    for f in "$dest"/*.spv; do
        spirv-val "$f" || { echo "spirv-val FAILED: $f" >&2; exit 1; }
    done
    # emitted-instruction re-read from the OUTPUT binaries (39 sec 3.4)
    python3 - "$dest" "$BASE" "$SPP" << 'PYV'
import json, re, subprocess, sys, glob, os
dest, base, spp = sys.argv[1], sys.argv[2], sys.argv[3]
fails = []
for rp in sorted(glob.glob(os.path.join(dest, '*.rgs.report.json'))):
    r = json.load(open(rp))
    h = os.path.basename(rp).split('.')[0]
    f = os.path.join(dest, h + '.rgs_reference_main.spv')
    asm = subprocess.run(['spirv-dis', f], capture_output=True, text=True).stdout
    van = subprocess.run(['spirv-dis', os.path.join(base, h + '.rgs_reference_main.spv')],
                         capture_output=True, text=True).stdout
    if asm.count('OpTraceRayKHR') != van.count('OpTraceRayKHR'):
        fails.append(f'{h}: trace count changed'); continue
    # ids are renumbered by spirv-as/dis round trip -- all checks are
    # structural, none reference ids from the build reports
    m = re.search(r'(%\w+) = OpIEqual %bool (%\w+) %uint_32\b', asm)
    if not m:
        fails.append(f'{h}: no class-1 gate emitted'); continue
    tier = r['tier']
    A = asm.splitlines()
    if tier == 'dyn':
        mx = re.search(r'(%\w+) = OpExtInst %uint %\w+ UMax ', asm)
        if not mx:
            fails.append(f'{h}: UMax missing'); continue
        eff = None
        me = re.search(r'(%\w+) = OpSelect %uint %\w+ ' + re.escape(mx.group(1)) + r' (%\w+)', asm)
        if not me:
            fails.append(f'{h}: eff select (of UMax) missing'); continue
        eff = me.group(1)
        if not re.search(r'OpULessThan %bool %\w+ ' + re.escape(eff) + r'\b', asm):
            fails.append(f'{h}: sample latch does not compare against eff'); continue
        n = len(re.findall(r'(?<![\w%])' + re.escape(eff) + r'(?![\w])', asm))
        if n < 7:   # def + >=6 uses
            fails.append(f'{h}: eff has only {n} occurrences')
    else:
        s = r['skin_spp']
        # find the wired loop: an OpLoopMerge M C where block C holds the
        # accumulator adds and ends BranchConditional cond H M
        ok = False
        for lmm in re.finditer(r'OpLoopMerge (%\w+) (%\w+) None', asm):
            M, C = lmm.groups()
            i = asm.rfind('= OpLabel', 0, lmm.start())
            H = re.search(r'(%\w+) = OpLabel', asm[asm.rfind('\n', 0, i):i + 12])
            H = H.group(1) if H else None
            cb = re.search(re.escape(C) + r' = OpLabel\n(.*?)(?=\n\s+%\w+ = OpLabel\n)', asm, re.S)
            if not cb:
                continue
            blk = cb.group(1)
            if len(re.findall(r'= OpFAdd %half ', blk)) >= s['merge_phis'] \
               and re.search(r'OpBranchConditional %\w+ ' + re.escape(H or '%none') + r' ' + re.escape(M) + r'\b', blk) \
               and re.search(r'= OpIMul %uint %\w+ %uint_747796405\b', blk):
                ok = True
                break
        if not ok:
            fails.append(f'{h}: wired sample loop (accumulate + conditional back-edge) not found'); continue
        if not re.search(r'OpSelect %uint %\w+ %uint_' + spp + r' %uint_1\b', asm):
            fails.append(f'{h}: N select missing'); continue
        if not re.search(r'OpSelect %half ', asm):
            fails.append(f'{h}: invN select missing')
if fails:
    print('EMITTED-CODE RE-READ FAILED:\n  ' + '\n  '.join(fails)); sys.exit(1)
print(f'  emitted-code re-read: {dest} clean')
PYV
    # MANIFEST: base provenance verbatim, renamed, ref= note updated
    local refnote
    if (( ${#patch[@]} == 10 )); then refnote="ref=12(6 spp$SPP-dyn + 4 spp$SPP-baked + 2 pass-through)"
    else refnote="ref=12(6 spp$SPP-dyn + 4 pass-through + 2 pass-through)"; fi
    sed -e "1s/^$BASE_NAME /$name /" \
        -e "1s/ref=12(pass-through)/$refnote/" \
        "$BASE/MANIFEST.txt" > "$dest/MANIFEST.txt"
    grep -q "^$name " "$dest/MANIFEST.txt" || { echo "MANIFEST rewrite failed" >&2; exit 1; }
    echo "# skin-only sample count (handoff/29 B4, build 77): class-1 pixels get max(RayNumber,$SPP) spp" >> "$dest/MANIFEST.txt"
    echo "# photo-mode-priced: ~+60-90% PT cost in face close-ups (29 B7); A/B d-vs-full isolates the baked-tier risk" >> "$dest/MANIFEST.txt"
    n=$(ls "$dest"/*.spv | wc -l)
    echo "  built swaps.$name: $n modules, all spirv-val clean"
}

build_rung "$RUNG_D" "${DYN[@]}"
build_rung "$RUNG_F" "${DYN[@]}" "${BAKED[@]}"

n_base=$(ls "$BASE"/*.spv | wc -l)
for r in "$RUNG_D" "$RUNG_F"; do
    n=$(ls "$MOD_DIR/swaps.$r"/*.spv | wc -l)
    [[ "$n" == "$n_base" ]] || { echo "swaps.$r has $n files, base has $n_base" >&2; exit 1; }
done

if (( DO_INSTALL )); then
    for r in "$RUNG_D" "$RUNG_F"; do
        park="$INSTALL_DIR/skin.set/$r"
        mkdir -p "$park"; rm -f "$park"/*.spv "$park"/*.json "$park/MANIFEST.txt"
        cp -pf "$MOD_DIR/swaps.$r"/*.spv "$MOD_DIR/swaps.$r"/*.json "$MOD_DIR/swaps.$r/MANIFEST.txt" "$park/"
        echo "  parked -> $park"
    done
fi
echo "select with skinspec=$RUNG_D (engine-loop half) or skinspec=$RUNG_F (full)"
echo "contract: skin=on, ser=class, shadowset=full-shadow, ptq combo unchanged since the base rung was built"
