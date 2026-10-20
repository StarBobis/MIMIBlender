"""Generated-file controls shared by the four texture replacement nodes.

Slot Texture Bind, Hash Texture Bind, Global Hash Texture Bind and Global Slot
Texture Bind all rename one or more generated texture files, so the drawing
code for "here is the file name" plus "type an alias to rename it" lives here
instead of being copied four times.

Only display work happens in this module:

- ``upstream_draw_ib_hints`` reads the objects that feed a node, because the
  generated name contains their DrawIB and object name;
- ``draw_generated_name`` shows the name that the export will write, split
  over several lines so a long name stays readable inside a node;
- ``draw_rename_box`` shows the optional alias field and the resulting name.

The rules themselves live in ``common.texture_output_naming``, which the
export pass uses as well.  That is what keeps the shown name honest.
"""
import os
import textwrap

import bpy

from ..i18n.i18n import tr
from ..common.texture_output_naming import (
    DRAW_IB_PLACEHOLDER,
    OBJECT_PLACEHOLDER,
    alias_output_filename_with_suffix,
    texture_source_suffix,
)

# Characters per line for a displayed file name.  A node is only a few hundred
# pixels wide, so a 60 character name has to wrap instead of being clipped.
_NAME_LINE_WIDTH = 42


def draw_ib_from_name(name):
    """Return the DrawIB part of an object or Submesh name ("" when unknown).

    Mirrors ``DrawCallModel._try_parse_name``: an optional ``LOD0.`` prefix is
    ignored and the DrawIB is the text before the first ``-``.
    """
    text = str(name or "").strip()
    if not text:
        return ""
    # A LOD prefix is not part of the DrawIB and would make the name wrong.
    if text.upper().startswith("LOD") and "." in text:
        prefix, _, rest = text.partition(".")
        if prefix[3:].isdigit():
            text = rest
    # The alias after the dot is display data, never part of the DrawIB.
    text = text.partition(".")[0]
    draw_ib = text.partition("-")[0].strip()
    return draw_ib if draw_ib and draw_ib not in ("?", "<none>") else ""


def upstream_draw_ib_hints(node):
    """Return ``[(object_name, draw_ib), ...]`` for the objects feeding a node.

    The generated name of an object scoped row contains the object name and the
    DrawIB, so the node UI has to resolve them from the upstream Object Info and
    Object List nodes.  Entries are de-duplicated and keep wire order; an empty
    list means "cannot be resolved here", which the UI shows as placeholders.
    """
    # Imported lazily: blueprint_graph imports this module indirectly through
    # several node modules, so a module level import could become a cycle.
    from .blueprint_graph import iter_object_sources

    hints = []
    seen = set()
    try:
        for source in iter_object_sources(node):
            object_name = str(getattr(source, "object_name", "") or "").strip()
            submesh_name = str(getattr(source, "submesh_name", "") or "").strip()
            draw_ib = draw_ib_from_name(submesh_name) or draw_ib_from_name(object_name)
            key = (object_name.lower(), draw_ib.lower())
            if not object_name and not draw_ib:
                continue
            if key in seen:
                continue
            seen.add(key)
            hints.append((object_name, draw_ib))
    except Exception:
        # A half-built graph must never make the node editor fail to draw.
        return []
    return hints


def upstream_submesh_names(node):
    """Return the Submesh names of the objects feeding a node (in wire order)."""
    from .blueprint_graph import iter_object_sources

    names = []
    try:
        for source in iter_object_sources(node):
            name = str(getattr(source, "submesh_name", "") or "").strip()
            if name and name not in names:
                names.append(name)
    except Exception:
        return []
    return names


def first_hint(hints):
    """Return the first ``(object_name, draw_ib)`` pair, or placeholders."""
    if hints:
        object_name, draw_ib = hints[0]
        return object_name or OBJECT_PLACEHOLDER, draw_ib or DRAW_IB_PLACEHOLDER
    return OBJECT_PLACEHOLDER, DRAW_IB_PLACEHOLDER


def display_suffix(format_mode, source_path):
    """Return the suffix the generated file will most likely use.

    A manual format always converts the image, so the file is a DDS.  Auto
    follows the captured original, which the UI cannot read while drawing a
    node; the source suffix is shown then and ``suffix_is_certain`` reports
    that the conversion may still change it.
    """
    suffix = texture_source_suffix(source_path)
    if str(format_mode or "").upper() == "MANUAL":
        return ".dds", True
    return suffix, (suffix == ".dds")


def exact_format_enabled():
    """Return the global exact-format switch without breaking node drawing.

    The export pass converts a replacement to a DDS whenever the switch is on
    and an original can be resolved; the UI needs the same answer to show the
    right suffix.  A light test stub without the switch counts as enabled,
    exactly like the model layer decides it.
    """
    from ..common.mimi_global_properties import MIMIGlobalProperties

    getter = getattr(MIMIGlobalProperties, "exact_texture_format_enabled", None)
    try:
        return bool(getter()) if callable(getter) else True
    except Exception:
        return True


def alias_preview(row, suffix):
    """Return the file name the alias field currently produces ("" = unused)."""
    return alias_output_filename_with_suffix(getattr(row, "output_name", ""), suffix)


def draw_generated_name(layout, name, icon='FILE_IMAGE', certainty_note=""):
    """Draw one generated file name, wrapped so it fits inside a node.

    A missing name means this row does not generate a file at all (it reuses an
    existing resource), which is different from a name that is not known yet;
    the caller decides which text to pass.
    """
    box = layout.box()
    box.label(text=tr("Generated texture file"), icon=icon)
    if not name:
        box.label(text=tr("This row generates no texture file"), icon='INFO')
        return
    # Long names are split on separators where possible; a single very long
    # fragment is broken anyway so nothing is clipped silently.
    for line in textwrap.wrap(name, _NAME_LINE_WIDTH, break_long_words=True,
                              break_on_hyphens=False) or [name]:
        box.label(text=line)
    if certainty_note:
        box.label(text=certainty_note, icon='INFO')


def draw_rename_box(layout, row, suffix, generated_name, allow_rename=True, disabled_reason=""):
    """Draw the optional alias field and the file name it produces.

    ``allow_rename`` is False for rows that reuse an existing resource or a
    GIMI API slot: those generate no file, so an alias would be a promise the
    export cannot keep and the field is replaced by an explanation.
    """
    if not allow_rename:
        if disabled_reason:
            layout.label(text=disabled_reason, icon='INFO')
        return
    column = layout.column(align=True)
    column.prop(row, "output_name", text=tr("Rename to"))
    preview = alias_preview(row, suffix)
    if not preview:
        # An empty field is the normal case: the generated default name stays.
        column.label(text=tr("Leave empty to keep the name above"), icon='BLANK1')
        return
    if preview == generated_name:
        column.label(text=tr("The alias matches the generated name"), icon='CHECKMARK')
        return
    column.label(text=tr("Renamed file: {name}").format(name=preview), icon='CHECKMARK')


def alias_suffix_note(suffix_is_certain):
    """Return the hint shown when the format conversion may change the suffix."""
    if suffix_is_certain:
        return ""
    return tr("Auto format conversion may change the suffix to .dds")


def draw_file_missing_warning(layout, source_path):
    """Warn about a chosen file that does not exist (export would fail)."""
    text = str(source_path or "").strip()
    if not text:
        return
    try:
        # Relative Blender paths are resolved the same way the export does.
        exists = os.path.isfile(bpy.path.abspath(text))
    except Exception:
        exists = True
    if not exists:
        layout.label(text=tr("The chosen texture file does not exist"), icon='ERROR')
