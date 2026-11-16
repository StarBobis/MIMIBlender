"""Prepare and emit the interaction deformation of an export.

This module is the preset independent part of the feature.  A preset only
has to provide a backend that says whether its meshes can carry the
deformation; everything else - the region collection, the buffer writing
and the INI sections - is shared.

The deformation replaces the position buffer that the game reads, so it
cannot be combined with a feature that writes the same buffer.  The
preset exporter therefore has to report which DrawIBs already use the
position buffer for something else, and this module refuses to build a
deformation for those.
"""

import os

from .runtime import (
    InteractionRegion,
    append_interaction_ini_sections,
    assemble_interaction_data,
    build_state_record,
    collect_positions,
    collect_triangles,
    copy_apply_shader,
    get_controls_buffer_filename,
    get_state_buffer_filename,
    write_interaction_files,
)


# The runtime state carries two regions, so two is also the limit of the
# regions an export can use.
MAX_RUNTIME_REGIONS = 2


# The node id of the interaction deformation node.
INTERACTION_NODE_ID = "MIMINode_InteractionDeformation"


def collect_interaction_nodes(root_tree):
    """Return every interaction node of the tree and of its groups.

    The nodes are socketless, so they are not reached by the object
    traversal.  They are collected separately, the same way the global
    texture managers are.
    """
    node_list = []
    visited_tree_ids = set()

    def visit_tree(tree):
        if tree is None:
            return
        tree_id = id(tree)
        if tree_id in visited_tree_ids:
            return
        visited_tree_ids.add(tree_id)

        for node in getattr(tree, "nodes", []):
            if getattr(node, "bl_idname", "") != INTERACTION_NODE_ID:
                continue
            # A muted node behaves like every other muted blueprint node.
            if getattr(node, "mute", False):
                continue
            if not getattr(node, "enabled", True):
                continue
            node_list.append(node)

        # A group can hold its own nodes, so the groups are visited too.
        for node in getattr(tree, "nodes", []):
            node_tree = getattr(node, "node_tree", None)
            if node_tree is None:
                continue
            visit_tree(node_tree)

    visit_tree(root_tree)
    return node_list


def collect_region_list(node_list):
    """Return the enabled regions of the interaction nodes.

    Every region keeps the object it belongs to and the control group that
    carries its weight.  A region without a control group cannot be
    deformed and is reported by the caller.

    The runtime carries two regions, so a third one would be dropped
    without a trace.  The extra regions are reported instead of being
    silently ignored.
    """
    region_list = []
    for node in node_list:
        for entry in getattr(node, "regions", []):
            if not getattr(entry, "enabled", True):
                continue
            vertex_group = str(getattr(entry, "vertex_group", "") or "")
            if not vertex_group:
                continue
            region_list.append(InteractionRegion(
                label=str(getattr(entry, "label", "") or ""),
                object_name=str(getattr(entry, "object_name", "") or ""),
                vertex_group=vertex_group,
                offset=tuple(float(value) for value in getattr(entry, "offset", (0.0, 0.0, 0.0))),
            ))

    if len(region_list) > MAX_RUNTIME_REGIONS:
        print("Interaction deformation: the runtime carries only "
              + str(MAX_RUNTIME_REGIONS) + " regions, so "
              + str(len(region_list) - MAX_RUNTIME_REGIONS)
              + " of them are not exported. Keep one node with two regions.")
        region_list = region_list[:MAX_RUNTIME_REGIONS]

    return region_list


def collect_existing_control_groups(drawib_model_list):
    """Return the control groups that exist on the exported objects.

    The result holds every group name the sampler saw, even the ones
    without a weight.  That is what tells a group that does not exist
    apart from a group that exists but has no weight yet.
    """
    existing_group_set = set()
    for drawib_model in drawib_model_list:
        for submesh_model in drawib_model.submesh_model_list:
            attribute_dict = getattr(submesh_model, "export_vertex_attribute_dict", {})
            sampled_dict = attribute_dict.get("interaction_vertex_group_weights", {})
            existing_group_set.update(sampled_dict.get("all_group_names", []))
    return existing_group_set


