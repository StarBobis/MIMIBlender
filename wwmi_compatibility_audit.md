# WWMI compatibility audit after v1.0.49

## Scope and evidence

This audit follows the reported Merged Component bone 223 error and the Merged native shape-key batch metadata error. The original failing Blender project was unavailable. Evidence combines source/protocol inspection, synthetic regressions, and fresh imports of five existing local extraction workspaces. It is not an in-game rendering certification.

The audited path is extraction metadata consumption → vertex-group import → blueprint component/LOD selection → temporary joins → bone/shape buffer construction → generated INI/runtime resources → failure cleanup. No extractor or third-party runtime files were modified.

## Findings and fixes

### 1. Legacy runtime slots are not necessarily canonical VGMap names

The Xin component with `VGOffset=105`, `VGCount=121`, and `VGMap[118]=68` proves that runtime slot **223** and canonical bone **68** describe the same original bone. Rejecting 223 solely because it is absent from canonical VGMap values is incorrect for legacy/reverse-imported groups.

[Merged Component localization](games/wwmi/merged_component.py) now follows metadata-backed aliases while still requiring that the resolved bone exists in the target component's palette. It does not authorize arbitrary cross-component weights or subtract offsets blindly. Tests cover 223→68→118, shared ownership, unrelated-component rejection, and preservation of the source object.

### 2. Blender group indices are not bone identities

[WWMI model construction](games/wwmi/model.py) resolves numeric group names after joining, retains full-width identities for the runtime input buffer, and validates local palette bounds before R8 packing. Reordered or sparse groups are no longer deleted because their internal indices exceed a guessed count. Only deliberately named `ignore` groups retain the existing discard behavior.

Merged, PerComponent, and UniComponent now use the same identity principle as Merged Component. Zero-weight padding does not require a valid bone. Active nonnumeric groups produce an error rather than silently changing the skeleton.

When the existing merge-duplicate-groups option is enabled, per-component duplicate-name normalization occurs **before** selecting runtime palette influences. Otherwise merging `510` and `510.001` at the final join can promote a previously omitted fifth influence into the top four after its remap table has already been built. A regression covers this exact ordering problem. Active identities absent from a compact map are also explicitly rejected.

### 3. The fixed 512-entry runtime table was a real fresh-import failure

A fresh Xin Merged export reproduced `IndexError: index 512 is out of bounds for axis 0 with size 512`. Its original runtime skeleton extends to **553** slots.

The fix covers all dependent layers, not just numpy allocation:

- Uniform forward/reverse table stride: `max(512, max(VGOffset + VGCount))`.
- Actual numeric group names select table entries.
- Both original and extra merged skeleton buffers allocate at least three float4 rows per original slot; Xin requires **1659** rows.
- Every BlendRemapper call and both SkeletonRemapper calls receive the extended stride, because the inspected runtime resets the parameter after each call.
- Any extended remapped DrawIB raises the **whole Mod's** required WWMI runtime to **1.10**, even if its first DrawIB uses ordinary tables.
- Ordinary exports retain the existing 1.00 requirement. This audit verifies the extended API in runtime 1.10; it does not claim the precise historical version that introduced it.
- R16 identity limits, the 256-effective-bone limit per R8 draw, invalid ranges, and uninitialized gaps between runtime component ranges are checked before writing resources.

Runtime protocol inspection covered the installed WWMI 1.10 INI plus its BlendRemapper, SkeletonRemapper, and SkeletonMerger shaders. [Generated runtime integration](games/wwmi/blend_remap.py) and [Mod-level registration](games/wwmi/exporter.py) have matching regressions.

### 4. Shape-key metadata could be lost or misclassified

[Metadata normalization](workspace/wwmi_info.py) combines nonempty shape fields across the DrawIB's ordered components instead of trusting only the first component. Conflicting nonempty values are rejected rather than silently choosing one capture.

- Missing checksum is distinct from a valid checksum of **zero**.
- Legacy single-batch records preserve original vertex offset, count, and completeness information.
- Missing checksum or dispatch data remains an error; edited shape buffers cannot reconstruct the game's original checksum.
- Diagnostics distinguish exported batch count from available metadata and point to workspace/LOD selection and numeric Deform/Custom IDs.
- [Shape handling](games/wwmi/shapekeys.py) still requires genuine original metadata for every exported batch.
- A mesh with no shapes now produces an empty cache rather than a truthy tuple of `None` values in [shape utilities](utils/shapekey_utils.py).
- All models' native shape dispatch metadata and required offsets hashes are checked **before any buffer write**, preventing this class of error from leaving an existing Mod half-updated.
- Expected `Fatal` errors reach the existing operator error-report path rather than an uncaught traceback.

The exact trigger in the unavailable original project remains unproven. A truly missing additional batch is not papered over: the exporter still refuses to fabricate runtime data or discard its shapes.

