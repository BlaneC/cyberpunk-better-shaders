#!/usr/bin/env python3
"""Glass-interface Fresnel on the RT transparent reflection (handoff/20 §1
[corr 08-28], §5b): scale this pass's radiance by the dielectric reflectance
F(theta) of the air->glass interface, computed from the module's own dot(D,N).

WHY THIS AND NOT A BENT RAY.  Vanilla glass is *raster alpha-blend see-through*
+ screen-space Distortion + this pass's traced mirror reflection.  The
see-through is drawn by the raster layer and this module cannot reach it.  For
a flat pane the two glass interfaces cancel -- the exit ray is PARALLEL to the
entry ray, and the only residual is a lateral offset of 0.8/1.3/2.1/3.0 mm at
30/45/60/75 deg through 4 mm float glass.  So the raster see-through already IS
the physically correct transmitted image; what it is missing is the (1-F)
dimming, and what this pass is missing is the F weight on the reflection.
Phase 0.5 (76) instead repointed the traced direction to a SINGLE-interface
Snell bend -- 10.5/16.9/24.7/34.9 deg of deviation where the truth is ~0 -- and
dropped the reflection entirely at every angle.  That is the ghost.

    F is the whole angle-dependent story on flat glass.  Exact unpolarized,
    n=1.5:   theta  0    30    45    60    70    75    80    85    89
             F     .040  .042  .050  .089  .171  .253  .388  .613  .904

TWO HONEST LIMITS, STATED UP FRONT (do not re-chase them):

  1. THIS IS NOT ENERGY-CONSERVING, and it cannot be.  Under an ADDING
     consumer the composite becomes F*reflection + 1.0*transmission, because
     the raster transmission is unreachable and stays undimmed.  Correct
     reflection lobe stapled onto an undimmed see-through; slightly over unity
     at grazing.  The alternative -- writing negative radiance to cancel the
     raster term -- is a denoiser and fp16-clamp landmine.  It is NOT an
     option and is recorded here so nobody gets clever about it later.
  2. "REFRACTION IS INVISIBLE" IS A FLAT-PANE CLAIM, NOT A GLASS CLAIM.
     Bottles, tumblers, curved storefronts and windshield rake do bend
     visibly.  This module has no thickness or curvature input (86 §0: no
     material fetch of any kind), so it cannot tell them apart, and the
     honest choice on a pass that mostly runs on windows is to model the pane.

THE MATH.  --fresnel exact is the unpolarized dielectric Fresnel:

    c   = clamp(|dot(D,N)|, 0, 1)          ; cos theta_i
    g   = sqrt(1 - (1-c^2)/n^2)            ; cos theta_t
    rs  = (c - n*g)/(c + n*g)
    rp  = (n*c - g)/(n*c + g)
    F   = (rs^2 + rp^2)/2

--fresnel schlick is F0 + (1-F0)*(1-c)^5, F0 = ((n-1)/(n+1))^2 = 0.04 at
n=1.5.  Schlick runs up to 4 points high at 80-85 deg -- the exact band this
feature exists to get right -- so `exact` is the default and `schlick` is
built alongside it so the comparison is available rather than argued about.
Exact costs 20 instructions against Schlick's 8; the splice risk that would
normally argue for Schlick is bought off by the 6000-point self-check below.

Both take |dot(D,N)| and NOT clamp(-dot(D,N), 0, 1).  Normal-mapped glass
hands back wrong-sign cosines; clamping a negative to 0 yields F=1, a
full mirror on a pixel at near-normal incidence -- bright rim artifacts.  abs()
folds a flipped normal onto the equivalent front-facing angle instead.  The
outer clamp to 1 guards |dot| > 1 from a denormalized normal, which would
otherwise put a NaN in the sqrt.

NO BRANCH IS NEEDED AND NO DENOMINATOR CAN VANISH.  Entering a denser medium
(n>1) makes TIR impossible: 1-(1-c^2)/n^2 >= 1-1/n^2 > 0, so g >= sqrt(1-1/n^2)
and the two denominators are bounded below by sqrt(n^2-1) and sqrt(1-1/n^2)
(1.118 and 0.745 at n=1.5).  The build asserts that bound numerically over the
whole sample rather than trusting the algebra.

THE SITE is handoff/86 §2's: the radiance triple exists as a single named value
in exactly one place, the phis %273/%275/%277 at the top of block %2827, which
merges the env-miss arm (%2826) with the hit arm after aerial-perspective fog
(%2825).  %235 = dot(D,N) is defined at :512, on the gate-pass path that is the
only way into %2827, so it dominates the site.  Both are upstream of the module
clamp at %2830, so GOTCHAS "scale before a clamp" holds.  All 6 downstream uses
on 4 lines are rewritten or the build dies.  Alpha is the gate DEPTH (20 §1)
and is not touched by any mode here.

TWO DIAGNOSTIC MODES, because two independent unknowns gate the look:

  --mode null   radiance := 0.  Answers handoff/20 open item 1: if glass keeps
                its see-through, the consumer ADDS and our term is an overlay;
                if glass goes black, it REPLACES.  Weaker than it looks -- the
                Phase 0.5 ghost is itself evidence for ADDS, since a replacing
                consumer would show one bent copy, not two.
  --mode flat   radiance := a constant, regardless of what was traced.  Answers
                the unknown `null` CANNOT see: does the consumer apply its OWN
                Fresnel?  A raygen writing raw mirror radiance with no F is
                exactly what an engine does when the BRDF weight lives in the
                composite pass.  If the composited glass reflection still
                varies with viewing angle under constant input, downstream
                already multiplies by F and `fres` would double-apply it to
                F^2 -- near-invisible except at grazing, and hard to diagnose
                after the fact.  Run this BEFORE believing `fres`.

strength=0 emits NOTHING and rebuilds byte-identically -- the knob-0 control,
guarding the GOTCHAS trap "48 bytes of OpConstant nothing consumes".
"""
import argparse, math, pathlib, re, struct, subprocess, sys

