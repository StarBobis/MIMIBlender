"""Skeleton binding settings shared by every model import entry point.

Two add-on panels start a model import: the Mod Reverse panel and the Basic
Information panel. Both of them bind the character skeleton from a
``skeleton.json`` sidecar, so both of them must offer the same controls. The
choice belongs to the current blend file, therefore the state lives on the
Scene; this module is the only owner of that state:

* ``register`` / ``unregister`` define and remove the properties.
* ``draw_skeleton_binding`` renders the collapsible block (collapsed by
  default, with the bind checkbox in its header), so the two panels cannot
  drift apart into two slightly different sets of controls.
* ``ensure_bind_settings`` migrates files saved before the settings were split
  and returns the values an import has to use.
* ``remember_bind_report`` keeps the last binding result visible in the panel.

The properties keep their historical ``mimi_sword_`` prefix so the data of
already saved blend files keeps working. ``mimi_sword_skeleton_mode`` is kept
registered as a hidden legacy property: old files still restore its value, the
migration below reads it once and then never uses it again.
"""

import json
import os

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty

from ..i18n.i18n import tr
from .skeleton_helper import (
    BONE_CLEANUP_DELETE,
    BONE_CLEANUP_HIDE,
    BONE_CLEANUP_NONE,
    NAMING_BONE_TO_GROUP,
    NAMING_GROUP_TO_BONE,
    SkeletonHelper,
)

# Property names are also the keys stored inside the blend file, so renaming
# one of them would silently reset the setting for every existing user.
BIND_PROPERTY = "mimi_sword_bind_skeleton"
NAMING_PROPERTY = "mimi_sword_skeleton_naming"
CLEANUP_PROPERTY = "mimi_sword_skeleton_cleanup"
REPORT_PROPERTY = "mimi_sword_skeleton_last_report"
LEGACY_MODE_PROPERTY = "mimi_sword_skeleton_mode"

# The migration marker is a plain ID property, not an RNA property: it only
# has to say "this file was already converted", nothing else reads it.
SETTINGS_VERSION_KEY = "mimi_skeleton_settings_version"
# Version 2 removed the "Follow MMT" choice: the add-on decides the naming mode
# now, so a stored SIDECAR value has to become Rename Bones.
SETTINGS_VERSION = 2

SIDECAR_FILE_NAME = "skeleton.json"

# Parsing the sidecar on every redraw would be wasteful; the panel is redrawn
# on mouse moves. The mtime tells us whether the cached summary is still valid.
_SIDECAR_CACHE = {}


class BindSettings:
    """Values one import has to use, already resolved to plain names."""

    __slots__ = ("bind", "naming", "cleanup")

    def __init__(self, bind, naming, cleanup):
        self.bind = bool(bind)
        self.naming = str(naming or NAMING_BONE_TO_GROUP)
        self.cleanup = str(cleanup or BONE_CLEANUP_NONE)

    def __iter__(self):
        # Makes the value behave like the tuple tests and callers may unpack.
        return iter((self.bind, self.naming, self.cleanup))


def get_naming_items(self=None, context=None):
    """Translated naming choices; called by Blender on every dropdown draw.

    The add-on owns the decision now, so the mode the desktop app stored is not
    offered any more. ``Rename Bones`` is first on purpose: a dynamic items
    callback only accepts an integer default, so index 0 is the default of a
    fresh scene, and it is the mode the mod workflow needs.
    """
    return [
        (
            NAMING_BONE_TO_GROUP,
            tr("Rename Bones (mod workflow)"),
            tr("Keep numeric vertex groups and rename the armature bones (keeps the model exportable); "
               "a character whose DrawIBs use different palettes gets one armature per palette"),
        ),
        (
            NAMING_GROUP_TO_BONE,
            tr("Rename Vertex Groups (other purposes)"),
            tr("Rename mesh vertex groups to the skeleton bone names; the whole character stays on one armature"),
        ),
    ]


