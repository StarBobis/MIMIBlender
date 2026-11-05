---
name: texture-combiner-blueprint-results
description: Maintain automatic atlas planning, persistent output folders, and blueprint selection of generated DiffuseMap atlases.
---

# Texture Combiner Blueprint Results

## Ownership

- `texcomb/operators/combiner/size_distribution.py` owns planning and manual locks.
- `texcomb/operators/combiner/combiner.py` owns entry-point validation and merging.
- `i18n/i18n.py` owns the single root-module AddonPreferences class.
- `texcomb/output_settings.py` owns the persistent default-folder chooser.
- `common/merged_texture_results.py` owns explicit generated-image metadata.
- `blueprint/texture_row_ui.py` owns the shared result chooser; targeted Slot rows need their own assignment adapter.

## Invariants

- A missing distribution is generated automatically. Recalculate stale existing rows without discarding manual locks. Impossible constraints still cancel before UV mutation.
- Never scan geometry or decode images during panel redraws.
- DDS converter discovery is silent when a usable texconv executable is found. Hide both its path chooser and success status; show the chooser and missing-tool warning only when the existing resolver cannot find any candidate. Preserve resolver precedence and saved custom paths rather than introducing another discovery rule.
- The default folder is an add-on preference, not a Scene property. Save it explicitly when chosen, independent of Blender automatic preference saving.
- Programmatic exports with an explicit directory must not change the user's persistent defaults.
- Identify generated albedo images by explicit metadata, not filename guesses. Never offer metallic, normal, or roughness atlases as DiffuseMap.
- Use each row owner's existing file assignment path so naming, conversion, and export stay unchanged.
- Selecting a result stores that result's path, not an arbitrary global latest atlas. Multiple objects and previous merges may need different results.
- Tests and generated assets belong under `tmp/`; isolate Blender user configuration before testing preference persistence.

## Blender-specific traps

- Set `SKIP_SAVE` on the combiner's hidden directory argument. Otherwise Blender's last operator properties can override a newly selected default folder.
- Dynamic result enum tuples need stable explicit numeric values and long-lived strings. A removed file must not cause a remaining result to inherit the removed result's enum index.
- `bpy.ops` namespaces are transient proxies. Mock the owning module's `bpy` boundary rather than assigning a mocked attribute to `bpy.ops.wm`.
- Standalone synthetic node trees need `use_fake_user = True` before saving. Generated atlas Images also keep a fake user so replacing a material does not erase result discovery on reopening.
- `MIMINode_Texture_Global.width_texts()` is required by the node-title load handler, just like the Global Hash manager. Missing it interrupts saved-blueprint migration.
- Reserve atlas IDs from all supported output extensions and PBR channels when a persistent output folder contains earlier results.

## Verification

Use the installed executable at `C:/Program Files/Blender Foundation/Blender 5.2/blender.exe` with `-b --factory-startup --python-exit-code 1`.

1. Set `BLENDER_USER_CONFIG` to a fresh absolute directory under project `tmp/`.
2. Run `--python tools/test_texcomb_workflow.py`. This saves isolated preferences even with auto-save disabled, exercises PNG/DDS, fresh execute and stale invoke, validates all four texture node types, preserves manual locks, rejects missing files/rows, and writes a synthetic blend.
3. In a second process with the same isolated configuration, run `--python tools/test_texcomb_workflow.py -- --reopen <config directory>/atlases`. Factory startup skips preferences, so the test explicitly calls `read_userpref()` before verifying the default and reopening the blend.
4. Run `tools/test_texcomb_distribution.py`, `tools/test_texcomb_distribution_performance.py`, and `tools/test_global_hash_blender.py` under factory-startup Blender. For converter UI changes, also run `tools/test_texcomb_dds_controls.py`: it covers bundled discovery, stale custom paths with a working bundle, missing candidates, explicit recovery paths, and environment discovery without saving preferences.
5. Run the aspect, fixed-block, shared-repeat, shared-texture, UV-regression, UV-repeat-cost, and solid-preview Blender suites when changing merge preparation.
6. Run plain-Python `tools/test_texture_bind_ini.py` and `tools/test_hash_texture_bind_ini.py` for unchanged resource-copy and conversion contracts.
7. Run `tools/check_i18n.py` and `git diff --check`. The current baseline has 11 missing keys in the retired component-routing code; this feature must add no new missing translations. Both Chinese dictionaries carry the same new English msgids.

The large-mesh regression uses 100,000 polygons and 300,000 UV loops. It proves redraws never call the deep geometry fingerprint while merge-time validation still attempts recalculation. A cancelled repair must leave UVs and output files untouched.

The optional pure-core suite uses `python -m pytest texcomb/tests --basetemp tmp/<fresh directory> -p no:cacheprovider -q`. If pytest is absent, install it with `pip --target tmp/<dependency directory>` and set that directory as the test process's `PYTHONPATH`, not the global Python environment. Disable unrelated plugin autoload for isolation. The measured baseline is 206 passes and one pre-existing failure in `test_dds_match.py::test_linear_target_keeps_raw_bytes`: it expects raw data bytes from an AUTO color replacement without declaring DATA treatment. A clean HEAD archive reproduces the exact same `(55, 13, 4, 200)` pixel mismatch. Do not change color conversion semantics to silence that unrelated fixture.
