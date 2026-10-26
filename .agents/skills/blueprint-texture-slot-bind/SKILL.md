---
name: blueprint-texture-slot-bind
description: Change per-object texture replacement in the blueprint (Slot Texture Bind, Global Slot Texture Bind, key switches); explains why a marked texture cannot be swapped per object and where the copy has to come from.
---

# Blueprint Texture Slot Bind

## The 3Dmigoto fact that drives the whole design

| Mark style | What the automatic pipeline writes | Can a draw reference it? |
|---|---|---|
| `SharedSlot` | `[Resource-<capture stem>]` + `filename = Textures\<hash>_<name>.dds` | yes, the section exists |
| `Slot` | only the image file `Textures\<DrawIB>-<submesh index>-<name>.dds` | **no** — there is no resource section |
| `Hash` | `[TextureOverride_Texture_<hash>]` + `this = Resource...` | global only, never per draw |

Consequences:

- A `Slot` mark replaces the texture for the **whole Submesh by file name**. Two objects of
  one Submesh therefore always look the same unless each row owns its own image file.
- `ps-t3 = Resource-<capture stem>` for a `Slot` mark is a **dangling reference**: 3Dmigoto
  keeps the previous binding, so the mod exports and the key toggles but the picture never
  changes. This is the classic "switch does nothing" report.
- `ResourceTex_<DrawIB>_<Object>_<slot>` (see `common/texture_output_naming.file_resource_stem`)
  is the only name that can differ per object.

## Where each piece lives

| Concern | File |
|---|---|
| Row RNA, node drawing, mark dropdown, generated-name preview | `blueprint/blueprint_node_texture.py` |
| Collecting rows into plain dicts at export time | `model/blueprint_model.py` `_collect_texture_bindings` |
| Deciding the resource + copy job per row | `model/drawib_model.py` `resolve_texture_slot_bindings` |
| Generated file names shared by UI and export | `common/texture_output_naming.py` |
| Conversion (exact format) status + batch convert | `common/texture_format_service.py`, `blueprint/texture_format_widgets.py` |
| Emitting lines inside the switch condition | `common/m_control_flow.py` |

## Rules to keep