def get_cleanup_items(self=None, context=None):
    """Translated cleanup choices, mirroring the helper's mode constants."""
    return [
        (
            BONE_CLEANUP_NONE,
            tr("Keep All Bones"),
            tr("Keep the whole character skeleton; bones that no imported mesh uses stay in the armature"),
        ),
        (
            BONE_CLEANUP_DELETE,
            tr("Delete Invalid Bones"),
            tr("Delete bones that no imported mesh uses; children of a deleted bone are reattached to the nearest usable parent"),
        ),
        (
            BONE_CLEANUP_HIDE,
            tr("Hide Invalid Bones"),
            tr("Hide bones that no imported mesh uses; the skeleton hierarchy is not changed"),
        ),
    ]


def _concrete_naming(value):
    """Return one of the two modes the add-on offers.

    A file saved while ``Follow MMT`` existed still carries ``SIDECAR`` in its
    scene; that value no longer exists and becomes the add-on default.
    """
    if str(value or "") == NAMING_GROUP_TO_BONE:
        return NAMING_GROUP_TO_BONE
    return NAMING_BONE_TO_GROUP


def _legacy_bind_settings(scene):
    """Map the old single enum onto the split settings.

    ``BONE_TO_GROUP`` used to be the default for everybody and is the add-on's
    default again, so it becomes ``Rename Bones``. ``GROUP_TO_BONE`` and
    ``NONE`` were explicit choices and are preserved.
    """
    legacy = str(getattr(scene, LEGACY_MODE_PROPERTY, "") or "")
    if legacy == "NONE":
        return False, NAMING_BONE_TO_GROUP
    if legacy == NAMING_GROUP_TO_BONE:
        return True, NAMING_GROUP_TO_BONE
    return True, NAMING_BONE_TO_GROUP


def read_bind_settings(scene):
    """Return the settings an import draws with, without changing the scene.

    Panel draw functions are not allowed to write Scene properties in Blender
    5.2, so this function only reads. A file that was not migrated yet still
    reports its legacy values instead of the defaults of the new properties.
    """
    cleanup = str(getattr(scene, CLEANUP_PROPERTY, BONE_CLEANUP_NONE) or BONE_CLEANUP_NONE)
    if _settings_version(scene) == 0:
        bind, naming = _legacy_bind_settings(scene)
        return BindSettings(bind, naming, cleanup)
    # Version 1 already had the split properties but could store the removed
    # SIDECAR mode; the read path resolves it without writing to the scene.
    return BindSettings(
        getattr(scene, BIND_PROPERTY, True),
        _concrete_naming(getattr(scene, NAMING_PROPERTY, "")),
        cleanup,
    )


def _settings_version(scene):
    """Return the stored migration version of one scene, 0 when unreadable."""
    try:
        return int(scene.get(SETTINGS_VERSION_KEY, 0) or 0)
    except (TypeError, ValueError):
        return 0


def ensure_scene_settings(scene):
    """Write the split settings once per scene and mark the file as migrated.

    Returns True when this call changed the scene. Operators and the load
    handler may write, so this is the only place that converts old values.
    """
    if scene is None:
        return False
    version = _settings_version(scene)
    if version >= SETTINGS_VERSION:
        return False
    if version == 0:
        bind, naming = _legacy_bind_settings(scene)
    else:
        # Version 1 already had the split properties; only the naming value can
        # still name the removed mode.
        bind = bool(getattr(scene, BIND_PROPERTY, True))
        naming = _concrete_naming(getattr(scene, NAMING_PROPERTY, ""))
    try:
        setattr(scene, BIND_PROPERTY, bind)
        setattr(scene, NAMING_PROPERTY, naming)
        scene[SETTINGS_VERSION_KEY] = SETTINGS_VERSION
        return True
    except (AttributeError, TypeError, ValueError):
        # A half registered add-on must not break the import; the read helper
        # still falls back to the legacy value in that state.
        return False


