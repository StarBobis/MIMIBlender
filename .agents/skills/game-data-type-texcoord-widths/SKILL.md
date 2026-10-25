---
name: game-data-type-texcoord-widths
description: Diagnose and fix a game preset whose TEXCOORD element width the Blender add-on cannot carry (the "no models were imported" workspace import, or a mod build that dies with "could not broadcast input array from shape (N,2) into shape (N,4)"), by splitting the data type into ordinary two-component channels instead of adding a custom byte channel. Covers the PGR R32G32B32 -> R32G32 + R16G16 split, the R32G32B32A32 -> two R32G32 split, the extractor matching rule, and the measured fidelity.
---

# TEXCOORD widths the Blender add-on can carry

## Symptom: the import refuses the workspace

One-click workspace import ends with "No models were successfully imported
from the current workspace" (当前工作空间中没有成功导入任何模型), while the
folder probe in the UI says the directory is importable. The reverse/import
panel's own warning does not name the offending element: each DrawIB is imported
inside a `try/except` that only prints to the console.

The console shows the real cause:

```
TEXCOORD has 3 components, which a Blender uv layer cannot hold.
This workspace was extracted with an outdated data type; re-extract the model ...
```

## Symptom: the mod build refuses a four-component element

A **four**-component element (`R32G32B32A32_FLOAT`) imports fine — the add-on
creates `<name>.xy` and `<name>.zw` — but the export cannot pack it back.
`ObjBufferHelper._parse_texcoord` reads the two layers one at a time and keeps the
last one (2 columns), while the structured record declares 4:

```
ValueError: could not broadcast input array from shape (16464,2) into shape (16464,4)
  File "common/obj_buffer_helper.py", line 735, in convert_to_element_vertex_ndarray
```

The first dimension is the mesh's loop count, the second is the declared element
width. Nothing the user did caused it: an unmodified import/export reproduces it.
The fix is the same as below — split the 16 bytes into two `R32G32_FLOAT` elements
in the data type (this renumbers the uv channels behind the split, so the type name
changes too). Measured on PGR's 52-byte record (5188 v, 16464 loops): 5 uv layers,
the exported 8 floats match the capture within `3e-8` (the usual V-flip rounding),
and only the trailing `R16G16` half pair is canonicalized where the capture holds
NaN.

## Why it cannot work in the add-on

- A Blender uv layer is always **two components**. `MeshCreateHelper.import_uv_layers`
  only supports 2 (`xy`) and 4 (`xy` + `zw`), and the exporter reads exactly one
  layer per element, so a 4-component element exports 2 columns into 4.
- The export writes exactly the width the data type declares
  (`D3D11GameType.get_total_structured_dtype()`), so importing 8 bytes for a
  12-byte element would shift every following element of the vertex.
- Therefore the width has to be fixed **in the data type**, not patched with a
  custom byte attribute in the add-on. The project rule is: do not invent a
  custom payload channel for a game channel that the uv path can describe. The
  same rule applies to widening the exporter: keep every TEXCOORD element
  two-component instead.

## The fix (PGR, verified on the real capture)

PGR's `cdd6cefa` vb1 record is 36 bytes and the game declares its last channel as
`TEXCOORD3 R32G32B32_FLOAT` (12 bytes at offset 24). Its payload is *not* a uv
value (it decodes to a biased unit direction: `v = 2x - 1` has length 1 for all
3697 vertices, 42% exactly `(0,0,1)`), so its values are meant to be ignored.

Describe the same 12 bytes as two ordinary channels:

| offset | before | after |
| --- | --- | --- |
| 24 | TEXCOORD3 R32G32B32_FLOAT (12) | TEXCOORD3 R32G32_FLOAT (8) |
| 32 | — | TEXCOORD4 R16G16_FLOAT (4) |

`R16G16_FLOAT` is the only four-byte format that is two components and survives
the uv conversion path unchanged (`_parse_texcoord` casts it back to float16).

Where:

