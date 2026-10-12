"""Real mesh tests for upper/lower-body objects and scoped draw offsets.

Run with Blender --background --factory-startup --python-exit-code 1 --python.
Only workspace metadata is synthetic; separation and export use production code.
"""
import importlib
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import bpy
import numpy as np

# Register the checkout in a disposable Blender process, never a user's scene.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
importlib.import_module(ROOT.name).register()
from MIMIBlender.common.global_config import GlobalConfig, LogicName
from MIMIBlender.common.m_key import M_Key
from MIMIBlender.common.m_ini_helper import M_IniHelper
from MIMIBlender.model.submesh_model import SubMeshModel
from MIMIBlender.model.draw_call_model import DrawCallModel
from MIMIBlender.model.drawib_model import DrawIBModel

# Test contract:
# - The input is one mesh, not two independently constructed source objects.
# - Upper and lower body triangles alternate in its original polygon order.
# - A real Edit Mode separation moves B's two triangles into another object.
# - Neither object's name encodes a body region: both own upper and lower faces.
# - Positive Y identifies the upper region; negative Y identifies the lower one.
# - Minimum X identifies A or B after decoding the actual exported triangles.
# - Ownership assertions never trust draw counts as a substitute for geometry.
# - Reversing object order checks that Blender selection order is irrelevant.
# - Reusing names across Submeshes checks global AND local offset collisions.
# - Array evaluation checks topology growth separately from unchanged geometry.
# - UniComponent extraction checks that every region inherits the source key.
# - WWMI checks its independent two-stage component merge and IB builder.
# - Synthetic workspace metadata supplies formats, not expected IB ordering.
# - There are no forced buffer reorderings or mocked geometry builders here.
# POSITION encodes both body region and ownership without relying on vertex IDs.
ELEMENTS = [
    dict(SemanticName='POSITION', SemanticIndex=0, Format='R32G32B32_FLOAT', ByteWidth=12, Category='Position'),
    dict(SemanticName='TEXCOORD', SemanticIndex=0, Format='R32G32_FLOAT', ByteWidth=8, Category='Texcoord'),
]
METADATA = SimpleNamespace(MatchCS='', MatchUAVBytes=0, JsonDict={'CategoryBufferList': [{'D3D11ElementList': ELEMENTS}]})