def ensure_bind_settings(scene):
    """Migrate the scene and return the values an import has to use."""
    ensure_scene_settings(scene)
    return read_bind_settings(scene)


def remember_bind_report(scene, summary):
    """Store the last binding summary so both panels can show it again."""
    if scene is None or not hasattr(scene, REPORT_PROPERTY):
        return
    try:
        setattr(scene, REPORT_PROPERTY, str(summary or "")[:512])
    except (AttributeError, TypeError, ValueError):
        pass


def _conflicting_characters(payload):
    """Characters whose DrawIBs number different bones with the same numbers.

    "Rename Bones" turns the palette numbers into bone names, and one armature
    can only carry one numbering. Such a character therefore gets one armature
    per palette, which changes the Outliner and the posing workflow; the panel
    says so before the import instead of letting the user discover it after.
    "Rename Vertex Groups" needs no hint: object-local groups keep one armature.
    """
    character_names = {}
    character_maps = {}
    for character in payload.get("Characters") or []:
        key = str(character.get("Id", ""))
        character_names[key] = str(character.get("Name") or character.get("Id") or "")
        character_maps[key] = character.get("BoneMap") or {}

    # Mirror SkeletonHelper.drawib_map(): a DrawIB map wins, the character map
    # is only the fallback for sidecars written before the per-DrawIB table.
    palettes = {}
    for entry in payload.get("DrawIBs") or []:
        key = str(entry.get("CharacterId", ""))
        mapping = entry.get("BoneMap") or character_maps.get(key) or {}
        if not mapping:
            continue
        palettes.setdefault(key, []).append(
            {str(index): str(name) for index, name in mapping.items()}
        )

    conflicts = []
    for key, maps in palettes.items():
        if len(maps) > 1 and SkeletonHelper.palettes_conflict(maps):
            conflicts.append(character_names.get(key) or key)
    return conflicts


def _wants_numeric_bones(naming):
    """Whether the chosen mode renames the bones to the palette numbers."""
    return _concrete_naming(naming) == NAMING_BONE_TO_GROUP


def _naming_hint(info, naming):
    """Hint for what a naming choice will really produce, or an empty string.

    Only numeric bone names need a warning: one bone can carry one number, so a
    character whose DrawIBs disagree gets several armatures. Renaming the vertex
    groups keeps one armature, because every object renames its own groups, so
    that mode has nothing to warn about. Per-component tables still change the
    naming itself: they keep bone names because the export addresses the
    components through one merged table.
    """
    if info is None:
        return ""
    if info.get("components"):
        if _wants_numeric_bones(naming):
            return tr(
                "This skeleton numbers bones per component; the import renames the vertex groups instead of the bones"
            )
        return ""
    conflicts = info.get("conflicts") or []
    if conflicts and _wants_numeric_bones(naming):
        return tr(
            "DrawIBs of {names} number different bones; the import creates one armature per palette"
        ).format(names=", ".join(conflicts[:3]))
    return ""


def sidecar_info(folder):
    """Summarize ``<folder>/skeleton.json`` or return None when it is missing.

    The summary is cached by modification time because the panel redraw calls
    this on every mouse move. A broken sidecar is reported as missing instead
    of raising: a half written file must never break the panel.
    """
    if not folder:
        return None
    path = os.path.join(str(folder), SIDECAR_FILE_NAME)
    try:
        modified = os.path.getmtime(path)
    except OSError:
        return None
    cached = _SIDECAR_CACHE.get(path)
    if cached is not None and cached[0] == modified:
        return cached[1]
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        payload = {}
    characters = []
    for character in payload.get("Characters") or []:
        name = str(character.get("Name") or character.get("Id") or "").strip()
        if name and name not in characters:
            characters.append(name)
    info = {
        "path": path,
        "draw_ibs": len(payload.get("DrawIBs") or []),
        "characters": characters,
        # The two facts that make "Rename Bones" impossible for this skeleton.
        # Computing them once per file modification keeps the redraw cheap.
        "conflicts": _conflicting_characters(payload),
        "components": any(entry.get("Components") for entry in payload.get("DrawIBs") or []),
    }
    _SIDECAR_CACHE[path] = (modified, info)
    return info


