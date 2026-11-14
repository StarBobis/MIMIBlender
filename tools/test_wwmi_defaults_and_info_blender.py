"""Run in factory-startup Blender; never open or save a user project."""

import importlib
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import bpy
import numpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
addon = importlib.import_module(ROOT.name)
addon.register()

from MIMIBlender.blueprint.blueprint_node_base import MIMIBlueprintTree
from MIMIBlender.blueprint.blueprint_node_wwmi_mod_info import MIMINode_WWMI_Mod_Info
from MIMIBlender.common.global_config import GlobalConfig, LogicName
from MIMIBlender.common.m_ini_builder import M_IniBuilder
from MIMIBlender.games.wwmi.mesh_defaults import fill_missing_mesh_data
from MIMIBlender.games.wwmi.mod_info import collect_mod_info
from MIMIBlender.games.wwmi.exporter import Exporter
from MIMIBlender.model.blueprint_model import BluePrintModel


class WWMIExportOptionsTests(unittest.TestCase):
    def setUp(self):
        # Keep test preset changes local to the factory-startup process.
        self.previous_logic = GlobalConfig.logic_name
        GlobalConfig.logic_name = LogicName.WWMI
        self.addCleanup(setattr, GlobalConfig, 'logic_name', self.previous_logic)
        self.tree = bpy.data.node_groups.new('wwmi_metadata_test', MIMIBlueprintTree.bl_idname)
        self.addCleanup(bpy.data.node_groups.remove, self.tree)

    def mesh(self, name, offset=0):
        # Separated components expose incorrect per-object projection bounds.
        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata([(offset, 0, 0), (offset + 2, 0, 0), (offset, 0, 2)], [], [(0, 1, 2)])
        obj = bpy.data.objects.new(name, mesh)
        self.addCleanup(bpy.data.meshes.remove, mesh)
        self.addCleanup(bpy.data.objects.remove, obj)
        return obj

    def uv(self, mesh, name):
        values = numpy.empty(len(mesh.loops) * 2, dtype=numpy.float32)
        mesh.uv_layers[name].data.foreach_get('uv', values)
        return values.reshape(-1, 2)

    def test_default_colors_and_common_projection(self):
        first, second = self.mesh('first'), self.mesh('second', 10)
        fill_missing_mesh_data([first, second])
        # XZ extent is 12 across both parts, with 2% total padding.
        numpy.testing.assert_allclose(self.uv(first.data, 'TEXCOORD2.xy')[0], [0.01, 0.41833333], atol=1e-6)
        numpy.testing.assert_allclose(self.uv(second.data, 'TEXCOORD2.xy')[1], [0.99, 0.41833333], atol=1e-6)
        for obj in (first, second):
            numpy.testing.assert_allclose(obj.data.color_attributes['COLOR'].data[0].color, [0, .25, 0, 1])
            numpy.testing.assert_allclose(obj.data.color_attributes['COLOR1'].data[0].color, [0, 0, 0, 0])

    def test_existing_attributes_and_primary_uv_are_preserved(self):
        obj = self.mesh('existing')
        mesh = obj.data
        mesh.color_attributes.new(name='COLOR', type='FLOAT_COLOR', domain='CORNER').data.foreach_set('color', [.2, .3, .4, .5] * 3)
        mesh.uv_layers.new(name='TEXCOORD.xy').data.foreach_set('uv', [.2, .3] * 3)
        mesh.uv_layers.new(name='TEXCOORD2.xy').data.foreach_set('uv', [.8, .7] * 3)
        fill_missing_mesh_data([obj])
        # Preserve user layers; only the missing secondary UV copies primary.
        numpy.testing.assert_allclose(mesh.color_attributes['COLOR'].data[0].color, [.2, .3, .4, .5])
        numpy.testing.assert_allclose(self.uv(mesh, 'TEXCOORD1.xy'), [[.2, .3]] * 3)
        numpy.testing.assert_allclose(self.uv(mesh, 'TEXCOORD2.xy'), [[.8, .7]] * 3)

    def test_degenerate_projection_is_finite(self):
        obj = self.mesh('point_extent')
        for vertex in obj.data.vertices:
            vertex.co = (0, 0, 0)
        fill_missing_mesh_data([obj])
        numpy.testing.assert_allclose(self.uv(obj.data, 'TEXCOORD2.xy'), [[.5, .5]] * 3)
        fill_missing_mesh_data([])

    def test_metadata_reaches_resources_and_copies_logo_once(self):
        node = self.tree.nodes.new('MIMINode_WWMI_Mod_Info')
        node.mod_name, node.mod_author = 'Test Mod', 'Test Author'
        node.mod_desc, node.mod_link = 'Description', 'https://example.com/mod'
        node.mod_logo = str(ROOT / 'resources/DisplayRampMap.dds')
        output = self.tree.nodes.new('MIMINode_Result_Output')
        blueprint = BluePrintModel(tree=self.tree, output_node=output)
        exporter = Exporter.__new__(Exporter)
        exporter.blueprint_model = blueprint
        exporter.mod_info_sections_written = False
        ini = M_IniBuilder()
        # Redirect every output into tmp; test actual copying and INI paths.
        scratch = ROOT / 'tmp'
        scratch.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as folder:
            with patch.object(GlobalConfig, 'path_generatemod_texture_folder', return_value=folder):
                for draw_ib in ('aaa', 'bbb'):
                    exporter.add_resource_mod_info_section_default(ini, SimpleNamespace(draw_ib=draw_ib))
            lines = [line for section in ini.ini_section_list for line in section.SectionLineList]
            self.assertEqual(lines.count('[ResourceModName]'), 1)
            for value in ('Test Mod', 'Test Author', 'Description', 'https://example.com/mod'):
                self.assertIn('data = "' + value + '"', lines)
            self.assertIn('filename = ' + GlobalConfig.ini_texture_filename('WWMIModLogo.dds'), lines)
            self.assertEqual((Path(folder) / 'WWMIModLogo.dds').read_bytes(), Path(node.mod_logo).read_bytes())

    def test_metadata_is_wwmi_only_and_rejects_duplicates(self):
        self.assertTrue(MIMINode_WWMI_Mod_Info.poll(self.tree))
        self.tree.nodes.new('MIMINode_WWMI_Mod_Info')
        self.tree.nodes.new('MIMINode_WWMI_Mod_Info')
        with self.assertRaises(ValueError):
            collect_mod_info(self.tree)
        # Existing saved nodes must not affect other presets after switching.
        GlobalConfig.logic_name = LogicName.GIMI
        self.assertFalse(MIMINode_WWMI_Mod_Info.poll(self.tree))
        self.assertEqual(collect_mod_info(self.tree), {})

    def test_metadata_node_copy_keeps_values(self):
        # Use the production blueprint clone path, not a hand-copied dictionary.
        # A non-default value catches loss during group/copy transformations.
        from MIMIBlender.blueprint.blueprint_node_group import _clone_node
        node = self.tree.nodes.new('MIMINode_WWMI_Mod_Info')
        node.mod_name = 'Copied Mod'
        other = bpy.data.node_groups.new('wwmi_metadata_copy', MIMIBlueprintTree.bl_idname)
        self.addCleanup(bpy.data.node_groups.remove, other)
        copied = _clone_node(node, other)
        self.assertEqual(copied.mod_name, 'Copied Mod')

    def test_metadata_preflight_rejects_invalid_input(self):
        node = self.tree.nodes.new('MIMINode_WWMI_Mod_Info')
        node.mod_name = 'invalid"name'
        with self.assertRaises(ValueError):
            collect_mod_info(self.tree)
        node.mod_name = 'Valid Name'
        node.mod_logo = str(ROOT / 'tmp/missing-mod-logo.dds')
        with self.assertRaises(ValueError):
            collect_mod_info(self.tree)

    def test_no_metadata_node_keeps_legacy_behavior(self):
        self.assertEqual(collect_mod_info(self.tree), {})
        exporter = Exporter.__new__(Exporter)
        exporter.mod_info_sections_written = False
        ini = M_IniBuilder()
        exporter.add_resource_mod_info_section_default(ini, SimpleNamespace(draw_ib='aaa'))
        lines = [line for section in ini.ini_section_list for line in section.SectionLineList]
        self.assertIn('data = "Unnamed Mod"', lines)
        self.assertIn('data = "Unknown Author"', lines)


try:
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(WWMIExportOptionsTests))
    if not result.wasSuccessful():
        raise AssertionError('WWMI defaults and metadata regressions failed')
finally:
    addon.unregister()
