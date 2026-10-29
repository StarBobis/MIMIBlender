# WWMI compatibility audit after v1.0.49

> Historical record. The MergedComponent and UniComponent architectures
> described below were removed from the add-on; the current vertex group modes
> are Merged and PerComponent. The removed sources are kept in `recycle/`.

## Scope and evidence

This audit follows the reported Merged Component bone 223 error and the Merged native shape-key batch metadata error. The original failing Blender project was unavailable during the initial audit. Evidence for that audit combines source/protocol inspection, synthetic regressions, and fresh imports of five existing local extraction workspaces. The later supplied-project investigation is recorded separately below. It is not an in-game rendering certification.

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

The initial audit did not establish the exact trigger in the then-unavailable project. The supplied-project investigation below now distinguishes missing metadata from native ID packing. A truly missing additional batch is not papered over: the exporter still refuses to fabricate runtime data or discard its shapes.

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

- The original scene was unavailable for the initial 109-test/20-export audit. The later supplied-scene checks below are separate; no in-game rendering test has been performed.
- Corrupt/missing original batch metadata, genuine cross-component weights in an offline-local architecture, and more than 256 effective bones in one R8 draw remain explicit errors.
- Preflight prevents metadata-validation partial writes, not arbitrary filesystem failures during subsequent output generation. Export is not a transactional filesystem operation.
- The initial patch did not migrate saved scenes. The explicit metadata-only repair helper described below is opt-in and does not save the scene. Neither patch overwrites extraction caches or modifies WWMI-Tools/the runtime or unrelated game export protocols.

## Supplied-project investigation and reverse metadata follow-up

### Reproduction and distinct causes

The later supplied scene contains nine edited reverse-import meshes, eight native component bindings, and native `Deform` IDs **0–175**. Its blueprint targets `LOD0.e590b8d4`. The reverse JSON is input data, not a replacement for the native MMT export workspace.

- Saved workspace synchronization currently resolves to the host's `Default` workspace. That is not evidence that the user selected the wrong workspace when the scene was originally saved. Explicitly selecting the matching `Xin` extraction isolates the actual export failures.
- With that extraction, MergedComponent rejects component 3's bone **229**. It has positive weights on **281 vertices**, up to approximately **0.482353**, and is absent from component 3's original palette. This differs from the already-fixed metadata-backed alias **223 → 68 → local 118**.
- Merged then reaches shape packing: the native extraction only records one legacy **127-slot** batch, while the scene uses **176 native IDs**. The reverse JSON already records two complete runtime batches, **127 + 49**, but the old reverse import did not retain those records on its objects for export.
- The reverse source and extraction match all eight original component draw ranges, the shape offsets/scale hashes, and the first runtime batch's checksum/dispatch. The second batch records checksum **3465**, dispatch Y **712**, and original vertex base **75507**. None of those values is inferred from edited buffers.

### Implemented metadata fix

[Reverse metadata preservation and validation](<workspace/wwmi_reverse_metadata.py>) stores a portable JSON custom property on newly imported WWMI reverse objects. The metadata includes original component match ranges and shape runtime records, not an absolute source path.

[WWMI model initialization](<games/wwmi/model.py>) considers only connected source objects and validates their metadata before creating temporary meshes. Original component ranges, resource hashes, and every overlapping runtime batch must agree. Multiple sources may contribute consistent longer sequences, but conflicting records fail atomically. Native skeleton palettes and mesh counts remain unchanged; compact reverse buffer counts/addresses never replace original runtime identities.

Existing saved projects cannot retrospectively recover properties that were never stored. To attach the known source metadata without reimporting edited geometry:

1. Enable the updated addon and select the edited meshes imported from the relevant reverse source.
2. Open [the metadata attachment helper](<tools/attach_wwmi_reverse_metadata_blender.py>) in Blender's Text Editor and set `source_json` to that explicit reverse JSON.
3. Run the helper. It attaches metadata only, does not save any file, and rolls back its property changes if attachment fails.
4. Export against the matching native workspace. Target compatibility is validated during export. Use Merged if retaining weights that cannot fit an original local palette.

[Shape packing diagnostics](<utils/shapekey_utils.py>) now report the DrawIB, offending native ID, slot capacity, and missing-metadata remedy. Do not delete or renumber native keys merely to suppress this error. [Workspace errors](<utils/mmt_error_utils.py>) now reuse the exporter's shared expected-error class, fixing missing-workspace failures that previously escaped the UI report handler.

### Supplied-scene and persistence checks

With only explicit metadata attachment and in-memory selection of the matching workspace/Merged mode, the supplied scene exported successfully through the production code. The final exporter was not monkey-patched to fabricate batch records. Generated resources contain both 128-offset blocks and both recorded runtime dispatch identities. All source mesh coordinates, group names/weights, shape names/coordinates, and face topology passed preservation checks; temporary objects/meshes were cleaned up. The original blend's SHA-256 remained unchanged.

A separate factory-scene probe imported all **10 recorded reverse JSON segments** (one whole-buffer segment plus nine component segments), verified IDs 0–175, copied an object, saved only that newly generated test scene, and reopened it. All imported objects retained the metadata property. The user scene itself retains only the nine component objects. The reverse source JSON and adjacent resources were unchanged. No original project was saved; local Blender also warned that it was older than the binary that wrote that project.

