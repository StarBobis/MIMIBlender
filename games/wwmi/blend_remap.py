"""
WWMI blend remap + merged skeleton INI sections.

These sections implement the merged-skeleton workflow of WWMI mods:
- the per-frame merged skeleton update command lists,
- the optional blend remap resources and command lists used when some
  components need their blend indices remapped onto the merged skeleton,
- the merged skeleton resource declarations.
"""

from ...common.mimi_global_properties import MIMIGlobalProperties
from ...common.m_ini_builder import M_IniBuilder, M_IniSection, M_SectionType
from .model import DrawIBModelWWMI


def add_commandlist_update_merged_skeleton(ini_builder: M_IniBuilder, draw_ib_model: DrawIBModelWWMI):
    """Per-frame merged skeleton update: swap the state id and copy the RW
    skeleton buffers (plus the remap step when a blend remap is active)."""
    commandlist_section = M_IniSection(M_SectionType.CommandList)
    if MIMIGlobalProperties.import_merged_vgmap() == 'MERGED':
        commandlist_section.append("[CommandListUpdateMergedSkeleton]")
        commandlist_section.append("if $state_id")
        commandlist_section.append("  $state_id = 0")
        commandlist_section.append("else")
        commandlist_section.append("  $state_id = 1")
        commandlist_section.append("endif")
        commandlist_section.append("ResourceMergedSkeleton = copy ResourceMergedSkeletonRW")
        commandlist_section.append("ResourceExtraMergedSkeleton = copy ResourceExtraMergedSkeletonRW")
        if draw_ib_model.blend_remap:
            commandlist_section.append("run = CommandListRemapMergedSkeleton")
        commandlist_section.new_line()
    ini_builder.append_section(commandlist_section)


def add_blend_remap_sections(ini_builder: M_IniBuilder, draw_ib_model: DrawIBModelWWMI):
    """Blend remap resources + command lists.

    Only components flagged in draw_ib_model.blend_remap_used get their own
    remapped blend/skeleton buffers; the others keep using the shared ones.
    """
    blend_remap_section = M_IniSection(M_SectionType.CommandList)

    if MIMIGlobalProperties.import_merged_vgmap() == 'MERGED':
        blend_remap_section.append("[ResourceMergedSkeletonRemap]")
        blend_remap_section.append("[ResourceExtraMergedSkeletonRemap]")
        blend_remap_section.new_line()

        blend_remap_section.append("[ResourceBlendBufferOverride]")
        blend_remap_section.append("[ResourceExtraMergedSkeletonOverride]")
        blend_remap_section.append("[ResourceMergedSkeletonOverride]")
        blend_remap_section.new_line()

        blend_remap_section.append("[ResourceRemappedBlendBufferRW]")
        blend_remap_section.append("[ResourceRemappedSkeletonRW]")
        blend_remap_section.append("[ResourceExtraRemappedSkeletonRW]")
        blend_remap_section.new_line()

        component_count = 0
        for component_tmp_obj_name, use_remap in draw_ib_model.blend_remap_used.items():
            if not use_remap:
                component_count += 1
                continue
            blend_remap_section.append("[ResourceRemappedBlendBufferComponent" + str(component_count) + "]")
            blend_remap_section.append("[ResourceRemappedSkeletonComponent" + str(component_count) + "]")
            blend_remap_section.append("[ResourceExtraRemappedSkeletonComponent" + str(component_count) + "]")
            blend_remap_section.new_line()
            component_count += 1

        if draw_ib_model.blend_remap:
            blend_remap_section.append("[CommandListInitializeBlendRemaps]")
            blend_remap_section.append("local $blend_remaps_initialized")
            blend_remap_section.append("if !$blend_remaps_initialized")
            blend_remap_section.append("  ResourceRemappedSkeletonRW = copy ResourceMergedSkeletonRW")
            blend_remap_section.append("  ResourceExtraRemappedSkeletonRW = copy ResourceExtraMergedSkeletonRW")
            blend_remap_section.new_line()
            blend_remap_section.append("  $\\WWMIv1\\custom_vertex_count = $mesh_vertex_count")
            weights_per_vertex_count = draw_ib_model.d3d11_game_type.get_blendindices_count_wwmi()
            blend_remap_section.append("  $\\WWMIv1\\weights_per_vertex_count = " + str(weights_per_vertex_count))
            blend_remap_section.append("  cs-t34 = ref ResourceBlendRemapReverseBuffer")
            blend_remap_section.append("  cs-t35 = ref ResourceBlendRemapVertexVGBuffer")

            blend_remap_id = 0
            component_count = 0
            for component_tmp_obj_name, use_remap in draw_ib_model.blend_remap_used.items():
                if not use_remap:
                    component_count += 1
                    continue
                component_count_str = str(component_count)
                blend_remap_section.append("    $\\WWMIv1\\blend_remap_id = " + str(blend_remap_id))
                blend_remap_section.append("    ResourceRemappedBlendBufferRW = copy ResourceBlendBufferNoStride")
                blend_remap_section.append("    cs-u4 = ref ResourceRemappedBlendBufferRW")
                blend_remap_section.append("    run = CustomShader\\WWMIv1\\BlendRemapper")
                blend_remap_section.append("    ResourceRemappedBlendBufferComponent" + component_count_str + " = copy ResourceRemappedBlendBufferRW")
                blend_remap_section.append("    ResourceRemappedBlendBufferComponent" + component_count_str + " = copy_desc ResourceBlendBuffer")
                blend_remap_section.new_line()
                blend_remap_id = blend_remap_id + 1
                component_count += 1

            blend_remap_section.append("    $blend_remaps_initialized = 1")
            blend_remap_section.append("endif")
            blend_remap_section.new_line()

        blend_remap_section.append("[CommandListRemapMergedSkeleton]")
        blend_remap_section.append("ResourceMergedSkeletonRemap = copy ResourceMergedSkeletonRW")
        blend_remap_section.append("ResourceExtraMergedSkeletonRemap = copy ResourceExtraMergedSkeletonRW")
        blend_remap_section.new_line()
        if draw_ib_model.blend_remap:
            blend_remap_section.append("cs-t37 = ResourceBlendRemapForwardBuffer")
            blend_remap_section.new_line()

            blend_remap_id = 0
            component_count = 0
            for component_tmp_obj_name, use_remap in draw_ib_model.blend_remap_used.items():
                if not use_remap:
                    component_count += 1
                    continue

                blend_remap_section.append("$\\WWMIv1\\blend_remap_id = " + str(blend_remap_id))
                vg_count = draw_ib_model.component_real_vg_count_dict[component_count]
                blend_remap_section.append("$\\WWMIv1\\vg_count = " + str(vg_count))
                blend_remap_section.append("cs-t38 = ResourceMergedSkeletonRemap")
                blend_remap_section.append("cs-u5 = ResourceRemappedSkeletonRW")
                blend_remap_section.append("run = CustomShader\\WWMIv1\\SkeletonRemapper")
                blend_remap_section.append("ResourceRemappedSkeletonComponent" + str(component_count) + " = copy ResourceRemappedSkeletonRW")
                blend_remap_section.append("cs-t38 = ResourceExtraMergedSkeletonRemap")
                blend_remap_section.append("cs-u5 = ResourceExtraRemappedSkeletonRW")
                blend_remap_section.append("run = CustomShader\\WWMIv1\\SkeletonRemapper")
                blend_remap_section.append("ResourceExtraRemappedSkeletonComponent" + str(component_count) + " = copy ResourceExtraRemappedSkeletonRW")
                blend_remap_section.new_line()
                blend_remap_id = blend_remap_id + 1
                component_count += 1

    ini_builder.append_section(blend_remap_section)


