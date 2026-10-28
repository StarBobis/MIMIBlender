'''
Slot Texture Bind blueprint node (per-object texture slot binding).

A transparent pass-through node: Object in, Object out. Every object that
passes through it gets its texture slots replaced right before its own
drawindexed line, so two objects of the same Submesh can use different
textures under different switch states.

The node can expose several pass-through channels. Channel N is input N plus
output N (see texture_bind_channels.py), and every channel shares the same
rows, so one node replaces the texture of several parts without the user
typing the rows once per part.

3Dmigoto facts backing this design:
- A texture slot assignment (e.g. "ps-t0 = ResourceXXX") inside a
  TextureOverride section stays in effect until another assignment changes
  it, so writing the binding immediately before the drawindexed call is
  the correct "replace only for this draw" pattern.
- The "ref" keyword captures the currently bound resource
  ("bak = ref ps-t0"), the same trick the SnowBreak exporter already uses
  to back up the index buffer; it allows restoring the original texture
  after the draw when the user enables "Restore After Draw".
- Resource sections are plain "[ResourceXXX] filename = ..." blocks; the
  exporter deduplicates them by resource name.

Texture sources:
- MARK:     reuse a texture marked in SSMT5 (TextureMarkUpInfoList of the
            Submesh). The row may also carry its own replacement image, which
            is what gives two objects of one Submesh two different pictures on
            the same slot; without one it reuses the Submesh-wide mark.
- FILE:     an external image file (dds/png/...). The exporter copies it
            into the generated mod and emits a dedicated resource section.
- RESOURCE: an already existing resource name (advanced users who share
            one resource between several objects).

Every row binds right before one drawindexed call, so the same node can be
wired into different Switch Key states (copy the Object Info node per state)
and each state then shows its own picture.
'''
import re
import time

import bpy
from bpy.types import PropertyGroup

from ..i18n.i18n import I18nOperator, tr, translatable
from .blueprint_node_base import MIMINodeBase
from ..common.global_config import GlobalConfig
from ..common.gimi_texture_slots import get_gimi_texture_slot
from ..common.texture_output_naming import (
    file_resource_stem,
    normalize_alias_stem,
    shared_slot_output_filename,
)
from .texture_format_widgets import (
    DEFAULT_MANUAL_FORMAT as _DEFAULT_MANUAL_FORMAT,
    color_space_items as _color_space_items,
    draw_convert_all as _draw_convert_all,
    draw_node_progress as _draw_node_progress,
    draw_row_controls as _draw_row_controls,
    format_mode_items as _format_mode_items,
    manual_format_items as _manual_format_items,
    predicted_suffix,
)
from .texture_output_widgets import (
    alias_suffix_note,
    display_suffix,
    draw_file_missing_warning,
    draw_generated_name,
    draw_rename_box,
    first_hint,
    upstream_draw_ib_hints,
    upstream_submesh_names,
)
# Channel socket pairs and their operators are shared with the Hash variant.
from .texture_bind_channels import channel_count, draw_channel_controls

# 3Dmigoto texture slot syntax: shader stage (ps/vs/gs/hs/ds/cs) + binding
# type (t/s/b/u) + register number, written lowercase by convention.
_SLOT_PATTERN = re.compile(r"^(ps|vs|gs|hs|ds|cs)-(t|s|b|u)\d+$")

# Placeholder identifier of the mark name dropdown. Blender enum identifiers
# must not be empty strings, otherwise RNA falls back to the numeric index
# and the stored value stops round-tripping ("current value '0' matches no
# enum" warning).
_MARK_NAME_NONE = "(none)"


def _gimi_mark_slot(item):
    """Known GIMI marks use the package API; all other sources stay physical."""
    if GlobalConfig.logic_name == "GIMI" and getattr(item, "source_type", "") == "MARK":
        return get_gimi_texture_slot(getattr(item, "mark_name", ""))
    return None


def _texture_slot_item_refresh_display(item):
    '''Rebuild the one-line display name shown inside the list widget.'''
    source_type = str(getattr(item, "source_type", "") or "")
    if source_type == 'MARK':
        source = mark_name_of(item) or "?"
        # A row with its own image differs from the plain mark reuse, so the
        # list has to reveal that difference without opening the row.
        replacement_image = bpy.path.basename(str(getattr(item, "mark_file_path", "") or "").strip())
        if replacement_image:
            source = source + " + " + replacement_image
    elif source_type == 'FILE':
        source = bpy.path.basename(str(getattr(item, "file_path", "") or "").strip()) or "?"
    else:
        source = str(getattr(item, "resource_name", "") or "").strip() or "?"
    # Known GIMI MARK rows target an API semantic, not the captured ps-t slot.
    logical_slot = _gimi_mark_slot(item)
    restore_suffix = " (+restore)" if getattr(item, "restore_after_draw", False) and not logical_slot else ""
    # A row the user renamed shows its new file name, so the list itself
    # already tells which binding owns which generated texture.
    alias_stem = normalize_alias_stem(getattr(item, "output_name", ""))
    alias_suffix = " -> " + alias_stem if alias_stem else ""
    item.name = "{slot} <- {source}{suffix}{alias}".format(
        slot=logical_slot or str(getattr(item, "slot", "") or "").strip() or "?",
        source=source,
        suffix=restore_suffix,
        alias=alias_suffix,
    )