SRC_DEFAULT = "swaps.ptrefl/ee6d252e090adc74.rgs_reflection_transparent_main.spvasm"
MODULE = "ee6d252e090adc74.rgs_reflection_transparent_main"

EXPECT_REWRITES = 6          # %273 x2, %275 x2, %277 x2 -- on 4 lines
# Fresnel lives below patch_refract.py's 2900-2918 and patch_refract_absorb's
# 3000+ so the three patchers stay composable (apply absorb last).
ID_BASE = 2850
ID_CEIL = 2900


def die(msg):
    sys.exit(f"patch_glass_fresnel: FATAL: {msg}")


def f32(x):
    return struct.unpack("f", struct.pack("f", x))[0]


# --- anchors: exact instruction shapes, not line numbers (die-on-guess) ----
ANCHORS = {
    "phi_r": (r"^%273 = OpPhi %float %336 %2826 %562 %2825$", "radiance.r at block 2827"),
    "phi_g": (r"^%275 = OpPhi %float %337 %2826 %563 %2825$", "radiance.g at block 2827"),
    "phi_b": (r"^%277 = OpPhi %float %338 %2826 %564 %2825$", "radiance.b at block 2827"),
    "dot":   (r"^%235 = OpDot %float %236 %237$",             "dot(D,N)"),
    "D":     (r"^%236 = OpCompositeConstruct %v3float %201 %202 %203$", "D"),
    "N":     (r"^%237 = OpCompositeConstruct %v3float %131 %132 %133$", "N"),
}
# Negative control.  Fresnel weights the MIRROR term; on a Phase 0.5 rung the
# traced direction is refracted and the weight would mean nothing.  Refuse.
PHASE05_MARKER = r"^%float_refr_eta = OpConstant %float "
CONST_ANCHOR = "%float_1 = OpConstant %float 1"
NEEDED_CONSTS = ["%float_0 ", "%float_1 ", "%float_0_5 "]


