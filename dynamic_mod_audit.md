# Dynamic Mod Audit

## Scope and verification level

Reviewed the DrawIndex Based Dynamic Mod (DrawIndexed switching), the Position.buf Based Dynamic Mod and the ShapeKey Real-time Based Dynamic Mod paths, including shared, Naraka and WWMI shape emission. Changes cover graph parsing, baking, buffer generation, resource declarations, command ordering, shader layouts and regression tests.

The original implementation was examined against the local bo3b/3Dmigoto source checkout at revision `8f329bd94fecc9bbcb9211ffd42a95dd7fe6b43e`. Validation includes real Blender 5.1 mesh evaluation and real D3D11 WARP shader compilation/dispatch/readback. It does **not** include injection into a running game or a complete extracted-character export for every preset.

## Findings and fixes

| Severity | Area | Finding | Resolution |
| --- | --- | --- | --- |
| Critical | Position frames | Blueprint attached `time_pos_frame_models`, but both writers consumed the never-populated `time_pos_frame_groups`. | Populate and validate the actual groups during DrawIB construction. Missing base DrawIBs now fail explicitly. |
| High | Shared aliases | Marking every draw carrying a Position timeline alias also removed ordinary DrawIndexed branches sharing that clock. | Record per-draw graph provenance, independently of the shared variable name. |
| High | Single Position frame | A one-frame node became an ordinary extra draw instead of replacing the separately connected base. | Keep one-frame Position nodes in the provider pipeline. |
| High | Position compatibility | Equal Position byte counts did not guarantee matching index/vertex order or shared UV/weight/normal data. | Compare exported IBs, loop correspondence and all non-Position categories, then validate the replacement slice length. |
| High | Multiple Position writers | Independent full-buffer copies undid each other's submesh changes. The first provider's gate was incorrectly assumed to represent all providers. | Require one clock and common outer conditions per DrawIB; reject duplicate providers and unsupported nested Position nodes. |
| High | Inactive/empty frames | No matching copy branch retained the previously selected geometry indefinitely. | Explicitly restore a separate original buffer for inactive gates or empty frames. |
| High | Shape composition | Overwriting `Position.1` changed the reference used by `shape - base`, cancelling animation at full shape weight. | Introduce a mutable `PositionTimeBase` accumulator seed; preserve the immutable `Position.1` reference. |
| Critical | Shared shape output | A structured UAV cannot be directly referenced as a vertex buffer. D3D11 rejects the combined structured/vertex descriptor. | Copy the computed bytes into an explicitly raw vertex buffer, replacing inherited misc flags, before referencing it from Position. |
| High | Shape input layout | The shared shader always assumed a 40-byte vertex, including for 12-byte Position streams. | Validate ordered semantics/formats/widths and select a dedicated 12-byte shader or the 40-byte shader. Reject unsupported layouts. |
| High | INI sections | Mixed writers produced repeated Constants/Present headers, including the append-order WWMI path. | Merge singleton contributions at insertion time; make repeated serialization idempotent. |
| High | Command timing | Pre-Present copies ran before input events, so new hotkey states could disagree with the next draw's Position seed. | Run gate-sensitive copies through an explicit `post run` command list, followed by shared shape compute. |
| High | Driver aliases | Digit-leading names and case variants violated engine naming assumptions; hotkeys could inherit a time driver depending on traversal order. | Validate identifiers, lowercase aliases, reserve internal names and reject mixed drivers in both traversal orders. Conflicting FPS values now fail. |
| Medium | Anonymous clocks | Revisited nodes allocated different clocks for each graph traversal. | Cache automatic clock identity per node/group instance. |
| Medium | Timeline robustness | Double-only tests missed float32 boundary behavior; invalid FPS or weights could generate malformed expressions. | Share validation and add a final modulo after floor division; test per-operation float32 rounding. Bound expanded timelines before traversal. |
| High | Shape dispatch | One thread per group exhausted Dispatch.x at 65,535 vertices. | Use 64-thread groups, ceil division, bounds checks and an explicit maximum group-count guard. |
| Medium | Shape state | Shared and WWMI paths cleared borrowed CS bindings instead of restoring the game's state. | Save/restore SRV/UAV references around shape computation. Naraka retains its existing restoration contract. |
| Medium | Shape initialization | A persistent first-run flag and duplicate first-frame compute were unnecessary and reload-sensitive. | Initialize the accumulator from its seed on each compute run; remove the extra pass and persistent initialization flag. |
| Medium | Frame copy overhead | Position resources were copied on every rendered frame even when the animation frame was unchanged. | Cache the selected frame, including inactive state, and copy only when selection changes. |
| High | Baking | Export normalization could discard animated object transforms; rebaking multi-input sockets could retain old links. | Bake world transforms into mesh data and remove old input links before connecting the new batch. |
| Medium | Baking safety | Failed sampling left partial hidden data; fractional scene time was lost; huge ranges allocated before validation. | Roll back newly created sampling data, restore subframes and use lazy ranges. |
| Medium | Resource naming | Animation frame filenames/resources shared the shape-name namespace; case-sensitive Blender names could collide on Windows. | Separate frame namespaces and validate unsafe/colliding shape names. |
| Medium | Unsupported paths | Some presets accepted animation data without a compatible consumer. | Explicitly reject unsupported Position presets, unsupported shared GPU shape paths, and EFMI/NTEMI time shape keys. |

## Correct runtime contracts

### DrawIndexed switching

- Each selected branch draws its own index range; topology can differ between frames.
- All frames still occupy the exported combined buffers. Disk/VRAM cost grows with mesh complexity and frame count.
- A shared alias synchronizes clocks, not draw classification. Different branch counts retain the existing LCM-period behavior, bounded to 10,000 states.
- An empty socket remains an empty draw state. A single draw frame remains a pass-through.

