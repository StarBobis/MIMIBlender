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
    limit_offset,
    write_interaction_files,
)


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
    return region_list


def prepare_interaction(drawib_model_list, region_list, backend):
    """Prepare the interaction data of every DrawIB that can carry it.

    Returns a dictionary that maps the DrawIB to its prepared data.  A
    DrawIB whose position layout the backend rejects is skipped and
    reported, so the rest of the mod keeps working.
    """
    prepared_dict = {}
    if not region_list:
        return prepared_dict

    for drawib_model in drawib_model_list:
        drawib = drawib_model.draw_ib
        game_type = getattr(drawib_model, "d3d11_game_type", None)
        if not backend.is_supported_game_type(game_type):
            print("Interaction deformation: DrawIB " + drawib + " is skipped because "
                  + backend.describe_unsupported_game_type(game_type))
            continue

        positions = collect_positions(drawib_model)
        if len(positions) == 0:
            print("Interaction deformation: DrawIB " + drawib + " is skipped because it has no positions")
            continue

        triangles = collect_triangles(drawib_model, len(positions))
        data = assemble_interaction_data(drawib_model, region_list, positions, triangles)

        # The pull of a region is a fraction of the model size, so the
        # same value behaves the same way on a large and on a small body.
        model_extent = data["model_extent"]
        safe_distance = data["safe_distance"]
        region_offsets = []
        for region in region_list:
            offset = tuple(float(value) * model_extent for value in region.offset)
            region_offsets.append(limit_offset(offset, safe_distance))

        data["region_offsets"] = region_offsets
        data["state_record"] = build_state_record(region_offsets)
        data["position_stride"] = game_type.CategoryStrideDict.get("Position", 0)
        prepared_dict[drawib] = data

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
