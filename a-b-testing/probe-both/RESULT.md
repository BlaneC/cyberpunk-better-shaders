# probe-both (G-U4 + A2/A3) -- 2026-08-31T00:17:27-05:00 -- PAINTS. Field is real but COARSE.

Serve verified: 76 dxil (the 77th, ab0bc2fe, correctly absent -- int buffer,
no radiance write) + 12 rgs_reference_main, 0 ser_reject,
skin_sha=69af98424a5e9c18 == 40 sec 7's recorded hash for probe-both.
Settings PINNED and proven (last written 778s before the first capture).
Capture: S1.png (= Launch3-test.png as shot). Scene: desert, 4 characters.

## Falsifier check (40 sec 0) -- does NOT fire

Frame is neither vanilla nor one uniform colour. The sub-enum read works in
compute, `& 31` is not folded away, the paint mechanism is live.
Per 40 sec 10 `sub`: this is the "distinct hues correlated with material
regions" branch => **G-U4 opens**, with the coarseness caveat below.

## Measured (dominant-channel clustering, head bboxes, near-black dropped)

    region             red-dom   green-dom  neutral
    L-NPC head          71.4%      9.3%*      0.8%
    R-man head          70.6%      1.2%      11.7%
    masked NPC head     46.5%      6.5%*     18.1%
    Johnny head         20.5%     23.2%      36.1%
    (* background vegetation inside the bbox: ratio matches the world sample)

    sample                 RGB                  ratio R:G:B
    L-NPC hair        [ 58.2  28.6   1.5]   0.659 0.323 0.017   <- B crushed; palette 0/9 = 0.694 0.278 0.028
    L-NPC jacket      [176.9  56.8  27.7]   0.677 0.217 0.106
    L-NPC skin        [186.8  97.7  72.6]   0.523 0.274 0.203
    R-man skin        [ 74.2  50.6  26.7]   0.490 0.334 0.176
    R-man cheek plate [185.5  96.5  64.4]   0.536 0.279 0.186   <- CHROME, == his skin
    Johnny tank       [114.1 176.2 135.9]   0.268 0.413 0.319   <- green-dominant
    vegetation        [ 59.0 122.1  88.8]   0.219 0.452 0.329

## Findings

1. **Chrome/cyberware has NO distinct sub-enum.** The R-man's cheek plate reads
   0.536/0.279/0.186 against his own skin at 0.500/0.305/0.194 -- the same hue
   family, within albedo noise. User's independent eyeball: "I dont see normal
   cyberware get any different colour on bodies". **A8's gate (51 sec 5 step 2)
   FAILS.** Thin-film iridescence cannot be subtype-gated. The stated fallback
   is ObjectID-hashed film thickness, which 43 already calls noise-per-object.
   Recommend A8 is dropped, not rebuilt.
2. **Skin does not split.** All four characters' skin lands in one red/orange
   family; skin, fabric and hair on ordinary NPCs share it. 40 sec 10 `c1sub`:
   one colour answers question (c) *no* -- class 1 has no usable sub-structure,
   so no face-vs-body-vs-cyberware-skin BRDF specialisation on this route.
   This closes that line WITHOUT spending the c1sub launch.
3. **Hair carries at least two distinct subtypes.** Every ordinary NPC's hair is
   red-dominant (L-NPC 0.659/0.323/0.017); Johnny's is green-dominant and his
   head is 36% neutral / 23% green vs ~71% red for the others. This CORROBORATES
   54's calibration anchor that the hair *family* holds multiple subtypes.
   Note Johnny's pale face is NOT independent evidence -- he is the brightest-lit
   subject and entry 0 (3.20,1.28,0.13) blown out through AgX desaturates toward
   cream. His HAIR is the load-bearing observation: dark albedo x entry 0 would
   be dark orange, not green.
4. Second 54 anchor (eye subtype 25 = bright cyan) is **untestable in this
   frame**: eyes read orange/amber, sclera matches surrounding skin. Consistent
   with 46, where the class probe reached eyes on only ~30 sun-clipped catchlight
   pixels -- eyes barely register in these 76 modules. Inconclusive, NOT a
   contradiction.

## Weaknesses -- read before quoting any sub-enum INDEX from this

* The paint is a **multiplier on radiance**, not a replacement, so observed hue
  = albedo x palette x lighting, then AgX. No absolute index is recoverable.
* The palette is **hue-degenerate in pairs**: 0/9 normalise to the same ratio
  (0.694,0.278,0.028) and differ only in brightness (3.20 vs 0.45), as do 10/31.
  Tonemapping destroys the brightness discriminator.
* The scene is a **desert** -- naturally orange. "Red-dominant" is therefore weak
  evidence on terrain/hills specifically; it is strong on hair (B at 1.7%) and
  fabric, which cannot be that saturated naturally.
* A rigorous decode needs a **vanilla control at the same camera** to divide out
  albedo. None was shot. Findings 1-3 are ratio COMPARISONS within the frame
  (chrome vs adjacent skin, hair vs hair) and survive this; index claims do not.
* **The A2/A3 sheen readout is confounded by the merge.** `both` paints and
  sheens the same modules, and the paint dominates the frame, so no grazing-rim
  judgement is possible. 38 sec 7's "one-launch merge" saved a launch and cost
  the sheen answer. If A2/A3 matters, `probe-sheen` alone is the clean read --
  and 40 sec 10 rates a sheen-null as "the strongest single result available
  from this launch", so it is worth its own launch.