def add_commandlist_merge_skeleton_section(ini_builder: M_IniBuilder, draw_ib_model: DrawIBModelWWMI):
    """Command list merging the game's bone data CB into the RW skeletons."""
    commandlist_section = M_IniSection(M_SectionType.CommandList)
    if MIMIGlobalProperties.import_merged_vgmap() == 'MERGED':
        commandlist_section.append("[CommandListMergeSkeleton]")
        commandlist_section.append("$\\WWMIv1\\custom_mesh_scale = 1.00")
        commandlist_section.append("cs-cb8 = ref vs-cb4")
        commandlist_section.append("cs-u6 = ResourceMergedSkeletonRW")
        commandlist_section.append("run = CustomShader\\WWMIv1\\SkeletonMerger")
        commandlist_section.append("cs-cb8 = ref vs-cb3")
        commandlist_section.append("cs-u6 = ResourceExtraMergedSkeletonRW")
        commandlist_section.append("run = CustomShader\\WWMIv1\\SkeletonMerger")
        commandlist_section.new_line()
    ini_builder.append_section(commandlist_section)


def add_resource_merged_skeleton(ini_builder: M_IniBuilder, draw_ib_model: DrawIBModelWWMI):
    """Resource declarations for the merged skeleton buffers.

    With a blend remap the RW buffers need double capacity (1536 instead of
    768) because remapped and original skeletons share the same buffer.
    """
    resource_skeleton_section = M_IniSection(M_SectionType.ResourceSkeletonOverride)
    resource_skeleton_section.append("[ResourceMergedSkeleton]")
    resource_skeleton_section.new_line()
    resource_skeleton_section.append("[ResourceMergedSkeletonRW]")
    resource_skeleton_section.append("type = RWBuffer")
    resource_skeleton_section.append("format = R32G32B32A32_FLOAT")
    resource_skeleton_section.append("array = 1536" if draw_ib_model.blend_remap else "array = 768")
    resource_skeleton_section.new_line()
    resource_skeleton_section.append("[ResourceExtraMergedSkeleton]")
    resource_skeleton_section.new_line()
    resource_skeleton_section.append("[ResourceExtraMergedSkeletonRW]")
    resource_skeleton_section.append("type = RWBuffer")
    resource_skeleton_section.append("format = R32G32B32A32_FLOAT")
    resource_skeleton_section.append("array = 1536" if draw_ib_model.blend_remap else "array = 768")
    ini_builder.append_section(resource_skeleton_section)
