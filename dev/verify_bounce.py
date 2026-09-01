#!/usr/bin/env python3
"""Re-derive handoff/89's bounce-bound raise from the SHIPPED binaries.

Nothing here trusts the patcher's report. Everything is re-found in the
disassembly of the .spv that will actually be served, structurally or by
resolved constant value.

  dev/verify_bounce.py <rung_dir> <base_dir> --n N
  dev/verify_bounce.py <base_dir> --negative
"""
import argparse, glob, os, re, subprocess, sys

FAIL = []


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


UNIT_ONE = ('%half_0x1p_0', '%float_1')


def bounce_edge(lines, d, name):
    """The PATH loop's back edge, re-derived from the shipped bytes with no
    help from the patcher: among the counted loops `LessThan(x + 1, bound)`
    whose body traces rays, the path loop is the one whose header seeds
    exactly 3 fp phis with 1.0 -- the RGB throughput. The other candidate is
    the SAMPLE loop (accumulators seeded to 0) and must seed none."""
    labels = {}
    for i, l in enumerate(lines):
        m = re.match(r'\s*(%\w+)\s*=\s*OpLabel', l)
        if m:
            labels[m.group(1)] = i
    cands = []
    for i, l in enumerate(lines):
        m = re.match(r'\s*OpBranchConditional (%\w+) (%\w+) (%\w+)', l)
        if not m:
            continue
        cond, t0, t1 = m.groups()
        cd = d.get(cond, (0, ''))[1]
        cm = re.match(r'Op([SU])LessThan %bool (%\w+) (%\w+)$', cd)
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
                    break                      # end of the header's phi run
                pm = re.match(r'\s*\S+\s*=\s*OpPhi %(half|float) (.+?)\s*$',
                              lines[j])
                if pm and any(v in UNIT_ONE
                              for v in pm.group(2).split()[0::2]):
                    ones += 1
            cands.append({"branch": i, "cond": cond, "sign": sign, "inc": a,
                          "bound": bound, "header": tgt, "header_line": hi,
                          "ones": ones})
    hot = [c for c in cands if c["ones"] == 3]
    if len(hot) != 1:
        bad(name, f"{len(hot)} throughput-seeded path loops, expected 1 "
                  f"(candidates {[(c['header'], c['ones']) for c in cands]})")
        return None
    for c in cands:
        if c is hot[0]:
            continue
        if c["ones"] != 0:
            bad(name, f"loop {c['header']} seeds {c['ones']} unit phis -- "
                      f"the throughput discriminator is not clean")
        elif not (c["header_line"] < hot[0]["header_line"]
                  and hot[0]["branch"] < c["branch"]):
            bad(name, f"path loop {hot[0]['header']} is not nested inside "
                      f"{c['header']}")
    return hot[0]


def verify_module(name, lines, base_lines, n):
    d, bd = index(lines), index(base_lines)
    e, be = bounce_edge(lines, d, name), bounce_edge(base_lines, bd, name)
    if e is None or be is None:
        return

    # the patched bound must be UMax(<the base module's own bound>, n)
    v = d.get(e["bound"], (0, ''))[1]
    m = re.match(r'OpExtInst %uint %\w+ UMax (%\w+) (%\w+)$', v)
    if not m:
        bad(name, f"bound {e['bound']} is {v!r}, wanted OpExtInst UMax")
        return
    inner, floor = m.groups()
    if uval(d, floor) != n:
        bad(name, f"UMax floor resolves to {uval(d, floor)}, want {n}")

    # the inner operand must be the SAME KIND of bound the base carried, and
    # for a literal, the same VALUE -- so a rung cannot silently drop the
    # engine's own runtime bound on the floor
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

    # the comparison and the loop shape are otherwise untouched
    if e["sign"] != be["sign"]:
        bad(name, f"compare sign changed {be['sign']} -> {e['sign']}")
    # exactly the UMax, plus the floor constant ONLY if the base lacked it
    had = any(re.match(r'\s*%\w+\s*=\s*OpConstant %uint ' + str(n) + r'\s*$', l)
              for l in base_lines)
    want = 1 if had else 2
    if len(lines) != len(base_lines) + want:
        bad(name, f"{len(lines) - len(base_lines)} lines added, expected "
                  f"{want} (the UMax{'' if had else ' and its uint constant'})"
                  f" -- nothing else may move")


def negative(base_dir):
    """The base must carry no UMax on its bounce bound."""
    n = 0
    for f in sorted(glob.glob(os.path.join(base_dir,
                                           '*.rgs_reference_main.spv'))):
        lines = dis(f)
        d = index(lines)
        e = bounce_edge(lines, d, os.path.basename(f))
        if e is not None:
            v = d.get(e["bound"], (0, ''))[1]
            if 'UMax' in v:
                bad(os.path.basename(f),
                    f"NEGATIVE CONTROL: base bound is already a UMax: {v!r}")
        n += 1
    print(f"  negative control: {n} base modules, "
          f"{'CLEAN' if not FAIL else 'DIRTY'}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('rung')
    ap.add_argument('base', nargs='?')
    ap.add_argument('--n', type=int)
    ap.add_argument('--negative', action='store_true')
    a = ap.parse_args()
    if a.negative:
        negative(a.rung)
    else:
        k = 0
        for f in sorted(glob.glob(os.path.join(a.rung,
                                               '*.rgs_reference_main.spv'))):
            b = os.path.join(a.base, os.path.basename(f))
            if not os.path.exists(b):
                raise SystemExit(f"no base for {f}")
            verify_module(os.path.basename(f).split('.')[0], dis(f), dis(b),
                          a.n)
            k += 1
        if k != 12:
            bad('rung', f"{k} reference modules verified, expected 12")
        print(f"  verify_bounce: {k}/12 modules, floor n={a.n}")
    if FAIL:
        print("VERIFY FAILED:\n  " + "\n  ".join(FAIL))
        sys.exit(1)
    print("  verify_bounce: PASS")


if __name__ == '__main__':
    main()
