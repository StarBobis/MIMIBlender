"""
ZZMI (Zenless Zone Zero) mod exporter.

ZZMI-specific pieces kept here:
- the VB overrides use the DRAW_TYPE branching of the ZZZ shader,
- the IB overrides support the ZZZ slot-fix resources and the skin
  texture command list.

Everything else (pipeline, resource sections, texture sections) comes from
the shared base.  The unused compute-shader variants that were copy-pasted
from unity.py were dropped; the canonical versions live in
games/base/sections.py should they ever be needed.
"""

from ..common.global_config import GlobalConfig
from ..common.mimi_global_properties import MIMIGlobalProperties
from ..common.m_ini_builder import M_IniBuilder, M_IniSection, M_SectionType
from ..common.m_ini_helper import M_IniHelper
from .base.standard_exporter import StandardExporter
from .base import sections


class ZZMITextureMarkName:
    DiffuseMap = "DiffuseMap"
    NormalMap = "NormalMap"
    LightMap = "LightMap"
    MaterialMap = "MaterialMap"
    StockingMap = "StockingMap"


class ExportZZMI(StandardExporter):
    """ZZMI exporter: shared pipeline, ZZZ-specific VB/IB overrides."""

    SLOT_FIX_RESOURCE_NAME_DICT = {
        ZZMITextureMarkName.DiffuseMap: r"Resource\ZZMI\Diffuse",
        ZZMITextureMarkName.NormalMap: r"Resource\ZZMI\NormalMap",
        ZZMITextureMarkName.LightMap: r"Resource\ZZMI\LightMap",
        ZZMITextureMarkName.MaterialMap: r"Resource\ZZMI\MaterialMap",
        ZZMITextureMarkName.StockingMap: r"Resource\ZZMI\WengineFx",
    }

    def add_drawib_sections(self, ini_builder: M_IniBuilder, drawib_model):
        # ZZMI doesn't need uav_byte_stride = 4 in its VertexLimitRaise
        # section, so the shared builder is called with it disabled.
        sections.add_unity_vs_texture_override_vlr_section(ini_builder=ini_builder, drawib_model=drawib_model, include_uav_byte_stride=False)
        self.add_unity_vs_texture_override_vb_sections(ini_builder=ini_builder, drawib_model=drawib_model)
        self.add_unity_vs_texture_override_ib_sections(ini_builder=ini_builder, drawib_model=drawib_model)
        sections.add_unity_vs_resource_vb_sections(ini_builder=ini_builder, drawib_model=drawib_model)
        sections.add_resource_texture_sections(ini_builder=ini_builder, drawib_model=drawib_model)

    def add_unity_vs_texture_override_vb_sections(self, ini_builder: M_IniBuilder, drawib_model):
        # VB overrides with the ZZZ DRAW_TYPE branching: the Blend category
        # carries the skinned draw (DRAW_TYPE 1) while Texcoord/Blend binds
        # are used by the DRAW_TYPE 2/4 paths.
        d3d11_game_type = drawib_model.d3d11_game_type
        draw_ib = drawib_model.draw_ib

        texture_override_vb_section = M_IniSection(M_SectionType.TextureOverrideVB)
        texture_override_vb_section.append("; " + draw_ib)
        for category_name in d3d11_game_type.OrderedCategoryNameList:
            category_hash = drawib_model.category_hash_dict.get(category_name, "")
            category_slot = d3d11_game_type.CategoryExtractSlotDict[category_name]

            # now almost all ZZMI game type's Position category use Blend as it's draw category
            # so we need to update MMT's game type to let Blend become draw category so here can be matched.
            # or we have a more simple solution, we just use Blend as draw category
            # and ignore the gametype's defenition, because most of the time the draw category will not change

            # In ZZZ the category will not change every day,so we can just make it easy
            # Just simply write every common category name's situation.
            if category_name == "Blend":
                texture_override_vb_name_suffix = "VB_" + draw_ib + "_" + drawib_model.draw_ib_alias + "_PreSkinning"
                texture_override_vb_section.append("[TextureOverride_" + texture_override_vb_name_suffix + "]")
                texture_override_vb_section.append("hash = " + category_hash)
                texture_override_vb_section.append("handling = skip")

                # Activate the key variable unconditionally; otherwise it may not take effect in some cases
                if len(self.blueprint_model.keyname_mkey_dict.keys()) != 0:
                    texture_override_vb_section.append("$active" + str(GlobalConfig.generated_mod_number) + " = 1")
                    # A visible range marks the whole mod as on screen for the hotkeys.
                    texture_override_vb_section.append("$mod_visible = 1")
                texture_override_vb_section.append("if DRAW_TYPE == 2 || DRAW_TYPE == 4")

                texcoord_category_slot = d3d11_game_type.CategoryExtractSlotDict["Texcoord"]
                # vb1 = ResourceXXXTexcoord
                texture_override_vb_section.append("  " + texcoord_category_slot + " = Resource" + draw_ib + "Texcoord")
                # vb2 = ResourceXXXBlend
                texture_override_vb_section.append("  " + category_slot + " = Resource" + draw_ib + category_name)
                texture_override_vb_section.append("  " + "checktextureoverride = ib")

                texture_override_vb_section.append("elif DRAW_TYPE == 1")
                position_category_slot = d3d11_game_type.CategoryExtractSlotDict["Position"]
                texture_override_vb_section.append("  " + position_category_slot + " = Resource" + draw_ib + "Position")
                texture_override_vb_section.append("  " + category_slot + " = Resource" + draw_ib + category_name)
                texture_override_vb_section.append("  " + "draw = " + str(drawib_model.draw_number) + ", 0")

                texture_override_vb_section.append("endif")
                texture_override_vb_section.new_line()

            elif category_name == "Position":
                # Nothing need to do with Position category new latest version of ZZZ
                pass
            elif category_name == "Texcoord":
                texture_override_vb_name_suffix = "VB_" + draw_ib + "_" + drawib_model.draw_ib_alias + "_" + category_name
                texture_override_vb_section.append("[TextureOverride_" + texture_override_vb_name_suffix + "]")
                texture_override_vb_section.append("hash = " + category_hash)
                texture_override_vb_section.append(category_slot + " = Resource" + draw_ib + category_name)
                texture_override_vb_section.new_line()

        ini_builder.append_section(texture_override_vb_section)

    def add_unity_vs_texture_override_ib_sections(self, ini_builder: M_IniBuilder, drawib_model):
        # IB overrides with the optional ZZZ slot fix: marked textures can be
        # redirected through the fixed Resource\ZZMI\* slots when the user
        # enabled the slot-fix option.
        texture_override_ib_section = M_IniSection(M_SectionType.TextureOverrideIB)
        draw_ib = drawib_model.draw_ib

        # first handling = skip for entire ib and then replace every part?
        # no no no, in latest version it will crash the game.
        # idk why but it will crash.
        # texture_override_ib_section.append("[TextureOverride_IB_" + draw_ib + "]")
        # texture_override_ib_section.append("hash = " + draw_ib)
        # texture_override_ib_section.append("handling = skip")
        # texture_override_ib_section.new_line()

        for submesh_model in drawib_model.submesh_model_list:
            texture_override_name_suffix = drawib_model.get_submesh_texture_override_suffix(submesh_model)
            ib_resource_name = drawib_model.get_submesh_ib_resource_name(submesh_model)

            texture_override_ib_section.append("[TextureOverride_" + texture_override_name_suffix + "]")
            texture_override_ib_section.append("hash = " + draw_ib)

            # exactly match by first_index and index_count
            # skip it and then draw it back with our command
            texture_override_ib_section.append("match_first_index = " + str(submesh_model.match_first_index))
            texture_override_ib_section.append("match_index_count = " + str(submesh_model.match_index_count))
            texture_override_ib_section.append("handling = skip")

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
