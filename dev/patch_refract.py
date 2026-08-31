#!/usr/bin/env python3
"""Phase 0.5 glass refraction (handoff/20 §5b, 51 §4): repoint the traced
mirror direction of ee6d252e090adc74.rgs_reflection_transparent_main to the
refracted one and push the ray origin through the surface.

Authored as text on the COMMITTED ptrefl spvasm (swaps.ptrefl/, cullMask
already widened 1->255 -- wanted for a transmitted ray, 20 §5b) and
reassembled with spirv-as, the original repo pattern for raygen work.

The splice, all straight-line (no new blocks, no new globals -- SPIR-V 1.4
interface list untouched):

    c2 = dot(D,N)^2                     ; %235 is the module's own dot(D,N)
    k  = 1 - eta^2 * (1 - c2)           ; eta = 1/n < 1  =>  k >= 1-eta^2 > 0,
    T  = eta*D - (eta*dot(D,N) + sqrt(k)) * N   ;  TIR is IMPOSSIBLE, no branch
    O' = P + eps*(1+9*fade)*D           ; vanilla is P - eps*...*D, which sits
                                        ; OUTSIDE the glass and self-hits a
                                        ; transmitted ray (20 §1 corr 08-28)

Then every downstream use of the mirror direction (%242-244) and the origin
(%232-234) is rewritten to the new ids -- trace, env-miss lookup, horizon
fade, hit reconstruction, SSR reprojection -- so the whole tail agrees on
what ray was traced. Exactly 19 lines must rewrite or we die.

Head-on sanity: D=-N => dot=-1, k=1, T = eta*D + (1-eta)*D = D: straight
through, as physics says. Verified numerically below on every build.
"""
import argparse, pathlib, re, struct, subprocess, sys, tempfile

SRC_DEFAULT = "swaps.ptrefl/ee6d252e090adc74.rgs_reflection_transparent_main.spvasm"
MODULE = "ee6d252e090adc74.rgs_reflection_transparent_main"

def die(msg):
    sys.exit(f"patch_refract: FATAL: {msg}")

def f32(x):
    return struct.unpack("f", struct.pack("f", x))[0]

# --- anchors: exact instruction shapes, not line numbers (die-on-guess) -----
ANCHORS = {
    # id : (regex the defining line must match, what it is)
    235: (r"%235 = OpDot %float %236 %237$",            "dot(D,N)"),
    236: (r"%236 = OpCompositeConstruct %v3float %201 %202 %203$", "D"),
    237: (r"%237 = OpCompositeConstruct %v3float %131 %132 %133$", "N"),
    242: (r"%242 = OpFSub %float %201 %239$",           "mirror.x"),
    243: (r"%243 = OpFSub %float %202 %240$",           "mirror.y"),
    244: (r"%244 = OpFSub %float %203 %241$",           "mirror.z"),
    232: (r"%232 = OpFSub %float %193 %227$",           "origin.x = P.x - eps.x"),
    233: (r"%233 = OpFSub %float %194 %229$",           "origin.y = P.y - eps.y"),
    234: (r"%234 = OpFSub %float %195 %231$",           "origin.z = P.z - eps.z"),
}
TRACE_RE = r"OpTraceRayKHR %262 %uint_16 %uint_(255|1) %uint_1 %uint_1 %uint_0 %265 %float_9_99999997en07 %266 %254 %57$"
CONST_ANCHOR = "%float_1 = OpConstant %float 1"
EXPECT_REWRITES = 19   # counted from the committed disasm; changes mean the
                       # module changed under us and every claim needs re-audit

