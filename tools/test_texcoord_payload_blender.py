"""Real import/export test for a game payload that used to sit in one wide TEXCOORD.

Run with Blender --background --factory-startup --python-exit-code 1 --python.

Why this test exists:
PGR's cdd6cefa draw call declares the last channel of its 36-byte vb1 record as
R32G32B32_FLOAT, but the 12 bytes are not a uv (they hold a game payload). A
Blender uv layer can only carry two components, so the data type describes the
same bytes as two ordinary channels instead:

    TEXCOORD3 R32G32_FLOAT (8 bytes, offset 24)
    TEXCOORD4 R16G16_FLOAT (4 bytes, offset 32)

The captured buffer never changes; only the SubmeshJson element list does. This
test pins that arrangement end to end, and pins the diagnostic a stale workspace
(old 12-byte element) now produces instead of a bare "Unhandled dimension".

Only the fixture is synthetic; import and export run production code.
"""

import importlib
import json
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path

import bpy
import numpy as np

# Register the checkout in a disposable Blender process, never a user's scene.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
importlib.import_module(ROOT.name).register()

from MIMIBlender.common.d3d11_gametype import D3D11GameType
from MIMIBlender.common.global_config import GlobalConfig, LogicName
from MIMIBlender.common.mmt_import_helper import MMTImportHelper
from MIMIBlender.utils.export_utils import ExportUtils
from MIMIBlender.utils.mmt_error_utils import Fatal

# Frozen record layout of the real capture:
# Position = POSITION(12) + NORMAL(12) + TANGENT(16) = 40 bytes
# Texcoord = four R32G32 uv sets (32) + one R16G16 pair (4) = 36 bytes
# Blend    = BLENDWEIGHTS(16) + BLENDINDICES(16) = 32 bytes
POSITION_STRIDE = 40
TEXCOORD_STRIDE = 36
BLEND_STRIDE = 32
VERTEX_COUNT = 6

# Two triangles over six distinct vertices; the exporter only needs a valid IB.
INDICES = [0, 1, 2, 3, 4, 5]

# The last channel of the real record decodes to a biased unit direction. The
# fixture keeps ordinary half values so an unedited channel must round-trip
# exactly; arbitrary bit patterns are discussed in the report instead.
LAST_CHANNEL_HALVES = [(1.5, -0.25), (0.75, 0.5), (-1.0, 0.125),
                       (1.25, -0.5), (0.5, 0.25), (-0.75, -0.125)]

SPLIT_GAME_TYPE_NAME = "GPU_P12_N12_TA16_BW16_BI16_T8_T1-8_T2-8_T3-8_T4-4_"
LEGACY_GAME_TYPE_NAME = "GPU_P12_N12_TA16_BW16_BI16_T8_T1-8_T2-8_T3-12_"


def element(semantic, index, fmt, byte_width, category, slot, technique="pointlist"):
    """One D3D11Element entry exactly as the SubmeshJson stores it."""
    return {
        "SemanticName": semantic,
        "SemanticIndex": str(index),
        "Format": fmt,
        "ByteWidth": str(byte_width),
        "ExtractSlot": slot,
        "ExtractTechnique": technique,
        "Category": category,
        "DrawCategory": category,
    }


def build_position_bytes():
    """Six vertices of float32 Position data (positions, normals, tangents)."""
    rows = []
    for index in range(VERTEX_COUNT):
        # A flat strip on the XY plane so the tangents are well defined.
        position = (float(index), 0.0, 0.0)
        normal = (0.0, 0.0, 1.0)
        tangent = (1.0, 0.0, 0.0, 1.0)
        rows.append(struct.pack("<10f", *(position + normal + tangent)))
    return b"".join(rows)


def build_texcoord_bytes():
    """Six vertices of the 36-byte record: four float pairs plus half pair."""
    rows = []
    for index in range(VERTEX_COUNT):
        texcoord = (index * 0.1, 0.25)
        texcoord1 = (index * 0.1, 0.5)
        texcoord2 = (index * 0.1, 0.75)
        texcoord3 = (index * 0.1, 1.0)
        rows.append(
            struct.pack("<8f", *(texcoord + texcoord1 + texcoord2 + texcoord3))
            + struct.pack("<2e", *LAST_CHANNEL_HALVES[index])
        )
    return b"".join(rows)


def build_blend_bytes():
    """Six vertices of blend weights and indices, four influences each."""
    rows = []
    for index in range(VERTEX_COUNT):
        weights = (1.0, 0.0, 0.0, 0.0)
        indices = (0, 0, 0, 0)
        rows.append(struct.pack("<4f", *weights) + struct.pack("<4I", *indices))
    return b"".join(rows)