# Regression invariants:
# Source objects keep their mesh data and key identities after every export.
# Temporary face attributes are restricted to copied export meshes.
# A draw must include every triangle belonging to its object in this Submesh.
# A draw must never include triangles belonging to the independently keyed object.
# Combined buffers remap vertex IDs without changing the ownership predicate.
# Split buffers retain local index offsets even when vertex buffers are shared.
# One object's appearances in different Submeshes need distinct offset entries.
# Triangles stay intact when regrouped, including game-specific winding flips.
# Vertex deduplication remains the production builder's responsibility.
# UV coordinates let tangent evaluation run on a complete real Blender mesh.
# Each test resets objects to prevent previous temporary exports influencing it.
# Empty factory startup avoids dependence on user preferences and saved scenes.
# The assertions deliberately distinguish ownership, completeness, and regions.
# A passing aggregate index count alone would not establish correct key control.
# All comparisons use decoded exported positions, not original mesh vertex IDs.
# Floating-point tolerance is used only when undoing WWMI's game-space transform.
# The source body coordinates are integers, so shared-path checks can be exact.
# Exported triangle spans are inspected through the actual drawindexed command.
# Conditional INI lines are checked alongside the geometry they address.
# Independent keys must stay independent even when objects share Submesh nodes.
# No tests read or modify external blend files or generated user mod folders.
# Registration failures are visible through Blender's Python exit-code flag.
# A failed unittest suite raises so shell automation cannot report false success.
class SplitDrawRangesTests(unittest.TestCase):
    def setUp(self):
        # Every test starts from a fresh in-memory scene, including selection state.
        bpy.ops.object.select_all(action='SELECT')
        bpy.ops.object.delete(use_global=False)
        GlobalConfig.logic_name = LogicName.EFMI
        vertices, faces = [], []
        # Original polygon order: upper A, upper B, lower A, lower B.
        for x, y in [(0, 10), (10, 10), (0, -10), (10, -10)]:
            start = len(vertices)
            vertices.extend([(x, y, 0), (x + 1, y, 0), (x, y + 1, 0)])
            faces.append((start, start + 1, start + 2))
        mesh = bpy.data.meshes.new('body_mesh')
        mesh.from_pydata(vertices, [], faces)
        uv = mesh.uv_layers.new(name='TEXCOORD.xy')
        for polygon in mesh.polygons:
            for j, loop in enumerate(polygon.loop_indices):
                uv.data[loop].uv = [(0, 0), (1, 0), (0, 1)][j]
        obj = bpy.data.objects.new('body', mesh)
        bpy.context.scene.collection.objects.link(obj)
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        # Clear all selection domains before separating B's upper AND lower faces.
        for vertex in mesh.vertices:
            vertex.select = False
        for edge in mesh.edges:
            edge.select = False
        for polygon in mesh.polygons:
            polygon.select = polygon.index in (1, 3)
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_mode(type='FACE')
        bpy.ops.mesh.separate(type='SELECTED')
        bpy.ops.object.mode_set(mode='OBJECT')
        self.objects = sorted(bpy.context.scene.objects, key=lambda item: item.data.vertices[0].co.x)
        for obj, name in zip(self.objects, ['body_a', 'body_b']):
            obj.name = name

    def export(self, submesh='LOD0.12345678-0', reverse=False):
        # Conditions are attached independently to A and B, as in a switch blueprint.
        draws = []
        for obj in self.objects[::-1] if reverse else self.objects:
            draw = DrawCallModel(obj_name=obj.name, submesh_name=submesh)
            draw.work_key_list = [M_Key(key_name='$' + obj.name, tmp_value=1)]
            draws.append(draw)
        with patch('MIMIBlender.model.submesh_model.MMTWorkSpace.check_and_get_submesh_json_path', return_value='synthetic.json'), patch('MIMIBlender.model.submesh_model.SubmeshJson', return_value=METADATA):
            return SubMeshModel(drawcall_model_list=draws)

    def assert_owned(self, model, offsets=None, ib=None, positions=None):
        # Decode actual drawn triangles, rather than asserting only aggregate counts.
        if positions is None:
            positions = np.frombuffer(model.category_buffer_dict['Position'], dtype='<f4').reshape(-1, 3)
        if ib is None:
            ib = model.ib
        for draw in model.drawcall_model_list:
            line = draw.get_drawindexed_str(offsets)
            count, start, base = map(int, line.split('=')[1].split(','))
            triangles = np.asarray(ib[start:start + count]).reshape(-1, 3)
            points = positions[triangles]
            expected = 0 if draw.obj_name.endswith('a') else 10
            self.assertTrue(np.all(points[:, :, 0].min(axis=1) == expected), line)
            # Both body regions must belong to the SAME key's draw, not just one half.
            self.assertTrue(np.any(points[:, :, 1] > 0), line)
            self.assertTrue(np.any(points[:, :, 1] < 0), line)
            local_positions = np.frombuffer(model.category_buffer_dict['Position'], dtype='<f4').reshape(-1, 3)
            owned_total = sum(local_positions[np.asarray(model.ib).reshape(-1, 3)][:, :, 0].min(axis=1) == expected)
            self.assertEqual(len(triangles), owned_total)
            self.assertIn('if $' + draw.obj_name + ' == 1', M_IniHelper.get_drawindexed_str_list(model.drawcall_model_list, offsets))

    def test_cross_body_separation(self):
        # Disconnected upper/lower faces alone must not split a key's coverage.
        self.assert_owned(self.export())
        self.assert_owned(self.export(reverse=True))

    def test_evaluated_polygon_order(self):
        # A topology modifier must not strand later A/B segments outside their keys.
        for obj in self.objects:
            mod = obj.modifiers.new('repeat_body', 'ARRAY')
            mod.use_relative_offset = False
            mod.use_constant_offset = True
            mod.constant_offset_displace = (0, 0, 2)
            mod.count = 2
        self.assert_owned(self.export())

    def test_unicomponent_keeps_keys_on_both_body_regions(self):
        # Split each A/B object again by real upper/lower vertex-group ownership.
        # Use the production blueprint emitter to verify condition propagation.
        from MIMIBlender.common.mimi_global_properties import MIMIGlobalProperties
        from MIMIBlender.model.blueprint_model import BluePrintModel
        from MIMIBlender.utils.vertexgroup_utils import VertexGroupUtils
        names = ['LOD0.12345678-0', 'LOD0.12345678-1']
        maps = {names[0]: {0}, names[1]: {1}}
        reverse = {names[0]: {0: 0}, names[1]: {1: 0}}
        parser = BluePrintModel.__new__(BluePrintModel)
        parser.ordered_draw_obj_data_model_list = []
        parser._unico_temp_objects = []
        for obj in self.objects:
            for group, upper in [(0, True), (1, False)]:
                vg = obj.vertex_groups.new(name=str(group))
                vg.add([v.index for v in obj.data.vertices if (v.co.y > 0) == upper], 1, 'REPLACE')

        def split(obj, node_submesh_name):
            # No fabricated split objects: BMesh extraction runs on the real mesh.
            return VertexGroupUtils.split_merged_object_by_submesh_vg_ranges(obj, maps, reverse, maps)

        with patch.object(MIMIGlobalProperties, 'is_unico_component', return_value=True), patch.object(parser, '_unico_split_object', side_effect=split):
            for obj in self.objects:
                parser._emit_object_source(obj.name, names[0], '', [M_Key(key_name='$' + obj.name, tmp_value=1)])
        self.assertEqual(len(parser.ordered_draw_obj_data_model_list), 4)
        for source in self.objects:
            draws = [draw for draw in parser.ordered_draw_obj_data_model_list if draw.get_condition_str() == '$' + source.name + ' == 1']
            self.assertEqual({draw.submesh_name for draw in draws}, set(names))
            regions = set()
            for draw in draws:
                obj = bpy.data.objects[draw.obj_name]
                self.assertEqual(len(obj.data.polygons), 1)
                regions.add(obj.data.vertices[0].co.y > 0)
            self.assertEqual(regions, {False, True})

    def test_wwmi_cross_body_ranges(self):
        # Exercise WWMI's separate component merge and actual deduplicating builder.
        # The shared range resolver must preserve its triangle winding and VB IDs.
        from MIMIBlender.common.d3d11_gametype import D3D11GameType
        from MIMIBlender.common.mimi_global_properties import MIMIGlobalProperties
        from MIMIBlender.games.wwmi.model import DrawIBModelWWMI
        from MIMIBlender.utils.export_utils import ExportUtils
        from MIMIBlender.utils.draw_range_utils import DrawRangeUtils
        assembly = DrawIBModelWWMI.__new__(DrawIBModelWWMI)
        assembly.draw_ib = '12345678'
        assembly.wwmi_info = SimpleNamespace(components=[SimpleNamespace(vg_map={})])
        assembly.submesh_drawcall_groups = [[DrawCallModel(obj_name=obj.name, submesh_name='LOD0.12345678-0') for obj in self.objects]]
        assembly.d3d11_game_type = D3D11GameType.from_submesh_json_dict(METADATA.JsonDict)
        with patch.object(GlobalConfig, 'logic_name', LogicName.WWMI), patch.object(MIMIGlobalProperties, 'import_merged_vgmap', return_value='PER_COMPONENT'), patch.object(MIMIGlobalProperties, 'apply_all_modifiers', return_value=False), patch.object(assembly, 'export_blendremap_forward_and_reverse'):
            merged = assembly.build_merged_object()
            context = ExportUtils.build_obj_element_context(assembly.d3d11_game_type, merged.object)
            result = ExportUtils.build_wwmi_obj_buffer_result(context)
            owners = merged.components[0].objects
            ib = DrawRangeUtils.align_buffer_ranges(context.mesh, result.ib, owners)
            positions = np.frombuffer(result.category_buffer_dict['Position'], dtype='<f4').reshape(-1, 3)
            # Undo WWMI's 180-degree rotation and 100x scale for ownership checks.
            # Floating-point rotation introduces tiny errors, so compare tolerantly.
            positions = positions / np.asarray([-100, -100, 100])
            for owner in owners:
                points = positions[np.asarray(ib[owner.index_offset:owner.index_offset + owner.index_count]).reshape(-1, 3)]
                expected = 0 if owner.name.endswith('a') else 10
                self.assertEqual(len(points), 2)
                self.assertTrue(np.allclose(points[:, :, 0].min(axis=1), expected, atol=1e-5))
                self.assertTrue(np.any(points[:, :, 1] > 0))
                self.assertTrue(np.any(points[:, :, 1] < 0))

    # Multi-Submesh coverage is separate from the modifier regression above.
    # It uses unchanged geometry and therefore cannot be blamed on evaluation.
    # Each Submesh independently exports the very same Blender object identities.
    # The second Submesh reverses A/B's draw order to expose local collisions.
    # Combined IBs append the second Submesh after the first Submesh's triangles.
    # Name-only global offsets silently point the first draw into that later span.
    # Coincident geometry could hide this mistake in a visual-only check.
    # The global test therefore validates span identity as well as geometry.
    # Split IBs start again at zero, making the same overwrite select B for A.
    # The local test validates decoded ownership and reproduces the old failure.
    # Identity keys must win even while compatibility name keys remain present.
    # Instanced drawing shares the resolver and must honor identical scoped offsets.
    # No source renaming is needed to avoid collisions after this fix.
    # No new condition variables should be introduced to compensate for ranges.
    # The actual draw model references remain alive for the entire assembly.
    # These assertions cover both assembly modes used by shared game exporters.
    def test_same_objects_in_two_submeshes(self):
        # A blueprint can reference the same A/B objects in multiple original draws.
        # Different object order makes name-only local offsets collide as well.
        first = self.export()
        second = self.export(submesh='LOD0.12345678-1', reverse=True)
        assembly = DrawIBModel.__new__(DrawIBModel)
        assembly.submesh_model_list = [first, second]
        buffers, bases, _, _ = assembly._assemble_category_buffers()
        positions = np.frombuffer(buffers['Position'], dtype='<f4').reshape(-1, 3)
        combined, offsets = assembly._assemble_combined_ib_and_draw_offset(bases)
        self.assert_owned(first, offsets, combined, positions)
        self.assert_owned(second, offsets, combined, positions)
        # Combined name-only offsets select the other Submesh's copy of A/B.
        # Its positions coincide here, so explicitly verify the wrong IB span.
        legacy = {key: value for key, value in offsets.items() if isinstance(key, str)}
        for draw in first.drawcall_model_list:
            self.assertNotEqual(draw._get_draw_offset(legacy), offsets[id(draw)])
        for draw in first.drawcall_model_list:
            expected_offset = offsets[id(draw)]
            self.assertEqual(draw.get_drawindexed_instanced_str(offsets), f'drawindexedinstanced = {draw.index_count},INSTANCE_COUNT,{expected_offset},0,FIRST_INSTANCE')
        separate, offsets, _ = assembly._assemble_split_ib_and_draw_offset(bases)
        self.assert_owned(first, offsets, separate[first.submesh_name], positions)
        self.assert_owned(second, offsets, separate[second.submesh_name], positions)
        # In split mode the same collision now selects the other object's faces.
        # A decoded ownership assertion must therefore fail on the legacy map.
        legacy = {key: value for key, value in offsets.items() if isinstance(key, str)}
        with self.assertRaises(AssertionError):
            self.assert_owned(first, legacy, separate[first.submesh_name], positions)


if __name__ == '__main__':
    # Propagate unittest failures to Blender's --python-exit-code contract.
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(SplitDrawRangesTests)
    if not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful():
        raise RuntimeError('Split draw range regression tests failed')
