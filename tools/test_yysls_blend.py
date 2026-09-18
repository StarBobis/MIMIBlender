"""Blender regression tests for YYSLS EXT8 and ordinary four-weight meshes.

Run with Blender --background --factory-startup --python-exit-code 1 --python
this_file, optionally followed by -- --face-json <corrected extraction JSON>.
The real importer, weight gatherer, quantizer and buffer exporter are exercised.
Only material discovery is disabled: no game installation or GUI is required.
Synthetic tests cover editing weights, influence truncation, empty rows, gaps,
and duplicate bones across the two sets. The optional capture test compares
bone-weight maps after the real vertex splitting and index renumbering path.
It does not claim to validate the running game's shader or facial animation.

The comparison deliberately distinguishes three kinds of identity:
- Native category bytes must survive extraction without reinterpretation.
- Bone contributions must survive Blender import and export per vertex.
- Exported vertex numbers may change when corner attributes split vertices.
The last case is expected and is checked through the real exporter's loop map.
Zero-weight bone indices are ignored because they cannot affect skinning.
Duplicate bone indices are accumulated before comparing contributions.
A one-byte tolerance is allowed for float storage, but the captured face has
also been observed to round-trip with exactly zero bone-weight byte error.
The synthetic four-weight and WWMI tests guard the compatibility boundary.
They assert that the new EXT8 helper is not called by those older paths.
The settings registration belongs only to this disposable Blender process.
No installed addon files, saved scenes or live Mod files are modified.
"""

import argparse
import json
from pathlib import Path
import sys
import types
from unittest.mock import patch

import bpy
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
package = types.ModuleType("yysls_blend_test")
package.__path__ = [str(ROOT)]
sys.modules[package.__name__] = package

from yysls_blend_test.common.d3d11_gametype import D3D11GameType
from yysls_blend_test.common.global_config import GlobalConfig, LogicName
from yysls_blend_test.common.mesh_create_helper import MeshCreateHelper
from yysls_blend_test.common.mimi_global_properties import MIMIGlobalProperties
from yysls_blend_test.common.mmt_import_helper import MMTImportHelper
from yysls_blend_test.common.obj_buffer_helper import ObjBufferHelper
from yysls_blend_test.common.raw_vertex_attributes import store_raw_bytes
from yysls_blend_test.utils.export_utils import ExportUtils
from yysls_blend_test.utils.vertexgroup_utils import VertexGroupUtils
from yysls_blend_test.utils.yysls_blend import pack_extended_blend


def blend_type(sets=2, padding=False):
    elements = []
    for index in range(sets):
        for name, fmt in (("BLENDWEIGHT", "R8G8B8A8_UNORM"),
                          ("BLENDINDICES", "R8G8B8A8_UINT")):
            elements.append(dict(SemanticName=name, SemanticIndex=str(index),
                                 Format=fmt, ByteWidth="4", ExtractSlot="vb2",
                                 Category="Blend", DrawCategory="Blend"))
    if padding:
        elements.append(dict(SemanticName="RAWDATA", SemanticIndex="0", Format="R8_UINT",
                             ByteWidth="3", ExtractSlot="vb2", Category="Blend", DrawCategory="Blend"))
    return D3D11GameType.from_submesh_json_dict({
        "WorkGameType": "synthetic_ext8", "CategoryBufferList": [{"D3D11ElementList": elements}]})


def triangle(weights=None):
    mesh = bpy.data.meshes.new("yysls_test_mesh")
    mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
    obj = bpy.data.objects.new("yysls_test", mesh)
    bpy.context.scene.collection.objects.link(obj)
    if weights is not None:
        for group in range(max(map(len, weights))):
            vg = obj.vertex_groups.new(name=str(group))
            for vertex, row in enumerate(weights):
                if group < len(row) and row[group] > 0:
                    vg.add([vertex], row[group], 'REPLACE')
    return obj


