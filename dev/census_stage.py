#!/usr/bin/env python3
"""Census the dumped SPIR-V modules by execution model (shader stage).

    python3 dev/census_stage.py [dump_dir] [--list Fragment]

Written for 79 section 6: G-U2 (the fragment / G-buffer-fill stage) is gated on
"has a fragment splice ever executed here", and the first half of that answer
is just "how many fragment modules does the layer even see". Parses the
OpEntryPoint word directly -- no spirv-dis, so it runs over all 3273 modules
in about a second.

2026-08-31 result (~/callisto_dump, 3273 files):
    1290 Fragment / 1179 Vertex / 675 GLCompute / 57 MissKHR /
      43 RayGenerationKHR / 24 ClosestHitKHR / 5 AnyHitKHR
Paired with `ls swaps.*/ | grep -ciE '\\.ps_|frag|pixel'` == 0 -- fragment
modules are dumped in bulk and have never once been swapped.
"""
import collections, glob, os, struct, sys

MAGIC = 0x07230203
MODELS = {
    0: "Vertex", 1: "TessControl", 2: "TessEvaluation", 3: "Geometry",
    4: "Fragment", 5: "GLCompute", 6: "Kernel",
    5267: "TaskNV", 5268: "MeshNV",
    5313: "RayGenerationKHR", 5314: "IntersectionKHR", 5315: "AnyHitKHR",
    5316: "ClosestHitKHR", 5317: "MissKHR", 5318: "CallableKHR",
    5364: "TaskEXT", 5365: "MeshEXT",
}


def entry_models(path):
    """Yield the execution model of every OpEntryPoint in one module."""
    with open(path, "rb") as f:
        blob = f.read()
    if len(blob) < 20:
        return
    if struct.unpack("<I", blob[:4])[0] == MAGIC:
        end = "<"
    elif struct.unpack(">I", blob[:4])[0] == MAGIC:
        end = ">"
    else:
        return                                    # not SPIR-V
    n = len(blob) // 4
    words = struct.unpack(end + str(n) + "I", blob[:n * 4])
    i = 5                                         # skip the 5-word header
    while i < n:
        op, length = words[i] & 0xFFFF, words[i] >> 16
        if length == 0 or i + length > n:
            return                                # truncated / malformed
        if op == 15:                              # OpEntryPoint
            yield words[i + 1]
        i += length


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dump = args[0] if args else os.path.expanduser("~/callisto_dump")
    want = None
    if "--list" in sys.argv:
        want = sys.argv[sys.argv.index("--list") + 1]

    counts, named, files = collections.Counter(), [], sorted(glob.glob(os.path.join(dump, "*.spv")))
    if not files:
        sys.exit(f"no .spv under {dump}")
    for path in files:
        for model in entry_models(path):
            name = MODELS.get(model, f"model_{model}")
            counts[name] += 1
            if name == want:
                named.append(os.path.basename(path))

    if want:
        print("\n".join(named))
        return
    for name, count in counts.most_common():
        print(f"{count:6d}  {name}")
    print(f"{len(files):6d}  files scanned")


if __name__ == "__main__":
    main()