class MIMITextureSlotItem(PropertyGroup):
    '''One texture slot binding row of a Texture Bind node.'''
    name: bpy.props.StringProperty(name=tr("Binding"), default="") # type: ignore

    enabled: bpy.props.BoolProperty(
        name=tr("Enabled"),
        description=tr("Disabled rows are skipped at export time"),
        default=True,
        update=lambda self, context: _texture_slot_item_refresh_display(self),
    ) # type: ignore

    slot: bpy.props.StringProperty(
        name=tr("Slot"),
        description=tr("Texture slot to replace right before this object's drawindexed, e.g. ps-t0"),
        default="ps-t0",
        update=lambda self, context: _texture_slot_item_refresh_display(self),
    ) # type: ignore

    source_type: bpy.props.EnumProperty(
        name=tr("Source"),
        description=tr("Where the replacement texture comes from"),
        items=[
            ('MARK', tr("Marked Texture"), tr("Reuse a texture marked in the SSMT5 texture mark page of this Submesh, and optionally give this object its own image for that slot")),
            ('FILE', tr("External File"), tr("Copy an external image file into the generated mod; the slot is typed by hand")),
            ('RESOURCE', tr("Existing Resource"), tr("Reference an existing [ResourceXXX] section by name")),
        ],
        default='MARK',
        update=lambda self, context: _texture_slot_item_refresh_display(self),
    ) # type: ignore

    mark_name: bpy.props.EnumProperty(
        name=tr("Mark Name"),
        description=tr("Semantic mark name from the SSMT5 texture mark page; resolved against the Submesh of the upstream object. Picking one fills the slot automatically"),
        items=lambda self, context: _texture_bind_mark_name_items(self),
        update=lambda self, context: _texture_slot_item_mark_changed(self),
    ) # type: ignore

    mark_name_value: bpy.props.StringProperty(
        name=tr("Stored Mark Name"),
        description=tr("Durable mark identity written by the dropdown above. It keeps the row bound to the same mark even when the mark list order changes, which an enum value alone cannot do"),
        default="",
    ) # type: ignore

    file_path: bpy.props.StringProperty(
        name=tr("Texture File"),
        description=tr("Image file (dds, png, jpg, bmp or tga) copied into the generated mod at export time"),
        subtype='FILE_PATH',
        default="",
        update=lambda self, context: _texture_slot_item_refresh_display(self),
    ) # type: ignore

    mark_file_path: bpy.props.StringProperty(
        name=tr("Replacement Image"),
        description=tr("Image that replaces the marked texture for this object only. Leave empty to reuse the marked image shared by the whole Submesh; pick a file to give two objects of one Submesh two different pictures on the same slot, which is what a key switch needs"),
        subtype='FILE_PATH',
        default="",
        update=lambda self, context: _texture_slot_item_refresh_display(self),
    ) # type: ignore

    resource_name: bpy.props.StringProperty(
        name=tr("Resource Name"),
        description=tr("Name of an existing [ResourceXXX] section, e.g. ResourceMySharedTexture"),
        default="",
        update=lambda self, context: _texture_slot_item_refresh_display(self),
    ) # type: ignore

    format_mode: bpy.props.EnumProperty(
        name=tr("Format Source"),
        description=tr("Auto follows the format of the captured original texture; Manual applies the format selected below when no original can be resolved"),
        items=_format_mode_items,
        # Blender only accepts an integer default when ``items`` is a callback;
        # index 0 is the 'AUTO' entry the callback returns first.
        default=0,
        update=lambda self, context: _texture_slot_item_refresh_display(self),
    ) # type: ignore

    manual_format: bpy.props.EnumProperty(
        name=tr("Target Format"),
        description=tr("DXGI format written by texconv when the format source is Manual"),
        items=_manual_format_items,
        # Same rule: a callback based enum list requires an integer index.
        default=0,
    ) # type: ignore

    force_original_size: bpy.props.BoolProperty(
        name=tr("Force Original Resolution"),
        description=tr("Resize the replacement to the captured texture resolution instead of keeping its own size"),
        default=False,
    ) # type: ignore

    color_space: bpy.props.EnumProperty(
        name=tr("Color Space"),
        description=tr("How the replacement's pixels are interpreted. Auto follows the source file format and the mark role (normal/mask roles are data); the target format always follows the original texture"),
        items=_color_space_items,
        # Callback based enum lists persist an integer index; keep the item
        # order stable or old rows would silently change their meaning.
        default=0,
    ) # type: ignore

    output_name: bpy.props.StringProperty(
        name=tr("Rename To"),
        description=tr("Leave empty to keep the generated file name shown above; fill in to rename the generated texture file (the image format suffix stays)"),
        default="",
        update=lambda self, context: _texture_slot_item_refresh_display(self),
    ) # type: ignore

    restore_after_draw: bpy.props.BoolProperty(
        name=tr("Restore After Draw"),
        description=tr("Capture the original texture with ref before the draw and bind it back after drawindexed; needed when a later draw must see the original texture again"),
        default=False,
        update=lambda self, context: _texture_slot_item_refresh_display(self),
    ) # type: ignore