def test_joint_quantization_and_editing():
    # Include more than eight groups so the dropped influences cannot remain
    # in the normalization denominator. Vertex 0 also exercises an empty half.
    obj = triangle([[0.5, 0.3, 0.2], [0.4, 0.2, 0.1, 0.1, 0.08, 0.06, 0.04, 0.02],
                    [0.1] * 10])
    gt = blend_type()
    result = ObjBufferHelper.parse_elementname_data_dict(obj.data, gt)
    wide = np.concatenate([result["BLENDWEIGHT"], result["BLENDWEIGHT1"]], axis=1)
    assert np.all(wide.sum(axis=1) == 255), wide
    assert wide[0, 4:].sum() == 0
    assert 0 < wide[1, 4:].sum() < 255
    assert np.count_nonzero(wide[2]) == 8
    # Repainting a secondary bone must affect the exported second-set data.
    obj.vertex_groups[7].add([1], 0.3, 'REPLACE')
    changed = ObjBufferHelper.parse_elementname_data_dict(obj.data, gt)
    assert not np.array_equal(changed["BLENDWEIGHT1"], result["BLENDWEIGHT1"])
    print("PASS: joint EXT8 quantization, top-eight limit and edited weights")


def test_small_and_empty_meshes():
    # A whole mesh with fewer than four influences still writes both sets.
    obj = triangle([[1], [1], [1]])
    weights, indices = pack_extended_blend(obj.data, blend_type())
    assert weights[1].shape == (3, 4) and not weights[1].any()
    assert indices[1].shape == (3, 4) and not indices[1].any()
    empty = triangle()
    weights, _ = pack_extended_blend(empty.data, blend_type())
    assert not weights[0].any() and not weights[1].any()
    print("PASS: implicit zero extension and unweighted rows")


def test_duplicate_import_and_padding():
    obj = triangle()
    ids = {0: np.array([[4, 5, 0, 0]] * 3), 1: np.array([[4, 6, 0, 0]] * 3)}
    weights = {0: np.array([[0.5, 0.125, 0, 0]] * 3), 1: np.array([[0.25, 0.125, 0, 0]] * 3)}
    MeshCreateHelper.import_vertex_groups(obj.data, obj, ids, weights, None, merge_duplicate_weights=True)
    assert abs(obj.vertex_groups[4].weight(0) - 0.75) < 1e-6
    raw = np.array([[1, 128, 255], [7, 8, 9], [3, 2, 1]], dtype=np.uint8)
    store_raw_bytes(obj.data, "3DMigoto:YYSLS:RAWDATA", raw, 3)
    parsed = ObjBufferHelper.parse_elementname_data_dict(obj.data, blend_type(padding=True))
    np.testing.assert_array_equal(parsed["RAWDATA"], raw)
    print("PASS: repeated bones accumulate; non-word-aligned padding survives")


def test_legacy_four_weight_path():
    # The old gatherer and per-element packer are the compatibility oracle.
    # A spy also prevents accidentally routing old meshes through EXT8 later.
    obj = triangle([[0.6, 0.3, 0.1], [0.4, 0.3, 0.2, 0.1], [1]])
    gt = blend_type(sets=1)
    weights, _ = VertexGroupUtils.get_blendweights_blendindices_v3(obj.data, normalize_weights=True)
    expected = ObjBufferHelper._parse_blendweight(weights, gt.ElementNameD3D11ElementDict["BLENDWEIGHT"])
    with patch("yysls_blend_test.common.obj_buffer_helper.pack_extended_blend") as extended:
        result = ObjBufferHelper.parse_elementname_data_dict(obj.data, gt)
        extended.assert_not_called()
    np.testing.assert_array_equal(result["BLENDWEIGHT"], expected)
    print("PASS: ordinary four-weight YYSLS follows the unchanged path")


