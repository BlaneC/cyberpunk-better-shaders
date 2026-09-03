#!/usr/bin/env bash
# Build the CAP6 stack:
#   gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog-earglow-cap6-glintdense
#
# = 101 sec 18's `earglow-cap6` (the ear glow with a 6 mm thickness FLOOR)
#   WITH 100 sec 6's carglint at the -dense knobs (nu0 = 6e5), in the same 10
#   of 12 rgs_reference_main permutations. The user chose cap6 as the default
#   (2026-09-03) and the standing default already carried the dense glints, so
#   the new default has to carry BOTH.
#
# WHY THIS IS A WRAPPER AND NOT A COPY, AND NOT AN EDIT.
# dev/build_carglint_stack.sh does NOT take its base or its output name as a
# parameter -- EGBASE/EGLIN/RUNG/WORK are plain assignments -- and it is the
# glint agent's file, being run by that agent right now. So this script does
# not edit it in place and does not fork its gate logic. It generates a
# PARAMETERISED INSTANCE of it by applying a fixed list of substitutions, each
# of which MUST match exactly once (asserted below, so a rename upstream
# breaks this loudly instead of silently building the wrong thing), runs that
# instance, and then adds the gates the cap6 base needs on top:
#
#   * verify_earglow_rq3.py must be given --floor on the stacked output,
#     because the floor puts one NMax between the guarded t and the transfer.
#     Both of the inner script's calls on swaps.$RUNG get it -- including the
#     wrong-knobs decoy, which otherwise would be rejected for the FLOOR and
#     would stop testing the knobs it exists to test.
#   * verify_earglow_cap.py --cap 0.006 on the stacked output (the inner
#     script knows nothing about floors).
#   * the stacked rung read WITHOUT --floor must be REJECTED, and the CURRENT
#     default stack read as a cap6 rung must be REJECTED -- together those two
#     say the 6 mm floor is present here and absent there, which is the one
#     variable between the old default and the new one.
#   * 10 of 93 differ from the CURRENT default stack.
#
# EGLIN is pointed at the base itself: the inner script uses it only to assert
# "the lineage dir carries the base's bytes", and for this rung the base IS
# its own name. That check is then trivially true and is reported as such.
#
#   ./dev/build_carglint_stack_cap6.sh [--install]
set -euo pipefail

MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="${CALLISTO_INSTALL_DIR:-$HOME/.local/lib/callisto}"
INNER="$MOD_DIR/dev/build_carglint_stack.sh"
OLDBASE=gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog
EGBASE=earglow-cap6
CAP=0.006
OLDSTACK="$OLDBASE-earglow-glintdense"
RUNG="$OLDBASE-earglow-cap6-glintdense"
GEN="$MOD_DIR/dev/disasm/build_carglint_stack.cap6.generated.sh"
DO_INSTALL=0
[[ "${1:-}" == "--install" ]] && DO_INSTALL=1

[[ -f "$INNER" ]] || { echo "$INNER is missing" >&2; exit 1; }
[[ -d "$INSTALL_DIR/skin.set/$EGBASE" ]] \
    || { echo "skin.set/$EGBASE is not parked -- run ./dev/build_earglow_cap.sh --install" >&2; exit 1; }

mkdir -p "$(dirname "$GEN")"
python3 - "$INNER" "$GEN" "$EGBASE" "$RUNG" "$MOD_DIR" <<'PY' || exit 1
import re, sys
src, dst, egbase, rung, root = sys.argv[1:6]
s = open(src).read()
SUBS = [
    # The instance does not live in dev/, so its own $BASH_SOURCE would put
    # MOD_DIR one directory too deep. Pin it to the repo root instead of
    # depending on where the generated file happens to sit.
    ('MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"',
     'MOD_DIR=' + repr(root).replace("'", '"')),
    ('EGBASE=earglow-rq3', 'EGBASE=' + egbase),
    ('EGLIN=gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog-earglow\n',
     'EGLIN=' + egbase + '\n'),
    ('RUNG=gi-50b-bleed-oil-sheen-deep-clothhi-cone2all-fog-earglow-glintdense',
     'RUNG=' + rung),
    ('NULLRUNG=carglint-stack-null', 'NULLRUNG=carglint-stack-cap6-null'),
    ('WORK="$MOD_DIR/dev/disasm/carglint-stack"',
     'WORK="$MOD_DIR/dev/disasm/carglint-stack-cap6"'),
    # the two earglow-verifier calls ON THE STACKED OUTPUT get --floor
    ('python3 "$EGVERIFY" "$MOD_DIR/swaps.$RUNG" --base "$OLD" --mode glow --wide 4.0 --wrap 0.35\n',
     'python3 "$EGVERIFY" "$MOD_DIR/swaps.$RUNG" --base "$OLD" --mode glow --wide 4.0 --wrap 0.35 --floor\n'),
    ('       python3 "$EGVERIFY" "$MOD_DIR/swaps.$RUNG" --base "$OLD" --mode glow --wide 2.0 --wrap 0.35\n',
     '       python3 "$EGVERIFY" "$MOD_DIR/swaps.$RUNG" --base "$OLD" --mode glow --wide 2.0 --wrap 0.35 --floor\n'),
]
for old, new in SUBS:
    n = s.count(old)
    if n != 1:
        sys.stderr.write('  !! substitution matched %d times, want 1: %r\n' % (n, old[:70]))
        sys.exit(1)
    s = s.replace(old, new)