def build_submesh_json(game_type_name, texcoord_elements):
    """The SubmeshJson that describes the synthetic files below."""
    return {
        "GamePreset": "PGR",
        "VertexLimitVB": "4ccff098",
        "CategoryHash": {"Position": "5c399c2d", "Texcoord": "7c288730", "Blend": "b58c9606"},
        "CategoryDrawCategoryMap": {"Position": "Position", "Texcoord": "Texcoord", "Blend": "Blend"},
        "WorkGameType": game_type_name,
        "GPU-PreSkinning": True,
        "CB4Hash": "",
        "VertexOffset": 0,
        "VertexCount": 0,
        "IndexOffset": 0,
        "IndexCount": 0,
        "VGCount": 0,
        "VGOffset": 0,
        "ShapeKeysInfo": {
            "offsets_hash": "",
            "scale_hash": "",
            "vertex_ids_hash": "",
            "vertex_offsets_hash": "",
            "vertex_count": 0,
            "dispatch_y": 0,
            "checksum": 0,
            "shapekey_count": 0,
            "buffer_layout": "",
            "batches": [],
        },
        "IndexBufferList": [{"DXGI_FORMAT": "DXGI_FORMAT_R32_UINT", "FileName": "test-0.ib"}],
        "CategoryBufferList": [
            {
                "FileName": "test-0-Position.buf",
                "Type": "Normal",
                "D3D11ElementList": [
                    element("POSITION", 0, "R32G32B32_FLOAT", 12, "Position", "cs-t0"),
                    element("NORMAL", 0, "R32G32B32_FLOAT", 12, "Position", "cs-t0"),
                    element("TANGENT", 0, "R32G32B32A32_FLOAT", 16, "Position", "cs-t0"),
                ],
            },
            {
                "FileName": "test-0-Blend.buf",
                "Type": "Normal",
                "D3D11ElementList": [
                    element("BLENDWEIGHTS", 0, "R32G32B32A32_FLOAT", 16, "Blend", "cs-t1"),
                    element("BLENDINDICES", 0, "R32G32B32A32_UINT", 16, "Blend", "cs-t1"),
                ],
            },
            {
                "FileName": "test-0-Texcoord.buf",
                "Type": "Normal",
                "D3D11ElementList": texcoord_elements,
            },
        ],
    }


def split_texcoord_elements():
    """The current arrangement: every channel is a normal two-component uv."""
    return [
        element("TEXCOORD", 0, "R32G32_FLOAT", 8, "Texcoord", "vb1", "trianglelist"),
        element("TEXCOORD", 1, "R32G32_FLOAT", 8, "Texcoord", "vb1", "trianglelist"),
        element("TEXCOORD", 2, "R32G32_FLOAT", 8, "Texcoord", "vb1", "trianglelist"),
        element("TEXCOORD", 3, "R32G32_FLOAT", 8, "Texcoord", "vb1", "trianglelist"),
        element("TEXCOORD", 4, "R16G16_FLOAT", 4, "Texcoord", "vb1", "trianglelist"),
    ]


def legacy_texcoord_elements():
    """The outdated arrangement that stored all 12 bytes in one element."""
    return [
        element("TEXCOORD", 0, "R32G32_FLOAT", 8, "Texcoord", "vb1", "trianglelist"),
        element("TEXCOORD", 1, "R32G32_FLOAT", 8, "Texcoord", "vb1", "trianglelist"),
        element("TEXCOORD", 2, "R32G32_FLOAT", 8, "Texcoord", "vb1", "trianglelist"),
        element("TEXCOORD", 3, "R32G32B32_FLOAT", 12, "Texcoord", "vb1", "trianglelist"),
    ]


def write_fixture(folder: str, game_type_name: str, texcoord_elements: list) -> str:
    """Write the buffers and the SubmeshJson; return the json path."""
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "test-0-Position.buf"), "wb") as position_file:
        position_file.write(build_position_bytes())
    with open(os.path.join(folder, "test-0-Texcoord.buf"), "wb") as texcoord_file:
        texcoord_file.write(build_texcoord_bytes())
    with open(os.path.join(folder, "test-0-Blend.buf"), "wb") as blend_file:
        blend_file.write(build_blend_bytes())
    with open(os.path.join(folder, "test-0.ib"), "wb") as index_file:
        index_file.write(b"".join(struct.pack("<I", value) for value in INDICES))

    json_path = os.path.join(folder, "test-0.json")
    with open(json_path, "w", encoding="utf-8") as json_file:
        json.dump(build_submesh_json(game_type_name, texcoord_elements), json_file, indent=2)
    return json_path


def as_rows(value, stride):
    """Turn an exported category buffer into fixed-width byte rows."""
    if isinstance(value, bytes):
        raw = np.frombuffer(value, dtype=np.uint8)
    else:
        raw = np.asarray(value, dtype=np.uint8).ravel()
    return raw.reshape(-1, stride), raw


