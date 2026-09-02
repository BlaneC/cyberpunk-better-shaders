#!/usr/bin/env python3
"""Verify the handoff/93 sec 5 light-struct debug paint FROM THE SHIPPED BYTES.

Nothing here trusts the patcher's report. Each module is re-disassembled from
the .spv that will actually be served, the class word and the PATH counter are
re-derived structurally (40 sec 8: ids are not comparable across the round
trip), and every numeric knob is checked by RESOLVED CONSTANT VALUE.

Non-vacuous on all six axes -- wrong mode, wrong rscale, wrong uscale, wrong
sscale, a paint that reads the wrong struct offset, and a gate on the SAMPLE
counter instead of the path counter (90 sec 1) all FAIL.

  ./dev/verify_cavity_probe.py DIR BASEDIR --mode u --rscale 20 --uscale 0.5
  ./dev/verify_cavity_probe.py --negative BASEDIR
"""
import argparse, glob, os, re, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import patch_earglow as E
from patch_cavity2 import find_class_word, find_path_counter
from patch_chs_brdf import load_lenient
from patch_cavity_probe import (find_paint_site, _uses, EPS, STRIDE,
                                OFF_RANGE, OFF_RAD, OFF_SPOT)

FAIL = []


def bad(m):
    FAIL.append(m)


def dis(spv):
    fd, p = tempfile.mkstemp(suffix='.spvasm')
    os.close(fd)
    subprocess.run(['spirv-dis', spv, '-o', p], check=True,
                   capture_output=True)
    return p


def fvals(mod):
    out = {}
    for ln in mod.lines:
        m = re.match(r'\s*(%\w+)\s*=\s*OpConstant %float ([-\d.e+]+)\s*$', ln)
        if m:
            out[m.group(1)] = float(m.group(2))
    return out


def close(a, b, rel=1e-5):
    return abs(a - b) <= rel * max(1.0, abs(b))


