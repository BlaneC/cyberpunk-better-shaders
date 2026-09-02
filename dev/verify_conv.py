#!/usr/bin/env python3
"""Re-derive handoff/92's converged-mode gate from the SHIPPED binaries.

Nothing here trusts the patcher's report: every id is re-found in the
disassembly of the .spv that will actually be served, and every constant is
checked by RESOLVED VALUE.

The point of this file is handoff/90 sec 2's lesson. That verifier accepted any
`X == 0` as the cavity gate, which is exactly how the wrong counter passed five
times. The gate axis here is checked to the ROOT: the predicate must be
`OpUGreaterThan(<cbv[188] component 1>, 1)` with the access chain, the load,
the bitcast and the component index all re-derived -- not "some comparison
against some uint".

  verify_conv.py RUNG BASE --n N --spp S [--gate accum|none]

  --gate accum  (default) the handoff/92 shape: the bounce floor is
                OpSelect(accum, N, 0) and the skin predicate is
                LogicalAnd(isSkin, accum).
  --gate none   the UNGATED shape handoff/89 and handoff/77 shipped: a bare
                constant floor and a bare isSkin. Exists so the gate check can
                be shown NON-VACUOUS in both directions -- point `--gate accum`
                at `-b3` or at `-spp4` and it must FAIL; point `--gate none` at
                this rung and it must FAIL.

  --n 0    assert the module carries NO bounce floor at all.
  --spp 0  assert the module carries NO skin sample edit at all.
"""
import argparse, glob, os, re, subprocess, sys

FAIL = []
CBV_WORD = 188
RAYN_COMP = '1'
CLASS_MASK = '%uint_4294967264'          # ~31
CLASS_SKIN = 32
UNIT_ONE = ('%half_0x1p_0', '%float_1')


def bad(mod, msg):
    FAIL.append(f"{mod}: {msg}")


def dis(path):
    r = subprocess.run(['spirv-dis', '--no-header', path],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"spirv-dis failed on {path}")
    return r.stdout.split('\n')


def index(lines):
    d = {}
    for i, l in enumerate(lines):
        m = re.match(r'\s*(%\w+)\s*=\s*(.*?)\s*$', l)
        if m:
            d[m.group(1)] = (i, m.group(2))
    return d


def uval(d, tok):
    m = re.match(r'%uint_(\d+)$', tok)
    if m:
        return int(m.group(1))
    v = d.get(tok, (0, ''))[1]
    m = re.match(r'OpConstant %uint (\d+)$', v)
    return int(m.group(1)) if m else None


def hval(d, tok):
    """resolved value of an OpConstant %half, or None."""
    v = d.get(tok, (0, ''))[1]
    m = re.match(r'OpConstant %half (\S+)$', v)
    if not m:
        m2 = re.match(r'%half_(\S+)$', tok)
        if not m2:
            return None
        try:
            return float.fromhex(m2.group(1).replace('n', '-').replace('p_', 'p+'))
        except ValueError:
            return None
    try:
        return float.fromhex(m.group(1))
    except ValueError:
        return None


# --------------------------------------------------------------- loops

def loop_cands(lines, d):
    """every counted loop `Op[SU]LessThan(x + 1, bound)` on a back edge whose
    body traces rays, with the count of fp header phis seeded with 1.0."""
    labels = {}
    for i, l in enumerate(lines):
        m = re.match(r'\s*(%\w+)\s*=\s*OpLabel', l)
        if m:
            labels[m.group(1)] = i
    out = []
    for i, l in enumerate(lines):
        m = re.match(r'\s*OpBranchConditional (%\w+) (%\w+) (%\w+)', l)
        if not m:
            continue
        cond, t0, t1 = m.groups()
        cm = re.match(r'Op([SU])LessThan %bool (%\w+) (%\w+)$',
                      d.get(cond, (0, ''))[1])
        if not cm:
            continue
        sign, a, bound = cm.groups()
        if not re.match(r'OpIAdd %uint %\w+ %uint_1$', d.get(a, (0, ''))[1]):
            continue
        for tgt in (t0, t1):
            hi = labels.get(tgt)
            if hi is None or hi >= i:
                continue
            if not any('OpTraceRayKHR' in lines[j] for j in range(hi, i)):
                continue
            ones = 0
            for j in range(hi + 1, len(lines)):
                if not re.match(r'\s*\S+\s*=\s*OpPhi ', lines[j]):
                    break
                pm = re.match(r'\s*\S+\s*=\s*OpPhi %(half|float) (.+?)\s*$',
                              lines[j])
                if pm and any(v in UNIT_ONE
                              for v in pm.group(2).split()[0::2]):
                    ones += 1
            out.append({"branch": i, "sign": sign, "bound": bound,
                        "header": tgt, "header_line": hi, "ones": ones})
    return out


