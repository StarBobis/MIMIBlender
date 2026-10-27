"""
Naraka cross-IB blueprint tree post-processor.

BluePrintModel calls this module after the whole blueprint tree has been
parsed into DrawCallModels (see games.get_tree_post_processor).  It scans
the tree (and nested group trees) for two configuration sources:

- NarakaCrossIBRender nodes: explicit source -> target object pairs.
- DrawIndex timeline nodes with Cross-IB enabled: every frame of that one
  timeline is moved to one host draw call.  The parser tags each draw with
  the timeline's graph-provenance key, so re-baking a timeline keeps working
  without editing one pair per frame object.

The nodes are standalone config: they are found by scanning, not by link
parsing, so they never need to be connected anywhere.
"""

from ...common.global_config import GlobalConfig, LogicName
from ...blueprint.blueprint_node_group import GROUP_NODE_IDNAME
from ...blueprint.blueprint_node_time_switch import MIMINode_TimeSwitch, time_switch_owner_key
from ...utils.log_utils import LOG
from .nodes import MIMINode_NarakaCrossIBRender


# Every diagnostic uses one prefix, so a user can search the console output
# and the tests can assert the feature that failed instead of any exception.
CROSS_IB_ERROR_PREFIX = "Naraka Cross-IB Render: "


def apply_cross_ib_render_nodes(tree, blueprint_model):
    """Scan the tree for cross-IB configuration and apply every request.

    Raises ValueError when a request is incomplete, references objects that
    are not part of the export, or asks for two different hosts, so a
    misconfiguration fails loudly instead of silently producing a broken INI.
    """
    cross_node_list, time_node_list = _collect_config_nodes(tree)
    if not cross_node_list and not time_node_list:
        return

    if GlobalConfig.logic_name != LogicName.Naraka:
        raise ValueError("The Naraka Cross-IB Render node is only supported under the Naraka game preset")

    # Resolve every request into one desired host per DrawCall first.  This
    # makes the application atomic: a later conflicting request cannot leave
    # half of the draws already rewritten.
    desired_host_by_draw_id = {}
    for time_node in time_node_list:
        _apply_time_switch_batch(blueprint_model, time_node, desired_host_by_draw_id)
    for cross_node in cross_node_list:
        for pair in getattr(cross_node, "pairs", []):
            _apply_cross_ib_pair(blueprint_model, pair, desired_host_by_draw_id)

    # Commit only after every request passed validation.
    for draw_call_model, host_submesh_name, _source_label in desired_host_by_draw_id.values():
        draw_call_model.cross_render_at_submesh = host_submesh_name


def _collect_config_nodes(tree):
    """Return the manual cross-IB nodes and the DrawIndex timeline nodes."""
    cross_node_list = []
    time_node_list = []
    visited_trees = set()

    def collect(node_tree):
        if node_tree is None or id(node_tree) in visited_trees:
            return
        visited_trees.add(id(node_tree))
        for node in getattr(node_tree, "nodes", []):
            # Muted nodes are excluded everywhere else, so skip them here too.
            if getattr(node, "mute", False):
                continue
            bl_idname = getattr(node, "bl_idname", "")
            if bl_idname == MIMINode_NarakaCrossIBRender.bl_idname:
                cross_node_list.append(node)
            elif bl_idname == MIMINode_TimeSwitch.bl_idname:
                # Disabled timelines are filtered later.  Keeping the full
                # list means a typo in the enable switch is visible in tests
                # instead of looking like a missing node.
                time_node_list.append(node)
            elif bl_idname == GROUP_NODE_IDNAME:
                collect(getattr(node, "node_tree", None))

    collect(tree)
    return cross_node_list, time_node_list