def find_missing_control_groups(drawib_model_list, region_list, existing_group_set=None):
    """Return the control groups that no exported object carries.

    A region that names a group nobody has is a configuration mistake, so
    it is reported.  A group that exists but only on some of the DrawIBs is
    normal: a body and its weapon are two DrawIBs, and only the body
    carries the control group.
    """
    if existing_group_set is None:
        existing_group_set = collect_existing_control_groups(drawib_model_list)

    missing_group_list = []
    for region in region_list:
        if region.vertex_group in existing_group_set:
            continue
        if region.vertex_group in missing_group_list:
            continue
        missing_group_list.append(region.vertex_group)
    return missing_group_list


def collect_weighted_control_groups(drawib_model_list):
    """Return the control groups that carry a weight on some DrawIB.

    A group that was sampled but whose weight is zero on every exported
    vertex does not count, because such a group moves nothing.
    """
    weighted_group_set = set()
    for drawib_model in drawib_model_list:
        for submesh_model in drawib_model.submesh_model_list:
            attribute_dict = getattr(submesh_model, "export_vertex_attribute_dict", {})
            sampled_dict = attribute_dict.get("interaction_vertex_group_weights", {})
            group_weights = sampled_dict.get("weights_by_group", {})
            for group_name, weights in group_weights.items():
                if len(weights) == 0:
                    continue
                if float(sum(weights)) > 1e-12:
                    weighted_group_set.add(group_name)
    return weighted_group_set


def find_empty_control_groups(drawib_model_list, region_list, existing_group_set=None,
                              weighted_group_set=None):
    """Return the control groups that exist but carry no weight at all.

    A group that exists on the mesh but was never painted is a different
    mistake than a group that does not exist, so it is reported with its
    own wording.
    """
    if existing_group_set is None:
        existing_group_set = collect_existing_control_groups(drawib_model_list)
    if weighted_group_set is None:
        weighted_group_set = collect_weighted_control_groups(drawib_model_list)

    empty_group_list = []
    for region in region_list:
        group_name = region.vertex_group
        if group_name not in existing_group_set:
            continue
        if group_name in weighted_group_set:
            continue
        if group_name in empty_group_list:
            continue
        empty_group_list.append(group_name)
    return empty_group_list


def drawib_object_name_set(drawib_model):
    """Return the names of the objects that belong to the DrawIB."""
    object_name_set = set()
    for submesh_model in drawib_model.submesh_model_list:
        for draw_call_model in getattr(submesh_model, "drawcall_model_list", []):
            object_name = getattr(draw_call_model, "obj_name", "")
            if object_name:
                object_name_set.add(object_name)
    return object_name_set


def describe_missing_region(drawib_model, region, existing_group_set, weighted_group_set):
    """Return why a region does not deform this DrawIB.

    The wording has to name the real cause, so the object name of the
    region is only used when the object really is missing from the
    DrawIB.
    """
    group_name = region.vertex_group
    if group_name not in existing_group_set:
        return "the control group '" + group_name + "' does not exist"

    object_name_set = drawib_object_name_set(drawib_model)
    if region.object_name and region.object_name not in object_name_set:
        return ("the region '" + (region.label or group_name) + "' names the object '"
                + region.object_name + "', which is not part of this DrawIB")

    if group_name not in weighted_group_set:
        return "the control group '" + group_name + "' has no weight on this DrawIB"

    # The group has a weight on this DrawIB, but not on the object the
    # region names.  That is a different mistake than a group without any
    # weight at all.
    if region.object_name:
        return ("the object '" + region.object_name + "' of the region '"
                + (region.label or group_name) + "' carries no weight for the"
                + " control group '" + group_name + "'")

    return "the control group '" + group_name + "' has no weight on this DrawIB"


