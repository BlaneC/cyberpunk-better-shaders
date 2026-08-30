#!/usr/bin/env bash
# Regenerate every number quoted in handoff/46-AB-LEDGER.md.
# Run from the repo root:  bash a-b-testing/reproduce.sh
set -u
cd "$(dirname "$0")/.."

E0=a-b-testing/E0-baseline
E1=a-b-testing/E1-shipping-default
E2A=a-b-testing/E2a-rough-1.3
E2B=a-b-testing/E2b-gloss-0.7
M=a-b-testing/masks

# Per-scene crop windows. Fixed for the whole run: the camera reproduces
# exactly across launches (every pair phase-correlates to 0,0), so the same
# crop and the same mask apply to every rung.
C1=1005,385,1380,850
C2=980,390,1330,830
C3=1020,350,1460,900

echo "############ 0. launch audit (layer verification per launch) ############"
./dev/ab_launch_audit.py 6

echo "############ 1. E0 vanilla -> E1 shipping default ############"
# S1 is the only scene with an E0 capture of the CURRENT character.
./dev/ab_compare.py $E0/20260830_E0_vanilla_S1.png $E1/S1.png \
    --crop $C1 --mask $M/S1.npy --tone --label "S1 direct sun: E0 -> E1"
# The S2 pair below is the OLD character (both frames), kept because it is the
# evidence for the 42 finding. Do not compare it against any post-13:18 capture.
./dev/ab_compare.py $E0/20260830_E0_vanilla_S2.png $E1/20260830_E1_default_S2.png \
    --crop 1000,380,1400,880 \
    --seeds "70,175;265,88;262,240;300,168" \
    --tone --label "S2 bounce-lit: E0 -> E1  (OLD character pair)"

echo "############ 2. E1 -> E2a rough-1.3 and E2b gloss-0.7 ############"
for s in 1 2 3; do
  eval C=\$C$s
  ./dev/ab_compare.py $E1/S$s.png $E2A/S$s.png --crop $C --mask $M/S$s.npy \
      --tone --label "S$s : E1 -> E2a rough-1.3"
  ./dev/ab_compare.py $E1/S$s.png $E2B/S$s.png --crop $C --mask $M/S$s.npy \
      --tone --label "S$s : E1 -> E2b gloss-0.7"
done

echo "############ 3. texture energy (the metric that matched perception) ############"
./dev/ab_texture.py --crop $C1 --mask $M/S1.npy --label "S1 direct sun" \
  "E0 vanilla=$E0/20260830_E0_vanilla_S1.png" \
  "E1 skinspec=off=$E1/S1.png" \
  "E2a rough-1.3=$E2A/S1.png" \
  "E2b gloss-0.7=$E2B/S1.png"
./dev/ab_texture.py --crop $C2 --mask $M/S2.npy --label "S2 bounce-lit" \
  "E1 skinspec=off=$E1/S2.png" "E2a rough-1.3=$E2A/S2.png" "E2b gloss-0.7=$E2B/S2.png"
./dev/ab_texture.py --crop $C3 --mask $M/S3.npy --label "S3 dim grazing" \
  "E1 skinspec=off=$E1/S3.png" "E2a rough-1.3=$E2A/S3.png" "E2b gloss-0.7=$E2B/S3.png"

echo "############ 4. bias check on the --tone bins (see handoff/46 section 4.3) ############"
# ab_compare.py --tone is BIASED by construction. This does not fix it -- it
# shows how much of each --tone row survives an unbiased binning.
./dev/ab_bias_check.py $E0/20260830_E0_vanilla_S1.png $E1/S1.png --crop $C1 --mask $M/S1.npy
./dev/ab_bias_check.py $E1/S1.png $E2A/S1.png --crop $C1 --mask $M/S1.npy
./dev/ab_bias_check.py $E1/S1.png $E2B/S1.png --crop $C1 --mask $M/S1.npy