The follow-up regression run passed **127 tests**: 29 MergedComponent, 21 shape batches, 15 reverse metadata, 15 component modes, 17 multi-DrawIB INI, 25 merged sculpt, and 5 split draw ranges. The LOD isolation fixture was updated to include the native shape container required by production metadata initialization; the production validation was not bypassed.

The earlier 20-export matrix is historical, not a rerun against this supplied scene. No exported Mod has been visually validated in game.

### Follow-up design: automatic component reassignment

A missing bone in the current component does **not** prove that the triangle cannot be exported with any original local palette. Before rejecting reassignment, intersect the compatible-component candidates for **every positive influence on every vertex of each triangle**. Metadata-backed aliases must participate in the same way as normal localization.

Read-only analysis of the nine supplied source meshes found:

| Skeleton feasibility | Triangles |
| --- | ---: |
| Already compatible with the assigned component | 68019 |
| Exactly one alternative component candidate | 25142 |
| Multiple alternative component candidates | 1843 |
| No original component can represent all influences | 5131 |

The last group consists of **2007** triangles on component 3 and **3124** on component 6. Across the source objects, **3151 vertices** individually have no compatible original palette. Copying boundary vertices or merely separating objects cannot remove an individual vertex's mixed-palette bone dependencies.

These counts establish skeleton feasibility only, not compatible material/texture/draw states. Automatic reassignment was not part of the metadata patch. It is now implemented in the separate follow-up below, with explicit consent for native destination draw-state changes rather than claiming that matching bone palettes prove matching materials.

## Follow-up: conservative whole-triangle component routing

The [pure planner](<games/wwmi/component_routing.py>) checks every positive influence of every triangle corner against the actual representable original palettes. It shares canonical/alias resolution with [final local-index conversion](<games/wwmi/merged_component.py>). An already valid blueprint target always wins. A unique alternative requires the new **Allow Component Draw-State Changes** option, which defaults to false. Multiple alternatives and impossible triangles remain errors.

The [Blender adapter](<games/wwmi/component_routing_blender.py>) rebuckets only the temporary export IB and draw models. It does not physically split source objects or edit source weights. Shared vertices with different destination local indices duplicate naturally during buffer packing; both original native shape IDs and their deltas follow the existing vertex mapping. Original texture binding resolution runs before routing. Every conditional draw branch is copied separately, including explicit texture capture/restore lines, hotkey conditions, and time conditions. Unspecified native shader/material state comes from the destination component under the user's explicit consent.

Any remaining issue prevents the entire plan for that DrawIB from being applied. The complete Blender Text report contains source object names, pre-modifier source face IDs, post-modifier triangle/vertex IDs, all positive weights, candidate component IDs, and individually unassignable vertices. The new UI buttons open the report and select problem source faces. Selection validates ordered source topology rather than trusting matching polygon counts. Unknown modifier provenance is not guessed. See the [Chinese usage and repair guide](<wwmi_component_routing.md>).

### Follow-up regression results

All **151 focused tests passed**: the previous 127 plus [15 pure routing tests](<tools/test_wwmi_component_routing.py>) and [9 Blender routing tests](<tools/test_wwmi_component_routing_blender.py>). New integration checks cover:

- Four source vertices producing six output vertices due to different local palettes, with original `Deform 0` and `Deform 127` deltas duplicated correctly across two runtime batches.
- Real conditional INI draws, keyboard/time conditions, explicit per-draw texture capture/restore, multiple source branches, and complete non-contiguous IB rebucketing.
- Atomic rejection when one face can move but another cannot; conservative default consent.
- Problem-face selection, stale-topology rejection, joined-object provenance, triangulated quads, and Mirror modifier provenance with shape keys.

The [real-workspace roundtrip harness](<tools/test_wwmi_roundtrip_blender.py>) was also rerun on Xin, Default, MoNing, QingXiao, and Veilinai in **all four architectures: 20 successful exports**. Every run retained complete source index coverage, unchanged source geometry/weights/shapes, and no temporary-object or orphaned-mesh residue. Xin's Merged runtime stride remains 553; its local modes remain unaffected by that extended runtime table.

The global translation coverage command still reports **67 pre-existing missing keys**. Comparison against HEAD confirms the same 67 before and after this change, with **22 newly referenced UI/report messages and no new missing translations**. This is not reported as a clean global i18n check.

### Supplied-project results after routing integration

The same factory-startup, disabled-autoexec, read-only project probe was rerun against the matching Xin workspace and the production reverse-metadata attachment helper:

| Result | Default consent off | Consent on |
| --- | ---: | ---: |
| Already valid in original target | 68,019 | 68,019 |
| Unique alternative awaiting consent | 25,142 | 0 |
| Proposed reassignment | 0 | 25,142 |
| Multiple alternative targets | 1,843 | 1,843 |
| No complete original palette | 5,131 | 5,131 |

Both MergedComponent attempts correctly cancel with a complete report. Proposed reassignment counts are **not applied changes** when other faces remain blocked. The original project still cannot be fully exported through local palettes without explicit repairs or architectural choice; routing does not pretend otherwise.

The independent **Merged export still succeeds** with the preserved native two-batch shape metadata. All three project probes retain identical source geometry, weights, group names, and shape coordinates, leave no temporary objects or meshes, and preserve the original blend SHA-256 `44b363e30ddc2c497cf316c654e06d605431f5e305c6ce4e53160989c4fd72a5`. No game-side appearance verification is claimed.
