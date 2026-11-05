"""Present AI edits in the user's real visible Blender desktop.

This is collaborative UI state, not an offscreen rendering approximation.
A user can inspect the same graph/objects immediately and continue manual work.
Never create a background Blender instance or silently open a different blend.
"""
# Collaboration rules:
# - All presentation runs on Blender's existing main-thread desktop context.
# - Headless/background execution is rejected, not used as a fallback.
# - No scene or saved file is replaced to make an AI result visible.
# - Object and tree targets use exact names supplied by the action result.
# - Only the current window's chosen editor is changed.
# - A user's unrelated editors in other windows remain untouched.
# - An existing MIMIBlender editor is preferred for blueprint presentation.
# - Otherwise a large 3D view can display the requested blueprint visibly.
# - Editor enum identifiers are read from the running Blender before assignment.
# - Focus operators run with explicit window, area and window-region context.
# - Updating a blueprint does not require a user mouse click to reveal it.
# - A graph's active sidebar selection follows its presented version.
# - View framing changes navigation, not geometry or Mod configuration.
# - Object selection is explicit and does not depend on the previous selection.
# - Presentation may be disabled for a multi-step fixture or draft action.
# - Production graph actions present their successful result by default.
# - GUI failure is reported with diagnostics, never claimed as visible success.
# - Redraw is requested for the real areas rather than a synthetic screenshot.
# - A user remains free to change the view or selection after the call returns.
# - Revision tokens exclude those navigation changes but include graph edits.
from functools import wraps
import os
import sys

import bpy

from .contract import AutomationError
from .inspection import require_tree


def restore_minimized_desktop():
    """Restore this Blender process's minimized Windows window, not another app.

    An existing bpy window can still be minimized and yield black screenshots.
    Restoring it is necessary for the user's real-time collaborative observation.
    Do not steal foreground focus when its desktop window is already restored.
    """
    if sys.platform != "win32":
        return
    import ctypes
    user32 = ctypes.windll.user32
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_ssize_t)
    windows = []
    def visit(handle, data):
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(ctypes.c_void_p(handle), ctypes.byref(pid))
        if pid.value == os.getpid() and user32.IsWindowVisible(ctypes.c_void_p(handle)):
            windows.append(handle)
        return True
    callback = callback_type(visit)
    user32.EnumWindows(callback, 0)
    if not windows:
        raise AutomationError("VISIBLE_DESKTOP_REQUIRED", "This Blender process has no visible desktop window")
    for handle in windows:
        if user32.IsIconic(ctypes.c_void_p(handle)):
            # SW_RESTORE is a Win32 window command, not a Blender RNA enum.
            # Apply it only to visible windows owned by this exact process.
            user32.ShowWindow(ctypes.c_void_p(handle), 9)


def desktop_window():
    """Require a real interactive desktop without headless fallbacks."""
    if bpy.app.background or bpy.context.window is None:
        raise AutomationError("VISIBLE_DESKTOP_REQUIRED", "AI collaboration requires a visible Blender desktop")
    restore_minimized_desktop()
    return bpy.context.window


def editor_area(window, editor_type):
    """Choose one existing editor or reuse a large current-window 3D view."""
    areas = list(window.screen.areas)  # Never inspect another window's layout.
    matches = [area for area in areas if area.type == editor_type]  # Prefer an existing matching editor.
    if editor_type == "NODE_EDITOR":  # Material and Mod blueprints are different workflows.
        own = [area for area in matches if area.spaces.active.tree_type == "MIMIBlueprintTreeType"]  # Reuse the Mod editor first.
        if own:  # The user already has a visible blueprint workspace.
            matches = own  # Preserve unrelated shader editors.
        else:
            # Do not replace a material shader editor merely because it exists.
            # Prefer the current 3D view when no blueprint editor is available.
            matches = [area for area in areas if area.type == "VIEW_3D"] or matches  # An explicit presentation may reuse this view.
    if not matches:  # Object presentation may need to restore a previous 3D editor.
        matches = [area for area in areas if area.type in {"VIEW_3D", "NODE_EDITOR"}]  # Exclude properties, timeline and outliner areas.
    if not matches:  # Refuse to invent a replacement desktop layout.
        raise AutomationError("EDITOR_REQUIRED", "No suitable visible editor area exists")  # Actionable GUI precondition.
    area = max(matches, key=lambda item: item.width * item.height)  # Prefer the largest usable work area.
    identifiers = [item.identifier for item in bpy.types.Area.bl_rna.properties["type"].enum_items]  # Running Blender is authoritative.
    if editor_type not in identifiers:  # Do not assign an unsupported enum identifier.
        raise AutomationError("EDITOR_REQUIRED", "This Blender build does not expose the requested editor")  # No headless fallback.
    if area.type != editor_type:  # Do not reset an already matching editor's view state.
        area.type = editor_type  # Change only the chosen current-window area.
    return area  # Its window region is resolved by the presentation operation.