def _find_owner_bind_node(item):
    '''Find the Texture Bind node that owns the given collection item.'''
    tree = getattr(item, "id_data", None)
    if tree is None:
        return None
    for node in getattr(tree, "nodes", []):
        if getattr(node, "bl_idname", "") != 'MIMINode_Texture_Bind':
            continue
        for candidate in getattr(node, "texture_slot_items", []):
            if candidate.as_pointer() == item.as_pointer():
                return node
    return None


def _resolve_upstream_submesh_name(node, depth=0):
    '''Find the first enabled upstream source, respecting list/group ports.'''
    # The old Object-Info-only traversal left marked-texture dropdowns empty
    # when an Object List or custom group fed the binding node.
    from .blueprint_graph import iter_object_sources
    for source in iter_object_sources(node):
        submesh_name = str(getattr(source, "submesh_name", "") or "").strip()
        object_name = str(getattr(source, "object_name", "") or "").strip()
        if submesh_name or object_name:
            return submesh_name or object_name
    return ""


# Nodes that only forward objects unchanged. The switch state readout walks
# through them, because a binding is often placed above or below a Group.
_SWITCH_STATE_PASS_THROUGH = (
    'NodeReroute',
    'MIMINode_Object_Group',
    'MIMINode_Texture_Bind',
    'MIMINode_Hash_Texture_Bind',
)


def _find_switch_state(start_sockets, depth_limit=12):
    """Walk downstream from output sockets to the nearest Switch Key input.

    Returns ``(key, alias, state_index, state_count)`` or an empty tuple.
    Starting from sockets instead of a node is what lets a multi-channel
    binding node report the state of every channel separately.
    """
    visited = set()
    pending = list(start_sockets)
    steps = 0
    while pending and steps <= depth_limit:
        steps += 1
        current = pending.pop(0)
        for link in getattr(current, "links", []):
            target = link.to_node
            if target is None:
                continue
            pointer = target.as_pointer()
            if pointer in visited:
                continue
            visited.add(pointer)
            if getattr(target, "bl_idname", "") == 'MIMINode_SwitchKey':
                sockets = list(target.inputs)
                if link.to_socket not in sockets:
                    continue
                return (
                    str(getattr(target, "key_name", "") or "").strip(),
                    str(getattr(target, "key_alias", "") or "").strip(),
                    sockets.index(link.to_socket),
                    len(sockets),
                )
            if getattr(target, "bl_idname", "") in _SWITCH_STATE_PASS_THROUGH:
                # Pass-through nodes forward with all of their own outputs.
                pending.extend(list(getattr(target, "outputs", []) or []))
    return ()


def downstream_switch_state(node, depth_limit=12):
    '''Return ``(key, alias, state_index, state_count)`` of the nearest Switch Key.

    A texture binding only takes effect in the state its object is drawn in, so
    the node shows that state instead of leaving the wiring invisible.  An empty
    tuple means no Switch Key follows this node, so the binding always applies.
    '''
    return _find_switch_state(getattr(node, "outputs", []) or [], depth_limit)


def switch_state_text(state):
    """Return the one-line description of one switch state tuple."""
    if not state:
        return tr("Not inside a key switch: the bindings always apply")
    key_name, key_alias, state_index, state_count = state
    text = tr("Key switch {key}: state {state} of {count}").format(
        key=key_name or tr("(no key set)"), state=state_index + 1, count=state_count,
    )
    if key_alias:
        text = text + "  ($" + key_alias.lower() + ")"
    return text


def draw_switch_state(layout, node):
    '''Draw which key switch state the bindings of this node belong to.

    With more than one channel every output can feed a different switch state,
    so the node lists them instead of pretending there is a single state.
    '''
    if channel_count(node) <= 1:
        state = downstream_switch_state(node)
        layout.label(
            text=switch_state_text(state),
            icon='DRIVER' if state else 'BLANK1',
        )
        return
    for index, output in enumerate(getattr(node, "outputs", []) or []):
        if not output.is_linked:
            detail = tr("Channel output not connected")
        else:
            detail = switch_state_text(_find_switch_state([output]))
        layout.label(
            text=tr("Channel {index}: {detail}").format(index=index + 1, detail=detail),
            icon='DRIVER',
        )


