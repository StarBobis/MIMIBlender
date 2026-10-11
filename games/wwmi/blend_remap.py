"""
WWMI blend remap + merged skeleton INI sections.

These sections implement the merged-skeleton workflow of WWMI mods:

- the per-frame merged skeleton refresh and the per component reset of the
  skeleton merge status,
- the guarded skeleton merge command list that copies bone data out of the
  game's constant buffers,
- the optional blend remap resources and command lists used when some
  components need their blend indices remapped onto the merged skeleton,
- the merged skeleton resource declarations.

All symbols that describe one draw range carry the DrawIB as a suffix, because
every INI of a mod shares one 3Dmigoto namespace. See ``names.py``.
"""

from ...common.mimi_global_properties import MIMIGlobalProperties
from ...common.m_ini_builder import M_IniBuilder, M_IniSection, M_SectionType
from .model import DrawIBModelWWMI
from .names import scoped_global, scoped_name, scoped_section

# The filter index the WWMI runtime and this generator use to tag skeleton
# constant buffers. A constant buffer only carries bone data when it still has
# this marker, which is what makes the merge below safe: without the check the
# shader would copy unrelated constant buffer contents into the skeleton.
BONE_DATA_FILTER_INDEX = "3381.7777"


def add_commandlist_update_merged_skeleton(ini_builder: M_IniBuilder, draw_ib_model: DrawIBModelWWMI):
    """Per-frame merged skeleton update.

    Flips the frame state id, copies the accumulated RW skeletons into the
    resources that get bound to the vs-cb slots, resets the per component merge
    status so every component can collect skeleton data again in this frame and
    re-runs the remap step when a blend remap is active.
    """
    draw_ib = draw_ib_model.draw_ib
    commandlist_section = M_IniSection(M_SectionType.CommandList)
    if MIMIGlobalProperties.import_merged_vgmap() == 'MERGED':
        state_id_var = scoped_global("state_id", draw_ib)
        commandlist_section.append(scoped_section("CommandListUpdateMergedSkeleton", draw_ib))
        commandlist_section.append("if " + state_id_var)
        commandlist_section.append("  " + state_id_var + " = 0")
        commandlist_section.append("else")
        commandlist_section.append("  " + state_id_var + " = 1")
        commandlist_section.append("endif")
        commandlist_section.append(
            scoped_name("ResourceMergedSkeleton", draw_ib) + " = copy " + scoped_name("ResourceMergedSkeletonRW", draw_ib)
        )
        commandlist_section.append(
            scoped_name("ResourceExtraMergedSkeleton", draw_ib) + " = copy " + scoped_name("ResourceExtraMergedSkeletonRW", draw_ib)
        )
        # Skeleton data is collected per component and per frame, so the status
        # resets here, right before the draw calls of the new frame run.
        for component_index in range(len(draw_ib_model.wwmi_info.components)):
            commandlist_section.append(
                scoped_global("merge_status_id_" + str(component_index), draw_ib) + " = 0"
            )
        if draw_ib_model.blend_remap:
            commandlist_section.append("run = " + scoped_name("CommandListRemapMergedSkeleton", draw_ib))
        commandlist_section.new_line()
    ini_builder.append_section(commandlist_section)


