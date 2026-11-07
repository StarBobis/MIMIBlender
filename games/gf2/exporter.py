"""
GF2 (Girls' Frontline 2) mod exporter.

This file is a COPY of the GIMI exporter, deliberately not a subclass of it:
GF2 ships the Genshin mod layout (texture-slot API, IB override sections)
only as a starting point and is expected to grow its own logic, so the two
implementations must be free to diverge. A fix that applies to both is meant
to be applied twice; never import or inherit GIMI's exporter from here.

Kept identical to the GIMI exporter for now:
- the IB overrides submit name-driven logical textures to the texture API,
  with physical fallbacks for names the package does not recognize,
- the VertexLimitRaise section never carries uav_byte_stride.

GF2-specific: cross-IB rendering.  The vertex buffers are replaced slot by
slot (vb0/vb1/vb2) from the mod's own resource buffers, and the verified
captures show the indexed draws reuse the same buffers as the point-list
pass, so a guest Submesh can back up its live bindings with "ref vbN" and be
re-drawn inside the host Submesh's section.  Unlike the compute-shader
presets, the blend stream lives in its own slot (vb2), so the backup covers
every slot the game type declares instead of a fixed vb0/vb1 pair.

Everything else (pipeline, VB overrides, resource sections, texture
sections) comes from the shared base in games/base/.
"""

from ...common.mimi_global_properties import MIMIGlobalProperties
from ...common.cross_ib_support import CROSS_IB_ERROR_PREFIX
from ...common.m_ini_builder import M_IniBuilder, M_IniSection, M_SectionType
from ...common.m_ini_helper import M_IniHelper
from ...common.skip_draw import append_hidden_submesh_section, is_submesh_skipped
from ..base.standard_exporter import StandardExporter
from ..base import sections
from ...common.gimi_texture_slots import collect_gimi_texture_bindings, gimi_texture_lines


def _append_slot_texture_lines(section, drawib_model, submesh_model):
    """Submit automatic marks through the package's semantic API."""
    if MIMIGlobalProperties.forbid_auto_texture_ini():
        return
    logical, physical = collect_gimi_texture_bindings(
        drawib_model.get_submesh_texture_markup_info_list(submesh_model)
    )
    for line in gimi_texture_lines(logical, physical):
        section.append(line)


