# E0 — bit-exact vanilla baseline (2026-08-30 12:38:21 launch)

Journal line:

    tier=off skin=off ptq=off ptrefl=on ser=off shadowset=full-shadow
    skinspec=off cache=cleared payload=d2dfb3f53119172b

Layer verification for that pid — this is what makes it a true reference:

| check | value |
|---|---|
| modules compiled | 18929 |
| `"swap"` values | 18929 x `"none"` — zero HITs |
| overlays | ser / skin / shadowcull / ptq / ptrefl all `enabled:0` |
| `ser_reject` | 0 |

## Scenes

| file | scene | notes |
|---|---|---|
| `20260830_E0_vanilla_S1.png` | **S1** direct sun on a face | badlands exterior. NOTE: character switched vs the 11:45 E1 set, so hair does not fall on the cheeks. E1's S1 is therefore NOT comparable and must be re-shot with this character. |
| `20260830_E0_vanilla_S3.png` | **S3** grazing / dim | dim exterior at dusk, dark background. Per the user: photo-mode light sources do not load consistently, so a lit-room S3 was not workable; a very dim exterior is the repeatable option. |
| `20260830_E0_vanilla_S2.png` | **S2** bounce-lit face | captured in a second E0 launch, 2026-08-30T13:05:36 (`cache=kept`, identical payload `d2dfb3f53119172b`; 6852 modules, all `"swap":"none"`). Aligns 0,0 with the E1 S2. |