def add_blend_remap_sections(ini_builder: M_IniBuilder, draw_ib_model: DrawIBModelWWMI):
    """Blend remap resources + command lists.

    Only components flagged in draw_ib_model.blend_remap_used_by_index get
    their own remapped blend/skeleton buffers; the others keep using the
    shared ones. The flag is keyed by the real component index, because a
    component without objects has no remap data and no name entry.
    """
    draw_ib = draw_ib_model.draw_ib
    blend_remap_section = M_IniSection(M_SectionType.CommandList)

    if MIMIGlobalProperties.import_merged_vgmap() == 'MERGED':
        blend_remap_section.append(scoped_section("ResourceMergedSkeletonRemap", draw_ib))
        blend_remap_section.append(scoped_section("ResourceExtraMergedSkeletonRemap", draw_ib))
        blend_remap_section.new_line()

        blend_remap_section.append(scoped_section("ResourceBlendBufferOverride", draw_ib))
        blend_remap_section.append(scoped_section("ResourceExtraMergedSkeletonOverride", draw_ib))
        blend_remap_section.append(scoped_section("ResourceMergedSkeletonOverride", draw_ib))
        blend_remap_section.new_line()

        blend_remap_section.append(scoped_section("ResourceRemappedBlendBufferRW", draw_ib))
        blend_remap_section.append(scoped_section("ResourceRemappedSkeletonRW", draw_ib))
        blend_remap_section.append(scoped_section("ResourceExtraRemappedSkeletonRW", draw_ib))
        blend_remap_section.new_line()

        # Component indexes are the real ones, so the resource names match the
        # [TextureOverrideComponentN] sections. A component without objects has
        # no remap data and gets no resources at all.
        use_remap_by_index = getattr(draw_ib_model, "blend_remap_used_by_index", None) or {}
        component_count = len(getattr(draw_ib_model.wwmi_info, "components", []) or [])
        for component_index in range(component_count):
            if not use_remap_by_index.get(component_index, False):
                continue
            blend_remap_section.append(scoped_section("ResourceRemappedBlendBufferComponent" + str(component_index), draw_ib))
            blend_remap_section.append(scoped_section("ResourceRemappedSkeletonComponent" + str(component_index), draw_ib))
            blend_remap_section.append(scoped_section("ResourceExtraRemappedSkeletonComponent" + str(component_index), draw_ib))
            blend_remap_section.new_line()

        if draw_ib_model.blend_remap:
            blend_remap_section.append(scoped_section("CommandListInitializeBlendRemaps", draw_ib))
            blend_remap_section.append("local $blend_remaps_initialized")
            blend_remap_section.append("if !$blend_remaps_initialized")
            blend_remap_section.append("  " + scoped_name("ResourceRemappedSkeletonRW", draw_ib) + " = copy " + scoped_name("ResourceMergedSkeletonRW", draw_ib))
            blend_remap_section.append("  " + scoped_name("ResourceExtraRemappedSkeletonRW", draw_ib) + " = copy " + scoped_name("ResourceExtraMergedSkeletonRW", draw_ib))
            blend_remap_section.new_line()
            blend_remap_section.append("  $\\WWMIv1\\custom_vertex_count = " + scoped_global("mesh_vertex_count", draw_ib))
            weights_per_vertex_count = draw_ib_model.d3d11_game_type.get_blendindices_count_wwmi()
            blend_remap_section.append("  $\\WWMIv1\\weights_per_vertex_count = " + str(weights_per_vertex_count))
            blend_remap_section.append("  cs-t34 = ref " + scoped_name("ResourceBlendRemapReverseBuffer", draw_ib))
            blend_remap_section.append("  cs-t35 = ref " + scoped_name("ResourceBlendRemapVertexVGBuffer", draw_ib))

            # blend_remap_id stays a compact index over the remapped components
            # only, because the remap buffers are packed in that order.
            blend_remap_id = 0
            for component_index in range(component_count):
                if not use_remap_by_index.get(component_index, False):
                    continue
                component_count_str = str(component_index)
                blend_remap_section.append("    $\\WWMIv1\\blend_remap_id = " + str(blend_remap_id))
                blend_remap_section.append("    " + scoped_name("ResourceRemappedBlendBufferRW", draw_ib) + " = copy " + scoped_name("ResourceBlendBufferNoStride", draw_ib))
                blend_remap_section.append("    cs-u4 = ref " + scoped_name("ResourceRemappedBlendBufferRW", draw_ib))
                blend_remap_section.append("    run = CustomShader\\WWMIv1\\BlendRemapper")
                blend_remap_section.append("    " + scoped_name("ResourceRemappedBlendBufferComponent" + component_count_str, draw_ib) + " = copy " + scoped_name("ResourceRemappedBlendBufferRW", draw_ib))
                blend_remap_section.append("    " + scoped_name("ResourceRemappedBlendBufferComponent" + component_count_str, draw_ib) + " = copy_desc " + scoped_name("ResourceBlendBuffer", draw_ib))
                blend_remap_section.new_line()
                blend_remap_id = blend_remap_id + 1

            blend_remap_section.append("    $blend_remaps_initialized = 1")
            blend_remap_section.append("endif")
            blend_remap_section.new_line()

        blend_remap_section.append(scoped_section("CommandListRemapMergedSkeleton", draw_ib))
        blend_remap_section.append(scoped_name("ResourceMergedSkeletonRemap", draw_ib) + " = copy " + scoped_name("ResourceMergedSkeletonRW", draw_ib))
        blend_remap_section.append(scoped_name("ResourceExtraMergedSkeletonRemap", draw_ib) + " = copy " + scoped_name("ResourceExtraMergedSkeletonRW", draw_ib))
        blend_remap_section.new_line()
        if draw_ib_model.blend_remap:
            blend_remap_section.append("cs-t37 = " + scoped_name("ResourceBlendRemapForwardBuffer", draw_ib))
            blend_remap_section.new_line()

            blend_remap_id = 0
            for component_index in range(component_count):
                if not use_remap_by_index.get(component_index, False):
                    continue

                blend_remap_section.append("$\\WWMIv1\\blend_remap_id = " + str(blend_remap_id))
                vg_count = draw_ib_model.component_real_vg_count_dict[component_index]
                blend_remap_section.append("$\\WWMIv1\\vg_count = " + str(vg_count))
                blend_remap_section.append("cs-t38 = " + scoped_name("ResourceMergedSkeletonRemap", draw_ib))
                blend_remap_section.append("cs-u5 = " + scoped_name("ResourceRemappedSkeletonRW", draw_ib))
                blend_remap_section.append("run = CustomShader\\WWMIv1\\SkeletonRemapper")
                blend_remap_section.append(scoped_name("ResourceRemappedSkeletonComponent" + str(component_index), draw_ib) + " = copy " + scoped_name("ResourceRemappedSkeletonRW", draw_ib))
                blend_remap_section.append("cs-t38 = " + scoped_name("ResourceExtraMergedSkeletonRemap", draw_ib))
                blend_remap_section.append("cs-u5 = " + scoped_name("ResourceExtraRemappedSkeletonRW", draw_ib))
                blend_remap_section.append("run = CustomShader\\WWMIv1\\SkeletonRemapper")
                blend_remap_section.append(scoped_name("ResourceExtraRemappedSkeletonComponent" + str(component_index), draw_ib) + " = copy " + scoped_name("ResourceExtraRemappedSkeletonRW", draw_ib))
                blend_remap_section.new_line()
                blend_remap_id = blend_remap_id + 1

    ini_builder.append_section(blend_remap_section)