def path_edge(lines, d, name):
    """the PATH loop, by the 3-unit-phi RGB-throughput discriminator
    (handoff/89 sec 2). Returns (path, others) or (None, None)."""
    cands = loop_cands(lines, d)
    hot = [c for c in cands if c["ones"] == 3]
    if len(hot) != 1:
        bad(name, f"{len(hot)} throughput-seeded path loops, expected 1 "
                  f"(candidates {[(c['header'], c['ones']) for c in cands]})")
        return None, None
    others = []
    for c in cands:
        if c is hot[0]:
            continue
        if c["ones"] != 0:
            bad(name, f"loop {c['header']} seeds {c['ones']} unit phis -- the "
                      f"throughput discriminator is not clean")
        elif not (c["header_line"] < hot[0]["header_line"]
                  and hot[0]["branch"] < c["branch"]):
            bad(name, f"path loop {hot[0]['header']} is not nested inside "
                      f"{c['header']}")
        others.append(c)
    return hot[0], others


# ---------------------------------------------------------- the gate root

def check_accum(d, cond, name, what):
    """`cond` must BE `bitcast(cbv[188]).y > 1`, re-derived to the root."""
    v = d.get(cond, (0, ''))[1]
    m = re.match(r'OpUGreaterThan %bool (%\w+) (%\w+)$', v)
    if not m:
        bad(name, f"{what}: gate {cond} is {v!r}, wanted OpUGreaterThan")
        return False
    ext, one = m.groups()
    if uval(d, one) != 1:
        bad(name, f"{what}: gate compares against {uval(d, one)}, want 1")
        return False
    ev = d.get(ext, (0, ''))[1]
    m = re.match(r'OpCompositeExtract %uint (%\w+) (\d+)$', ev)
    if not m:
        bad(name, f"{what}: gate operand {ext} is {ev!r}, wanted a "
                  f"CompositeExtract")
        return False
    bc, comp = m.groups()
    if comp != RAYN_COMP:
        bad(name, f"{what}: gate reads cbv component {comp}, want "
                  f"{RAYN_COMP} (RayNumber) -- .z is BounceNumber")
        return False
    bv = d.get(bc, (0, ''))[1]
    m = re.match(r'OpBitcast %v4uint (%\w+)$', bv)
    if not m:
        bad(name, f"{what}: {bc} is {bv!r}, wanted OpBitcast %v4uint")
        return False
    lv = d.get(m.group(1), (0, ''))[1]
    m = re.match(r'OpLoad %v4float (%\w+)$', lv)
    if not m:
        bad(name, f"{what}: {lv!r} is not an OpLoad %v4float")
        return False
    av = d.get(m.group(1), (0, ''))[1]
    m = re.match(r'OpAccessChain %_ptr_Uniform_v4float %\w+ %uint_0 (%\w+)$',
                 av)
    if not m:
        bad(name, f"{what}: {av!r} is not a uniform access chain")
        return False
    if uval(d, m.group(1)) != CBV_WORD:
        bad(name, f"{what}: gate reads cbv word {uval(d, m.group(1))}, "
                  f"want {CBV_WORD}")
        return False
    return True


def check_predicate(d, pred, gate, name, what):
    """the shared shape of both gated edits' predicate.
    gate=='accum': pred == LogicalAnd(isSkin, accum)  [skin] or the accum
                   condition itself [bounce, handled by the caller]
    gate=='none' : pred == isSkin"""
    v = d.get(pred, (0, ''))[1]
    if gate == 'accum':
        m = re.match(r'OpLogicalAnd %bool (%\w+) (%\w+)$', v)
        if not m:
            bad(name, f"{what}: predicate {pred} is {v!r}, wanted "
                      f"LogicalAnd(isSkin, accum)")
            return
        skin, acc = m.groups()
        check_isskin(d, skin, name, what)
        check_accum(d, acc, name, what)
    else:
        check_isskin(d, pred, name, what)


def check_isskin(d, skin, name, what):
    v = d.get(skin, (0, ''))[1]
    m = re.match(r'OpIEqual %bool (%\w+) (%\w+)$', v)
    if not m:
        bad(name, f"{what}: isSkin {skin} is {v!r}, wanted OpIEqual")
        return
    a, c = m.groups()
    if uval(d, c) != CLASS_SKIN:
        bad(name, f"{what}: isSkin compares against {uval(d, c)}, want "
                  f"{CLASS_SKIN} (class 1 << 5)")
    av = d.get(a, (0, ''))[1]
    if not re.match(r'OpBitwiseAnd %uint %\w+ ' + re.escape(CLASS_MASK) + '$',
                    av):
        bad(name, f"{what}: isSkin operand {a} is {av!r}, wanted the class "
                  f"mask BitwiseAnd ~31")


