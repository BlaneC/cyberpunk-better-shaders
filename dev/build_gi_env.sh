#!/usr/bin/env bash
# 84: a gi raygen base PLUS ONE VARIABLE -- the environment chroma bleed.
#
#   ./dev/build_gi_env.sh --q 0.35 --install               # gi-50bnd-env35
#   ./dev/build_gi_env.sh --q 0.70 --install               # gi-50bnd-env70
#   ./dev/build_gi_env.sh --from gi-50bnd --q 0 --name X   # the inertness test
#
# Runs dev/patch_gi_env.py as a SECOND pass over an already-parked gi rung's
# four ReSTIR-GI diffuse raygens: luminance-held chroma widening at each
# module's final radiance triple, gated class != 1 && class != 4. The other
# 89 files (12 rgs_reference_main + 77 compute) are copied byte-verbatim and
# asserted so, and the raygen delta is asserted to be exactly the 4 diffuse
# modules -- so <base> vs <base>-envNN is one variable by construction.
#
# Why a second pass and not a flag on patch_gi_c1.py: it keeps the emission
# out of build_gi_rung.sh's one-variable assertions, it makes "q=0 rebuilds
# the base byte-for-byte" a literal cmp instead of an argument, and -- GOTCHAS
# rule 12 -- every detector then runs in a fresh process against bytes that
# are fully written, never against ids whose defining instruction is still
# pending in an edit list.
#
# Provenance (src_ser/ser_sha/ptq_sha) carries over VERBATIM from the base, so
# sync_settings.sh's gi_refuse contract is unchanged: ser=class +
# shadowset=full-shadow.
set -euo pipefail

MOD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="${CALLISTO_INSTALL_DIR:-$HOME/.local/lib/callisto}"
PY="$MOD_DIR/dev/patch_gi_env.py"

FROM=gi-50bnd
Q=""
NAME=""
DO_INSTALL=0
while (( $# )); do
    case "$1" in
        --install) DO_INSTALL=1 ;;
        --from) FROM="${2:?--from needs a parked gi rung}"; shift ;;
        --q)    Q="${2:?--q needs a value}"; shift ;;
        --name) NAME="${2:?--name needs a rung name}"; shift ;;
        *) echo "unknown flag: $1" >&2; exit 2 ;;
    esac
    shift
done
[[ -n "$Q" ]] || { echo "--q is required" >&2; exit 2; }
if [[ -z "$NAME" ]]; then
    NAME="$FROM-env$(python3 -c "print('%02d' % round(float('$Q')*100))")"
fi

BASE="$INSTALL_DIR/skin.set/$FROM"
DEST="$MOD_DIR/swaps.gi.${NAME#gi-}"
WORK="$MOD_DIR/dev/disasm/gi-env.$NAME"

