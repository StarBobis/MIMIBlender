"""Exercise node snapshots, structured buffer policies and MMT mark transfer."""

import importlib
import json
from pathlib import Path
import re
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import bpy
import numpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
addon = importlib.import_module(ROOT.name)
addon.register()
from MIMIBlender.utils.outline_utils import rebuild_outline, weld_directions
from MIMIBlender.common.obj_buffer_helper import ObjBufferHelper
from MIMIBlender.common.global_config import GlobalConfig, LogicName
from MIMIBlender.common.m_ini_builder import M_IniBuilder
from MIMIBlender.blueprint.blueprint_node_base import MIMIBlueprintTree
from MIMIBlender.model.blueprint_model import BluePrintModel
from MIMIBlender.workspace.texture_metadata_helper import TextureMetadataResolver
from MIMIBlender.games.zzmi import ExportZZMI


DTYPE = numpy.dtype([('POSITION', 'f4', 3), ('NORMAL', 'f4', 3), ('TANGENT', 'f4', 4),
                     ('TEXCOORD1', 'f4', 2), ('COLOR', 'u1', 4)])


def fixture():
    # An obtuse and a right-angle corner share position, but keep separate IDs.
    # Distinct input bytes expose accidental writes outside the chosen field.
    vb = numpy.zeros(6, dtype=DTYPE)
    vb['POSITION'] = [(0, 0, 0), (1, 0, 0), (-1, 1, 0), (0, 0, 0), (0, 1, 0), (0, 0, 1)]
    vb['NORMAL'] = [(0, 0, 1)] * 3 + [(1, 0, 0)] * 3
    vb['TANGENT'] = [(1, 0, 0, -1)] * 6
    vb['TEXCOORD1'] = (.25, .75)
    vb['COLOR'] = (10, 20, 30, 73)
    return vb, numpy.arange(6)


