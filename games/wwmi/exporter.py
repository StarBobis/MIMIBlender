"""
WWMI (Wuthering Waves) mod exporter.

WWMI assembles all exported DrawIB/LOD scopes into one INI file; the export keeps the append order (no section
reordering), and the mod registers itself with the WWMI runtime through
the CommandListRegisterMod flow.  This file holds the main exporter and
its DrawIB-level sections; the shape key and blend remap / merged skeleton
sections live in their own modules of this package.

Every DrawIB shares one 3Dmigoto namespace with all other INI files of the
same mod, so all symbols that describe one draw range (globals, resources,
command lists and custom shaders) carry the DrawIB as a suffix.  The naming
rules live in ``names.py``; see that module for the engine behaviour that
makes the suffix necessary.
"""

import os

from ...common.mimi_global_properties import MIMIGlobalProperties
from ...common.global_config import GlobalConfig
from ...common.m_ini_builder import M_IniBuilder, M_IniSection, M_SectionType
from ...common.m_ini_helper import M_IniHelper
from ...common.d3d11_semantics import D3D11Category
from .model import DrawIBModelWWMI
from .names import (
    WWMI_REQUIRED_RUNTIME_VERSION,
    scoped_global,
    scoped_name,
    scoped_section,
)
from .ini_validation import disable_legacy_ini_files, validate_ini_builder
from . import shapekeys
from . import blend_remap

# ---------------------------------------------------------------------------
# Category binding helpers
# ---------------------------------------------------------------------------
# Every category used to be bound to one fixed vertex buffer slot. The capture
# also stores the slot the stream was dumped from, and a shader resource slot
# ("vs-t0", "vs-t1", "ps-t3", ...) means the vertex shader fetches that record by
# hand instead of reading the input assembler. Such a stream is only reachable
# through a resource view, so the mod has to hand the runtime a view instead of a
# plain vertex buffer.
CATEGORY_DEFAULT_SLOT = {
    D3D11Category.POSITION: "vb0",
    # "Vector" holds TANGENT and NORMAL and has no D3D11Category constant.
    "Vector": "vb1",
    D3D11Category.TEXCOORD: "vb2",
    D3D11Category.COLOR: "vb3",
    D3D11Category.BLEND: "vb4",
}

# DXGI format of one half2 texcoord element.
HALF2_FORMAT = "DXGI_FORMAT_R16G16_FLOAT"

# The game declares the texcoord record as half4 groups in the input layout, so
# a manual fetch reads eight bytes at a time and the view element has to hold
# four half components.
HALF4_FORMAT = "DXGI_FORMAT_R16G16B16A16_FLOAT"


def is_shader_resource_slot(slot_name: str) -> bool:
    """Return True when the slot holds a shader resource view.

    "vs-t0", "ps-t2", "cs-t1" and so on are shader resource slots: they take a
    view and therefore need a declared element format. "vb0" and "ib" are input
    assembler slots and take a buffer directly.
    """
    if not slot_name or "-t" not in slot_name:
        return False
    shader_prefix = slot_name.split("-t", 1)[0]
    return shader_prefix in ("vs", "ps", "cs", "gs", "hs", "ds")


def get_category_binding_slot(d3d11_game_type, category_name: str) -> str:
    """Slot the mod has to bind for one category.

    Old workspaces carry no ExtractSlot for their elements, so fall back to the
    vertex buffer slot this exporter has always used.
    """
    slot_dict = getattr(d3d11_game_type, "CategoryExtractSlotDict", None) or {}
    slot_name = slot_dict.get(category_name, "")
    if slot_name:
        return slot_name
    return CATEGORY_DEFAULT_SLOT.get(category_name, "")


def get_ordered_category_names(d3d11_game_type) -> list:
    """Category names of one game type in declaration order.

    The real model keeps ``OrderedCategoryNameList``. A stripped down model that
    only carries the stride dict still works, because that dict keeps the
    declaration order as well.
    """
    category_names = getattr(d3d11_game_type, "OrderedCategoryNameList", None)
    if category_names:
        return list(category_names)
    return list(getattr(d3d11_game_type, "CategoryStrideDict", {}) or {})


def get_srv_view_layout(d3d11_game_type, category_name: str):
    """Return (format, element width) of the view a shader slot needs.

    The texcoord record is declared as half4 groups, so a sixteen byte record is
    read as two eight byte elements. Every other category is read one declared
    element at a time, which is also what its input layout says.

    Returns ("", 0) when the category has no element to describe.
    """
    elements = [
        element
        for element in getattr(d3d11_game_type, "D3D11ElementList", [])
        if element.Category == category_name
    ]
    if not elements:
        return "", 0
    if category_name == D3D11Category.TEXCOORD:
        category_stride = sum(element.ByteWidth for element in elements)
        every_element_is_half2 = all(
            element.Format == "R16G16_FLOAT" and element.ByteWidth == 4
            for element in elements
        )
        if every_element_is_half2 and category_stride % 8 == 0:
            return HALF4_FORMAT, 8
    first_element = elements[0]
    return "DXGI_FORMAT_" + first_element.Format, first_element.ByteWidth


