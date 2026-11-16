"""Assemble the interaction deformation data and write the INI sections.

The runtime side of the interaction deformation is a single compute shader
per DrawIB.  It reads the immutable bind pose, the control data of every
vertex and the current per-region pull, and writes the deformed vertex
back into a buffer that the game then reads instead of its own position
buffer.

The resource contract mirrors the one the shared shape key pipeline uses:
the shader runs from the top of the Position vertex buffer override, so
the game's own skinning compute shader reads the deformed positions.

    [TextureOverride_VB_<DrawIB>_<Alias>_Position]
    hash = ...
    run = CustomShaderComputeInteraction<DrawIB>
    cs-cb0 = Resource_<DrawIB>_VertexLimit
    cs-t0  = Resource<DrawIB>Position
    cs-t1  = Resource<DrawIB>Blend
    handling = skip
    dispatch = ...

Because the shader always starts from the immutable bind pose, the
deformation never accumulates across frames.
"""

import os
from dataclasses import dataclass, field

import numpy as np

from ..m_ini_builder import M_IniSection, M_SectionType
from .weight_field import (
    build_control_data,
    compute_gradient_bound,
    compute_safe_displacement,
    compute_surface_gradients,
)


@dataclass
class InteractionRegion:
    """One pullable region of the exported model.

    object_name: the Blender object the region belongs to.  An empty name
    matches every object of the DrawIB.
    vertex_group: the control group that carries the weight of the pull.
    offset: the pull direction and strength.  The length is a fraction of
    the longest side of the model.
    """

    label: str = ""
    object_name: str = ""
    vertex_group: str = ""
    offset: tuple = (0.0, 0.0, 0.0)


# The shader file name, relative to the mod folder.
APPLY_SHADER_FILENAME = "interaction_apply_cs.hlsl"

# The sub folder of the mod folder that holds the interaction buffers.
BUFFER_SUBFOLDER = "Interaction"

# The state buffer holds nine float4 records: two regions with an offset
# and a velocity each, plus the bookkeeping the runtime controller needs.
STATE_RECORD_COUNT = 9
STATE_RECORD_SIZE = 16

# The byte size of one control record: two weights, two gradients.
CONTROL_RECORD_SIZE = 32


def get_resource_prefix(drawib):
    """Return the prefix of every resource name of one DrawIB."""
    return "Resource" + drawib + "Interaction"


def get_apply_command_list_name(drawib):
    """Return the command list name of one DrawIB."""
    return "CustomShaderComputeInteraction" + drawib


def get_rest_resource_name(drawib):
    """Return the resource name of the immutable bind pose."""
    return get_resource_prefix(drawib) + "Rest"


def get_controls_resource_name(drawib):
    """Return the resource name of the per-vertex control data."""
    return get_resource_prefix(drawib) + "Controls"


def get_state_resource_name(drawib):
    """Return the resource name of the runtime state."""
    return get_resource_prefix(drawib) + "State"


def get_deformed_resource_name(drawib):
    """Return the resource name of the deformed vertex buffer."""
    return get_resource_prefix(drawib) + "Deformed"


def get_backup_resource_name(drawib, slot):
    """Return the resource name that holds a borrowed compute slot."""
    return get_resource_prefix(drawib) + "Backup_" + slot


def get_controls_buffer_filename(drawib):
    """Return the mod relative file name of the control data buffer."""
    return BUFFER_SUBFOLDER + "/" + drawib + "-Controls.buf"


def get_state_buffer_filename(drawib):
    """Return the mod relative file name of the runtime state buffer."""
    return BUFFER_SUBFOLDER + "/" + drawib + "-State.buf"


def collect_region_weights(drawib_model, region):
    """Return one weight per vertex of the DrawIB for one region.

    The weights of a DrawIB are the concatenation of the weights of its
    submeshes, in the same order the position buffer is assembled in.  A
    submesh that does not contain the object of the region contributes
    zeroes, so a region never leaks into another body part.
    """
    weights_list = []
    for submesh_model in drawib_model.submesh_model_list:
        exported_vertex_count = drawib_model._get_exported_vertex_count(submesh_model)
        weights = np.zeros(exported_vertex_count, dtype=np.float64)

        object_name_list = []
        for draw_call_model in submesh_model.drawcall_model_list:
            object_name = getattr(draw_call_model, "obj_name", "")
            if object_name and object_name not in object_name_list:
                object_name_list.append(object_name)

        # The region only applies to the object it names.
        if region.object_name and region.object_name not in object_name_list:
            weights_list.append(weights)
            continue

        attribute_dict = getattr(submesh_model, "export_vertex_attribute_dict", {})
        sampled_dict = attribute_dict.get("interaction_vertex_group_weights", {})
        group_weights = sampled_dict.get("weights_by_group", {})
        group_weight = group_weights.get(region.vertex_group, None)
        if group_weight is not None and len(group_weight) == exported_vertex_count:
            weights = np.array(group_weight, dtype=np.float64)

        weights_list.append(weights)

    if not weights_list:
        return np.zeros(0, dtype=np.float64)
    return np.concatenate(weights_list)


