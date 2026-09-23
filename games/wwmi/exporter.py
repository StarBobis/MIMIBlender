"""
WWMI (Wuthering Waves) mod exporter.

WWMI does not follow the standard single-INI pipeline: every DrawIB gets
its own INI file, the export keeps the append order (no section
reordering), and the mod registers itself with the WWMI runtime through
the CommandListRegisterMod flow.  This file holds the main exporter and
its DrawIB-level sections; the shape key and blend remap / merged skeleton
sections live in their own modules of this package.
"""

import os

from ...common.mimi_global_properties import MIMIGlobalProperties
from ...common.global_config import GlobalConfig
from ...common.m_ini_builder import M_IniBuilder, M_IniSection, M_SectionType
from ...common.m_ini_helper import M_IniHelper
from ...common.d3d11_semantics import D3D11Category
from .model import DrawIBModelWWMI
from . import shapekeys
from . import blend_remap


class Exporter:
    """WWMI exporter: one INI per DrawIB, WWMIv1 runtime registration."""

    def __init__(self, blueprint_model):
        self.blueprint_model = blueprint_model
        self.drawib_drawibmodel_dict: dict[str, DrawIBModelWWMI] = {}
        self.parse_draw_ib_draw_ib_model_dict()

    def parse_draw_ib_draw_ib_model_dict(self):
        # Group the blueprint draw calls by DrawIB, keeping first-seen order.
        ordered_draw_ib_list = []
        for drawcall_model in self.blueprint_model.ordered_draw_obj_data_model_list:
            draw_ib = drawcall_model.match_draw_ib
            if draw_ib in ordered_draw_ib_list:
                continue
            ordered_draw_ib_list.append(draw_ib)

        # UniComponent debug: print the submesh assignment of every DrawCallModel
        if MIMIGlobalProperties.is_unico_component():
            print("[UniComponent Export] DrawCallModel list:")
            for dcm in self.blueprint_model.ordered_draw_obj_data_model_list:
                print(f"  obj='{dcm.obj_name}' submesh='{dcm.get_submesh_name()}' draw_ib='{dcm.match_draw_ib}'")

        for draw_ib in ordered_draw_ib_list:
            draw_ib_model = DrawIBModelWWMI(draw_ib=draw_ib, blueprint_model=self.blueprint_model)
            self.drawib_drawibmodel_dict[draw_ib] = draw_ib_model

            # UniComponent debug: print the submesh grouping
            if MIMIGlobalProperties.is_unico_component():
                print(f"[UniComponent Export] DrawIB '{draw_ib}' submesh groups:")
                for idx, group in enumerate(draw_ib_model.submesh_drawcall_groups):
                    names = [dcm.obj_name for dcm in group]
                    sm_name = draw_ib_model.wwmi_info.components[idx] if idx < len(draw_ib_model.wwmi_info.components) else None
                    print(f"  Component {idx}: {names}")

        for draw_ib_model in self.drawib_drawibmodel_dict.values():
            draw_ib_model.apply_drawib_alias()

    def add_constants_section(self, ini_builder: M_IniBuilder, draw_ib_model: DrawIBModelWWMI):
        constants_section = M_IniSection(M_SectionType.Constants)
        constants_section.append("[Constants]")
        constants_section.append("global $required_wwmi_version = 0.91")
        constants_section.append("global $object_guid = " + str(draw_ib_model.wwmi_info.index_count))
        constants_section.append("global $mesh_vertex_count = " + str(draw_ib_model.mesh_vertex_count))
        constants_section.append("global $shapekey_vertex_count = " + str(len(draw_ib_model.obj_buffer_model_wwmi.shapekey_vertex_ids)))
        for batch_id, batch in enumerate(shapekeys.get_wwmi_shapekey_batches(draw_ib_model)):
            constants_section.append("global $shapekey_vertex_offset_batch" + str(batch_id) + " = " + str(batch["custom_vertex_offset"]))
            constants_section.append("global $shapekey_vertex_count_batch" + str(batch_id) + " = " + str(batch["custom_vertex_count"]))
        constants_section.append("global $mod_id = -1000")

        if MIMIGlobalProperties.import_merged_vgmap() == 'MERGED':
            constants_section.append("global $state_id = 0")

        constants_section.append("global $mod_enabled = 0")
        constants_section.append("global $object_detected = 0")
        constants_section.new_line()
        ini_builder.append_section(constants_section)

    def add_present_section(self, ini_builder: M_IniBuilder, draw_ib_model: DrawIBModelWWMI):
        present_section = M_IniSection(M_SectionType.Present)
        present_section.append("[Present]")
        present_section.append("if $object_detected")
        present_section.append("  if $mod_enabled")
        present_section.append("    post $object_detected = 0")

        if MIMIGlobalProperties.import_merged_vgmap() == 'MERGED':
            if draw_ib_model.blend_remap:
                present_section.append("    run = CommandListInitializeBlendRemaps")
            present_section.append("    run = CommandListUpdateMergedSkeleton")

        present_section.append("  else")
        present_section.append("    if $mod_id == -1000")
        present_section.append("      run = CommandListRegisterMod")
        present_section.append("    endif")
        present_section.append("  endif")
        present_section.append("endif")
        present_section.new_line()
        ini_builder.append_section(present_section)

    def add_commandlist_register_mod_section(self, ini_builder: M_IniBuilder, draw_ib_model: DrawIBModelWWMI):
        commandlist_section = M_IniSection(M_SectionType.CommandList)
        commandlist_section.append("[CommandListRegisterMod]")
        commandlist_section.append("$\\WWMIv1\\required_wwmi_version = $required_wwmi_version")
        commandlist_section.append("$\\WWMIv1\\object_guid = $object_guid")
        commandlist_section.append("Resource\\WWMIv1\\ModName = ref ResourceModName")
        commandlist_section.append("Resource\\WWMIv1\\ModAuthor = ref ResourceModAuthor")
        commandlist_section.append("Resource\\WWMIv1\\ModDesc = ref ResourceModDesc")
        commandlist_section.append("Resource\\WWMIv1\\ModLink = ref ResourceModLink")
        commandlist_section.append("Resource\\WWMIv1\\ModLogo = ref ResourceModLogo")
        commandlist_section.append("run = CommandList\\WWMIv1\\RegisterMod")
        commandlist_section.append("$mod_id = $\\WWMIv1\\mod_id")
        commandlist_section.append("if $mod_id >= 0")
        commandlist_section.append("  $mod_enabled = 1")
        commandlist_section.append("endif")
        commandlist_section.new_line()
        ini_builder.append_section(commandlist_section)

    def add_commandlist_trigger_shared_cleanup_section(self, ini_builder: M_IniBuilder, draw_ib_model: DrawIBModelWWMI):
        commandlist_section = M_IniSection(M_SectionType.CommandList)
        commandlist_section.append("[CommandListTriggerResourceOverrides]")
        commandlist_section.append("CheckTextureOverride = ps-t0")
        commandlist_section.append("CheckTextureOverride = ps-t1")
        commandlist_section.append("CheckTextureOverride = ps-t2")
        commandlist_section.append("CheckTextureOverride = ps-t3")
        commandlist_section.append("CheckTextureOverride = ps-t4")
        commandlist_section.append("CheckTextureOverride = ps-t5")
        commandlist_section.append("CheckTextureOverride = ps-t6")
        commandlist_section.append("CheckTextureOverride = ps-t7")
        if MIMIGlobalProperties.import_merged_vgmap() == 'MERGED':
            commandlist_section.append("CheckTextureOverride = vs-cb3")
            commandlist_section.append("CheckTextureOverride = vs-cb4")
        commandlist_section.new_line()

        commandlist_section.append("[ResourceBypassVB0]")
        commandlist_section.new_line()

        commandlist_section.append("[CommandListOverrideSharedResources]")
        commandlist_section.append("ResourceBypassVB0 = ref vb0")
        commandlist_section.append("ib = ResourceIndexBuffer")
        if shapekeys.get_wwmi_shapekey_entries(draw_ib_model):
            commandlist_section.append("run = CommandListApplyShapeKeysPosition")
            commandlist_section.append("run = CommandListApplyShapeKeysVector")
            commandlist_section.append("vb0 = ref ResourcePositionBufferShapeKeyVB")
            commandlist_section.append("vb1 = ref ResourceVectorBufferShapeKeyVB")
        else:
            commandlist_section.append("vb0 = ResourcePositionBuffer")
            commandlist_section.append("vb1 = ResourceVectorBuffer")
        commandlist_section.append("vb2 = ResourceTexcoordBuffer")
        commandlist_section.append("vb3 = ResourceColorBuffer")

        if not draw_ib_model.blend_remap:
            commandlist_section.append("vb4 = ResourceBlendBuffer")

        # Note: here we must use ref instead of a direct "=" assignment.
        # In 3Dmigoto, "= ResourceMergedSkeleton" is a one-time value copy;
        # "= ref ResourceMergedSkeleton" is a reference binding.
        # Without ref, when a later compute shader updates the skeleton, vs-cb will not update in sync.

        if MIMIGlobalProperties.import_merged_vgmap() == 'MERGED':
            if draw_ib_model.blend_remap:
                commandlist_section.append("if ResourceBlendBufferOverride === null")
                commandlist_section.append("vb4 = ResourceBlendBuffer")
                commandlist_section.append("if vs-cb4 == 3381.7777")
                commandlist_section.append("  vs-cb4 = ref ResourceMergedSkeleton")
                commandlist_section.append("  if vs-cb3 == 3381.7777")
                commandlist_section.append("    vs-cb3 = ref ResourceExtraMergedSkeleton")
                commandlist_section.append("  endif")
                commandlist_section.append("else if vs-cb3 == 3381.7777")
                commandlist_section.append("  vs-cb3 = ref ResourceMergedSkeleton")
                commandlist_section.append("endif")
                commandlist_section.append("else")
                commandlist_section.append("vb4 = ref ResourceBlendBufferOverride")
                commandlist_section.append("if vs-cb4 == 3381.7777")
                commandlist_section.append("  vs-cb4 = ref ResourceMergedSkeletonOverride")
                commandlist_section.append("  if vs-cb3 == 3381.7777")
                commandlist_section.append("    vs-cb3 = ref ResourceExtraMergedSkeletonOverride")
                commandlist_section.append("  endif")
                commandlist_section.append("else if vs-cb3 == 3381.7777")
                commandlist_section.append("  vs-cb3 = ref ResourceMergedSkeletonOverride")
                commandlist_section.append("endif")
                commandlist_section.append("endif")
            else:
                commandlist_section.append("if vs-cb4 == 3381.7777")
                commandlist_section.append("  vs-cb4 = ref ResourceMergedSkeleton")
                commandlist_section.append("  if vs-cb3 == 3381.7777")
                commandlist_section.append("    vs-cb3 = ref ResourceExtraMergedSkeleton")
                commandlist_section.append("  endif")
                commandlist_section.append("else if vs-cb3 == 3381.7777")
                commandlist_section.append("  vs-cb3 = ref ResourceMergedSkeleton")
                commandlist_section.append("endif")

        commandlist_section.new_line()
        commandlist_section.append("[CommandListCleanupSharedResources]")
        commandlist_section.append("vb0 = ref ResourceBypassVB0")

        if draw_ib_model.blend_remap:
            commandlist_section.append("if ResourceBlendBufferOverride !== null")
            commandlist_section.append("    ResourceBlendBufferOverride = null")
            commandlist_section.append("    ResourceMergedSkeletonOverride = null")
            commandlist_section.append("    ResourceExtraMergedSkeletonOverride = null")
            commandlist_section.append("endif")

        commandlist_section.new_line()
        ini_builder.append_section(commandlist_section)

    def add_resource_mod_info_section_default(self, ini_builder: M_IniBuilder, draw_ib_model: DrawIBModelWWMI):
        resource_mod_info_section = M_IniSection(M_SectionType.ResourceModInfo)
        resource_mod_info_section.append("[ResourceModName]")
        resource_mod_info_section.append("type = Buffer")
        resource_mod_info_section.append("data = \"Unnamed Mod\"")
        resource_mod_info_section.new_line()
        resource_mod_info_section.append("[ResourceModAuthor]")
        resource_mod_info_section.append("type = Buffer")
        resource_mod_info_section.append("data = \"Unknown Author\"")
        resource_mod_info_section.new_line()
        resource_mod_info_section.append("[ResourceModDesc]")
        resource_mod_info_section.append("; type = Buffer")
        resource_mod_info_section.append("; data = \"Empty Mod Description\"")
        resource_mod_info_section.new_line()
        resource_mod_info_section.append("[ResourceModLink]")
        resource_mod_info_section.append("; type = Buffer")
        resource_mod_info_section.append("; data = \"Empty Mod Link\"")
        resource_mod_info_section.new_line()
        resource_mod_info_section.append("[ResourceModLogo]")
        resource_mod_info_section.append("; filename = Logo.dds")
        resource_mod_info_section.new_line()
        ini_builder.append_section(resource_mod_info_section)

    def add_texture_override_mark_bone_data_cb(self, ini_builder: M_IniBuilder, draw_ib_model: DrawIBModelWWMI):
        texture_override_mark_bonedatacb_section = M_IniSection(M_SectionType.TextureOverrideGeneral)
        texture_override_mark_bonedatacb_section.append("[TextureOverrideMarkBoneDataCB]")
        texture_override_mark_bonedatacb_section.append("hash = " + draw_ib_model.wwmi_info.cb4_hash)
        texture_override_mark_bonedatacb_section.append("match_priority = 0")
        texture_override_mark_bonedatacb_section.append("filter_index = 3381.7777")
        texture_override_mark_bonedatacb_section.new_line()
        ini_builder.append_section(texture_override_mark_bonedatacb_section)

    def add_texture_override_component(self, ini_builder: M_IniBuilder, draw_ib_model: DrawIBModelWWMI):
        texture_override_component = M_IniSection(M_SectionType.TextureOverrideIB)
        component_count = 0

        for component_tmp_obj_name, component_blend_remap_used in draw_ib_model.blend_remap_used.items():
            component_name = "Component " + str(component_count + 1)
            component_count_str = str(component_count)
            component_object = draw_ib_model.wwmi_info.components[component_count]

            texture_override_component.append("[TextureOverrideComponent" + component_count_str + "]")
            texture_override_component.append("hash = " + draw_ib_model.wwmi_info.vb0_hash)
            texture_override_component.append("match_first_index = " + str(component_object.index_offset))
            texture_override_component.append("match_index_count = " + str(component_object.index_count))
            texture_override_component.append("$object_detected = 1")

            if len(self.blueprint_model.keyname_mkey_dict.keys()) != 0:
                texture_override_component.append("$active" + str(GlobalConfig.generated_mod_number) + " = 1")

            texture_override_component.append("if $mod_enabled")

            if MIMIGlobalProperties.import_merged_vgmap() == 'MERGED':
                state_id_var_str = "$state_id_" + component_count_str
                texture_override_component.append("  local " + state_id_var_str)
                texture_override_component.append("  if " + state_id_var_str + " != $state_id")
                texture_override_component.append("    " + state_id_var_str + " = $state_id")
                texture_override_component.append("    $\\WWMIv1\\vg_offset = " + str(component_object.vg_offset))
                texture_override_component.append("    $\\WWMIv1\\vg_count = " + str(component_object.vg_count))
                texture_override_component.append("    run = CommandListMergeSkeleton")
                texture_override_component.append("  endif")
                texture_override_component.append("  if ResourceMergedSkeleton !== null")
                texture_override_component.append("    handling = skip")

                drawindexed_str_list = M_IniHelper.get_drawindexed_str_list(draw_ib_model.submesh_drawcall_groups[component_count])

                if len(drawindexed_str_list) != 0:
                    if component_blend_remap_used:
                        texture_override_component.append("    ResourceBlendBufferOverride = ref ResourceRemappedBlendBufferComponent" + str(component_count))
                        texture_override_component.append("    ResourceMergedSkeletonOverride = ref ResourceRemappedSkeletonComponent" + str(component_count))
                        texture_override_component.append("    ResourceExtraMergedSkeletonOverride = ref ResourceExtraRemappedSkeletonComponent" + str(component_count))

                    texture_override_component.append("    run = CommandListTriggerResourceOverrides")
                    texture_override_component.append("    run = CommandListOverrideSharedResources")
                    texture_override_component.append("    ; Draw Component " + component_count_str)
                    for drawindexed_str in drawindexed_str_list:
                        texture_override_component.append(drawindexed_str)
                    texture_override_component.append("    run = CommandListCleanupSharedResources")
                texture_override_component.append("  endif")
            else:
                drawindexed_str_list = M_IniHelper.get_drawindexed_str_list(draw_ib_model.submesh_drawcall_groups[component_count])
                if len(drawindexed_str_list) != 0:
                    texture_override_component.append("  handling = skip")
                    texture_override_component.append("  run = CommandListTriggerResourceOverrides")
                    texture_override_component.append("  run = CommandListOverrideSharedResources")
                    texture_override_component.append("  ; Draw Component " + component_count_str)
                    for drawindexed_str in drawindexed_str_list:
                        texture_override_component.append(drawindexed_str)
                    texture_override_component.append("  run = CommandListCleanupSharedResources")

            texture_override_component.append("endif")
            texture_override_component.new_line()
            component_count = component_count + 1

        ini_builder.append_section(texture_override_component)

    def add_resource_buffer(self, ini_builder: M_IniBuilder, draw_ib_model: DrawIBModelWWMI):
        # Buffer files live in the Buffers subfolder; INI lines carry the prefix.
        resource_buffer_section = M_IniSection(M_SectionType.ResourceBuffer)

        resource_buffer_section.append("[ResourceIndexBuffer]")
        resource_buffer_section.append("type = Buffer")
        resource_buffer_section.append("format = DXGI_FORMAT_R32_UINT")
        resource_buffer_section.append("stride = 12")
        resource_buffer_section.append("filename = " + GlobalConfig.ini_buffer_filename(draw_ib_model.draw_ib + "-Component1.buf"))
        resource_buffer_section.new_line()

        for category_name, category_stride in draw_ib_model.d3d11_game_type.CategoryStrideDict.items():
            resource_buffer_section.append("[Resource" + category_name + "Buffer]")
            resource_buffer_section.append("type = Buffer")
            if category_name == D3D11Category.POSITION:
                resource_buffer_section.append("format = DXGI_FORMAT_R32G32B32_FLOAT")
            elif category_name == D3D11Category.BLEND:
                resource_buffer_section.append("format = DXGI_FORMAT_R8_UINT")
            elif category_name == "Vector":
                resource_buffer_section.append("format = DXGI_FORMAT_R8G8B8A8_SNORM")
            elif category_name == D3D11Category.COLOR:
                resource_buffer_section.append("format = DXGI_FORMAT_R8G8B8A8_UNORM")
            elif category_name == D3D11Category.TEXCOORD:
                resource_buffer_section.append("format = DXGI_FORMAT_R16G16_FLOAT")
            resource_buffer_section.append("stride = " + str(category_stride))
            resource_buffer_section.append("filename = " + GlobalConfig.ini_buffer_filename(draw_ib_model.draw_ib + "-" + category_name + ".buf"))
            resource_buffer_section.new_line()

            if category_name == D3D11Category.BLEND and draw_ib_model.blend_remap:
                resource_buffer_section.append("[ResourceBlendBufferNoStride]")
                resource_buffer_section.append("type = Buffer")
                resource_buffer_section.append("format = DXGI_FORMAT_R8_UINT")
                resource_buffer_section.append("filename = " + GlobalConfig.ini_buffer_filename(draw_ib_model.draw_ib + "-" + category_name + ".buf"))
                resource_buffer_section.new_line()

        if draw_ib_model.blend_remap:
            resource_buffer_section.append("[ResourceBlendRemapVertexVGBuffer]")
            resource_buffer_section.append("type = Buffer")
            resource_buffer_section.append("format = DXGI_FORMAT_R16_UINT")
            resource_buffer_section.append("filename = " + GlobalConfig.ini_buffer_filename(draw_ib_model.draw_ib + "-BlendRemapVertexVG.buf"))
            resource_buffer_section.new_line()

            resource_buffer_section.append("[ResourceBlendRemapForwardBuffer]")
            resource_buffer_section.append("type = Buffer")
            resource_buffer_section.append("format = DXGI_FORMAT_R16_UINT")
            resource_buffer_section.append("filename = " + GlobalConfig.ini_buffer_filename(draw_ib_model.draw_ib + "-BlendRemapForward.buf"))
            resource_buffer_section.new_line()

            resource_buffer_section.append("[ResourceBlendRemapReverseBuffer]")
            resource_buffer_section.append("type = Buffer")
            resource_buffer_section.append("format = DXGI_FORMAT_R16_UINT")
            resource_buffer_section.append("filename = " + GlobalConfig.ini_buffer_filename(draw_ib_model.draw_ib + "-BlendRemapReverse.buf"))
            resource_buffer_section.new_line()

        resource_buffer_section.append("[ResourceShapeKeyOffsetBuffer]")
        resource_buffer_section.append("type = Buffer")
        resource_buffer_section.append("format = DXGI_FORMAT_R32G32B32A32_UINT")
        resource_buffer_section.append("stride = 16")
        resource_buffer_section.append("filename = " + GlobalConfig.ini_buffer_filename(draw_ib_model.draw_ib + "-ShapeKeyOffset.buf"))
        resource_buffer_section.new_line()

        resource_buffer_section.append("[ResourceShapeKeyVertexIdBuffer]")
        resource_buffer_section.append("type = Buffer")
        resource_buffer_section.append("format = DXGI_FORMAT_R32_UINT")
        resource_buffer_section.append("stride = 4")
        resource_buffer_section.append("filename = " + GlobalConfig.ini_buffer_filename(draw_ib_model.draw_ib + "-ShapeKeyVertexId.buf"))
        resource_buffer_section.new_line()

        resource_buffer_section.append("[ResourceShapeKeyVertexOffsetBuffer]")
        resource_buffer_section.append("type = Buffer")
        resource_buffer_section.append("format = DXGI_FORMAT_R16_FLOAT")
        resource_buffer_section.append("stride = 2")
        resource_buffer_section.append("filename = " + GlobalConfig.ini_buffer_filename(draw_ib_model.draw_ib + "-ShapeKeyVertexOffset.buf"))
        resource_buffer_section.new_line()

        ini_builder.append_section(resource_buffer_section)

    def generate_unreal_vs_config_ini(self):
        """Generate one INI per DrawIB, keeping the append order of sections."""
        config_ini_builder = M_IniBuilder()

        for draw_ib, draw_ib_model in self.drawib_drawibmodel_dict.items():
            self.add_constants_section(ini_builder=config_ini_builder, draw_ib_model=draw_ib_model)
            self.add_present_section(ini_builder=config_ini_builder, draw_ib_model=draw_ib_model)
            self.add_commandlist_register_mod_section(ini_builder=config_ini_builder, draw_ib_model=draw_ib_model)
            blend_remap.add_commandlist_update_merged_skeleton(ini_builder=config_ini_builder, draw_ib_model=draw_ib_model)
            blend_remap.add_blend_remap_sections(ini_builder=config_ini_builder, draw_ib_model=draw_ib_model)
            self.add_resource_mod_info_section_default(ini_builder=config_ini_builder, draw_ib_model=draw_ib_model)
            self.add_texture_override_mark_bone_data_cb(ini_builder=config_ini_builder, draw_ib_model=draw_ib_model)
            blend_remap.add_commandlist_merge_skeleton_section(ini_builder=config_ini_builder, draw_ib_model=draw_ib_model)
            self.add_commandlist_trigger_shared_cleanup_section(ini_builder=config_ini_builder, draw_ib_model=draw_ib_model)
            self.add_texture_override_component(ini_builder=config_ini_builder, draw_ib_model=draw_ib_model)
            shapekeys.add_texture_override_shapekeys(ini_builder=config_ini_builder, draw_ib_model=draw_ib_model)
            shapekeys.add_resource_shapekeys(ini_builder=config_ini_builder, draw_ib_model=draw_ib_model)
            shapekeys.add_wwmi_shapekey_sections(ini_builder=config_ini_builder, draw_ib_model=draw_ib_model)

            if MIMIGlobalProperties.import_merged_vgmap() == 'MERGED':
                blend_remap.add_resource_merged_skeleton(ini_builder=config_ini_builder, draw_ib_model=draw_ib_model)

            self.add_resource_buffer(ini_builder=config_ini_builder, draw_ib_model=draw_ib_model)

            print("=" * 60)
            print("[TRACE] generate_unreal_vs_config_ini: DrawIB=" + draw_ib + " - start copying Slot textures...")
            M_IniHelper.move_slot_style_textures(draw_ib_model=draw_ib_model)
            print("[TRACE] generate_unreal_vs_config_ini: DrawIB=" + draw_ib + " - Slot texture copy done")

            GlobalConfig.generated_mod_number = GlobalConfig.generated_mod_number + 1
            M_IniHelper.add_branch_key_sections(ini_builder=config_ini_builder, key_name_mkey_dict=self.blueprint_model.keyname_mkey_dict)

            print("[TRACE] generate_unreal_vs_config_ini: DrawIB=" + draw_ib + " - start generating Hash texture INI...")
            global_hash_rows = getattr(self.blueprint_model, "global_hash_texture_binding_list", [])
            M_IniHelper.generate_hash_style_global_texture_ini(
                ini_builder=config_ini_builder,
                global_hash_texture_binding_list=global_hash_rows,
            )
            M_IniHelper.generate_hash_style_texture_ini(
                ini_builder=config_ini_builder,
                drawib_drawibmodel_dict=self.drawib_drawibmodel_dict,
                global_hash_texture_binding_list=global_hash_rows,
            )
            M_IniHelper.generate_shared_slot_style_texture_ini(ini_builder=config_ini_builder, drawib_drawibmodel_dict=self.drawib_drawibmodel_dict)
            # Texture Bind node FILE resources are explicit user intent and
            # must exist even when the automatic texture pipeline is off.
            M_IniHelper.add_object_texture_binding_resource_sections(ini_builder=config_ini_builder, draw_ib_model=draw_ib_model)
            # Conditional hash overrides from Hash Texture Bind nodes follow
            # the same explicit-intent rule (full dict, like the generators above).
            M_IniHelper.generate_hash_style_object_texture_ini(
                ini_builder=config_ini_builder,
                drawib_drawibmodel_dict=self.drawib_drawibmodel_dict,
            )
            # Copy explicit object texture replacements after automatic Hash
            # generation so a marked filename is not overwritten by its
            # original extracted bytes.
            M_IniHelper.move_object_texture_binding_files(draw_ib_model=draw_ib_model)
            print("[TRACE] generate_unreal_vs_config_ini: DrawIB=" + draw_ib + " - Hash/SharedSlot texture INI generation done")
            print("=" * 60)

            config_ini_builder.save_to_file_not_reorder(os.path.join(GlobalConfig.path_generate_mod_folder(), GlobalConfig.get_generated_mod_name() + "_" + draw_ib + ".ini"))
            config_ini_builder.clear()

    def export(self):
        for draw_ib_model in self.drawib_drawibmodel_dict.values():
            draw_ib_model.write_buffer_files()
        self.generate_unreal_vs_config_ini()
