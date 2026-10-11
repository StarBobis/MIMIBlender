"""Blender regression tests for global editing with offline local export.

Use factory startup so the new enum default is tested independently of saved
scenes. Real meshes exercise Blender group indices, joins and polygon ranges.
Run with blender -b --factory-startup --python-exit-code 1 --python this_file.
"""

import importlib
import json
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import bpy
import numpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT / "tools"))
addon = importlib.import_module(ROOT.name)
# The shared INI test helpers register the addon once when imported.

from MIMIBlender.common.mimi_global_properties import MIMIGlobalProperties
from MIMIBlender.common.global_config import GlobalConfig, LogicName
from MIMIBlender.common.obj_buffer_helper import ObjBufferHelper
from MIMIBlender.games.wwmi.merged_component import localize_blendindices
from MIMIBlender.games.wwmi.model import DrawIBModelWWMI
from MIMIBlender.utils.export_utils import ObjElementContext
from MIMIBlender.utils.obj_utils import ObjUtils
from MIMIBlender.workspace.wwmi_info import WWMIInfoComponent
from test_wwmi_components_blender import make_model, make_exporter, render_lines


class MergedComponentTests(unittest.TestCase):
    """The source mesh and weight arrays must survive conversion unchanged."""

    def setUp(self):
        # Two triangles allow the same Blender vertex to belong to two draws.
        # Component-specific local indices may differ on those shared corners.
        mesh = bpy.data.meshes.new("merged_component_test")
        mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0)], [], [(0, 1, 2), (1, 3, 2)])
        self.obj = bpy.data.objects.new("merged_component_test", mesh)
        bpy.context.scene.collection.objects.link(self.obj)
        # These sparse names deliberately differ from Blender's internal IDs.
        self.obj.vertex_groups.new(name="522")
        self.obj.vertex_groups.new(name="552")
        self.obj.vertex_groups.new(name="unused_helper")
        self.components = [
            SimpleNamespace(objects=[SimpleNamespace(name="part_a", index_offset=0, index_count=3)]),
            SimpleNamespace(objects=[SimpleNamespace(name="part_b", index_offset=3, index_count=3)]),
        ]
        self.extracted = [
            WWMIInfoComponent(0, 0, 0, 3, 0, 20, {"7": 522, "19": 552}),
            WWMIInfoComponent(0, 0, 3, 3, 20, 20, {"9": 522, "3": 552}),
        ]
        # Four and eight influences use the same flat R8 buffer contract.
        self.context = self.make_context(4)

    def tearDown(self):
        # Remove only test-created objects; the user scene is never involved.
        mesh = self.obj.data
        bpy.data.objects.remove(self.obj, do_unlink=True)
        bpy.data.meshes.remove(mesh)

    def make_context(self, width):
        dtype = numpy.dtype([("BLENDINDICES", numpy.uint8, (width,)), ("BLENDWEIGHT", numpy.uint8, (width,))])
        indices = numpy.zeros((6, width), dtype=numpy.uint32)
        weights = numpy.zeros((6, width), dtype=numpy.uint8)
        indices[:, :3] = [0, 1, 2]
        weights[:, :2] = [153, 102]
        return ObjElementContext(
            obj=self.obj, obj_name=self.obj.name, mesh=self.obj.data, total_structured_dtype=dtype,
            d3d11_game_type=SimpleNamespace(
                OrderedFullElementList=["BLENDINDICES", "BLENDWEIGHT"],
                get_total_structured_dtype=lambda: dtype,
            ),
            original_elementname_data_dict={"BLENDINDICES": indices, "BLENDWEIGHT": weights},
        )

    def convert(self):
        return localize_blendindices(self.context, self.components, self.extracted, "deadbeef")

    def test_default_and_saved_enum_values(self):
        # Adding the first UI item must not reinterpret existing saved values.
        settings = MIMIGlobalProperties._instance()
        self.assertEqual(settings.import_merged_vgmap, "MERGED_COMPONENT")
        self.assertTrue(MIMIGlobalProperties.is_merged_mode())
        self.assertFalse(MIMIGlobalProperties.is_unico_component())
        try:
            for number, name in enumerate(("MERGED", "PER_COMPONENT", "UNICOMPONENT", "MERGED_COMPONENT")):
                settings["import_merged_vgmap"] = number
                self.assertEqual(settings.import_merged_vgmap, name)
        finally:
            settings.import_merged_vgmap = "MERGED_COMPONENT"

    def test_high_global_names_become_component_local_indices(self):
        original_indices = self.context.original_elementname_data_dict["BLENDINDICES"].copy()
        original_weights = self.context.original_elementname_data_dict["BLENDWEIGHT"].copy()
        output = self.convert()
        numpy.testing.assert_array_equal(output["BLENDINDICES"][:3], [[7, 19, 0, 0]] * 3)
        numpy.testing.assert_array_equal(output["BLENDINDICES"][3:], [[9, 3, 0, 0]] * 3)
        numpy.testing.assert_array_equal(self.context.original_elementname_data_dict["BLENDINDICES"], original_indices)
        numpy.testing.assert_array_equal(self.context.original_elementname_data_dict["BLENDWEIGHT"], original_weights)
        self.assertEqual([group.name for group in self.obj.vertex_groups], ["522", "552", "unused_helper"])
        self.assertEqual((len(self.obj.data.vertices), len(self.obj.data.polygons)), (4, 2))

    def test_local_arrays_pack_into_actual_uint8_fields(self):
        # Verify the integration seam, not merely the returned integer values.
        self.context.final_elementname_data_dict.update(self.convert())
        packed = ObjBufferHelper.convert_to_element_vertex_ndarray(
            self.context.d3d11_game_type, self.context.mesh,
            self.context.original_elementname_data_dict, self.context.final_elementname_data_dict,
        )
        self.assertEqual(packed.dtype["BLENDINDICES"].base, numpy.dtype(numpy.uint8))
        numpy.testing.assert_array_equal(packed["BLENDINDICES"][0], [7, 19, 0, 0])
        numpy.testing.assert_array_equal(packed["BLENDWEIGHT"][0], [153, 102, 0, 0])

    def test_eight_weights_and_zero_padding(self):
        # Padding references an unnamed group but has no exported contribution.
        self.context = self.make_context(8)
        output = self.convert()["BLENDINDICES"]
        self.assertEqual(output.shape, (6, 8))
        numpy.testing.assert_array_equal(output[0], [7, 19, 0, 0, 0, 0, 0, 0])

    def test_missing_bone_fails_without_weight_deletion(self):
        # A different component's local slot is never a valid fallback.
        self.extracted[0].vg_map.pop("19")
        before = self.context.original_elementname_data_dict["BLENDWEIGHT"].copy()
        with self.assertRaisesRegex(ValueError, "component 0, object 'part_a'.*552"):
            self.convert()
        numpy.testing.assert_array_equal(self.context.original_elementname_data_dict["BLENDWEIGHT"], before)

    def test_active_unnamed_group_is_rejected(self):
        self.context.original_elementname_data_dict["BLENDWEIGHT"][:, 2] = 1
        with self.assertRaisesRegex(ValueError, "unnamed group index 2"):
            self.convert()

    def test_import_offset_fallback_and_duplicate_slots(self):
        # Missing explicit entries follow the import rule. Repeated global IDs
        # choose the smallest representable local slot deterministically.
        self.extracted[0].vg_offset = 522
        self.extracted[0].vg_map = {"19": 552, "11": 552}
        output = self.convert()["BLENDINDICES"]
        numpy.testing.assert_array_equal(output[0], [0, 11, 0, 0])

    def test_boundary_global_names_do_not_limit_local_indices(self):
        # Global identity is independent of the old 256/512 table boundaries.
        for global_id in (255, 256, 511, 512, 522, 552):
            self.obj.vertex_groups[0].name = str(global_id)
            self.context.original_elementname_data_dict["BLENDWEIGHT"][:, 1] = 0
            self.extracted[0].vg_map = {"7": global_id}
            self.extracted[1].vg_map = {"9": global_id}
            output = self.convert()["BLENDINDICES"]
            self.assertTrue(numpy.all(output[:3, 0] == 7))
            self.assertTrue(numpy.all(output[3:, 0] == 9))

    def test_unrepresentable_local_bone_fails(self):
        self.extracted[0].vg_count = 301
        self.extracted[0].vg_map = {"300": 522, "19": 552}
        with self.assertRaisesRegex(ValueError, "global bone 522"):
            self.convert()

    def test_empty_component_and_missing_ownership(self):
        # Empty metadata components do not shift the maps of later components.
        self.components.insert(1, SimpleNamespace(objects=[]))
        self.extracted.insert(1, WWMIInfoComponent(0, 0, 3, 0, 0, 0, {}))
        numpy.testing.assert_array_equal(self.convert()["BLENDINDICES"][3], [9, 3, 0, 0])
        self.components[0].objects = []
        with self.assertRaisesRegex(ValueError, "no blueprint component"):
            self.convert()

    def test_real_merge_and_parse_keep_sparse_global_groups(self):
        # Exercise the real temporary-object pipeline, not synthetic arrays.
        # Disabling gap filling makes internal indices differ from global names.
        from MIMIBlender.common.d3d11_gametype import D3D11GameType
        from MIMIBlender.utils.export_utils import ExportUtils
        game_type = D3D11GameType.from_submesh_json_dict({
            "WorkGameType": "merged_component_test",
            "CategoryBufferList": [{"D3D11ElementList": [
                {"SemanticName": "POSITION", "SemanticIndex": 0, "Format": "R32G32B32_FLOAT", "ByteWidth": 12, "Category": "Position"},
                {"SemanticName": "BLENDINDICES", "SemanticIndex": 0, "Format": "R8_UINT", "ByteWidth": 4, "Category": "Blend"},
                {"SemanticName": "BLENDWEIGHT", "SemanticIndex": 0, "Format": "R8G8B8A8_UNORM", "ByteWidth": 4, "Category": "Blend"},
            ]}],
        })
        # Export evaluates tangents even for this minimal layout, so provide UVs.
        uv_layer = self.obj.data.uv_layers.new(name="texcoord")
        uv_layer.data.foreach_set("uv", [0, 0, 1, 0, 0, 1, 1, 0, 1, 1, 0, 1])
        self.obj.vertex_groups[0].add(list(range(4)), 0.6, 'REPLACE')
        self.obj.vertex_groups[1].add(list(range(4)), 0.4, 'REPLACE')
        model = DrawIBModelWWMI.__new__(DrawIBModelWWMI)
        model.draw_ib = "deadbeef"
        model.wwmi_info = SimpleNamespace(components=[self.extracted[0]])
        model.submesh_drawcall_groups = [[SimpleNamespace(obj_name=self.obj.name)]]
        model.d3d11_game_type = game_type
        merged = None
        with patch.object(GlobalConfig, "logic_name", LogicName.WWMI):
            with patch.object(MIMIGlobalProperties, "export_add_missing_vertex_groups", return_value=False):
                with patch.object(MIMIGlobalProperties, "apply_all_modifiers", return_value=False):
                    with patch.object(model, "export_blendremap_forward_and_reverse", side_effect=AssertionError("runtime remap must not run")):
                        try:
                            merged = model.build_merged_object()
                            context = ExportUtils.build_obj_element_context(game_type, merged.object)
                            converted = localize_blendindices(context, merged.components, model.wwmi_info.components, model.draw_ib)
                            numpy.testing.assert_array_equal(converted["BLENDINDICES"][:, :2], [[7, 19]] * 6)
                            # Packing and deduplication must preserve a complete
                            # four-vertex mesh and all six original triangle indices.
                            context.final_elementname_data_dict.update(converted)
                            packed = ObjBufferHelper.convert_to_element_vertex_ndarray(
                                game_type, context.mesh, context.original_elementname_data_dict,
                                context.final_elementname_data_dict,
                            )
                            result = ExportUtils.build_wwmi_index_buffers(context.mesh, packed, packed.dtype, game_type)
                            self.assertEqual(len(result[2]), 4)
                            self.assertEqual(numpy.asarray(result[0]).size, 6)
                            self.assertEqual(len(merged.object.data.vertices), 4)
                            self.assertEqual(len(self.obj.data.vertices), 4)
                            self.assertEqual([group.name for group in self.obj.vertex_groups], ["522", "552", "unused_helper"])
                        finally:
                            if merged is not None:
                                bpy.data.objects.remove(merged.object, do_unlink=True)

    def test_multiple_component_binding_is_rejected(self):
        # Sharing one complete object's rows between different palettes is unsafe.
        model = DrawIBModelWWMI.__new__(DrawIBModelWWMI)
        model.wwmi_info = SimpleNamespace(components=self.extracted)
        draw = SimpleNamespace(obj_name=self.obj.name)
        model.submesh_drawcall_groups = [[draw], [draw]]
        with self.assertRaisesRegex(ValueError, "multiple components"):
            try:
                model.build_merged_object()
            finally:
                for obj in list(bpy.data.objects):
                    if obj.name.startswith("TEMP_" + self.obj.name):
                        bpy.data.objects.remove(obj, do_unlink=True)

    def test_runtime_sections_keep_original_skeleton(self):
        # Exercise all real section writers, including shape-key callbacks.
        model = make_model()
        model.blend_remap = False
        model.blend_remap_used_by_index = {}
        model.wwmi_info.shapekeys.offsets_hash = "12345678"
        model.wwmi_info.shapekeys.scale_hash = "87654321"
        exporter = make_exporter(model)
        with patch("MIMIBlender.common.m_ini_builder.M_IniBuilder.save_to_file_not_reorder") as save:
            with patch("MIMIBlender.common.m_ini_helper.M_IniHelper.move_slot_style_textures"):
                with patch("MIMIBlender.common.global_config.GlobalConfig.path_generate_mod_folder", return_value=str(ROOT / "tmp")):
                    exporter.generate_unreal_vs_config_ini()
        self.assertEqual(save.call_count, 1)
        # Inspect captured builder through the same writers individually: the
        # serializer may combine sections, so assertions use flattened lines.
        from MIMIBlender.common.m_ini_builder import M_IniBuilder
        from MIMIBlender.games.wwmi import blend_remap, shapekeys
        builder = M_IniBuilder()
        for method in (exporter.add_constants_section, exporter.add_present_section,
                       exporter.add_commandlist_trigger_shared_cleanup_section,
                       exporter.add_texture_override_component, shapekeys.add_texture_override_shapekeys,
                       blend_remap.add_blend_remap_sections, blend_remap.add_commandlist_merge_skeleton_section):
            method(ini_builder=builder, draw_ib_model=model)
        text = "\n".join(render_lines(builder))
        self.assertIn("vb4 = ResourceBlendBuffer_", text)
        self.assertIn("handling = skip", text)
        self.assertNotIn("MergedSkeleton", text)
        self.assertNotIn("BlendRemapper", text)
        self.assertNotIn("merge_status", text)
        self.assertNotIn("vs-cb4 =", text)
        self.assertNotIn("vs-cb3 =", text)


if __name__ == "__main__":
    # The suite targets the installed 5.2 LTS API and emits a compact CI result.
    print("RESULT_VERSION " + json.dumps({"blender": list(bpy.app.version)}))
    try:
        result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(MergedComponentTests))
    finally:
        addon.unregister()
    print("RESULT " + json.dumps({"tests": result.testsRun, "passed": result.wasSuccessful()}))
    if not result.wasSuccessful():
        raise AssertionError("MergedComponent tests failed")
