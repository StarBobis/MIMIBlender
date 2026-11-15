"""Compare decoded Naraka triangles before and after real P separation.

Run with Blender --background --factory-startup --python-exit-code 1 --python.
Only workspace metadata is synthetic; mesh conversion uses production code.
The test checks position/UV pairs through IB, rather than VB ordering.
"""
import importlib
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import bpy
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
importlib.import_module(ROOT.name).register()
from MIMIBlender.common.global_config import GlobalConfig, LogicName
from MIMIBlender.model.submesh_model import SubMeshModel
from MIMIBlender.model.draw_call_model import DrawCallModel
from MIMIBlender.model.drawib_model import DrawIBModel

# Match the conventional Naraka position and primary texcoord streams.
# Shared corners deliberately have UV seams between adjacent panels.
# Separation duplicates shared vertices, so raw VB equality is inappropriate.
ELEMENTS = [
    dict(SemanticName=name, SemanticIndex=0, Format=fmt, ByteWidth=width, Category=category)
    for name, fmt, width, category in [
        ('POSITION', 'R32G32B32_FLOAT', 12, 'Position'),
        ('NORMAL', 'R32G32B32_FLOAT', 12, 'Position'),
        ('TANGENT', 'R32G32B32A32_FLOAT', 16, 'Position'),
        ('TEXCOORD', 'R32G32_FLOAT', 8, 'Texcoord'),
    ]
]
METADATA = SimpleNamespace(MatchCS='', MatchUAVBytes=0,
                          JsonDict={'CategoryBufferList': [{'D3D11ElementList': ELEMENTS}]})


class NarakaSplitUvTests(unittest.TestCase):
    def setUp(self):
        # No saved user scene, cache, or generated Mod is touched.
        bpy.ops.object.select_all(action='SELECT')
        bpy.ops.object.delete(use_global=False)
        GlobalConfig.logic_name = LogicName.Naraka
        mesh = bpy.data.meshes.new('split_uv_mesh')
        mesh.from_pydata([(x, y, 0) for x in range(4) for y in range(2)], [],
                         [(2*x, 2*x+2, 2*x+3, 2*x+1) for x in range(3)])
        uv = mesh.uv_layers.new(name='TEXCOORD.xy')
        for face in mesh.polygons:
            for corner, loop in enumerate(face.loop_indices):
                uv.data[loop].uv = [(0.1, 0.2), (0.3, 0.2), (0.3, 0.4), (0.1, 0.4)][corner]
                uv.data[loop].uv.x += face.index * 0.25
        obj = bpy.data.objects.new('panel', mesh)
        bpy.context.scene.collection.objects.link(obj)
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        self.obj = obj

    def export(self, objects):
        # Only path lookup and workspace JSON loading are replaced.
        # Temporary copies, triangulation, join, packing and range alignment run.
        draws = [DrawCallModel(obj_name=obj.name, submesh_name='LOD0.12345678-0') for obj in objects]
        with patch('MIMIBlender.model.submesh_model.MMTWorkSpace.check_and_get_submesh_json_path', return_value='synthetic.json'), patch('MIMIBlender.model.submesh_model.SubmeshJson', return_value=METADATA):
            return SubMeshModel(drawcall_model_list=draws)

    def decoded(self, model, ib=None):
        # Decode both streams using the SAME output index, as the GPU does.
        # Canonicalize corners and triangles without hiding UV/position mismatch.
        position = np.frombuffer(model.category_buffer_dict['Position'], '<f4').reshape(-1, 10)[:, :3]
        uv = np.frombuffer(model.category_buffer_dict['Texcoord'], '<f4').reshape(-1, 2)
        indices = np.asarray(model.ib if ib is None else ib).reshape(-1, 3)
        return sorted(tuple(sorted(tuple(np.round(np.r_[position[i], uv[i]], 5)) for i in tri)) for tri in indices)

    def separate(self):
        # Execute Blender's real P / Selection operation twice.
        # The remaining original quad and the two selected quads form three objects.
        for unused in range(2):
            bpy.ops.object.select_all(action='DESELECT')
            self.obj.select_set(True)
            bpy.context.view_layer.objects.active = self.obj
            mesh = self.obj.data
            for vertex in mesh.vertices:
                vertex.select = False
            for edge in mesh.edges:
                edge.select = False
            for face in mesh.polygons:
                face.select = face.index == len(mesh.polygons) - 1
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_mode(type='FACE')
            bpy.ops.mesh.separate(type='SELECTED')
            bpy.ops.object.mode_set(mode='OBJECT')
        return sorted(bpy.context.scene.objects, key=lambda obj: obj.name)

    def test_three_objects_keep_indexed_uvs(self):
        expected = self.decoded(self.export([self.obj]))
        objects = self.separate()
        self.assertEqual(len(objects), 3)
        snapshots = {obj.name: [tuple(item.uv) for item in obj.data.uv_layers[0].data] for obj in objects}
        for order in (objects, objects[::-1]):
            split = self.export(order)
            self.assertEqual(self.decoded(split), expected)
            # Check the actual split-IB assembly and drawindexed ranges too.
            assembly = DrawIBModel.__new__(DrawIBModel)
            assembly.submesh_model_list = [split]
            assembly.d3d11_game_type = split.d3d11_game_type
            buffers, bases, _, _ = assembly._assemble_category_buffers()
            index_lists, offsets, _ = assembly._assemble_split_ib_and_draw_offset(bases)
            drawn = []
            for draw in split.drawcall_model_list:
                count, start, base = map(int, draw.get_drawindexed_str(offsets).split('=')[1].split(','))
                self.assertEqual(base, 0)
                span = index_lists[split.submesh_name][start:start+count]
                drawn.extend(self.decoded(split, span))
            self.assertEqual(sorted(drawn), expected)
            # Temporary export processing must never modify source UV layers.
            for obj in objects:
                self.assertEqual([tuple(item.uv) for item in obj.data.uv_layers[0].data], snapshots[obj.name])


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(NarakaSplitUvTests)
    if not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful():
        raise RuntimeError('Naraka split UV regression failed')
