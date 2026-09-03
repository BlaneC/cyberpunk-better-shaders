#!/usr/bin/env bash
# earglow-cap -- a THICKNESS FLOOR in the ear-glow transfer. handoff/101 sec 18.
#
# The user, on the shipped default rung: "Also if the intensity gets more
# intense as geometry gets thinner, we might want to cap that at a certain
# point. Childrens ears GLOW. They emit alot of light which doesnt look
# correct. Everything else looks great".
#
# W3's transfer is monotone decreasing in t, so thin flesh is monotonically
# brighter and query B's tmin (1.5 mm) is the only ceiling there is. These
# rungs add ONE variable: t_eff = NMax(t_B, t_cap), evaluated INSIDE the
# transfer and NOT in the ray -- query C's origin keeps the raw t. Anything
# thinner than t_cap glows exactly like t_cap; anything thicker is untouched
# bit for bit, so adult ears are unchanged BY CONSTRUCTION.
#
#   ./dev/build_earglow_cap.sh [--install] [--base <skin.set name>]
#
# Three rungs: earglow-cap3 (3 mm), earglow-cap4 (4 mm), earglow-cap6 (6 mm).
# k is NOT touched (0.22, 70/71). The CONTROL is the shipped default rung
# itself -- it IS cap 0 -- and gate 2b proves that by rebuilding with --cap 0
# and demanding 93/93 byte-identical to it.
#
# Nine gates, all offline, then the driver self-test:
#   0 base + default-rung provenance   5 identity: 10/93 differ, rungs differ
#   1 dis->as byte-neutral             6 verify_earglow_cap.py (+ the rq3 half)
#   2 patch + spirv-val vulkan1.4      7 non-vacuity: 12 decoys REJECTED
#   2b the cap-0 NULL is byte-exact    8 closed-form transfer with the floor
#   3 coverage census from reports     9 MANIFEST provenance
#   4 instruction census on bytes        then: ./dev/selftest_earglow_rq.sh
set -euo pipefail

MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="${CALLISTO_INSTALL_DIR:-$HOME/.local/lib/callisto}"
PY="$MOD_DIR/dev/patch_earglow_cap.py"
VERIFY="$MOD_DIR/dev/verify_earglow_cap.py"
VERIFY3="$MOD_DIR/dev/verify_earglow_rq3.py"
WORK="$MOD_DIR/dev/disasm/earglow_cap"

BASE=gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog
DEFAULT_RUNG="$BASE-earglow"      # the SHIPPED default: rq3, cap 0
CTL=earglow-rq-ctl
K=0.22
WIDE=4.0
WRAP=0.35
DO_INSTALL=0
while (( $# )); do
    case "$1" in
        --install) DO_INSTALL=1 ;;
        --base) BASE="${2:?--base needs a skin.set name}"; DEFAULT_RUNG="$BASE-earglow"; shift ;;
        -h|--help) sed -n '2,28p' "$0"; exit 0 ;;
        *) echo "unknown arg $1" >&2; exit 1 ;;
    esac
    shift
done

SRC="$INSTALL_DIR/skin.set/$BASE"
PASS=(40c6faab52a13874 ab7f1822eeb0331b)
ORDER=(earglow-cap3 earglow-cap4 earglow-cap6)
declare -A CAP_M=([earglow-cap3]=0.003 [earglow-cap4]=0.004 [earglow-cap6]=0.006)