def build(src_path, n_glass, out_dir):
    eta  = f32(1.0 / n_glass)
    eta2 = f32(eta * eta)
    lines = pathlib.Path(src_path).read_text().splitlines()

    found = {}
    trace_line = None
    for i, ln in enumerate(lines):
        s = ln.strip()
        for k, (rx, _) in ANCHORS.items():
            if re.search(rx, s):
                if k in found: die(f"anchor %{k} matched twice")
                found[k] = i
        if re.search(TRACE_RE, s):
            if trace_line is not None: die("trace anchor matched twice")
            trace_line = i
    for k, (rx, what) in ANCHORS.items():
        if k not in found: die(f"anchor not found: %{k} ({what}) ~ {rx}")
    if trace_line is None: die("OpTraceRayKHR anchor not found")

    const_at = [i for i, ln in enumerate(lines) if ln.strip() == CONST_ANCHOR]
    if len(const_at) != 1: die(f"constant anchor '{CONST_ANCHOR}' x{len(const_at)}")

    # verify our fresh ids are really fresh
    for tok in ["%float_refr_eta", "%float_refr_eta2"] + [f"%{i}" for i in range(2900, 2919)]:
        if any(re.search(re.escape(tok) + r"\b", ln) for ln in lines):
            die(f"id {tok} already in use")

    ind = "        "
    consts = [f"{ind[:4]}%float_refr_eta = OpConstant %float {eta!r}",
              f"{ind[:4]}%float_refr_eta2 = OpConstant %float {eta2!r}"]
    body = [
        "%2900 = OpFMul %float %235 %235",
        "%2901 = OpFSub %float %float_1 %2900",
        "%2902 = OpFMul %float %float_refr_eta2 %2901",
        "%2903 = OpFSub %float %float_1 %2902",
        "%2904 = OpExtInst %float %177 Sqrt %2903",
        "%2905 = OpFMul %float %float_refr_eta %235",
        "%2906 = OpFAdd %float %2905 %2904",
        "%2907 = OpFMul %float %float_refr_eta %201",
        "%2908 = OpFMul %float %float_refr_eta %202",
        "%2909 = OpFMul %float %float_refr_eta %203",
        "%2910 = OpFMul %float %2906 %131",
        "%2911 = OpFMul %float %2906 %132",
        "%2912 = OpFMul %float %2906 %133",
        "%2913 = OpFSub %float %2907 %2910",
        "%2914 = OpFSub %float %2908 %2911",
        "%2915 = OpFSub %float %2909 %2912",
        "%2916 = OpFAdd %float %193 %227",
        "%2917 = OpFAdd %float %194 %229",
        "%2918 = OpFAdd %float %195 %231",
    ]

    # --- numeric self-check of the EMITTED text (typo catcher) --------------
    import random
    def run_block(D, N, P, E):
        env = {235: f32(D[0]*N[0] + D[1]*N[1] + D[2]*N[2]),
               201: D[0], 202: D[1], 203: D[2],
               131: N[0], 132: N[1], 133: N[2],
               193: P[0], 194: P[1], 195: P[2],
               227: E[0], 229: E[1], 231: E[2]}
        named = {"float_1": 1.0, "float_refr_eta": eta, "float_refr_eta2": eta2}
        for b in body:
            m = re.match(r"%(\d+) = Op(\w+) %float (.+)$", b)
            rid, op, rest = int(m.group(1)), m.group(2), m.group(3).split()
            def val(tok):
                tok = tok[1:]
                return env[int(tok)] if tok.isdigit() else named[tok]
            if op == "FMul":   env[rid] = f32(val(rest[0]) * val(rest[1]))
            elif op == "FSub": env[rid] = f32(val(rest[0]) - val(rest[1]))
            elif op == "FAdd": env[rid] = f32(val(rest[0]) + val(rest[1]))
            elif op == "ExtInst":
                assert rest[1] == "Sqrt", rest
                env[rid] = f32(env[int(rest[2][1:])] ** 0.5)
            else: die(f"self-check can't eval {b}")
        return [env[i] for i in (2913, 2914, 2915)], [env[i] for i in (2916, 2917, 2918)]
    rng = random.Random(20)
    import math
    for _ in range(500):
        while True:
            N = [rng.uniform(-1, 1) for _ in range(3)]
            n = math.sqrt(sum(x*x for x in N))
            if n > 1e-3: break
        N = [x/n for x in N]
        while True:
            D = [rng.uniform(-1, 1) for _ in range(3)]
            n = math.sqrt(sum(x*x for x in D))
            if n > 1e-3 and sum(a*b for a, b in zip(D, N))/n < -1e-3: break
        D = [x/n for x in D]
        P = [rng.uniform(-50, 50) for _ in range(3)]
        E = [rng.uniform(0, 0.1) * d for d in D]
        (T, O) = run_block(D, N, P, E)
        c = -sum(a*b for a, b in zip(D, N))
        k = 1 - (1/n_glass)**2 * (1 - c*c)
        ref = [(1/n_glass)*d + ((1/n_glass)*c - math.sqrt(k))*nn for d, nn in zip(D, N)]
        if any(abs(a-b) > 2e-6 for a, b in zip(T, ref)): die(f"refract self-check: {T} vs {ref}")
        if any(abs(a-b) > 1e-4 for a, b in zip(O, [p+e for p, e in zip(P, E)])): die("origin self-check")
        tl = math.sqrt(sum(x*x for x in T))
        if abs(tl - 1) > 1e-5: die(f"T not unit: {tl}")
    print(f"  self-check: 500 random (D,N) OK -- |T|=1, matches reference refract, eta={eta!r}")

    # --- splice -------------------------------------------------------------
    out, rewrites = [], 0
    remap = {242: 2913, 243: 2914, 244: 2915, 232: 2916, 233: 2917, 234: 2918}
    def_lines = set(found.values())
    insert_after = found[244]
    rx_use = re.compile(r"%(24[234]|23[234])\b")
    for i, ln in enumerate(lines):
        if i in def_lines or not rx_use.search(ln):
            out.append(ln)
        else:
            out.append(rx_use.sub(lambda m: f"%{remap[int(m.group(1))]}", ln))
            rewrites += 1
        if ln.strip() == CONST_ANCHOR:
            out.extend(consts)
        if i == insert_after:
            out.extend(ind + b for b in body)
    if rewrites != EXPECT_REWRITES:
        die(f"rewrote {rewrites} lines, expected {EXPECT_REWRITES} -- module changed, re-audit")

    out_dir = pathlib.Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    asm = out_dir / f"{MODULE}.spvasm"
    spv = out_dir / f"{MODULE}.spv"
    asm.write_text("\n".join(out) + "\n")
    r = subprocess.run(["spirv-as", "--target-env", "spv1.4", str(asm), "-o", str(spv)],
                       capture_output=True, text=True)
    if r.returncode: die(f"spirv-as: {r.stderr}")
    r = subprocess.run(["spirv-val", str(spv)], capture_output=True, text=True)
    if r.returncode: die(f"spirv-val: {r.stderr}")
    # identity string must survive so the layer matches the module
    blob = spv.read_bytes()
    if MODULE.replace(".rgs_", ".?rgs_").encode() not in blob.replace(b"@@YAXXZ.dxil", b""):
        if b"ee6d252e090adc74" not in blob: die("dxil identity OpString lost")
    print(f"  {spv} ({len(blob)} B): spirv-as + spirv-val clean, {rewrites} uses rewritten")
    return spv

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=SRC_DEFAULT)
    ap.add_argument("--n", type=float, required=True, help="glass refractive index, e.g. 1.5")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    build(a.src, a.n, a.out)