def clear_sidecar_cache():
    """Forget cached sidecar summaries (tests and explicit folder changes)."""
    _SIDECAR_CACHE.clear()


# The side panel is narrow, so a bind report has to be split into lines that
# actually fit. One line that is too long is shortened in the middle, which hid
# the forced-naming note of every long report.
REPORT_LINE_WIDTH = 38
REPORT_MAX_LINES = 8


def wrap_bind_report(text, width=REPORT_LINE_WIDTH, max_lines=REPORT_MAX_LINES):
    """Split a bind report into panel width lines, never into more than max_lines.

    Words are kept whole when possible; a word longer than the width is left on
    its own line instead of being broken, because path-like tokens are easier to
    read that way. A report that does not fit is marked with "..." so a cut
    result is never mistaken for a complete one.
    """
    words = str(text or "").split()
    lines = []
    current = ""
    index = 0
    while index < len(words) and len(lines) < max_lines:
        word = words[index]
        if not current:
            current = word
        elif len(current) + 1 + len(word) <= width:
            current = current + " " + word
        else:
            lines.append(current)
            current = word
        index += 1
    if current and len(lines) < max_lines:
        lines.append(current)
    if index < len(words) and lines:
        # The remaining words did not fit; say so instead of dropping them.
        lines[-1] = lines[-1][: max(0, width - 3)] + "..."
    if not lines:
        # An empty input still gives the caller one drawable line.
        return [""]
    return lines


def draw_skeleton_binding(layout, scene, folder, panel_id="mimi_skeleton_binding"):
    """Draw the shared skeleton block under an import button.

    The block is a collapsible sub-panel that starts collapsed. The bind
    checkbox lives in the header, so the user can switch binding on or off
    without opening it, and the import reads the same Scene property either
    way: how the block is drawn never changes what the import does.

    ``folder`` is the folder this panel's import reads its sidecar from, so
    both panels can show a hint about their own source instead of a generic
    message that may belong to the other panel.
    ``panel_id`` keeps the open/closed state of the two panels apart; the same
    id would open both blocks together.
    """
    header, body = layout.panel(panel_id, default_closed=True)
    header.use_property_split = False
    header.label(text=tr("Skeleton Binding"), icon='ARMATURE_DATA')
    # Push the checkbox to the right edge; it stays reachable while collapsed.
    # A layout that does not accept spacers in a header still keeps the checkbox
    # next to the title instead of failing the whole panel.
    try:
        header.separator_spacer()
    except (AttributeError, RuntimeError, TypeError):
        pass
    header.prop(scene, BIND_PROPERTY, text="")
    if body is None:
        return
    bound = bool(getattr(scene, BIND_PROPERTY, True))
    if bound:
        body.prop(scene, NAMING_PROPERTY, text=tr("Skeleton Naming"))
        body.prop(scene, CLEANUP_PROPERTY, text=tr("Bone Cleanup"))
        info = sidecar_info(folder)
        if info is not None:
            # The hint belongs right under the dropdown it explains: the user
            # then knows how many rigs to expect before pressing the button.
            hint = _naming_hint(
                info, _concrete_naming(getattr(scene, NAMING_PROPERTY, ""))
            )
            if hint:
                # A per-component fallback really changes the naming mode, while
                # one armature per palette is the documented numeric behaviour.
                body.label(text=hint, icon='ERROR' if info.get("components") else 'INFO')
            body.label(
                text=tr("Skeleton file found: the import will bind the character armature"),
                icon='ARMATURE_DATA',
            )
            if info["characters"]:
                names = ", ".join(info["characters"][:3])
                body.label(text=tr("Character: {names}").format(names=names))
        else:
            # The sidecar is only one of the two skeleton sources now: every
            # SubmeshJson can carry its own embedded block, so this hint must not
            # promise that no armature will be created.
            body.label(
                text=tr("No skeleton.json next to this folder; the import uses the skeleton embedded in each Json when it has one"),
                icon='INFO',
            )
    else:
        body.label(
            text=tr("Skeleton binding is off; the import creates no armature"),
            icon='INFO',
        )

    report = str(getattr(scene, REPORT_PROPERTY, "") or "")
    if report:
        # A single label shortens a long text in the middle, which used to hide
        # exactly the part that explains a forced naming mode. Wrapping the
        # report keeps every reason readable inside the narrow side panel.
        caption = tr("Last bind: {summary}").format(summary=report)
        lines = wrap_bind_report(caption)
        body.label(text=lines[0], icon='CHECKMARK')
        for line in lines[1:]:
            body.label(text="  " + line)


