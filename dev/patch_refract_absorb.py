#!/usr/bin/env python3
"""Beer-Lambert coloured transmission for the Phase 0.5 refraction rung
(handoff/86, building on 20 par5b / 76).

Splices  T = exp(-sigma_rgb * d)  onto the traced radiance of
ee6d252e090adc74.rgs_reflection_transparent_main, where d is the REFRACTED
ray's own hit distance.  Authored as text on the COMMITTED eta15 spvasm
(swaps.refract.eta15/), reassembled with spirv-as -- the repo's raygen pattern.

WHY THIS SITE, AND ONLY THIS SITE
---------------------------------
%267 = OpLoad %float %250   (payload member 3) is the hit distance of the ray
that was actually traced; Phase 0.5 rewrote the trace's direction operand
(%266 <- %2913-2915), so in the eta15 build it is the REFRACTED segment length.
It is proven to be a distance by its own vanilla uses: hit-position rebuild
%394-396 = %267*dir (+origin), the 0..1 fade %403 = t*0.001, the sqrt(t) normal
offset %414-417, the miss sentinel %267 == 10000 (%268), and the re-store into
payload %56 member 3 at %453.

The radiance triple exists as ONE named value in exactly one place: the phis
%273/%275/%277 at the top of block %2827, which merges the env-miss arm (%2826)
with the hit arm after aerial-perspective fog (%2825).  %267 is defined in
%2769, which dominates %2827.  It does NOT dominate %2830 -- the block holding
the *1/64 encode and the +-65504 fp16 clamp -- so doc 20's "splice before the
clamp" site is unreachable for anything that consumes t.  %2827 is upstream of
both anyway.

MISS HANDLING (mandatory, handoff/86 par4)
------------------------------------------
On a miss the payload carries the 10000 sentinel, not a length.  Two guards,
belt and braces:
  d      = OpSelect(miss, 0, NMin(t, dmax))     -- keeps every intermediate
                                                   finite on the miss path
  out    = OpSelect(miss, original, absorbed)   -- BIT-EXACT identity, and it
                                                   does not depend on Exp()'s
                                                   ULP behaviour at exp(-0)
The second select is what the identity claim rests on; the first only keeps
the dead arm well-behaved.

SIGMA (handoff/86 par2) is a GLOBAL constant, not per-material: the module
makes exactly three G-buffer reads -- depth (registers[1]+1 .x), normal
(registers[5] .xyz) and the transparent gate (registers[2]+14 .x) -- and no
material fetch of any kind in 3084 lines, so there is no per-pixel glass
albedo to derive sigma from.  The hue is real soda-lime float glass; only the
magnitude is an authoring choice.  See SIGMA_REF below.
"""
import argparse, math, pathlib, random, re, struct, subprocess, sys

SRC_DEFAULT = "swaps.refract.eta15/ee6d252e090adc74.rgs_reflection_transparent_main.spvasm"
MODULE = "ee6d252e090adc74.rgs_reflection_transparent_main"

# --- the physics ----------------------------------------------------------
# Standard soda-lime float glass ("clear float"), the green-cyan edge tint.
# Anchored on the published 6 mm figure: visible transmittance ~0.89 including
# both Fresnel interfaces (~0.918), so INTERNAL transmittance over 6 mm ~0.970.
# Split across RGB by the two iron bands that make the edge green: Fe2+ absorbs
# in the red (its 1050 nm band tails into the visible), Fe3+ in the blue/violet,
# green passes -- hence sigma_R > sigma_B > sigma_G.
#   sigma_ref = (9.80, 3.63, 7.31) 1/m
#   attenuation length 1/sigma = (102, 275, 137) mm
#   internal T(6 mm) = (0.9428, 0.9785, 0.9571), Rec.709 luma 0.9693
# Shipped rungs keep this HUE RATIO exactly (R:G:B = 2.700 : 1.000 : 2.014) and
# rescale the magnitude, because the mod's d is the distance BEHIND the
# interface, not the thickness of a pane: at true float-glass magnitude the
# medium saturates in ~0.3 m and every window would read black.  The rescale is
# quoted as "mm of real float glass absorbed per metre of traced path".
SIGMA_REF = (9.80, 3.63, 7.31)          # 1/m, soda-lime float glass
REC709 = (0.2126, 0.7152, 0.0722)
EPS_L = 1e-9                             # luma denominator floor
EXPECT_REWRITES = 6                      # %273 x2, %275 x2, %277 x2 (4 lines)

