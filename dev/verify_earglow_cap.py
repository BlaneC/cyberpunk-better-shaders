#!/usr/bin/env python3
"""verify_earglow_cap.py <rung-dir> --base <base-dir> --cap METRES
                         [--k K] [--wide W] --wrap R [--skip-rq3]
   verify_earglow_cap.py --negative <base-dir>

Re-derives the THICKNESS FLOOR (handoff/101 sec 18) from the SHIPPED .spv
bytes. Never from the patcher's reports, never from a byte diff.

Two halves, and the first one is not optional:

  A. the rq3 rung underneath is STILL the rung it claims to be. This runs
     verify_earglow_rq3.py as a subprocess against the same directory, so all
     of its checks (three queries, flags 545/517/517, the bracket, the sun
     mask, the instance match, query C's origin and its LogicalNot, the gate,
     the census, the transfer constants, the writes) must pass on the capped
     bytes too. A cap that broke the rung would fail here, not be excused by
     the fact that this file only knows about caps.

  B. THE ONE NEW VARIABLE, re-derived structurally -- never by counting
     NMax, because the shipped modules already contain several of their own:

     1  exactly ONE OpRayQueryGetIntersectionTKHR  ->  t
     2  exactly ONE guard OpSelect(_, t, _)        ->  t_guarded
     3  exactly ONE OpExtInst _ NMax with t_guarded as its FIRST operand
        -> t_eff, and its second operand is an OpConstant %float equal to the
        REQUESTED cap. This is what rejects `cap3 read as cap4` and what
        rejects the uncapped default read as a cap rung (no such instruction).
        The opcode must be NMax and not NMin: NMin would be a CEILING on
        thickness, i.e. a floor on brightness -- the exact opposite -- and
        `--decoy capmin` builds it.
     4  the transfer: every OpFMul that heads an FMul->FNegate->Exp chain
        takes t_eff, there are 6 of them (dual lobe) or 3 (single), and NOT
        ONE of them takes t_guarded. `--decoy nocap` emits the NMax and leaves
        the chains on t_guarded, and this is the check that catches it: the
        cap is a data-flow fact, not the presence of an opcode.
     5  query C's push is OpFAdd(t_guarded, 0.001) -- the RAW t. The cap is in
        the TRANSFER, not in the RAY: capping the push would move the
        sun-visibility ray's origin and silently ask a different geometric
        question. `--decoy capray` builds exactly that and dies here.
     6  the consumers of t_guarded are EXACTLY {the NMax, the push}. No third
        consumer, so nothing in the module reads the uncapped thickness by a
        path this file has not accounted for.

`--negative` asserts the base carries no ray query at all (delegated).
"""
import argparse, glob, os, re, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import verify_earglow_rq as V
from verify_earglow_rq import dis, index, fval, close, bad, PASS_THROUGH

HERE = os.path.dirname(os.path.abspath(__file__))
PUSH_M = 0.001


def _res(l):
    m = re.match(r'\s*(%\w+)\s*=\s*Op', l)
    return m.group(1) if m else None