class OutlinePolicyTests(unittest.TestCase):
    def setUp(self):
        self.previous = GlobalConfig.logic_name
        self.addCleanup(setattr, GlobalConfig, 'logic_name', self.previous)
        self.options = dict(mode='MODERN', precision=8, custom_normals=False, gate=10, himi_target='COLOR')

    def test_obtuse_weld_and_tangent_convention(self):
        vb, ib = fixture()
        original = vb.tobytes()
        for preset in ('GIMI', 'SRMI'):
            result = rebuild_outline(vb, ib, preset, self.options)
            numpy.testing.assert_allclose(result['TANGENT'][0, :3], [2 / numpy.sqrt(13), 0, 3 / numpy.sqrt(13)], atol=1e-6)
            self.assertEqual(result['TANGENT'][0, 3], 1)
            # Only TANGENT is owned by this policy; original input is immutable.
            for field in ('POSITION', 'NORMAL', 'COLOR', 'TEXCOORD1'):
                self.assertEqual(result[field].tobytes(), vb[field].tobytes())
        self.assertEqual(vb.tobytes(), original)

    def test_himi_color_preserves_alpha_and_other_streams(self):
        vb, ib = fixture()
        result = rebuild_outline(vb, ib, 'HIMI', self.options)
        numpy.testing.assert_array_equal(result['COLOR'][:, 3], vb['COLOR'][:, 3])
        numpy.testing.assert_array_equal(result['COLOR'][0, :3], [198, 128, 234])
        self.assertEqual(result['TANGENT'].tobytes(), vb['TANGENT'].tobytes())

    def test_zzmi_projection_gate_and_tangent_preservation(self):
        vb, ib = fixture()
        result = rebuild_outline(vb, ib, 'ZZMI', self.options)
        numpy.testing.assert_allclose(result['TEXCOORD1'][0], [2 / numpy.sqrt(13), 0], atol=1e-6)
        self.assertEqual(result['TANGENT'].tobytes(), vb['TANGENT'].tobytes())
        # Raising the threshold masks this corner without changing its basis.
        gated = rebuild_outline(vb, ib, 'ZZMI', dict(self.options, gate=60))
        numpy.testing.assert_allclose(gated['TEXCOORD1'][0], [0, 0])

    def test_precision_custom_normals_and_degenerate_faces(self):
        vb, ib = fixture()
        vb['POSITION'][3] += .00001
        coarse = weld_directions(vb['POSITION'], ib, precision=4)
        fine = weld_directions(vb['POSITION'], ib, precision=8)
        self.assertFalse(numpy.allclose(coarse[0], fine[0]))
        authored = rebuild_outline(vb, ib, 'GIMI', dict(self.options, custom_normals=True))
        numpy.testing.assert_allclose(authored['TANGENT'][0, :3], vb['NORMAL'][0])
        vb['POSITION'] = 0
        result = rebuild_outline(vb, ib, 'ZZMI', self.options)
        self.assertTrue(numpy.isfinite(result['TEXCOORD1']).all())

    def test_integer_direction_encoding(self):
        # Signed-byte directions must be decoded for math and quantized once.
        vb, ib = fixture()
        dtype = numpy.dtype([('POSITION', 'f4', 3), ('NORMAL', 'i1', 4), ('TANGENT', 'i1', 4)])
        packed = numpy.zeros(6, dtype=dtype)
        packed['POSITION'] = vb['POSITION']
        packed['NORMAL'][:, :3] = vb['NORMAL'] * 127
        packed['TANGENT'] = (127, 0, 0, -127)
        result = rebuild_outline(packed, ib, 'GIMI', self.options)
        numpy.testing.assert_array_equal(result['TANGENT'][0], [70, 0, 106, 127])

    def test_off_and_legacy_preserve_existing_export_contract(self):
        GlobalConfig.logic_name = LogicName.GIMI
        vb, ib = fixture()
        game = SimpleNamespace(OrderedFullElementList=['POSITION', 'NORMAL', 'TANGENT', 'COLOR'])
        obj = {'3DMigoto:RecalculateTANGENT': True}
        off = ObjBufferHelper.apply_outline_policy(obj, vb, ib, game, DTYPE, {'mode': 'OFF'})
        self.assertEqual(off.tobytes(), vb.tobytes())
        # Compare actual old production calls with the compatibility dispatcher.
        with patch.object(ObjBufferHelper, 'average_normal_color', side_effect=lambda obj, vertices, *args: vertices):
            expected = ObjBufferHelper.average_normal_tangent_xxmi(obj, vb, ib, game, DTYPE)
            actual = ObjBufferHelper.apply_outline_policy(obj, vb, ib, game, DTYPE, {'mode': 'LEGACY'})
        self.assertEqual(actual.tobytes(), expected.tobytes())

    def test_selected_output_snapshot_reaches_real_buffer_builder(self):
        GlobalConfig.logic_name = LogicName.GIMI
        tree = bpy.data.node_groups.new('outline_policy_fixture', MIMIBlueprintTree.bl_idname)
        self.addCleanup(bpy.data.node_groups.remove, tree)
        first = tree.nodes.new('MIMINode_Result_Output')
        second = tree.nodes.new('MIMINode_Result_Output')
        second.outline_mode = 'MODERN'
        second.outline_precision = 7
        model = BluePrintModel(tree=tree, output_node=second)
        self.assertEqual(first.outline_mode, 'LEGACY')
        self.assertEqual(model.outline_options['precision'], 7)
        vb, ib = fixture()
        mesh = bpy.data.meshes.new('outline_buffer_fixture')
        mesh.from_pydata(vb['POSITION'].tolist(), [], [(0, 1, 2), (3, 4, 5)])
        self.addCleanup(bpy.data.meshes.remove, mesh)
        game = SimpleNamespace(CategoryStrideDict={'All': DTYPE.itemsize}, get_real_category_stride_dict=lambda: {'All': DTYPE.itemsize})
        # The real builder retains the vertex IDs and ownership map while applying
        # the node snapshot to the category bytes before slicing the output.
        indices, categories, mapping = ObjBufferHelper.calc_index_vertex_buffer_unified(mesh, vb, {}, game, DTYPE, model.outline_options)
        self.assertEqual(indices, ib.tolist())
        self.assertEqual(mapping, {i: i for i in range(6)})
        packed = numpy.frombuffer(categories['All'].tobytes(), dtype=DTYPE)
        numpy.testing.assert_allclose(packed['TANGENT'][0, :3], [2 / numpy.sqrt(13), 0, 3 / numpy.sqrt(13)], atol=1e-6)

    def test_mmt_marks_survive_metadata_and_reach_slotfix(self):
        GlobalConfig.logic_name = LogicName.ZZMI
        # Read the actual MMT preset choices rather than a copied test list.
        mmt = ROOT.parent / 'SSMT5/src/views/MarkTexture/MarkTextureFull.vue'
        names = re.search(r'\bZZMI: \[([^\]]+)\]', mmt.read_text(encoding='utf-8')).group(1)
        names = re.findall(r"'([^']+)'", names)
        extended = [name for name in names if name.startswith(('Glow', 'Wengine'))]
        self.assertEqual(len(extended), 7)
        for name in extended + ['StockingMap']:
            # This is the existing JSON transport shape consumed by Blender.
            raw = json.loads(json.dumps([dict(MarkName=name, MarkType='Slot', MarkSlot='ps-t6', MarkFileName=name + '.dds')]))
            marks = TextureMetadataResolver.normalize_texture_markup_info_list(raw)
            submesh = SimpleNamespace(submesh_name='part', match_first_index=0, match_index_count=3, drawcall_model_list=[])
            drawib = SimpleNamespace(draw_ib='12345678', submesh_model_list=[submesh], submesh_ib_dict={'part': [0, 1, 2]},
                get_submesh_texture_override_suffix=lambda part: 'part', get_submesh_ib_resource_name=lambda part: 'ResourceIndex',
                get_submesh_texture_markup_info_list=lambda part: marks, obj_name_draw_offset={})
            exporter = ExportZZMI.__new__(ExportZZMI)
            exporter.blueprint_model = SimpleNamespace(keyname_mkey_dict={})
            ini = M_IniBuilder()
            with patch('MIMIBlender.games.zzmi.MIMIGlobalProperties.zzz_use_slot_fix', return_value=True), patch('MIMIBlender.games.zzmi.MIMIGlobalProperties.forbid_auto_texture_ini', return_value=False):
                exporter.add_unity_vs_texture_override_ib_sections(ini, drawib)
            lines = [line for section in ini.ini_section_list for line in section.SectionLineList]
            semantic = 'WengineFx' if name == 'StockingMap' else name
            binding = 'Resource\\ZZMI\\' + semantic + ' = ref ' + marks[0].get_resource_name()
            self.assertIn(binding, lines)
            self.assertLess(lines.index(binding), lines.index(r'run = CommandList\ZZMI\SetTextures'))

    def test_submesh_pipeline_preserves_source_and_applies_snapshot(self):
        from MIMIBlender.model.submesh_model import SubMeshModel
        from MIMIBlender.model.draw_call_model import DrawCallModel
        GlobalConfig.logic_name = LogicName.GIMI
        vb, _ib = fixture()
        mesh = bpy.data.meshes.new('outline_source_mesh')
        mesh.from_pydata(vb['POSITION'].tolist(), [], [(0, 1, 2), (3, 4, 5)])
        obj = bpy.data.objects.new('outline_source', mesh)
        bpy.context.scene.collection.objects.link(obj)
        self.addCleanup(bpy.data.meshes.remove, mesh)
        self.addCleanup(bpy.data.objects.remove, obj, do_unlink=True)
        mesh.uv_layers.new(name='TEXCOORD.xy').data.foreach_set('uv', [0, 0, 1, 0, 0, 1] * 2)
        obj.shape_key_add(name='Basis')
        bend = obj.shape_key_add(name='Bend')
        bend.data[2].co.z = 1
        source_shape = [tuple(vertex.co) for vertex in bend.data]
        source = [tuple(vertex.co) for vertex in mesh.vertices]
        elements = [dict(SemanticName=name, SemanticIndex=0, Format=fmt, ByteWidth=width, Category=category)
                    for name, fmt, width, category in (
                        ('POSITION', 'R32G32B32_FLOAT', 12, 'Position'),
                        ('NORMAL', 'R32G32B32_FLOAT', 12, 'Position'),
                        ('TANGENT', 'R32G32B32A32_FLOAT', 16, 'Position'),
                        ('TEXCOORD', 'R32G32_FLOAT', 8, 'Texcoord'))]
        metadata = SimpleNamespace(MatchCS='', MatchUAVBytes=0, JsonDict={'CategoryBufferList': [{'D3D11ElementList': elements}]})
        models = []
        for mode in ('OFF', 'MODERN'):
            draw = DrawCallModel(obj_name=obj.name, submesh_name='LOD0.12345678-0')
            with patch('MIMIBlender.model.submesh_model.MMTWorkSpace.check_and_get_submesh_json_path', return_value='fixture.json'), patch('MIMIBlender.model.submesh_model.SubmeshJson', return_value=metadata), patch('MIMIBlender.utils.export_utils.BlueprintExportHelper.get_current_shapekeyname_mkey_dict', return_value={'Bend': SimpleNamespace()}):
                models.append(SubMeshModel(drawcall_model_list=[draw], outline_options=dict(self.options, mode=mode)))
        self.assertEqual(models[0].ib, models[1].ib)
        self.assertNotEqual(models[0].category_buffer_dict['Position'].tobytes(), models[1].category_buffer_dict['Position'].tobytes())
        self.assertEqual(source, [tuple(vertex.co) for vertex in mesh.vertices])
        self.assertEqual(source_shape, [tuple(vertex.co) for vertex in bend.data])
        # Independent corner-angle calculation for the deformed first face.
        # Its tangent morph must be rebuilt, rather than reverting to raw TBN.
        angle = numpy.arccos(-1 / numpy.sqrt(3))
        expected = numpy.array([numpy.pi / 2, -angle / numpy.sqrt(2), angle / numpy.sqrt(2)])
        expected /= numpy.linalg.norm(expected)
        # The existing GIMI export path rotates the source by -90 degrees on X.
        expected = expected[[0, 2, 1]] * [1, 1, -1]
        shape = models[1].shape_key_buffer_dict['Bend'].element_vertex_ndarray
        numpy.testing.assert_allclose(shape['TANGENT'][0, :3], expected, atol=1e-6)
        self.assertEqual(len(mesh.uv_layers), 1)
        self.assertFalse(any(item.name.startswith('TEMP_SUBMESH') for item in bpy.data.objects))


try:
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(OutlinePolicyTests))
    if not result.wasSuccessful():
        raise AssertionError('Outline policy regressions failed')
finally:
    addon.unregister()