def redraw(window):
    """Request real desktop redraws so the user sees the completed operation."""
    for area in window.screen.areas:
        area.tag_redraw()


def ui_transaction(handler):
    """Restore desktop navigation if a presentation operation fails midway.

    A failed build must not strand the user in a deleted staging tree.
    Snapshot only the current window and the selection state we may change.
    Geometry and saved files are outside this transaction and remain untouched.
    """
    @wraps(handler)
    def guarded(target, *args, **kwargs):
        window = desktop_window()
        from ..blueprint.blueprint_export_helper import BlueprintExportHelper
        props = bpy.context.scene.mimi_global_properties
        areas = [(area, area.type,
                  area.spaces.active.tree_type if area.type == "NODE_EDITOR" else None,
                  area.spaces.active.node_tree if area.type == "NODE_EDITOR" else None)
                 for area in window.screen.areas]
        selected = list(bpy.context.selected_objects)
        active = bpy.context.view_layer.objects.active
        old_blueprint = props.selected_blueprint_name
        old_runtime = BlueprintExportHelper.runtime_blueprint_tree_name
        hidden = {}
        if isinstance(target, list):
            for name in target:
                obj = bpy.context.view_layer.objects.get(name)
                if obj is not None:
                    hidden[obj] = obj.hide_get()
        try:
            return handler(target, *args, **kwargs)
        except Exception as error:
            # Restore editors before the graph builder discards its stage.
            # Old tree pointers still identify the user's untouched versions.
            failures = []
            for area, kind, tree_type, tree in areas:
                try:
                    area.type = kind
                    if tree_type is not None:
                        area.spaces.active.tree_type = tree_type
                        area.spaces.active.node_tree = tree
                except Exception as problem:
                    failures.append(str(problem))
            try:
                BlueprintExportHelper.runtime_blueprint_tree_name = old_runtime
                if props.selected_blueprint_name != old_blueprint:
                    if old_blueprint:
                        props.selected_blueprint_name = old_blueprint
                    else:
                        props.property_unset("selected_blueprint_name")
                if bpy.context.mode == "OBJECT":
                    for obj in bpy.context.view_layer.objects:
                        obj.select_set(obj in selected)
                    bpy.context.view_layer.objects.active = active
                    for obj, was_hidden in hidden.items():
                        obj.hide_set(was_hidden)
                redraw(window)
            except Exception as problem:
                failures.append(str(problem))
            if failures:
                raise AutomationError("UI_ROLLBACK_FAILED", "Desktop state could not be fully restored",
                                      {"original_error": str(error), "errors": failures}) from error
            if isinstance(error, AutomationError):
                raise
            raise AutomationError("PRESENTATION_FAILED", str(error)) from error
    return guarded


