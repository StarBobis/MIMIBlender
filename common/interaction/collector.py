"""Sample the Blender vertex groups of a mesh during the export.

The exported vertex order does not match the Blender vertex order: the
export splits a vertex at every hard edge and UV seam.  A control weight
therefore cannot be copied from the Blender vertex list; it has to be
sampled through the export's own loop mapping.

The export deletes the temporary merged mesh right after it produced the
buffers, so this sampling has to happen inside that window.  The generic
registry in common/m_export_vertex_attributes.py provides it.

Why the control groups are removed before the buffers are built
-----------------------------------------------------------------
The exporter reads every vertex group of the mesh as a skin weight.  A
control group is not a bone, so leaving it in place would add a second
weight to every vertex of the region, change the normalisation of the
real bone weights and shift the bone indices.

The weights are therefore read first and the groups are removed right
after, before the vertex and index buffers are built.  The weights are
kept on the temporary object, so the collector can still map them onto
the exported vertices afterwards.

Every vertex group with the control prefix of this feature is sampled,
not every group of the mesh: the other groups are bone groups and the
exporter reads them as skin weights.  The sampling cost is one pass over
the mesh, and the result is reused by whichever feature asks for it.
"""

import json

import numpy as np

from ..m_export_vertex_attributes import register_collector, register_preprocessor


# The key the sampled weights are stored under.
COLLECTOR_NAME = "interaction_vertex_group_weights"

# The prefix of the control vertex groups this feature creates.  The
# prefix keeps them apart from the numbered bone groups, which the
# exporter would otherwise treat as skin weights.
CONTROL_GROUP_PREFIX = "MimiInteraction_"

# The custom property the staged weights are kept on until the collector
# runs.  It lives on the temporary merged object, which is deleted right
# after the export, so nothing survives it.
STAGED_PROPERTY = "mimi_interaction_staged_weights"

# The sampling is only worth its cost when the export actually declares
# an interaction region.  The blueprint model flips this switch before the
# meshes are built, so an export without the feature pays nothing.
_ENABLED = False


def set_enabled(enabled):
    """Turn the sampling on or off and return the previous state."""
    global _ENABLED
    previous = _ENABLED
    _ENABLED = bool(enabled)
    return previous


def is_enabled():
    """Return True when the sampling runs during the export."""
    return _ENABLED


def stage_control_groups(merged_obj):
    """Read the control groups and remove them from the export mesh.

    The weights are read from the same evaluated mesh the exporter uses,
    because the loop indices of the exported vertex map belong to that
    mesh.  A modifier that changes the topology, such as a mirror, makes
    the two spaces differ, and reading the base mesh would silently
    produce no weights at all.

    The weights and the loop map are kept on the temporary object, so the
    collector can still map them onto the exported vertices afterwards.
    Removing the groups here keeps them out of the skin weights.
    """
    if not _ENABLED:
        return
    if merged_obj is None or merged_obj.type != 'MESH':
        return

    group_name_by_index = {
        vertex_group.index: vertex_group.name
        for vertex_group in merged_obj.vertex_groups
        if vertex_group.name.startswith(CONTROL_GROUP_PREFIX)
    }
    if not group_name_by_index:
        return

    # The exporter evaluates the object, resets the shape keys and then
    # triangulates the mesh when the tangents cannot be calculated.  The
    # same steps have to run here, otherwise the loop indices of the two
    # meshes do not describe the same loops.
    import bpy
    from ...utils.obj_utils import ObjUtils
    from ...utils.shapekey_utils import ShapeKeyUtils

    ShapeKeyUtils.reset_all_shapekey_values(merged_obj)
    evaluated_object = merged_obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    evaluated_mesh = evaluated_object.to_mesh()
    try:
        if len(evaluated_mesh.polygons) > 0:
            try:
                evaluated_mesh.calc_tangents()
            except RuntimeError:
                ObjUtils.mesh_triangulate(evaluated_mesh)
                evaluated_mesh.calc_tangents()

        group_weight_dict = read_weights_from_evaluated_mesh(
            evaluated_mesh, group_name_by_index)

        loop_vertex_index = [0] * len(evaluated_mesh.loops)
        evaluated_mesh.loops.foreach_get("vertex_index", loop_vertex_index)
    finally:
        # The clear call belongs to the evaluated object, not to the mesh.
        evaluated_object.to_mesh_clear()

    if not group_weight_dict:
        return

    merged_obj[STAGED_PROPERTY] = json.dumps({
        "weights_by_group": group_weight_dict,
        "loop_vertex_index": loop_vertex_index,
    })

    # The groups are removed in reverse order, so the indices of the
    # remaining groups do not shift while they are being removed.
    control_group_list = [
        vertex_group for vertex_group in merged_obj.vertex_groups
        if vertex_group.name.startswith(CONTROL_GROUP_PREFIX)
    ]
    for vertex_group in reversed(control_group_list):
        merged_obj.vertex_groups.remove(vertex_group)