def check(mod, mode, rscale, uscale, sscale, negative):
    name = mod.name
    eline, fid = E._entry(mod, 'RayGenerationKHR')
    fs, fe = E._func_span(mod, fid)
    D = {}
    for i, ln in enumerate(mod.lines):
        m = re.match(r'\s*(%\w+)\s*=\s*(Op\S+.*?)\s*$', ln)
        if m:
            D[m.group(1)] = m.group(2)
    FC = fvals(mod)

    # --- the site, re-derived structurally, exactly as the patcher does ---
    site = find_paint_site(mod, fs, fe)
    ext = site["ext"]

    # --- the paint: one OpSelect per radiance extract, sharing one gate ----
    trio, gates = {}, set()
    for i in range(fs, fe):
        m = re.match(r'\s*(%\w+)\s*=\s*OpSelect %float (%\w+) (%\w+) (%\w+)\s*$',
                     mod.lines[i])
        if m and m.group(4) in ext:
            trio[m.group(4)] = (m.group(1), m.group(3))
            gates.add(m.group(2))
    if negative:
        if trio:
            bad(f"{name}: NEGATIVE CONTROL -- base already paints "
                f"{sorted(trio)}")
        return
    if len(trio) != 3 or set(trio) != set(ext):
        bad(f"{name}: {len(trio)} painted radiance extracts, expected 3 "
            f"({ext})")
        return
    if len(gates) != 1:
        bad(f"{name}: the 3 paint selects use {len(gates)} distinct gates")
        return
    gate = gates.pop()

    # --- the gate, re-derived (90 sec 1): class 1 AND PATH counter == 0 ----
    cls_word, _, _ = find_class_word(mod, fs, fe)
    path_ctr, _ = find_path_counter(mod, fs, fe)
    ga = D.get(gate, '')
    m = re.match(r'OpLogicalAnd %\w+ (%\w+) (%\w+)$', ga)
    if not m:
        bad(f"{name}: gate {gate} is not an OpLogicalAnd: {ga}")
        return
    conj = {D.get(x, '') for x in m.groups()}
    if not any(c.startswith('OpIEqual') and cls_word in c and '%uint_1' in c
               for c in conj):
        bad(f"{name}: gate does not test the re-derived class word "
            f"{cls_word} == 1 (got {conj})")
    if not any(c.startswith('OpIEqual') and path_ctr in c and '%uint_0' in c
               for c in conj):
        bad(f"{name}: gate does not test the re-derived PATH counter "
            f"{path_ctr} == 0 -- 90 sec 1's defect (got {conj})")

    # --- identity when dead: each original keeps exactly one use, ours -----
    for e in ext:
        u = _uses(mod, e)
        if len(u) != 1 or not u[0][1].strip().startswith(trio[e][0] + ' '):
            bad(f"{name}: original extract {e} has {len(u)} remaining use(s), "
                f"expected exactly 1 (our OpSelect {trio[e][0]})")

    u12, u44 = site["off12"], site["off44"]

    def halves(src):
        """(ids equal to LO, ids equal to HI) of the packed half2 in `src`.

        Returns SETS, not ids: the engine unpacks this same word itself, so an
        id comparison would fail on a semantically correct paint. This checks
        the VALUE's provenance -- the offset-12 (or -44) raw load -- which is
        the axis that must be non-vacuous.
        """
        shifted = {k for k, v in D.items()
                   if v == f"OpShiftRightLogical %uint {src} %uint_16"}

        def ext0(srcs):
            unp = set()
            for k, v in D.items():
                m2 = re.match(r'OpExtInst %\w+ %\w+ UnpackHalf2x16 (%\w+)$', v)
                if m2 and m2.group(1) in srcs:
                    unp.add(k)
            return {k for k, v in D.items()
                    if any(v == f"OpCompositeExtract %float {u} 0"
                           for u in unp)}
        return ext0({src}), ext0(shifted)

    def sat_of(sel_id):
        v = D.get(sel_id, '')
        m2 = re.match(r'OpExtInst %float %\w+ NClamp (%\w+) %float_0 '
                      r'%float_1$', v)
        return m2.group(1) if m2 else None

    def mul_by(x, operands, want):
        m2 = re.match(r'OpFMul %float (%\w+) (%\w+)$', D.get(x, ''))
        if not m2:
            return False
        for src, con in (m2.groups(), m2.groups()[::-1]):
            if src in operands and FC.get(con) is not None \
                    and close(FC[con], want):
                return True
        return False

    pr, pg, pb = (trio[ext[0]][1], trio[ext[1]][1],
                  trio[ext[2]][1])

    R, U = halves(u12)
    if not R or not U:
        bad(f"{name}: could not re-derive the offset-{OFF_RANGE} half2 "
            f"(lo={sorted(R)} hi={sorted(U)})")
        return


    # --- blue: the scale-free ratio anchor, in BOTH modes ------------------
    inner = sat_of(pb)
    ok = False
    if inner:
        v = D.get(inner, '')
        m2 = re.match(r'OpFDiv %float (%\w+) (%\w+)$', v)
        if m2 and m2.group(1) in U:
            g2 = D.get(m2.group(2), '')
            m3 = re.match(r'OpExtInst %float %\w+ NMax (%\w+) (%\w+)$', g2)
            ok = (bool(m3) and m3.group(1) in R
                  and close(FC.get(m3.group(2), -1), EPS))
    if not ok:
        bad(f"{name}: blue channel is not saturate(U / NMax(R, {EPS})) "
            f"reading the offset-{OFF_RANGE} half2")

    if mode == 'u':
        ir, ig = sat_of(pr), sat_of(pg)
        if not (ir and mul_by(ir, R, 1.0 / rscale)):
            bad(f"{name}: red channel is not saturate(range * 1/{rscale}) "
                f"off the offset-{OFF_RANGE} LOW half")
        if not (ig and mul_by(ig, U, 1.0 / uscale)):
            bad(f"{name}: green channel is not saturate(U * 1/{uscale}) "
                f"off the offset-{OFF_RANGE} HIGH half")
    else:
        if u44 is None:
            bad(f"{name}: no offset-{OFF_SPOT} load to decode")
            return
        SC, BI = halves(u44)
        ir = sat_of(pr)
        if not (SC and ir and mul_by(ir, SC, 1.0 / sscale)):
            bad(f"{name}: red channel is not saturate(spot_scale * "
                f"1/{sscale}) off the offset-{OFF_SPOT} LOW half")
        if sat_of(pg) not in BI:
            bad(f"{name}: green channel is not saturate(spot_bias) off the "
                f"offset-{OFF_SPOT} HIGH half")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('dirs', nargs='+')
    ap.add_argument('--negative', action='store_true')
    ap.add_argument('--mode', choices=('u', '44'), default='u')
    ap.add_argument('--rscale', type=float, default=20.0)
    ap.add_argument('--uscale', type=float, default=0.5)
    ap.add_argument('--sscale', type=float, default=2.0)
    a = ap.parse_args()
    d = a.dirs[0]
    mods = sorted(glob.glob(os.path.join(d, '*.rgs_reference_main.spv')))
    if len(mods) != 12:
        print(f"FAIL: {len(mods)} rgs_reference_main in {d}, expected 12")
        sys.exit(1)
    for spv in mods:
        p = dis(spv)
        try:
            mod, _ = load_lenient(p)
            mod.name = os.path.basename(spv).split('.')[0]
            check(mod, a.mode, a.rscale, a.uscale, a.sscale, a.negative)
        finally:
            os.unlink(p)
    if FAIL:
        print(f"verify_cavity_probe: FAIL ({len(FAIL)})")
        for f in FAIL[:24]:
            print("  " + f)
        sys.exit(1)
    what = 'negative control clean' if a.negative else \
        f"mode={a.mode} rscale={a.rscale} uscale={a.uscale} sscale={a.sscale}"
    print(f"  verify_cavity_probe.py PASS  12/12 modules  ({what})")


if __name__ == '__main__':
    main()