def die(msg):
    sys.exit(f"patch_refract_absorb: FATAL: {msg}")

def f32(x):
    return struct.unpack("f", struct.pack("f", x))[0]

# --- anchors: exact instruction shapes, not line numbers (die-on-guess) ----
ANCHORS = {
    "phi_r": (r"^%273 = OpPhi %float %336 %2826 %562 %2825$",  "radiance.r at block 2827"),
    "phi_g": (r"^%275 = OpPhi %float %337 %2826 %563 %2825$",  "radiance.g at block 2827"),
    "phi_b": (r"^%277 = OpPhi %float %338 %2826 %564 %2825$",  "radiance.b at block 2827"),
    "t":     (r"^%267 = OpLoad %float %250$",                  "hit distance (payload member 3)"),
    "miss":  (r"^%268 = OpFOrdEqual %bool %267 %float_10000$", "miss sentinel test"),
}
# The negative control.  Absorption is only meaningful on a REFRACTED segment,
# so the patcher refuses any module that does not carry Phase 0.5's marker.
# On plain ptrefl / swaps.refract.off this finds 0 and dies -- by design.
PHASE05_MARKER = r"^%float_refr_eta = OpConstant %float "
CONST_ANCHOR = "%float_1 = OpConstant %float 1"
NEEDED_CONSTS = ["%float_0 ", "%float_n0 "]     # reused, must already exist
ID_BASE = 3000

def emit(mode, sigma, dmax, smax):
    """Return (const_lines, body_lines, final_ids). Empty when sigma is zero."""
    if max(sigma) == 0.0:
        return [], [], None                      # knob-0 => byte-inert
    C = lambda n, v: f"    %float_absorb_{n} = OpConstant %float {v!r}"
    consts = [C("sr", sigma[0]), C("sg", sigma[1]), C("sb", sigma[2]),
              C("dmax", dmax)]
    i = ID_BASE
    B = []
    def n():
        nonlocal i
        i += 1
        return i - 1
    d_clamped, d, tr, tg, tb, ar, ag, ab = (n() for _ in range(8))
    B += [f"%{d_clamped} = OpExtInst %float %177 NMin %267 %float_absorb_dmax",
          f"%{d} = OpSelect %float %268 %float_0 %{d_clamped}"]
    for tid, s in ((tr, "sr"), (tg, "sg"), (tb, "sb")):
        m, neg = n(), n()
        B += [f"%{m} = OpFMul %float %float_absorb_{s} %{d}",
              f"%{neg} = OpFSub %float %float_n0 %{m}",
              f"%{tid} = OpExtInst %float %177 Exp %{neg}"]
    for aid, cid, tid in ((ar, 273, tr), (ag, 275, tg), (ab, 277, tb)):
        B.append(f"%{aid} = OpFMul %float %{cid} %{tid}")
    out = (ar, ag, ab)
    if mode == "luma":
        consts += [C("wr", REC709[0]), C("wg", REC709[1]), C("wb", REC709[2]),
                   C("eps", EPS_L), C("smax", smax)]
        lum = []
        for src in ((273, 275, 277), (ar, ag, ab)):
            p = [n() for _ in range(3)]
            s1, s2 = n(), n()
            for pid, cid, w in zip(p, src, ("wr", "wg", "wb")):
                B.append(f"%{pid} = OpFMul %float %{cid} %float_absorb_{w}")
            B += [f"%{s1} = OpFAdd %float %{p[0]} %{p[1]}",
                  f"%{s2} = OpFAdd %float %{s1} %{p[2]}"]
            lum.append(s2)
        den, raw, sc = n(), n(), n()
        B += [f"%{den} = OpExtInst %float %177 NMax %{lum[1]} %float_absorb_eps",
              f"%{raw} = OpFDiv %float %{lum[0]} %{den}",
              f"%{sc} = OpExtInst %float %177 NClamp %{raw} %float_0 %float_absorb_smax"]
        held = [n() for _ in range(3)]
        for hid, aid in zip(held, (ar, ag, ab)):
            B.append(f"%{hid} = OpFMul %float %{aid} %{sc}")
        out = tuple(held)
    finals = [n() for _ in range(3)]
    for fid, cid, oid in zip(finals, (273, 275, 277), out):
        B.append(f"%{fid} = OpSelect %float %268 %{cid} %{oid}")
    return consts, B, tuple(finals)