def read_weights_from_evaluated_mesh(evaluated_mesh, group_name_by_index):
    """Return the weight of every vertex of the evaluated mesh.

    The evaluated mesh keeps the group membership of its vertices, so a
    mirrored vertex carries the mirrored weight.  It has no vertex group
    collection of its own, so the group names come from the object.
    """
    group_weight_dict = {}
    if len(evaluated_mesh.vertices) == 0:
        return group_weight_dict

    vertex_index_list = []
    group_index_list = []
    weight_list = []
    for vertex in evaluated_mesh.vertices:
        for membership in vertex.groups:
            if membership.group not in group_name_by_index:
                continue
            vertex_index_list.append(vertex.index)
            group_index_list.append(membership.group)
            weight_list.append(membership.weight)

    if not vertex_index_list:
        return group_weight_dict

    vertex_indices = np.array(vertex_index_list, dtype=np.int64)
    group_indices = np.array(group_index_list, dtype=np.int64)
    weights = np.array(weight_list, dtype=np.float64)

    for group_index, group_name in group_name_by_index.items():
        selected = group_indices == group_index
        if not selected.any():
            continue
        # The pairs are stored instead of a dictionary, because a JSON
        # object only accepts string keys and the vertex index would not
        # survive the round trip as a number.
        group_weight_dict[group_name] = [
            [int(vertex_indices[position]), float(weights[position])]
            for position in np.where(selected)[0]
        ]

    return group_weight_dict


def map_weights_to_exported_vertices(loop_vertex_index, index_loop_id_dict, group_weight_dict):
    """Return one weight per exported vertex for every sampled group.

    index_loop_id_dict maps an exported vertex index to the loop it came
    from.  The loop carries the vertex, and that vertex carries the group
    membership.  The loop map has to come from the same mesh as the
    weights, otherwise the two index spaces do not match.
    """
    mapped_dict = {}
    exported_vertex_count = len(index_loop_id_dict)
    if exported_vertex_count == 0 or not group_weight_dict:
        return mapped_dict

    exported_index_list = sorted(index_loop_id_dict.keys())
    loop_index_array = np.array(
        [index_loop_id_dict[index] for index in exported_index_list], dtype=np.int64)

    if len(loop_index_array) and int(loop_index_array.max()) >= len(loop_vertex_index):
        raise ValueError("The exported vertex map refers to loop "
                         + str(int(loop_index_array.max()))
                         + ", but the evaluated mesh only has "
                         + str(len(loop_vertex_index)) + " loops. "
                         + "The control weights cannot be placed on the exported vertices.")

    blender_vertex_array = np.array(loop_vertex_index, dtype=np.int64)[loop_index_array]

    for group_name, vertex_weight_pair_list in group_weight_dict.items():
        vertex_weight_dict = {
            int(vertex_index): float(weight)
            for vertex_index, weight in vertex_weight_pair_list
        }
        weights = np.zeros(exported_vertex_count, dtype=np.float64)
        for position, blender_vertex in enumerate(blender_vertex_array):
            weight = vertex_weight_dict.get(int(blender_vertex), 0.0)
            weights[position] = weight
        mapped_dict[group_name] = weights

    return mapped_dict


def collect_vertex_group_weights(merged_obj, submesh_model):
    """Collector entry point used by the export registry."""
    if not _ENABLED:
        # Nothing declared an interaction region, so the weights are not
        # needed and the mesh is not touched at all.
        return None

    index_loop_id_dict = getattr(submesh_model, "index_vertex_id_dict", None)
    if not index_loop_id_dict:
        return None

    staged = merged_obj.get(STAGED_PROPERTY, None)
    if not staged:
        return None

    staged_dict = json.loads(staged)

    mapped_dict = map_weights_to_exported_vertices(
        staged_dict["loop_vertex_index"],
        index_loop_id_dict,
        staged_dict["weights_by_group"],
    )
    if not mapped_dict:
        return None

    return {
        "weights_by_group": mapped_dict,
        "vertex_count": len(index_loop_id_dict),
    }


collect_vertex_group_weights.collector_name = COLLECTOR_NAME
stage_control_groups.collector_name = COLLECTOR_NAME


def register():
    """Register the preprocessor and the collector."""
    register_preprocessor(stage_control_groups)
    register_collector(collect_vertex_group_weights)


def unregister():
    """Remove the preprocessor and the collector."""
    from ..m_export_vertex_attributes import unregister_collector, unregister_preprocessor
    unregister_collector(collect_vertex_group_weights)
    unregister_preprocessor(stage_control_groups)
