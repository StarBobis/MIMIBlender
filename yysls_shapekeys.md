# YYSLS dynamic ShapeKey export

## Usage

1. Select the **YYSLS** game preset.
2. Enable shape-key generation on the output node and select the required keys.
3. Use the existing weight hotkeys, or a **ShapeKey Real-time Based Dynamic Mod** node for animated weights. Do not configure the same shape in both places.
4. Generate the mod normally. The exporter packages lowercase `yysls_shapes_<drawib>.hlsl` files beside the INI automatically.
5. Reload the mod in the game and check the intended mesh, its other render passes, and an unrelated mesh.

No manual copying from the supplied example is necessary. The example's source files are not modified. Other game presets retain their existing exporters.

## Reference and implementation

This implementation adapts the user-supplied Where Winds Meet dynamic ShapeKey example: start from the original vertex buffer, copy it into a compute UAV, blend full-weight shape data, then draw with the computed position buffer. Its packed-normal algorithm decodes UNORM8 XYZ to a signed direction, normalizes the result, and preserves the fourth byte.

The example's fixed triangular/smoothstep clock is intentionally not hard-coded. The existing node timeline and hotkey system provides the weights instead.

Production differences:

- Compute runs before VB binding, inside the existing costume-mod gate and cloth/fallback draw scope.
- A transient per-DrawIB flag caches the result across submeshes and render passes. Post-Present invalidates it; offscreen models do not dispatch. Reload starts with an invalid cache, so the first draw works even before Present.
- Work groups contain 64 threads, with tail guards on all accessed resources. The supported maximum is 65,535 groups, or 4,194,240 vertices.
- Immutable inputs are explicit structured SRVs. They are referenced instead of copied on every shape dispatch.
- The UAV is allocated through `cs-u5 = copy <seed>`, preserving the reference's important allocation order.
- The compute result is copied to an explicitly RAW-only vertex buffer. A direct reference from a structured UAV to a VB can create illegal `STRUCTURED | VERTEX_BUFFER` resource flags on standard D3D11 implementations.
- Borrowed `cs-u5`, `cs-u6`, `cs-t50`, and `cs-t51` slots are saved and restored.
- Multiple shape deltas accumulate in float precision before the final position quantization and normal normalization. Single-key computation keeps these deltas in registers and needs only one dummy scratch record, rather than a per-vertex scratch array.
- Zero weights preserve every seed byte exactly. Color, UV, padding, normal W, and quantized position W are not interpolated.
- Position animation supplies a mutable seed while shape deltas still subtract the immutable original. The result is `animated_seed + sum(weight * (shape - original))`.

## Supported layouts

The Position category must feed a vertex-buffer slot and have a word-aligned stride of at most 2048 bytes. Field offsets are derived from category-local metadata, including padding, rather than inferred from stride alone.

| Field | Supported encoding |
| --- | --- |
| POSITION | `R32G32B32_FLOAT` or `R16G16B16A16_UNORM` |
| NORMAL | `R8G8B8A8_UNORM` |
| Other fields | Copied unchanged from the seed |

This covers the supplied 28-byte float-position mesh and packed 24-byte UNORM16-position meshes. Compressed positions stay in the original shared bounding-box coordinates; values outside that representable range are clamped. Other normal encodings, compute-slot Position categories, malformed lengths, and unsupported layouts raise a diagnostic rather than emitting a corrupt shader. Use DrawIndexed animation for those layouts.

The `GPU_PreSkinning` metadata flag alone does not reject a YYSLS mesh: this exporter consumes its Position category as a VB. No compute-skinning interception is added.

## Validation

Run from the repository root:

```text
python tools/test_yysls_shapekeys.py
python tools/test_yysls_shapekey_gpu.py
python tools/test_yysls_cloth.py
python tools/test_time_position_ini.py
python tools/test_animation_toggle_ini.py
python tools/test_naraka_shapekeys.py
python tools/test_naraka_shapekey_gpu.py
```

The GPU tests use Windows D3D11 WARP and compile the actual exported shader source. They compare full read-back buffers against an independent CPU oracle. Cases include both layouts, 65-vertex tails, 65,537 vertices, zero/partial/full/negative weights, multi-pass accumulation, opposing normals, and animated seeds. The single-key tests bind the same tiny scratch buffer used by the exporter.

To test the supplied original mesh without changing it:

```text
python tools/test_yysls_shapekey_gpu.py "<example>/Buffer/b08e2121-Position.buf" "<example>/Buffer/b08e2121-Position.ShapeKeyApplied.buf"
```

The supplied 7,691-vertex pair passed all seven weight sequences. The eight new INI tests and eleven existing cloth tests also passed. Existing time-position, animation-toggle, Naraka INI, and shared GPU regression tests passed. `tools/test_yysls_blend.py` passed under Blender 5.2 using `--background --factory-startup --python-exit-code 1 --python`.

The broader, unchanged `tools/test_dynamic_animation_blender.py` passed its first seven checks, then stopped in `test_rebake_wiring_and_large_ranges`: its `SimpleNamespace` node collection lacks `.get()`, which the unchanged `blueprint_time_bake.py` requires. This unrelated fixture failure was not modified as part of the YYSLS integration.

These checks validate generation and Direct3D arithmetic/resource descriptors, not the particular game's loader parser or live rendering. In-game acceptance is still required, especially for cloth shader scoping, model visibility toggles, reload, and multipass rendering.