def test_wwmi_path_unchanged():
    # WWMI packs eight contiguous weights/indices, unlike YYSLS's interleaving.
    # Reusing its gatherer must not change this established physical layout.
    gt = blend_type(sets=1)
    for element in gt.D3D11ElementList:
        element.ByteWidth = 8
        element.Format = "R8_UNORM" if element.SemanticName == "BLENDWEIGHT" else "R8_UINT"
    obj = triangle([[0.125] * 8] * 3)
    GlobalConfig.logic_name = LogicName.WWMI
    try:
        with patch("yysls_blend_test.common.obj_buffer_helper.pack_extended_blend") as extended:
            result = ObjBufferHelper.parse_elementname_data_dict(obj.data, gt)
            extended.assert_not_called()
        assert result["BLENDWEIGHT"].shape == (3, 8)
        assert np.all(result["BLENDWEIGHT"].sum(axis=1) == 255)
        assert result["BLENDINDICES"].shape == (3, 8)
    finally:
        GlobalConfig.logic_name = LogicName.YYSLS
    print("PASS: existing WWMI eight-influence path is unchanged")


def bone_map(row):
    # Influence order and zero-weight indices have no skinning meaning.
    # Compare the accumulated contribution of each bone, not raw sort order.
    result = np.zeros(256, dtype=np.int32)
    for weight, index in zip(np.r_[row[:4], row[8:12]], np.r_[row[4:8], row[12:16]]):
        result[int(index)] += int(weight)
    return result


def test_real_face(path):
    payload = json.loads(path.read_text(encoding="utf-8"))
    gt = D3D11GameType.from_submesh_json_dict(payload)
    assert "BLENDINDICES1" in gt.ElementNameD3D11ElementDict, "Re-extract with the EXT8 type first"
    assert "COLOR1" not in gt.ElementNameD3D11ElementDict
    blend = next(item for item in payload["CategoryBufferList"]
                 if item["D3D11ElementList"][0]["Category"] == "Blend")
    source = np.fromfile(path.parent / blend["FileName"], dtype=np.uint8).reshape(-1, 16)
    expected = np.stack([bone_map(row) for row in source])
    assert np.all(expected.sum(axis=1) == 255)
    active_extra = int(np.count_nonzero(source[:, 8:12].sum(axis=1)))
    assert active_extra > 0

    # Import actual serialized buffers, then use the production evaluated-mesh
    # exporter. No weight parsing, quantization or index splitting is mocked.
    with patch.object(MeshCreateHelper, "create_bsdf_with_diffuse_linked"):
        obj = MMTImportHelper.create_mesh_from_json(str(path))
    assert len(obj.data.vertices) == len(source)
    result = ExportUtils.build_unity_obj_buffer_result(obj, gt)
    output = result.category_buffer_dict["Blend"].reshape(-1, 16)
    worst_error = 0
    for exported, loop in result.index_loop_id_dict.items():
        vertex = obj.data.loops[loop].vertex_index
        actual = bone_map(output[exported])
        assert actual.sum() == 255
        worst_error = max(worst_error, int(np.abs(actual - expected[vertex]).max()))
    # A one-byte quantization tolerance allows floating-point Blender storage.
    # The former bug instead changes whole extra bone contributions or yields
    # a combined weight of 510, both far outside this bound.
    assert worst_error <= 1, worst_error
    assert len(result.category_buffer_dict["Position"]) == len(output) * 28
    assert len(result.category_buffer_dict["Texcoord"]) == len(output) * 16
    print(f"PASS: real face {len(source)} vertices, {active_extra} use EXT, "
          f"{len(output)} exported vertices, max bone-byte error {worst_error}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--face-json", type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    # Register only settings used by the importer/exporter, not the addon UI.
    bpy.utils.register_class(MIMIGlobalProperties)
    bpy.types.Scene.mimi_global_properties = bpy.props.PointerProperty(type=MIMIGlobalProperties)
    GlobalConfig.logic_name = LogicName.YYSLS
    test_joint_quantization_and_editing()
    test_small_and_empty_meshes()
    test_duplicate_import_and_padding()
    test_legacy_four_weight_path()
    test_wwmi_path_unchanged()
    if args.face_json:
        test_real_face(args.face_json)
    print("All YYSLS Blender regressions passed")


if __name__ == "__main__":
    main()