# ------------------------------------------------------------- the checks

def check_bounce(name, lines, d, base_lines, bd, n, gate):
    e, _ = path_edge(lines, d, name)
    be, _ = path_edge(base_lines, bd, name)
    if e is None or be is None:
        return
    v = d.get(e["bound"], (0, ''))[1]
    m = re.match(r'OpExtInst %uint %\w+ UMax (%\w+) (%\w+)$', v)
    if n == 0:
        if m:
            bad(name, f"--n 0 but the path bound IS a UMax: {v!r}")
        return
    if not m:
        bad(name, f"bound {e['bound']} is {v!r}, wanted OpExtInst UMax")
        return
    inner, floor = m.groups()

    # the floor: gated OpSelect (92) vs the bare constant (89)
    fv = d.get(floor, (0, ''))[1]
    sm = re.match(r'OpSelect %uint (%\w+) (%\w+) (%\w+)$', fv)
    if gate == 'accum':
        if not sm:
            bad(name, f"bounce floor {floor} is {fv!r}, wanted "
                      f"OpSelect(accum, {n}, 0) -- this rung is UNGATED")
            return
        cond, hi, lo = sm.groups()
        if uval(d, hi) != n:
            bad(name, f"gated bounce floor is {uval(d, hi)}, want {n}")
        if uval(d, lo) != 0:
            bad(name, f"gate-false bounce floor is {uval(d, lo)}, want 0 -- "
                      f"UMax(bound, 0) is the identity and anything else "
                      f"changes 1 spp behaviour")
        check_accum(d, cond, name, "bounce floor")
    else:
        if sm:
            bad(name, f"--gate none but the bounce floor {floor} is an "
                      f"OpSelect: {fv!r}")
            return
        if uval(d, floor) != n:
            bad(name, f"bounce floor resolves to {uval(d, floor)}, want {n}")

    # the inner operand keeps the base's KIND: a literal its value, a runtime
    # extract its component -- no rung may silently drop the CVar wire.
    bv = bd.get(be["bound"], (0, ''))[1]
    iv = d.get(inner, (0, ''))[1]
    if bv.startswith('OpConstant %uint'):
        if iv != bv:
            bad(name, f"base bound was {bv!r}, patched inner is {iv!r}")
    elif bv.startswith('OpCompositeExtract %uint'):
        if not iv.startswith('OpCompositeExtract %uint'):
            bad(name, f"base bound was a runtime extract, patched inner is "
                      f"{iv!r} -- the CVar wire was dropped")
        elif iv.split()[-1] != bv.split()[-1]:
            bad(name, f"component index moved: base {bv.split()[-1]} vs "
                      f"patched {iv.split()[-1]}")
    else:
        bad(name, f"unrecognised base bound {bv!r}")
    if e["sign"] != be["sign"]:
        bad(name, f"compare sign changed {be['sign']} -> {e['sign']}")


def base_tier(base_lines):
    if not any(re.search(r'= OpBitwiseAnd %uint %\w+ ' + re.escape(CLASS_MASK)
                         + r'\s*$', l) for l in base_lines):
        return 'ser'
    for i, l in enumerate(base_lines):
        if re.search(r'OpAccessChain %_ptr_Uniform_v4float %\w+ %uint_0 '
                     r'%uint_' + str(CBV_WORD) + r'\s*$', l):
            for j in range(i + 1, min(i + 5, len(base_lines))):
                if re.search(r'OpCompositeExtract %uint %\w+ ' + RAYN_COMP
                             + r'\s*$', base_lines[j]):
                    return 'dyn'
    return 'baked'


