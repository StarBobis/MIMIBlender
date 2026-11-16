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

import os
import sys
import types

import bpy


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

    print("OK: the interaction region tool works in Blender 5.2")


if __name__ == "__main__":
    main()
