"""Exercise routing with real Blender joins, buffers, shape keys and UI reports.

Factory startup avoids loading or saving any user project.
The two triangles share vertices but need different local bone indices.
This forces export-only duplication and proves that native deltas follow it.

Integration contract
--------------------
The fixtures use production copy, modifier, triangulation and join helpers.
They do not replace buffer builders with hand-written expected output.
Component 0 has canonical bones 10 and 30 in local slots 0 and 1.
Component 1 has canonical bones 30 and 20 in local slots 0 and 1.
Both source triangles start on component 0 in the blueprint.
Their shared bone 30 changes local slot when the second triangle moves.
Four source vertices therefore require six distinct serialized vertices.
The source retains four vertices, its original group names and native keys.
Deform 0 belongs to the first original runtime batch.
Deform 127 belongs to the second original runtime batch.
Both batches must contain deltas for every duplicate of the affected vertex.
Missing intermediate native IDs consume empty slots rather than renumbering keys.

Draw and diagnostic checks
--------------------------
Repeated source branches remain repeated conditional draws after redistribution.
Explicit textures capture and restore the incoming slot on every cloned draw.
Both keyboard-driven and time-driven conditions remain on those clones.
Destination metadata supplies the original match range, not a fabricated draw.
Actual INI rendering must contain local component draws without MergedSkeleton.
IB reordering must preserve triangle source vertices, not merely total counts.
A blocked plan must not apply even its individually routable assignments.
Default consent remains disabled on a fresh scene.
Reports store the full machine data as well as human-readable guidance.
Selection operates on original source faces rather than joined export indices.
A topology signature rejects old diagnostics after polygon reordering.
Joined meshes retain separate source ownership despite overlapping face numbers.
A source quad remains a quad even when two export triangles are diagnosed.
Modifier-generated copies must retain source provenance when Blender supplies it.
A missing provenance mapping is not permission to guess a source face.

Isolation boundaries
--------------------
Every test tracks only objects, meshes and Text blocks that it created.
Teardown leaves edit mode before cleaning those exact datablock identities.
No test writes a blend file, extraction cache, or generated user Mod directory.
The separate real-project probe verifies full geometry and weight digests.
Neither this suite nor the probe constitutes an in-game appearance check.
"""
import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

import bpy
import numpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT / 'tools'))
from test_wwmi_components_blender import addon, make_model, render_component_sections
from MIMIBlender.common.d3d11_gametype import D3D11GameType
from MIMIBlender.common.global_config import GlobalConfig, LogicName
from MIMIBlender.common.mimi_global_properties import MIMIGlobalProperties
from MIMIBlender.games.wwmi.model import DrawIBModelWWMI
from MIMIBlender.games.wwmi.component_routing_blender import (
    prepare_routing, apply_routing, latest_report, REPORT_DATA, topology_signature,
)
from MIMIBlender.games.wwmi.merged_component import localize_blendindices
from MIMIBlender.model.draw_call_model import DrawCallModel
from MIMIBlender.utils.draw_range_utils import DrawRangeUtils
from MIMIBlender.utils.export_utils import ExportUtils
from MIMIBlender.workspace.wwmi_info import WWMIInfoComponent