def add_commandlist_merge_skeleton_section(ini_builder: M_IniBuilder, draw_ib_model: DrawIBModelWWMI):
    """Command list merging the game's bone data CB into the RW skeletons.

    The WWMI SkeletonMerger compute shader copies whatever resource is bound to
    ``cs-cb8`` into the merged skeleton, without validating the contents. Both
    merges therefore have to be guarded:

    * only a constant buffer that still carries the bone data marker
      (``filter_index = 3381.7777``) contains a skeleton;
    * the regular skeleton occupies ``vs-cb4`` and the extra skeleton - used by
      passes such as anti aliasing - occupies ``vs-cb3`` and is only present
      when BOTH slots carry the marker.

    The two ``$merge_status_id`` gates keep one component from merging twice in
    the same frame, which is both cheaper and the reason the two slot patterns
    can be told apart at all.
    """
    draw_ib = draw_ib_model.draw_ib
    commandlist_section = M_IniSection(M_SectionType.CommandList)
    if MIMIGlobalProperties.import_merged_vgmap() == 'MERGED':
        status_var = scoped_global("merge_status_id", draw_ib)
        commandlist_section.append(scoped_section("CommandListMergeSkeleton", draw_ib))

        # Step 1: the regular skeleton lives in vs-cb4 and is always present for
        # a skinned draw call.
        commandlist_section.append("if " + status_var + " == 0")
        commandlist_section.append("  if vs-cb4 == " + BONE_DATA_FILTER_INDEX)
        commandlist_section.append("    cs-cb8 = ref vs-cb4")
        commandlist_section.append("    cs-u6 = " + scoped_name("ResourceMergedSkeletonRW", draw_ib))
        commandlist_section.append("    $\\WWMIv1\\custom_mesh_scale = 1.00")
        commandlist_section.append("    run = CustomShader\\WWMIv1\\SkeletonMerger")
        commandlist_section.append("    " + status_var + " = 1")
        commandlist_section.append("  endif")
        commandlist_section.append("endif")

        # Step 2: the extra skeleton is only reliably identifiable while the
        # regular one is still in vs-cb4, hence the two conditions.
        commandlist_section.append("if " + status_var + " == 1")
        commandlist_section.append(
            "  if vs-cb4 == " + BONE_DATA_FILTER_INDEX + " && vs-cb3 == " + BONE_DATA_FILTER_INDEX
        )
        commandlist_section.append("    cs-cb8 = ref vs-cb3")
        commandlist_section.append("    cs-u6 = " + scoped_name("ResourceExtraMergedSkeletonRW", draw_ib))
        commandlist_section.append("    $\\WWMIv1\\custom_mesh_scale = 1.00")
        commandlist_section.append("    run = CustomShader\\WWMIv1\\SkeletonMerger")
        commandlist_section.append("    " + status_var + " = 2")
        commandlist_section.append("  endif")
        commandlist_section.append("endif")

        commandlist_section.new_line()
    ini_builder.append_section(commandlist_section)


def add_resource_merged_skeleton(ini_builder: M_IniBuilder, draw_ib_model: DrawIBModelWWMI):
    """Resource declarations for the merged skeleton buffers.

    With a blend remap the RW buffers need double capacity (1536 instead of
    768) because remapped and original skeletons share the same buffer.
    """
    draw_ib = draw_ib_model.draw_ib
    resource_skeleton_section = M_IniSection(M_SectionType.ResourceSkeletonOverride)
    resource_skeleton_section.append(scoped_section("ResourceMergedSkeleton", draw_ib))
    resource_skeleton_section.new_line()
    resource_skeleton_section.append(scoped_section("ResourceMergedSkeletonRW", draw_ib))
    resource_skeleton_section.append("type = RWBuffer")
    resource_skeleton_section.append("format = R32G32B32A32_FLOAT")
    resource_skeleton_section.append("array = 1536" if draw_ib_model.blend_remap else "array = 768")
    resource_skeleton_section.new_line()
    resource_skeleton_section.append(scoped_section("ResourceExtraMergedSkeleton", draw_ib))
    resource_skeleton_section.new_line()
    resource_skeleton_section.append(scoped_section("ResourceExtraMergedSkeletonRW", draw_ib))
    resource_skeleton_section.append("type = RWBuffer")
    resource_skeleton_section.append("format = R32G32B32A32_FLOAT")
    resource_skeleton_section.append("array = 1536" if draw_ib_model.blend_remap else "array = 768")
    ini_builder.append_section(resource_skeleton_section)
