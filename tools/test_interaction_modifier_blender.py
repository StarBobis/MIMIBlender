"""Blender check: the control weights survive a topology changing modifier.

The exporter builds its vertex and index buffers from the evaluated mesh,
so the loop indices of the exported vertex map belong to that mesh.  A
mirror modifier doubles the topology, and the base mesh and the evaluated
mesh then describe different loops.  Reading the weights from the wrong
mesh produces no weights at all, and the feature would silently do
nothing in the game.

This test builds a mesh with a mirror modifier, a control group and a
bone group, then runs the production sampler and checks that:

- the control weights land on the exported vertices,
- the mirrored half carries the mirrored weight, and
- the control group is gone afterwards, so it cannot be read as a skin
  weight.

Run with:
    blender --background --factory-startup --python tools/test_interaction_modifier_blender.py
"""

import json
import os
import sys
import types

import bpy


# The repository is loaded as a package so the production modules can use
# their own relative imports.  The package name is local to this process.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
package = types.ModuleType("interaction_blender_test")
package.__path__ = [ROOT]
sys.modules[package.__name__] = package


def build_scene():
    """Return an object with a control group, a bone group and a mirror."""
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()

    bpy.ops.mesh.primitive_grid_add(x_subdivisions=2, y_subdivisions=2)
    obj = bpy.context.object
    obj.name = "InteractionProbe"

    control_group = obj.vertex_groups.new(name="MimiInteraction_Chest")
    bone_group = obj.vertex_groups.new(name="0")

    # Give the first half of the grid a control weight and a bone weight.
    original_weighted_count = 0
    for vertex in obj.data.vertices:
        if vertex.co.x < 0.0:
            control_group.add([vertex.index], 1.0, 'REPLACE')
            bone_group.add([vertex.index], 1.0, 'REPLACE')
            original_weighted_count += 1
    if original_weighted_count == 0:
        raise AssertionError("the fixture did not weight any vertex")

    modifier = obj.modifiers.new(name="Mirror", type='MIRROR')
    modifier.use_axis = (True, False, False)
    return obj, original_weighted_count


def check_rest_resource_path():
    """The Rest resource must point at the file the exporter really writes.

    The bind pose of the deformation is the exported position buffer.  If
    the name in the INI and the name on the disk drift apart, the game
    loads no bind pose and the mesh collapses to the world origin.
    """
    from interaction_blender_test.common.global_config import GlobalConfig

    file_name = "LOD0.test1234-Position.buf"
    ini_name = GlobalConfig.ini_buffer_filename(file_name)

    # The name has to carry the shared buffer folder, otherwise the game
    # looks for the file in the wrong place.
    expected_name = GlobalConfig.BUFFER_OUTPUT_SUBFOLDER + "\\" + file_name
    print("INI resource name: %s" % ini_name)
    if ini_name != expected_name:
        raise AssertionError("the resource name is " + ini_name
                             + " but the shared folder rule gives " + expected_name)

    # The name is relative to the INI, so it has to resolve into the
    # folder the exporter writes the buffer into.
    resolved = os.path.normpath(os.path.join("ModFolder", ini_name))
    expected = os.path.normpath(os.path.join(
        "ModFolder", GlobalConfig.BUFFER_OUTPUT_SUBFOLDER, file_name))
    if resolved != expected:
        raise AssertionError("the resource name resolves to " + resolved
                             + " but the exporter writes " + expected)
    print("rest resource path: OK")


def main():
    from interaction_blender_test.common.interaction import collector as interaction_collector
    from interaction_blender_test.common.interaction.collector import CONTROL_GROUP_PREFIX

    obj, original_weighted_count = build_scene()

    base_vertex_count = len(obj.data.vertices)
    evaluated_object = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    evaluated_mesh = evaluated_object.to_mesh()
    evaluated_vertex_count = len(evaluated_mesh.vertices)
    evaluated_object.to_mesh_clear()
    print("base vertices: %d, evaluated vertices: %d" % (base_vertex_count, evaluated_vertex_count))
    if evaluated_vertex_count <= base_vertex_count:
        raise AssertionError("the mirror modifier did not change the topology, the test proves nothing")

    interaction_collector.set_enabled(True)
    try:
        # The production sampler runs on the merged export object.
        interaction_collector.stage_control_groups(obj)

        staged = obj.get(interaction_collector.STAGED_PROPERTY, None)
        if not staged:
            raise AssertionError("the sampler stored no weights")
        staged_dict = json.loads(staged)

        weights = staged_dict["weights_by_group"]
        group_name = CONTROL_GROUP_PREFIX + "Chest"
        if group_name not in weights:
            raise AssertionError("the control group was not sampled")
        weight_dict = {int(vertex_index): float(weight)
                       for vertex_index, weight in weights[group_name]}

        weighted_vertex_count = len(weight_dict)
        print("sampled weighted vertices: %d (the base mesh had %d)"
              % (weighted_vertex_count, original_weighted_count))
        if weighted_vertex_count < original_weighted_count:
            raise AssertionError(
                "the sampled weights lost vertices: %d weighted vertices for %d weighted base vertices"
                % (weighted_vertex_count, original_weighted_count))

        # The mirrored half has to carry the mirrored weight.
        mirrored_weighted = [index for index in weight_dict if index >= base_vertex_count]
        print("weighted vertices in the mirrored half: %d" % len(mirrored_weighted))
        if not mirrored_weighted:
            raise AssertionError("the mirrored half carries no weight")

        # The loop map has to describe the evaluated mesh.
        loop_vertex_index = staged_dict["loop_vertex_index"]
        if len(loop_vertex_index) == 0:
            raise AssertionError("the loop map is empty")

        # The control group has to be gone, so it cannot become a skin weight.
        remaining_group_names = [group.name for group in obj.vertex_groups]
        print("remaining groups: %s" % remaining_group_names)
        for group_name in remaining_group_names:
            if group_name.startswith(CONTROL_GROUP_PREFIX):
                raise AssertionError("the control group was not removed from the export mesh")
        if not any(group.name.isdigit() for group in obj.vertex_groups):
            raise AssertionError("the bone group was removed as well")

    finally:
        interaction_collector.set_enabled(False)

    check_rest_resource_path()
    print("OK: the control weights survive a mirror modifier and the group is removed")


if __name__ == "__main__":
    main()