### 5. Import and UniComponent palette compatibility

[Import selection](common/mmt_import_helper.py) and [mesh creation](common/mesh_create_helper.py) preserve an explicit empty VGMap so that `VGOffset + local` fallback remains enabled. WWMI duplicate local aliases mapping to the same global bone add their weights instead of replacing earlier contributions.

[UniComponent palette selection](model/blueprint_model.py) now:

- Stays within the node's exact LOD scope.
- Builds complete palettes from VGCount with explicit map overrides and offset fallbacks.
- Shares metadata-backed runtime aliases across every compatible palette.
- Recognizes numeric Blender suffixes and ignores unused nonnumeric helpers when selecting candidate palettes.
- Reports palette loading failures instead of silently omitting that component.

[UniComponent splitting](utils/vertexgroup_utils.py) no longer crashes on nonnumeric helper groups in shared-bone fallback. Before creating copies it rejects faces spanning incompatible ownership and active influences outside their selected palette. Those edits require Merged; successful export must not mean missing faces or discarded weights.

### 6. Temporary data cleanup

Failed WWMI model construction removes only objects created during that invocation. Newly orphaned mesh copies are removed on both success and failure.

[Output cleanup](ui/ui_func_export.py) also handles a UniComponent blueprint constructor failing after earlier nodes created split copies, before the caller receives the blueprint instance. It tracks object/mesh identity, not `TEMP`/`Uni` name prefixes, and resets runtime output state. Existing scene objects, including similarly named ones, are preserved.

## Verification

Final verification status: **all 109 focused tests passed; all 20 final real-workspace exports passed**. The final matrix also passed source-data digest, index coverage, temporary-object, and orphan-mesh assertions. Compilation and whitespace checks passed. Earlier successful matrix runs were followed by this final run after the additional UniComponent loss guards and duplicate-group ordering fix.

### Focused suites

- [Merged Component and architecture regressions](tools/test_merged_component_blender.py): 27 tests.
- [Shape batches and metadata compatibility](tools/test_wwmi_batches.py): 20 tests, including the optional real 161-key/two-batch fixture when available.
- [WWMI component INI integration](tools/test_wwmi_components_blender.py): 15 tests.
- [Multi-DrawIB INI integration](tools/test_wwmi_multi_drawib_ini.py): 17 tests.
- [Merged sculpt compatibility](tools/test_merged_sculpt_blender.py): 25 tests.
- [Split draw ownership](tools/test_split_draw_ranges_blender.py): 5 tests.

Total: **109 focused tests**. Python compilation and `git diff --check` are separate checks.

### Real workspace matrix

[Optional safe roundtrip harness](tools/test_wwmi_roundtrip_blender.py) imports and exports in factory-startup Blender 5.2.0 LTS. Workspace selection/cache writes are mocked; generated files are redirected under the repository's ignored temporary folder. No user's blend file is opened, saved, or modified.

Each globally named import is exported as Merged Component, Merged, and UniComponent. PerComponent is imported separately with local names and exported in that mode. Each export verifies its status, exact index coverage, a digest of source geometry/group names/weights/all shape coordinates, and the absence of leaked objects or orphaned mesh copies.

| Workspace | Expected exported indices per architecture | Architectures |
| --- | ---: | --- |
| Xin | 355434 | Merged Component, Merged, UniComponent, PerComponent |
| Default | 145266 | Merged Component, Merged, UniComponent, PerComponent |
| MoNing | 273777 | Merged Component, Merged, UniComponent, PerComponent |
| QingXiao | 296013 | Merged Component, Merged, UniComponent, PerComponent |
| Veilinai | 145266 | Merged Component, Merged, UniComponent, PerComponent |

Default and Veilinai share the same DrawIB and index count; this is a five-workspace matrix, not evidence of five distinct character geometries.

This is **20 exports across 10 isolated Blender processes** per complete matrix run. Assertions fail the process rather than merely printing a caught exception.

Example invocation from the repository root:

```text
blender --background --factory-startup --python-exit-code 1 --python tools/test_wwmi_roundtrip_blender.py
```

Set `MIMI_AUDIT_WORKSPACE` to a local workspace name and optionally `MIMI_AUDIT_IMPORT_MODE=PER_COMPONENT`. The default workspace is Xin. Missing optional workspaces are explicitly reported as skipped.

## Remaining boundaries

- No original failing scene or in-game test was available; no claim is made about their observed final rendering.
- Corrupt/missing original batch metadata, genuine cross-component weights in an offline-local architecture, and more than 256 effective bones in one R8 draw remain explicit errors.
- Preflight prevents metadata-validation partial writes, not arbitrary filesystem failures during subsequent output generation. Export is not a transactional filesystem operation.
- This patch does not migrate saved user scenes, overwrite extraction caches, or modify WWMI-Tools/the runtime. It does not change unrelated game presets' export protocols.