def _load_submesh_mark_dicts(submesh_name, dedupe_names=True):
    '''Texture marks of one Submesh as normalized plain dicts.

    Shared by the mark dropdowns, the auto-fill operators and the
    pick-a-mark update callbacks, so all of them agree on the workspace
    format. Returns [] when the Submesh JSON is missing or has no marks.
    '''
    if not submesh_name:
        return []
    # Imported here so a missing workspace never breaks the node UI.
    from ..workspace.submesh_json import SubmeshJson
    from ..workspace.mmt_workspace import MMTWorkSpace
    submesh_json = SubmeshJson(MMTWorkSpace.check_and_get_submesh_json_path(submesh_name))
    mark_dict_list = []
    seen_names = set()
    for raw_mark in submesh_json.TextureMarkUpInfoList:
        if isinstance(raw_mark, dict):
            mark_name = str(raw_mark.get("MarkName", "") or "").strip()
            mark_dict = {
                "name": mark_name,
                "type": str(raw_mark.get("MarkType", "") or "").strip(),
                "slot": str(raw_mark.get("MarkSlot", "") or "").strip().lower(),
                "hash": str(raw_mark.get("MarkHash", "") or "").strip().lower(),
                "filename": str(raw_mark.get("MarkFileName", "") or "").strip(),
            }
        else:
            mark_name = str(getattr(raw_mark, "MarkName", "") or "").strip()
            mark_dict = {
                "name": mark_name,
                "type": str(getattr(raw_mark, "MarkType", "") or "").strip(),
                "slot": str(getattr(raw_mark, "MarkSlot", "") or "").strip().lower(),
                "hash": str(getattr(raw_mark, "MarkHash", "") or "").strip().lower(),
                "filename": str(getattr(raw_mark, "MarkFileName", "") or "").strip(),
            }
        normalized = mark_name.lower()
        # Conditional dropdowns identify marks by name; the global scanner
        # identifies them by hash and must also see repeated semantic names.
        if not mark_name or (dedupe_names and normalized in seen_names):
            continue
        seen_names.add(normalized)
        mark_dict_list.append(mark_dict)
    return mark_dict_list


def _find_submesh_mark_by_name(item, find_owner_node):
    '''Locate the mark dict matching the row's mark name ("" when missing).'''
    try:
        mark_name = mark_name_of(item)
        if not mark_name:
            return None
        node = find_owner_node(item)
        submesh_name = _resolve_upstream_submesh_name(node)
        if not submesh_name:
            return None
        for mark_dict in _load_submesh_mark_dicts(submesh_name):
            if mark_dict["name"].lower() == mark_name.lower():
                return mark_dict
    except Exception:
        # Dropdown and callback lookups must never break the node editor.
        pass
    return None


def _texture_slot_item_mark_changed(item):
    '''Picking a mark fills the slot from the mark's own MarkSlot value.'''
    # Persist the identifier itself before anything reads the row: the enum
    # index is only a position in the current dropdown list.
    item.mark_name_value = normalize_mark_name_enum_value(getattr(item, "mark_name", ""))
    mark_dict = _find_submesh_mark_by_name(item, _find_owner_bind_node)
    if mark_dict and mark_dict["slot"]:
        item.slot = mark_dict["slot"]
    _texture_slot_item_refresh_display(item)


# Reading the marks of a Submesh opens a JSON file, and Blender redraws a node
# on every mouse move, so the preview keeps a very short cache instead of
# hitting the disk dozens of times per second.
_MARK_DICT_CACHE = {}
_MARK_DICT_CACHE_TTL_SECONDS = 2.0
_MARK_DICT_CACHE_LIMIT = 16


def invalidate_mark_cache():
    '''Drop the cached marks; a Refresh / Auto Fill press means the data changed.'''
    _MARK_DICT_CACHE.clear()


def _cached_submesh_mark_dicts(submesh_name):
    '''Return the mark dicts of one Submesh, cached for the node preview.'''
    name = str(submesh_name or "").strip()
    if not name:
        return []
    now = time.monotonic()
    cached = _MARK_DICT_CACHE.get(name)
    if cached is not None and now - cached[0] < _MARK_DICT_CACHE_TTL_SECONDS:
        return cached[1]
    try:
        mark_dict_list = _load_submesh_mark_dicts(name)
    except Exception:
        # A missing or half-written Submesh JSON must not break the node.
        mark_dict_list = []
    if len(_MARK_DICT_CACHE) >= _MARK_DICT_CACHE_LIMIT:
        _MARK_DICT_CACHE.clear()
    _MARK_DICT_CACHE[name] = (now, mark_dict_list)
    return mark_dict_list