open(dst, 'w').write(s)
print('  generated instance: %d substitutions, each matched exactly once' % len(SUBS))
PY
chmod +x "$GEN"
bash -n "$GEN" || { echo "generated instance does not parse" >&2; exit 1; }

echo "=== running the generated instance of build_carglint_stack.sh on $EGBASE"
if (( DO_INSTALL )); then "$GEN" --install; else "$GEN"; fi

# --------------------------------------------------------------- cap gates
echo
echo "=== cap6 gates (this wrapper's own, on the stacked bytes)"
D="$MOD_DIR/swaps.$RUNG"
OLD="$INSTALL_DIR/skin.set/$OLDBASE"

d=0; n=0
for f in "$D"/*.spv; do
    cmp -s "$MOD_DIR/swaps.$OLDSTACK/$(basename "$f")" "$f" || d=$((d+1)); n=$((n+1))
done
[[ "$n" == 93 && "$d" == 10 ]] \
    || { echo "  !! $d of $n differ from $OLDSTACK, want 10 of 93" >&2; exit 1; }
echo "  10 of 93 differ from the CURRENT default stack ($OLDSTACK)"

python3 "$MOD_DIR/dev/verify_earglow_cap.py" "$D" --base "$OLD" --cap "$CAP" \
    --k 0.22 --wide 4.0 --wrap 0.35

reject () { local what="$1"; shift
    if "$@" >/dev/null 2>&1; then echo "  !! ACCEPTS $what -- vacuous" >&2; exit 1; fi
    echo "  rejects $what, as required"; }
reject "the cap6 stack read WITHOUT --floor (the floor must be REAL)" \
    python3 "$MOD_DIR/dev/verify_earglow_rq3.py" "$D" --base "$OLD" --mode glow \
    --wide 4.0 --wrap 0.35
reject "the cap6 stack read as cap3" \
    python3 "$MOD_DIR/dev/verify_earglow_cap.py" "$D" --base "$OLD" --cap 0.003 \
    --k 0.22 --wide 4.0 --wrap 0.35
reject "the CURRENT default stack read as a cap6 rung (it has no floor)" \
    python3 "$MOD_DIR/dev/verify_earglow_cap.py" "$MOD_DIR/swaps.$OLDSTACK" \
    --base "$OLD" --cap "$CAP" --k 0.22 --wide 4.0 --wrap 0.35
reject "earglow-cap6 itself read as a glint rung (the glints must be REAL)" \
    python3 "$MOD_DIR/dev/verify_carglint.py" "$INSTALL_DIR/skin.set/$EGBASE" --nu0 600000

echo
printf '  %s\n  content sha %s\n' "$RUNG" \
       "$(cat "$D"/*.spv | sha256sum | cut -c1-16)"
if (( DO_INSTALL )); then
    d=0; for f in "$D"/*.spv; do
        cmp -s "$f" "$INSTALL_DIR/skin.set/$RUNG/$(basename "$f")" || d=$((d+1)); done
    [[ "$d" == 0 ]] || { echo "  !! parked differs from built on $d files" >&2; exit 1; }
    echo "  parked == built, 93 of 93 cmp-verbatim"
fi
echo "contract: ser=class + shadowset=full-shadow (12 reference + 4 restirgi raygens)"
