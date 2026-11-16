"""Sample the Blender vertex groups of a mesh during the export.

The exported vertex order does not match the Blender vertex order: the
export splits a vertex at every hard edge and UV seam.  A control weight
therefore cannot be copied from the Blender vertex list; it has to be
sampled through the export's own loop mapping.

The export deletes the temporary merged mesh right after it produced the
buffers, so this sampling has to happen inside that window.  The generic
registry in common/m_export_vertex_attributes.py provides it.

Every vertex group of the mesh is sampled, not only the ones a feature
needs: the collector cannot know which groups will be used, because the
feature configuration is read after the meshes were built.  The sampling
cost is one pass over the mesh, and the result is reused by whichever
feature asks for it.
"""

import numpy as np

from ..m_export_vertex_attributes import register_collector


# The key the sampled weights are stored under.
COLLECTOR_NAME = "interaction_vertex_group_weights"

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


def read_vertex_group_weights(merged_obj):
    """Return every vertex group of the object mapped to its weights.

    The result maps the group name to a dictionary of Blender vertex index
    mapped to the weight of that vertex.  Vertices that are not a member
    of the group are not listed at all.
    """
    group_weight_dict = {}
    if merged_obj is None or merged_obj.type != 'MESH':
        return group_weight_dict

    mesh = merged_obj.data
    vertex_group_list = list(merged_obj.vertex_groups)
    if not vertex_group_list:
        return group_weight_dict

    # The Blender API has no bulk read for the group membership, so the
    # membership is collected in one pass and split per group afterwards.
    group_name_by_index = {}
    for vertex_group in vertex_group_list:
        group_name_by_index[vertex_group.index] = vertex_group.name

    vertex_index_list = []
    group_index_list = []
    weight_list = []
    for vertex in mesh.vertices:
        for membership in vertex.groups:
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
        group_weight_dict[group_name] = {
            int(vertex_indices[position]): float(weights[position])
            for position in np.where(selected)[0]
        }

    return group_weight_dict


def map_weights_to_exported_vertices(mesh, index_loop_id_dict, group_weight_dict):
    """Return one weight per exported vertex for every sampled group.

    index_loop_id_dict maps an exported vertex index to the Blender loop it
    came from.  The loop carries the Blender vertex, and that vertex
    carries the group membership.
    """
    mapped_dict = {}
    exported_vertex_count = len(index_loop_id_dict)
    if exported_vertex_count == 0 or not group_weight_dict:
        return mapped_dict

    # The loop order is stable, so one bulk read gives the Blender vertex
    # of every loop.
    loop_vertex_index = np.zeros(len(mesh.loops), dtype=np.int64)
    mesh.loops.foreach_get("vertex_index", loop_vertex_index)

    exported_index_list = sorted(index_loop_id_dict.keys())
    loop_index_array = np.array([index_loop_id_dict[index] for index in exported_index_list], dtype=np.int64)
    blender_vertex_array = loop_vertex_index[loop_index_array]

    for group_name, vertex_weight_dict in group_weight_dict.items():
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

    group_weight_dict = read_vertex_group_weights(merged_obj)
    if not group_weight_dict:
        return None

    mapped_dict = map_weights_to_exported_vertices(
        merged_obj.data,
        index_loop_id_dict,
        group_weight_dict,
    )
    if not mapped_dict:
        return None

    return {
        "weights_by_group": mapped_dict,
        "vertex_count": len(index_loop_id_dict),
    }


collect_vertex_group_weights.collector_name = COLLECTOR_NAME


def register():
    """Register the collector with the generic export registry."""
    register_collector(collect_vertex_group_weights)


def unregister():
    """Remove the collector from the generic export registry."""
    from ..m_export_vertex_attributes import unregister_collector
    unregister_collector(collect_vertex_group_weights)
