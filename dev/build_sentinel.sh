#!/usr/bin/env bash
# G-U5 payload sentinel rungs (handoff/55): does an INJECTED OpTraceRayKHR
# execute in this game's RT pipelines?
#
#   ./dev/build_sentinel.sh              # build both rungs (no install)
#   ./dev/build_sentinel.sh --install    # ALSO park as skin.set/sentinel{,-b}
#
# Two rungs, launched one at a time, A first:
#   sentinel    injected trace, cullMask 0 (guaranteed miss), fresh armed
#               payload; this library's ms_empty_main patched with an
#               ARM->MAGIC handshake; MAGENTA where the magic came back.
#   sentinel-b  the same injected trace with EVERY operand verbatim (hits
#               scene, unpatched CHS writes the payload), no ms patch;
#               CYAN where the armed word changed. Discriminates "traces
#               execute but the miss-0 mapping assumption is wrong".
#
# Base: skin.set/gi-50 -- the standing rung. Its 77 compute + 4 restirgi + 2
# atomic reference files ship VERBATIM (cmp-asserted); only the 10 paintable
# rgs_reference_main are patched (their bytes are ser.set/class pass-throughs,
# asserted below), plus (rung A) 10 dump-vanilla ms_empty_main. MANIFEST
# provenance (src_ser/ser_sha/ptq_sha) carries over verbatim, so sync's
# gi_refuse contract holds: needs ser=class + shadowset=full-shadow.
set -euo pipefail

MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DUMP_DIR="${CALLISTO_DUMP_DIR:-$HOME/callisto_dump}"
INSTALL_DIR="${CALLISTO_INSTALL_DIR:-$HOME/.local/lib/callisto}"
GI="$INSTALL_DIR/skin.set/gi-50"
SERC="$INSTALL_DIR/ser.set/class"
WORK="$MOD_DIR/dev/disasm/sentinel"
PY="$MOD_DIR/dev/patch_sentinel.py"

DO_INSTALL=0
[[ "${1:-}" == "--install" ]] && DO_INSTALL=1

PASS=(40c6faab52a13874 ab7f1822eeb0331b)

[[ -f "$GI/MANIFEST.txt" ]] || { echo "no $GI/MANIFEST.txt -- run ./dev/build_gi_rung.sh --install first" >&2; exit 1; }

