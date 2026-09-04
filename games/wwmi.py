import os

import shutil

from ..common.global_properties import GlobalProperties
from ..common.global_config import GlobalConfig
from ..common.global_config import LogicName
from ..model.drawib_model_wwmi import DrawIBModelWWMI
from ..model.blueprint_model import BluePrintModel
from ..blueprint.blueprint_export_helper import BlueprintExportHelper
from ..common.m_ini_builder import M_IniBuilder, M_IniSection, M_SectionType
from ..common.global_config import GlobalConfig
from ..common.d3d11_semantics import D3D11Category
from ..common.m_ini_helper import M_IniHelper
from ..common.m_ini_helper_gui import M_IniHelperGUI


class ExportWWMI:
    def __init__(self, blueprint_model: BluePrintModel):
        self.blueprint_model = blueprint_model
        self.drawib_drawibmodel_dict: dict[str, DrawIBModelWWMI] = {}
        self.parse_draw_ib_draw_ib_model_dict()

    def parse_draw_ib_draw_ib_model_dict(self):
        ordered_draw_ib_list = []
        for drawcall_model in self.blueprint_model.ordered_draw_obj_data_model_list:
            draw_ib = drawcall_model.match_draw_ib
            if draw_ib in ordered_draw_ib_list:
                continue
            ordered_draw_ib_list.append(draw_ib)

        # UniComponent 调试：打印所有 DrawCallModel 的 submesh 分配
        if GlobalProperties.is_unico_component():
            print("[UniComponent Export] DrawCallModel 列表:")
            for dcm in self.blueprint_model.ordered_draw_obj_data_model_list:
                print(f"  obj='{dcm.obj_name}' submesh='{dcm.get_submesh_name()}' draw_ib='{dcm.match_draw_ib}'")

        for draw_ib in ordered_draw_ib_list:
            draw_ib_model = DrawIBModelWWMI(draw_ib=draw_ib, blueprint_model=self.blueprint_model)
            self.drawib_drawibmodel_dict[draw_ib] = draw_ib_model

            # UniComponent 调试：打印 submesh 分组
            if GlobalProperties.is_unico_component():
                print(f"[UniComponent Export] DrawIB '{draw_ib}' submesh 分组:")
                for idx, group in enumerate(draw_ib_model.submesh_drawcall_groups):
                    names = [dcm.obj_name for dcm in group]
                    sm_name = draw_ib_model.wwmi_info.components[idx] if idx < len(draw_ib_model.wwmi_info.components) else None
                    print(f"  Component {idx}: {names}")

        for draw_ib_model in self.drawib_drawibmodel_dict.values():
            draw_ib_model.apply_drawib_alias()

    @staticmethod
    def get_safe_shapekey_name(shapekey_name: str) -> str:
        return DrawIBModelWWMI.get_safe_shapekey_name(shapekey_name)

    @staticmethod
    def get_wwmi_shapekey_entries(draw_ib_model: DrawIBModelWWMI | None = None):
        shapekeyname_mkey_dict = BlueprintExportHelper.get_current_shapekeyname_mkey_dict()
        if draw_ib_model is not None:
            available_names = (
                set(draw_ib_model.obj_buffer_model_wwmi.shapekey_position_buffer_dict.keys())
                & set(draw_ib_model.obj_buffer_model_wwmi.shapekey_vector_buffer_dict.keys())
            )
            shapekeyname_mkey_dict = {
                shapekey_name: m_key
                for shapekey_name, m_key in shapekeyname_mkey_dict.items()
                if shapekey_name in available_names
            }
        return [
            (shapekey_name, ExportWWMI.get_safe_shapekey_name(shapekey_name), m_key)
            for shapekey_name, m_key in shapekeyname_mkey_dict.items()
        ]

    @staticmethod
    def copy_wwmi_shapekey_shaders_to_mod_folder():
        res_path = os.path.join(GlobalConfig.path_generate_mod_folder(), "res")
        os.makedirs(res_path, exist_ok=True)

        addon_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for filename in ("ShapesWWMIPosition.hlsl", "ShapesWWMIVector.hlsl"):
            src = os.path.join(addon_root, "resources", filename)
            shutil.copy2(src, os.path.join(res_path, filename))

    def add_constants_section(self, ini_builder: M_IniBuilder, draw_ib_model: DrawIBModelWWMI):
        constants_section = M_IniSection(M_SectionType.Constants)
        constants_section.append("[Constants]")
        constants_section.append("global $required_wwmi_version = 0.91")
        constants_section.append("global $object_guid = " + str(draw_ib_model.wwmi_info.index_count))
        constants_section.append("global $mesh_vertex_count = " + str(draw_ib_model.mesh_vertex_count))
        constants_section.append("global $shapekey_vertex_count = " + str(len(draw_ib_model.obj_buffer_model_wwmi.shapekey_vertex_ids)))
        for batch_id, batch in enumerate(self.get_wwmi_shapekey_batches(draw_ib_model)):
            constants_section.append("global $shapekey_vertex_offset_batch" + str(batch_id) + " = " + str(batch["custom_vertex_offset"]))
            constants_section.append("global $shapekey_vertex_count_batch" + str(batch_id) + " = " + str(batch["custom_vertex_count"]))
        constants_section.append("global $mod_id = -1000")

        if GlobalProperties.import_merged_vgmap() == 'MERGED':
            constants_section.append("global $state_id = 0")

        constants_section.append("global $mod_enabled = 0")
        constants_section.append("global $object_detected = 0")
        constants_section.new_line()
        ini_builder.append_section(constants_section)

    @staticmethod
    def get_wwmi_shapekey_batches(draw_ib_model: DrawIBModelWWMI) -> list[dict]:
        shapekey_offsets = draw_ib_model.obj_buffer_model_wwmi.shapekey_offsets
        if not shapekey_offsets:
            return []

        batch_count = len(shapekey_offsets) // 128
        metadata_batches = list(getattr(draw_ib_model.wwmi_info.shapekeys, "batches", []) or [])
        if not metadata_batches and getattr(draw_ib_model.wwmi_info.shapekeys, "checksum", 0):
            metadata_batches = [{
                "vertex_offset": 0,
                "dispatch_y": draw_ib_model.wwmi_info.shapekeys.dispatch_y,
                "checksum": draw_ib_model.wwmi_info.shapekeys.checksum,
            }]
        if len(metadata_batches) < batch_count:
            return []

        batches = []
        custom_vertex_offset = 0
        for batch_id in range(batch_count):
            batch_offsets = shapekey_offsets[batch_id * 128:(batch_id + 1) * 128]
            custom_vertex_count = batch_offsets[-1] if batch_offsets else 0
            metadata = metadata_batches[batch_id]
            if int(metadata.get("checksum", 0)) == 0:
                return []
            batches.append({
                "checksum": int(metadata.get("checksum", 0)),
                "original_vertex_offset": int(metadata.get("vertex_offset", 0)),
                "dispatch_y": int(metadata.get("dispatch_y", 0)),
                "custom_vertex_offset": custom_vertex_offset,
                "custom_vertex_count": custom_vertex_count,
            })
            custom_vertex_offset += custom_vertex_count
        return batches

    def add_present_section(self, ini_builder: M_IniBuilder, draw_ib_model: DrawIBModelWWMI):
        present_section = M_IniSection(M_SectionType.Present)
        present_section.append("[Present]")
        present_section.append("if $object_detected")
        present_section.append("  if $mod_enabled")
        present_section.append("    post $object_detected = 0")

        if GlobalProperties.import_merged_vgmap() == 'MERGED':
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

    def add_commandlist_update_merged_skeleton(self, ini_builder: M_IniBuilder, draw_ib_model: DrawIBModelWWMI):
        commandlist_section = M_IniSection(M_SectionType.CommandList)
        if GlobalProperties.import_merged_vgmap() == 'MERGED':
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

    def add_blend_remap_sections(self, ini_builder: M_IniBuilder, draw_ib_model: DrawIBModelWWMI):
        blend_remap_section = M_IniSection(M_SectionType.CommandList)

        if GlobalProperties.import_merged_vgmap() == 'MERGED':
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
        if GlobalProperties.import_merged_vgmap() == 'MERGED':
            commandlist_section.append("CheckTextureOverride = vs-cb3")
            commandlist_section.append("CheckTextureOverride = vs-cb4")
        commandlist_section.new_line()

        commandlist_section.append("[ResourceBypassVB0]")
        commandlist_section.new_line()

        commandlist_section.append("[CommandListOverrideSharedResources]")
        commandlist_section.append("ResourceBypassVB0 = ref vb0")
        commandlist_section.append("ib = ResourceIndexBuffer")
        if self.get_wwmi_shapekey_entries(draw_ib_model):
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
        
        # 娉ㄦ剰锛岃繖閲屽繀椤荤敤ref 鑰屼笉鏄洿鎺?= 
        # 鍦?Dmigoto涓?Dmigoto 涓?= ResourceMergedSkeleton 鏄竴娆℃€у€兼嫹璐濓紝
        # = ref ResourceMergedSkeleton 鎵嶆槸寮曠敤缁戝畾銆?
        # 缂哄皯 ref 鎰忓懗鐫€鍚庣画 compute shader 鏇存柊楠ㄦ灦鏃讹紝vs-cb 涓嶄細鍚屾鏇存柊銆?

        if GlobalProperties.import_merged_vgmap() == 'MERGED':
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

    def add_commandlist_merge_skeleton_section(self, ini_builder: M_IniBuilder, draw_ib_model: DrawIBModelWWMI):
        commandlist_section = M_IniSection(M_SectionType.CommandList)
        if GlobalProperties.import_merged_vgmap() == 'MERGED':
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
        resource_mod_info_section.append("; filename = Textures/Logo.dds")
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
                if GlobalProperties.generate_branch_mod_gui():
                    texture_override_component.append("$ActiveCharacter = 1")

            texture_override_component.append("if $mod_enabled")

            if GlobalProperties.import_merged_vgmap() == 'MERGED':
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

    def add_texture_override_shapekeys(self, ini_builder: M_IniBuilder, draw_ib_model: DrawIBModelWWMI):
        shapekey_batches = self.get_wwmi_shapekey_batches(draw_ib_model)
        if not shapekey_batches:
            return

        texture_override_shapekeys_section = M_IniSection(M_SectionType.TextureOverrideShapeKeys)

        shapekey_offsets_hash = draw_ib_model.wwmi_info.shapekeys.offsets_hash
        if shapekey_offsets_hash != "":
            texture_override_shapekeys_section.append("[TextureOverrideShapeKeyOffsets]")
            texture_override_shapekeys_section.append("hash = " + shapekey_offsets_hash)
            texture_override_shapekeys_section.append("match_priority = 0")
            texture_override_shapekeys_section.append("override_byte_stride = 24")
            texture_override_shapekeys_section.append("override_vertex_count = $mesh_vertex_count")
            texture_override_shapekeys_section.new_line()

        shapekey_scale_hash = draw_ib_model.wwmi_info.shapekeys.scale_hash
        if shapekey_scale_hash != "":
            texture_override_shapekeys_section.append("[TextureOverrideShapeKeyScale]")
            texture_override_shapekeys_section.append("hash = " + draw_ib_model.wwmi_info.shapekeys.scale_hash)
            texture_override_shapekeys_section.append("match_priority = 0")
            texture_override_shapekeys_section.append("override_byte_stride = 4")
            texture_override_shapekeys_section.append("override_vertex_count = $mesh_vertex_count")
            texture_override_shapekeys_section.new_line()

        texture_override_shapekeys_section.append("[CommandListSetupShapeKeysBatch]")
        for batch_id, batch in enumerate(shapekey_batches):
            texture_override_shapekeys_section.append("$\\WWMIv1\\shapekey_checksum_batch" + str(batch_id) + " = " + str(batch["checksum"]))
            texture_override_shapekeys_section.append("$\\WWMIv1\\shapekey_vertex_offset_original_batch" + str(batch_id) + " = " + str(batch["original_vertex_offset"]))
            texture_override_shapekeys_section.append("$\\WWMIv1\\shapekey_vertex_offset_custom_batch" + str(batch_id) + " = $shapekey_vertex_offset_batch" + str(batch_id))
        texture_override_shapekeys_section.append("cs-t33 = ResourceShapeKeyOffsetBuffer")
        texture_override_shapekeys_section.append("cs-u5 = ResourceCustomShapeKeyValuesRW")
        texture_override_shapekeys_section.append("cs-u6 = ResourceShapeKeyCBRW")
        texture_override_shapekeys_section.append("run = CustomShader\\WWMIv1\\ShapeKeyBatchOverrider")
        texture_override_shapekeys_section.new_line()

        texture_override_shapekeys_section.append("[CommandListLoadShapeKeysBatch]")
        for batch_id, batch in enumerate(shapekey_batches):
            texture_override_shapekeys_section.append("$\\WWMIv1\\shapekey_dispatch_size_y_original_batch" + str(batch_id) + " = " + str(batch["dispatch_y"]))
            texture_override_shapekeys_section.append("$\\WWMIv1\\shapekey_vertex_count_batch" + str(batch_id) + " = $shapekey_vertex_count_batch" + str(batch_id))
        texture_override_shapekeys_section.append("cs-t0 = ResourceShapeKeyVertexIdBuffer")
        texture_override_shapekeys_section.append("cs-t1 = ResourceShapeKeyVertexOffsetBuffer")
        texture_override_shapekeys_section.append("cs-u6 = ResourceShapeKeyCBRW")
        texture_override_shapekeys_section.append("run = CommandList\\WWMIv1\\LoadShapeKeysBatch")
        texture_override_shapekeys_section.new_line()

        if shapekey_offsets_hash != "":
            texture_override_shapekeys_section.append("[TextureOverrideShapeKeyLoaderCallback]")
            texture_override_shapekeys_section.append("hash = " + draw_ib_model.wwmi_info.shapekeys.offsets_hash)
            texture_override_shapekeys_section.append("match_priority = 0")
            texture_override_shapekeys_section.append("if $mod_enabled")
            if GlobalProperties.import_merged_vgmap() == 'MERGED':
                texture_override_shapekeys_section.append("  if cs == 3381.3333 && ResourceMergedSkeleton !== null")
            else:
                texture_override_shapekeys_section.append("  if cs == 3381.3333")
            texture_override_shapekeys_section.append("    handling = skip")
            texture_override_shapekeys_section.append("    run = CommandListSetupShapeKeysBatch")
            texture_override_shapekeys_section.append("    run = CommandListLoadShapeKeysBatch")
            texture_override_shapekeys_section.append("  endif")
            texture_override_shapekeys_section.append("endif")
            texture_override_shapekeys_section.new_line()

        texture_override_shapekeys_section.append("[CommandListMultiplyShapeKeys]")
        texture_override_shapekeys_section.append("$\\WWMIv1\\custom_vertex_count = $mesh_vertex_count")
        texture_override_shapekeys_section.append("run = CustomShader\\WWMIv1\\ShapeKeyMultiplier")
        texture_override_shapekeys_section.new_line()

        if shapekey_offsets_hash != "":
            texture_override_shapekeys_section.append("[TextureOverrideShapeKeyMultiplierCallback]")
            texture_override_shapekeys_section.append("hash = " + draw_ib_model.wwmi_info.shapekeys.offsets_hash)
            texture_override_shapekeys_section.append("match_priority = 0")
            texture_override_shapekeys_section.append("if $mod_enabled")
            if GlobalProperties.import_merged_vgmap() == 'MERGED':
                texture_override_shapekeys_section.append("  if cs == 3381.4444 && ResourceMergedSkeleton !== null")
            else:
                texture_override_shapekeys_section.append("  if cs == 3381.4444")
            texture_override_shapekeys_section.append("    handling = skip")
            texture_override_shapekeys_section.append("    run = CommandListMultiplyShapeKeys")
            texture_override_shapekeys_section.append("  endif")
            texture_override_shapekeys_section.append("endif")
            texture_override_shapekeys_section.new_line()

        ini_builder.append_section(texture_override_shapekeys_section)

    def add_resource_shapekeys(self, ini_builder: M_IniBuilder, draw_ib_model: DrawIBModelWWMI):
        shapekey_batches = self.get_wwmi_shapekey_batches(draw_ib_model)
        if not shapekey_batches:
            return

        resource_shapekeys_section = M_IniSection(M_SectionType.ResourceShapeKeysOverride)
        resource_shapekeys_section.append("; Resources: Shape Keys Override -------------------------")
        resource_shapekeys_section.append("[ResourceShapeKeyCBRW]")
        resource_shapekeys_section.append("type = RWBuffer")
        resource_shapekeys_section.append("format = R32G32B32A32_UINT")
        resource_shapekeys_section.append("array = 66")
        resource_shapekeys_section.append("[ResourceCustomShapeKeyValuesRW]")
        resource_shapekeys_section.append("type = RWBuffer")
        resource_shapekeys_section.append("format = R32G32B32A32_FLOAT")
        resource_shapekeys_section.append("array = " + str(32 * len(shapekey_batches)))
        ini_builder.append_section(resource_shapekeys_section)

    def add_wwmi_shapekey_sections(self, ini_builder: M_IniBuilder, draw_ib_model: DrawIBModelWWMI):
        shapekey_entries = self.get_wwmi_shapekey_entries(draw_ib_model)
        if not shapekey_entries:
            return

        self.copy_wwmi_shapekey_shaders_to_mod_folder()

        constants_section = M_IniSection(M_SectionType.Constants)
        constants_section.SectionName = "Constants"
        for shapekey_name, _safe_name, m_key in shapekey_entries:
            constants_section.append("; ShapeKey: " + shapekey_name)
            constants_section.append("global persist " + m_key.key_name + " = " + str(m_key.initialize_value))
            constants_section.new_line()
        ini_builder.append_section(constants_section)

        key_section = M_IniSection(M_SectionType.Key)
        for shapekey_name, _safe_name, m_key in shapekey_entries:
            if m_key.initialize_vk_str == "":
                continue

            key_section.append("[Key_ShapeKey_" + shapekey_name + "]")
            comment = getattr(m_key, 'comment', '')
            if comment:
                key_section.append("; " + comment)
            key_section.append("key = " + m_key.initialize_vk_str)
            key_section.append("type = cycle")
            key_section.append(m_key.key_name + " = 0,0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8,0.9,1")
            key_section.new_line()
        ini_builder.append_section(key_section)

        commandlist_section = M_IniSection(M_SectionType.CommandList)
        commandlist_section.append("[CommandListApplyShapeKeysPosition]")
        commandlist_section.append("ResourcePositionBufferRW = copy ResourcePositionBufferFloat")
        commandlist_section.append("x89 = " + str(draw_ib_model.mesh_vertex_count * 3))
        commandlist_section.append("cs-t50 = ResourcePositionBufferFloat")
        commandlist_section.append("cs-u5 = ResourcePositionBufferRW")
        for shapekey_name, safe_name, m_key in shapekey_entries:
            commandlist_section.append("; ShapeKey: " + shapekey_name)
            commandlist_section.append("x88 = " + m_key.key_name)
            commandlist_section.append("cs-t51 = ResourceShapeKeyPosition_" + safe_name)
            commandlist_section.append("run = CustomShaderComputeWWMIShapeKeyPosition")
        commandlist_section.append("cs-t50 = null")
        commandlist_section.append("cs-t51 = null")
        commandlist_section.append("cs-u5 = null")
        commandlist_section.append("ResourcePositionBufferShapeKeyVB = copy ResourcePositionBufferRW")
        commandlist_section.new_line()

        commandlist_section.append("[CustomShaderComputeWWMIShapeKeyPosition]")
        commandlist_section.append("cs = .\\res\\ShapesWWMIPosition.hlsl")
        commandlist_section.append("vs = null")
        commandlist_section.append("ps = null")
        commandlist_section.append("hs = null")
        commandlist_section.append("ds = null")
        commandlist_section.append("gs = null")
        commandlist_section.append("dispatch = " + str((draw_ib_model.mesh_vertex_count * 3 + 63) // 64) + ", 1, 1")
        commandlist_section.new_line()

        commandlist_section.append("[CommandListApplyShapeKeysVector]")
        commandlist_section.append("ResourceVectorBufferRW = copy ResourceVectorBufferInt")
        commandlist_section.append("x89 = " + str(draw_ib_model.mesh_vertex_count * 2))
        commandlist_section.append("cs-t50 = ResourceVectorBufferInt")
        commandlist_section.append("cs-u5 = ResourceVectorBufferRW")
        for shapekey_name, safe_name, m_key in shapekey_entries:
            commandlist_section.append("; ShapeKey: " + shapekey_name)
            commandlist_section.append("x88 = " + m_key.key_name)
            commandlist_section.append("cs-t51 = ResourceShapeKeyVector_" + safe_name)
            commandlist_section.append("run = CustomShaderComputeWWMIShapeKeyVector")
        commandlist_section.append("cs-t50 = null")
        commandlist_section.append("cs-t51 = null")
        commandlist_section.append("cs-u5 = null")
        commandlist_section.append("ResourceVectorBufferShapeKeyVB = copy ResourceVectorBufferRW")
        commandlist_section.new_line()

        commandlist_section.append("[CustomShaderComputeWWMIShapeKeyVector]")
        commandlist_section.append("cs = .\\res\\ShapesWWMIVector.hlsl")
        commandlist_section.append("vs = null")
        commandlist_section.append("ps = null")
        commandlist_section.append("hs = null")
        commandlist_section.append("ds = null")
        commandlist_section.append("gs = null")
        commandlist_section.append("dispatch = " + str((draw_ib_model.mesh_vertex_count * 2 + 63) // 64) + ", 1, 1")
        commandlist_section.new_line()
        ini_builder.append_section(commandlist_section)

        resource_section = M_IniSection(M_SectionType.ResourceBuffer)
        resource_section.append("[ResourcePositionBufferRW]")
        resource_section.append("type = RWBuffer")
        resource_section.append("format = R32_FLOAT")
        resource_section.append("array = " + str(draw_ib_model.mesh_vertex_count * 3))
        resource_section.new_line()
        resource_section.append("[ResourcePositionBufferFloat]")
        resource_section.append("type = Buffer")
        resource_section.append("format = R32_FLOAT")
        resource_section.append("filename = Meshes/" + draw_ib_model.draw_ib + "-Position.buf")
        resource_section.new_line()
        resource_section.append("[ResourcePositionBufferShapeKeyVB]")
        resource_section.append("type = Buffer")
        resource_section.append("stride = 12")
        resource_section.new_line()
        resource_section.append("[ResourceVectorBufferRW]")
        resource_section.append("type = RWBuffer")
        resource_section.append("format = R8_SINT")
        resource_section.append("array = " + str(draw_ib_model.mesh_vertex_count * 8))
        resource_section.new_line()
        resource_section.append("[ResourceVectorBufferInt]")
        resource_section.append("type = Buffer")
        resource_section.append("format = R8_SINT")
        resource_section.append("filename = Meshes/" + draw_ib_model.draw_ib + "-Vector.buf")
        resource_section.new_line()
        resource_section.append("[ResourceVectorBufferShapeKeyVB]")
        resource_section.append("type = Buffer")
        resource_section.append("stride = 8")
        resource_section.new_line()
        for shapekey_name, safe_name, _m_key in shapekey_entries:
            resource_section.append("[ResourceShapeKeyPosition_" + safe_name + "]")
            resource_section.append("type = Buffer")
            resource_section.append("format = R32_FLOAT")
            resource_section.append("filename = Meshes/" + draw_ib_model.draw_ib + "-Position." + safe_name + ".buf")
            resource_section.new_line()
            resource_section.append("[ResourceShapeKeyVector_" + safe_name + "]")
            resource_section.append("type = Buffer")
            resource_section.append("format = R8_SINT")
            resource_section.append("filename = Meshes/" + draw_ib_model.draw_ib + "-Vector." + safe_name + ".buf")
            resource_section.new_line()
        ini_builder.append_section(resource_section)

    def add_resource_merged_skeleton(self, ini_builder: M_IniBuilder, draw_ib_model: DrawIBModelWWMI):
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

    def add_resource_buffer(self, ini_builder: M_IniBuilder, draw_ib_model: DrawIBModelWWMI):
        resource_buffer_section = M_IniSection(M_SectionType.ResourceBuffer)
        buffer_folder_name = "Meshes"

        resource_buffer_section.append("[ResourceIndexBuffer]")
        resource_buffer_section.append("type = Buffer")
        resource_buffer_section.append("format = DXGI_FORMAT_R32_UINT")
        resource_buffer_section.append("stride = 12")
        resource_buffer_section.append("filename = " + buffer_folder_name + "/" + draw_ib_model.draw_ib + "-Component1.buf")
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
            resource_buffer_section.append("filename = " + buffer_folder_name + "/" + draw_ib_model.draw_ib + "-" + category_name + ".buf")
            resource_buffer_section.new_line()

            if category_name == D3D11Category.BLEND and draw_ib_model.blend_remap:
                resource_buffer_section.append("[ResourceBlendBufferNoStride]")
                resource_buffer_section.append("type = Buffer")
                resource_buffer_section.append("format = DXGI_FORMAT_R8_UINT")
                resource_buffer_section.append("filename = " + buffer_folder_name + "/" + draw_ib_model.draw_ib + "-" + category_name + ".buf")
                resource_buffer_section.new_line()

        if draw_ib_model.blend_remap:
            resource_buffer_section.append("[ResourceBlendRemapVertexVGBuffer]")
            resource_buffer_section.append("type = Buffer")
            resource_buffer_section.append("format = DXGI_FORMAT_R16_UINT")
            resource_buffer_section.append("filename = " + buffer_folder_name + "/" + draw_ib_model.draw_ib + "-BlendRemapVertexVG.buf")
            resource_buffer_section.new_line()

            resource_buffer_section.append("[ResourceBlendRemapForwardBuffer]")
            resource_buffer_section.append("type = Buffer")
            resource_buffer_section.append("format = DXGI_FORMAT_R16_UINT")
            resource_buffer_section.append("filename = " + buffer_folder_name + "/" + draw_ib_model.draw_ib + "-BlendRemapForward.buf")
            resource_buffer_section.new_line()

            resource_buffer_section.append("[ResourceBlendRemapReverseBuffer]")
            resource_buffer_section.append("type = Buffer")
            resource_buffer_section.append("format = DXGI_FORMAT_R16_UINT")
            resource_buffer_section.append("filename = " + buffer_folder_name + "/" + draw_ib_model.draw_ib + "-BlendRemapReverse.buf")
            resource_buffer_section.new_line()

        resource_buffer_section.append("[ResourceShapeKeyOffsetBuffer]")
        resource_buffer_section.append("type = Buffer")
        resource_buffer_section.append("format = DXGI_FORMAT_R32G32B32A32_UINT")
        resource_buffer_section.append("stride = 16")
        resource_buffer_section.append("filename = " + buffer_folder_name + "/" + draw_ib_model.draw_ib + "-ShapeKeyOffset.buf")
        resource_buffer_section.new_line()

        resource_buffer_section.append("[ResourceShapeKeyVertexIdBuffer]")
        resource_buffer_section.append("type = Buffer")
        resource_buffer_section.append("format = DXGI_FORMAT_R32_UINT")
        resource_buffer_section.append("stride = 4")
        resource_buffer_section.append("filename = " + buffer_folder_name + "/" + draw_ib_model.draw_ib + "-ShapeKeyVertexId.buf")
        resource_buffer_section.new_line()

        resource_buffer_section.append("[ResourceShapeKeyVertexOffsetBuffer]")
        resource_buffer_section.append("type = Buffer")
        resource_buffer_section.append("format = DXGI_FORMAT_R16_FLOAT")
        resource_buffer_section.append("stride = 2")
        resource_buffer_section.append("filename = " + buffer_folder_name + "/" + draw_ib_model.draw_ib + "-ShapeKeyVertexOffset.buf")
        resource_buffer_section.new_line()

        ini_builder.append_section(resource_buffer_section)

    def generate_unreal_vs_config_ini(self):
        config_ini_builder = M_IniBuilder()

        for draw_ib, draw_ib_model in self.drawib_drawibmodel_dict.items():
            self.add_constants_section(ini_builder=config_ini_builder, draw_ib_model=draw_ib_model)
            self.add_present_section(ini_builder=config_ini_builder, draw_ib_model=draw_ib_model)
            self.add_commandlist_register_mod_section(ini_builder=config_ini_builder, draw_ib_model=draw_ib_model)
            self.add_commandlist_update_merged_skeleton(ini_builder=config_ini_builder, draw_ib_model=draw_ib_model)
            self.add_blend_remap_sections(ini_builder=config_ini_builder, draw_ib_model=draw_ib_model)
            self.add_resource_mod_info_section_default(ini_builder=config_ini_builder, draw_ib_model=draw_ib_model)
            self.add_texture_override_mark_bone_data_cb(ini_builder=config_ini_builder, draw_ib_model=draw_ib_model)
            self.add_commandlist_merge_skeleton_section(ini_builder=config_ini_builder, draw_ib_model=draw_ib_model)
            self.add_commandlist_trigger_shared_cleanup_section(ini_builder=config_ini_builder, draw_ib_model=draw_ib_model)
            self.add_texture_override_component(ini_builder=config_ini_builder, draw_ib_model=draw_ib_model)
            self.add_texture_override_shapekeys(ini_builder=config_ini_builder, draw_ib_model=draw_ib_model)
            self.add_resource_shapekeys(ini_builder=config_ini_builder, draw_ib_model=draw_ib_model)
            self.add_wwmi_shapekey_sections(ini_builder=config_ini_builder, draw_ib_model=draw_ib_model)

            if GlobalProperties.import_merged_vgmap() == 'MERGED':
                self.add_resource_merged_skeleton(ini_builder=config_ini_builder, draw_ib_model=draw_ib_model)
            
            self.add_resource_buffer(ini_builder=config_ini_builder, draw_ib_model=draw_ib_model)

            print("=" * 60)
            print("[TRACE] generate_unreal_vs_config_ini: DrawIB=" + draw_ib + " - 寮€濮嬪鍒?Slot 璐村浘...")
            M_IniHelper.move_slot_style_textures(draw_ib_model=draw_ib_model)
            print("[TRACE] generate_unreal_vs_config_ini: DrawIB=" + draw_ib + " - Slot 璐村浘澶嶅埗瀹屾垚")

            GlobalConfig.generated_mod_number = GlobalConfig.generated_mod_number + 1
            M_IniHelper.add_branch_key_sections(ini_builder=config_ini_builder, key_name_mkey_dict=self.blueprint_model.keyname_mkey_dict)
            M_IniHelperGUI.add_branch_mod_gui_section(ini_builder=config_ini_builder, key_name_mkey_dict=self.blueprint_model.keyname_mkey_dict)

            print("[TRACE] generate_unreal_vs_config_ini: DrawIB=" + draw_ib + " - 寮€濮嬬敓鎴?Hash 璐村浘 INI...")
            M_IniHelper.generate_hash_style_texture_ini(ini_builder=config_ini_builder, drawib_drawibmodel_dict=self.drawib_drawibmodel_dict)
            M_IniHelper.generate_shared_slot_style_texture_ini(ini_builder=config_ini_builder, drawib_drawibmodel_dict=self.drawib_drawibmodel_dict)
            print("[TRACE] generate_unreal_vs_config_ini: DrawIB=" + draw_ib + " - Hash/SharedSlot 璐村浘 INI 鐢熸垚瀹屾垚")
            print("=" * 60)

            config_ini_builder.save_to_file_not_reorder(os.path.join(GlobalConfig.path_generate_mod_folder(), GlobalConfig.get_generated_mod_name() + "_" + draw_ib + ".ini"))
            config_ini_builder.clear()

    def export(self):
        for draw_ib_model in self.drawib_drawibmodel_dict.values():
            draw_ib_model.write_buffer_files()
        self.generate_unreal_vs_config_ini()