def _slot_row_output_name(node, item):
    '''Return how one Slot Texture Bind row names its generated file.

    The result is ``(generated_name, suffix, suffix_is_certain, can_rename,
    disabled_reason)``.  ``generated_name`` is the exact name the export writes
    while the alias field is empty; every part of it comes from the same helper
    the exporter calls, so the node can never show a name that export ignores.
    '''
    # Known GIMI marks are submitted to the game API by name; no file exists.
    if _gimi_mark_slot(item):
        return (
            "", ".dds", True, False,
            tr("GIMI submits this slot by name, so no texture file is generated"),
        )

    source_type = str(getattr(item, "source_type", "") or "")
    object_name, draw_ib = first_hint(upstream_draw_ib_hints(node))
    slot_token = str(getattr(item, "slot", "") or "").strip().lower().replace("-", "_") or "texture"

    if source_type == 'FILE':
        source_path = str(getattr(item, "file_path", "") or "").strip()
        # The preview must show the converted .dds name whenever a capture is
        # resolved, so it asks the same lookup the status line uses.
        suffix, suffix_is_certain = predicted_suffix(node, item, source_path)
        return file_resource_stem(draw_ib, object_name, slot_token) + suffix, suffix, suffix_is_certain, True, ""

    if source_type == 'MARK':
        mark_name = mark_name_of(item)
        submesh_name = _resolve_upstream_submesh_name(node)
        matched_mark = None
        for mark_dict in _cached_submesh_mark_dicts(submesh_name):
            if mark_dict["name"].lower() == mark_name.lower():
                matched_mark = mark_dict
                break
        replacement_path = str(getattr(item, "mark_file_path", "") or "").strip()
        if not mark_name or matched_mark is None:
            # A row may already own an image before a mark is picked; the file
            # is then named after the object and the slot like any other copy.
            if replacement_path:
                suffix, suffix_is_certain = predicted_suffix(node, item, replacement_path)
                return file_resource_stem(draw_ib, object_name, slot_token) + suffix, suffix, suffix_is_certain, True, ""
            # Nothing is generated before the user picks a mark.
            return "", ".dds", True, True, tr("Pick a marked texture to see the generated file name")
        if replacement_path:
            # The row owns this image, so the export copies it into the Mod
            # instead of pointing at the mark's shared resource.
            suffix, suffix_is_certain = predicted_suffix(node, item, replacement_path)
            return file_resource_stem(draw_ib, object_name, slot_token) + suffix, suffix, suffix_is_certain, True, ""
        # A shared marked texture keeps the hash name and already owns a
        # [Resource...] section, so this row reuses it without a new file.
        if str(matched_mark.get("type", "")) == "SharedSlot":
            generated_name = shared_slot_output_filename(matched_mark.get("hash", ""), matched_mark["name"])
            suffix, suffix_is_certain = display_suffix(
                getattr(item, "format_mode", "AUTO"), matched_mark.get("filename", ""),
            )
            return generated_name, suffix, suffix_is_certain, True, ""
        # A plain Slot mark is bound by file name and declares no resource
        # section, so an object scoped row copies the marked image and names it
        # after the object and the slot. The copy always ends up as a DDS.
        return file_resource_stem(draw_ib, object_name, slot_token) + ".dds", ".dds", True, True, ""

    # Anything else references an existing resource and creates no file.
    return (
        "", ".dds", True, False,
        tr("This row reuses an existing resource, so no texture file is generated"),
    )


def _selected_mark_type(node, item):
    '''Return the mark type (Slot / SharedSlot / Hash) picked on one row.

    The node explains what an empty replacement image means, which depends on
    whether the mark owns a shared [Resource...] section or is bound by file
    name.  An unresolvable mark keeps the plain reuse wording.
    '''
    mark_name = mark_name_of(item)
    if not mark_name:
        return ""
    try:
        for mark_dict in _cached_submesh_mark_dicts(_resolve_upstream_submesh_name(node)):
            if str(mark_dict.get("name", "")).lower() == mark_name.lower():
                return str(mark_dict.get("type", "") or "")
    except Exception:
        # A half-built graph must never break node drawing.
        return ""
    return ""


def _mark_missing_submeshes(node, item):
    '''Return the upstream Submeshes that do not contain this row's mark.

    A node with several channels can feed objects of several Submeshes, while a
    mark name only exists in the Submesh that was marked. The export resolves
    the mark per object, so the objects of the other Submeshes would fail late;
    reporting the gap next to the row makes the channel wiring safe to build.
    A single-Submesh node returns nothing: its one Submesh is already validated
    by the export message and by the empty dropdown.
    '''
    if str(getattr(item, "source_type", "") or "") != 'MARK':
        return []
    wanted = mark_name_of(item).lower()
    if not wanted:
        return []
    submesh_names = upstream_submesh_names(node)
    if len(submesh_names) < 2:
        # One Submesh means one owner; there is nothing to compare.
        return []
    missing = []
    for submesh_name in submesh_names:
        mark_dict_list = _cached_submesh_mark_dicts(submesh_name)
        if not any(str(mark_dict.get("name", "") or "").lower() == wanted for mark_dict in mark_dict_list):
            missing.append(submesh_name)
    return missing


def _draw_image_format_controls(box, node, item, index, tree):
    '''Draw the exact-format controls shared by file and mark-image rows.'''
    # Auto matches the captured original; Manual is the explicit fallback for
    # slots that have no capture to match.
    format_row = box.row(align=True)
    format_row.prop(item, "format_mode", text="")
    if str(item.format_mode) == 'MANUAL':
        format_row.prop(item, "manual_format", text="")
    box.prop(item, "force_original_size")
    # Colour-space interpretation: AUTO derives it from the source format and
    # the mark role; a mis-tagged DDS can be corrected per row.
    box.prop(item, "color_space")
    # Detected original format, readiness and the per-row Convert button.
    _draw_row_controls(box, node, item, index, tree)


