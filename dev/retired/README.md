# Retired dev scripts

Kept for the record; nothing shipping calls them. Each was superseded or its
result was falsified -- the handoff doc named beside it has the evidence.
Python files here import from `dev/` and need `PYTHONPATH=dev` to run.

| script | why retired | see |
|---|---|---|
| `bisect_hunt.sh`, `bisect_null.sh`, `bisect_tint.sh`, `build_tintnet.sh` | the class hunt / tint bisect that established skin=1, hair=4, eyes=8; done | `05`, `31` |
| `hunt_hair_class.sh` | same hunt, hair side; done | `05` |
| `patch_all_perms.sh`, `patch_chs_perms.sh`, `patch_compute_perms.sh`, `patch_shadow_perms.sh` | raygen/CHS-era batch drivers; raygen BRDF patches are sampling-only and cannot change a pixel | `00` s2 |
| `validate_dual_lobe.py`, `compare_brdf_ab.py`, `HAIR_HANDOFF.md` | hair BRDF track, removed 2026-08-28 | `19`, `27` s8 |
| `find_tonemap_gens.py` | superseded by `find_lut_gens.py` (10 permutations, not 2) | `21` |