### Position switching

- Connect one base object normally for each animated submesh.
- Use one shared Position timeline per DrawIB. Several submeshes may share it when their outer conditions agree.
- Frame files contain the whole DrawIB Position stream, replacing only the selected submesh slices. Other slices remain byte-identical to the base.
- Topology and non-Position attributes must remain compatible. If separate normals, UVs, weights or other categories change, use DrawIndexed switching instead.
- Empty/inactive states restore the original. Repeated selections do not issue redundant full-buffer copies.
- WWMI, NTEMI and EFMI remain unsupported. Shared Position GPU paths for Naraka/NarakaM/AILIMIT/ZZMIDX12 retain their existing allowlist; other GPU paths fail rather than silently remaining static.

### Shape-key animation

- The shared shaders support exact float32 layouts: 12-byte POSITION, or 40-byte POSITION/NORMAL/TANGENT. Packed/reordered/other layouts require a dedicated shader.
- The 12-byte shader animates Position only; separate vector streams are not animated by that shared path. WWMI retains its separate Position/Vector implementation.
- Composition is `animated_seed + sum(weight * (full_weight_shape - immutable_base))`.
- Each compute run resets its accumulator. Shape weights do not accumulate across frames or repeated overrides.
- Shared output uses an explicit raw vertex buffer; Naraka uses an explicit raw shader-resource buffer immediately before skinning.
- The shared path rejects GPU pre-skinning without a dedicated integration. Naraka and WWMI use their dedicated integrations.

## 3Dmigoto source checks

Source links below point to the exact revision inspected locally:

- [CommandList.cpp](https://github.com/bo3b/3Dmigoto/blob/8f329bd94fecc9bbcb9211ffd42a95dd7fe6b43e/DirectX11/CommandList.cpp): `DEFINE_OPERATOR` evaluates float operands; `//` is floor division and `%` is fmod. `valid_variable_name` defines the variable grammar. `VariableAssignment::run` marks persistent state dirty, rather than writing a file for every assignment.
- The same file's `ParseRunExplicitCommandList` explicitly handles `post run` by running the target's command lists together. `RunExplicitCommandList::run` implements that behavior. Resource descriptor override/recreation logic explains why misc flags must be explicitly replaced when converting structured results to raw buffers.
- [HackerDXGI.cpp](https://github.com/bo3b/3Dmigoto/blob/8f329bd94fecc9bbcb9211ffd42a95dd7fe6b43e/DirectX11/HackerDXGI.cpp): `RunFrameActions` runs pre-Present commands before input dispatch; post-Present commands run after the underlying Present call. They prepare future draws, not geometry already rendered into the image being presented.
- [IniHandler.cpp](https://github.com/bo3b/3Dmigoto/blob/8f329bd94fecc9bbcb9211ffd42a95dd7fe6b43e/DirectX11/IniHandler.cpp): command phase parsing and explicit resource bind/misc flag overrides were checked. Runtime timelines remain non-persistent because they are not user settings, not because persistence inherently writes disk every frame.

## Regression coverage

- `python tools/test_time_switch_ini.py`: globals/hotkeys, frame conditions and float32 expression boundaries.
- `python tools/test_time_position_ini.py`: frame resources, restoration/cache branches, weight timelines, structured inputs/raw VB output, mixed-feature composition, post-hook ordering, singleton sections and both serialization modes.
- `python tools/test_naraka_shapekeys.py`: Naraka skinning hook order, raw conversion, input declarations and borrowed-slot restoration.
- `python tools/test_naraka_shapekey_gpu.py`: real HLSL compilation and D3D11 WARP execution for 12-byte and 40-byte layouts; weights 0/0.3/1/reset/multiple additions; animated seeds; partial work groups; 65,537 vertices. Also reproduces three invalid legacy descriptor combinations.
- `blender -b --factory-startup --python-exit-code 1 --python tools/test_dynamic_animation_blender.py`: real model traversal/grouping/assembly with mocked external workspace lookups, byte-slice preservation, topology/attribute rejection, actual Blender mesh evaluation, world transforms, fractional-frame restoration, failed-sampling cleanup, replacement wiring, lazy ranges and WWMI time-weight emission.
- `blender -b --factory-startup --python-exit-code 1 --python tools/test_dynamic_mod_titles.py`: dynamic mod node titles in both languages, node width, the legacy title migration (English and Simplified Chinese spellings, user-chosen titles preserved, idempotent), the real save/reopen `load_post` path and the renamed report translations.
- Python compilation of `blueprint`, `common`, `model`, `games`, and `tools`; Git whitespace validation.

## Remaining limits and migration

1. Regenerate the INI, buffers and shaders together. Frame namespaces and shader group sizes changed; do not mix old generated artifacts with the new shaders.
2. No running-game validation was performed. Confirm representative exports in each target game, especially GPU pre-skinning and combined Position/shape animation, and inspect the 3Dmigoto log for resource or command errors.
3. Position files remain full-size per-frame buffers, not compressed deltas or independent per-submesh GPU composition. Multiple independent clocks per DrawIB are intentionally rejected rather than approximated.
4. Playback remains step-sampled and injection-clock-relative. Low render rates can skip animation samples, and float32 clock precision degrades with very long uptime. The modulo guard prevents invalid frame indices; it cannot recover time precision already lost by the engine.
5. Supported layouts and presets are explicit safety boundaries, not a claim that every extracted game format can use all three techniques. DrawIndexed switching remains the general fallback for topology or multi-category animation.