def check_cap(path, cap, name):
    lines = dis(path)
    d = index(lines)

    tg = [l for l in lines if 'OpRayQueryGetIntersectionTKHR' in l]
    if len(tg) != 1:
        return bad(name, f"{len(tg)} committed-T getters, want 1")
    t = _res(tg[0])

    gs = [l for l in lines
          if re.match(rf'\s*%\w+ = OpSelect %float %\w+ {t} %\w+\s*$', l)]
    if len(gs) != 1:
        return bad(name, f"{len(gs)} guards OpSelect(_, {t}, _), want 1")
    tu = _res(gs[0])

    # 3. the floor itself
    nm = [l for l in lines
          if re.match(rf'\s*%\w+ = OpExtInst %float %\w+ N(Max|Min) {tu} %\w+\s*$', l)]
    if len(nm) != 1:
        return bad(name, f"{len(nm)} N(Max|Min) on the guarded t {tu}, want "
                         f"exactly 1 -- an uncapped rung has none")
    m = re.match(r'\s*(%\w+) = OpExtInst %float %\w+ N(Max|Min) %\w+ (%\w+)\s*$',
                 nm[0])
    teff, op, cid = m.group(1), 'N' + m.group(2), m.group(3)
    if op != 'NMax':
        return bad(name, f"the floor is {op}, not NMax -- NMin caps thickness "
                         f"from ABOVE, which brightens thick flesh instead of "
                         f"limiting thin")
    got = fval(d, cid)
    if got is None:
        return bad(name, f"the floor's second operand {cid} is not a float "
                         f"constant")
    if not close(got, cap, rel=1e-5):
        return bad(name, f"floor is {got} m, requested {cap} m")

    # 4. the transfer runs on t_eff and nothing runs on t_guarded
    heads = []
    for l in lines:
        mm = re.match(r'\s*(%\w+) = OpFMul %float (%\w+) %\w+\s*$', l)
        if not mm:
            continue
        r, a0 = mm.group(1), mm.group(2)
        if a0 not in (tu, teff):
            continue
        neg = [x for x in lines
               if re.match(rf'\s*%\w+ = OpFNegate %float {r}\s*$', x)]
        if len(neg) != 1:
            continue
        nr = _res(neg[0])
        exp = [x for x in lines
               if re.match(rf'\s*%\w+ = OpExtInst %float %\w+ Exp {nr}\s*$', x)]
        if len(exp) == 1:
            heads.append((r, a0))
    if not heads:
        return bad(name, "no FMul->FNegate->Exp transfer chain found off the "
                         "thickness at all")
    on_raw = [r for r, a0 in heads if a0 == tu]
    if on_raw:
        return bad(name, f"{len(on_raw)} transfer chain(s) still read the "
                         f"UNCAPPED t ({on_raw[:3]}) -- the floor is emitted "
                         f"but not wired")
    if len(heads) not in (3, 6):
        return bad(name, f"{len(heads)} capped transfer chains, want 3 or 6")

    # 5/6. every consumer of the raw guarded t, classified
    push = []
    for l in lines:
        toks = re.findall(r'%\w+', l)
        ops = toks[1:] if _res(l) else toks
        if tu not in ops:
            continue
        if _res(l) == teff:
            continue
        mm = re.match(rf'\s*(%\w+) = OpFAdd %float {tu} (%\w+)\s*$', l)
        if mm:
            v = fval(d, mm.group(2))
            if v is None or not close(v, PUSH_M, rel=1e-5):
                return bad(name, f"the push off the raw t adds {v}, want "
                                 f"{PUSH_M}")
            push.append(mm.group(1))
            continue
        if l is gs[0] or _res(l) == tu:
            continue
        return bad(name, f"an unaccounted consumer of the UNCAPPED t: "
                         f"{l.strip()[:90]}")
    if len(push) != 1:
        return bad(name, f"{len(push)} pushes off the raw t, want exactly 1 "
                         f"(query C's origin) -- if 0, the cap was applied to "
                         f"the RAY and query C now starts at the wrong point")
    return len(heads)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('rung', nargs='?')
    ap.add_argument('--base')
    ap.add_argument('--negative')
    ap.add_argument('--cap', type=float)
    ap.add_argument('--k', type=float, default=0.22)
    ap.add_argument('--wide', type=float)
    ap.add_argument('--wrap', type=float)
    ap.add_argument('--skip-rq3', action='store_true',
                    help='skip half A (only for the self-test of this file)')
    a = ap.parse_args()
    if a.negative:
        r = subprocess.run([sys.executable,
                            os.path.join(HERE, 'verify_earglow_rq3.py'),
                            '--negative', a.negative])
        raise SystemExit(r.returncode)
    if not a.rung or not a.base or a.cap is None:
        ap.error('need <rung-dir> --base <base-dir> --cap METRES')

    if not a.skip_rq3:
        cmd = [sys.executable, os.path.join(HERE, 'verify_earglow_rq3.py'),
               a.rung, '--base', a.base, '--mode', 'glow',
               '--k', str(a.k), '--wrap', str(a.wrap), '--floor']
        if a.wide is not None:
            cmd += ['--wide', str(a.wide)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        sys.stdout.write('  [rq3] ' + r.stdout.strip().replace('\n', '\n  [rq3] ')
                         + '\n')
        if r.returncode != 0:
            sys.stdout.write(r.stderr)
            print("  FAIL the rq3 rung underneath does not verify")
            raise SystemExit(1)

    n = tot = 0
    for p in sorted(glob.glob(os.path.join(a.rung, '*.rgs_reference_main.spv'))):
        ident = os.path.basename(p).split('.')[0]
        if ident in PASS_THROUGH:
            continue
        tot += check_cap(p, a.cap, os.path.basename(p)) or 0
        n += 1
    print(f"verify_earglow_cap: {n} permutations, {tot} capped transfer "
          f"chains, floor = {a.cap*1e3:g} mm (NMax on the guarded t, "
          f"query C's push left RAW)")
    if V.FAIL:
        for f in V.FAIL:
            print("  FAIL " + f)
        raise SystemExit(1)
    print("  ALL PASS")


if __name__ == '__main__':
    main()