def prepare_interaction(drawib_model_list, region_list, backend, conflict_reason_dict=None):
    """Prepare the interaction data of every DrawIB that can carry it.

    Returns a dictionary that maps the DrawIB to its prepared data.  A
    DrawIB that cannot carry the deformation is skipped, and the reason is
    collected so the export can report it instead of producing a mod that
    silently does nothing.  A skipped DrawIB never stops the export: the
    other parts of the mod are still worth exporting.

    conflict_reason_dict names the DrawIBs that another feature already
    writes.  Those DrawIBs are skipped here, before the applied pull is
    reported, so a DrawIB that does not carry the deformation never claims
    a pull.
    """
    prepared_dict = {}
    skipped_reason_list = []
    applied_report_list = []
    if not region_list:
        return prepared_dict
    if conflict_reason_dict is None:
        conflict_reason_dict = {}

    # A region that names a group nobody has is a configuration mistake.
    # It is reported once, because no DrawIB could ever carry it.
    existing_group_set = collect_existing_control_groups(drawib_model_list)
    weighted_group_set = collect_weighted_control_groups(drawib_model_list)
    missing_group_list = find_missing_control_groups(
        drawib_model_list, region_list, existing_group_set)
    for group_name in missing_group_list:
        print("Interaction deformation: the control group '" + group_name
              + "' was not found on any exported object, so the region that uses it does nothing.")
    for group_name in find_empty_control_groups(
            drawib_model_list, region_list, existing_group_set, weighted_group_set):
        print("Interaction deformation: the control group '" + group_name
              + "' exists but carries no weight, so the region that uses it does nothing.")

    for drawib_model in drawib_model_list:
        drawib = drawib_model.draw_ib

        # Another feature already writes the position buffer of this
        # DrawIB.  It is skipped here, so it never claims a pull.
        if drawib in conflict_reason_dict:
            skipped_reason_list.append(drawib + ": " + conflict_reason_dict[drawib])
            continue

        game_type = getattr(drawib_model, "d3d11_game_type", None)
        if not backend.is_supported_game_type(game_type):
            reason = backend.describe_unsupported_game_type(game_type)
            skipped_reason_list.append(drawib + ": " + reason)
            continue

        positions = collect_positions(drawib_model)
        if len(positions) == 0:
            skipped_reason_list.append(drawib + ": the DrawIB has no positions")
            continue

        # The game dispatches its skinning over the vertex count of the
        # DrawIB, so the deformation has to cover exactly the same range.
        # A difference would leave the tail of the deformed buffer
        # unwritten while the game still reads it.
        exported_vertex_count = getattr(drawib_model, "vertex_count", 0)
        if exported_vertex_count and exported_vertex_count != len(positions):
            skipped_reason_list.append(
                drawib + ": it exports " + str(exported_vertex_count)
                + " vertices but its position buffer holds " + str(len(positions))
                + ", so the deformation cannot cover the whole mesh")
            continue

        triangles = collect_triangles(drawib_model, len(positions))
        data = assemble_interaction_data(drawib_model, region_list, positions, triangles)

        # Only the regions this DrawIB really carries are checked.  A body
        # and its weapon are two DrawIBs, and the weapon carries no
        # control group at all.
        active_region_index_list = [
            region_index for region_index in range(len(region_list))
            if bool((data["region_weight_sum_list"][region_index] > 1e-9))
        ]
        active_region_index_set = set(active_region_index_list)

        # The reason is named for every region this DrawIB does not
        # carry, so a region that stays silent is impossible.
        weighted_group_set = collect_weighted_control_groups([drawib_model])
        inactive_reason_list = []
        for region_index, region in enumerate(region_list):
            if region_index in active_region_index_set:
                continue
            inactive_reason_list.append(
                (region.label or region.vertex_group) + ": "
                + describe_missing_region(
                    drawib_model, region, existing_group_set, weighted_group_set))

        if not active_region_index_list:
            skipped_reason_list.append(
                drawib + ": it carries none of the interaction regions ("
                + "; ".join(inactive_reason_list) + ")")
            continue

        # The reports of this DrawIB are only published when the DrawIB
        # itself is used, so a skipped DrawIB never claims a pull.
        drawib_report_list = []

        # The pull of a region is a fraction of the distance that its own
        # weight field can carry.  The distance shrinks with the gradient
        # of the weight field, so a narrow control group can only be
        # pulled a little.  Measuring the pull against that distance
        # keeps the whole slider range usable: a value of one always
        # means "as far as this region can be pulled safely".
        model_extent = data["model_extent"]
        region_offsets = []
        region_problem = ""
        for region_index, region in enumerate(region_list):
            if region_index not in active_region_index_set:
                # This DrawIB does not carry the region, so it does not move.
                region_offsets.append((0.0, 0.0, 0.0))
                continue

            direction = tuple(float(value) for value in region.offset)
            strength = float(sum(value * value for value in direction) ** 0.5)
            if strength <= 1e-12:
                # The region asks for no pull, so it simply does not move.
                region_offsets.append((0.0, 0.0, 0.0))
                continue

            gradient_bound = data["region_gradient_bound_list"][region_index]
            if gradient_bound <= 1e-12:
                # The group carries a constant weight, so there is no
                # gradient and the surface cannot be stretched safely.
                region_problem = ("the control group '" + region.vertex_group
                                  + "' has a constant weight, so it cannot be pulled safely; "
                                  + "give the region a weight that fades out towards its border")
                break

            safe_distance = data["region_safe_distance_list"][region_index]
            if safe_distance <= 1e-12:
                region_problem = ("the pull of the region '" + (region.label or region.vertex_group)
                                  + "' is too small for its weight field and would be cancelled; "
                                  + "increase the pull or soften the control group")
                break

            # The direction of the pull stays the one the user chose, and
            # the length is the strength scaled to the safe distance.
            applied_magnitude = strength * safe_distance
            unit_direction = tuple(value / strength for value in direction)
            applied = tuple(value * applied_magnitude for value in unit_direction)

            # The user has to see the distance that is really applied,
            # because it depends on the way the region was drawn.
            drawib_report_list.append(
                "the region '" + (region.label or region.vertex_group)
                + "' of DrawIB " + drawib + " pulls "
                + format(applied_magnitude, ".4f")
                + " with a strength of " + format(strength, ".2f")
                + "; its weight gradient is " + format(gradient_bound, ".2f"))
            region_offsets.append(applied)

        # A region that cannot be pulled is reported and the DrawIB is
        # skipped.  It never stops the export, because the other parts of
        # the mod are still worth exporting.
        if region_problem:
            skipped_reason_list.append(drawib + ": " + region_problem)
            continue

        data["region_offsets"] = region_offsets
        data["state_record"] = build_state_record(region_offsets)
        data["position_stride"] = game_type.CategoryStrideDict.get("Position", 0)
        prepared_dict[drawib] = data

        # The reports of a DrawIB are only published when the DrawIB is
        # used, so a skipped DrawIB never claims a pull it does not have.
        applied_report_list.extend(drawib_report_list)

        # A region that this DrawIB does not carry is reported even when
        # other regions of the same DrawIB work, so no region stays
        # silent.
        if inactive_reason_list:
            skipped_reason_list.append(
                drawib + ": these regions do not deform it ("
                + "; ".join(inactive_reason_list) + ")")

    # A DrawIB that was skipped has to be visible, otherwise the export
    # succeeds with a mod that does nothing at all.
    if skipped_reason_list:
        print("Interaction deformation: the following DrawIBs do not carry the deformation:")
        for reason in skipped_reason_list:
            print("  " + reason)

    # The applied distance has to be visible, because it depends on the
    # way the region was drawn and the node only carries the strength.
    if applied_report_list:
        print("Interaction deformation: the applied pull of every region:")
        for report in applied_report_list:
            print("  " + report)

    return prepared_dict


