"""Visible task, cancellation and retained-version recovery controls."""
# UI ownership:
# - Panels read the same records that MCP state.inspect and job.inspect expose.
# - Drawing never invokes a mutation or assigns scene settings.
# - Buttons dispatch only a small allowlist of implemented structured actions.
# - Cancel is cooperative and does not force the user out of Edit/Pose/Paint.
# - Recovery uses the exact revision observed by an explicit inspection click.
# - A user edit after inspection therefore rejects the old recovery button.
# - Retained pre-edit data is not deleted or overwritten by these controls.
# - Graph navigation opens an existing retained version without rebuilding it.
# - Errors and progress come from actual outcomes, not estimated success.
# - Terminal artifact success never claims in-game verification.
# - Registration is independent of existing native class identities.
# - Development reload updates helper globals without replacing registered UI.
# - No transport, Blender process or game is automatically started here.
import json
import textwrap

import bpy
from bpy.props import StringProperty

from .state import snapshot


ALLOWED = {"job.cancel", "mesh.inspect", "mesh.restore", "scene.present"}  # The desktop operator cannot become a generic bpy invocation endpoint.


def button(layout, label, action, params):
    """Bind explicit JSON data to one native desktop operator button."""
    operation = layout.operator("mimi.ai_collaboration_action", text=label)
    operation.action = action  # Keep action identity separate from serialized parameter data.
    operation.payload = json.dumps(params, ensure_ascii=True, allow_nan=False)  # Finite JSON is the same parameter language used by MCP clients.


class MIMI_OT_ai_collaboration_action(bpy.types.Operator):
    """Run only dedicated actions; arbitrary Python and native ops are absent."""
    bl_idname = "mimi.ai_collaboration_action"
    bl_label = "AI Collaboration Action"
    action: StringProperty()
    payload: StringProperty()

    def execute(self, context):
        from . import dispatch
        if self.action not in ALLOWED:  # Reject injected actions before importing a handler or touching data.
            self.report({"ERROR"}, "Unsupported collaboration UI action")
            return {"CANCELLED"}
        try:
            params = json.loads(self.payload)  # Parsing is not permission to execute caller-provided Python source.
        except ValueError:
            self.report({"ERROR"}, "Invalid collaboration UI data")
            return {"CANCELLED"}
        result = dispatch({"action": self.action, "params": params, "request_id": "desktop-ui"})
        if not result["ok"]:  # A failed transaction stays failed in native operator status.
            self.report({"ERROR"}, result["error"]["code"] + ": " + result["error"]["message"])
            return {"CANCELLED"}
        self.report({"INFO"}, "AI collaboration action completed; no game validation was performed")
        return {"FINISHED"}


def label(layout, text):
    """Keep complete English diagnostics readable in a narrow native sidebar."""
    # Blender labels otherwise elide the middle of long structured errors.
    # A bounded wrap preserves the code and message without widening the editor.
    # No layout calculation touches scene RNA or advances a workflow job.
    for line in textwrap.wrap(str(text), width=36)[:4]:
        layout.label(text=line)


def draw_status(layout, context):
    """Render bounded current-scene observations with no read-side mutations."""
    state = snapshot()  # Draw-side reads do not mutate scene settings or advance timers.
    label(layout, "Shared visible scene: " + state["scene"])
    label(layout, "User mode: " + state["mode"])
    label(layout, "Generated files are not game validation")
    for job in state["jobs"][:3]:  # Bound vertical work so recovery remains reachable in the sidebar.
        box = layout.box()
        label(box, job["action"] + " / " + job["status"])
        progress = job.get("progress") or {}  # Use observed completed steps, never a fabricated completion estimate.
        label(box, str(progress.get("phase", "queued")) + ": " + str(progress.get("done", 0)) + "/" + str(progress.get("total", 0)))
        if progress.get("current"):
            label(box, str(progress["current"])[-80:])
        if job.get("error"):  # Stable error codes remain recognizable without parsing log messages.
            label(box, job["error"]["code"] + ": " + job["error"]["message"])
        for warning in job.get("warnings", [])[:1]:
            label(box, warning)  # Cleanup diagnostics remain visible even after cancellation.
        if job["status"] not in {"succeeded", "failed", "cancelled", "interrupted"}:
            button(box, "Cancel future steps", "job.cancel", {"job": job["id"]})
        else:
            label(box, "Partial work and earlier versions are retained")
    events = state["events"]  # Synchronous edits share this journal with cooperative job observations.
    for event in events[-3:]:  # Recent outcomes summarize actual operations rather than pending plans.
        box = layout.box()
        label(box, event["action"] + (" / completed" if event["ok"] else " / failed"))
        if event.get("error"):
            label(box, event["error"]["code"] + ": " + event["error"]["message"])
        tree = event.get("targets", {}).get("base_tree")  # A retained base graph is navigation/recovery data, not a new graph stage.
        if tree and bpy.data.node_groups.get(tree):
            button(box, "Show pre-edit blueprint", "scene.present", {"tree": tree})
    obj = context.active_object  # Inspection is an explicit user click on the current active mesh only.
    if obj and obj.type == "MESH":
        # An inspection click freezes the revision for subsequent recovery.
        # Drawing does not rehash all mesh data on every viewport event.
        # Changing the mesh after inspection makes these buttons stale by design.
        button(layout, "Inspect active mesh / recovery", "mesh.inspect", {"object": obj.name})
        observation = next((item for item in reversed(events) if item["action"] == "mesh.inspect" and item["ok"] and item["targets"].get("object") == obj.name), None)
        if observation:  # Recovery consumes the revision frozen by the last inspection click.
            result = observation["result"]  # Use checkpoint identities returned by the production mesh handler.
            for checkpoint in result.get("checkpoints", [])[-5:]:
                button(layout, "Restore " + checkpoint["id"][:8], "mesh.restore", {
                    "object": obj.name, "revision": result["revision"], "checkpoint": checkpoint["id"]})


class MIMI_PT_ai_collaboration_view(bpy.types.Panel):
    """Keep task state accessible in the real 3D sidebar."""
    bl_label = "AI Collaboration"
    bl_idname = "MIMI_PT_ai_collaboration_view"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "AI Collaboration"

    def draw(self, context):
        draw_status(self.layout, context)


class MIMI_PT_ai_collaboration_graph(bpy.types.Panel):
    """The same task controls remain visible while editing a blueprint."""
    bl_label = "AI Collaboration"
    bl_idname = "MIMI_PT_ai_collaboration_graph"
    bl_space_type = "NODE_EDITOR"
    bl_region_type = "UI"
    bl_category = "AI Collaboration"

    def draw(self, context):
        draw_status(self.layout, context)


CLASSES = (MIMI_OT_ai_collaboration_action, MIMI_PT_ai_collaboration_view, MIMI_PT_ai_collaboration_graph)  # Registration owns exactly these new UI classes and no native peers.


def register():
    """Register only newly owned collaboration UI classes, once."""
    for cls in CLASSES:
        if not cls.is_registered:  # Repeated setup does not duplicate existing RNA registrations.
            bpy.utils.register_class(cls)


def unregister():
    """Leave all native add-on classes and user data intact."""
    for cls in reversed(CLASSES):
        if cls.is_registered:  # Disabling collaboration cannot unregister unrelated add-on classes.
            bpy.utils.unregister_class(cls)
