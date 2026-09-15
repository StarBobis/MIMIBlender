"""
Naraka cross-IB blueprint tree post-processor.

BluePrintModel calls this module after the whole blueprint tree has been
parsed into DrawCallModels (see games.get_tree_post_processor).  It scans
the tree (and nested group trees) for NarakaCrossIBRender nodes and marks
the DrawCallModels of every source object with the host Submesh name.

The nodes are standalone config: they are found by scanning, not by link
parsing, so they never need to be connected anywhere.
"""

from ...common.global_config import GlobalConfig, LogicName
from ...blueprint.blueprint_node_group import GROUP_NODE_IDNAME
from .nodes import MIMINode_NarakaCrossIBRender


def apply_cross_ib_render_nodes(tree, blueprint_model):
    """Scan the tree for NarakaCrossIBRender nodes and apply every pair.

    Raises ValueError when a pair is incomplete or references objects that
    are not part of the export, so misconfiguration fails loudly instead of
    silently producing a broken INI.
    """
    cross_node_list = []
    visited_trees = set()

    def collect(node_tree):
        if node_tree is None or id(node_tree) in visited_trees:
            return
        visited_trees.add(id(node_tree))
        for node in getattr(node_tree, "nodes", []):
            # Muted nodes are excluded everywhere else, so skip them here too.
            if getattr(node, "mute", False):
                continue
            if getattr(node, "bl_idname", "") == MIMINode_NarakaCrossIBRender.bl_idname:
                cross_node_list.append(node)
            elif getattr(node, "bl_idname", "") == GROUP_NODE_IDNAME:
                collect(getattr(node, "node_tree", None))

    collect(tree)
    if not cross_node_list:
        return

    if GlobalConfig.logic_name != LogicName.Naraka:
        raise ValueError("The Naraka Cross-IB Render node is only supported under the Naraka game preset")

    for cross_node in cross_node_list:
        for pair in getattr(cross_node, "pairs", []):
            _apply_cross_ib_pair(blueprint_model, pair)


def _apply_cross_ib_pair(blueprint_model, pair):
    """Mark every DrawCallModel of the source object with the target's Submesh name."""
    source_obj_name = str(getattr(pair, "source_object", "") or "").strip()
    target_obj_name = str(getattr(pair, "target_object", "") or "").strip()

    # Fully empty rows are editing leftovers; ignore them silently.
    if not source_obj_name and not target_obj_name:
        return
    if not source_obj_name or not target_obj_name:
        raise ValueError("Naraka Cross-IB Render: a pair needs both a source object and a target object")

    # The host Submesh is resolved from the already parsed DrawCallModels of
    # the target object, so every name-format fallback stays in one place.
    host_submesh_name_set = set()
    for draw_call_model in blueprint_model.ordered_draw_obj_data_model_list:
        if draw_call_model.obj_name == target_obj_name:
            host_submesh_name_set.add(draw_call_model.match_submesh_name)

    if len(host_submesh_name_set) == 0:
        raise ValueError("Naraka Cross-IB Render: target object '" + target_obj_name + "' is not used by any Object Info node connected to the output")
    if len(host_submesh_name_set) > 1:
        raise ValueError("Naraka Cross-IB Render: target object '" + target_obj_name + "' maps to more than one Submesh: " + ", ".join(sorted(host_submesh_name_set)))
    host_submesh_name = next(iter(host_submesh_name_set))

    marked_count = 0
    for draw_call_model in blueprint_model.ordered_draw_obj_data_model_list:
        if draw_call_model.obj_name == source_obj_name:
            draw_call_model.cross_render_at_submesh = host_submesh_name
            marked_count = marked_count + 1

    if marked_count == 0:
        raise ValueError("Naraka Cross-IB Render: source object '" + source_obj_name + "' is not used by any Object Info node connected to the output")
