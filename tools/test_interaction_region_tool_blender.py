"""Blender check: the interaction region tool works in Blender 5.2.

The tool that creates the control group of a region is the only way the
user can set a region up, so it has to work in the Blender version the
add-on supports.  Two things broke it: the edit mode is called
"EDIT_MESH" since Blender 5.2, and the vertex group has no element list
any more.

The test runs the real operator on a real mesh and checks that:

- the operator accepts the mesh edit mode,
- the control group is created with the interaction prefix,
- the group carries the feathered weights,
- the region row of the node is filled in,
- two objects with the same label get different groups, so a join cannot
  merge them.

Run with:
    blender --background --factory-startup --python tools/test_interaction_region_tool_blender.py
"""

import json
import os
import sys
import types

import bpy
import numpy as np


# The repository is loaded as a package so the production modules can use
# their own relative imports.  The package name is local to this process.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
package = types.ModuleType("interaction_region_test")
package.__path__ = [ROOT]
sys.modules[package.__name__] = package


def build_mesh(name, size=1.0):
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=2, y_subdivisions=2, size=size)
    obj = bpy.context.object
    obj.name = name
    return obj


def main():
    from interaction_region_test.blueprint import blueprint_interaction_region_tools as region_tools

    # The edit mode has to be recognised under both names.
    class FakeContext:
        mode = "EDIT_MESH"

    if not region_tools.is_edit_mode(FakeContext()):
        raise AssertionError("the edit mode EDIT_MESH was not recognised")

    FakeContext.mode = "EDIT"
    if not region_tools.is_edit_mode(FakeContext()):
        raise AssertionError("the edit mode EDIT was not recognised")

    FakeContext.mode = "OBJECT"
    if region_tools.is_edit_mode(FakeContext()):
        raise AssertionError("the object mode was taken for the edit mode")
    print("the edit mode names: OK")

    # The group name has to carry the object, so two objects with the same
    # label cannot end up in one group.
    first_name = region_tools.build_group_name("Chest", "Body")
    second_name = region_tools.build_group_name("Chest", "Hair")
    print("group names: %s and %s" % (first_name, second_name))
    if first_name == second_name:
        raise AssertionError("two objects with the same label share the group name")
    for group_name in (first_name, second_name):
        if not group_name.startswith(region_tools.GROUP_PREFIX):
            raise AssertionError("the group name misses the prefix: " + group_name)
    if "Body" not in first_name or "Hair" not in second_name:
        raise AssertionError("the group name does not carry the object name")
    print("the group names: OK")

    # Two labels that only differ in characters that are not allowed in a
    # name must still get their own group.
    spaced_name = region_tools.build_group_name("Region 1", "Body")
    tight_name = region_tools.build_group_name("Region1", "Body")
    print("the folded names: %s and %s" % (spaced_name, tight_name))
    if spaced_name == tight_name:
        raise AssertionError("two different labels share the group name")

    # The name has to be the same every time, or the group of a region
    # would be lost on the next run.
    if region_tools.build_group_name("Chest", "Body") != first_name:
        raise AssertionError("the group name is not stable")
    print("the folded names: OK")

    # The operator has to run on a real mesh in the real edit mode.
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()
    obj = build_mesh("Body")

    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')

    class FakeNode:
        class FakeEntry:
            label = "Chest"
            object_name = ""
            vertex_group = ""
            enabled = True

        def __init__(self):
            self.regions = [FakeNode.FakeEntry()]

    node = FakeNode()
    # The operator has to be registered before it can be called.
    bpy.utils.register_class(region_tools.MIMI_OT_InteractionCreateRegion)
    try:
        # The operator looks the node up in the space, so the lookup is
        # replaced by the node of the test.
        import interaction_region_test.blueprint.blueprint_node_interaction as node_module
        original_finder = node_module.find_interaction_node
        node_module.find_interaction_node = lambda context, tree_name, node_name: node
        try:
            result = bpy.ops.mimi.interaction_create_region(
                tree_name="Tree", node_name="Node", region_index=0, feather_rings=2)
        finally:
            node_module.find_interaction_node = original_finder
    finally:
        bpy.utils.unregister_class(region_tools.MIMI_OT_InteractionCreateRegion)

    print("the operator result: %s" % result)
    if "FINISHED" not in result:
        raise AssertionError("the operator did not finish: " + str(result))

    group_name_list = [group.name for group in obj.vertex_groups]
    print("the groups of the object: %s" % group_name_list)
    if not group_name_list:
        raise AssertionError("the operator created no group")
    if not group_name_list[0].startswith(region_tools.GROUP_PREFIX):
        raise AssertionError("the group misses the prefix: " + group_name_list[0])

    weighted_count = 0
    for vertex in obj.data.vertices:
        for membership in vertex.groups:
            if membership.weight > 0.0:
                weighted_count += 1
    print("the vertices with a weight: %d" % weighted_count)
    if weighted_count == 0:
        raise AssertionError("the group carries no weight")

    if not node.regions[0].vertex_group:
        raise AssertionError("the region row was not filled in")
    if node.regions[0].object_name != obj.name:
        raise AssertionError("the region row does not name the object")
    print("the region row: OK (%s / %s)"
          % (node.regions[0].object_name, node.regions[0].vertex_group))

    # A second run has to clear the old weights, so the group carries only
    # the vertices of the new selection.
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    # One single vertex is selected, so the second run has to drop the
    # weights of the other eight.  The operator is called in the edit
    # mode, because that is where it reads the selection from.
    #
    # The selection lives in the edit cage, which is not the mesh of the
    # object, so it is changed through the bmesh of the edit cage.  That
    # bmesh belongs to Blender and must not be freed.
    import bmesh
    edit_bmesh = bmesh.from_edit_mesh(obj.data)
    edit_bmesh.verts.ensure_lookup_table()
    for vertex in edit_bmesh.verts:
        vertex.select = False
    edit_bmesh.verts[0].select = True
    selected_count = sum(1 for vertex in edit_bmesh.verts if vertex.select)
    print("the selected vertices before the second run: %d" % selected_count)

    bpy.utils.register_class(region_tools.MIMI_OT_InteractionCreateRegion)
    try:
        import interaction_region_test.blueprint.blueprint_node_interaction as node_module
        original_finder = node_module.find_interaction_node
        node_module.find_interaction_node = lambda context, tree_name, node_name: node
        try:
            second_result = bpy.ops.mimi.interaction_create_region(
                tree_name="Tree", node_name="Node", region_index=0, feather_rings=2)
        finally:
            node_module.find_interaction_node = original_finder
    finally:
        bpy.utils.unregister_class(region_tools.MIMI_OT_InteractionCreateRegion)
    print("the second operator result: %s" % second_result)

    group = obj.vertex_groups.get(node.regions[0].vertex_group)
    second_weighted = 0
    for vertex in obj.data.vertices:
        for membership in vertex.groups:
            if membership.group == group.index and membership.weight > 0.0:
                second_weighted += 1
    print("the group index: %d, the groups of the object: %s"
          % (group.index, [(item.index, item.name) for item in obj.vertex_groups]))
    print("the vertices with a weight after the second run: %d" % second_weighted)
    if second_weighted >= weighted_count:
        raise AssertionError("the second run kept the old weights: %d of %d"
                             % (second_weighted, weighted_count))

    # The weight of the region has to fall off towards its border, because
    # a constant weight has no gradient and the region could not be
    # pulled at all.  The production sampler and the production gradient
    # decide this.
    from interaction_region_test.common.interaction import collector as interaction_collector
    from interaction_region_test.common.interaction.weight_field import (
        compute_gradient_bound,
        compute_surface_gradients,
    )

    interaction_collector.set_enabled(True)
    try:
        interaction_collector.stage_control_groups(obj)
    finally:
        interaction_collector.set_enabled(False)

    staged = obj.get(interaction_collector.STAGED_PROPERTY, None)
    if not staged:
        raise AssertionError("the sampler stored no weights")
    staged_dict = json.loads(staged)
    group_name = node.regions[0].vertex_group
    if group_name not in staged_dict["weights_by_group"]:
        raise AssertionError("the sampler did not find the group")
    pairs = staged_dict["weights_by_group"][group_name]
    weight_dict = {int(index): float(weight) for index, weight in pairs}

    distinct_value_list = sorted(set(round(value, 4) for value in weight_dict.values()))
    print("the distinct weights of the region: %s" % distinct_value_list)
    if len(distinct_value_list) < 2:
        raise AssertionError("the weight does not fall off: " + str(distinct_value_list))

    mesh = obj.data
    positions = np.array([vertex.co[:] for vertex in mesh.vertices], dtype=np.float64)
    weight_array = np.array(
        [weight_dict.get(vertex.index, 0.0) for vertex in mesh.vertices], dtype=np.float64)
    triangle_list = [
        [polygon.vertices[0], polygon.vertices[1], polygon.vertices[2]]
        for polygon in mesh.polygons]
    gradients = compute_surface_gradients(
        positions, weight_array, np.array(triangle_list, dtype=np.int64))
    gradient_bound = compute_gradient_bound(gradients)
    print("the gradient bound of the region: %f" % gradient_bound)
    if gradient_bound <= 1e-12:
        raise AssertionError("the region has no gradient, so it cannot be pulled")

    print("OK: the interaction region tool works in Blender 5.2")


if __name__ == "__main__":
    main()