def _texture_bind_mark_name_items(item):
    '''Enum items for the mark name dropdown: marks of the upstream Submeshes.

    A node with several channels can feed objects of several Submeshes, so the
    dropdown lists the union of their marks. A name that exists in more than one
    Submesh is offered once; the export resolves it against the Submesh of each
    object, which is where the real mark lives.
    '''
    empty_items = [(_MARK_NAME_NONE, "(" + tr("none") + ")", "")]
    try:
        node = _find_owner_bind_node(item)
        submesh_names = upstream_submesh_names(node)
        if not submesh_names:
            # Fall back to the single lookup for older graphs the helper cannot
            # walk; it resolves the same value as before.
            first_name = _resolve_upstream_submesh_name(node)
            submesh_names = [first_name] if first_name else []
        if not submesh_names:
            return empty_items
        items = list(empty_items)
        seen_names = set()
        for submesh_name in submesh_names:
            for mark_dict in _load_submesh_mark_dicts(submesh_name):
                normalized = str(mark_dict["name"] or "").strip().lower()
                if not normalized or normalized in seen_names:
                    continue
                seen_names.add(normalized)
                items.append((mark_dict["name"], mark_dict["name"], ""))
        return items if len(items) > 1 else empty_items
    except Exception:
        # Never let a dropdown lookup break the node editor drawing.
        return empty_items


def normalize_mark_name_enum_value(value):
    '''Map the dropdown placeholder back to an empty mark name at export.'''
    text = str(value or "").strip()
    return "" if text == _MARK_NAME_NONE else text


def mark_name_of(item):
    '''Return the durable mark name of one row, migrating legacy enum values.

    Blender persists an EnumProperty as an integer index. An old row therefore
    silently changed meaning whenever the mark list order changed (extract,
    re-mark, workspace switch), which is the "the generated texture is not the
    one I specified" report. ``mark_name_value`` stores the identifier itself;
    the enum stays only as the picker. The first read of an old row copies the
    still-valid enum identifier into the string field.
    '''
    value = str(getattr(item, "mark_name_value", "") or "").strip()
    if value:
        return value
    legacy = normalize_mark_name_enum_value(getattr(item, "mark_name", ""))
    if legacy:
        try:
            item.mark_name_value = legacy
        except Exception:
            # A read-only stand-in (tests, adapters) still resolves the name.
            pass
        return legacy
    return ""


class MMT_OT_TexBindAddItem(I18nOperator):
    '''Add one texture slot binding row to a Texture Bind node'''
    bl_idname = "mimi.texbind_add_item"
    bl_label = "Add Texture Binding"
    bl_options = {'REGISTER', 'UNDO'}

    node_name: bpy.props.StringProperty() # type: ignore
    tree_name: bpy.props.StringProperty() # type: ignore

    def execute(self, context):
        tree = bpy.data.node_groups.get(self.tree_name) if self.tree_name else None
        # Explicit targets must not fall back to another open blueprint.
        if tree is None and not self.tree_name:
            tree = getattr(context.space_data, "edit_tree", None) or getattr(context.space_data, "node_tree", None)
        if tree is None:
            return {'CANCELLED'}
        node = tree.nodes.get(self.node_name)
        if node is None or getattr(node, "bl_idname", "") != 'MIMINode_Texture_Bind':
            return {'CANCELLED'}
        item = node.texture_slot_items.add()
        # Bake the display name immediately so the new row is not blank.
        _texture_slot_item_refresh_display(item)
        node.texture_slot_index = len(node.texture_slot_items) - 1
        return {'FINISHED'}


class MMT_OT_TexBindRemoveItem(I18nOperator):
    '''Remove the selected texture slot binding row from a Texture Bind node'''
    bl_idname = "mimi.texbind_remove_item"
    bl_label = "Remove Texture Binding"
    bl_options = {'REGISTER', 'UNDO'}

    node_name: bpy.props.StringProperty() # type: ignore
    tree_name: bpy.props.StringProperty() # type: ignore

    def execute(self, context):
        tree = bpy.data.node_groups.get(self.tree_name) if self.tree_name else None
        # Explicit targets must not fall back to another open blueprint.
        if tree is None and not self.tree_name:
            tree = getattr(context.space_data, "edit_tree", None) or getattr(context.space_data, "node_tree", None)
        if tree is None:
            return {'CANCELLED'}
        node = tree.nodes.get(self.node_name)
        if node is None or getattr(node, "bl_idname", "") != 'MIMINode_Texture_Bind':
            return {'CANCELLED'}
        index = int(getattr(node, "texture_slot_index", 0))
        if 0 <= index < len(node.texture_slot_items):
            node.texture_slot_items.remove(index)
            node.texture_slot_index = max(0, min(index, len(node.texture_slot_items) - 1))
        return {'FINISHED'}


