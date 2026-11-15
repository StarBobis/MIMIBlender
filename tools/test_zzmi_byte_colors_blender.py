"""Verify ZZMI byte control colors through real Blender import and export."""
# Run with Blender --background --factory-startup --python-exit-code 1 --python.
# Fixtures exercise all 256 byte values, including independent alpha values.
# The importer and exporter both run production code in a disposable scene.
# No user projects, installed add-ons or game Mod directories are changed.
import sys
import importlib
from pathlib import Path
from unittest.mock import patch
import unittest
import bpy
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
# Register real scene settings used by the production import workflow.
importlib.import_module(ROOT.name).register()
from MIMIBlender.common.mesh_create_helper import MeshCreateHelper
from MIMIBlender.common.obj_buffer_helper import ObjBufferHelper
from MIMIBlender.common.d3d11_element import D3D11Element
from MIMIBlender.common.global_config import GlobalConfig


def element(name, fmt, width):
    # Keep fixture layout independent of any installed game workspace.
    return D3D11Element(name, 0, fmt, width, 'vb0', 'trianglelist', 'Position', 0)


class ByteControlColors(unittest.TestCase):
    def setUp(self):
        # Restore global preset state even when an assertion fails.
        self.previous = GlobalConfig.logic_name
        GlobalConfig.logic_name = 'ZZMI'
        self.addCleanup(setattr, GlobalConfig, 'logic_name', self.previous)

    def test_all_bytes_import_export(self):
        # Every source vertex participates in one nondegenerate triangle.
        # Independent alpha checks that RGB transfer never touches alpha.
        ramp = np.arange(256, dtype=np.uint8)
        rgba = np.column_stack((ramp, 255-ramp, np.roll(ramp, 73), np.roll(ramp, 11)))
        colors = np.repeat(rgba, 3, axis=0)
        points = np.tile(np.array([[0,0,0], [1,0,0], [0,1,0]], np.float32), (256,1))
        position = element('POSITION', 'R32G32B32_FLOAT', 12)
        color = element('COLOR', 'R8G8B8A8_UNORM', 4)
        # Material discovery is unrelated to the vertex payload contract.
        with patch.object(MeshCreateHelper, 'create_bsdf_with_diffuse_linked'):
            obj = MeshCreateHelper.create_mesh_object(
                'byte_color_fixture', '', 'ZZMI', 'fixture', [position, color],
                {'POSITION': points, 'COLOR': colors}, np.arange(len(points)),
                len(points), len(points), 256)
        # Real import must retain the stored byte-domain values.
        result = ObjBufferHelper._parse_color(obj.data, len(obj.data.loops), 'COLOR', color)
        np.testing.assert_array_equal(result, colors)

    def test_legacy_byte_layer(self):
        # Existing projects store control bytes through the legacy sRGB view.
        # The regression is visible at 128: a linear read exports roughly 55.
        mesh = bpy.data.meshes.new('legacy_byte_fixture')
        mesh.from_pydata([(0,0,0), (1,0,0), (0,1,0)], [], [(0,1,2)])
        layer = mesh.color_attributes.new(name='COLOR', type='BYTE_COLOR', domain='CORNER')
        for item in layer.data:
            item.color_srgb = (128/255, 128/255, 0, 73/255)
        color = element('COLOR', 'R8G8B8A8_UNORM', 4)
        result = ObjBufferHelper._parse_color(mesh, 3, 'COLOR', color)
        np.testing.assert_array_equal(result, [[128,128,0,73]]*3)
        # Other presets retain their established linear interpretation.
        GlobalConfig.logic_name = 'GIMI'
        other = ObjBufferHelper._parse_color(mesh, 3, 'COLOR', color)
        np.testing.assert_array_equal(other, [[55,55,0,73]]*3)

    def test_float_layer_stays_linear(self):
        # FLOAT_COLOR is intentionally outside the stored-byte policy.
        mesh = bpy.data.meshes.new('float_color_fixture')
        mesh.from_pydata([(0,0,0), (1,0,0), (0,1,0)], [], [(0,1,2)])
        layer = mesh.color_attributes.new(name='COLOR', type='FLOAT_COLOR', domain='CORNER')
        for item in layer.data:
            item.color = (.5,.25,.75,.125)
        color = element('COLOR', 'R32G32B32A32_FLOAT', 16)
        result = ObjBufferHelper._parse_color(mesh, 3, 'COLOR', color)
        np.testing.assert_array_equal(result, [[.5,.25,.75,.125]]*3)


if __name__ == '__main__':
    # Propagate failures to Blender's --python-exit-code gate.
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ByteControlColors)
    if not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful():
        raise RuntimeError('ZZMI color regression')