# --- the 10 paintable reference hashes, from gi-50's own files --------------
mapfile -t REFS < <(cd "$GI" && ls *.rgs_reference_main.spv | sed 's/\..*//')
(( ${#REFS[@]} == 12 )) || { echo "gi-50 has ${#REFS[@]} rgs_reference_main, expected 12" >&2; exit 1; }
TARGETS=()
for h in "${REFS[@]}"; do
    skip=0
    for p in "${PASS[@]}"; do [[ "$h" == "$p" ]] && skip=1; done
    (( skip )) && continue
    TARGETS+=("$h")
    # provenance: gi-50's reference files must BE ser.set/class bytes
    cmp -s "$GI/$h.rgs_reference_main.spv" "$SERC/$h.rgs_reference_main.spv" \
        || { echo "$h.rgs_reference_main in gi-50 differs from ser.set/class -- ref=12(pass-through) broken?" >&2; exit 1; }
    [[ -f "$DUMP_DIR/$h.ms_empty_main.spv" ]] \
        || { echo "no $DUMP_DIR/$h.ms_empty_main.spv" >&2; exit 1; }
done
(( ${#TARGETS[@]} == 10 )) || { echo "expected 10 paintable refs, have ${#TARGETS[@]}" >&2; exit 1; }

rm -rf "$WORK" "$MOD_DIR/swaps.sentinel" "$MOD_DIR/swaps.sentinel-b"
mkdir -p "$WORK"

for h in "${TARGETS[@]}"; do
    spirv-dis "$GI/$h.rgs_reference_main.spv" -o "$WORK/$h.rgs_reference_main.spvasm"
    spirv-dis "$DUMP_DIR/$h.ms_empty_main.spv" -o "$WORK/$h.ms_empty_main.spvasm"
done

jobs="${CALLISTO_JOBS:-$(nproc 2>/dev/null || echo 4)}"

build_rung() {  # $1 = rung name, $2 = rgs tier, $3 = with_ms (0/1)
    local dest="$MOD_DIR/swaps.$1" name="$1" tier="$2" with_ms="$3"
    mkdir -p "$dest"
    printf '%s\0' "${TARGETS[@]}" | CB_D="$dest" CB_P="$PY" CB_W="$WORK" CB_T="$tier" \
        xargs -0 -P "$jobs" -n1 bash -c '
            python3 "$CB_P" "$CB_W/$0.rgs_reference_main.spvasm" --tier "$CB_T" \
                --outdir "$CB_D" > "$CB_D/$0.rgs.report.json"'
    if (( with_ms )); then
        printf '%s\0' "${TARGETS[@]}" | CB_D="$dest" CB_P="$PY" CB_W="$WORK" \
            xargs -0 -P "$jobs" -n1 bash -c '
                python3 "$CB_P" "$CB_W/$0.ms_empty_main.spvasm" --tier ms \
                    --outdir "$CB_D" > "$CB_D/$0.ms.report.json"'
    fi
    # verbatim halves: compute + restirgi + the 2 atomic refs
    cp -pf "$GI"/*.dxil.spv "$dest/"
    cp -pf "$GI"/*.rgs_restirgi_*.spv "$dest/"
    for p in "${PASS[@]}"; do cp -pf "$GI/$p.rgs_reference_main.spv" "$dest/"; done
    for f in "$GI"/*.dxil.spv "$GI"/*.rgs_restirgi_*.spv; do
        cmp -s "$f" "$dest/$(basename "$f")" || { echo "verbatim copy differs: $f" >&2; exit 1; }
    done
    # patched halves must DIFFER from their base
    for h in "${TARGETS[@]}"; do
        cmp -s "$GI/$h.rgs_reference_main.spv" "$dest/$h.rgs_reference_main.spv" \
            && { echo "$name: $h rgs is byte-identical to base -- splice emitted nothing" >&2; exit 1; }
        if (( with_ms )); then
            cmp -s "$DUMP_DIR/$h.ms_empty_main.spv" "$dest/$h.ms_empty_main.spv" \
                && { echo "$name: $h ms is byte-identical to dump -- handshake emitted nothing" >&2; exit 1; }
        fi
    done
    for f in "$dest"/*.spv; do
        spirv-val "$f" || { echo "spirv-val FAILED: $f" >&2; exit 1; }
    done
    # emitted-instruction re-read, from the OUTPUT binaries (39 sec 3.4)
    python3 - "$dest" "$tier" "$with_ms" << 'PYV'
import re, subprocess, sys, glob, os
dest, tier, with_ms = sys.argv[1], sys.argv[2], sys.argv[3] == '1'
ARM, MAGIC = '1588010577', '826392798'   # 0x5EA71E51, 0x3141C0DE
fails = []
for f in sorted(glob.glob(os.path.join(dest, '*.rgs_reference_main.spv'))):
    h = os.path.basename(f).split('.')[0]
    if h in ('40c6faab52a13874', 'ab7f1822eeb0331b'):
        continue
    asm = subprocess.run(['spirv-dis', f], capture_output=True, text=True).stdout
    traces = re.findall(r'OpTraceRayKHR (.+)', asm)
    van = subprocess.run(['spirv-dis', os.path.expanduser(
        f'~/.local/lib/callisto/skin.set/gi-50/{h}.rgs_reference_main.spv')],
        capture_output=True, text=True).stdout
    if len(traces) != van.count('OpTraceRayKHR') + 1:
        fails.append(f'{h}: trace count {len(traces)} != vanilla+1'); continue
    if ARM not in asm:
        fails.append(f'{h}: ARM constant missing'); continue
    if tier == 'miss':
        inj = [t for t in traces if ' %uint_0 %uint_1 %uint_1 %uint_0 ' in ' '+t]
        if not any('%uint_0' == t.split()[2] for t in traces):
            fails.append(f'{h}: no cullMask-0 injected trace')
        if MAGIC not in asm:
            fails.append(f'{h}: MAGIC constant missing')
    if 'OpSelect %float' not in asm:
        fails.append(f'{h}: no paint select emitted')
if with_ms:
    for f in sorted(glob.glob(os.path.join(dest, '*.ms_empty_main.spv'))):
        asm = subprocess.run(['spirv-dis', f], capture_output=True, text=True).stdout
        ok = (ARM in asm and MAGIC in asm and 'OpSelect %uint' in asm
              and 'IncomingRayPayloadKHR' in asm)
        if not ok:
            fails.append(os.path.basename(f) + ': handshake shape missing')
if fails:
    print('EMITTED-CODE RE-READ FAILED:\n  ' + '\n  '.join(fails)); sys.exit(1)
print(f'  emitted-code re-read: {dest} clean')
PYV
    # MANIFEST: gi-50's provenance verbatim, renamed
    local msnote=""
    (( with_ms )) && msnote=" ms_empty=10(armed,dump-vanilla-based)"
    sed -e "1s/^gi-50 /$name /" \
        -e "1s/ref=12(pass-through)/ref=12(10 sentinel-$tier + 2 pass-through)$msnote/" \
        "$GI/MANIFEST.txt" > "$dest/MANIFEST.txt"
    grep -q "^$name " "$dest/MANIFEST.txt" || { echo "MANIFEST rewrite failed" >&2; exit 1; }
    echo "# G-U5 payload sentinel (handoff/55): tier=$tier ARM=0x5EA71E51 MAGIC=0x3141C0DE" >> "$dest/MANIFEST.txt"
    echo "# diagnostic rung -- read handoff/55's interpretation table BEFORE the screen" >> "$dest/MANIFEST.txt"
    n=$(ls "$dest"/*.spv | wc -l)
    echo "  built swaps.$name: $n modules, all spirv-val clean"
}

build_rung sentinel   miss  1
build_rung sentinel-b clone 0

n_a=$(ls "$MOD_DIR/swaps.sentinel"/*.spv | wc -l)
n_b=$(ls "$MOD_DIR/swaps.sentinel-b"/*.spv | wc -l)
[[ "$n_a" == 103 ]] || { echo "sentinel has $n_a files, expected 103 (77+12+4+10)" >&2; exit 1; }
[[ "$n_b" == 93  ]] || { echo "sentinel-b has $n_b files, expected 93 (77+12+4)" >&2; exit 1; }

if (( DO_INSTALL )); then
    for r in sentinel sentinel-b; do
        park="$INSTALL_DIR/skin.set/$r"
        mkdir -p "$park"; rm -f "$park"/*.spv "$park"/*.json "$park/MANIFEST.txt"
        cp -pf "$MOD_DIR/swaps.$r"/*.spv "$MOD_DIR/swaps.$r"/*.json "$MOD_DIR/swaps.$r/MANIFEST.txt" "$park/"
        echo "  parked -> $park"
    done
fi
echo "select with skinspec=sentinel (A, magenta) or skinspec=sentinel-b (B, cyan)"
echo "contract: ser=class, shadowset=full-shadow (gi-50's); read handoff/55 sec 5 FIRST"
