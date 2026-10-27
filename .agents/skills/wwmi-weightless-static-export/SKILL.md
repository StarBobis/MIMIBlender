# Export a WWMI layout that has no bone indices at all

Use when a WWMI workspace imports into Blender with **zero vertex groups** and
the export then refuses the whole draw, when a user reports "导入进来没有权重，
所以导出有问题", or when adding another static (weightless) data type.

## Symptom

- Import succeeds and prints `Vertex group import complete`, but the object has
  no vertex groups. That is correct for this layout, not a failed import.
- `Generate Mod` fails per architecture:

| Architecture | Error |
| --- | --- |
| MergedComponent (WWMI default) | `MergedComponent: missing bone index export layout` |
| UniComponent | `UniComponent: object '<name>', polygon 0 spans incompatible component palettes or has no skeleton ownership; use Merged ...` |
| Merged | works (it never localizes indices) |

- The workspace `SubmeshJson` shows `VGCount: 0`, `VGOffset: 0`, no `VGMap`, and
  `CategoryBufferList` has no `Blend` entry. The data type name starts with
  `CPU_` (no GPU pre-skinning) and contains no `BI`/`BW` fragment, e.g.
  `CPU_P12_TA4_N4_T4_T1-4_T2-4_T3-4_` (real case: WWMI `14a706ae`, a
  shader-slot fetched weapon mesh, 3540 vertices / 10446 indices).

## Why it is not a missing extraction

The captured draw has no skinning input: `vb0` holds only positions (12 bytes),
`vs-t1` the tangent+normal record (8 bytes), `vs-t0` four half2 UV sets
(16 bytes), and `vb4` is a 12-byte per-draw constant. There is no
`BLENDINDICES`/`BLENDWEIGHT` stream anywhere in the frame, so the game cannot
skin this mesh per vertex and the mod must not invent weights.

Read the buffers before believing "the extractor lost the weights": half2 UVs
stay inside `[0, 1]` while uint16 bone ids would decode as denormal garbage.

## Rules the add-on now follows

- `games/wwmi/component_routing_blender.py::prepare_routing` - when the export
  layout has **no** `BLENDINDICES` element, do not raise. Return the identity
  plan: every triangle keeps the component of its `OWNER_ATTRIBUTE`, with
  `counts.unchanged = faces`, no issues, and `loop_components` filled from those
  assignments. `apply_routing` then returns `[]` (nothing to rebucket) and
  `localize_blendindices` returns `{}` (nothing to serialize) but still
  validates loop ownership.
- `model/blueprint_model.py::_unico_split_object` - when no Submesh palette of
  the DrawIB declares a bone, the node object already is its own Submesh's
  geometry: bind a **disposable copy** (same temporary-object contract as a
  real split) instead of raising. Returning `[]` would silently drop the draw.
- Weightless layouts keep working in `Merged` without changes; the fixed layout
  binding (`vb0` / `vs-t#` resource views) and the missing `Blend` resource are
  the exporter's existing shader-slot support, not part of this rule.

## Verify

```powershell
cd D:\Dev\MIMIBlender
$env:MIMI_AUDIT_WORKSPACE='JiYanQiang'
blender.exe --background --factory-startup --python-exit-code 1 --python tools\test_wwmi_roundtrip_blender.py
```

Expect one `AUDIT_RESULT` line with `indices: 10446` for `MERGED_COMPONENT`,
`MERGED` and `UNICOMPONENT`, `source_preserved: true`, and no leftover objects.
The generated `Buffers\*-Position.buf` is 44652 bytes = 3721 vertices (seam
split of the 3540 captured ones), `Vector.buf` 29768 = 3721 x 8, `Texcoord.buf`
59536 = 3721 x 16, and there is **no** `Blend.buf`.

Regression tests:

- `tools/test_wwmi_component_routing_blender.py::test_static_layout_without_bone_indices_keeps_face_ownership`
- `tools/test_wwmi_component_routing.py` (pure planner, unweighted vertices)
- `tools/test_wwmi_srv_binding_ini.py` (no blend reference in the ini)

## Pitfalls

- Do not "fix" this by adding a zeroed `Blend` category or by painting all-1
  weights: the draw has no skinning input, so the game never reads a blend
  buffer for it, and fabricated data only hides the real contract.
- A *weighted* WWMI layout must still fail loudly when a triangle cannot be
  localized; only a layout with no bone index element may skip routing. Keep the
  `scalar.kind != 'u'` guard for layouts that do declare indices.
- `get_blendindices_count_wwmi()` returns 4 when there is no `BLENDINDICES`; the
  weight packing path still runs and is simply unused. Do not special-case it.