def emit(mode, kind, n_glass, strength, flat_value):
    """Return (const_lines, body_lines, final_tokens, mult_token).

    final_tokens are what the three radiance uses get rewritten to; they may be
    instruction results or plain constants.  Empty body => byte-inert rebuild.
    """
    if mode == "fresnel" and strength == 0.0:
        return [], [], None, None

    if mode == "null":
        return [], [], ("%float_0",) * 3, "%float_0"
    if mode == "flat":
        c = f"    %float_fres_flat = OpConstant %float {f32(flat_value)!r}"
        return [c], [], ("%float_fres_flat",) * 3, "%float_fres_flat"

    i = ID_BASE
    B, consts = [], []

    def nid():
        nonlocal i
        i += 1
        if i >= ID_CEIL:
            die(f"id space exhausted at %{i} (ceiling {ID_CEIL})")
        return i - 1

    a, c = nid(), nid()
    B += [f"%{a} = OpExtInst %float %177 FAbs %235",
          f"%{c} = OpExtInst %float %177 NClamp %{a} %float_0 %float_1"]

    if kind == "schlick":
        f0 = f32(((n_glass - 1.0) / (n_glass + 1.0)) ** 2)
        consts += [f"    %float_fres_f0 = OpConstant %float {f0!r}",
                   f"    %float_fres_1mf0 = OpConstant %float {f32(1.0 - f0)!r}"]
        m, m2, m4, m5, t, F = (nid() for _ in range(6))
        B += [f"%{m} = OpFSub %float %float_1 %{c}",
              f"%{m2} = OpFMul %float %{m} %{m}",
              f"%{m4} = OpFMul %float %{m2} %{m2}",
              f"%{m5} = OpFMul %float %{m4} %{m}",
              f"%{t} = OpFMul %float %float_fres_1mf0 %{m5}",
              f"%{F} = OpFAdd %float %float_fres_f0 %{t}"]
    else:
        inv_n2 = f32(1.0 / f32(n_glass * n_glass))
        consts += [f"    %float_fres_n = OpConstant %float {f32(n_glass)!r}",
                   f"    %float_fres_invn2 = OpConstant %float {inv_n2!r}"]
        cc, s2, st2, g2, g2c, g = (nid() for _ in range(6))
        ng, ns, ds, rs, nc, np_, dp, rp = (nid() for _ in range(8))
        rs2, rp2, ssum, F = (nid() for _ in range(4))
        B += [
            f"%{cc} = OpFMul %float %{c} %{c}",
            f"%{s2} = OpFSub %float %float_1 %{cc}",
            f"%{st2} = OpFMul %float %{s2} %float_fres_invn2",
            f"%{g2} = OpFSub %float %float_1 %{st2}",
            f"%{g2c} = OpExtInst %float %177 NMax %{g2} %float_0",
            f"%{g} = OpExtInst %float %177 Sqrt %{g2c}",
            f"%{ng} = OpFMul %float %float_fres_n %{g}",
            f"%{ns} = OpFSub %float %{c} %{ng}",
            f"%{ds} = OpFAdd %float %{c} %{ng}",
            f"%{rs} = OpFDiv %float %{ns} %{ds}",
            f"%{nc} = OpFMul %float %float_fres_n %{c}",
            f"%{np_} = OpFSub %float %{nc} %{g}",
            f"%{dp} = OpFAdd %float %{nc} %{g}",
            f"%{rp} = OpFDiv %float %{np_} %{dp}",
            f"%{rs2} = OpFMul %float %{rs} %{rs}",
            f"%{rp2} = OpFMul %float %{rp} %{rp}",
            f"%{ssum} = OpFAdd %float %{rs2} %{rp2}",
            f"%{F} = OpFMul %float %{ssum} %float_0_5",
        ]

    mult = f"%{F}"
    if strength != 1.0:
        consts.append(f"    %float_fres_s = OpConstant %float {f32(strength)!r}")
        fm1, sc, M = nid(), nid(), nid()
        B += [f"%{fm1} = OpFSub %float %{F} %float_1",
              f"%{sc} = OpFMul %float %float_fres_s %{fm1}",
              f"%{M} = OpFAdd %float %float_1 %{sc}"]
        mult = f"%{M}"

    finals = []
    for cid in (273, 275, 277):
        fid = nid()
        B.append(f"%{fid} = OpFMul %float %{cid} {mult}")
        finals.append(f"%{fid}")
    return consts, B, tuple(finals), mult


# --- interpreter over the EMITTED text (the typo catcher) -----------------
OPS = {
    "OpFMul": lambda a, b: f32(a * b),
    "OpFAdd": lambda a, b: f32(a + b),
    "OpFSub": lambda a, b: f32(a - b),
    "OpFDiv": lambda a, b: f32(a / b),
}
EXT = {
    "FAbs":   abs,
    "Sqrt":   math.sqrt,
    "NMax":   max,
    "NClamp": lambda a, b, c: min(max(a, b), c),
}


def run_block(body, consts_env, dot_dn, rad):
    """Execute the emitted instructions on one sample. Returns (env, denoms)."""
    env = dict(consts_env)
    env.update({"235": dot_dn, "273": rad[0], "275": rad[1], "277": rad[2]})
    denoms = []

    def val(tok):
        k = tok.lstrip("%")
        if k not in env:
            die(f"self-check: unknown operand {tok} in emitted text")
        return env[k]

    for b in body:
        m = re.match(r"%(\S+) = OpExtInst %float %177 (\w+) (.+)$", b)
        if m:
            dst, fn, args = m.group(1), m.group(2), m.group(3).split()
            if fn not in EXT:
                die(f"self-check: unmodelled ext inst {fn}")
            env[dst] = f32(EXT[fn](*[val(x) for x in args]))
            continue
        m = re.match(r"%(\S+) = (Op\w+) %float (\S+) (\S+)$", b)
        if not m:
            die(f"self-check: unparsed instruction: {b}")
        dst, op, x, y = m.groups()
        if op not in OPS:
            die(f"self-check: unmodelled op {op}")
        if op == "OpFDiv":
            denoms.append(abs(val(y)))
        env[dst] = OPS[op](val(x), val(y))
    return env, denoms


