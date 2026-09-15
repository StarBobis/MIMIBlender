"""
Naraka (Naraka: Bladepoint) mod exporter.

Naraka uses the GPU pre-skinning compute-shader path:
- The original Position VB is enlarged by a VertexLimitRaise override.
- A compute shader dispatch copies the modded Position/Blend data from
  resource buffers into the game's own VB at draw time.
- The Texcoord VB is replaced by a resource buffer directly.
- Every submesh IB draw is skipped and re-emitted manually, which is also
  the place where cross-IB rendering blocks are injected.

Only the cross-IB aware pieces live in this file; the rest of the compute
path comes from the shared section builders.
"""

from ...common.global_config import GlobalConfig
from ...common.mimi_global_properties import MIMIGlobalProperties
from ...common.m_ini_builder import M_IniBuilder, M_IniSection, M_SectionType
from ...common.m_ini_helper import M_IniHelper
from ..base.standard_exporter import StandardExporter
from ..base import sections


class Exporter(StandardExporter):
    """Naraka exporter: shared compute pipeline + cross-IB rendering."""

    def __init__(self, blueprint_model):
        super().__init__(blueprint_model)
        # Pre-scan every DrawIB and group cross-marked draw calls by their
        # host Submesh, so the IB section generation can inject the cross
        # blocks.  Fails fast (before any buffer is written) when a pair
        # references an unknown host.
        self.cross_ib_host_entries = self.collect_cross_ib_host_entries()

    @staticmethod
    def get_cross_ib_backup_resource_name(drawib_model, submesh_model, vb_slot: int) -> str:
        # The name carries the Submesh identity and the VB slot directly, so
        # any number of backups never collide (no auto-increment numbers),
        # e.g. Resource_LOD0_fd1dede6_0_BK_VB0
        return "Resource_" + drawib_model.get_submesh_unique_key(submesh_model) + "_BK_VB" + str(vb_slot)

    @staticmethod
    def submesh_has_cross_ib_draw_call(submesh_model) -> bool:
        # A Submesh is a cross-IB guest when at least one of its draw calls
        # is marked to be rendered inside another Submesh's section.
        for draw_call_model in submesh_model.drawcall_model_list:
            if draw_call_model.cross_render_at_submesh:
                return True
        return False

    def collect_cross_ib_host_entries(self):
        # Pre-scan every DrawIB and group cross-marked draw calls by their host
        # Submesh, so the IB section generation can inject the cross blocks.
        # Returns: host submesh_name -> list of guest entries.
        submesh_lookup = {}
        for drawib_model in self.drawib_model_list:
            for submesh_model in drawib_model.submesh_model_list:
                submesh_lookup[submesh_model.submesh_name] = submesh_model

        cross_ib_host_entries = {}
        for drawib_model in self.drawib_model_list:
            for submesh_model in drawib_model.submesh_model_list:
                # Group this Submesh's cross-marked draw calls by host,
                # keeping the blueprint parse order inside each group.
                crossed_per_host = {}
                for draw_call_model in submesh_model.drawcall_model_list:
                    host_submesh_name = draw_call_model.cross_render_at_submesh
                    if host_submesh_name:
                        draw_call_list = crossed_per_host.get(host_submesh_name, [])
                        draw_call_list.append(draw_call_model)
                        crossed_per_host[host_submesh_name] = draw_call_list

                for host_submesh_name, draw_call_list in crossed_per_host.items():
                    if host_submesh_name not in submesh_lookup:
                        raise ValueError("Naraka Cross-IB Render: host Submesh '" + host_submesh_name + "' does not exist in this export")
                    entry = {
                        "guest_drawib_model": drawib_model,
                        "guest_submesh_model": submesh_model,
                        "draw_call_list": draw_call_list,
                    }
                    entry_list = cross_ib_host_entries.get(host_submesh_name, [])
                    entry_list.append(entry)
                    cross_ib_host_entries[host_submesh_name] = entry_list

        return cross_ib_host_entries

    def add_drawib_sections(self, ini_builder: M_IniBuilder, drawib_model):
        # Naraka always uses the compute-shader (GPU pre-skinning) path.
        sections.add_unity_vs_texture_override_vlr_section(ini_builder=ini_builder, drawib_model=drawib_model)
        sections.add_unity_cs_texture_override_vb_sections(ini_builder=ini_builder, drawib_model=drawib_model, blueprint_model=self.blueprint_model)
        self.add_naraka_cs_texture_override_ib_sections(ini_builder=ini_builder, drawib_model=drawib_model)
        sections.add_unity_cs_resource_vertexlimit(ini_builder=ini_builder, drawib_model=drawib_model)
        self.add_naraka_cs_resource_vb_sections(ini_builder=ini_builder, drawib_model=drawib_model)
        sections.add_resource_texture_sections(ini_builder=ini_builder, drawib_model=drawib_model)

    def add_naraka_cs_texture_override_ib_sections(self, ini_builder: M_IniBuilder, drawib_model):
        # IB overrides: skip every original draw and re-emit it manually with
        # the modded index buffer. Cross-IB rendering is applied here:
        # - guest draw calls are suppressed from their own Submesh section,
        # - guest Submesh sections capture their DrawIB's VB bindings (backup),
        # - host Submesh sections re-emit the guest draws after their own.
        texture_override_ib_section = M_IniSection(M_SectionType.TextureOverrideIB)
        draw_ib = drawib_model.draw_ib
        d3d11_game_type = drawib_model.d3d11_game_type

        for submesh_model in drawib_model.submesh_model_list:
            ib_resource_name = drawib_model.get_submesh_ib_resource_name(submesh_model)
            texture_override_ib_namesuffix = drawib_model.get_submesh_texture_override_suffix(submesh_model)

            texture_override_ib_section.append("[TextureOverride_" + texture_override_ib_namesuffix + "]")
            texture_override_ib_section.append("hash = " + draw_ib)
            texture_override_ib_section.append("match_first_index = " + str(submesh_model.match_first_index))
            texture_override_ib_section.append("checktextureoverride = vb1")

            # Hash-marked textures join the override check so the mod only
            # applies when the original textures are bound.
            if not MIMIGlobalProperties.forbid_auto_texture_ini():
                for texture_markup_info in drawib_model.get_submesh_texture_markup_info_list(submesh_model):
                    if texture_markup_info.mark_type == "Hash":
                        texture_override_ib_section.append("checktextureoverride = " + texture_markup_info.mark_slot)

            texture_override_ib_section.append("handling = skip")

            # An empty index buffer means the submesh is hidden: leave it skipped.
            ib_buf = drawib_model.submesh_ib_dict.get(submesh_model.submesh_name, None)
            if ib_buf is None or len(ib_buf) == 0:
                texture_override_ib_section.new_line()
                continue

            if not d3d11_game_type.GPU_PreSkinning:
                for original_category_name, draw_category_name in d3d11_game_type.CategoryDrawCategoryDict.items():
                    if original_category_name == draw_category_name:
                        category_original_slot = d3d11_game_type.CategoryExtractSlotDict[original_category_name]
                        texture_override_ib_section.append(category_original_slot + " = Resource" + draw_ib + original_category_name)

            texture_override_ib_section.append("ib = " + ib_resource_name)

            # Automatic Slot / SharedSlot texture bindings from the Submesh marks.
            if not MIMIGlobalProperties.forbid_auto_texture_ini():
                for texture_markup_info in drawib_model.get_submesh_texture_markup_info_list(submesh_model):
                    if texture_markup_info.mark_type in ("Slot", "SharedSlot"):
                        texture_override_ib_section.append(texture_markup_info.mark_slot + " = " + texture_markup_info.get_resource_name())

            # Only draw calls without a cross-IB mark stay in this section;
            # marked ones move into their host Submesh section instead.
            normal_draw_call_list = []
            for draw_call_model in submesh_model.drawcall_model_list:
                if not draw_call_model.cross_render_at_submesh:
                    normal_draw_call_list.append(draw_call_model)

            for drawindexed_str in M_IniHelper.get_drawindexed_str_list(
                normal_draw_call_list,
                obj_name_draw_offset_dict=drawib_model.obj_name_draw_offset,
            ):
                texture_override_ib_section.append(drawindexed_str)

            # Guest backup: capture this DrawIB's VB bindings while they are
            # live (vb0 already holds the CS-written modded data and vb1 is
            # the modded Texcoord buffer), so host sections can rebind them.
            if self.submesh_has_cross_ib_draw_call(submesh_model):
                texture_override_ib_section.append(self.get_cross_ib_backup_resource_name(drawib_model, submesh_model, 0) + " = ref vb0")
                texture_override_ib_section.append(self.get_cross_ib_backup_resource_name(drawib_model, submesh_model, 1) + " = ref vb1")

            # Host cross blocks: always appended after the host's own draws,
            # so the host bindings never need to be restored afterwards.
            for cross_entry in self.cross_ib_host_entries.get(submesh_model.submesh_name, []):
                guest_drawib_model = cross_entry["guest_drawib_model"]
                guest_submesh_model = cross_entry["guest_submesh_model"]
                texture_override_ib_section.append("; Cross-IB: " + guest_submesh_model.display_str + " rendered at " + submesh_model.display_str)
                texture_override_ib_section.append("ib = " + guest_drawib_model.get_submesh_ib_resource_name(guest_submesh_model))
                texture_override_ib_section.append("vb0 = " + self.get_cross_ib_backup_resource_name(guest_drawib_model, guest_submesh_model, 0))
                texture_override_ib_section.append("vb1 = " + self.get_cross_ib_backup_resource_name(guest_drawib_model, guest_submesh_model, 1))
                for drawindexed_str in M_IniHelper.get_drawindexed_str_list(
                    cross_entry["draw_call_list"],
                    obj_name_draw_offset_dict=guest_drawib_model.obj_name_draw_offset,
                ):
                    texture_override_ib_section.append(drawindexed_str)

            if not d3d11_game_type.GPU_PreSkinning:
                if len(self.blueprint_model.keyname_mkey_dict.keys()) != 0:
                    texture_override_ib_section.append("$active" + str(GlobalConfig.generated_mod_number) + " = 1")

        ini_builder.append_section(texture_override_ib_section)

    def add_naraka_cs_resource_vb_sections(self, ini_builder: M_IniBuilder, drawib_model):
        # Resource declarations: the shared compute-path declarations plus a
        # unified declaration area for the cross-IB backup resources (one
        # empty section per guest Submesh and VB slot, filled by "ref" at
        # runtime).
        resource_vb_section = sections.build_unity_cs_resource_vb_section(drawib_model)

        for submesh_model in drawib_model.submesh_model_list:
            if not self.submesh_has_cross_ib_draw_call(submesh_model):
                continue
            resource_vb_section.append("[" + self.get_cross_ib_backup_resource_name(drawib_model, submesh_model, 0) + "]")
            resource_vb_section.new_line()
            resource_vb_section.append("[" + self.get_cross_ib_backup_resource_name(drawib_model, submesh_model, 1) + "]")
            resource_vb_section.new_line()

        ini_builder.append_section(resource_vb_section)