class Exporter:
    """WWMI exporter: one mod INI, scoped geometry, WWMIv1 registration."""

    def __init__(self, blueprint_model):
        self.blueprint_model = blueprint_model
        self.drawib_drawibmodel_dict: dict[str, DrawIBModelWWMI] = {}
        # Mod level sections (mod info, hash texture overrides) may only be
        # written once for the whole mod, because every INI of a mod shares one
        # 3Dmigoto namespace and a repeated section name is only read once.
        self.mod_info_sections_written = False
        self.hash_sections_written = False
        self.parse_draw_ib_draw_ib_model_dict()

    def parse_draw_ib_draw_ib_model_dict(self):
        # Preserve first-seen order while isolating metadata for each LOD.
        # Renaming alone is not sufficient: each model must load only its LOD.
        scopes = []
        for drawcall in self.blueprint_model.ordered_draw_obj_data_model_list:
            submesh = drawcall.get_submesh_name()
            prefix = submesh.split(".", 1)[0]
            lod = prefix if "." in submesh and prefix.startswith("LOD") and prefix[3:].isdigit() else ""
            scope = (drawcall.match_draw_ib, lod)
            if scope not in scopes:
                scopes.append(scope)
        for draw_ib, lod in scopes:
            model = DrawIBModelWWMI(
                draw_ib=draw_ib, blueprint_model=self.blueprint_model, lod_name=lod,
            )
            self.drawib_drawibmodel_dict[model.draw_ib] = model

        for draw_ib_model in self.drawib_drawibmodel_dict.values():
            draw_ib_model.apply_drawib_alias()

    def add_constants_section(self, ini_builder: M_IniBuilder, draw_ib_model: DrawIBModelWWMI):
        """[Constants] of one DrawIB.

        Two groups of variables live here:

        * mod level variables (``$required_wwmi_version``, ``$mod_id``,
          ``$mod_enabled``, ``$object_detected``): deliberately global, because
          the runtime registration and the "is my object on screen" flag are
          properties of the whole mod;
        * draw range variables (guid, vertex counts, shape key batches, the
          merged skeleton state ids): suffixed with the DrawIB, because each
          DrawIB has its own geometry and its own skeleton buffers.

        A repeated global is dropped by 3Dmigoto ("Redeclaration"), so the
        suffix is what keeps a second DrawIB from silently inheriting the first
        DrawIB's vertex count.
        """
        draw_ib = draw_ib_model.draw_ib
        constants_section = M_IniSection(M_SectionType.Constants)
        constants_section.append("[Constants]")
        # Mod globals are singleton declarations even with multiple models.
        # Inspect the builder, not exporter state, so rebuilding stays safe.
        if not any(section.SectionType == M_SectionType.Constants for section in ini_builder.ini_section_list):
            # Extended tables require the verified WWMI 1.10 stride API. The
            # requirement is mod-wide, so inspect every DrawIB before emitting
            # the singleton even if the first character needs only legacy maps.
            models = getattr(self, "drawib_drawibmodel_dict", {}).values()
            extended_remap = any(model.blend_remap and getattr(model, "blend_remap_bone_count", 512) > 512 for model in models)
            required_version = "1.10" if extended_remap else WWMI_REQUIRED_RUNTIME_VERSION
            constants_section.append("global $required_wwmi_version = " + required_version)
            constants_section.append("global $mod_id = -1000")
            constants_section.append("global $mod_enabled = 0")
            constants_section.append("global $object_detected = 0")
        constants_section.append("global " + scoped_global("object_detected", draw_ib) + " = 0")
        constants_section.append(
            "global " + scoped_global("object_guid", draw_ib) + " = " + str(draw_ib_model.wwmi_info.index_count)
        )
        constants_section.append(
            "global " + scoped_global("mesh_vertex_count", draw_ib) + " = " + str(draw_ib_model.mesh_vertex_count)
        )

        # A category dumped from a shader resource slot is bound through a
        # resource view. The game's shader decides how wide that view element is,
        # and the texcoord record has two documented widths: eight byte half4
        # groups (0) or single four byte half2 elements (1). Every other stream
        # keeps the width its captured input layout declares.
        if self.has_texcoord_half2_switch(draw_ib_model):
            # The comment is part of the generated file: only the game's shader
            # knows the width it fetches, so the switch has to be discoverable
            # without regenerating the mod.
            constants_section.append(
                "; The texcoord record of this DrawIB is fetched from a shader resource"
            )
            constants_section.append(
                "; slot, so the mod binds it through a resource view. 0 reads half4"
            )
            constants_section.append(
                "; groups (eight byte elements), 1 reads single half2 elements (four"
            )
            constants_section.append(
                "; byte elements). Set it to 1 when the mesh renders with wrong UVs."
            )
            constants_section.append(
                "global " + scoped_global("srv_texcoord_half2", draw_ib) + " = 0"
            )
        constants_section.append(
            "global " + scoped_global("shapekey_vertex_count", draw_ib) + " = "
            + str(len(draw_ib_model.obj_buffer_model_wwmi.shapekey_vertex_ids))
        )
        for batch_id, batch in enumerate(shapekeys.get_wwmi_shapekey_batches(draw_ib_model)):
            constants_section.append(
                "global " + scoped_global("shapekey_vertex_offset_batch" + str(batch_id), draw_ib)
                + " = " + str(batch["custom_vertex_offset"])
            )
            constants_section.append(
                "global " + scoped_global("shapekey_vertex_count_batch" + str(batch_id), draw_ib)
                + " = " + str(batch["custom_vertex_count"])
            )
        # The merged skeleton workflow tracks, per component, how much skeleton
        # data was collected in the current frame. The status of the component
        # currently being merged is passed through one shared variable, exactly
        # like the reference WWMI implementation does.
        if MIMIGlobalProperties.import_merged_vgmap() == 'MERGED':
            constants_section.append("global " + scoped_global("state_id", draw_ib) + " = 0")
            constants_section.append("global " + scoped_global("merge_status_id", draw_ib) + " = 0")
            for component_index in range(len(draw_ib_model.wwmi_info.components)):
                constants_section.append(
                    "global " + scoped_global("merge_status_id_" + str(component_index), draw_ib) + " = 0"
                )

        constants_section.new_line()
        ini_builder.append_section(constants_section)

    def add_present_section(self, ini_builder: M_IniBuilder, draw_ib_model: DrawIBModelWWMI):
        """Per frame work of one DrawIB.

        Registers the mod once and, while the mod is enabled, refreshes the
        merged skeleton copies and resets the per component merge status so
        every component can collect skeleton data again in this frame.
        """
        draw_ib = draw_ib_model.draw_ib
        present_section = M_IniSection(M_SectionType.Present)
        present_section.append("[Present]")
        present_section.append("if " + scoped_global("object_detected", draw_ib))
        present_section.append("  if $mod_enabled")
        present_section.append("    post " + scoped_global("object_detected", draw_ib) + " = 0")

        if MIMIGlobalProperties.import_merged_vgmap() == 'MERGED':
            if draw_ib_model.blend_remap:
                present_section.append("    run = " + scoped_name("CommandListInitializeBlendRemaps", draw_ib))
            present_section.append("    run = " + scoped_name("CommandListUpdateMergedSkeleton", draw_ib))

        present_section.append("  else")
        present_section.append("    if $mod_id == -1000")
        present_section.append("      run = " + scoped_name("CommandListRegisterMod", draw_ib))
        present_section.append("    endif")
        present_section.append("  endif")
        present_section.append("endif")
        present_section.new_line()
        ini_builder.append_section(present_section)

    def add_commandlist_register_mod_section(self, ini_builder: M_IniBuilder, draw_ib_model: DrawIBModelWWMI):
        """Hand the mod metadata to the WWMI runtime and read back the mod id."""
        draw_ib = draw_ib_model.draw_ib
        commandlist_section = M_IniSection(M_SectionType.CommandList)
        commandlist_section.append(scoped_section("CommandListRegisterMod", draw_ib))
        # "$\WWMIv1\..." and "Resource\WWMIv1\..." are runtime API names: they
        # must keep their exact spelling, only their values are DrawIB scoped.
        commandlist_section.append("$\\WWMIv1\\required_wwmi_version = $required_wwmi_version")
        commandlist_section.append("$\\WWMIv1\\object_guid = " + scoped_global("object_guid", draw_ib))
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
        """By-hash triggers plus the by-slot shared resource override pair.

        ``[CommandList...OverrideSharedResources]`` redirects the VB/IB slots to
        this DrawIB's own buffers and plugs the merged skeleton into the bone
        data constant buffers; the cleanup list restores the original context.
        """
        draw_ib = draw_ib_model.draw_ib
        commandlist_section = M_IniSection(M_SectionType.CommandList)
        commandlist_section.append(scoped_section("CommandListTriggerResourceOverrides", draw_ib))
        for slot_index in range(9):
            commandlist_section.append("CheckTextureOverride = ps-t" + str(slot_index))
        if MIMIGlobalProperties.import_merged_vgmap() == 'MERGED':
            commandlist_section.append("CheckTextureOverride = vs-cb3")
            commandlist_section.append("CheckTextureOverride = vs-cb4")
        commandlist_section.new_line()

        commandlist_section.append(scoped_section("ResourceBypassVB0", draw_ib))
        commandlist_section.new_line()

        commandlist_section.append(scoped_section("CommandListOverrideSharedResources", draw_ib))
        commandlist_section.append(scoped_name("ResourceBypassVB0", draw_ib) + " = ref vb0")
        commandlist_section.append("ib = " + scoped_name("ResourceIndexBuffer", draw_ib))
        # Shape key buffers are written by compute shaders before the bindings.
        if shapekeys.get_wwmi_shapekey_entries(draw_ib_model):
            commandlist_section.append("run = " + scoped_name("CommandListApplyShapeKeysPosition", draw_ib))
            commandlist_section.append("run = " + scoped_name("CommandListApplyShapeKeysVector", draw_ib))

        # One binding per captured category. The workspace stores the slot each
        # stream was dumped from, so a shader resource slot (vs-t0, vs-t1) is
        # filled with a resource view next to the vertex buffer slots.
        self.add_category_bindings(commandlist_section, draw_ib_model)

        # Some captured layouts omit COLOR entirely. Do not bind a resource that
        # add_resource_buffer cannot declare for that layout; null it out so a
        # buffer left behind by the previous draw is never read as our geometry.
        if D3D11Category.COLOR not in draw_ib_model.d3d11_game_type.CategoryStrideDict:
            commandlist_section.append("vb3 = null")

        # Note: here we must use ref instead of a direct "=" assignment.
        # In 3Dmigoto, "= ResourceMergedSkeleton" is a one-time value copy;
        # "= ref ResourceMergedSkeleton" is a reference binding.
        # Without ref, when a later compute shader updates the skeleton, vs-cb will not update in sync.

        if MIMIGlobalProperties.import_merged_vgmap() == 'MERGED':
            merged_skeleton = scoped_name("ResourceMergedSkeleton", draw_ib)
            extra_skeleton = scoped_name("ResourceExtraMergedSkeleton", draw_ib)
            merged_skeleton_override = scoped_name("ResourceMergedSkeletonOverride", draw_ib)
            extra_skeleton_override = scoped_name("ResourceExtraMergedSkeletonOverride", draw_ib)

            if draw_ib_model.blend_remap:
                commandlist_section.append("if " + scoped_name("ResourceBlendBufferOverride", draw_ib) + " === null")
                commandlist_section.append("vb4 = " + scoped_name("ResourceBlendBuffer", draw_ib))
                commandlist_section.append("if vs-cb4 == 3381.7777")
                commandlist_section.append("  vs-cb4 = ref " + merged_skeleton)
                commandlist_section.append("  if vs-cb3 == 3381.7777")
                commandlist_section.append("    vs-cb3 = ref " + extra_skeleton)
                commandlist_section.append("  endif")
                commandlist_section.append("else if vs-cb3 == 3381.7777")
                commandlist_section.append("  vs-cb3 = ref " + merged_skeleton)
                commandlist_section.append("endif")
                commandlist_section.append("else")
                commandlist_section.append("vb4 = ref " + scoped_name("ResourceBlendBufferOverride", draw_ib))
                commandlist_section.append("if vs-cb4 == 3381.7777")
                commandlist_section.append("  vs-cb4 = ref " + merged_skeleton_override)
                commandlist_section.append("  if vs-cb3 == 3381.7777")
                commandlist_section.append("    vs-cb3 = ref " + extra_skeleton_override)
                commandlist_section.append("  endif")
                commandlist_section.append("else if vs-cb3 == 3381.7777")
                commandlist_section.append("  vs-cb3 = ref " + merged_skeleton_override)
                commandlist_section.append("endif")
                commandlist_section.append("endif")
            else:
                commandlist_section.append("if vs-cb4 == 3381.7777")
                commandlist_section.append("  vs-cb4 = ref " + merged_skeleton)
                commandlist_section.append("  if vs-cb3 == 3381.7777")
                commandlist_section.append("    vs-cb3 = ref " + extra_skeleton)
                commandlist_section.append("  endif")
                commandlist_section.append("else if vs-cb3 == 3381.7777")
                commandlist_section.append("  vs-cb3 = ref " + merged_skeleton)
                commandlist_section.append("endif")

        commandlist_section.new_line()
        commandlist_section.append(scoped_section("CommandListCleanupSharedResources", draw_ib))
        commandlist_section.append("vb0 = ref " + scoped_name("ResourceBypassVB0", draw_ib))

        if draw_ib_model.blend_remap:
            commandlist_section.append("if " + scoped_name("ResourceBlendBufferOverride", draw_ib) + " !== null")
            commandlist_section.append("    " + scoped_name("ResourceBlendBufferOverride", draw_ib) + " = null")
            commandlist_section.append("    " + scoped_name("ResourceMergedSkeletonOverride", draw_ib) + " = null")
            commandlist_section.append("    " + scoped_name("ResourceExtraMergedSkeletonOverride", draw_ib) + " = null")
            commandlist_section.append("endif")

        commandlist_section.new_line()
        ini_builder.append_section(commandlist_section)

    def get_srv_category_names(self, draw_ib_model: DrawIBModelWWMI) -> list:
        """Categories of one DrawIB that the capture dumped from a shader slot."""
        game_type = draw_ib_model.d3d11_game_type
        category_names = []
        for category_name in get_ordered_category_names(game_type):
            binding_slot = get_category_binding_slot(game_type, category_name)
            if is_shader_resource_slot(binding_slot):
                category_names.append(category_name)
        return category_names

    def has_texcoord_half2_switch(self, draw_ib_model: DrawIBModelWWMI) -> bool:
        """Whether the texcoord record offers both view widths.

        The half2 width is only declared when the default view is the half4
        group, so the switch variable and its command list block must agree.
        """
        if D3D11Category.TEXCOORD not in self.get_srv_category_names(draw_ib_model):
            return False
        view_format, _view_stride = get_srv_view_layout(
            draw_ib_model.d3d11_game_type, D3D11Category.TEXCOORD
        )
        return view_format == HALF4_FORMAT

    def add_category_bindings(self, commandlist_section: M_IniSection, draw_ib_model: DrawIBModelWWMI):
        """Bind every captured category to the slot it was dumped from.

        Most categories come from a vertex buffer and keep the plain binding
        this exporter has always written. A category dumped from a shader
        resource slot is different: the vertex shader of such a mesh fetches the
        record by hand, so the buffer has to be handed in as a resource view as
        well. The vertex buffer slot of that category is bound too, because a
        shader variant that reads the input assembler then keeps working on the
        same data.
        """
        draw_ib = draw_ib_model.draw_ib
        game_type = draw_ib_model.d3d11_game_type
        # A shape key DrawIB replaces position and vector with the buffers its
        # shape key command lists have just written.
        shapekey_entries = shapekeys.get_wwmi_shapekey_entries(draw_ib_model)

        for category_name in get_ordered_category_names(game_type):
            binding_slot = get_category_binding_slot(game_type, category_name)
            if not binding_slot:
                # An unknown category name cannot be bound anywhere.
                continue

            # A blend remap keeps its own remapped Blend buffers, which the
            # remap command lists bind; the shared list must not overwrite them.
            if category_name == D3D11Category.BLEND and draw_ib_model.blend_remap:
                continue

            # Shape key buffers are written by a compute shader and only exist as
            # vertex buffers, so they never live in a shader resource slot.
            if shapekey_entries and category_name == D3D11Category.POSITION:
                commandlist_section.append("vb0 = ref " + scoped_name("ResourcePositionBufferShapeKeyVB", draw_ib))
                continue
            if shapekey_entries and category_name == "Vector":
                commandlist_section.append("vb1 = ref " + scoped_name("ResourceVectorBufferShapeKeyVB", draw_ib))
                continue

            resource_name = scoped_name("Resource" + category_name + "Buffer", draw_ib)

            if not is_shader_resource_slot(binding_slot):
                # A plain vertex buffer slot is complete with the buffer itself.
                commandlist_section.append(binding_slot + " = " + resource_name)
                continue

            # Keep the input assembler path of the same category fed as well.
            default_slot = CATEGORY_DEFAULT_SLOT.get(category_name, "")
            if default_slot:
                commandlist_section.append(default_slot + " = " + resource_name)

            # The view element width has to match what the game's shader fetches.
            # The texcoord record has two documented widths, so it gets a switch
            # that selects between them in game. The half2 width is only offered
            # when add_resource_buffer declared it for this record.
            srv_resource_name = scoped_name("Resource" + category_name + "BufferSrv", draw_ib)
            view_format, _view_stride = get_srv_view_layout(game_type, category_name)
            use_half2_switch = (
                category_name == D3D11Category.TEXCOORD and view_format == HALF4_FORMAT
            )
            if use_half2_switch:
                half2_resource_name = scoped_name("Resource" + category_name + "BufferSrvHalf2", draw_ib)
                commandlist_section.append("if " + scoped_global("srv_texcoord_half2", draw_ib))
                commandlist_section.append("  " + binding_slot + " = ref " + half2_resource_name)
                commandlist_section.append("else")
                commandlist_section.append("  " + binding_slot + " = ref " + srv_resource_name)
                commandlist_section.append("endif")
            else:
                commandlist_section.append(binding_slot + " = ref " + srv_resource_name)

    def add_resource_mod_info_section_default(self, ini_builder: M_IniBuilder, draw_ib_model: DrawIBModelWWMI):
        """Mod name / author / description resources.

        Written once per mod: the resource names are shared by every DrawIB INI,
        and a repeated section would only be read from the first file anyway.
        """
        if self.mod_info_sections_written:
            return
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
        self.mod_info_sections_written = True

    def add_texture_override_mark_bone_data_cb(self, ini_builder: M_IniBuilder, draw_ib_model: DrawIBModelWWMI):
        """Tag the bone data constant buffer with the 3381.7777 filter index.

        The merge command list can only tell skeleton data apart from other
        constant buffer contents by this marker, so the section is required for
        the merged skeleton workflow (and harmless otherwise).
        """
        draw_ib = draw_ib_model.draw_ib
        texture_override_mark_bonedatacb_section = M_IniSection(M_SectionType.TextureOverrideGeneral)
        texture_override_mark_bonedatacb_section.append(scoped_section("TextureOverrideMarkBoneDataCB", draw_ib))
        texture_override_mark_bonedatacb_section.append("hash = " + draw_ib_model.wwmi_info.cb4_hash)
        texture_override_mark_bonedatacb_section.append("match_priority = 0")
        texture_override_mark_bonedatacb_section.append("filter_index = 3381.7777")
        texture_override_mark_bonedatacb_section.new_line()
        ini_builder.append_section(texture_override_mark_bonedatacb_section)

    def add_texture_override_component(self, ini_builder: M_IniBuilder, draw_ib_model: DrawIBModelWWMI):
        """One [TextureOverrideComponent...] per Submesh of the DrawIB.

        A Submesh without any object in the blueprint still gets its section:
        the component metadata must stay aligned with the real component index,
        and the game's own draw for that range has to be dealt with. Only the
        drawindexed lines are omitted, so that Submesh is not rendered while
        the mod is enabled.

        Such a component also takes no part in the skeleton merge: its
        component level VG range does not describe the merged vertex group
        layout, so merging for it would overwrite skeleton data that another
        component already collected correctly.
        """
        draw_ib = draw_ib_model.draw_ib
        texture_override_component = M_IniSection(M_SectionType.TextureOverrideIB)
        blend_remap_used_by_index = getattr(draw_ib_model, "blend_remap_used_by_index", None) or {}
        submesh_drawcall_groups = getattr(draw_ib_model, "submesh_drawcall_groups", []) or []

        for component_count, component_object in enumerate(draw_ib_model.wwmi_info.components):
            component_count_str = str(component_count)
            component_blend_remap_used = bool(blend_remap_used_by_index.get(component_count, False))

            drawcall_model_list = (
                submesh_drawcall_groups[component_count]
                if component_count < len(submesh_drawcall_groups)
                else []
            )
            drawindexed_str_list = M_IniHelper.get_drawindexed_str_list(drawcall_model_list)

            # Skip Draw: the blueprint hides this Submesh. The component keeps
            # its section and metadata (component numbering must never drift),
            # but it re-issues no draw, exactly like a component without any
            # exported object.
            component_skip_draw = any(
                bool(getattr(drawcall_model, "skip_draw", False))
                for drawcall_model in drawcall_model_list
            )
            if component_skip_draw:
                drawindexed_str_list = []

            # A component without any object is skipped in game instead of drawn
            # from the mod's buffers.
            component_has_objects = len(drawindexed_str_list) != 0

            # One reason string keeps both draw branches below in sync when a
            # component is hidden on purpose instead of unassigned.
            draw_skipped_reason = (
                "Skip Draw is enabled for this Submesh"
                if component_skip_draw
                else "No matching custom components found"
            )

            texture_override_component.append(scoped_section("TextureOverrideComponent" + component_count_str, draw_ib))
            texture_override_component.append("hash = " + draw_ib_model.wwmi_info.vb0_hash)
            texture_override_component.append("match_first_index = " + str(component_object.index_offset))
            texture_override_component.append("match_index_count = " + str(component_object.index_count))
            # The shared flag guards textures; the scoped flag selects the
            # registration GUID of a model actually detected this frame.
            texture_override_component.append("$object_detected = 1")
            texture_override_component.append(scoped_global("object_detected", draw_ib) + " = 1")

            if len(self.blueprint_model.keyname_mkey_dict.keys()) != 0:
                texture_override_component.append("$active" + str(GlobalConfig.generated_mod_number) + " = 1")
                # A visible draw range marks the whole mod as on screen. The
                # hotkeys are gated on this instead of a single range's flag,
                # so they work whichever part of the mod is drawn.
                texture_override_component.append("$mod_visible = 1")

            texture_override_component.append("if $mod_enabled")

            if MIMIGlobalProperties.import_merged_vgmap() == 'MERGED':
                # The status is handed to the merge command list through one
                # shared variable and the updated status is read back, so a
                # component merges at most once per frame even when its draw
                # call is issued repeatedly.
                status_var_str = scoped_global("merge_status_id_" + component_count_str, draw_ib)
                shared_status_var_str = scoped_global("merge_status_id", draw_ib)
                if component_has_objects:
                    texture_override_component.append("  if " + status_var_str + " != 2")
                    texture_override_component.append("    $\\WWMIv1\\vg_offset = " + str(component_object.vg_offset))
                    texture_override_component.append("    $\\WWMIv1\\vg_count = " + str(component_object.vg_count))
                    texture_override_component.append("    " + shared_status_var_str + " = " + status_var_str)
                    texture_override_component.append("    run = " + scoped_name("CommandListMergeSkeleton", draw_ib))
                    texture_override_component.append("    " + status_var_str + " = " + shared_status_var_str)
                    texture_override_component.append("  endif")

                texture_override_component.append("  if " + scoped_name("ResourceMergedSkeleton", draw_ib) + " !== null")
                # Skipping the original draw is what removes an unassigned
                # Submesh from the scene; the mod has no geometry for it.
                texture_override_component.append("    handling = skip")
                if component_has_objects:
                    if component_blend_remap_used:
                        texture_override_component.append("    " + scoped_name("ResourceBlendBufferOverride", draw_ib) + " = ref " + scoped_name("ResourceRemappedBlendBufferComponent" + component_count_str, draw_ib))
                        texture_override_component.append("    " + scoped_name("ResourceMergedSkeletonOverride", draw_ib) + " = ref " + scoped_name("ResourceRemappedSkeletonComponent" + component_count_str, draw_ib))
                        texture_override_component.append("    " + scoped_name("ResourceExtraMergedSkeletonOverride", draw_ib) + " = ref " + scoped_name("ResourceExtraRemappedSkeletonComponent" + component_count_str, draw_ib))

                    texture_override_component.append("    run = " + scoped_name("CommandListTriggerResourceOverrides", draw_ib))
                    texture_override_component.append("    run = " + scoped_name("CommandListOverrideSharedResources", draw_ib))
                    texture_override_component.append("    ; Draw Component " + component_count_str)
                    for drawindexed_str in drawindexed_str_list:
                        texture_override_component.append("    " + drawindexed_str)
                    texture_override_component.append("    run = " + scoped_name("CommandListCleanupSharedResources", draw_ib))
                else:
                    texture_override_component.append("    ; Draw skipped: " + draw_skipped_reason)
                texture_override_component.append("  endif")
            else:
                texture_override_component.append("  handling = skip")
                if component_has_objects:
                    if component_blend_remap_used:
                        texture_override_component.append("  " + scoped_name("ResourceBlendBufferOverride", draw_ib) + " = ref " + scoped_name("ResourceRemappedBlendBufferComponent" + component_count_str, draw_ib))
                        texture_override_component.append("  " + scoped_name("ResourceMergedSkeletonOverride", draw_ib) + " = ref " + scoped_name("ResourceRemappedSkeletonComponent" + component_count_str, draw_ib))
                        texture_override_component.append("  " + scoped_name("ResourceExtraMergedSkeletonOverride", draw_ib) + " = ref " + scoped_name("ResourceExtraRemappedSkeletonComponent" + component_count_str, draw_ib))

                    texture_override_component.append("  run = " + scoped_name("CommandListTriggerResourceOverrides", draw_ib))
                    texture_override_component.append("  run = " + scoped_name("CommandListOverrideSharedResources", draw_ib))
                    texture_override_component.append("  ; Draw Component " + component_count_str)
                    for drawindexed_str in drawindexed_str_list:
                        texture_override_component.append("  " + drawindexed_str)
                    texture_override_component.append("  run = " + scoped_name("CommandListCleanupSharedResources", draw_ib))
                else:
                    texture_override_component.append("  ; Draw skipped: " + draw_skipped_reason)

            texture_override_component.append("endif")
            texture_override_component.new_line()

        ini_builder.append_section(texture_override_component)

    def add_resource_buffer(self, ini_builder: M_IniBuilder, draw_ib_model: DrawIBModelWWMI):
        """Buffer resource declarations of one DrawIB.

        Buffer files live in the Buffers subfolder; INI lines carry the prefix.
        Every resource is DrawIB scoped: two DrawIBs of the same mod would
        otherwise declare the same section name and every draw call of the mod
        would read whichever file happened to be parsed first.
        """
        draw_ib = draw_ib_model.draw_ib
        resource_buffer_section = M_IniSection(M_SectionType.ResourceBuffer)

        resource_buffer_section.append(scoped_section("ResourceIndexBuffer", draw_ib))
        resource_buffer_section.append("type = Buffer")
        resource_buffer_section.append("format = DXGI_FORMAT_R32_UINT")
        resource_buffer_section.append("stride = 12")
        resource_buffer_section.append("filename = " + GlobalConfig.ini_buffer_filename(draw_ib + "-Component1.buf"))
        resource_buffer_section.new_line()

        for category_name, category_stride in draw_ib_model.d3d11_game_type.CategoryStrideDict.items():
            resource_buffer_section.append(scoped_section("Resource" + category_name + "Buffer", draw_ib))
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
            resource_buffer_section.append("filename = " + GlobalConfig.ini_buffer_filename(draw_ib + "-" + category_name + ".buf"))
            resource_buffer_section.new_line()

            if category_name == D3D11Category.BLEND and draw_ib_model.blend_remap:
                resource_buffer_section.append(scoped_section("ResourceBlendBufferNoStride", draw_ib))
                resource_buffer_section.append("type = Buffer")
                resource_buffer_section.append("format = DXGI_FORMAT_R8_UINT")
                resource_buffer_section.append("filename = " + GlobalConfig.ini_buffer_filename(draw_ib + "-" + category_name + ".buf"))
                resource_buffer_section.new_line()

        if draw_ib_model.blend_remap:
            resource_buffer_section.append(scoped_section("ResourceBlendRemapVertexVGBuffer", draw_ib))
            resource_buffer_section.append("type = Buffer")
            resource_buffer_section.append("format = DXGI_FORMAT_R16_UINT")
            resource_buffer_section.append("filename = " + GlobalConfig.ini_buffer_filename(draw_ib + "-BlendRemapVertexVG.buf"))
            resource_buffer_section.new_line()

            resource_buffer_section.append(scoped_section("ResourceBlendRemapForwardBuffer", draw_ib))
            resource_buffer_section.append("type = Buffer")
            resource_buffer_section.append("format = DXGI_FORMAT_R16_UINT")
            resource_buffer_section.append("filename = " + GlobalConfig.ini_buffer_filename(draw_ib + "-BlendRemapForward.buf"))
            resource_buffer_section.new_line()

            resource_buffer_section.append(scoped_section("ResourceBlendRemapReverseBuffer", draw_ib))
            resource_buffer_section.append("type = Buffer")
            resource_buffer_section.append("format = DXGI_FORMAT_R16_UINT")
            resource_buffer_section.append("filename = " + GlobalConfig.ini_buffer_filename(draw_ib + "-BlendRemapReverse.buf"))
            resource_buffer_section.new_line()

        # A category dumped from a shader resource slot cannot be bound as a
        # plain buffer: a resource view has to name its element format and width.
        # The element view is declared per shader slot category, and the texcoord
        # record additionally declares the half2 width, so the switch in the
        # command list can select it in game without a new export.
        for category_name in self.get_srv_category_names(draw_ib_model):
            view_format, view_stride = get_srv_view_layout(draw_ib_model.d3d11_game_type, category_name)
            if not view_format or not view_stride:
                # Nothing to describe, the category has no element.
                continue
            buffer_filename = GlobalConfig.ini_buffer_filename(draw_ib + "-" + category_name + ".buf")

            resource_buffer_section.append(scoped_section("Resource" + category_name + "BufferSrv", draw_ib))
            resource_buffer_section.append("type = Buffer")
            resource_buffer_section.append("format = " + view_format)
            resource_buffer_section.append("stride = " + str(view_stride))
            resource_buffer_section.append("filename = " + buffer_filename)
            resource_buffer_section.new_line()

            if category_name == D3D11Category.TEXCOORD and view_format != HALF2_FORMAT:
                resource_buffer_section.append(
                    scoped_section("Resource" + category_name + "BufferSrvHalf2", draw_ib)
                )
                resource_buffer_section.append("type = Buffer")
                resource_buffer_section.append("format = " + HALF2_FORMAT)
                resource_buffer_section.append("stride = 4")
                resource_buffer_section.append("filename = " + buffer_filename)
                resource_buffer_section.new_line()

        resource_buffer_section.append(scoped_section("ResourceShapeKeyOffsetBuffer", draw_ib))
        resource_buffer_section.append("type = Buffer")
        resource_buffer_section.append("format = DXGI_FORMAT_R32G32B32A32_UINT")
        resource_buffer_section.append("stride = 16")
        resource_buffer_section.append("filename = " + GlobalConfig.ini_buffer_filename(draw_ib + "-ShapeKeyOffset.buf"))
        resource_buffer_section.new_line()

        resource_buffer_section.append(scoped_section("ResourceShapeKeyVertexIdBuffer", draw_ib))
        resource_buffer_section.append("type = Buffer")
        resource_buffer_section.append("format = DXGI_FORMAT_R32_UINT")
        resource_buffer_section.append("stride = 4")
        resource_buffer_section.append("filename = " + GlobalConfig.ini_buffer_filename(draw_ib + "-ShapeKeyVertexId.buf"))
        resource_buffer_section.new_line()

        resource_buffer_section.append(scoped_section("ResourceShapeKeyVertexOffsetBuffer", draw_ib))
        resource_buffer_section.append("type = Buffer")
        resource_buffer_section.append("format = DXGI_FORMAT_R16_FLOAT")
        resource_buffer_section.append("stride = 2")
        resource_buffer_section.append("filename = " + GlobalConfig.ini_buffer_filename(draw_ib + "-ShapeKeyVertexOffset.buf"))
        resource_buffer_section.new_line()

        ini_builder.append_section(resource_buffer_section)

    def generate_unreal_vs_config_ini(self):
        """Assemble and validate one INI with all exported geometry scopes."""
        config_ini_builder = M_IniBuilder()
        self.mod_info_sections_written = False
        # Repeated generation on the same exporter must keep activeN stable.
        # Scope numbering is local to this one consolidated mod, not the app.
        GlobalConfig.generated_mod_number = 0
        bone_hashes = set()
        matches = {}
        # Distinct LOD names do not distinguish identical runtime matches.
        # Fail instead of running two incompatible overrides on one draw call.
        for model in self.drawib_drawibmodel_dict.values():
            for component in model.wwmi_info.components:
                match = (model.wwmi_info.vb0_hash.lower(), component.index_offset, component.index_count)
                if match in matches:
                    raise ValueError("WWMI ambiguous component match between " + matches[match] + " and " + model.draw_ib
                                     + "; recapture LODs with distinct VB hashes or index ranges")
                matches[match] = model.draw_ib

        for draw_ib, draw_ib_model in self.drawib_drawibmodel_dict.items():
            self.add_constants_section(ini_builder=config_ini_builder, draw_ib_model=draw_ib_model)
            self.add_present_section(ini_builder=config_ini_builder, draw_ib_model=draw_ib_model)
            self.add_commandlist_register_mod_section(ini_builder=config_ini_builder, draw_ib_model=draw_ib_model)
            blend_remap.add_commandlist_update_merged_skeleton(ini_builder=config_ini_builder, draw_ib_model=draw_ib_model)
            blend_remap.add_blend_remap_sections(ini_builder=config_ini_builder, draw_ib_model=draw_ib_model)
            self.add_resource_mod_info_section_default(ini_builder=config_ini_builder, draw_ib_model=draw_ib_model)
            # A bone filter is a hash marker, not a geometry override.
            # Emit one marker for shared hashes instead of overlapping filters.
            if draw_ib_model.wwmi_info.cb4_hash not in bone_hashes:
                self.add_texture_override_mark_bone_data_cb(ini_builder=config_ini_builder, draw_ib_model=draw_ib_model)
                bone_hashes.add(draw_ib_model.wwmi_info.cb4_hash)
            blend_remap.add_commandlist_merge_skeleton_section(ini_builder=config_ini_builder, draw_ib_model=draw_ib_model)
            self.add_commandlist_trigger_shared_cleanup_section(ini_builder=config_ini_builder, draw_ib_model=draw_ib_model)
            self.add_texture_override_component(ini_builder=config_ini_builder, draw_ib_model=draw_ib_model)
            shapekeys.add_texture_override_shapekeys(ini_builder=config_ini_builder, draw_ib_model=draw_ib_model)
            shapekeys.add_resource_shapekeys(ini_builder=config_ini_builder, draw_ib_model=draw_ib_model)
            shapekeys.add_wwmi_shapekey_sections(ini_builder=config_ini_builder, draw_ib_model=draw_ib_model)

            if MIMIGlobalProperties.import_merged_vgmap() == 'MERGED':
                blend_remap.add_resource_merged_skeleton(ini_builder=config_ini_builder, draw_ib_model=draw_ib_model)

            self.add_resource_buffer(ini_builder=config_ini_builder, draw_ib_model=draw_ib_model)

            # Assign an active flag once per scope, then declare all flags
            # together after the loop so no key/global is redeclared.
            GlobalConfig.generated_mod_number += 1
            M_IniHelper.move_slot_style_textures(draw_ib_model=draw_ib_model)
            M_IniHelper.add_object_texture_binding_resource_sections(
                ini_builder=config_ini_builder, draw_ib_model=draw_ib_model)

        # Public branch keys and automatic textures describe the entire mod.
        # Running these helpers per model repeats both names and copy work.
        M_IniHelper.add_branch_key_sections(
            ini_builder=config_ini_builder, key_name_mkey_dict=self.blueprint_model.keyname_mkey_dict)
        global_hash_rows = getattr(self.blueprint_model, "global_hash_texture_binding_list", [])
        M_IniHelper.generate_hash_style_texture_ini(
            ini_builder=config_ini_builder, drawib_drawibmodel_dict=self.drawib_drawibmodel_dict,
            global_hash_texture_binding_list=global_hash_rows, guard_with_object_detected=True)
        M_IniHelper.generate_shared_slot_style_texture_ini(
            ini_builder=config_ini_builder, drawib_drawibmodel_dict=self.drawib_drawibmodel_dict)
        M_IniHelper.generate_hash_style_global_texture_ini(
            ini_builder=config_ini_builder, global_hash_texture_binding_list=global_hash_rows,
            drawib_drawibmodel_dict=self.drawib_drawibmodel_dict)
        M_IniHelper.generate_hash_style_object_texture_ini(
            ini_builder=config_ini_builder, drawib_drawibmodel_dict=self.drawib_drawibmodel_dict,
            global_hash_texture_binding_list=global_hash_rows)
        for model in self.drawib_drawibmodel_dict.values():
            # Explicit replacements must win over automatically copied originals.
            M_IniHelper.move_object_texture_binding_files(draw_ib_model=model)

        # Deferred reset keeps the texture guard active for the full frame.
        present = M_IniSection(M_SectionType.Present)
        present.append("post $object_detected = 0")
        config_ini_builder.append_section(present)
        validate_ini_builder(config_ini_builder)
        # Old generated files would still be loaded by 3Dmigoto beside the
        # consolidated file. Disable only verifiably unchanged owned outputs.
        # Include raw hashes because previous versions did not scope by LOD.
        legacy_scopes = list(self.drawib_drawibmodel_dict)
        legacy_scopes.extend(getattr(model, "source_draw_ib", model.draw_ib)
                             for model in self.drawib_drawibmodel_dict.values())
        disable_legacy_ini_files(GlobalConfig.path_generate_mod_folder(),
                                 GlobalConfig.get_generated_mod_name(), legacy_scopes)
        filename = GlobalConfig.get_generated_mod_name() + ".ini"
        config_ini_builder.save_to_file_not_reorder(
            os.path.join(GlobalConfig.path_generate_mod_folder(), filename))

    def export(self):
        # Skip Draw is checked before any buffer or INI is written, so a mixed
        # or unsupported combination never leaves a half-updated Mod on disk.
        from ...common.skip_draw import validate_skip_draw
        validate_skip_draw(list(self.drawib_drawibmodel_dict.values()))
        # Validate all native shape dispatches before overwriting any buffer.
        # A bad second DrawIB must not leave a half-updated Mod on disk.
        # Missing metadata remains an error, never a reason to drop shape keys.
        for draw_ib_model in self.drawib_drawibmodel_dict.values():
            batches = shapekeys.get_wwmi_shapekey_batches(draw_ib_model)
            if batches and not draw_ib_model.wwmi_info.shapekeys.offsets_hash:
                raise ValueError("WWMI native shape keys require the original offsets hash before export.")
        for draw_ib_model in self.drawib_drawibmodel_dict.values():
            draw_ib_model.write_buffer_files()
        self.generate_unreal_vs_config_ini()