[[ -f "$BASE/MANIFEST.txt" ]] || { echo "no $BASE/MANIFEST.txt -- park the base first (./dev/build_gi_rung.sh --flat-front --install)" >&2; exit 1; }
n_base=$(ls "$BASE"/*.spv | wc -l)
[[ "$n_base" == 93 ]] || { echo "$BASE has $n_base modules, expected 93" >&2; exit 1; }
n_diff=$(ls "$BASE"/*.rgs_restirgi_*.spv | wc -l)
[[ "$n_diff" == 4 ]] || { echo "$BASE has $n_diff restirgi raygens, expected 4" >&2; exit 1; }

# --- disassemble the 4 diffuse raygens from the PARKED base ---------------
rm -rf "$WORK"; mkdir -p "$WORK/asm" "$WORK/out"
for f in "$BASE"/*.rgs_restirgi_*.spv; do
    spirv-dis "$f" -o "$WORK/asm/$(basename "${f%.spv}").spvasm"
done

python3 "$PY" --env-chroma "$Q" --out "$WORK/out" "$WORK"/asm/*.spvasm

# --- coverage from the reports, never byte diffs (the 42 rule) ------------
python3 - "$WORK/out" "$Q" <<'PYA'
import glob, json, sys
d, q = sys.argv[1], float(sys.argv[2])
reps = [json.load(open(f)) for f in sorted(glob.glob(d + '/*.json'))]
assert len(reps) == 4, "%d reports, want 4" % len(reps)
shapes, qs, bad = {}, set(), []
sites = 0
for r in reps:
    e = r['gi_env']
    if r['spirv_val'] != 'clean':
        bad.append((r['ident'], 'spirv-val not clean'))
    shapes[e['shape']] = shapes.get(e['shape'], 0) + 1
    qs.add(e['q'])
    if e['gate'] != 'class != 1 && class != 4':
        bad.append((r['ident'], 'gate is %r' % e['gate']))
    if e['class_how'] != 'class-switch':
        bad.append((r['ident'], 'class read as %r, want the module\'s own '
                                'material OpSwitch' % e['class_how']))
    if q <= 0:
        if e['spliced']:
            bad.append((r['ident'], 'q=0 emitted %d channels' % len(e['spliced'])))
        continue
    sites += 1
    ch = sorted(x['chan'] for x in e['spliced'])
    if ch != [0, 1, 2]:
        # 39's rule: a channel that could not be proven must fail the BUILD,
        # never ship as a guess.
        bad.append((r['ident'], 'channels %s, want [0,1,2]' % ch))
    if any(x['uses_rewritten'] < 1 for x in e['spliced']):
        bad.append((r['ident'], 'a channel reached 0 consumers'))
    if e['wiring'] != ('texel-rebuild' if e['shape'] == 'rgb' else 'use-rewrite'):
        bad.append((r['ident'], 'shape/wiring mismatch: %s/%s'
                    % (e['shape'], e['wiring'])))
if len(qs) != 1:
    bad.append(('coverage', 'modules disagree on q: %s' % sorted(qs)))
if q > 0:
    # The census (handoff/84 s2) is 2 plain-RGB writes and 2 YCoCg-or-
    # passthrough writes, one site each. A module count or a shape count that
    # differs from this is a FINDING, not a rounding error (46 s12).
    if sites != 4:
        bad.append(('coverage', '%d sites, census says 4' % sites))
    if shapes != {'rgb': 2, 'ycocg': 2}:
        bad.append(('coverage', 'shapes %s, census says 2 rgb + 2 ycocg' % shapes))
if bad:
    for m, why in bad:
        sys.stderr.write('    %s :: %s\n' % (m, why))
    sys.exit(1)
print("  env coverage: 4 modules, %d sites, shapes %s, q=%s, gate "
      "class!=1 && class!=4 off the module's own class switch"
      % (sites, shapes, sorted(qs)[0]))
PYA

# --- assemble: the base's 89 other files verbatim + the 4 patched ---------
rm -rf "$DEST"; mkdir -p "$DEST"
cp -pf "$BASE"/*.spv "$DEST/"
cp -pf "$WORK/out"/*.rgs_restirgi_*.spv "$DEST/"
n=$(ls "$DEST"/*.spv | wc -l)
[[ "$n" == 93 ]] || { echo "rung has $n modules, expected 93" >&2; exit 1; }

d=0; dn=""
for f in "$BASE"/*.spv; do
    b="$(basename "$f")"
    cmp -s "$f" "$DEST/$b" || { d=$((d+1)); dn="$dn $b"; }
done
if [[ "$Q" == 0 || "$Q" == 0.0 ]]; then
    # BYTE-INERTNESS, the whole point of the zero rung: the patcher declares
    # no constant and splices no instruction, so the assembled output must be
    # the base's own bytes. A byte diff here would be the 42 failure mode --
    # a rung that "differs" only by constants nothing consumes.
    (( d == 0 )) || { echo "q=0 rebuild differs from $FROM in $d files ($dn) -- NOT byte-inert" >&2; exit 1; }
    echo "  q=0: 93 of 93 modules byte-identical to $FROM (gate-false byte-inert)"
else
    (( d == 4 )) || { echo "$NAME differs from $FROM in $d of 93 files ($dn) -- want exactly the 4 restirgi diffuse raygens" >&2; exit 1; }
    for b in $dn; do
        case "$b" in *.rgs_restirgi_*) ;; *) echo "unexpected delta file $b" >&2; exit 1 ;; esac
    done
    # spelled out so a future edit cannot quietly move the delta elsewhere
    nref=0; ncomp=0
    for f in "$BASE"/*.rgs_reference_main.spv; do cmp -s "$f" "$DEST/$(basename "$f")" && nref=$((nref+1)); done
    for f in "$BASE"/*.dxil.spv; do cmp -s "$f" "$DEST/$(basename "$f")" && ncomp=$((ncomp+1)); done
    [[ "$nref" == 12 ]] || { echo "only $nref of 12 rgs_reference_main are byte-identical to $FROM" >&2; exit 1; }
    [[ "$ncomp" == 77 ]] || { echo "only $ncomp of 77 compute modules are byte-identical to $FROM" >&2; exit 1; }
    echo "  $NAME vs $FROM: 4 of 16 raygens differ (the restirgi diffuse four); ref 12/12 and compute 77/77 byte-identical"
fi

for f in "$DEST"/*.spv; do spirv-val "$f" || { echo "spirv-val FAILED: $f" >&2; exit 1; }; done
echo "  spirv-val clean on all 93 modules"

# MANIFEST: the base's provenance verbatim, renamed, with the new knob.
sed -e "1s/^$FROM /$NAME env_chroma=$Q /" "$BASE/MANIFEST.txt" > "$DEST/MANIFEST.txt"
grep -q "^$NAME env_chroma=$Q " "$DEST/MANIFEST.txt" \
    || { echo "MANIFEST rewrite failed -- check $BASE/MANIFEST.txt line 1 format" >&2; exit 1; }
echo "# + environment chroma bleed: luminance-held chroma widening (q=$Q) at the 4 GI diffuse raygens' final radiance triple, class != 1 && class != 4; see handoff/84" >> "$DEST/MANIFEST.txt"
echo "  built $DEST: 93 modules"

if [[ "$DO_INSTALL" == 1 ]]; then
    park="$INSTALL_DIR/skin.set/$NAME"
    mkdir -p "$park"; rm -f "$park"/*.spv "$park/MANIFEST.txt"
    cp -pf "$DEST"/*.spv "$DEST/MANIFEST.txt" "$park/"
    echo "  parked -> $park"
else
    echo "NOT installed. To park: ./dev/build_gi_env.sh --from $FROM --q $Q --install"
fi
