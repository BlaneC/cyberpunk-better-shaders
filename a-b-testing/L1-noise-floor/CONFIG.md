# L1 — noise floor: exact E1 relaunch (2026-08-30 14:45:50 launch)

`46` §9.4 L1. **Zero config delta vs the 13:18:10 E1 launch** — the A in an
A-B-A whose B was E2a/E2b. Its only purpose is to measure what two identical
launches disagree about.

Config served (journal line 2026-08-30T14:45:50-05:00):

    tier=1 kernel=detail skin=on shadowcull=on shadowset=full-shadow
    skinspec=off ptreg=on ptclamp=on ptbounce=on ptrefl=on ptmsggx=on ser=off
    ptq=rcbm  skin_sha=0d0f3ee45ea0d538  cache=cleared  payload=225acb871d94a4b8

`skin_sha` and `payload` are byte-identical to both E1 launches (11:45, 13:18).

| check | value |
|---|---|
| unique `.dxil` compute-resolver HITs | 77 / 77 |
| unique `rgs_reference_main` HITs | 12 |
| `rgs_shadow_main` / reflection HITs | 10 / 3 |
| `ser_reject` | 0 |
| SER device event | `enabled`, `reason=already_enabled_feature_on` |

Scenes — same save, same camera, shot S1→S2→S3:

| file | scene | alignment vs E1 |
|---|---|---|
| `S1.png` | S1 direct sun | dy=0 dx=0 (SSD 16.88) |
| `S2.png` | S2 bounce-lit interior | dy=0 dx=0 (SSD 6.70) |
| `S3.png` | S3 dim grazing | dy=0 dx=−1 (SSD 9.98) |

**Result: `46` §11.** S1 and S3 have a floor larger than every effect ever
measured in them; S2's floor is ~0.4%. The floor is denoiser-resolved
pore detail, not scene reproduction error — the diff heatmaps are dense
speckle over the whole face with no shadow-edge or geometry structure.