echo "############ 5. L1 noise floor -- the A-B-A null (handoff/46 section 11) ############"
L1=a-b-testing/L1-noise-floor
# 5a. The null pair itself: same config, same save, same camera, two launches.
for s in 1 2 3; do
  eval C=\$C$s
  ./dev/ab_compare.py $E1/S$s.png $L1/S$s.png --crop $C --mask $M/S$s.npy \
      --tone --label "FLOOR S$s : E1 -> L1 (identical config)"
done
# 5b. The floor on the texture metric, printed beside the rungs it invalidates.
./dev/ab_texture.py --crop $C1 --mask $M/S1.npy --label "S1 -- FLOOR beside rungs" \
  "E0 vanilla=$E0/20260830_E0_vanilla_S1.png" "E1 skinspec=off=$E1/S1.png" \
  "L1 skinspec=off REPEAT=$L1/S1.png" \
  "E2a rough-1.3=$E2A/S1.png" "E2b gloss-0.7=$E2B/S1.png"
./dev/ab_texture.py --crop $C2 --mask $M/S2.npy --label "S2 -- FLOOR beside rungs" \
  "E1 skinspec=off=$E1/S2.png" "L1 skinspec=off REPEAT=$L1/S2.png" \
  "E2a rough-1.3=$E2A/S2.png" "E2b gloss-0.7=$E2B/S2.png"
./dev/ab_texture.py --crop $C3 --mask $M/S3.npy --label "S3 -- FLOOR beside rungs" \
  "E1 skinspec=off=$E1/S3.png" "L1 skinspec=off REPEAT=$L1/S3.png" \
  "E2a rough-1.3=$E2A/S3.png" "E2b gloss-0.7=$E2B/S3.png"
# 5c. Second, independent sample of E0 -> E1 (L1 is a valid E1 sample).
./dev/ab_compare.py $E0/20260830_E0_vanilla_S1.png $L1/S1.png \
    --crop $C1 --mask $M/S1.npy --tone --label "S1: E0 -> L1 (replicate of E0 -> E1)"
# 5d. The floor is a near-uniform relative offset -- so it CANCELS rung-vs-rung.
./dev/ab_bias_check.py $E1/S1.png $L1/S1.png --crop $C1 --mask $M/S1.npy
./dev/ab_compare.py $E2A/S1.png $E2B/S1.png --crop $C1 --mask $M/S1.npy \
    --tone --label "S1 rung-vs-rung: E2a rough-1.3 -> E2b gloss-0.7"

echo "############ 6. the regime break and the TRUE floor (handoff/46 section 13) ############"
L4A=a-b-testing/L4a-rr-off
python3 -c "
import numpy as np
for s in ('S1','S3'):
    np.save('/tmp/inv_%s.npy'%s, ~np.load('a-b-testing/masks/%s.npy'%s))"
# 6a. Non-skin fine energy across every launch: the break is at ~13:30 and is
#     visible on STATIC GEOMETRY, which no skin rung can touch.
./dev/ab_texture.py --crop $C1 --mask /tmp/inv_S1.npy --label "S1 NON-SKIN across launches" \
  "E0 12:59=$E0/20260830_E0_vanilla_S1.png" "E1 13:19=$E1/S1.png" \
  "E2a 13:38=$E2A/S1.png" "E2b 13:53=$E2B/S1.png" \
  "L1 14:47=$L1/S1.png" "L4a 15:39=$L4A/S1.png"
# 6b. The true floor: two skinspec=off launches on the SAME side of the break.
for s in 1 2 3; do
  eval C=\$C$s
  ./dev/ab_compare.py $L1/S$s.png $L4A/S$s.png --crop $C --mask $M/S$s.npy \
      --tone --label "TRUE FLOOR S$s : L1 -> L4a (same config, same regime)"