def clear_scene():
    """Start every test from an empty scene so objects never accumulate."""
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)


class TexcoordPayloadTests(unittest.TestCase):
    def setUp(self):
        clear_scene()
        # The add-on resolves its cache and game preset through GlobalConfig;
        # point them at a scratch folder instead of a real install.
        self.work_folder = tempfile.mkdtemp(prefix="texcoord_payload_", dir=str(ROOT / "tmp"))
        GlobalConfig.cache_location = self.work_folder + os.sep
        GlobalConfig.gamename = "PGR"
        GlobalConfig.workspacename = "Default"
        GlobalConfig.logic_name = LogicName.PGR
        GlobalConfig.current_game_migoto_folder = self.work_folder

    def import_fixture(self, game_type_name, texcoord_elements, folder_name):
        """Write one fixture and import it with the production importer."""
        json_path = write_fixture(
            os.path.join(self.work_folder, folder_name), game_type_name, texcoord_elements
        )
        with open(json_path, "r", encoding="utf-8") as json_file:
            json_dict = json.load(json_file)
        obj = MMTImportHelper.create_mesh_from_json(
            json_file_path=json_path,
            import_collection=bpy.context.scene.collection,
        )
        return obj, json_dict, json_path

    def test_split_record_imports_and_exports_without_losing_bytes(self):
        # The current data type: four float pairs and one half pair.
        obj, json_dict, json_path = self.import_fixture(
            SPLIT_GAME_TYPE_NAME, split_texcoord_elements(), "split"
        )
        self.assertIsNotNone(obj)
        self.assertEqual(len(obj.data.vertices), VERTEX_COUNT)

        # Every channel becomes an ordinary uv layer; no custom payload channel
        # is involved, which is the whole point of the data-type split.
        uv_names = [layer.name for layer in obj.data.uv_layers]
        for index in range(5):
            expected = "TEXCOORD{}.xy".format(index if index else "")
            self.assertIn(expected, uv_names)
        self.assertEqual(
            [name for name in uv_names if name.startswith("TEXCOORD")],
            ["TEXCOORD.xy", "TEXCOORD1.xy", "TEXCOORD2.xy", "TEXCOORD3.xy", "TEXCOORD4.xy"],
        )
        self.assertEqual(
            [attribute.name for attribute in obj.data.attributes
             if attribute.name.startswith("3DMigoto:Raw")],
            [],
            "the split data type must not need a raw payload channel",
        )

        game_type = D3D11GameType.from_submesh_json_dict(json_dict, json_path)
        result = ExportUtils.build_unity_obj_buffer_result(obj=obj, d3d11_game_type=game_type)
        texcoord_rows, texcoord_raw = as_rows(result.category_buffer_dict["Texcoord"], TEXCOORD_STRIDE)

        # The exported record still has the captured width, so no following
        # element can shift; a truncated channel would break this immediately.
        self.assertEqual(texcoord_raw.size % TEXCOORD_STRIDE, 0)
        self.assertGreater(len(texcoord_rows), 0)

        # Both halves of the split channel keep their values. The add-on flips
        # V on the way in and back on the way out, so ordinary half values must
        # survive exactly (the fixture uses no NaN/denormal bit patterns).
        source_rows = np.frombuffer(build_texcoord_bytes(), dtype=np.uint8).reshape(-1, TEXCOORD_STRIDE)
        source_half_pairs = {row[32:36].tobytes() for row in source_rows}
        exported_half_pairs = {row[32:36].tobytes() for row in texcoord_rows}
        self.assertEqual(exported_half_pairs, source_half_pairs)
        # The fourth float pair carries the value that shares those bytes in the
        # capture; it is a normal uv and must survive as well.
        source_fourth_pairs = {row[24:32].tobytes() for row in source_rows}
        exported_fourth_pairs = {row[24:32].tobytes() for row in texcoord_rows}
        self.assertEqual(exported_fourth_pairs, source_fourth_pairs)

    def test_legacy_wide_element_reports_an_actionable_error(self):
        # An old workspace still declares one 12-byte element. It cannot be
        # carried by a uv layer, so the import must say what to do instead of
        # failing with a bare dimension number.
        json_path = write_fixture(
            os.path.join(self.work_folder, "legacy"),
            LEGACY_GAME_TYPE_NAME,
            legacy_texcoord_elements(),
        )
        with self.assertRaises(Fatal) as raised:
            MMTImportHelper.create_mesh_from_json(
                json_file_path=json_path,
                import_collection=bpy.context.scene.collection,
            )
        message = str(raised.exception)
        self.assertIn("TEXCOORD has 3 components", message)
        self.assertIn("re-extract", message)


if __name__ == "__main__":
    # A failed suite must reach the shell: Blender reports the exit code.
    unittest.main(argv=[sys.argv[0]], exit=True)