class MMT_OT_TexBindAutoFill(I18nOperator):
    '''Add one binding row for every Slot / SharedSlot mark of the upstream Submesh'''
    bl_idname = "mimi.texbind_autofill"
    bl_label = "Auto Fill From Marks"
    bl_options = {'REGISTER', 'UNDO'}

    node_name: bpy.props.StringProperty() # type: ignore
    tree_name: bpy.props.StringProperty() # type: ignore

    def execute(self, context):
        tree = bpy.data.node_groups.get(self.tree_name) if self.tree_name else None
        # Explicit targets must not fall back to another open blueprint.
        if tree is None and not self.tree_name:
            tree = getattr(context.space_data, "edit_tree", None) or getattr(context.space_data, "node_tree", None)
        if tree is None:
            return {'CANCELLED'}
        node = tree.nodes.get(self.node_name)
        if node is None or getattr(node, "bl_idname", "") != 'MIMINode_Texture_Bind':
            return {'CANCELLED'}

        # A multi-channel node can feed objects of several Submeshes, so the
        # rows are collected from every upstream Submesh, each mark once.
        submesh_names = upstream_submesh_names(node)
        if not submesh_names:
            first_name = _resolve_upstream_submesh_name(node)
            submesh_names = [first_name] if first_name else []
        if not submesh_names:
            self.report({'ERROR'}, tr("Upstream Submesh not resolved; set the Submesh on the upstream Object Info node first"))
            return {'CANCELLED'}

        # The user is about to read freshly marked textures; drop the preview
        # cache so the generated names follow the new marks immediately.
        invalidate_mark_cache()

        # Rows already referencing a mark are kept untouched; the operator
        # only appends what is missing, so it is safe to press repeatedly.
        existing_names = set()
        for row_item in node.texture_slot_items:
            if str(row_item.source_type or "") == 'MARK':
                existing_names.add(mark_name_of(row_item).lower())

        added_count = 0
        skipped_count = 0
        for submesh_name in submesh_names:
            try:
                mark_dict_list = _load_submesh_mark_dicts(submesh_name)
            except Exception as error:
                # One unreadable Submesh must not hide the others' marks.
                self.report({'ERROR'}, tr("Failed to read the texture marks of Submesh") + " '" + submesh_name + "': " + str(error))
                continue

            for mark_dict in mark_dict_list:
                if mark_dict["type"] not in ("Slot", "SharedSlot"):
                    continue
                if not mark_dict["name"] or mark_dict["name"].lower() in existing_names:
                    skipped_count += 1
                    continue
                if not mark_dict["slot"]:
                    print("Slot Texture Bind auto fill: mark '" + mark_dict["name"] + "' has no MarkSlot, skipped")
                    skipped_count += 1
                    continue
                row_item = node.texture_slot_items.add()
                row_item.enabled = True
                row_item.slot = mark_dict["slot"]
                row_item.source_type = 'MARK'
                row_item.mark_name = mark_dict["name"]
                row_item.mark_name_value = mark_dict["name"]
                _texture_slot_item_refresh_display(row_item)
                added_count += 1
                existing_names.add(mark_dict["name"].lower())

        node.texture_slot_index = len(node.texture_slot_items) - 1
        self.report({'INFO'}, tr("Auto fill done: {added} row(s) added, {skipped} skipped").format(added=added_count, skipped=skipped_count))
        return {'FINISHED'}


