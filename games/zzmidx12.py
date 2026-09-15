"""
ZZMIDX12 (Zenless Zone Zero, DirectX 12) mod exporter.

DX12-specific pieces kept here:
- the VB overrides match the compute-shader pre-skinning step by hash and
  drive it with an explicit dispatch,
- the IB overrides support the ZZZ slot-fix resources and the skin
  texture command list (same idea as ZZMI, different matching).

Everything else (pipeline, resource sections, texture sections) comes from
the shared base.
"""

import math

from ..common.global_config import GlobalConfig
from ..common.mimi_global_properties import MIMIGlobalProperties
from ..common.m_ini_builder import M_IniBuilder, M_IniSection, M_SectionType
from ..common.m_ini_helper import M_IniHelper
from .base.standard_exporter import StandardExporter
from .base import sections


class ZZMIDX12TextureMarkName:
    DiffuseMap = "DiffuseMap"
    NormalMap = "NormalMap"
    LightMap = "LightMap"
    MaterialMap = "MaterialMap"
    StockingMap = "StockingMap"


class ExportZZMIDX12(StandardExporter):
    """ZZMIDX12 exporter: shared pipeline, DX12-specific VB/IB overrides."""

    SLOT_FIX_RESOURCE_NAME_DICT = {
        ZZMIDX12TextureMarkName.DiffuseMap: r"Resource\ZZMI\Diffuse",
        ZZMIDX12TextureMarkName.NormalMap: r"Resource\ZZMI\NormalMap",
        ZZMIDX12TextureMarkName.LightMap: r"Resource\ZZMI\LightMap",
        ZZMIDX12TextureMarkName.MaterialMap: r"Resource\ZZMI\MaterialMap",
        ZZMIDX12TextureMarkName.StockingMap: r"Resource\ZZMI\WengineFx",
    }

    def add_drawib_sections(self, ini_builder: M_IniBuilder, drawib_model):
        self.add_unity_vs_texture_override_vb_sections(ini_builder=ini_builder, drawib_model=drawib_model)
        self.add_unity_vs_texture_override_ib_sections(ini_builder=ini_builder, drawib_model=drawib_model)
        sections.add_unity_vs_resource_vb_sections(ini_builder=ini_builder, drawib_model=drawib_model)
        sections.add_resource_texture_sections(ini_builder=ini_builder, drawib_model=drawib_model)

    def add_unity_vs_texture_override_vb_sections(self, ini_builder: M_IniBuilder, drawib_model):
        d3d11_game_type = drawib_model.d3d11_game_type
        draw_ib = drawib_model.draw_ib

        texture_override_vb_section = M_IniSection(M_SectionType.TextureOverrideVB)
        texture_override_vb_section.append("; " + draw_ib)

        match_cs = self.get_blend_match_cs(drawib_model)
        draw_number = drawib_model.draw_number
        vb_idx = 1

        # DX12: PreSkinning section (Position as compute shader dispatch hub)
        position_hash = drawib_model.category_hash_dict.get("Position", "")
        blend_hash = drawib_model.category_hash_dict.get("Blend", "")
        has_blend = "Blend" in d3d11_game_type.OrderedCategoryNameList

        texture_override_vb_section.append("[TextureOverride_VB_" + draw_ib + "_PreSkinning]")
        if match_cs:
            texture_override_vb_section.append("cs_hash = " + match_cs)
        texture_override_vb_section.append("match_cs_t0_hash = " + position_hash)
        if has_blend:
            texture_override_vb_section.append("match_cs_t1_hash = " + blend_hash)
        texture_override_vb_section.append("cs-t0 = Resource" + draw_ib + "Position")
        if has_blend:
            texture_override_vb_section.append("cs-t1 = Resource" + draw_ib + "Blend")
        texture_override_vb_section.append("handling = skip")
        texture_override_vb_section.append("dispatch = " + str(math.ceil(draw_number / 64)) + ",1,1")

        if len(self.blueprint_model.keyname_mkey_dict.keys()) != 0:
            texture_override_vb_section.append("$active" + str(GlobalConfig.generated_mod_number) + " = 1")

        texture_override_vb_section.new_line()

        # DX12: non-Position, non-Blend categories use vb<N> bindings
        for category_name in d3d11_game_type.OrderedCategoryNameList:
            if category_name in ("Position", "Blend"):
                continue

            category_hash = drawib_model.category_hash_dict.get(category_name, "")
            texture_override_vb_name_suffix = "VB_" + draw_ib + "_" + drawib_model.draw_ib_alias + "_" + category_name
            texture_override_vb_section.append("[TextureOverride_" + texture_override_vb_name_suffix + "]")
            texture_override_vb_section.append("hash = " + category_hash)

            for original_category_name, draw_category_name in d3d11_game_type.CategoryDrawCategoryDict.items():
                if category_name != draw_category_name:
                    continue
                texture_override_vb_section.append("vb" + str(vb_idx) + " = Resource" + draw_ib + original_category_name)
            vb_idx += 1

            texture_override_vb_section.new_line()

        ini_builder.append_section(texture_override_vb_section)

    def get_blend_match_cs(self, drawib_model) -> str:
        # The compute shader hash of the pre-skinning step, read from the
        # first Submesh that carries it.
        for submesh_model in drawib_model.submesh_model_list:
            match_cs = str(getattr(submesh_model, "match_cs", "") or "").strip()
            if match_cs:
                return match_cs
        return ""

    def get_blend_match_uav_bytes(self, drawib_model) -> int:
        # The UAV byte size of the pre-skinning step, read from the first
        # Submesh that carries a positive value.
        for submesh_model in drawib_model.submesh_model_list:
            try:
                match_uav_bytes = int(getattr(submesh_model, "match_uav_bytes", 0) or 0)
            except (TypeError, ValueError):
                match_uav_bytes = 0
            if match_uav_bytes > 0:
                return match_uav_bytes
        return 0

    def add_unity_vs_texture_override_ib_sections(self, ini_builder: M_IniBuilder, drawib_model):
        # IB overrides with the optional ZZZ slot fix (same idea as ZZMI):
        # marked textures can be redirected through the fixed Resource\ZZMI\*
        # slots when the user enabled the slot-fix option.
        texture_override_ib_section = M_IniSection(M_SectionType.TextureOverrideIB)
        draw_ib = drawib_model.draw_ib

        texture_override_ib_section.append("[TextureOverride_IB_" + draw_ib + "]")
        texture_override_ib_section.append("hash = " + draw_ib)
        texture_override_ib_section.append("handling = skip")
        texture_override_ib_section.new_line()

        for submesh_model in drawib_model.submesh_model_list:
            texture_override_name_suffix = drawib_model.get_submesh_texture_override_suffix(submesh_model)
            ib_resource_name = drawib_model.get_submesh_ib_resource_name(submesh_model)

            texture_override_ib_section.append("[TextureOverride_" + texture_override_name_suffix + "]")
            texture_override_ib_section.append("hash = " + draw_ib)
            texture_override_ib_section.append("match_first_index = " + str(submesh_model.match_first_index))

            ib_buf = drawib_model.submesh_ib_dict.get(submesh_model.submesh_name, None)
            if ib_buf is None or len(ib_buf) == 0:
                texture_override_ib_section.append("ib = null")
                texture_override_ib_section.new_line()
                continue

            texture_override_ib_section.append("ib = " + ib_resource_name)

            texture_markup_info_list = drawib_model.get_submesh_texture_markup_info_list(submesh_model)
            if not MIMIGlobalProperties.forbid_auto_texture_ini() and texture_markup_info_list:
                slot_fix_enabled = MIMIGlobalProperties.zzz_use_slot_fix()
                uses_slot_fix = False

                for texture_markup_info in texture_markup_info_list:
                    if texture_markup_info.mark_type not in ("Slot", "SharedSlot"):
                        continue

                    slot_fix_resource_name = self.SLOT_FIX_RESOURCE_NAME_DICT.get(texture_markup_info.mark_name)
                    if slot_fix_enabled and slot_fix_resource_name is not None:
                        texture_override_ib_section.append(
                            slot_fix_resource_name + " = ref " + texture_markup_info.get_resource_name()
                        )
                        uses_slot_fix = True
                    else:
                        texture_override_ib_section.append(
                            texture_markup_info.mark_slot + " = " + texture_markup_info.get_resource_name()
                        )

                if uses_slot_fix:
                    texture_override_ib_section.append(r"run = CommandList\ZZMI\SetTextures")

            if texture_markup_info_list:
                texture_override_ib_section.append("run = CommandListSkinTexture")

            for drawindexed_str in M_IniHelper.get_drawindexed_str_list(
                submesh_model.drawcall_model_list,
                obj_name_draw_offset_dict=drawib_model.obj_name_draw_offset,
            ):
                texture_override_ib_section.append(drawindexed_str)

        ini_builder.append_section(texture_override_ib_section)