# --- interpreter over the EMITTED text (the typo catcher) -----------------
def run_block(body, consts_env, c, t, miss):
    env = {273: c[0], 275: c[1], 277: c[2], 267: t}
    bools = {268: miss}
    def val(tok):
        tok = tok[1:]
        if tok.isdigit():
            return env[int(tok)]
        return consts_env[tok]
    for b in body:
        m = re.match(r"%(\d+) = Op(\w+) %float (.+)$", b)
        if not m:
            die(f"self-check cannot parse: {b}")
        rid, op, rest = int(m.group(1)), m.group(2), m.group(3).split()
        if op == "FMul":   env[rid] = f32(val(rest[0]) * val(rest[1]))
        elif op == "FAdd": env[rid] = f32(val(rest[0]) + val(rest[1]))
        elif op == "FSub": env[rid] = f32(val(rest[0]) - val(rest[1]))
        elif op == "FDiv": env[rid] = f32(val(rest[0]) / val(rest[1]))
        elif op == "Select":
            cond = bools[int(rest[0][1:])]
            env[rid] = val(rest[1]) if cond else val(rest[2])
        elif op == "ExtInst":
            assert rest[0] == "%177", rest
            fn = rest[1]
            if fn == "Exp":     env[rid] = f32(math.exp(val(rest[2])))
            elif fn == "NMin":  env[rid] = f32(min(val(rest[2]), val(rest[3])))
            elif fn == "NMax":  env[rid] = f32(max(val(rest[2]), val(rest[3])))
            elif fn == "NClamp":
                env[rid] = f32(min(max(val(rest[2]), val(rest[3])), val(rest[4])))
            else: die(f"self-check cannot eval extinst {fn}")
        else: die(f"self-check cannot eval {b}")
    return env