def _apply_time_switch_batch(blueprint_model, time_node, desired_host_by_draw_id):
    """Mark every frame draw of one timeline with the timeline's host Submesh."""
    if not bool(getattr(time_node, "cross_ib_enabled", False)):
        return

    owner_key = time_switch_owner_key(time_node)
    parsed_keys = getattr(blueprint_model, "parsed_time_switch_owner_keys", set())
    if owner_key not in parsed_keys:
        # The node is not connected to the output, so it owns no exported
        # draw.  Ignoring it keeps an abandoned editor node harmless.
        return

    node_label = str(getattr(time_node, "name", "") or "")
    host_object = getattr(time_node, "cross_ib_host_object", None)
    if host_object is None:
        raise ValueError(
            CROSS_IB_ERROR_PREFIX + "timeline '" + node_label
            + "' has Cross-IB enabled but no host object"
        )
    if getattr(host_object, "type", "") != 'MESH':
        raise ValueError(
            CROSS_IB_ERROR_PREFIX + "host object '" + str(host_object.name)
            + "' of timeline '" + node_label + "' is not a mesh object"
        )

    host_object_name = str(host_object.name)
    host_submesh_name = _resolve_host_submesh_name(blueprint_model, host_object_name)

    # Only draws produced by this exact timeline are moved.  Matching the
    # provenance key rather than object names is what makes re-baking safe:
    # the new frame objects are tagged during the next parse automatically.
    tagged_draw_list = []
    for draw_call_model in blueprint_model.ordered_draw_obj_data_model_list:
        if getattr(draw_call_model, "time_switch_owner_key", "") == owner_key:
            tagged_draw_list.append(draw_call_model)

    if len(tagged_draw_list) == 0:
        raise ValueError(
            CROSS_IB_ERROR_PREFIX + "timeline '" + node_label
            + "' has no exported frame objects; connect at least one frame or turn Cross-IB off"
        )

    marked_count = 0
    skipped_count = 0
    for draw_call_model in tagged_draw_list:
        # The host's own draw must stay in its own section; moving it would
        # either duplicate the host or make the section depend on itself.
        if draw_call_model.obj_name == host_object_name:
            skipped_count = skipped_count + 1
            continue
        # A frame already drawn by the host Submesh needs no second draw.
        if draw_call_model.match_submesh_name == host_submesh_name:
            skipped_count = skipped_count + 1
            continue
        _assign_host(
            desired_host_by_draw_id,
            draw_call_model,
            host_submesh_name,
            "timeline '" + node_label + "'",
        )
        marked_count = marked_count + 1

    if marked_count == 0:
        raise ValueError(
            CROSS_IB_ERROR_PREFIX + "timeline '" + node_label
            + "' needs no cross-IB: every frame already renders at host Submesh '"
            + host_submesh_name + "' or is the host object itself; turn Cross-IB off"
        )

    LOG.info(
        "Naraka Cross-IB: timeline '" + node_label + "' -> host '" + host_object_name
        + "' (Submesh '" + host_submesh_name + "'): " + str(marked_count)
        + " draw(s) marked, " + str(skipped_count) + " skipped"
    )


def _apply_cross_ib_pair(blueprint_model, pair, desired_host_by_draw_id):
    """Mark every DrawCallModel of the source object with the target's Submesh name."""
    source_obj_name = str(getattr(pair, "source_object", "") or "").strip()
    target_obj_name = str(getattr(pair, "target_object", "") or "").strip()

    # Fully empty rows are editing leftovers; ignore them silently.
    if not source_obj_name and not target_obj_name:
        return
    if not source_obj_name or not target_obj_name:
        raise ValueError(CROSS_IB_ERROR_PREFIX + "a pair needs both a source object and a target object")
    if source_obj_name == target_obj_name:
        raise ValueError(
            CROSS_IB_ERROR_PREFIX + "source and target must be different objects: '"
            + source_obj_name + "'"
        )

    host_submesh_name = _resolve_host_submesh_name(blueprint_model, target_obj_name)

    marked_count = 0
    for draw_call_model in blueprint_model.ordered_draw_obj_data_model_list:
        if draw_call_model.obj_name == source_obj_name:
            _assign_host(
                desired_host_by_draw_id,
                draw_call_model,
                host_submesh_name,
                "pair '" + source_obj_name + "' -> '" + target_obj_name + "'",
            )
            marked_count = marked_count + 1

    if marked_count == 0:
        raise ValueError(
            CROSS_IB_ERROR_PREFIX + "source object '" + source_obj_name
            + "' is not used by any Object Info node connected to the output"
        )


def _resolve_host_submesh_name(blueprint_model, host_obj_name):
    """Resolve one host object name to exactly one exported Submesh name."""
    host_submesh_name_set = set()
    for draw_call_model in blueprint_model.ordered_draw_obj_data_model_list:
        if draw_call_model.obj_name == host_obj_name:
            host_submesh_name_set.add(draw_call_model.match_submesh_name)

    if len(host_submesh_name_set) == 0:
        raise ValueError(
            CROSS_IB_ERROR_PREFIX + "host object '" + host_obj_name
            + "' is not used by any Object Info node connected to the output"
        )
    if len(host_submesh_name_set) > 1:
        raise ValueError(
            CROSS_IB_ERROR_PREFIX + "host object '" + host_obj_name
            + "' maps to more than one Submesh: " + ", ".join(sorted(host_submesh_name_set))
        )
    return next(iter(host_submesh_name_set))


def _assign_host(desired_host_by_draw_id, draw_call_model, host_submesh_name, source_label):
    """Record one draw -> host request and reject two different hosts."""
    existing_request = desired_host_by_draw_id.get(id(draw_call_model))
    if existing_request is None:
        desired_host_by_draw_id[id(draw_call_model)] = (
            draw_call_model,
            host_submesh_name,
            source_label,
        )
        return
    if existing_request[1] != host_submesh_name:
        raise ValueError(
            CROSS_IB_ERROR_PREFIX + "object '" + str(draw_call_model.obj_name)
            + "' is assigned to two different host Submeshes: "
            + existing_request[2] + " wants '" + existing_request[1] + "', "
            + source_label + " wants '" + host_submesh_name + "'"
        )