def fresnel_ref(cos_i, n, kind):
    """Independently written reference. Not shared with emit() by design."""
    c = min(max(abs(cos_i), 0.0), 1.0)
    if kind == "schlick":
        f0 = ((n - 1.0) / (n + 1.0)) ** 2
        return f0 + (1.0 - f0) * (1.0 - c) ** 5
    g = math.sqrt(max(0.0, 1.0 - (1.0 - c * c) / (n * n)))
    rs = (c - n * g) / (c + n * g)
    rp = (n * c - g) / (n * c + g)
    return (rs * rs + rp * rp) / 2.0


def selfcheck(body, consts, finals, mult, mode, kind, n_glass, strength, npts):
    import random
    rng = random.Random(20260901)
    consts_env = {"float_0": 0.0, "float_1": 1.0, "float_0_5": 0.5}
    for c in consts:
        consts_env[c.split()[0].lstrip("%")] = f32(float(c.split()[-1]))

    worst_m, worst_out, min_den, seen_hi = 0.0, 0.0, float("inf"), False
    for j in range(npts):
        # cover the sphere of incidence incl. exact grazing and exact normal,
        # BOTH normal orientations, and radiance over 6 decades incl. 0 and <0
        if j < 8:
            dot_dn = [-1.0, 1.0, 0.0, -1e-8, -0.9999999, 1e-8, -0.5, 0.5][j]
        else:
            dot_dn = math.cos(rng.uniform(0.0, math.pi))
        rad = tuple(rng.choice([0.0, -rng.uniform(0, 5), rng.uniform(1e-3, 1e3)])
                    for _ in range(3))
        env, denoms = run_block(body, consts_env, f32(dot_dn), rad)
        min_den = min([min_den] + denoms)
        if abs(dot_dn) < 0.09:            # ~>85 deg: the band we care about
            seen_hi = True

        m_ref = 1.0 + strength * (fresnel_ref(dot_dn, n_glass, kind) - 1.0)
        m_got = env[mult.lstrip("%")]
        worst_m = max(worst_m, abs(m_got - m_ref) / max(abs(m_ref), 1e-6))
        for tok, r in zip(finals, rad):
            got, want = env[tok.lstrip("%")], f32(m_ref * r)
            worst_out = max(worst_out, abs(got - want) / max(abs(want), 1e-6))

    if worst_out > 1e-5:
        die(f"self-check: worst relative output error {worst_out:.3e} > 1e-5")
    if worst_m > 1e-5:
        die(f"self-check: worst relative multiplier error {worst_m:.3e} > 1e-5")
    if not seen_hi:
        die("self-check: no grazing samples drawn -- sampler is broken")
    if kind == "exact":
        bound = min(math.sqrt(n_glass * n_glass - 1.0),
                    math.sqrt(1.0 - 1.0 / (n_glass * n_glass)))
        if min_den < 0.5 * bound:
            die(f"self-check: |denominator| fell to {min_den:.6f}, below the "
                f"proven bound {bound:.6f} -- the no-TIR argument is wrong")
    print(f"  self-check {npts} pts: worst rel err out={worst_out:.2e} "
          f"mult={worst_m:.2e}" +
          (f", min|denom|={min_den:.4f}" if min_den < float("inf") else ""))