def selfcheck(body, consts, finals, mode, sigma, dmax, smax, npts):
    cenv = {}
    for ln in consts:
        m = re.match(r"\s*%(\S+) = OpConstant %float (\S+)$", ln)
        cenv[m.group(1)] = f32(float(m.group(2)))
    cenv["float_0"] = 0.0
    cenv["float_n0"] = -0.0
    cenv["float_1"] = 1.0
    rng = random.Random(86)
    worst_val = worst_luma = 0.0
    clamp_bound = 0
    n_miss = n_nonneg = 0
    for i in range(npts):
        miss = (i % 4 == 0)
        t = 10000.0 if miss else rng.choice(
            [rng.uniform(0, 1), rng.uniform(0, 60), rng.uniform(0, 12000)])
        neg = (i % 37 == 0)                      # a few pathological inputs
        def chan():
            if i % 11 == 0: return 0.0
            v = f32(10 ** rng.uniform(-3, 3))
            return f32(-v) if neg else v
        c = (chan(), chan(), chan())
        env = run_block(body, cenv, c, t, miss)
        got = tuple(env[f] for f in finals)
        # --- closed form ---
        if miss:
            ref = c
        else:
            d = f32(min(t, dmax))
            T = tuple(f32(math.exp(f32(-f32(s * d)))) for s in sigma)
            a = tuple(f32(x * y) for x, y in zip(c, T))
            if mode == "luma":
                L0 = f32(f32(f32(c[0]*REC709[0]) + f32(c[1]*REC709[1])) + f32(c[2]*REC709[2]))
                L1 = f32(f32(f32(a[0]*REC709[0]) + f32(a[1]*REC709[1])) + f32(a[2]*REC709[2]))
                s_raw = f32(L0 / f32(max(L1, EPS_L)))
                s = f32(min(max(s_raw, 0.0), smax))
                if s != s_raw and not neg: clamp_bound += 1
                a = tuple(f32(x * s) for x in a)
            ref = a
        if miss:
            n_miss += 1
            if got != c:                          # BIT-EXACT, not a tolerance
                die(f"miss is not exact identity: {got} vs {c}")
        for g, r in zip(got, ref):
            e = abs(g - r) / max(abs(r), 1e-6)
            worst_val = max(worst_val, e)
            if e > 4e-6:
                die(f"closed-form mismatch {e:.3e}: got {got} ref {ref} "
                    f"(c={c} t={t} miss={miss})")
        if mode == "luma" and not miss and not neg:
            n_nonneg += 1
            L_in = sum(x*w for x, w in zip(c, REC709))
            L_out = sum(x*w for x, w in zip(got, REC709))
            if L_in > 1e-4:
                worst_luma = max(worst_luma, abs(L_out - L_in) / L_in)
    if mode == "luma":
        if clamp_bound:
            die(f"s_max clamp bound on {clamp_bound} samples -- it must be a "
                f"no-op for representable inputs; recompute smax")
        if worst_luma >= 1e-5:
            die(f"luma NOT held: worst relative error {worst_luma:.3e} >= 1e-5")
    print(f"  self-check: {npts} points OK -- closed form max rel err "
          f"{worst_val:.2e}, {n_miss} miss samples bit-exact identity"
          + (f", luma held over {n_nonneg} samples (max {worst_luma:.2e})"
             if mode == "luma" else ""))

