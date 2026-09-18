# YYSLS face meshes: EXT8 skinning and vertex-buffer views

## Confirmed capture findings

Capture: `FrameAnalysis-2026-09-18-145351`, IB `874579d8`.
Draws 000022, 000041 and 000067 use the same input layout (`47e81178`).
The captured bindings are **three separate resources**, not one shared resource:

| Slot | Resource hash | Stride | Contents |
| --- | --- | ---: | --- |
| vb0 | 8043ec8b | 28 | Position, color, normal, UV |
| vb1 | 345a863c | 16 | Tangent and binormal |
| vb2 | e4503319 | 16 | Weight0, index0, weight1, index1 |

The second bone set is named `BLENDWEIGHTEXT` / `BLENDINDICESEXT` in the game.
The old extraction incorrectly described these bytes as `COLOR1` / `COLOR2`.
Among the 7008 captured vertices, **2992 use nonzero secondary weights**.
Treating these fields as colors loses their bone semantics and can change their
bytes through Blender color storage. Normalizing each four-weight set separately
is also wrong: it can produce a combined byte-weight sum of 510 instead of 255.

## Changes

- SSMT5 adds layout-selected `EXT8_` game types. They describe the second set as
  `BLENDWEIGHT` / `BLENDINDICES` with semantic index 1. Indices use UINT, not UNORM.
- The physical Blend order remains four bytes each of **weight0, index0,
  weight1, index1**. No vertex-shader or input-layout replacement is needed.
- MIMIBlender reuses the WWMI wide influence gatherer, takes the strongest eight
  influences, jointly normalizes/quantizes all eight, then writes the two sets.
- Duplicate bones across the two sets accumulate during YYSLS EXT8 import.
- Ordinary four-weight YYSLS and existing WWMI generation retain their old paths.
- SSMT5 matches actual input semantics rather than accepting equal buffer sizes.
  Per-slot source offsets/strides are respected even if two slots share a buffer.
  Interior input-layout gaps become RAWDATA fields; Blender retains those bytes.
  Independent replacement buffers are valid: shared source allocation identity
  does not have to be reproduced for ordinary IA vertex-buffer reads.

The existing no-cloth override remains restricted to VS `ab148fe238420411`.
The face shaders in this capture are different and are **not** replaced by it.

## Migration

1. Update/rebuild SSMT5 and update the **actually enabled** MIMIBlender addon.
   Updating the development checkout does not update a separate installed addon.
2. Re-extract the face. Select the newly detected type ending in `EXT8_`.
   Historical color-based types remain available only for actual color layouts
   or the historical header-less extraction fallback.
3. Re-import the corrected JSON and rebuild the face Mod from that object.
   An old object already imported with COLOR1/COLOR2 is not automatically repaired.
   Merely changing its type label cannot reliably reconstruct its missing weights.
4. Keep any edited old face as a backup; transfer desired geometry edits to the
   corrected import, or transfer the corrected weights deliberately.
5. Test facial animation, head movement, and multiple rendering passes in game.
   Check a normal four-weight outfit and the scoped cloth toggle as regressions.

No live Mod buffers, saved Blender scenes or installed addon copies were changed
by this implementation. The local real-capture test extraction is under
`D:\Dev\SSMT5\tmp\yysls_regression\874579d8` and can also be used for re-import
with the updated addon. It contains geometry buffers, not synchronized textures.

## Verification

Production Blender 5.2 import and export of the corrected extraction passed:

- 7008 native vertices; 2992 with active EXT weights.
- 7038 exported vertices after legitimate corner-attribute splitting.
- **Zero bone-weight byte error**, comparing accumulated bone contributions
  through the exporter's actual vertex/loop mapping.
- Both sets together sum to 255 for every exported face vertex.
- Synthetic tests cover top-eight truncation, weight painting, empty secondary
  sets, duplicate bones, padding, four-weight compatibility and the WWMI path.

SSMT5 tests exercise the actual extractor against the face and the older
`31e22cc3` cloth capture. The face and all three cloth submesh products retain
byte-identical native category-buffer data over their referenced vertex ranges.
Synthetic tests cover shared allocations with different binding offsets/strides,
interior element gaps, first-vertex addressing and out-of-bounds rejection.
The ten scoped-cloth generation tests pass, and the no-cloth shader still compiles
with executable DXBC and signatures identical to its verified reference.

Example Blender invocation (pass the corrected JSON after `--`):

```text
blender --background --factory-startup --python-exit-code 1 --python tools/test_yysls_blend.py -- --face-json <corrected-face.json>
python tools/test_yysls_cloth.py
```

These are extraction, Blender and shader-compilation checks. Actual game visual
and animation acceptance still requires running the regenerated Mod in game.