def append_interaction_sections(ini_builder, prepared_dict, drawib_model_dict):
    """Append the interaction sections of every prepared DrawIB."""
    if not prepared_dict:
        return

    for drawib in sorted(prepared_dict.keys()):
        data = prepared_dict[drawib]
        drawib_model = drawib_model_dict.get(drawib, None)
        if drawib_model is None:
            continue

        # The bind pose is the exported position buffer of the DrawIB.
        from ..global_config import GlobalConfig
        rest_file_name = GlobalConfig.ini_buffer_filename(
            drawib_model.get_category_buffer_filename("Position"))

        append_interaction_ini_sections(
            ini_builder,
            drawib,
            data["vertex_count"],
            data["position_stride"],
            get_controls_buffer_filename(drawib),
            get_state_buffer_filename(drawib),
            rest_file_name,
        )


def write_interaction_files_to_folder(output_folder, prepared_dict, addon_root):
    """Write the interaction buffers and the shader of an export."""
    if not prepared_dict:
        return

    copy_apply_shader(output_folder, addon_root)
    for drawib in sorted(prepared_dict.keys()):
        data = prepared_dict[drawib]
        write_interaction_files(
            output_folder,
            drawib,
            data["control_record"],
            data["state_record"],
        )


def get_interaction_command_list_name(drawib):
    """Return the command list name the position override has to run."""
    from .runtime import get_apply_command_list_name
    return get_apply_command_list_name(drawib)