@translatable
class MIMINode_Texture_Bind(MIMINodeBase):
    '''Slot Texture Bind assigns replacement textures to slots right before each passing object's drawindexed'''
    bl_idname = 'MIMINode_Texture_Bind'
    bl_label = 'Slot Texture Bind'
    bl_icon = 'TEXTURE'
    bl_width_min = 320

    texture_slot_items: bpy.props.CollectionProperty(type=MIMITextureSlotItem) # type: ignore
    texture_slot_index: bpy.props.IntProperty(default=0) # type: ignore

    def width_texts(self):
        """Return every text that decides how wide this node has to be."""
        return [self.label]

    def init(self, context):
        # The default title is instance data, so bake in the active language.
        self.label = tr("Slot Texture Bind")
        self.inputs.new('MIMISocketObject', "Object")
        self.outputs.new('MIMISocketObject', "Output")
        self.width = 340
        self.use_custom_color = True
        self.color = (0.55, 0.42, 0.16)

    def draw_buttons(self, context, layout):
        tree = self.id_data if getattr(self, "id_data", None) and getattr(self.id_data, "bl_idname", "") == 'MIMIBlueprintTreeType' else None

        # A running exact-format batch is global, so its progress is shown at
        # the top of the node even while the user edits another row.
        _draw_node_progress(layout)
        # Channels turn this pass-through into a reusable 1..N node; the count
        # and its +- buttons stay at the top so the wiring is understandable.
        draw_channel_controls(layout, self, tree)
        # Every row of this node applies only in the state its object is drawn
        # in, so name that state instead of leaving the key wiring invisible.
        draw_switch_state(layout, self)

        row = layout.row()
        # The list shows the compact one-line summary of every binding row.
        # The list id must be unique per node: the uiList runtime state
        # (scroll offset and resize-grip height) is keyed by this id, so a
        # constant id would sync the height of every Texture Bind node.
        row.template_list(
            "UI_UL_list", "mimi_texture_bind_" + self.name,
            self, "texture_slot_items",
            self, "texture_slot_index",
            rows=3,
        )
        column = row.column(align=True)
        add_operator = column.operator("mimi.texbind_add_item", text="", icon='ADD')
        add_operator.node_name = self.name
        add_operator.tree_name = tree.name if tree else ""
        remove_operator = column.operator("mimi.texbind_remove_item", text="", icon='REMOVE')
        remove_operator.node_name = self.name
        remove_operator.tree_name = tree.name if tree else ""
        # One click turns every Slot / SharedSlot mark of the upstream
        # Submesh into a ready-made MARK binding row.
        autofill_operator = column.operator("mimi.texbind_autofill", text="", icon='FILE_REFRESH')
        autofill_operator.node_name = self.name
        autofill_operator.tree_name = tree.name if tree else ""

        if not self.texture_slot_items:
            layout.label(text=tr("No bindings; objects pass through unchanged"), icon='INFO')
            return

        index = int(self.texture_slot_index)
        if not (0 <= index < len(self.texture_slot_items)):
            return
        item = self.texture_slot_items[index]

        box = layout.box()
        box.prop(item, "enabled")
        # Physical slot and restore controls would be misleading for API marks.
        logical_slot = _gimi_mark_slot(item)
        if logical_slot:
            box.label(text=logical_slot, icon='TEXTURE')
        else:
            box.prop(item, "slot")
        box.prop(item, "source_type")

        source_type = str(item.source_type or "")
        if source_type == 'MARK':
            box.prop(item, "mark_name")
            # The marked image is shared by the whole Submesh. This optional
            # field is the per-object entry: two objects of one Submesh can use
            # two different pictures on the same slot, which is exactly what a
            # key switch compares.
            box.prop(item, "mark_file_path")
            draw_file_missing_warning(box, item.mark_file_path)
            if str(item.mark_file_path or "").strip():
                # The row owns an image, so it converts exactly like an
                # external file and shows the same controls.
                _draw_image_format_controls(box, self, item, index, tree)
            elif _selected_mark_type(self, item) == "SharedSlot":
                # A SharedSlot mark owns a [Resource...] section, so several
                # objects can bind it without generating extra files.
                box.label(text=tr("Empty: reuses the shared mark resource"), icon='BLANK1')
            else:
                # A plain Slot mark is bound by file name, so this object gets
                # its own copy of the marked image.
                box.label(text=tr("Empty: copies the marked image for this object"), icon='BLANK1')
            # Tell the user when the dropdown could not resolve the upstream
            # Submesh, instead of leaving a mysteriously empty dropdown.
            upstream_submesh = _resolve_upstream_submesh_name(self)
            if not upstream_submesh:
                box.label(text=tr("Upstream Submesh not resolved; mark names unavailable"), icon='ERROR')
            # A multi-channel node can feed several Submeshes while a mark only
            # exists in one of them; the export would fail for the other
            # objects, so say it here where the row is edited.
            missing_submeshes = _mark_missing_submeshes(self, item)
            if missing_submeshes:
                box.label(
                    text=tr("This mark does not exist in Submesh: {submeshes}").format(
                        submeshes=", ".join(missing_submeshes),
                    ),
                    icon='ERROR',
                )
        elif source_type == 'FILE':
            box.prop(item, "file_path")
            _draw_image_format_controls(box, self, item, index, tree)
        else:
            box.prop(item, "resource_name")

        if not logical_slot:
            # Physical connected slots always restore their captured state.
            # Keep the old RNA field for saved files, but do not offer a leak mode.
            box.label(text=tr('Draw-local binding: always restores after draw'))

        # Show the file name this row will produce and let the user rename it.
        # Every value comes from the shared naming helpers, so the displayed
        # name is the name the export writes.
        generated_name, suffix, suffix_is_certain, can_rename, disabled_reason = _slot_row_output_name(self, item)
        notes = []
        if len(upstream_draw_ib_hints(self)) > 1:
            notes.append(tr("One file per object; the first object is shown"))
        suffix_note = alias_suffix_note(suffix_is_certain)
        if suffix_note:
            notes.append(suffix_note)
        draw_generated_name(box, generated_name, certainty_note=" | ".join(notes))
        draw_rename_box(
            box, item, suffix, generated_name,
            allow_rename=can_rename, disabled_reason=disabled_reason,
        )
        if source_type == 'FILE':
            draw_file_missing_warning(box, item.file_path)

        # Early slot format feedback; the export pass validates again and
        # raises a hard error so a typo can never reach the generated INI.
        slot_text = str(item.slot or "").strip().lower()
        if not logical_slot and slot_text and _SLOT_PATTERN.match(slot_text) is None:
            layout.label(text=tr("Slot format looks wrong; expected something like ps-t0"), icon='ERROR')

        active_count = len([row_item for row_item in self.texture_slot_items if row_item.enabled])
        layout.label(text=tr("{count} slot binding(s)").format(count=active_count), icon='TEXTURE')

        # One click prepares every replacement of this node in the background,
        # so a later Generate Mod only has to copy finished files.
        _draw_convert_all(layout, self, tree)


classes = (
    MMT_OT_TexBindAddItem,
    MMT_OT_TexBindRemoveItem,
    MMT_OT_TexBindAutoFill,
    MIMINode_Texture_Bind,
)


def register():
    # The PropertyGroup must exist before the node class that references it.
    bpy.utils.register_class(MIMITextureSlotItem)
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    bpy.utils.unregister_class(MIMITextureSlotItem)
