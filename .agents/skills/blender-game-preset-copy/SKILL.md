---
name: blender-game-preset-copy
description: Add a game preset to the MIMIBlender add-on whose mod generation logic is an independent copy of a sibling preset (the PGR-from-Naraka copy). Covers LogicName, the games/<abbr> package, the exporter registry, the import/export axis gates, and the tests that prove nothing leaked between the two presets.
---

# Add a copied game preset to the Blender add-on

Use this when the host (MMT) already extracts a new game and the user asks for
the export side: "copy Naraka's mod generation logic over, but do not inherit,
because we may need to change it independently".

PGR (Punishing: Gray Raven) was added this way from Naraka: both are Unity
titles whose skinning runs on the GPU through a compute shader, so the
generated INI layout is identical today. The copy exists so the two can
diverge later. **Copy, rename, register — never alias and never subclass.**

## 1. Copy the two Naraka files

| Naraka | PGR copy | Rename |
| --- | --- | --- |
| `games/naraka/exporter.py` | `games/pgr/exporter.py` | `Exporter` → `PGRExporter`, `add_naraka_*` → `add_pgr_*` |
| `games/naraka/shapekeys.py` | `games/pgr/shapekeys.py` | `add_naraka_shapekey_ini_sections` → `add_pgr_shapekey_ini_sections`, `CustomShaderComputeShapesNaraka` → `CustomShaderComputeShapesPGR` |
| `games/naraka/__init__.py` | `games/pgr/__init__.py` | write a short package docstring |

- Keep the "deliberate copy, apply a fix twice" paragraph in both docstrings.
- Inside the copied code the only place allowed to name Naraka is the docstring
  and inline provenance comments; identifiers, error strings and INI strings
  must be re-branded, otherwise a PGR user reads a Naraka error.
- Do **not** copy `games/naraka/nodes.py` or `games/naraka/cross_ib.py`.
  Blueprint node classes register globally by `bl_idname` (`__init__.py`
  yields `blueprint_node_naraka.register`), and the tree post-processor is
  selected in `games/__init__.get_tree_post_processor`, both per game. The
  cross-IB *sections* inside the exporter stay inert until a PGR node exists.
- Do not copy `resources/Shapes.hlsl`; it is a shared asset addressed by the
  shape key module through the addon root.

## 2. Register the preset

- `common/global_config.py`: add the code to `LogicName` with a comment naming
  the engine shape it copies. The constant **must equal** the host's
  `gamePreset` string and the `GamePreset` written into every `SubMeshJson` —
  the add-on reads it from `Games/<game>/Config.json` for export and from
  `SubMeshJson.GamePreset` for import.
- `games/__init__.py`: import the class and add a `_LOGIC_EXPORTER_DICT` entry
  with the "own copy, never point this back" comment.

## 3. Three gates a GPU-pre-skinning preset also needs

A registered exporter alone exports a rotated or rejected mod. Add the preset:

1. `model/drawib_model.py` → `supported_preskinning_logics`
   (Position.buf Based Dynamic Mod; the copied pipeline re-reads `cs-t0`).
2. `model/submesh_model.py` → `_apply_export_rotation_for_logic`
   (which rotation the exported buffer needs).
3. `common/mesh_create_helper.py` → the import rotation branch
   (which presets cancel the Y-up→Z-up conversion).

## 4. Decide the axis from a real dump, never by guessing

`MeshCreateHelper.set_import_coordinate` sets `R_x(+90)` on every imported
object; assigning `rotation_euler = 0` afterwards **overwrites** that rotation,
which is how the Z-up presets keep raw game space. So the import branch and the
export rotation branch are a pair.

Measure the extracted Position buffer instead of trusting the engine name:

```python
# tmp/axis_check.py -- run with the bundled python (numpy)
import json, os, sys, numpy as np
json_path = sys.argv[1]
data = json.load(open(json_path, encoding="utf-8"))
folder = os.path.dirname(json_path)
for entry in data["CategoryBufferList"]:
    stride = sum(int(e["ByteWidth"]) for e in entry["D3D11ElementList"])
    names = [e["SemanticName"] for e in entry["D3D11ElementList"]]
    if "POSITION" not in names:            # Position category only
        continue
    raw = np.fromfile(os.path.join(folder, entry["FileName"]), dtype=np.float32)
    pos = raw.reshape(-1, stride // 4)[:, 0:3]
    print(entry["FileName"], "extent", pos.max(0) - pos.min(0), "min", pos.min(0))
```

A standing character is much taller on the up axis with its feet at 0.

- Z-up (PGR extent `[0.99, 0.26, 1.45]`, min z ≈ 0; Naraka the same): cancel
  the import conversion (same branch as `is_zzmi_family`/Naraka) and export
  with no rotation (same branch as `EFMI`/Naraka).
- Y-up (GIMI/HIMI/SRMI/GF2): leave the import alone and add the preset to the
  `-90` degree X export branch.

## 5. Verify

```bash
python tools/test_pgr_preset.py          # registry, independence, INI, sections
python tools/test_mod_generation_guard.py # every preset reaches the export flow
python tools/test_mod_output_detection.py # real INI path validation
python tools/test_naraka_shapekeys.py    # the sibling did not regress
python tools/check_imports.py            # only tmp/ noise may remain
```

`tools/test_pgr_preset.py` is the template for the next copy: it executes the
real `LogicName` class and the real `_LOGIC_EXPORTER_DICT` with `ast` (no bpy),
reuses the stub harness of `test_naraka_shapekeys.py`, drives the real
`PGRExporter` over fake DrawIB/Submesh models, and asserts the generated INI
never contains the sibling's name.

Optional one-off proof that the copy is still faithful: render the same fake
models through both exporters, normalise the command list name, and diff. Do
not turn that into a test — the presets are supposed to diverge.

## Pitfalls

- Never import `..naraka.*` from the copied exporter; the registry entry is the
  only link, and it must point at the copy.
- Keep `get_compute_command_list_name` distinct per preset. Both mods can live
  in one `Mods` folder and their INIs are reviewed side by side.
- A test fixture that executes `ui/ui_func_export.py` needs
  `bpy.types.Operator` **and** a distinct `I18nOperator`: the WWMI report
  operators inherit both, and Python rejects the same class in both positions.
- The add-on reads `logic_name` from the host config; nothing in the UI selects
  a preset, so no EnumProperty or i18n entry is needed for a new game.
- Keep each file's existing line endings; the tree mixes LF and CRLF and
  `core.autocrlf=true` normalises the index.
