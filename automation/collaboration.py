"""Resolve visible native UI controls against a blueprint's AI workspace.

The add-on's original draw and texture/blueprint edit implementations remain in
use. Only their transient game/path lookup context changes for bound AI trees.
Ordinary unbound user blueprints retain the original host-selected behavior.
"""
# UI context rules:
# - Draw callbacks cannot assign scene RNA settings while Blender draws.
# - The lightweight scope changes/restores Python configuration fields only.
# - User-selected AI tree metadata determines its source workspace and preset.
# - Unbound trees do not receive any context override.
# - Malformed workflow metadata is reported instead of choosing another game.
# - Registered class identities and RNA schemas are never replaced.
# - Original callback functions are retained for unregister/reload restoration.
# - Only node drawing and named texture/blueprint edits receive wrappers.
# - Import, updater and filesystem datatype-removal operators are excluded.
# - Generate Mod uses its dedicated export-job routing, not this wrapper.
# - No UI wrapper launches a replacement scene or a headless Blender process.
# - File pickers still use their original explicit tree/node identities.
# - Authorization checks inside original callbacks remain unchanged.
# - API edits and native manual edits resolve the same persisted workspace.
from functools import wraps

import bpy

from .contract import AutomationError
from .context import readonly_workflow_context, require_session_config
from .inspection import addon_classes


_WRAPPED = bpy.app.driver_namespace.setdefault("mimi_ai_ui_wrappers", [])
PREFIXES = ("mimi.texbind_", "mimi.texhashbind_", "mimi.texture_", "mimi.objlist_",
            "mimi.time_switch_", "mimi.time_shapekey_", "mimi.switch_")
EXACT = {"mimi.global_hash_refresh", "mimi.refresh_blueprint"}


def owner_tree(owner, context):
    """Resolve a node or explicit operator target, never a different named tree."""
    tree = getattr(owner, "id_data", None)
    if getattr(tree, "bl_idname", "") == "MIMIBlueprintTreeType":
        return tree
    name = getattr(owner, "tree_name", "")
    if name:
        return bpy.data.node_groups.get(name)
    space = getattr(context, "space_data", None)
    return getattr(space, "edit_tree", None) or getattr(space, "node_tree", None)


def wrap_callback(original, drawing):
    """Use the same original callback under a lightweight source context."""
    # Blender RNA dispatch counts concrete positional slots, not *args.
    # wraps preserves metadata but cannot add a missing native layout slot.
    # Keep shared context/error routing separate from the native signatures.
    def invoke(self, context, *args, **kwargs):
        tree = owner_tree(self, context)  # Resolve this callback's actual explicit target.
        if tree is None or not tree.get("mimi_ai_workflow"):  # Unbound workflows keep the original host behavior.
            return original(self, context, *args, **kwargs)  # Do not alter existing authorization or edit rules.
        try:
            config = require_session_config(tree)
            with readonly_workflow_context(config):
                return original(self, context, *args, **kwargs)
        except AutomationError as error:
            if drawing:
                if args:
                    args[0].label(text="AI workspace: " + str(error), icon="ERROR")
                return None
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
    if drawing:
        # Both draw_buttons and draw_buttons_ext require an explicit layout.
        # Pass it positionally so workspace errors use the same UI surface.
        @wraps(original)
        def guarded_draw(self, context, layout):
            return invoke(self, context, layout)
        return guarded_draw

    # Native execute callbacks have only self and context, never a layout.
    # Do not change the original operator return or authorization behavior.
    @wraps(original)
    def guarded_execute(self, context):
        return invoke(self, context)
    return guarded_execute


def register():
    """Install wrappers after native class registration, without new UI actions."""
    if _WRAPPED:
        return
    for cls, kind in addon_classes():
        callbacks = ("draw_buttons", "draw_buttons_ext") if kind == "Node" else ()
        identifier = getattr(cls, "bl_idname", "")
        if kind == "Operator" and (identifier in EXACT or identifier.startswith(PREFIXES)):
            callbacks = ("execute",)
        for name in callbacks:
            original = vars(cls).get(name)
            if callable(original):
                replacement = wrap_callback(original, kind == "Node")
                setattr(cls, name, replacement)
                _WRAPPED.append((cls, name, original, replacement))


def unregister():
    """Restore only callbacks still owned by this module's installed wrappers."""
    for cls, name, original, replacement in reversed(_WRAPPED):
        if getattr(cls, name, None) is replacement:
            setattr(cls, name, original)
    _WRAPPED.clear()