def build(src_path, mode, mm_per_m, dmax, out_dir, npts):
    lines = pathlib.Path(src_path).read_text().splitlines()
    stripped = [ln.strip() for ln in lines]

    # NEGATIVE CONTROL: refuse anything that is not a Phase 0.5 refract rung.
    n_marker = sum(1 for s in stripped if re.match(PHASE05_MARKER, s))
    if n_marker != 1:
        die(f"0 sites: Phase 0.5 marker '%float_refr_eta' found {n_marker}x in "
            f"{src_path} -- absorption is only defined on a refracted segment "
            f"(handoff/86 par5). Refusing.")

    found = {}
    for i, s in enumerate(stripped):
        for k, (rx, _) in ANCHORS.items():
            if re.match(rx, s):
                if k in found: die(f"anchor {k} matched twice")
                found[k] = i
    for k, (rx, what) in ANCHORS.items():
        if k not in found: die(f"anchor not found: {k} ({what}) ~ {rx}")
    for c in NEEDED_CONSTS:
        if not any(s.startswith(c) for s in stripped): die(f"missing constant {c}")
    const_at = [i for i, s in enumerate(stripped) if s == CONST_ANCHOR]
    if len(const_at) != 1: die(f"constant anchor x{len(const_at)}")
    # the three phis must be adjacent and last in their block (OpPhi at top)
    if not (found["phi_r"] + 1 == found["phi_g"] == found["phi_b"] - 1):
        die("radiance phis are not adjacent -- module changed, re-audit")
    if stripped[found["phi_b"] + 1].startswith("%") and \
       "OpPhi" in stripped[found["phi_b"] + 1]:
        die("a fourth OpPhi follows the radiance triple -- re-audit block 2827")

    sigma = tuple(f32(s * mm_per_m / 1000.0) for s in SIGMA_REF)
    # exact bound on L0/L1 for non-negative radiance: 1/min_ch(T(dmax))
    smax = f32(math.exp(max(sigma) * dmax) * 1.0000001) if max(sigma) else 0.0
    consts, body, finals = emit(mode, sigma, dmax, smax)

    if body:
        maxid = max(int(m) for m in re.findall(r"%(\d+)\b", "\n".join(lines)))
        if maxid >= ID_BASE:
            die(f"id space collision: module already uses %{maxid} >= {ID_BASE}")
        for tok in [c.split()[0] for c in consts]:
            if any(re.search(re.escape(tok) + r"\b", ln) for ln in lines):
                die(f"id {tok} already in use")
        selfcheck(body, consts, finals, mode, sigma, dmax, smax, npts)
    else:
        print("  sigma == 0: emitting nothing (byte-inert rebuild)")

    # --- splice ------------------------------------------------------------
    remap = ({273: finals[0], 275: finals[1], 277: finals[2]} if body else {})
    rx_use = re.compile(r"%(273|275|277)\b")
    def_lines = {found[k] for k in ("phi_r", "phi_g", "phi_b")}
    out, rewrites, rewritten_lines = [], 0, 0
    for i, ln in enumerate(lines):
        if body and i not in def_lines and rx_use.search(ln):
            new, k = rx_use.subn(lambda m: f"%{remap[int(m.group(1))]}", ln)
            out.append(new); rewrites += k; rewritten_lines += 1
        else:
            out.append(ln)
        if body and stripped[i] == CONST_ANCHOR:
            out.extend(consts)
        if body and i == found["phi_b"]:
            out.extend("        " + b for b in body)
    if body and rewrites != EXPECT_REWRITES:
        die(f"rewrote {rewrites} uses on {rewritten_lines} lines, expected "
            f"{EXPECT_REWRITES} -- module changed, re-audit")

    out_dir = pathlib.Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    asm, spv = out_dir / f"{MODULE}.spvasm", out_dir / f"{MODULE}.spv"
    asm.write_text("\n".join(out) + "\n")
    r = subprocess.run(["spirv-as", "--target-env", "spv1.4", str(asm), "-o", str(spv)],
                       capture_output=True, text=True)
    if r.returncode: die(f"spirv-as: {r.stderr}")
    r = subprocess.run(["spirv-val", str(spv)], capture_output=True, text=True)
    if r.returncode: die(f"spirv-val: {r.stderr}")
    if b"ee6d252e090adc74" not in spv.read_bytes(): die("dxil identity OpString lost")
    print(f"  {spv} ({spv.stat().st_size} B): spirv-as + spirv-val clean, "
          f"{len(consts)} consts + {len(body)} instructions, "
          f"{rewrites} uses rewritten on {rewritten_lines} lines")
    if body:
        print(f"  sigma_rgb = ({sigma[0]:.6f}, {sigma[1]:.6f}, {sigma[2]:.6f}) 1/m "
              f"= {mm_per_m} mm float glass per metre; 1/sigma = "
              f"({1/sigma[0]:.1f}, {1/sigma[1]:.1f}, {1/sigma[2]:.1f}) m; dmax={dmax} m")
    return spv

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=SRC_DEFAULT)
    ap.add_argument("--mode", choices=("physical", "luma"), required=True)
    ap.add_argument("--mm-per-m", type=float, required=True,
                    help="mm of real soda-lime float glass absorbed per metre "
                         "of traced path (0 = byte-inert control)")
    ap.add_argument("--dmax", type=float, default=40.0, help="medium ends at, metres")
    ap.add_argument("--points", type=int, default=6000)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    build(a.src, a.mode, a.mm_per_m, a.dmax, a.out, a.points)