1. `src-tauri/crates/mmt-gametype/src/gametype/type_pgr.rs` — every GPU type with
   a 12-byte texcoord (five of them), plus their names:
   `..._T3-12_` → `..._T3-8_T4-4_`, `..._T1-12_` → `..._T1-8_T2-4_`.
2. `src-tauri/crates/mmt-extract/src/extract_new/pgr.rs` — the ignored tests that
   pin the matched type name and the expected element list.

The capture bytes never change: the extractor copies the whole category buffer,
so this is a metadata-only change. `declared_layout_matches` accepts extra
candidate elements as long as every declared semantic sits at its declared
offset, so splitting at the same start offset keeps capture matching intact.

## Verify

```bash
cd src-tauri
cargo test -p mmt-gametype --lib
cargo test -p mmt-extract --lib
# real capture: matching, extraction, and "one type per DrawIB"
$env:SSMT_PGR_FRAME_ANALYSIS_CDD6CEFA = "<FrameAnalysis dir>"
cargo test -p mmt-extract --lib pgr_ -- --ignored --nocapture --test-threads 1
```

Then import the freshly extracted workspace in a headless Blender. This probe
prints the only facts that matter (uv layer count, exported row width):

```python
import bpy, sys, json, os
sys.path.insert(0, r"D:\Dev")
import MIMIBlender
from MIMIBlender.common.global_config import GlobalConfig, LogicName
from MIMIBlender.common.mimi_global_properties import register
from MIMIBlender.common.d3d11_gametype import D3D11GameType
from MIMIBlender.common.mmt_import_helper import MMTImportHelper
from MIMIBlender.utils.export_utils import ExportUtils
register()
GlobalConfig.logic_name = LogicName.PGR
GlobalConfig.cache_location = r"D:\MMTCacheFolder" + "\\"
GlobalConfig.gamename, GlobalConfig.workspacename = "PGR", "Default"
json_path = "<...>\\cdd6cefa-14568-0.json"
json_dict = json.load(open(json_path, encoding="utf-8"))
obj = MMTImportHelper.create_mesh_from_json(json_path, bpy.context.scene.collection)
print([layer.name for layer in obj.data.uv_layers])
game_type = D3D11GameType.from_submesh_json_dict(json_dict, json_path)
result = ExportUtils.build_unity_obj_buffer_result(obj=obj, d3d11_game_type=game_type)
print(len(result.category_buffer_dict["Texcoord"]), "texcoord bytes")
```

`tools/test_texcoord_payload_blender.py` is the committed regression test: it
builds a two-triangle fixture with the split record, imports it, exports it, and
asserts the 36-byte row width plus exact float-pair/half-pair survival; it also
asserts the old 12-byte arrangement produces the actionable error.

## Measured fidelity (real PGR mesh, 3697 vertices)

- Positions: byte-identical sets to the capture (PGR keeps raw game space).
- The four float pairs: max distance to the nearest source row `3e-8` (the uv
  V-flip rounds the last bit, exactly like every other uv channel in the add-on).
- The extra 4 bytes: 998 of 1048 distinct bit patterns survive exactly; the 66
  records whose half pattern is NaN are canonicalized by the float16 cast. That
  is acceptable **only** because the value is a game payload the mod does not
  edit; never treat it as a uv.

## Pitfalls

- Do split a **four**-component TEXCOORD as well: it imports (`xy` + `zw`) but
  never round-trips, because the exporter hands two columns to a four-column
  field. Two `R32G32_FLOAT` elements keep the same 16 bytes at the same offset
  and only renumber the channels behind them.
- Keep element offsets contiguous; a gap would change the category stride.
- The type name encodes widths, so rename it. Existing workspaces keep the old
  folder name and now fail with the actionable message — that is intended, and
  the user re-extracts.
- Re-extracting into an existing workspace leaves the old `TYPE_*` folder next to
  the new one; move it to `tmp/recycle/` before measuring, or the probe may read
  the stale type.
- Never "fix" this by widening the importer: a byte-for-byte custom channel only
  moves the problem into the export path and was explicitly rejected.