def build(src_path, mode, kind, n_glass, strength, flat_value, out_dir, npts):
    lines = pathlib.Path(src_path).read_text().splitlines()
    stripped = [ln.strip() for ln in lines]

    if any(re.match(PHASE05_MARKER, s) for s in stripped):
        die(f"{src_path} carries Phase 0.5's %float_refr_eta marker. Fresnel "
            f"weights the MIRROR reflection; on a refracted rung the weight is "
            f"meaningless. Patch the plain ptrefl raygen. Refusing.")

    found = {}
    for i, s in enumerate(stripped):
        for k, (rx, _) in ANCHORS.items():
            if re.match(rx, s):
                if k in found:
                    die(f"anchor {k} matched twice")
                found[k] = i
    for k, (rx, what) in ANCHORS.items():
        if k not in found:
            die(f"anchor not found: {k} ({what}) ~ {rx}")
    for c in NEEDED_CONSTS:
        if not any(s.startswith(c) for s in stripped):
            die(f"missing constant {c}")
    const_at = [i for i, s in enumerate(stripped) if s == CONST_ANCHOR]
    if len(const_at) != 1:
        die(f"constant anchor x{len(const_at)}")
    if not (found["phi_r"] + 1 == found["phi_g"] == found["phi_b"] - 1):
        die("radiance phis are not adjacent -- module changed, re-audit")
    nxt = stripped[found["phi_b"] + 1]
    if nxt.startswith("%") and "OpPhi" in nxt:
        die("a fourth OpPhi follows the radiance triple -- re-audit block 2827")
    # dominance: dot(D,N) must be defined before the site that consumes it
    if not found["dot"] < found["phi_r"]:
        die("dot(D,N) is defined after the radiance phis -- dominance broken")

    consts, body, finals, mult = emit(mode, kind, n_glass, strength, flat_value)

    if finals:
        maxid = max(int(m) for m in re.findall(r"%(\d+)\b", "\n".join(lines)))
        if maxid >= ID_BASE:
            die(f"id space collision: module already uses %{maxid} >= {ID_BASE}")
        for tok in [c.split()[0] for c in consts]:
            if any(re.search(re.escape(tok) + r"\b", ln) for ln in lines):
                die(f"id {tok} already in use")
        if body:
            selfcheck(body, consts, finals, mult, mode, kind, n_glass,
                      strength, npts)
    else:
        print("  strength == 0: emitting nothing (byte-inert rebuild)")

    # --- splice ------------------------------------------------------------
    remap = ({273: finals[0], 275: finals[1], 277: finals[2]} if finals else {})
    rx_use = re.compile(r"%(273|275|277)\b")
    def_lines = {found[k] for k in ("phi_r", "phi_g", "phi_b")}
    out, rewrites, rewritten_lines = [], 0, 0
    for i, ln in enumerate(lines):
        if finals and i not in def_lines and rx_use.search(ln):
            new, k = rx_use.subn(lambda m: remap[int(m.group(1))], ln)
            out.append(new)
            rewrites += k
            rewritten_lines += 1
        else:
            out.append(ln)
        if consts and stripped[i] == CONST_ANCHOR:
            out.extend(consts)
        if body and i == found["phi_b"]:
            out.extend("        " + b for b in body)
    if finals and rewrites != EXPECT_REWRITES:
        die(f"rewrote {rewrites} uses on {rewritten_lines} lines, expected "
            f"{EXPECT_REWRITES} -- module changed, re-audit")

    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    asm, spv = out_dir / f"{MODULE}.spvasm", out_dir / f"{MODULE}.spv"
    asm.write_text("\n".join(out) + "\n")
    r = subprocess.run(["spirv-as", "--target-env", "spv1.4", str(asm), "-o", str(spv)],
                       capture_output=True, text=True)
    if r.returncode:
        die(f"spirv-as: {r.stderr}")
    r = subprocess.run(["spirv-val", str(spv)], capture_output=True, text=True)
    if r.returncode:
        die(f"spirv-val: {r.stderr}")
    if b"ee6d252e090adc74" not in spv.read_bytes():
        die("dxil identity OpString lost")
    print(f"  {spv} ({spv.stat().st_size} B): spirv-as + spirv-val clean, "
          f"{len(consts)} consts + {len(body)} instructions, "
          f"{rewrites} uses rewritten on {rewritten_lines} lines")
    if body and mode == "fresnel":
        tbl = "  ".join(
            f"{d}:{1.0 + strength * (fresnel_ref(math.cos(math.radians(d)), n_glass, kind) - 1.0):.3f}"
            for d in (0, 45, 60, 75, 85))
        print(f"  {kind} n={n_glass} strength={strength}  M(theta) {tbl}")
    return spv


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=SRC_DEFAULT)
    ap.add_argument("--mode", choices=("fresnel", "null", "flat"), default="fresnel")
    ap.add_argument("--fresnel", dest="kind", choices=("exact", "schlick"),
                    default="exact")
    ap.add_argument("--n", type=float, default=1.5, help="glass refractive index")
    ap.add_argument("--strength", type=float, default=1.0,
                    help="lerp(1, F, strength); 0 = byte-inert control")
    ap.add_argument("--flat-value", type=float, default=8.0,
                    help="constant radiance for --mode flat")
    ap.add_argument("--points", type=int, default=6000)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    if a.n <= 1.0:
        sys.exit("patch_glass_fresnel: --n must exceed 1.0 (the no-TIR argument)")
    build(a.src, a.mode, a.kind, a.n, a.strength, a.flat_value, a.out, a.points)