# --- 0. provenance ----------------------------------------------------------
[[ -f "$SRC/MANIFEST.txt" ]] || { echo "no $SRC/MANIFEST.txt" >&2; exit 1; }
n_c=$(ls "$SRC"/*.dxil.spv | wc -l)
n_g=$(ls "$SRC"/*.rgs_restirgi_*.spv | wc -l)
n_r=$(ls "$SRC"/*.rgs_reference_main.spv | wc -l)
[[ "$n_c" == 77 && "$n_g" == 4 && "$n_r" == 12 ]] \
    || { echo "$BASE is $n_c/$n_g/$n_r, expected 77/4/12" >&2; exit 1; }
[[ -d "$MOD_DIR/swaps.$DEFAULT_RUNG" ]] \
    || { echo "swaps.$DEFAULT_RUNG is missing -- run" \
              "./dev/build_earglow_rq3.sh --lineage $DEFAULT_RUNG --install first;" \
              "these rungs are the DEFAULT plus one variable and the build" \
              "refuses to guess what the default was" >&2; exit 1; }
[[ -d "$MOD_DIR/swaps.$CTL" ]] || { echo "swaps.$CTL is missing" >&2; exit 1; }

mapfile -t REFS < <(cd "$SRC" && ls *.rgs_reference_main.spv | sed 's/\..*//')
TARGETS=()
for h in "${REFS[@]}"; do
    skip=0; for p in "${PASS[@]}"; do [[ "$h" == "$p" ]] && skip=1; done
    (( skip )) && continue
    TARGETS+=("$h")
done
(( ${#TARGETS[@]} == 10 )) || { echo "expected 10 paintable refs" >&2; exit 1; }
echo "=== 0. base: $BASE ; default rung: $DEFAULT_RUNG"

rm -rf "$WORK"; mkdir -p "$WORK/asm" "$WORK/rt"
for h in "${TARGETS[@]}"; do
    spirv-dis "$SRC/$h.rgs_reference_main.spv" -o "$WORK/asm/$h.spvasm"
done

# --- 1. round-trip neutrality ----------------------------------------------
echo "=== 1. round-trip neutrality (spirv-dis -> spirv-as == base bytes)"
for h in "${TARGETS[@]}"; do
    spirv-as --target-env spv1.4 "$WORK/asm/$h.spvasm" -o "$WORK/rt/$h.spv"
    cmp -s "$SRC/$h.rgs_reference_main.spv" "$WORK/rt/$h.spv" \
        || { echo "  !! $h does not round-trip" >&2; exit 1; }
done
echo "  10 of 10 reference permutations round-trip byte-identically"
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
                > "$CB_O/$0.earglowcap.report.json"'
    rm -f "$WORK/.args"
    local n; n=$(ls "$out"/*.spv 2>/dev/null | wc -l)
    [[ "$n" == 10 ]] || { echo "  !! $out produced $n modules, want 10" >&2; exit 1; }
}

assemble () {    # $1 = dest swaps dir, $2 = patched-module dir
    local dest="$1" src="$2"
    rm -rf "$dest"; mkdir -p "$dest"
    cp -pf "$src"/*.spv "$src"/*.json "$dest/"
    cp -pf "$SRC"/*.dxil.spv "$SRC"/*.rgs_restirgi_*.spv "$dest/"
    for p in "${PASS[@]}"; do cp -pf "$SRC/$p.rgs_reference_main.spv" "$dest/"; done
    for f in "$SRC"/*.dxil.spv "$SRC"/*.rgs_restirgi_*.spv; do
        cmp -s "$f" "$dest/$(basename "$f")" \
            || { echo "  !! verbatim copy differs: $(basename "$f")" >&2; exit 1; }
    done
    for h in "${TARGETS[@]}"; do
        cmp -s "$SRC/$h.rgs_reference_main.spv" "$dest/$h.rgs_reference_main.spv" \
            && { echo "  !! $h is byte-identical to the base" >&2; exit 1; }
    done
    local n; n=$(ls "$dest"/*.spv | wc -l)
    [[ "$n" == 93 ]] || { echo "  !! $dest has $n modules, expected 93" >&2; exit 1; }
    for f in "$dest"/*.spv; do
        spirv-val --target-env vulkan1.4 "$f" >/dev/null \
            || { echo "  !! spirv-val FAILED: $f" >&2; exit 1; }
    done
}

# --- 2. patch + assemble ----------------------------------------------------
echo "=== 2. patch + assemble the three rungs"
for r in "${ORDER[@]}"; do
    patch_set "$WORK/p.$r" --k "$K" --cap "${CAP_M[$r]}" --wide "$WIDE" --wrap "$WRAP"
    assemble "$MOD_DIR/swaps.$r" "$WORK/p.$r"
    echo "  swaps.$r: 93 modules, 10 patched, floor ${CAP_M[$r]} m, spirv-val clean"
done

# --- 2b. THE NULL -----------------------------------------------------------
# --cap 0 emits nothing, so this patcher must reproduce the SHIPPED DEFAULT
# byte for byte. That is what makes the cap the ONE variable of these rungs:
# not "the diff looks small", but "the diff is empty when the cap is off".
echo "=== 2b. cap-0 null: this patcher with the floor off == the default rung"
patch_set "$WORK/p.null" --k "$K" --cap 0 --wide "$WIDE" --wrap "$WRAP"
d=0
for h in "${TARGETS[@]}"; do
    cmp -s "$WORK/p.null/$h.rgs_reference_main.spv" \
           "$MOD_DIR/swaps.$DEFAULT_RUNG/$h.rgs_reference_main.spv" || d=$((d+1))
done
[[ "$d" == 0 ]] || { echo "  !! cap-0 differs from $DEFAULT_RUNG on $d of 10" >&2; exit 1; }
echo "  10 of 10 byte-identical to swaps.$DEFAULT_RUNG -- the floor is the only variable"

for pair in "earglow-cap3 earglow-cap4" "earglow-cap4 earglow-cap6" \
            "earglow-cap3 earglow-cap6" "earglow-cap3 $DEFAULT_RUNG"; do
    set -- $pair; d=0
    for h in "${TARGETS[@]}"; do
        cmp -s "$MOD_DIR/swaps.$1/$h.rgs_reference_main.spv" \
               "$MOD_DIR/swaps.$2/$h.rgs_reference_main.spv" || d=$((d+1))
    done
    [[ "$d" == 10 ]] || { echo "  !! only $d of 10 differ between $1 and $2" >&2; exit 1; }
done
echo "  10 of 10 differ between every pair of rungs and vs the default"

# --- 3. coverage census, from the REPORTS ----------------------------------
echo "=== 3. coverage census"
python3 - "$MOD_DIR" "${ORDER[@]}" <<'PY' || exit 1
import glob, json, os, sys
mod_dir, rungs = sys.argv[1], sys.argv[2:]
# Stated HERE, independently of argv: a rung whose floor silently moved must
# fail even if the request moved with it.
WANT = {'earglow-cap3': 0.003, 'earglow-cap4': 0.004, 'earglow-cap6': 0.006}
bad = []
for r in rungs:
    d = os.path.join(mod_dir, 'swaps.' + r)
    mods = 0
    for f in sorted(glob.glob(os.path.join(d, '*.earglowcap.report.json'))):
        j = json.load(open(f))
        c = j['earglow_cap']
        g = j['earglow_rq3']
        if abs(c['cap_m'] - WANT[r]) > 1e-9:
            bad.append(f'{r}/{j["ident"]}: cap {c["cap_m"]} want {WANT[r]}')
        if c['op'] != 'NMax':
            bad.append(f'{r}/{j["ident"]}: op {c["op"]} want NMax')
        if c['capped_fmuls'] != 6:
            bad.append(f'{r}/{j["ident"]}: {c["capped_fmuls"]} capped FMuls, want 6')
        if not c['push_untouched']:
            bad.append(f'{r}/{j["ident"]}: query C push was capped')
        if c['decoy'] is not None:
            bad.append(f'{r}/{j["ident"]}: decoy {c["decoy"]} in a shipped rung')
        if g.get('k') != 0.22:
            bad.append(f'{r}/{j["ident"]}: k moved to {g.get("k")} -- k is FIXED')
        if j['spirv_val'] != 'clean':
            bad.append(f'{r}/{j["ident"]}: spirv-val not clean')
        mods += 1
    if mods != 10:
        bad.append(f'{r}: {mods} reports, want 10')
    print(f'  {r}: 10 modules, floor {WANT[r]*1e3:g} mm, 6 capped chains each, '
          f'k=0.22 untouched, query C raw')
if bad:
    for b in bad[:12]:
        sys.stderr.write('    ' + b + '\n')
    sys.exit(1)
PY

# --- 4. instruction census on the SHIPPED bytes ----------------------------
echo "=== 4. instruction census on the SHIPPED bytes"
python3 - "$MOD_DIR" "$SRC" "$MOD_DIR/swaps.$DEFAULT_RUNG" "${ORDER[@]}" <<'PY' || exit 1
import glob, os, subprocess, sys
mod_dir, src, dflt, rungs = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:]
PASS = ('40c6faab52a13874', 'ab7f1822eeb0331b')
def dis(p):
    return subprocess.run(['spirv-dis', p], capture_output=True, text=True).stdout
bad = []
for r in rungs:
    d = os.path.join(mod_dir, 'swaps.' + r)
    tot = dict(init=0, proceed=0, iid=0, tget=0, nmax=0)
    for f in sorted(glob.glob(os.path.join(d, '*.rgs_reference_main.spv'))):
        h = os.path.basename(f).split('.')[0]
        a = dis(f)
        b = dis(os.path.join(src, os.path.basename(f)))
        c = dis(os.path.join(dflt, os.path.basename(f)))
        n_i = a.count('OpRayQueryInitializeKHR')
        n_p = a.count('OpRayQueryProceedKHR')
        n_d = a.count('OpRayQueryGetIntersectionInstanceIdKHR')
        n_t = a.count('OpRayQueryGetIntersectionTKHR')
        dt = a.count('OpTraceRayKHR') - b.count('OpTraceRayKHR')
        # ONE added NMax against the UNCAPPED DEFAULT, not against the base:
        # the shipped modules carry NMax of their own and counting them
        # against vanilla would be measuring the engine, not the splice.
        dn = a.count(' NMax ') - c.count(' NMax ')
        if h in PASS:
            if (n_i or n_p or n_d or n_t or dn):
                bad.append(f'{r}/{h}: pass-through module was patched')
            continue
        if (n_i, n_p, n_d, n_t, dt, dn) != (3, 3, 2, 1, 0, 1):
            bad.append(f'{r}/{h}: census {(n_i, n_p, n_d, n_t, dt, dn)} '
                       f'want (3, 3, 2, 1, 0, 1)')
        for k, v in zip(('init', 'proceed', 'iid', 'tget', 'nmax'),
                        (n_i, n_p, n_d, n_t, dn)):
            tot[k] += v
    print(f'  {r}: {tot["init"]} Initialize, {tot["proceed"]} Proceed, '
          f'{tot["iid"]} InstanceId, {tot["tget"]} committed-T, '
          f'{tot["nmax"]} ADDED NMax, 0 added OpTraceRayKHR')
if bad:
    for b in bad[:12]:
        sys.stderr.write('    ' + b + '\n')
    sys.exit(1)
PY

# --- 5. identity, over the WHOLE set ---------------------------------------
echo "=== 5. identity"
for r in "${ORDER[@]}"; do
    d=0
    for f in "$SRC"/*.spv; do
        cmp -s "$f" "$MOD_DIR/swaps.$r/$(basename "$f")" || d=$((d+1))
    done
    [[ "$d" == 10 ]] || { echo "  !! $r differs on $d files, want exactly 10" >&2; exit 1; }
done
echo "  the three rungs: 10 of 93 differ (the 10 paintable permutations)"

# --- 6. the verifier, on the shipped bytes ---------------------------------
echo "=== 6. verify_earglow_cap.py on the shipped .spv (includes the rq3 half)"
for r in "${ORDER[@]}"; do
    python3 "$VERIFY" "$MOD_DIR/swaps.$r" --base "$SRC" --cap "${CAP_M[$r]}" \
        --k "$K" --wide "$WIDE" --wrap "$WRAP"
done
python3 "$VERIFY" --negative "$MOD_DIR/swaps.$CTL"

# --- 7. verifier NON-VACUITY -----------------------------------------------
echo "=== 7. verifier non-vacuity (each of these MUST fail)"
reject () {
    local why="$1"; shift
    if "$@" >/dev/null 2>&1; then
        echo "  !! NOT REJECTED: $why" >&2; exit 1
    fi
    echo "  rejected: $why"
}
G=(--base "$SRC" --cap 0.003 --k "$K" --wide "$WIDE" --wrap "$WRAP")
reject "the SHIPPED DEFAULT (uncapped) read as cap3" \
       python3 "$VERIFY" "$MOD_DIR/swaps.$DEFAULT_RUNG" "${G[@]}"
reject "cap3 read as cap4" \
       python3 "$VERIFY" "$MOD_DIR/swaps.earglow-cap3" --base "$SRC" --cap 0.004 \
       --k "$K" --wide "$WIDE" --wrap "$WRAP"
reject "cap4 read as cap3" \
       python3 "$VERIFY" "$MOD_DIR/swaps.earglow-cap4" "${G[@]}"
reject "cap6 read as cap3" \
       python3 "$VERIFY" "$MOD_DIR/swaps.earglow-cap6" "${G[@]}"
reject "cap3 read as an UNCAPPED rq3 rung (verify_earglow_rq3.py, no --floor)" \
       python3 "$VERIFY3" "$MOD_DIR/swaps.earglow-cap3" --base "$SRC" --mode glow \
       --k "$K" --wide "$WIDE" --wrap "$WRAP"
reject "the SHIPPED DEFAULT read as an rq3 rung WITH --floor (it has no floor)" \
       python3 "$VERIFY3" "$MOD_DIR/swaps.$DEFAULT_RUNG" --base "$SRC" --mode glow \
       --k "$K" --wide "$WIDE" --wrap "$WRAP" --floor
reject "the k=0 CONTROL read as cap3" \
       python3 "$VERIFY" "$MOD_DIR/swaps.$CTL" "${G[@]}"
reject "the BASE read as cap3" \
       python3 "$VERIFY" "$SRC" "${G[@]}"
if [[ -d "$MOD_DIR/swaps.earglow-rq2" ]]; then
    reject "earglow-rq2 (no query C at all) read as cap3" \
           python3 "$VERIFY" "$MOD_DIR/swaps.earglow-rq2" "${G[@]}"
fi
# decoy BUILDS -- one module each, never installed
for dec in capray capmin nocap; do
    rm -rf "$WORK/d.$dec"
    python3 "$PY" "$WORK/asm/${TARGETS[0]}.spvasm" --outdir "$WORK/d.$dec" \
        --k "$K" --cap 0.003 --wide "$WIDE" --wrap "$WRAP" --decoy "$dec" \
        --no-roundtrip-check > /dev/null
    reject "decoy build --decoy $dec" \
           python3 "$VERIFY" "$WORK/d.$dec" --base "$SRC" --cap 0.003 \
           --k "$K" --wide "$WIDE" --wrap "$WRAP" --skip-rq3
done
# ...and each decoy must be rejected for ITS OWN reason. A decoy that failed
# for an unrelated reason would prove nothing about the cap check.
# NOTE the command substitution: `verifier | grep -q` cannot be used under
# `set -o pipefail`, because the verifier's own exit 1 makes the PIPELINE fail
# even when grep matched -- which reads as "rejected for the wrong reason" and
# is not.
why () {   # $1 = expected substring, $2.. = command
    local want="$1"; shift
    local out; out="$("$@" 2>&1 || true)"
    grep -q -- "$want" <<<"$out" \
        || { echo "  !! rejected for the WRONG reason (wanted '$want'):" >&2
             echo "$out" | tail -3 >&2; exit 1; }
}
D=(--base "$SRC" --cap 0.003 --k "$K" --wide "$WIDE" --wrap "$WRAP" --skip-rq3)
why 'pushes off the raw t'      python3 "$VERIFY" "$WORK/d.capray" "${D[@]}"
why 'still read the UNCAPPED t' python3 "$VERIFY" "$WORK/d.nocap"  "${D[@]}"
why 'is NMin, not NMax'         python3 "$VERIFY" "$WORK/d.capmin" "${D[@]}"
echo "  each decoy is rejected for its OWN reason, not incidentally"

# --- 8. closed form, with the floor ----------------------------------------
echo "=== 8. closed-form transfer (rates AND the floor read back from the .spv)"
python3 - "$MOD_DIR" "${ORDER[@]}" <<'PY' || exit 1
import glob, os, re, subprocess, sys
import numpy as np
mod_dir, rungs = sys.argv[1], sys.argv[2:]
LD = np.array([0.00367, 0.00137, 0.00068])
WIDE, K = 4.0, 0.22
WANT = {'earglow-cap3': 0.003, 'earglow-cap4': 0.004, 'earglow-cap6': 0.006}
bad = []
for rung in rungs:
    f = sorted(glob.glob(os.path.join(mod_dir, 'swaps.' + rung,
                                      '*.rgs_reference_main.spv')))[0]
    asm = subprocess.run(['spirv-dis', f], capture_output=True, text=True).stdout
    vals = []
    for m in re.finditer(r'OpConstant %float ([0-9.e+-]+)\s*$', asm, re.M):
        try:
            vals.append(float(m.group(1)))
        except ValueError:
            pass
    a1, a2 = [], []
    for ld in LD:
        c1 = [v for v in vals if abs(v - 1.0 / ld) <= 1e-3 * (1.0 / ld)]
        c2 = [v for v in vals if abs(v - 1.0 / (WIDE * ld)) <= 1e-3 / (WIDE * ld)]
        if not c1 or not c2:
            bad.append(f'{rung}: transfer rates missing for ld={ld}')
            c1, c2 = [1.0 / ld], [1.0 / (WIDE * ld)]
        a1.append(c1[0]); a2.append(c2[0])
    a1, a2 = np.array(a1), np.array(a2)
    # The floor, read back off the NMax ON THE GUARDED T -- located by
    # walking committed-T -> its OpSelect guard -> the NMax that consumes it.
    # A bare search for "the first NMax" finds one of the module's OWN (there
    # is an NMax on 0.005 in every permutation) and would measure the engine.
    mt = re.search(r'(%\w+) = OpRayQueryGetIntersectionTKHR', asm)
    if not mt:
        bad.append(f'{rung}: no committed-T getter'); continue
    mg = re.search(r'(%\w+) = OpSelect %float %\w+ ' + re.escape(mt.group(1))
                   + r' %\w+\s*$', asm, re.M)
    if not mg:
        bad.append(f'{rung}: no guard on the committed t'); continue
    mm = re.search(r'= OpExtInst %float %\w+ NMax ' + re.escape(mg.group(1))
                   + r' (%\w+)\s*$', asm, re.M)
    if not mm:
        bad.append(f'{rung}: no NMax on the guarded t in the shipped bytes'); continue
    cid = mm.group(1)
    cm = re.search(re.escape(cid) + r' = OpConstant %float ([0-9.e+-]+)', asm)
    cap = float(cm.group(1)) if cm else None
    if cap is None or abs(cap - WANT[rung]) > 1e-6:
        bad.append(f'{rung}: floor {cap} want {WANT[rung]}')
        cap = WANT[rung]
    t = np.array([1.5, 2.0, 3.0, 4.0, 6.0, 8.0]) * 1e-3
    te = np.maximum(t, cap)
    T = 0.5 * (np.exp(-np.outer(te, a1)) + np.exp(-np.outer(te, a2)))
    T0 = 0.5 * (np.exp(-np.outer(t, a1)) + np.exp(-np.outer(t, a2)))
    print(f'  {rung}: floor {cap*1e3:g} mm, k={K}, wide={WIDE}')
    print('     t(mm)    k*T_capped R/G/B          uncapped R      ratio')
    for i, tt in enumerate(t):
        r, g, b = T[i] * K
        print(f'   {tt*1e3:6.1f}   {r:8.5f} {g:8.5f} {b:8.5f}    '
              f'{T0[i,0]*K:8.5f}   {T0[i,0]/T[i,0]:6.3f}x')
    # the floor must be FLAT below the cap and IDENTICAL above it
    below = t < cap - 1e-12
    if below.any() and not np.allclose(T[below], T[below][0:1], rtol=1e-12):
        bad.append(f'{rung}: the transfer is not flat below the floor')
    above = t > cap + 1e-12
    if above.any() and not np.allclose(T[above], T0[above], rtol=1e-12):
        bad.append(f'{rung}: the transfer CHANGED above the floor -- adult '
                   f'ears must be untouched by construction')
    # and the floor must actually remove something at tmin
    tmin = 0.0015
    Tm = 0.5 * (np.exp(-tmin * a1) + np.exp(-tmin * a2))
    Tc = 0.5 * (np.exp(-cap * a1) + np.exp(-cap * a2))
    print('   removed at tmin=1.5 mm: R %.2fx  G %.2fx  B %.2fx'
          % tuple(Tm / Tc))
    if np.any(Tm / Tc <= 1.0):
        bad.append(f'{rung}: the floor does not dim the thinnest flesh')
if bad:
    for b in bad:
        sys.stderr.write('    ' + b + '\n')
    sys.exit(1)
PY

# --- 9. MANIFEST ------------------------------------------------------------
echo "=== 9. MANIFEST provenance"
src_ser=$(head -1 "$SRC/MANIFEST.txt")
for r in "${ORDER[@]}"; do
    dest="$MOD_DIR/swaps.$r"
    {
      echo "$r (base=$BASE, = $DEFAULT_RUNG + a thickness floor) handoff/101 sec 18"
      echo "# t_eff = NMax(t_B, ${CAP_M[$r]}) INSIDE the transfer; query C's push keeps the RAW t"
      echo "# everything else is the shipped default rung, byte for byte at cap 0"
      echo "# k=$K (untuned, 70/71), wide=$WIDE wrap=$WRAP"
      echo "# src: $src_ser"
      grep -E '^# (src_ser|ser_sha|ptq_sha)' "$SRC/MANIFEST.txt" 2>/dev/null || true
      echo "# UNSHOT. Read handoff/101 sec 18 BEFORE the screen: the frame needs"
      echo "# a CHILD and an ADULT in it, backlit, ears clear of hair."
    } > "$dest/MANIFEST.txt"
done
echo "  ${#ORDER[@]} MANIFESTs written, provenance carried verbatim"

echo
echo "=== shas (content = cat of all 93 .spv in name order)"
setsha () {
    find "$1" -maxdepth 1 -name "$2" -print0 | sort -z |
        xargs -0 cat | sha256sum | cut -c1-16
}
printf '  %-34s content=%s  raygen-half=%s\n' "($DEFAULT_RUNG)" \
    "$(setsha "$MOD_DIR/swaps.$DEFAULT_RUNG" '*.spv')" \
    "$(setsha "$MOD_DIR/swaps.$DEFAULT_RUNG" '*.rgs_reference_main.spv')"
for r in "${ORDER[@]}"; do
    printf '  %-34s content=%s  raygen-half=%s\n' "$r" \
        "$(setsha "$MOD_DIR/swaps.$r" '*.spv')" \
        "$(setsha "$MOD_DIR/swaps.$r" '*.rgs_reference_main.spv')"
done

if (( DO_INSTALL )); then
    for r in "${ORDER[@]}"; do
        park="$INSTALL_DIR/skin.set/$r"
        rm -rf "$park"; mkdir -p "$park"
        cp -pf "$MOD_DIR/swaps.$r"/*.spv "$MOD_DIR/swaps.$r/MANIFEST.txt" "$park/"
        n=0
        for f in "$MOD_DIR/swaps.$r"/*.spv; do
            cmp -s "$f" "$park/$(basename "$f")" || { echo "  !! park differs: $f" >&2; exit 1; }
            n=$((n+1))
        done
        echo "  parked -> $park ($n modules, cmp-verbatim against the build)"
    done
fi

echo
echo "select with skinspec=earglow-cap3 / earglow-cap4 / earglow-cap6"
echo "the CONTROL is the shipped default $DEFAULT_RUNG -- it IS cap 0"
echo "contract: ser=class, shadowset=full-shadow, ptq unchanged; RR OFF;"
echo "          BACKLIT, a CHILD and an ADULT in the same frame, ears clear of"
echo "          hair. Read handoff/101 sec 18 BEFORE the screen."