def queue_graph_focus(window, area, tree):
    """Frame nodes after Blender finishes binding/drawing the new editor tree.

    Immediate framing can be reset by Blender's deferred editor initialization.
    The callback stays on the real desktop's main thread and never sleeps.
    If the user has switched graphs in the meantime, it leaves their view alone.
    """
    def focus_after_binding():
        try:
            if area.type != "NODE_EDITOR" or area.spaces.active.node_tree != tree:
                return None
            region = next((item for item in area.regions if item.type == "WINDOW"), None)
            if region is not None:
                with bpy.context.temp_override(window=window, area=area, region=region):
                    if bpy.ops.node.view_all.poll():
                        bpy.ops.node.view_all()
                        # Blender's overlay sidebar can cover the framed output node.
                        # Measure actual projected node bounds instead of assuming one zoom step fits.
                        # This changes navigation only, never node layout or revision data.
                        sidebar = next((item for item in area.regions if item.type == "UI"), None)
                        if area.spaces.active.show_region_ui and sidebar and bpy.ops.view2d.zoom_out.poll():
                            from .revisions import absolute_node_location
                            limit = region.width - sidebar.width - 16  # Keep a small visible margin beside the overlay.
                            for attempt in range(12):  # Bound native navigation work; never busy-poll a redraw or worker.
                                right = 0
                                for node in tree.nodes:
                                    x, y = absolute_node_location(node)  # Frame-relative child positions require their real world layout.
                                    right = max(right, region.view2d.view_to_region(x + node.dimensions.x, y, clip=False)[0])
                                if right <= limit:
                                    break  # The complete node graph fits beside the visible collaboration sidebar.
                                bpy.ops.view2d.zoom_out()
                area.tag_redraw()
        except (ReferenceError, RuntimeError):
            # Closed windows or a replaced editor invalidate the deferred target.
            # Never recreate them or disturb the user's newly selected workspace.
            return None
        return None
    bpy.app.timers.register(focus_after_binding, first_interval=0.1)


@ui_transaction
def present_tree(tree, focus=True):
    """Reveal a named new/current blueprint and frame it in the actual editor."""
    window = desktop_window()
    area = editor_area(window, "NODE_EDITOR")
    space = area.spaces.active
    tree_types = [item.identifier for item in space.bl_rna.properties["tree_type"].enum_items]
    if tree.bl_idname not in tree_types:
        raise AutomationError("EDITOR_REQUIRED", "Registered blueprint tree type is not exposed by this editor")
    if space.tree_type != tree.bl_idname:
        space.tree_type = tree.bl_idname
    if space.node_tree != tree:
        space.node_tree = tree
    bpy.context.scene.mimi_global_properties.selected_blueprint_name = tree.name
    # Keep native runtime export selection coherent with the visible graph.
    # This changes only selection/presentation state, not the previous tree.
    from ..blueprint.blueprint_export_helper import BlueprintExportHelper
    BlueprintExportHelper.set_runtime_blueprint_tree(tree)
    redraw(window)
    if focus:
        queue_graph_focus(window, area, tree)
    return {"visible": True, "editor": area.type, "tree": tree.name,
            "focused": False, "focus_pending": bool(focus)}


@ui_transaction
def present_objects(names, focus=True):
    """Select explicit scene objects and show them in the real 3D viewport."""
    window = desktop_window()
    objects = [bpy.context.scene.objects.get(name) for name in names]
    if not objects or any(obj is None or obj.name not in bpy.context.view_layer.objects for obj in objects):
        raise AutomationError("NOT_FOUND", "Presentation objects were not found in the current scene")
    if bpy.context.mode != "OBJECT":
        raise AutomationError("OBJECT_MODE_REQUIRED", "Finish the current edit/pose operation before AI changes selection")
    area = editor_area(window, "VIEW_3D")
    for obj in bpy.context.view_layer.objects:
        obj.select_set(False)
    for obj in objects:
        obj.hide_set(False)
        if not obj.visible_get():
            raise AutomationError("INVISIBLE_TARGET", "Target remains hidden by object or collection visibility", {"object": obj.name})
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    region = next((item for item in area.regions if item.type == "WINDOW"), None)
    if focus and region is not None:
        with bpy.context.temp_override(window=window, area=area, region=region):
            if bpy.ops.view3d.view_selected.poll():
                bpy.ops.view3d.view_selected()
    redraw(window)
    return {"visible": True, "editor": area.type, "objects": names, "focused": bool(focus and region)}


def scene_present(params):
    """Present exactly one explicit target family; ambiguity is an error."""
    if bool(params.get("tree")) == bool(params.get("objects")):
        raise AutomationError("INVALID_ARGUMENT", "Specify either a blueprint tree or an object list")
    if params.get("tree"):
        return present_tree(require_tree(params["tree"]), params.get("focus", True))
    return present_objects(params["objects"], params.get("focus", True))