def collect_positions(drawib_model):
    """Return the bind pose positions of every vertex of the DrawIB.

    The positions are read from the exported position buffer, so they use
    exactly the layout the runtime shader will read.
    """
    position_stride = drawib_model.d3d11_game_type.CategoryStrideDict.get("Position", 0)
    position_chunks = []
    for submesh_model in drawib_model.submesh_model_list:
        position_buffer = submesh_model.category_buffer_dict.get("Position", None)
        if position_buffer is None:
            continue
        position_chunks.append(np.asarray(position_buffer, dtype=np.uint8).reshape(-1))

    if not position_chunks:
        return np.zeros((0, 3), dtype=np.float64)

    # The category buffer holds the raw bytes of the vertices, so the
    # positions are read back out of that byte stream.
    position_bytes = np.concatenate(position_chunks)
    vertex_count = len(position_bytes) // position_stride
    if vertex_count == 0:
        return np.zeros((0, 3), dtype=np.float64)

    # The position element is the first one of the vertex, so the first
    # three floats of every vertex are the position.
    values = np.frombuffer(
        position_bytes[:vertex_count * position_stride].tobytes(), dtype=np.float32)
    values = values.reshape(vertex_count, position_stride // 4)
    return values[:, 0:3].astype(np.float64)


def collect_triangles(drawib_model, vertex_count):
    """Return the triangle list of the DrawIB in the assembled order.

    The index buffer of a submesh is local to that submesh, so every
    submesh has to be shifted by the vertex count of the submeshes
    before it.
    """
    shifted_chunks = []
    vertex_offset = 0
    for submesh_model in drawib_model.submesh_model_list:
        submesh_ib = submesh_model.ib
        if submesh_ib:
            submesh_triangles = np.asarray(submesh_ib, dtype=np.int64).reshape(-1, 3)
            shifted_chunks.append(submesh_triangles + vertex_offset)
        vertex_offset += drawib_model._get_exported_vertex_count(submesh_model)

    if not shifted_chunks:
        return np.zeros((0, 3), dtype=np.int64)

    triangles = np.concatenate(shifted_chunks, axis=0)
    if len(triangles) and int(triangles.max()) >= vertex_count:
        # An index outside the vertex range would break the gradient.
        triangles = triangles[int(triangles.max(axis=1)) < vertex_count]
    return triangles


def compute_model_extent(positions):
    """Return the longest side of the bounding box of the mesh."""
    if len(positions) == 0:
        return 0.0
    span = positions.max(axis=0) - positions.min(axis=0)
    return float(span.max())


def limit_offset(offset, safe_distance):
    """Return the pull of one region, limited to the safe distance."""
    offset = np.array(offset, dtype=np.float64)
    magnitude = float(np.linalg.norm(offset))
    if magnitude <= 1e-12 or safe_distance <= 0.0:
        return np.zeros(3, dtype=np.float64)
    if magnitude <= safe_distance:
        return offset
    return offset * (safe_distance / magnitude)


def build_state_record(region_offsets):
    """Return the state buffer content of one DrawIB.

    The layout is fixed by the runtime controller: the first two records
    hold the offset and the velocity of the first region, the next two
    hold the same for the second region, and the last record holds the
    offset the region started from.
    """
    state = np.zeros((STATE_RECORD_COUNT, 4), dtype=np.float32)
    for region_index, offset in enumerate(region_offsets):
        if region_index >= 2:
            break
        state[region_index * 2, 0:3] = np.array(offset, dtype=np.float32)
        state[region_index * 2 + 1, 0:3] = 0.0
    return state


def assemble_interaction_data(drawib_model, regions, positions, triangles):
    """Assemble the per-vertex control data of one DrawIB.

    Returns a dictionary with the control record, the gradient bound and
    the pull distance that keeps the surface from folding.  The pull of
    every region is limited so that the Jacobian stays invertible.
    """
    vertex_count = len(positions)

    weights_by_region = []
    gradients_by_region = []
    for region in regions:
        weights = collect_region_weights(drawib_model, region)
        if len(weights) != vertex_count:
            weights = np.zeros(vertex_count, dtype=np.float64)
        weights_by_region.append(weights)
        gradients_by_region.append(compute_surface_gradients(positions, weights, triangles))

    control_record = build_control_data(weights_by_region, gradients_by_region)

    gradient_bound = 0.0
    for gradients in gradients_by_region:
        gradient_bound = max(gradient_bound, compute_gradient_bound(gradients))

    model_extent = compute_model_extent(positions)
    safe_distance = compute_safe_displacement(gradient_bound, model_extent)

    return {
        "control_record": control_record,
        "gradient_bound": gradient_bound,
        "safe_distance": safe_distance,
        "model_extent": model_extent,
        "vertex_count": vertex_count,
    }


def write_interaction_files(output_folder, drawib, control_record, state_record):
    """Write the control data and the state buffer of one DrawIB."""
    folder = os.path.join(output_folder, BUFFER_SUBFOLDER)
    os.makedirs(folder, exist_ok=True)

    control_record.astype("<f4").tofile(os.path.join(folder, drawib + "-Controls.buf"))
    state_record.astype("<f4").tofile(os.path.join(folder, drawib + "-State.buf"))


def copy_apply_shader(output_folder, addon_root):
    """Copy the interaction compute shader next to the generated INI."""
    import shutil

    source = os.path.join(addon_root, "resources", "interaction", APPLY_SHADER_FILENAME)
    os.makedirs(output_folder, exist_ok=True)
    shutil.copy2(source, os.path.join(output_folder, APPLY_SHADER_FILENAME))


def append_interaction_ini_sections(ini_builder, drawib, vertex_count, position_stride,
                                     control_file_name, state_file_name, rest_file_name):
    """Append the command list and the resource declarations of one DrawIB.

    The compute shader borrows three shader slots and one UAV slot.  A
    CustomShader restores the shaders and the output merge state, but not
    the compute bindings, so the borrowed slots are backed up and restored
    around the dispatch.
    """
    command_list_section = M_IniSection(M_SectionType.CommandList)
    command_list_section.append("[" + get_apply_command_list_name(drawib) + "]")
    command_list_section.append("cs = " + APPLY_SHADER_FILENAME)

    command_list_section.append(get_backup_resource_name(drawib, "cs-u5") + " = ref cs-u5")
    command_list_section.append("cs-t40 = " + get_rest_resource_name(drawib))
    command_list_section.append("cs-t41 = " + get_controls_resource_name(drawib))
    command_list_section.append("cs-t42 = " + get_state_resource_name(drawib))
    command_list_section.append("cs-u5 = ref " + get_deformed_resource_name(drawib))
    command_list_section.new_line()

    # One thread group handles 64 vertices.
    if vertex_count < 1:
        raise ValueError("Interaction deformation needs at least one vertex")
    if vertex_count > 65535 * 64:
        raise ValueError("Interaction deformation vertex count exceeds the supported Dispatch range")
    command_list_section.append("dispatch = " + str((vertex_count + 63) // 64) + ",1,1")
    command_list_section.new_line()

    # The deformed buffer replaces the bind pose for the skinning dispatch
    # that follows, so the game reads the deformed positions.
    command_list_section.append("Resource" + drawib + "Position = ref " + get_deformed_resource_name(drawib))
    command_list_section.new_line()

    command_list_section.append("cs-u5 = ref " + get_backup_resource_name(drawib, "cs-u5"))
    command_list_section.new_line()
    ini_builder.append_section(command_list_section)

    resource_section = M_IniSection(M_SectionType.ResourceBuffer)

    # The bind pose is the exported position buffer itself.
    resource_section.append("[" + get_rest_resource_name(drawib) + "]")
    resource_section.append("type = ByteAddressBuffer")
    resource_section.append("misc_flags = buffer_allow_raw_views")
    resource_section.append("bind_flags = shader_resource")
    resource_section.append("stride = " + str(position_stride))
    resource_section.append("filename = " + rest_file_name)
    resource_section.new_line()

    # The control data is a structured record per vertex.
    resource_section.append("[" + get_controls_resource_name(drawib) + "]")
    resource_section.append("type = StructuredBuffer")
    resource_section.append("stride = " + str(CONTROL_RECORD_SIZE))
    resource_section.append("filename = " + control_file_name)
    resource_section.new_line()

    # The runtime state is a structured record per slot.
    resource_section.append("[" + get_state_resource_name(drawib) + "]")
    resource_section.append("type = StructuredBuffer")
    resource_section.append("stride = " + str(STATE_RECORD_SIZE))
    resource_section.append("filename = " + state_file_name)
    resource_section.new_line()

    # The deformed buffer is written by the shader and read by the game.
    resource_section.append("[" + get_deformed_resource_name(drawib) + "]")
    resource_section.append("type = ByteAddressBuffer")
    resource_section.append("misc_flags = buffer_allow_raw_views")
    resource_section.append("bind_flags = shader_resource unordered_access")
    resource_section.append("stride = " + str(position_stride))
    resource_section.append("byte_width = " + str(vertex_count * position_stride))
    resource_section.new_line()

    resource_section.append("[" + get_backup_resource_name(drawib, "cs-u5") + "]")
    resource_section.new_line()
    ini_builder.append_section(resource_section)