class BlenderRoutingTests(unittest.TestCase):
    def setUp(self):
        # Track exact identities so teardown cannot remove unrelated scene data.
        # These tests never save the scene, and copies are created by production.
        # UVs exist because the standard export context also calculates tangents.
        self.before_objects = set(bpy.data.objects)
        self.before_meshes = set(bpy.data.meshes)
        self.before_texts = set(bpy.data.texts)
        mesh = bpy.data.meshes.new('routing_test')
        mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0)], [], [(0, 1, 2), (1, 3, 2)])
        uv = mesh.uv_layers.new(name='texcoord')
        uv.data.foreach_set('uv', [0, 0, 1, 0, 0, 1, 1, 0, 1, 1, 0, 1])
        self.obj = bpy.data.objects.new('deadbeef-0.routing_test', mesh)
        bpy.context.scene.collection.objects.link(self.obj)
        for name, indices in [('10', [0]), ('30', [1, 2]), ('20', [3])]:
            self.obj.vertex_groups.new(name=name).add(indices, 1, 'REPLACE')
        self.obj.shape_key_add(name='Basis')
        # Start each native key from Basis, not Blender's current mixed shape.
        # Otherwise adding the second key can inherit the first key's edit.
        self.obj.shape_key_add(name='Deform 0', from_mix=False).data[1].co.z += .1
        self.obj.shape_key_add(name='Deform 127', from_mix=False).data[1].co.z += .2
        self.game_type = D3D11GameType.from_submesh_json_dict({
            'WorkGameType': 'routing_test', 'CategoryBufferList': [{'D3D11ElementList': [
                {'SemanticName': 'POSITION', 'SemanticIndex': 0, 'Format': 'R32G32B32_FLOAT', 'ByteWidth': 12, 'Category': 'Position'},
                {'SemanticName': 'BLENDINDICES', 'SemanticIndex': 0, 'Format': 'R8_UINT', 'ByteWidth': 4, 'Category': 'Blend'},
                {'SemanticName': 'BLENDWEIGHT', 'SemanticIndex': 0, 'Format': 'R8G8B8A8_UNORM', 'ByteWidth': 4, 'Category': 'Blend'},
            ]}],
        })
        self.model = DrawIBModelWWMI.__new__(DrawIBModelWWMI)
        self.model.draw_ib = 'deadbeef'
        self.model.wwmi_info = NS(components=[
            WWMIInfoComponent(0, 4, 0, 3, 100, 2, {0: 10, 1: 30}),
            WWMIInfoComponent(0, 4, 3, 3, 200, 2, {0: 30, 1: 20}),
        ])
        self.draw = DrawCallModel(self.obj.name, 'LOD0.deadbeef-0')
        # Conditions are real key models, so INI serialization exercises them too.
        # A shallow routed draw must retain their original values and clock kind.
        from MIMIBlender.common.m_key import M_Key
        self.draw.work_key_list = [M_Key(key_name='$routing_key', tmp_value=1),
                                   M_Key(key_name='$routing_clock', key_type='time', tmp_value=2)]
        self.draw.resolved_texture_slot_lines = ['ResourcePreviousTexture = ref ps-t0',
                                                 'ps-t0 = ResourceExplicitTexture']
        self.draw.resolved_texture_slot_restore_lines = ['ps-t0 = ResourcePreviousTexture']
        self.draw.time_position_key_name = '$routing_time'
        self.model.submesh_drawcall_groups = [[self.draw], []]
        self.model.d3d11_game_type = self.game_type

    def tearDown(self):
        # Face-selection tests enter edit mode intentionally; leave it cleanly.
        # Newly orphaned export meshes are removed, not just their objects.
        # Report Text blocks are test output and should not pollute later cases.
        if bpy.context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        for obj in set(bpy.data.objects) - self.before_objects:
            bpy.data.objects.remove(obj, do_unlink=True)
        for mesh in set(bpy.data.meshes) - self.before_meshes:
            if mesh.users == 0:
                bpy.data.meshes.remove(mesh)
        for text in set(bpy.data.texts) - self.before_texts:
            bpy.data.texts.remove(text)

    def build_context(self, apply_modifiers=False):
        # Use the real copy, transform, triangulation and join implementation.
        # Disable optional policies unrelated to routing to keep expected deltas
        # and group identities directly attributable to this feature.
        with patch.object(GlobalConfig, 'logic_name', LogicName.WWMI), \
                patch.object(MIMIGlobalProperties, 'import_merged_vgmap', return_value='MERGED_COMPONENT'), \
                patch.object(MIMIGlobalProperties, 'export_add_missing_vertex_groups', return_value=False), \
                patch.object(MIMIGlobalProperties, 'apply_all_modifiers', return_value=apply_modifiers):
            self.model.merged_object = self.model.build_merged_object()
        self.model.merged_object.object['wwmi_shapekey_batch_counts'] = [127, 49]
        return ExportUtils.build_obj_element_context(self.game_type, self.model.merged_object.object)

    def route(self, context):
        # Apply only after the complete plan and local index conversion succeed.
        # This is the same ordering used by the production WWMI model constructor.
        plan = prepare_routing(self.model, context, True)
        context.final_elementname_data_dict.update(localize_blendindices(
            context, self.model.merged_object.components, self.model.wwmi_info.components,
            self.model.draw_ib, plan['loop_components']))
        links = apply_routing(self.model, context, plan, ['LOD0.deadbeef-0', 'LOD0.deadbeef-1'])
        result = ExportUtils.build_wwmi_obj_buffer_result(context)
        owners = [temp for component in self.model.merged_object.components for temp in component.objects]
        result.ib = DrawRangeUtils.align_buffer_ranges(context.mesh, result.ib, owners)
        for draw, temp in links:
            draw.index_count, draw.index_offset = temp.index_count, temp.index_offset
        return plan, result

    def test_shared_vertices_keep_both_native_shape_batches(self):
        """Check native dispatch identity, not just final key or vertex counts.
        Missing a delta on either duplicate would corrupt only one component.
        """
        before = topology_signature(self.obj.data)
        context = self.build_context()
        plan, result = self.route(context)
        self.assertEqual(plan['assignments'], [0, 1])
        self.assertEqual(len(result.index_vertex_id_dict), 6)
        duplicates = [index for index, vertex in result.index_vertex_id_dict.items() if vertex == 1]
        self.assertEqual(len(duplicates), 2)
        self.assertEqual(len(result.shapekey_offsets), 256)
        self.assertEqual(result.shapekey_offsets[1], 2)
        self.assertEqual(result.shapekey_offsets[129], 2)
        self.assertEqual(result.shapekey_vertex_ids, duplicates + duplicates)
        numpy.testing.assert_allclose(numpy.array(result.shapekey_vertex_offsets).reshape(-1, 6)[:, 2], [10, 10, 20, 20], atol=1e-4)
        self.assertEqual(before, topology_signature(self.obj.data))
        self.assertEqual([key.name for key in self.obj.data.shape_keys.key_blocks], ['Basis', 'Deform 0', 'Deform 127'])
        self.assertEqual([group.name for group in self.obj.vertex_groups], ['10', '30', '20'])

    def test_island_analysis_moves_one_connected_part_without_consent(self):
        """Let a joined object carry parts that no single blueprint palette holds.

        The two parts share no edge, so the join kept them apart and the
        connected-part evidence survives. Each part fits exactly one component,
        so the deduction names a single destination per part instead of leaving
        a per-face ambiguity. Moving that part still changes its draw state, so
        consent is required, and the report must name the proven candidate.
        """
        # Two disjoint triangles in one object; the second needs component 1.
        mesh = bpy.data.meshes.new('routing_island')
        mesh.from_pydata(
            [(2, 0, 0), (3, 0, 0), (2, 1, 0), (5, 0, 0), (6, 0, 0), (5, 1, 0)],
            [], [(0, 1, 2), (3, 4, 5)])
        uv = mesh.uv_layers.new(name='texcoord')
        uv.data.foreach_set('uv', [0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1])
        island = bpy.data.objects.new('deadbeef-0.routing_island', mesh)
        bpy.context.scene.collection.objects.link(island)
        island.vertex_groups.new(name='10').add([0, 1, 2], 1, 'REPLACE')
        island.vertex_groups.new(name='20').add([3, 4, 5], 1, 'REPLACE')
        # One object, one blueprint row: the whole object is bound to component 0.
        self.model.submesh_drawcall_groups = [
            [DrawCallModel(island.name, 'LOD0.deadbeef-0')], []]
        context = self.build_context()
        # Without consent the proven island target is reported, never applied.
        with self.assertRaisesRegex(ValueError, 'routing stopped|自动分配已停止'):
            prepare_routing(self.model, context, False)
        report = json.loads(latest_report()[REPORT_DATA])
        self.assertEqual(report['counts']['draw_state'], 1)
        self.assertEqual(report['counts']['ambiguous'], 0)
        issue = report['objects'][island.name]['issues'][0]
        self.assertTrue(issue.get('island'))
        self.assertEqual(issue['candidates'], [1])
        plan = prepare_routing(self.model, context, True)
        self.assertEqual(plan['assignments'], [0, 1])
        self.assertEqual(plan['counts']['island'], 1)
        self.assertEqual(plan['counts']['draw_state'], 0)
        self.assertEqual(plan['issues'], [])
        self.assertEqual(plan['islands'], [dict(source=[0], target=1, faces=1)])
        # The routed part receives a cloned branch and its own component range.
        links = apply_routing(self.model, context, plan,
                              ['LOD0.deadbeef-0', 'LOD0.deadbeef-1'])
        self.assertEqual(len(links), 2)
        self.assertEqual({draw.get_submesh_name() for draw, _temp in links},
                         {'LOD0.deadbeef-0', 'LOD0.deadbeef-1'})
        self.assertEqual([len(group) for group in self.model.submesh_drawcall_groups], [1, 1])

    def test_draw_conditions_bindings_and_final_ranges_follow_faces(self):
        """Check rendered INI as well as Python-side draw metadata.
        Correct buffer ranges alone do not preserve switches or texture scope.
        """
        # Several conditional branches may intentionally draw one geometry range.
        # Routing must clone each branch, not collapse it by source object name.
        branch = copy.copy(self.draw)
        branch.comment_alias_name = 'second branch'
        self.model.submesh_drawcall_groups[0].append(branch)
        context = self.build_context()
        plan, result = self.route(context)
        self.assertEqual([len(group) for group in self.model.submesh_drawcall_groups], [2, 2])
        for target, group in enumerate(self.model.submesh_drawcall_groups):
            for draw in group:
                self.assertEqual((draw.index_count, draw.index_offset), (3, 3 * target))
                self.assertEqual(draw.resolved_texture_slot_lines, self.draw.resolved_texture_slot_lines)
                self.assertEqual(draw.resolved_texture_slot_restore_lines, self.draw.resolved_texture_slot_restore_lines)
                self.assertEqual(draw.time_position_key_name, '$routing_time')
                self.assertEqual(draw.work_key_list, self.draw.work_key_list)
                self.assertEqual(draw.get_submesh_name(), 'LOD0.deadbeef-' + str(target))
        # Render real INI sections to prove these are local component draws, not
        # merely plausible Python range objects awaiting an untested serializer.
        fixture = make_model(draw_ib='deadbeef')
        fixture.wwmi_info.components = self.model.wwmi_info.components
        fixture.submesh_drawcall_groups = self.model.submesh_drawcall_groups
        text = '\n'.join(render_component_sections(fixture, 'MERGED_COMPONENT'))
        self.assertIn('drawindexed = 3,0,0', text)
        self.assertIn('drawindexed = 3,3,0', text)
        self.assertIn('ps-t0 = ResourceExplicitTexture', text)
        self.assertIn('$routing_key == 1', text)
        self.assertIn('$routing_clock == 2', text)
        self.assertEqual(text.count('ResourcePreviousTexture = ref ps-t0'), 4)
        self.assertEqual(text.count('ps-t0 = ResourcePreviousTexture'), 4)
        self.assertNotIn('MergedSkeleton', text)
        self.assertEqual(self.draw.submesh_name, 'LOD0.deadbeef-0')

    def test_noncontiguous_faces_are_reordered_into_correct_ib_buckets(self):
        """Reverse target order so a no-op alignment cannot accidentally pass.
        Source vertex triples distinguish reordered geometry from lost faces.
        """
        # Reverse the two target assignments while keeping the original mesh order.
        # This forces real IB reordering rather than merely confirming draw counts.
        # Every triangle must still point at its original source vertices afterward.
        self.obj.vertex_groups['10'].remove([0])
        self.obj.vertex_groups['10'].add([3], 1, 'REPLACE')
        self.obj.vertex_groups['20'].remove([3])
        self.obj.vertex_groups['20'].add([0], 1, 'REPLACE')
        context = self.build_context()
        plan, result = self.route(context)
        self.assertEqual(plan['assignments'], [1, 0])
        self.assertEqual({result.index_vertex_id_dict[int(index)] for index in result.ib[:3]}, {1, 2, 3})
        self.assertEqual({result.index_vertex_id_dict[int(index)] for index in result.ib[3:]}, {0, 1, 2})
        self.assertEqual(len(result.ib), 6)

    def test_default_consent_is_disabled_and_report_selects_source_face(self):
        """Exercise the registered UI operators in a fresh Blender scene.
        A failed export must leave usable diagnostics after temporary cleanup.
        """
        self.assertFalse(bpy.context.scene.mimi_global_properties.allow_component_draw_state_changes)
        context = self.build_context()
        with self.assertRaisesRegex(ValueError, 'routing stopped|自动分配已停止'):
            prepare_routing(self.model, context, False)
        report = json.loads(latest_report()[REPORT_DATA])
        self.assertEqual(report['counts']['draw_state'], 1)
        issue = report['objects'][self.obj.name]['issues'][0]
        self.assertEqual(issue['source_face'], 1)
        self.assertEqual(issue['candidates'], [1])
        bpy.context.view_layer.objects.active = self.obj
        self.obj.select_set(True)
        self.assertEqual(bpy.ops.mimi.select_wwmi_problem_faces(), {'FINISHED'})
        bpy.ops.object.mode_set(mode='OBJECT')
        self.assertEqual([face.index for face in self.obj.data.polygons if face.select], [1])

    def test_selection_rejects_stale_topology(self):
        """Invalidate a report by reordering corners without changing counts.
        Comparing only vertex and polygon totals would select an unrelated face.
        """
        context = self.build_context()
        with self.assertRaises(ValueError):
            prepare_routing(self.model, context, False)
        # Changing polygon corner order preserves counts but invalidates mapping.
        # The signature guard must catch this before applying any selection mask.
        mesh = bpy.data.meshes.new('changed_routing_source')
        mesh.from_pydata([vertex.co[:] for vertex in self.obj.data.vertices], [], [(2, 1, 0), (2, 3, 1)])
        self.obj.data = mesh
        bpy.context.view_layer.objects.active = self.obj
        self.assertEqual(bpy.ops.mimi.select_wwmi_problem_faces(), {'CANCELLED'})

    def test_joined_objects_keep_independent_source_face_identity(self):
        """Join real objects whose original face indices overlap.
        The report must identify the failing owner rather than the join target.
        """
        # Source face zero exists in both meshes; FACE owner separates them.
        # The second source already fits component 1 and must never be reported.
        # Real joining also offsets its vertex IDs without changing its weights.
        other = self.obj.copy()
        other.data = self.obj.data.copy()
        other.name = 'deadbeef-1.routing_second'
        bpy.context.scene.collection.objects.link(other)
        other.vertex_groups['10'].remove([0])
        other.vertex_groups['20'].add([0], 1, 'REPLACE')
        self.model.submesh_drawcall_groups[1] = [DrawCallModel(other.name, 'LOD0.deadbeef-1')]
        context = self.build_context()
        with self.assertRaises(ValueError):
            prepare_routing(self.model, context, False)
        report = json.loads(latest_report()[REPORT_DATA])
        self.assertEqual(set(report['objects']), {self.obj.name})
        self.assertEqual(report['objects'][self.obj.name]['issues'][0]['source_face'], 1)
        plan, result = self.route(context)
        self.assertEqual(plan['assignments'], [0, 1, 1, 1])
        self.assertEqual(len(result.ib), 12)
        self.assertEqual([len(group) for group in self.model.submesh_drawcall_groups], [1, 2])

    def test_mirror_modifier_keeps_source_face_provenance_with_shape_keys(self):
        """Exercise modifier application through the production shape-key helper.
        Both generated copies must point back to the same original polygon.
        """
        # Mirror generates additional export faces while the source remains edited
        # as two triangles with native keys. Both copies of source face 1 fail.
        # The reported selection must not mistake mirrored vertex IDs for source IDs.
        modifier = self.obj.modifiers.new('routing_mirror', 'MIRROR')
        modifier.use_mirror_merge = False
        context = self.build_context(apply_modifiers=True)
        self.assertEqual(len(context.mesh.polygons), 4)
        with self.assertRaises(ValueError):
            prepare_routing(self.model, context, False)
        issues = json.loads(latest_report()[REPORT_DATA])['objects'][self.obj.name]['issues']
        self.assertEqual([issue['source_face'] for issue in issues], [1, 1])
        self.assertEqual(len(self.obj.data.vertices), 4)
        self.assertEqual(len(self.obj.modifiers), 1)
        self.assertEqual(len(self.obj.data.shape_keys.key_blocks), 3)

    def test_triangulated_quad_maps_both_triangles_to_one_source_face(self):
        """Select a source quad rather than two nonexistent source triangles.
        Selecting diagnostics must not triangulate the user's original geometry.
        """
        # Triangulation is export-only: selection must still address the source quad.
        # Both generated triangles inherit its one-based pre-triangulation tag.
        # This also covers source objects without any native shape keys.
        mesh = bpy.data.meshes.new('routing_quad')
        mesh.from_pydata([vertex.co[:] for vertex in self.obj.data.vertices], [], [(0, 1, 3, 2)])
        mesh.uv_layers.new(name='texcoord').data.foreach_set('uv', [0, 0, 1, 0, 1, 1, 0, 1])
        self.obj.data = mesh
        self.obj.vertex_groups.new(name='20').add([0, 1, 2, 3], 1, 'REPLACE')
        context = self.build_context()
        with self.assertRaises(ValueError):
            prepare_routing(self.model, context, False)
        issues = json.loads(latest_report()[REPORT_DATA])['objects'][self.obj.name]['issues']
        self.assertEqual(len(issues), 2)
        self.assertEqual([issue['source_face'] for issue in issues], [0, 0])
        bpy.context.view_layer.objects.active = self.obj
        self.assertEqual(bpy.ops.mimi.select_wwmi_problem_faces(), {'FINISHED'})
        bpy.ops.object.mode_set(mode='OBJECT')
        self.assertTrue(self.obj.data.polygons[0].select)
        self.assertEqual(len(self.obj.data.polygons), 1)

    def test_static_layout_without_bone_indices_keeps_face_ownership(self):
        """Export a capture whose layout has no bone indices at all.

        WWMI's shader-fetched static meshes (weapon records) carry only position,
        vector and texcoord streams, so an import has no vertex groups and the
        default MergedComponent export used to cancel with "missing bone index
        export layout". Without bone indices no weight can constrain a palette,
        so every triangle must stay with its blueprint component and the plan
        must be a clean identity: no issues, no reassignment, unchanged ranges.
        """
        # Same blueprint, same ownership, but a layout nothing can localize.
        self.game_type = D3D11GameType.from_submesh_json_dict({
            'WorkGameType': 'routing_static_test', 'CategoryBufferList': [{'D3D11ElementList': [
                {'SemanticName': 'POSITION', 'SemanticIndex': 0, 'Format': 'R32G32B32_FLOAT', 'ByteWidth': 12, 'Category': 'Position'},
                {'SemanticName': 'TEXCOORD', 'SemanticIndex': 0, 'Format': 'R16G16_FLOAT', 'ByteWidth': 4, 'Category': 'Texcoord'},
            ]}],
        })
        context = self.build_context()
        plan = prepare_routing(self.model, context, False)
        self.assertEqual(plan['assignments'], [0, 0])
        self.assertEqual(plan['issues'], [])
        self.assertEqual(plan['counts'], dict(unchanged=2, reassigned=0, ambiguous=0,
                                             incompatible=0, draw_state=0, island=0))
        self.assertEqual(list(plan['loop_components']), [0, 0, 0, 0, 0, 0])
        # Localization has nothing to serialize, and no draw may be re-cloned.
        self.assertEqual(localize_blendindices(
            context, self.model.merged_object.components, self.model.wwmi_info.components,
            self.model.draw_ib, plan['loop_components']), {})
        self.assertEqual(apply_routing(self.model, context, plan,
                                       ['LOD0.deadbeef-0', 'LOD0.deadbeef-1']), [])
        self.assertEqual(self.model.submesh_drawcall_groups, [[self.draw], []])
        # The source keeps its own groups: routing never deletes user data.
        self.assertEqual([group.name for group in self.obj.vertex_groups], ['10', '30', '20'])

    def test_weighted_layout_without_index_element_still_fails(self):
        """Keep the corrupt-workspace guard beside the static exemption.

        Only a layout that declares no Blend category at all may skip routing.
        A weighted layout whose BLENDINDICES element vanished would otherwise
        export global bone ids as local ones, so it must still raise instead of
        producing a silently wrong mod.
        """
        self.game_type = D3D11GameType.from_submesh_json_dict({
            'WorkGameType': 'routing_weight_corrupt_test', 'CategoryBufferList': [{'D3D11ElementList': [
                {'SemanticName': 'POSITION', 'SemanticIndex': 0, 'Format': 'R32G32B32_FLOAT', 'ByteWidth': 12, 'Category': 'Position'},
                {'SemanticName': 'BLENDWEIGHT', 'SemanticIndex': 0, 'Format': 'R32G32B32A32_FLOAT', 'ByteWidth': 16, 'Category': 'Blend'},
            ]}],
        })
        context = self.build_context()
        with self.assertRaisesRegex(ValueError, 'missing bone index export layout'):
            prepare_routing(self.model, context, False)

    def test_incompatible_faces_reject_all_proposed_moves(self):
        """Keep one valid proposal beside one genuinely impossible triangle.
        Failure must preserve the original owner list instead of partly routing.
        """
        # Make the first triangle impossible while the second still fits target 1.
        # No partial FACE ownership or blueprint mutation may survive the failure.
        self.obj.vertex_groups['20'].add([0], .001, 'REPLACE')
        context = self.build_context()
        attribute = context.mesh.attributes[DrawRangeUtils.OWNER_ATTRIBUTE]
        before = [entry.value for entry in attribute.data]
        with self.assertRaises(ValueError):
            prepare_routing(self.model, context, True)
        report = json.loads(latest_report()[REPORT_DATA])
        self.assertEqual(report['counts']['incompatible'], 1)
        self.assertEqual(report['counts']['reassigned'], 1)
        self.assertEqual([entry.value for entry in attribute.data], before)
        self.assertEqual(self.model.submesh_drawcall_groups, [[self.draw], []])
        self.assertEqual(report['objects'][self.obj.name]['issues'][0]['unassignable_vertices'], [0])


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(BlenderRoutingTests))
    addon.unregister()
    if not result.wasSuccessful():
        raise AssertionError('WWMI routing Blender regressions failed')