done
# 6c. The rungs re-measured inside regime B, with a non-skin control.
./dev/ab_texture.py --crop $C1 --mask $M/S1.npy --label "S1 skin (regime B only)" \
  "L1 off=$L1/S1.png" "L4a off=$L4A/S1.png" "E2a rough-1.3=$E2A/S1.png" "E2b gloss-0.7=$E2B/S1.png"
./dev/ab_texture.py --crop $C1 --mask /tmp/inv_S1.npy --label "S1 non-skin (regime B only)" \
  "L1 off=$L1/S1.png" "L4a off=$L4A/S1.png" "E2a rough-1.3=$E2A/S1.png" "E2b gloss-0.7=$E2B/S1.png"

echo "############ 7. L5-L8: the elimination chain and the ptbounce result (handoff/46 sections 14-18) ############"
# Added by the 2026-08-30 late-evening peer review (47 section 11): sections
# 14-18 of the ledger -- including the ONLY replicated result of the day --
# were quoted from ad-hoc commands and not reproducible by this script.
L3D=a-b-testing/L3-ptclamp-off
L5=a-b-testing/L5-vanilla-regimeB
L6=a-b-testing/L6-ptreg-off
L7=a-b-testing/L7-vanilla-repeat
L8=a-b-testing/L8-ptbounce-off
python3 -c "
import numpy as np
for s in ('S1','S3'):
    np.save('/tmp/inv_%s.npy'%s, ~np.load('a-b-testing/masks/%s.npy'%s))"
# 7a. The headline (46 section 18.1): two vanilla samples, four mod configs in
#     one 1.4% band, and ONE switch (ptbounce) spanning the whole gap.
#     S3 non-skin same-config floor: 0.3% (L1 vs L4a).
./dev/ab_texture.py --crop $C3 --mask /tmp/inv_S3.npy --label "S3 NON-SKIN -- the elimination chain" \
  "vanilla L5=$L5/S3.png" "vanilla L7=$L7/S3.png" \
  "default L1=$L1/S3.png" "default L4a=$L4A/S3.png" \
  "clamp-off L3=$L3D/S3.png" "reg-off L6=$L6/S3.png" \
  "bounce-off L8=$L8/S3.png"
# 7b. S1 shows no separation -- the effect is dim-light only (46 section 17.1).
#     This band (6.46-6.81) is also the regime-B membership check (section 13).
./dev/ab_texture.py --crop $C1 --mask /tmp/inv_S1.npy --label "S1 NON-SKIN -- no separation; the regime-B band" \
  "vanilla L5=$L5/S1.png" "vanilla L7=$L7/S1.png" \
  "default L1=$L1/S1.png" "default L4a=$L4A/S1.png" \
  "clamp-off L3=$L3D/S1.png" "reg-off L6=$L6/S1.png" \
  "bounce-off L8=$L8/S1.png"
# 7c. The first valid mod-vs-vanilla skin measurement (46 section 14.1): the
#     mod brightens only the lit half of the face, switching on at ~106 lum,
#     independently matching L2's paint threshold (~116). NOTE: the wall-L
#     control is NOT flat in this scene (second NPC stands in it); ceiling and
#     floor-R are the valid controls here.
./dev/ab_compare.py $L5/S1.png $L1/S1.png --crop $C1 --mask $M/S1.npy \
    --tone --label "S1: L5 vanilla -> L1 mod default (the ~106-lum threshold)"
# 7d. S1 skin texture, mod vs vanilla: no skin-specific cost in direct sun
#     (46 section 14.2). S3-skin equivalents are withdrawn -- ~9% same-config
#     floor (section 16.2) -- and are deliberately not regenerated here.
./dev/ab_texture.py --crop $C1 --mask $M/S1.npy --label "S1 skin texture vs vanilla" \
  "vanilla L5=$L5/S1.png" "vanilla L7=$L7/S1.png" \
  "default L1=$L1/S1.png" "default L4a=$L4A/S1.png"