1. A per-object row must own a file. `MARK` + `mark_file_path` (the row's own image) or a plain
   `Slot` mark (copy of the capture) both go through `_resolve_mark_image_resource`; only a
   `SharedSlot` mark without an image may reuse the shared resource.
2. Never bind a name the INI does not declare. If a new row type appears, add it to
   `object_texture_binding_resource_list` so `add_object_texture_binding_resource_sections`
   writes its `[Resource...]` block.
3. The row's own image is a real replacement source: `_row_file_path`, `job_for_row`,
   `row_target_format` and `row_status` must all see it, otherwise "Convert Now" and the status
   line silently ignore the row.
4. `MARK` rows resolve their original capture by **mark name** (`row_selectors`), external files
   by slot. A slot can carry several marks, so the name is the precise selector.
5. `GIMI` submits known mark names through `Resource\GIMI\...`; those rows cannot carry a
   per-object image and must keep rejecting it loudly.
6. When two switch states bind the same resource for one object and slot, the switch cannot
   change anything — `_warn_identical_switch_states` prints the warning. Keep that check alive
   whenever the resolver changes.

## Supporting the duplicate-Object-Info switch flow

`Object Info -> Slot Texture Bind -> Switch Key (Status N)` needs one branch per state. Each
branch produces its own `DrawCallModel` for the same object; the geometry is merged twice and
the two draws differ only in their condition and their slot lines. `downstream_switch_state`
in the node file reads that wiring back so the node can show "state 2 of 2" instead of leaving
the user guessing whether the key is connected.

## Colour space of a replacement (texconv)

A replacement is converted to the capture's DXGI format, width/mips and header style. The
colour space is a separate decision and the historical bug was to pass both `-srgbi` and
`-srgbo` unconditionally: texconv then declares both ends sRGB, performs **no** conversion and
only re-tags the bytes. Measured with the bundled texconv:

| Source | Target | Flags | Stored value for sRGB 16..112 |
|---|---|---|---|
| sRGB PNG | BC7_UNORM_SRGB | `-srgbi -srgbo` | unchanged (correct) |
| sRGB PNG | BC6H_UF16 | `-srgbi` | linear `0.0052` (correct); with both flags `0.0627`, ~12x too bright |
| linear DDS | BC7_UNORM_SRGB | `-srgbo` | encoded back to `16..112`; with both flags stays dark |
| normal/mask data | any | `-srgbi -srgbo` | values untouched |

Rules in `texcomb/core/dds_match.py`:

- `source_color_space()`: DDS from its DXGI format; PNG/JPEG/BMP/TGA are sRGB.
- `colour_flags()`: AUTO by default; `DATA_ROLE_TOKENS` (normal, mask, roughness, metallic,
  occlusion, specular, gloss, smoothness, height, displacement, materialmap, aomap) mean data.
- `run_conversion_plan()` emits both flags only when the spaces are equal or the row is data;
  otherwise exactly `-srgbi` or `-srgbo`. `ConversionPlan` carries the decision and
  `ConversionCache` keys it (bump `CACHE_VERSION` when the flags change).
- The row has a `Color Space` override (`AUTO/SRGB/LINEAR/DATA`) for a DDS whose editor dropped
  the sRGB tag; the node status shows the treatment, e.g. `Needs conversion to BC6H_UF16
  (sRGB -> linear)`.

## Regenerating keeps the newer file

`M_IniHelper._refresh_generated_texture()` is the one rule for every generated texture: the
automatic Slot / Hash / SharedSlot copies, the global hash rows and the per-object replacement
images all go through it.

- identical bytes: nothing is touched (a repeated export stays free);
- target missing: copy;
- **target newer than its source: keep it** and print `kept the generated texture you edited by
  hand`, because artists re-save the generated DDS from Photoshop/NVTT to fix a colour and the
  next export used to restore the capture over that fix;
- otherwise (source edited, workspace re-extracted): copy.

The copy carries the source timestamp (`os.utime`), so "newer" stays meaningful across exports.
A converted replacement passes `source_stamp_path` = the picture the user picked, never the
temporary conversion product (whose time is when texconv ran).

Two earlier rules were each wrong for somebody: "target exists -> skip" kept yesterday's picture
after a re-extract, and "always copy when the bytes differ" (1.0.66) overwrote a hand-corrected
texture on the next export. Do not go back to either.

## Mark identity is a string, not an enum index

Blender persists a dynamic `EnumProperty` as an **integer index**. The mark dropdown is rebuilt
from the Submesh JSON, so re-extracting, re-marking or switching the active workspace silently
rebound rows to another mark (exactly "the generated texture is not the one I specified").
`MIMITextureSlotItem` / `MIMITextureHashItem` now store `mark_name_value` (the identifier) and
`mark_name_of(item)` is the only reader; the enum is just the picker and its update callback
writes the string. Old rows migrate on first read. Never read `item.mark_name` directly again.

## Verification

```
python tools/test_texture_bind_ini.py                 # resolver, aliases, switch states
python tools/test_hash_texture_bind_ini.py            # hash rows, shared slot copy
python tools/test_texture_format_color_space.py       # real texconv colour matrix (no Blender)
python tools/test_texture_format_conversion.py        # exact-format end-to-end (needs Pillow)
python tools/check_i18n.py                            # every tr() msgid has a zh_CN entry
python tools/run_blueprint_checks.py <blender.exe>     # real Blender suites
```

A headless export of a user blend is the fastest end-to-end check: point
`scene.mimi_global_properties` at a `CUSTOM` workspace, set `generate_mod_folder_path` to a temp
folder, call `ui_func_export.generate_mod_from_output_node`, then decode the produced
`Textures/*.dds` with the bundled texconv and compare the values with the source image.

`tools/test_blueprint_blender.py::test_wwmi_connected_hash_file_export` fails on a clean
checkout too (its `WWMIInfoHelper` stub has no `shapekeys`); do not read that as a regression
of a texture change.