@bpy.app.handlers.persistent
def migrate_loaded_scene(scene=None):
    """Convert every opened blend file that still stores the legacy setting.

    ``load_post`` fires when the user opens a file after startup; the register
    step covers the file that is already open and the add-on reload performed
    by the updater. The property may not exist while the add-on is being
    registered, so every access below tolerates a missing scene.
    """
    try:
        for candidate in bpy.data.scenes:
            ensure_scene_settings(candidate)
    except AttributeError:
        # bpy.data is restricted while add-ons register; load_post runs later.
        return


def register():
    """Define the shared properties and install the load time migration."""
    bpy.types.Scene.mimi_sword_bind_skeleton = BoolProperty(
        name=tr("Bind Skeleton"),
        description=tr("Build the character armature from skeleton.json during import"),
        default=True,
    )
    # Dynamic items keep the dropdown translated when the UI language changes;
    # index 0 ("Rename Bones") is therefore the default of a fresh scene.
    bpy.types.Scene.mimi_sword_skeleton_naming = EnumProperty(
        name=tr("Skeleton Naming"),
        description=tr("How the imported meshes and the armature reconcile their two name spaces"),
        items=get_naming_items,
    )
    bpy.types.Scene.mimi_sword_skeleton_cleanup = EnumProperty(
        name=tr("Bone Cleanup"),
        description=tr("How bones that no imported mesh uses are handled after the armature is bound"),
        items=get_cleanup_items,
    )
    bpy.types.Scene.mimi_sword_skeleton_last_report = StringProperty(
        name=tr("Last Skeleton Bind"),
        description=tr("Result of the last import that bound a skeleton"),
        default="",
    )
    # Hidden legacy property: old files restore their value into it, the
    # migration reads it once and the UI never shows it again.
    bpy.types.Scene.mimi_sword_skeleton_mode = EnumProperty(
        name="Skeleton Naming (Legacy)",
        items=[
            ("BONE_TO_GROUP", "Rename Bones", ""),
            ("GROUP_TO_BONE", "Rename Vertex Groups", ""),
            ("NONE", "No Skeleton", ""),
        ],
        default="BONE_TO_GROUP",
    )
    if migrate_loaded_scene not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(migrate_loaded_scene)
    # The file that is already open when the add-on starts (or reloads) needs
    # the same conversion as a file opened later.
    migrate_loaded_scene()


def unregister():
    """Remove the properties and the handler again."""
    for property_name in (
        "mimi_sword_skeleton_last_report",
        "mimi_sword_skeleton_cleanup",
        "mimi_sword_skeleton_naming",
        "mimi_sword_bind_skeleton",
        "mimi_sword_skeleton_mode",
    ):
        if hasattr(bpy.types.Scene, property_name):
            delattr(bpy.types.Scene, property_name)
    if migrate_loaded_scene in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(migrate_loaded_scene)
    clear_sidecar_cache()
