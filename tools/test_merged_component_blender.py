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

    def test_legacy_runtime_slot_alias_is_not_cross_component_weight(self):
        # Xin's old merged/reverse slot 223 is local 118 at VGOffset 105.
        # Current import merges that duplicate into bone 68. Both identities
        # address the same original bone and must produce local slot 118.
        self.obj.vertex_groups[0].name = "223"
        self.context.original_elementname_data_dict["BLENDWEIGHT"][:, 1] = 0
        self.extracted[0].vg_offset = 105
        self.extracted[0].vg_count = 121
        self.extracted[0].vg_map = {"118": 68}
        self.extracted[1].vg_map = {"9": 68}
        output = self.convert()["BLENDINDICES"]
        self.assertTrue(numpy.all(output[:3, 0] == 118))
        self.assertTrue(numpy.all(output[3:, 0] == 9))
        self.assertEqual(self.obj.vertex_groups[0].name, "223")

    def test_alias_does_not_authorize_an_unrelated_component(self):
        # An alias may only reach a bone present in the target palette.
        # This preserves rejection of genuine cross-component influences.
        # No arbitrary offset subtraction is allowed as an escape hatch.
        self.obj.vertex_groups[0].name = "223"
        self.context.original_elementname_data_dict["BLENDWEIGHT"][:, 1] = 0
        self.extracted[0].vg_offset = 105
        self.extracted[0].vg_count = 121
        self.extracted[0].vg_map = {"118": 68}
        with self.assertRaisesRegex(ValueError, "component 1.*223"):
            self.convert()

    def test_real_project_bone_229_remains_a_cross_component_error(self):
        # The supplied scene also uses bone 229 on the component with offset 105.
        # Unlike alias 223 -> 68, bone 229 belongs to another original palette.
        # Extending shape metadata must never relax this weight-preservation guard.
        self.obj.vertex_groups[0].name = '229'
        self.context.original_elementname_data_dict['BLENDWEIGHT'][:, 1] = 0
        self.extracted[0].vg_offset = 105
        self.extracted[0].vg_count = 121
        self.extracted[0].vg_map = {'118': 68}
        self.extracted[1].vg_offset = 227
        self.extracted[1].vg_count = 108
        self.extracted[1].vg_map = {'2': 229}
        before = self.context.original_elementname_data_dict['BLENDWEIGHT'].copy()
        with self.assertRaisesRegex(ValueError, "component 0, object 'part_a'.*229"):
            self.convert()
        numpy.testing.assert_array_equal(self.context.original_elementname_data_dict['BLENDWEIGHT'], before)

    def test_workspace_fatal_uses_the_exporters_expected_error_type(self):
        # Missing workspace bindings previously escaped as an unrelated Fatal.
        # The export UI already catches the shared format error class.
        # Keep old module imports compatible without duplicating exception types.
        from MIMIBlender.utils.format_utils import Fatal
        from MIMIBlender.utils.mmt_error_utils import MMTErrorUtils, Fatal as WorkspaceFatal
        self.assertIs(WorkspaceFatal, Fatal)
        with self.assertRaises(Fatal):
            MMTErrorUtils.raise_fatal('missing extracted submesh')

    def test_merged_remap_uses_names_and_dynamic_stride(self):
        # Sparse names and reordered Blender indices exercise two regressions
        # together: 552 must neither become internal index 1 nor overflow 512.
        # The source groups remain untouched by this export-only mapping.
        self.obj.vertex_groups[0].add([0, 1, 2], 0.6, 'REPLACE')
        self.obj.vertex_groups[1].add([0, 1, 2], 0.4, 'REPLACE')
        model = DrawIBModelWWMI.__new__(DrawIBModelWWMI)
        model.wwmi_info = SimpleNamespace(components=[WWMIInfoComponent(0, 0, 0, 0, 0, 553, {})])
        model.d3d11_game_type = SimpleNamespace(get_blendindices_count_wwmi=lambda: 4)
        model.component_real_vg_count_dict = {}
        model.export_blendremap_forward_and_reverse([(0, self.obj)])
        self.assertEqual(model.blend_remap_bone_count, 553)
        self.assertEqual(len(model.blend_remap_reverse_buffer), 553)
        numpy.testing.assert_array_equal(model.blend_remap_forward_buffer[:2], [522, 552])
        self.assertEqual(model.blend_remap_reverse_buffer[552], 1)
        # Do not mock a Blender RNA property with the same name as its accessor:
        # restoring that descriptor can replace the instance enum with a method.
        settings = MIMIGlobalProperties._instance()
        previous_mode = settings.import_merged_vgmap
        try:
            settings.import_merged_vgmap = 'MERGED'
            model.resolve_named_blendindices(self.context)
        finally:
            settings.import_merged_vgmap = previous_mode
        numpy.testing.assert_array_equal(self.context.original_elementname_data_dict['BLENDINDICES'][0], [522, 552, 0, 0])
        # A gap below the maximum extent is not an initialized runtime bone.
        # Reject it before creating a map that reads undefined skeleton matrices.
        model.wwmi_info.components[0].vg_offset = 500
        model.wwmi_info.components[0].vg_count = 53
        self.obj.vertex_groups[0].name = '400'
        with self.assertRaisesRegex(ValueError, 'outside the original merged skeleton'):
            model.export_blendremap_forward_and_reverse([(0, self.obj)])

    def test_extended_runtime_stride_is_set_for_every_shader_call(self):
        # The runtime resets the stride after each blend/skeleton remapper call.
        # Verify all three assignments, both matrix buffer sizes, and the mod's
        # minimum runtime version, not just successful numpy buffer generation.
        from MIMIBlender.common.m_ini_builder import M_IniBuilder
        from MIMIBlender.games.wwmi import blend_remap
        model = make_model()
        model.blend_remap_bone_count = 553
        model.wwmi_info.components[-1].vg_offset = 500
        model.wwmi_info.components[-1].vg_count = 53
        exporter = make_exporter(model)
        # An ordinary first DrawIB must not lower the shared runtime requirement
        # needed by an extended second DrawIB in the same generated Mod.
        first_model = make_model(draw_ib='deadbeef')
        exporter.drawib_drawibmodel_dict = {first_model.draw_ib: first_model, model.draw_ib: model}
        builder = M_IniBuilder()
        settings = MIMIGlobalProperties._instance()
        previous_mode = settings.import_merged_vgmap
        try:
            settings.import_merged_vgmap = 'MERGED'
            exporter.add_constants_section(builder, first_model)
            blend_remap.add_blend_remap_sections(builder, model)
            blend_remap.add_resource_merged_skeleton(builder, model)
        finally:
            settings.import_merged_vgmap = previous_mode
        text = '\n'.join(render_lines(builder))
        self.assertEqual(text.count('blend_remap_bone_count = 553'), 3)
        self.assertEqual(text.count('array = 1659'), 2)
        self.assertIn('global $required_wwmi_version = 1.10', text)

    def test_failed_model_build_cleans_only_its_disposable_objects(self):
        # A runtime validation failure can occur after one or more joins.
        # Verify exception cleanup by identity, preserving a pre-existing mesh
        # even if it happens to use the exporter's temporary naming convention.
        original_objects = set(bpy.data.objects)
        original_meshes = set(bpy.data.meshes)

        def fail_build(model):
            mesh = bpy.data.meshes.new('failure_copy')
            obj = bpy.data.objects.new('TEMP_EXPORT_OBJECT', mesh)
            bpy.context.scene.collection.objects.link(obj)
            raise ValueError('synthetic validation failure')

        with patch.object(DrawIBModelWWMI, '_initialize_model', fail_build):
            with self.assertRaisesRegex(ValueError, 'synthetic'):
                DrawIBModelWWMI('deadbeef', None)
        self.assertEqual(set(bpy.data.objects), original_objects)
        self.assertEqual(set(bpy.data.meshes), original_meshes)

    def test_unico_empty_map_keeps_offsets_and_lod_scope(self):
        # UniComponent must not skip a valid offset-only legacy palette or mix
        # another LOD that happens to reuse the same DrawIB hash. Capture the
        # production split arguments without creating any disposable geometry.
        from MIMIBlender.model.blueprint_model import BluePrintModel
        from MIMIBlender.workspace.mmt_workspace import MMTWorkSpace
        from MIMIBlender.utils.vertexgroup_utils import VertexGroupUtils
        palette = SimpleNamespace(VGMap={}, VGOffset=522, VGCount=4)
        model = BluePrintModel.__new__(BluePrintModel)
        with patch.object(MMTWorkSpace, 'get_ordered_submesh_name_list_by_drawib', return_value=['LOD0.deadbeef-0', 'LOD1.deadbeef-0']):
            with patch.object(MMTWorkSpace, 'check_and_get_submesh_json_path', return_value='unused'):
                with patch('MIMIBlender.workspace.submesh_json.SubmeshJson', return_value=palette):
                    with patch.object(VertexGroupUtils, 'split_merged_object_by_submesh_vg_ranges', return_value=[]) as split:
                        model._unico_split_object(self.obj, 'LOD0.deadbeef-0')
        maps = split.call_args.kwargs['submesh_reverse_vg_map']
        self.assertEqual(maps, {'LOD0.deadbeef-0': {522: 0, 523: 1, 524: 2, 525: 3}})

    def test_unico_shared_bone_fallback_tolerates_helper_groups(self):
        # Shared-bone vertices use the fallback path, not unique ownership.
        # A nonnumeric unused helper group previously crashed its comprehension.
        # Test the real split and then remove only its returned temporary copies.
        from MIMIBlender.utils.vertexgroup_utils import VertexGroupUtils
        self.obj.vertex_groups[0].add(list(range(4)), 1.0, 'REPLACE')
        pieces = VertexGroupUtils.split_merged_object_by_submesh_vg_ranges(
            self.obj, {'part_a': {522}}, {'part_a': {522: 0}}, {'part_a': set()})
        try:
            self.assertEqual(len(pieces), 1)
            self.assertEqual(len(pieces[0][1].data.polygons), 2)
            self.assertEqual(len(self.obj.data.polygons), 2)
            self.assertEqual(self.obj.vertex_groups[0].name, '522')
        finally:
            for _, piece in pieces:
                mesh = piece.data
                bpy.data.objects.remove(piece, do_unlink=True)
                bpy.data.meshes.remove(mesh)

    def test_unico_constructor_failure_cleans_unregistered_split_copies(self):
        # The caller's blueprint_model remains None when its constructor fails.
        # Emulate a later invalid node after an earlier split created a mesh.
        # Identity-based cleanup must preserve all pre-existing source data.
        from MIMIBlender.ui import ui_func_export
        before_objects = set(bpy.data.objects)
        before_meshes = set(bpy.data.meshes)

        def failed_parser(**kwargs):
            mesh = bpy.data.meshes.new('partial_split')
            obj = bpy.data.objects.new('Uni_partial_split', mesh)
            bpy.context.scene.collection.objects.link(obj)
            raise ValueError('invalid later component')

        with patch.object(MIMIGlobalProperties, 'is_unico_component', return_value=True):
            with patch.object(ui_func_export.GlobalConfig, 'path_generate_mod_folder', return_value='unused'):
                with patch.object(ui_func_export, 'BluePrintModel', side_effect=failed_parser):
                    with self.assertRaisesRegex(ValueError, 'invalid later'):
                        ui_func_export._export_regular_output(None, bpy.context, None, 'unused.ini')
        self.assertEqual(set(bpy.data.objects), before_objects)
        self.assertEqual(set(bpy.data.meshes), before_meshes)
        self.assertIsNone(ui_func_export.BlueprintExportHelper.runtime_output_node)
        self.assertEqual(ui_func_export.GlobalConfig.generated_mod_name_override, '')

    def test_unico_rejects_boundary_faces_without_creating_copies(self):
        # A face crossing dominant component ownership used to disappear when
        # each split deleted the other component's vertices. Fail before making
        # any disposable copies, leaving both source faces and weights intact.
        from MIMIBlender.utils.vertexgroup_utils import VertexGroupUtils
        self.obj.vertex_groups[0].add([0, 1], 1.0, 'REPLACE')
        self.obj.vertex_groups[1].add([2, 3], 1.0, 'REPLACE')
        maps = {'a': {522}, 'b': {552}}
        before = set(bpy.data.objects)
        with self.assertRaisesRegex(ValueError, 'spans incompatible'):
            VertexGroupUtils.split_merged_object_by_submesh_vg_ranges(
                self.obj, maps, {'a': {522: 0}, 'b': {552: 0}}, maps)
        self.assertEqual(set(bpy.data.objects), before)
        self.assertEqual(len(self.obj.data.polygons), 2)

    def test_unico_rejects_silent_cross_component_weight_loss(self):
        # All vertices choose component A, so face counts alone would pass.
        # The weaker bone belongs only to B and cannot be dropped silently.
        # Merged is the supported runtime path for this cross-component edit.
        from MIMIBlender.utils.vertexgroup_utils import VertexGroupUtils
        self.obj.vertex_groups[0].add(list(range(4)), 0.8, 'REPLACE')
        self.obj.vertex_groups[1].add(list(range(4)), 0.2, 'REPLACE')
        maps = {'a': {522}, 'b': {552}}
        with self.assertRaisesRegex(ValueError, 'outside its component palette'):
            VertexGroupUtils.split_merged_object_by_submesh_vg_ranges(
                self.obj, maps, {'a': {522: 0}, 'b': {552: 0}}, maps)
        self.assertAlmostEqual(self.obj.vertex_groups[1].weight(0), 0.2)

    def test_shape_metadata_preflight_does_not_overwrite_buffers(self):
        # A late shape metadata error previously occurred only during INI writing,
        # after replacing existing Mod buffers. Validate every model first so
        # a missing second runtime batch cannot leave a half-updated export.
        from unittest.mock import Mock
        from MIMIBlender.utils.format_utils import Fatal
        model = make_model()
        model.obj_buffer_model_wwmi.shapekey_offsets = [0] * 256
        model.wwmi_info.shapekeys.batches = [{'checksum': 0, 'dispatch_y': 2, 'vertex_offset': 0}]
        model.write_buffer_files = Mock()
        exporter = make_exporter(model)
        with self.assertRaises(Fatal):
            exporter.export()
        model.write_buffer_files.assert_not_called()

    def test_merged_rejects_more_than_256_effective_bones(self):
        # Global skeletons may exceed 512, but each R8 draw still holds 256 bones.
        # Distribute 257 active identities across vertices to exceed the palette
        # without exceeding the permitted per-vertex influence count.
        self.obj.data.clear_geometry()
        self.obj.data.from_pydata([(float(i), 0, 0) for i in range(257)], [], [])
        for identity in range(257):
            group = self.obj.vertex_groups.new(name=str(identity))
            group.add([identity], 1.0, 'REPLACE')
        model = DrawIBModelWWMI.__new__(DrawIBModelWWMI)
        model.wwmi_info = SimpleNamespace(components=[WWMIInfoComponent(0, 0, 0, 0, 0, 553, {})])
        model.d3d11_game_type = SimpleNamespace(get_blendindices_count_wwmi=lambda: 4)
        model.component_real_vg_count_dict = {}
        with self.assertRaisesRegex(ValueError, 'more than 256'):
            model.export_blendremap_forward_and_reverse([(0, self.obj)])

    def test_duplicate_name_merge_precedes_runtime_palette_selection(self):
        # Combining two 510 groups promotes a previously fifth-ranked influence
        # into the top four. Building the map first omitted 513 and truncated it
        # later. Exercise real joins, numeric-name merging, and palette creation.
        from MIMIBlender.model.draw_call_model import DrawCallModel
        self.obj.vertex_groups[0].name = '510'
        self.obj.vertex_groups[1].name = '511'
        for name, weight in [('510', 0.2), ('510.001', 0.2), ('511', 0.3), ('512', 0.2), ('513', 0.1)]:
            group = self.obj.vertex_groups.get(name) or self.obj.vertex_groups.new(name=name)
            group.add(list(range(4)), weight, 'REPLACE')
        model = DrawIBModelWWMI.__new__(DrawIBModelWWMI)
        model.wwmi_info = SimpleNamespace(components=[WWMIInfoComponent(0, 4, 0, 6, 0, 553, {})])
        model.submesh_drawcall_groups = [[DrawCallModel(obj_name=self.obj.name, submesh_name='LOD0.deadbeef-0')]]
        model.d3d11_game_type = SimpleNamespace(get_blendindices_count_wwmi=lambda: 4)
        settings = MIMIGlobalProperties._instance()
        previous_mode = settings.import_merged_vgmap
        previous_fill = settings.export_add_missing_vertex_groups
        before_objects = set(bpy.data.objects)
        before_meshes = set(bpy.data.meshes)
        try:
            settings.import_merged_vgmap = 'MERGED'
            settings.export_add_missing_vertex_groups = True
            model.build_merged_object()
            self.assertEqual(model.component_real_vg_count_dict[0], 4)
            self.assertEqual(next(iter(model.blend_remap_maps.values()))['forward'], [510, 511, 512, 513])
            self.assertAlmostEqual(self.obj.vertex_groups['510'].weight(0), 0.2)
            self.assertIn('510.001', self.obj.vertex_groups)
        finally:
            settings.import_merged_vgmap = previous_mode
            settings.export_add_missing_vertex_groups = previous_fill
            for obj in set(bpy.data.objects) - before_objects:
                bpy.data.objects.remove(obj, do_unlink=True)
            for mesh in set(bpy.data.meshes) - before_meshes:
                if mesh.users == 0:
                    bpy.data.meshes.remove(mesh)

    def test_local_modes_use_sparse_group_names_and_validate_limits(self):
        # Deleting unused groups changes internal indices without renaming bones.
        # Both original-local and UniComponent's split-local export must retain
        # those numeric names, clear padding, and reject unrepresentable slots.
        self.obj.vertex_groups[0].name = '7'
        self.obj.vertex_groups[1].name = '19'
        model = DrawIBModelWWMI.__new__(DrawIBModelWWMI)
        model.wwmi_info = SimpleNamespace(components=self.extracted)
        model.merged_object = SimpleNamespace(components=self.components)
        settings = MIMIGlobalProperties._instance()
        previous_mode = settings.import_merged_vgmap
        try:
            for mode in ['PER_COMPONENT', 'UNICOMPONENT']:
                settings.import_merged_vgmap = mode
                context = self.make_context(4)
                model.resolve_named_blendindices(context)
                numpy.testing.assert_array_equal(context.final_elementname_data_dict['BLENDINDICES'], [[7, 19, 0, 0]] * 6)
            self.obj.vertex_groups[1].name = '256'
            for component in self.extracted:
                component.vg_count = 300
            with self.assertRaisesRegex(ValueError, 'outside its local palette'):
                model.resolve_named_blendindices(self.make_context(4))
        finally:
            settings.import_merged_vgmap = previous_mode

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
        self.assertEqual(MIMIGlobalProperties.import_merged_vgmap(), 'MERGED_COMPONENT')
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
