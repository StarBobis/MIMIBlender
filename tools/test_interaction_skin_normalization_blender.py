"""Regression: an active full-weight control group must not erase bones.

Run Blender in background with --factory-startup --python this_file.py.
The fixture covers enabled and disabled interaction, including a vertex
assigned fully to bone 12 and partially weighted neighbouring vertices.
"""
import sys
import types
from pathlib import Path
import bpy

root = Path(__file__).resolve().parents[1]
package = types.ModuleType('interaction_normalization_test')
package.__path__ = [str(root)]
sys.modules[package.__name__] = package
from interaction_normalization_test.model.submesh_model import SubMeshModel
from interaction_normalization_test.common.interaction import collector


def check(enabled):
    """Run the production stages in order, without touching a user scene."""
    bpy.ops.mesh.primitive_plane_add()
    obj = bpy.context.object
    for number in range(13):
        obj.vertex_groups.new(name=str(number))
    obj.vertex_groups['12'].add([0,1],1.0,'REPLACE')
    obj.vertex_groups['12'].add([2,3],.75,'REPLACE')
    obj.vertex_groups['5'].add([2,3],.25,'REPLACE')
    helper = obj.vertex_groups.new(name='MimiInteraction_Chest')
    helper.add([0,1],1.0,'REPLACE')
    helper.add([2,3],.75,'REPLACE')
    obj.vertex_groups.active_index = helper.index
    model = SubMeshModel.__new__(SubMeshModel)
    model.d3d11_game_type = types.SimpleNamespace(OrderedCategoryNameList=['Blend'])
    # The early stage must leave both fields untouched. The active helper
    # is the exact trigger that previously erased the full-weight vertex.
    model._normalize_temp_obj_for_export(obj)
    assert obj.vertex_groups['12'].weight(0)==1.0
    assert helper.weight(0)==1.0
    collector.set_enabled(enabled)
    collector.stage_control_groups(obj)
    model._normalize_temp_obj_for_export(obj)
    assert len(obj.vertex_groups)==13
    for vertex in obj.data.vertices:
        assert abs(sum(g.weight for g in vertex.groups)-1)<1e-6
    assert obj.vertex_groups['12'].weight(0)==1.0
    assert obj.vertex_groups['12'].weight(2)==.75
    assert obj.vertex_groups['5'].weight(2)==.25
    print('PASS: original skin weights retained, interaction enabled =',enabled)


check(True)
check(False)
