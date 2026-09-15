"""
Identity V (Neox3 engine) mod exporter.

Identity V is the only preset that also emits skip-sections for Submeshes
that exist in the workspace folder but have no blueprint objects (the
"missing" entries), so its IB overrides stay fully game-specific.  The VB
override carries the vertex-limit fields inline, which is also unique to
this preset.  Everything else comes from the shared base.
"""

import os

from ..common.global_config import GlobalConfig
from ..common.mimi_global_properties import MIMIGlobalProperties
from ..common.m_ini_builder import M_IniBuilder, M_IniSection, M_SectionType
from ..common.m_ini_helper import M_IniHelper
from .base.standard_exporter import StandardExporter
from .base import sections


class ExportIdentityV(StandardExporter):
    """Identity V exporter: shared pipeline, custom VB/IB override sections."""

    def add_drawib_sections(self, ini_builder: M_IniBuilder, drawib_model):
        self.add_unity_vs_texture_override_vb_sections(ini_builder=ini_builder, drawib_model=drawib_model)
        self.add_unity_vs_texture_override_ib_sections(ini_builder=ini_builder, drawib_model=drawib_model)
        sections.add_unity_vs_resource_vb_sections(ini_builder=ini_builder, drawib_model=drawib_model, use_display_str=False)
        sections.add_resource_texture_sections(ini_builder=ini_builder, drawib_model=drawib_model)

    def _get_drawib_submesh_entries(self, drawib_model):
        # Collect every Submesh of this DrawIB: blueprint-driven ones first,
        # then the "missing" ones that only exist as workspace folders.
        existing_submesh_dict = {}
        for submesh_model in drawib_model.submesh_model_list:
            existing_submesh_dict[int(submesh_model.match_first_index)] = {
                "match_first_index": int(submesh_model.match_first_index),
                "submesh_name": submesh_model.submesh_name,
                "submesh_model": submesh_model,
                "is_missing": False,
            }

        workspace_folder = GlobalConfig.path_workspace_folder()
        if not os.path.exists(workspace_folder):
            return list(existing_submesh_dict.values())

        for entry_name in os.listdir(workspace_folder):
            entry_path = os.path.join(workspace_folder, entry_name)
            if not os.path.isdir(entry_path):
                continue
            if not entry_name.startswith(drawib_model.draw_ib + "-"):
                continue

            name_splits = entry_name.split("-")
            if len(name_splits) < 3:
                continue

            try:
                match_first_index = int(name_splits[2])
            except ValueError:
                continue

            if match_first_index in existing_submesh_dict:
                continue

            existing_submesh_dict[match_first_index] = {
                "match_first_index": match_first_index,
                "submesh_name": entry_name,
                "submesh_model": None,
                "is_missing": True,
            }

        return [
            existing_submesh_dict[match_first_index]
            for match_first_index in sorted(existing_submesh_dict.keys())
        ]

    def _append_missing_texture_override_ib_section(self, texture_override_ib_section, draw_ib, submesh_entry):
        # A missing Submesh still gets a bare skip section so the original
        # draw never shows up unmodded.
        texture_override_name_suffix = submesh_entry["submesh_name"].replace("-", "_")
        texture_override_ib_section.append("[TextureOverride_" + texture_override_name_suffix + "]")
        texture_override_ib_section.append("hash = " + draw_ib)
        texture_override_ib_section.append("match_first_index = " + str(submesh_entry["match_first_index"]))
        texture_override_ib_section.append("handling = skip")
        texture_override_ib_section.new_line()

    def add_unity_vs_texture_override_vb_sections(self, ini_builder: M_IniBuilder, drawib_model):
        # VB overrides with the vertex-limit fields inline (GPU pre-skinning
        # only; on CPU pre-skinning nothing is emitted here).
        d3d11_game_type = drawib_model.d3d11_game_type
        if not d3d11_game_type.GPU_PreSkinning:
            return

        texture_override_vb_section = M_IniSection(M_SectionType.TextureOverrideVB)
        texture_override_vb_section.append("; " + drawib_model.draw_ib)
        for category_name in d3d11_game_type.OrderedCategoryNameList:
            category_hash = drawib_model.category_hash_dict.get(category_name, "")
            texture_override_vb_name_suffix = "VB_" + drawib_model.draw_ib + "_" + drawib_model.draw_ib_alias + "_" + category_name
            texture_override_vb_section.append("[TextureOverride_" + texture_override_vb_name_suffix + "]")
            texture_override_vb_section.append("hash = " + category_hash)

            if category_name == d3d11_game_type.CategoryDrawCategoryDict["Position"]:
                texture_override_vb_section.append("override_byte_stride = " + str(d3d11_game_type.CategoryStrideDict["Position"]))
                texture_override_vb_section.append("override_vertex_count = " + str(drawib_model.draw_number))
                texture_override_vb_section.append("uav_byte_stride = 4")

            for original_category_name, draw_category_name in d3d11_game_type.CategoryDrawCategoryDict.items():
                if category_name != draw_category_name:
                    continue
                category_original_slot = d3d11_game_type.CategoryExtractSlotDict[original_category_name]
                texture_override_vb_section.append(category_original_slot + " = Resource" + drawib_model.draw_ib + original_category_name)

            if category_name == d3d11_game_type.CategoryDrawCategoryDict["Position"]:
                if len(self.blueprint_model.keyname_mkey_dict.values()) != 0:
                    texture_override_vb_section.append("$active" + str(GlobalConfig.generated_mod_number) + " = 1")

            texture_override_vb_section.new_line()

        ini_builder.append_section(texture_override_vb_section)

    def add_unity_vs_texture_override_ib_sections(self, ini_builder: M_IniBuilder, drawib_model):
        # IB overrides: back up the live IB, bind the modded one, draw, then
        # restore the backup so later draws see the original buffer again.
        texture_override_ib_section = M_IniSection(M_SectionType.TextureOverrideIB)
        draw_ib = drawib_model.draw_ib
        d3d11_game_type = drawib_model.d3d11_game_type

        for submesh_entry in self._get_drawib_submesh_entries(drawib_model):
            if submesh_entry["is_missing"]:
                self._append_missing_texture_override_ib_section(
                    texture_override_ib_section=texture_override_ib_section,
                    draw_ib=draw_ib,
                    submesh_entry=submesh_entry,
                )
                continue

            submesh_model = submesh_entry["submesh_model"]
            texture_override_name_suffix = drawib_model.get_submesh_texture_override_suffix(submesh_model)
            ib_resource_name = drawib_model.get_submesh_ib_resource_name(submesh_model)
            backup_resource_name = "Resource_IB_" + drawib_model.get_submesh_texture_override_suffix(submesh_model) + "_Bak"

            texture_override_ib_section.append("[" + backup_resource_name + "]")
            texture_override_ib_section.append("[TextureOverride_" + texture_override_name_suffix + "]")
            texture_override_ib_section.append("hash = " + draw_ib)
            texture_override_ib_section.append("match_first_index = " + str(submesh_model.match_first_index))
            texture_override_ib_section.append("handling = skip")
            texture_override_ib_section.append(backup_resource_name + " = ref ib")
            texture_override_ib_section.append("checktextureoverride = vb0")

            # Hash-marked textures join the override check so the mod only
            # applies when the original textures are bound.
            if not MIMIGlobalProperties.forbid_auto_texture_ini():
                texture_markup_info_list = drawib_model.get_submesh_texture_markup_info_list(submesh_model)
                if texture_markup_info_list:
                    for texture_markup_info in texture_markup_info_list:
                        if texture_markup_info.mark_type == "Hash":
                            texture_override_ib_section.append("checktextureoverride = " + texture_markup_info.mark_slot)

            texture_override_ib_section.append("ib = " + ib_resource_name)

            # Automatic Slot / SharedSlot texture bindings from the Submesh marks.
            if not MIMIGlobalProperties.forbid_auto_texture_ini():
                texture_markup_info_list = drawib_model.get_submesh_texture_markup_info_list(submesh_model)
                if texture_markup_info_list:
                    for texture_markup_info in texture_markup_info_list:
                        if texture_markup_info.mark_type in ("Slot", "SharedSlot"):
                            texture_override_ib_section.append(texture_markup_info.mark_slot + " = " + texture_markup_info.get_resource_name())

            if not d3d11_game_type.GPU_PreSkinning:
                for original_category_name, draw_category_name in d3d11_game_type.CategoryDrawCategoryDict.items():
                    if original_category_name == draw_category_name:
                        category_original_slot = d3d11_game_type.CategoryExtractSlotDict[original_category_name]
                        texture_override_ib_section.append(category_original_slot + " = Resource" + draw_ib + original_category_name)

            for drawindexed_str in M_IniHelper.get_drawindexed_str_list(
                submesh_model.drawcall_model_list,
                obj_name_draw_offset_dict=drawib_model.obj_name_draw_offset,
            ):
                texture_override_ib_section.append(drawindexed_str)

            if not d3d11_game_type.GPU_PreSkinning:
                if len(self.blueprint_model.keyname_mkey_dict.values()) != 0:
                    texture_override_ib_section.append("$active" + str(GlobalConfig.generated_mod_number) + " = 1")

            texture_override_ib_section.append("ib = " + backup_resource_name)
            texture_override_ib_section.new_line()

        ini_builder.append_section(texture_override_ib_section)
