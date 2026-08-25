# Evidence: rgs_reference_main permutations in the LIVE game

Source: `~/callisto_swap.jsonl`, produced by the swap layer over several launches. One row per distinct DXIL library hash.

| id (libhash.entry) | times created | SPIR-V bytes | swapped |
|---|---|---|---|
| `40c6faab52a13874.rgs_reference_main` | 6 | 329572 | **HIT** |
| `996a3b16253c3e7f.rgs_reference_main` | 6 | 293748 | none |
| `d622fb9e1dcb8cd0.rgs_reference_main` | 6 | 303048 | **HIT** |
| `1271d3815051da17.rgs_reference_main` | 3 | 293944 | none |
| `21a92f1a77eb4c22.rgs_reference_main` | 3 | 304076 | none |
| `25b54fc4a17688df.rgs_reference_main` | 3 | 293788 | none |
| `3d871a3170bc5815.rgs_reference_main` | 3 | 308284 | none |
| `4103c8860c3909e4.rgs_reference_main` | 3 | 297180 | none |
| `4270b745d11a5e8a.rgs_reference_main` | 3 | 303920 | none |
| `852b31a841b85b26.rgs_reference_main` | 3 | 298108 | none |
| `ab7f1822eeb0331b.rgs_reference_main` | 3 | 332876 | none |
| `d002cc05eb940591.rgs_reference_main` | 3 | 306512 | none |

**12 distinct permutations. Exactly 2 are patched.**

The two patched ones are the two that happened to be present in the
Nsight captures. The other 10 pass through unmodified.

Note the creation counts: three modules are created 6 times
(`996a3b16253c3e7f`, and the two we patch) while the rest are created 3
times. Whatever that grouping means, `996a3b16253c3e7f` keeps the same
company as our two and is never patched.