def check_skin(name, lines, d, base_lines, tier, spp, gate):
    """the skin sample floor, re-derived. dyn: the SAMPLE loop's bound must be
    the eff select. baked: the wired loop's N / invN selects."""
    effs = []
    for tok, (i, v) in d.items():
        m = re.match(r'OpSelect %uint (%\w+) (%\w+) (%\w+)$', v)
        if not m:
            continue
        g, hi, lo = m.groups()
        mv = d.get(hi, (0, ''))[1]
        um = re.match(r'OpExtInst %uint %\w+ UMax (%\w+) (%\w+)$', mv)
        k = uval(d, um.group(2)) if um else None
        # with --spp 0 nothing is expected, so the shapes are matched loosely
        # (any floor >= 2) -- a negative control that only recognised the one
        # value it was told to look for would be worth nothing.
        want = (lambda x: x == spp) if spp else (lambda x: x is not None and x >= 2)
        if um and um.group(1) == lo and want(k):
            effs.append((tok, g, lo))          # dyn shape
        elif tier == 'baked' and want(uval(d, hi)) and uval(d, lo) == 1 and \
                any(re.match(r'OpSelect %half ' + re.escape(g) + r' ', v2)
                    for _t, (_i, v2) in d.items()):
            effs.append((tok, g, None))        # baked shape
    if tier == 'ser':
        if any(re.search(r'= OpBitwiseAnd %uint %\w+ '
                         + re.escape(CLASS_MASK) + r'\s*$', l) for l in lines):
            bad(name, "SER permutation gained a class mask -- handoff/77 "
                      "leaves these two pass-through and so must this rung")
        if effs:
            bad(name, f"SER permutation carries {len(effs)} skin sample "
                      f"selects, expected 0")
        return
    if spp == 0:
        if effs:
            bad(name, f"--spp 0 but the module carries {len(effs)} skin "
                      f"sample selects")
        return
    if len(effs) != 1:
        bad(name, f"{len(effs)} skin sample selects at spp={spp}, expected 1")
        return
    eff, g, ext = effs[0]
    if tier == 'dyn':
        # gate-false MUST be the engine's own read, bit for bit
        ev = d.get(ext, (0, ''))[1]
        if not re.match(r'OpCompositeExtract %uint %\w+ ' + RAYN_COMP + '$',
                        ev):
            bad(name, f"eff's gate-false arm is {ev!r}, wanted the engine's "
                      f"own cbv[{CBV_WORD}].y read")
        # and it must actually BE the sample loop's bound
        _, others = path_edge(lines, d, name)
        if others is not None and eff not in [c["bound"] for c in others]:
            bad(name, f"eff {eff} is not the bound of any non-path counted "
                      f"loop -- the sample count did not move")
        gv = d.get(g, (0, ''))[1]
        m = re.match(r'OpLogicalAnd %bool (%\w+) (%\w+)$', gv)
        if not m:
            bad(name, f"eff gate {g} is {gv!r}, wanted "
                      f"LogicalAnd(<skin gate>, rayN != 0)")
            return
        inner, nz = m.groups()
        nv = d.get(nz, (0, ''))[1]
        if not re.match(r'OpINotEqual %bool %\w+ %uint_0$', nv):
            bad(name, f"eff gate's second operand is {nv!r}, wanted "
                      f"rayN != 0")
        check_predicate(d, inner, gate, name, "skin spp")
    else:
        check_predicate(d, g, gate, name, "skin spp")
        # the averaging reciprocal must match the same gate and 1/spp
        halves = [(t, v) for t, (i, v) in d.items()
                  if re.match(r'OpSelect %half ' + re.escape(g) + r' ', v)]
        if len(halves) != 1:
            bad(name, f"{len(halves)} OpSelect %half on the skin gate, "
                      f"expected 1 (the 1/N average)")
            return
        parts = halves[0][1].split()
        got, one = hval(d, parts[3]), hval(d, parts[4])
        if got is None or abs(got - 1.0 / spp) > 1e-6:
            bad(name, f"baked average multiplier is {got}, want {1.0/spp}")
        if one != 1.0:
            bad(name, f"baked gate-false multiplier is {one}, want 1.0 "
                      f"(exact in half, so off-gate output is bit-identical)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('rung')
    ap.add_argument('base')
    ap.add_argument('--n', type=int, required=True)
    ap.add_argument('--spp', type=int, required=True)
    ap.add_argument('--gate', choices=('accum', 'none'), default='accum')
    a = ap.parse_args()
    k, tiers = 0, {}
    for f in sorted(glob.glob(os.path.join(a.rung,
                                           '*.rgs_reference_main.spv'))):
        b = os.path.join(a.base, os.path.basename(f))
        if not os.path.exists(b):
            raise SystemExit(f"no base for {f}")
        name = os.path.basename(f).split('.')[0]
        lines, base_lines = dis(f), dis(b)
        d, bd = index(lines), index(base_lines)
        tier = base_tier(base_lines)
        tiers[tier] = tiers.get(tier, 0) + 1
        check_bounce(name, lines, d, base_lines, bd, a.n, a.gate)
        check_skin(name, lines, d, base_lines, tier, a.spp, a.gate)
        if sum('OpTraceRayKHR' in l for l in lines) != \
           sum('OpTraceRayKHR' in l for l in base_lines):
            bad(name, "trace-site count differs from the base")
        k += 1
    if k != 12:
        bad('rung', f"{k} reference modules verified, expected 12")
    print(f"  verify_conv: {k}/12 modules, gate={a.gate}, floor n={a.n}, "
          f"skin spp={a.spp}, tiers " +
          ', '.join(f"{t}x{c}" for t, c in sorted(tiers.items())))
    if FAIL:
        print("VERIFY FAILED:\n  " + "\n  ".join(FAIL))
        sys.exit(1)
    print("  verify_conv: PASS")


if __name__ == '__main__':
    main()
