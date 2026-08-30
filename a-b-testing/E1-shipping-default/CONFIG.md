# E1 — shipping default (2026-08-30 11:45:16 launch)

Captured before `45` E0 ran; originally filed as "first-test". These are E1,
not E0 — the game was still the 11:45 session when the E0 config was written
(seq continuity in `callisto_swap.jsonl`, no new line in
`~/callisto_launches.log`, `brdf_params.txt` mtime 11:49:35 > launch start).

Config served (journal line 2026-08-30T11:45:16-05:00):

    tier=1 kernel=detail skin=on shadowcull=on shadowset=full-shadow
    skinspec=off ptreg=on ptclamp=on ptbounce=on ptrefl=on ptmsggx=on ser=off
    ptq=rcbm  skin_sha=0d0f3ee45ea0d538  cache=cleared

Layer verification for that pid (all clean):

| check | value |
|---|---|
| unique `.dxil` compute-resolver HITs | 77 / 77 |
| unique `rgs_reference_main` HITs | 12 (ptq serving) |
| `rgs_shadow_main` / reflection HITs | 10 / 3 |
| `ser_reject` | 0 — first launch with none (`44` §2.1 fix confirmed) |
| SER device event | `enabled`, `reason=already_enabled_feature_on` |

Scenes (Panam, photo mode):

| file | scene | notes |
|---|---|---|
| `20260830_E1_default_S1.png` | **S1** direct sun on a face | badlands, exterior daylight, second NPC behind |
| `20260830_E1_default_S2.png` | **S2** bounce-lit face | interior, teal/green ambient, no direct light — the `42` scene |
| `20260830_E1_default_S3b.png` | *not S3* | warm interior, frontal light. S3 needs ~80 deg grazing + dark background. Reshoot. |