class GF2Exporter(StandardExporter):
    """GF2 exporter: Genshin-style pipeline plus IB override sections."""

    def __init__(self, blueprint_model):
        super().__init__(blueprint_model)
        # Pre-scan every DrawIB and group the cross-marked draw calls by the
        # host Submesh they render at.  Running before the first section is
        # written keeps a pair that names an unknown host from half-writing an
        # INI: the export fails and nothing is left behind.
        self.cross_ib_host_entries = self.collect_cross_ib_host_entries()

    # ------------------------------------------------------------------
    # Cross-IB rendering helpers
    # ------------------------------------------------------------------

    @staticmethod
    def get_cross_ib_backup_resource_name(drawib_model, submesh_model, vb_slot: str) -> str:
        """Return the backup resource name of one guest vertex-buffer slot.

        The name carries the Submesh identity and the slot directly, so any
        number of backups never collide (no auto-increment numbers), e.g.
        Resource_LOD0_fd1dede6_0_BK_VB0.  The slot arrives as the game type
        spells it ("vb0"), and only its number goes into the name so the
        existing Naraka naming style is preserved.
        """
        slot_index = str(vb_slot).strip().lower().replace("vb", "")
        return "Resource_" + drawib_model.get_submesh_unique_key(submesh_model) + "_BK_VB" + slot_index

    @staticmethod
    def get_cross_ib_backup_slot_list(drawib_model) -> list:
        """Every vertex-buffer slot this DrawIB's VB overrides replace.

        The list is read from the game type instead of being hard-coded:
        GF2's GPU-pre-skinning types keep BLENDWEIGHTS/BLENDINDICES in vb2,
        so a guest that only restored vb0/vb1 would be deformed with the
        host's weights.  The CPU-drawn types put everything in vb0 and
        produce a one-slot list with the same code.
        """
        game_type = drawib_model.d3d11_game_type
        slot_list = []

        # A category lands in a slot only when its draw category matches the
        # category whose TextureOverrideVB section emits the binding.
        for category_name in game_type.OrderedCategoryNameList:
            for original_category_name, draw_category_name in game_type.CategoryDrawCategoryDict.items():
                if category_name != draw_category_name:
                    continue
                slot_name = game_type.CategoryExtractSlotDict.get(original_category_name, "")
                if slot_name and slot_name not in slot_list:
                    slot_list.append(slot_name)

        # Sorted so the emitted INI stays identical no matter how the capture
        # ordered the categories.
        return sorted(slot_list)

    @staticmethod
    def submesh_has_cross_ib_draw_call(submesh_model) -> bool:
        """True when at least one draw call of this Submesh renders elsewhere.

        Such a Submesh is a cross-IB guest: it has to capture its live vertex
        buffers, because its own section no longer issues those draws.
        """
        for draw_call_model in getattr(submesh_model, "drawcall_model_list", []):
            if getattr(draw_call_model, "cross_render_at_submesh", ""):
                return True
        return False

    def collect_cross_ib_host_entries(self) -> dict:
        """Group the cross-marked draw calls by their host Submesh.

        Returns host submesh_name -> list of guest entries, keeping the
        blueprint parse order inside each group so the host section draws the
        guests in the order the user wired them.
        """
        submesh_name_set = set()
        for drawib_model in self.drawib_model_list:
            for submesh_model in drawib_model.submesh_model_list:
                submesh_name_set.add(submesh_model.submesh_name)

        host_entries = {}
        for drawib_model in self.drawib_model_list:
            for submesh_model in drawib_model.submesh_model_list:
                # Collect the crossed draws of this Submesh per host first.
                crossed_per_host = {}
                for draw_call_model in getattr(submesh_model, "drawcall_model_list", []):
                    host_submesh_name = getattr(draw_call_model, "cross_render_at_submesh", "")
                    if not host_submesh_name:
                        continue
                    draw_call_list = crossed_per_host.get(host_submesh_name, [])
                    draw_call_list.append(draw_call_model)
                    crossed_per_host[host_submesh_name] = draw_call_list

                for host_submesh_name, draw_call_list in crossed_per_host.items():
                    # A host that is not part of this export can never be
                    # matched by the game, so fail instead of writing a
                    # section that silently does nothing.
                    if host_submesh_name not in submesh_name_set:
                        raise ValueError(
                            CROSS_IB_ERROR_PREFIX + "host Submesh '" + host_submesh_name
                            + "' does not exist in this export"
                        )
                    entry = {
                        "guest_drawib_model": drawib_model,
                        "guest_submesh_model": submesh_model,
                        "draw_call_list": draw_call_list,
                    }
                    entry_list = host_entries.get(host_submesh_name, [])
                    entry_list.append(entry)
                    host_entries[host_submesh_name] = entry_list

        return host_entries

    def append_cross_ib_lines(self, section, drawib_model, submesh_model, backup_slot_list: list):
        """Write the guest backup and the host blocks of one Submesh section.

        Order matters and is the whole trick:
        - the guest backup sits after the guest's own draws, while the mod's
          vertex buffers are still the live bindings,
        - the host blocks sit after the host's own draws, so the host never
          has to restore anything afterwards.
        """
        # Guest backup: capture the live vertex buffers of this DrawIB.
        if self.submesh_has_cross_ib_draw_call(submesh_model):
            for slot_name in backup_slot_list:
                section.append(
                    self.get_cross_ib_backup_resource_name(drawib_model, submesh_model, slot_name)
                    + " = ref " + slot_name
                )

        # Host blocks: re-emit every guest draw call with the guest index
        # buffer and the guest vertex buffers restored from the backup.
        for cross_entry in self.cross_ib_host_entries.get(submesh_model.submesh_name, []):
            guest_drawib_model = cross_entry["guest_drawib_model"]
            guest_submesh_model = cross_entry["guest_submesh_model"]
            section.append(
                "; Cross-IB: " + guest_submesh_model.display_str
                + " rendered at " + submesh_model.display_str
            )
            section.append("ib = " + guest_drawib_model.get_submesh_ib_resource_name(guest_submesh_model))

            # The guest's own slot list is used, not the host's: these are the
            # buffers that belong to the geometry now being drawn.
            for slot_name in self.get_cross_ib_backup_slot_list(guest_drawib_model):
                section.append(
                    slot_name + " = "
                    + self.get_cross_ib_backup_resource_name(guest_drawib_model, guest_submesh_model, slot_name)
                )

            for drawindexed_str in M_IniHelper.get_drawindexed_str_list(
                cross_entry["draw_call_list"],
                obj_name_draw_offset_dict=guest_drawib_model.obj_name_draw_offset,
            ):
                section.append(drawindexed_str)

    def add_cross_ib_resource_sections(self, ini_builder: M_IniBuilder, drawib_model):
        """Declare one empty resource per guest vertex-buffer backup.

        The sections carry no type and no filename on purpose: 3Dmigoto fills
        them at run time from the "ref <slot>" line that captures the live
        binding, so a backup always holds the buffer the mod had bound and
        never a copy taken at export time.
        """
        backup_slot_list = self.get_cross_ib_backup_slot_list(drawib_model)
        resource_section = M_IniSection(M_SectionType.ResourceBuffer)
        declared_count = 0

        for submesh_model in drawib_model.submesh_model_list:
            if not self.submesh_has_cross_ib_draw_call(submesh_model):
                continue
            for slot_name in backup_slot_list:
                resource_section.append(
                    "[" + self.get_cross_ib_backup_resource_name(drawib_model, submesh_model, slot_name) + "]"
                )
                resource_section.new_line()
                declared_count = declared_count + 1

        # An empty section would only add a stray marker line to the INI.
        if declared_count == 0:
            return
        ini_builder.append_section(resource_section)

    # ------------------------------------------------------------------
    # Sections
    # ------------------------------------------------------------------

    def add_drawib_sections(self, ini_builder: M_IniBuilder, drawib_model):
        # GIMI's VertexLimitRaise never carries uav_byte_stride.
        sections.add_unity_vs_texture_override_vlr_section(ini_builder=ini_builder, drawib_model=drawib_model, include_uav_byte_stride=False)
        sections.add_unity_vs_texture_override_vb_sections(ini_builder=ini_builder, drawib_model=drawib_model, blueprint_model=self.blueprint_model)
        self.add_unity_vs_texture_override_ib_sections(ini_builder=ini_builder, drawib_model=drawib_model)
        sections.add_unity_vs_resource_vb_sections(ini_builder=ini_builder, drawib_model=drawib_model)
        # The backups are declared next to the other buffer resources, so a
        # reader finds every [Resource...] block in one part of the INI.
        self.add_cross_ib_resource_sections(ini_builder=ini_builder, drawib_model=drawib_model)
        sections.add_resource_texture_sections(ini_builder=ini_builder, drawib_model=drawib_model)

    def add_unity_vs_texture_override_ib_sections(self, ini_builder: M_IniBuilder, drawib_model):
        # IB overrides: skip the whole original IB first, then re-emit every
        # Submesh with its modded IB and the automatic slot textures.
        texture_override_ib_section = M_IniSection(M_SectionType.TextureOverrideIB)
        draw_ib = drawib_model.draw_ib
        # One list for the whole DrawIB: the backup covers exactly the slots
        # its VB overrides replace, and every guest of this DrawIB uses it.
        backup_slot_list = self.get_cross_ib_backup_slot_list(drawib_model)

        texture_override_ib_section.append("[TextureOverride_IB_" + draw_ib + "]")
        texture_override_ib_section.append("hash = " + draw_ib)
        texture_override_ib_section.append("handling = skip")
        texture_override_ib_section.new_line()

        for submesh_model in drawib_model.submesh_model_list:
            texture_override_name_suffix = drawib_model.get_submesh_texture_override_suffix(submesh_model)
            ib_resource_name = drawib_model.get_submesh_ib_resource_name(submesh_model)

            # Skip Draw: the DrawIB level section above already skips the whole
            # original IB, so a hidden Submesh only needs its own matched skip
            # section and must not submit textures or draws.
            if is_submesh_skipped(submesh_model):
                append_hidden_submesh_section(
                    texture_override_ib_section,
                    draw_ib,
                    texture_override_name_suffix,
                    submesh_model.match_first_index,
                    submesh_model,
                )
                continue

            texture_override_ib_section.append("[TextureOverride_" + texture_override_name_suffix + "]")
            texture_override_ib_section.append("hash = " + draw_ib)
            texture_override_ib_section.append("match_first_index = " + str(submesh_model.match_first_index))

            ib_buf = drawib_model.submesh_ib_dict.get(submesh_model.submesh_name, None)
            if ib_buf is None or len(ib_buf) == 0:
                texture_override_ib_section.append("ib = null")
                texture_override_ib_section.new_line()
                continue

            texture_override_ib_section.append("ib = " + ib_resource_name)

            # A cross-IB guest keeps only its ordinary draws here; the marked
            # ones are issued by the host Submesh section instead.
            normal_draw_call_list = []
            for draw_call_model in submesh_model.drawcall_model_list:
                if not getattr(draw_call_model, "cross_render_at_submesh", ""):
                    normal_draw_call_list.append(draw_call_model)

            # Objects with semantic MARK overrides need a fresh complete API
            # submission before each draw because SetTextures clears its inputs.
            has_semantic_overrides = any(
                (getattr(draw, "resolved_gimi_texture_bindings", {}) or getattr(draw, "global_gimi_texture_defaults", {}))
                for draw in normal_draw_call_list
            )
            if has_semantic_overrides:
                logical, physical = ({}, [])
                if not MIMIGlobalProperties.forbid_auto_texture_ini():
                    logical, physical = collect_gimi_texture_bindings(
                        drawib_model.get_submesh_texture_markup_info_list(submesh_model)
                    )

                def effective_lines(draw):
                    # A draw starts from defaults, never from the previous object.
                    effective = dict(logical)
                    # Merge from scratch because SetTextures consumes its inputs.
                    # Global defaults override automatic captures only for this Submesh.
                    # Connected semantic replacements are applied last and always win.
                    effective.update(getattr(draw, "global_gimi_texture_defaults", {}))
                    effective.update(getattr(draw, "resolved_gimi_texture_bindings", {}))
                    return gimi_texture_lines(effective, physical)

                M_IniHelper.append_drawindexed_with_slot_lines(
                    texture_override_ib_section,
                    normal_draw_call_list,
                    effective_lines,
                    obj_name_draw_offset_dict=drawib_model.obj_name_draw_offset,
                )
            else:
                _append_slot_texture_lines(texture_override_ib_section, drawib_model, submesh_model)
                for drawindexed_str in M_IniHelper.get_drawindexed_str_list(
                    normal_draw_call_list,
                    obj_name_draw_offset_dict=drawib_model.obj_name_draw_offset,
                ):
                    texture_override_ib_section.append(drawindexed_str)

            # Guest backup first, then the host blocks of this Submesh.
            self.append_cross_ib_lines(
                texture_override_ib_section,
                drawib_model,
                submesh_model,
                backup_slot_list,
            )

        ini_builder.append_section(texture_override_ib_section)
