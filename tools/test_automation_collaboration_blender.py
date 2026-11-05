"""Accept collaboration UI controls against the existing visible desktop."""
# Acceptance ownership:
# - Only new fixtures in the designated unsaved scene are touched.
# - No add-on registration chain or replacement Blender process is started.
# - Native button execution uses the same structured dispatcher as MCP tools.
# - Recovery must change actual data while preserving object identity/history.
# - Stale recovery must fail instead of clobbering resumed manual work.
# - Job cancellation must work without leaving the user's Edit mode.
# - Generator cleanup failure must retain a terminal diagnostic record.
# - Drawing is exercised with a layout recorder, not assumed from registration.
# - The real sidebar is additionally reviewed with a desktop screenshot.
import json
import unittest
import uuid

import bpy

from MIMIBlender import automation
from MIMIBlender.automation import jobs, ui

if bpy.app.background or bpy.data.filepath or bpy.context.mode != "OBJECT" or not bpy.context.scene.name.startswith("MIMIBlender MCP Capability Probe"):
    raise RuntimeError("Use the designated unsaved visible scene, never a user project")


class CollaborationTests(unittest.TestCase):
    """Keep fixture data and checkpoints available for desktop review."""

    def setUp(self):
        bpy.ops.mesh.primitive_cube_add()
        self.obj = bpy.context.active_object
        self.obj.name = "collaboration-fixture-" + uuid.uuid4().hex[:8]
        ui.register()  # Register only new owned UI classes, never rerun the native add-on chain.

    def call(self, action, params=None):
        result = automation.dispatch({"action": action, "params": params or {}})
        self.assertTrue(result["ok"], result)  # Test exact structured outcomes instead of trusting native log text.
        return result["result"]

    def test_native_recovery_button_and_stale_revision(self):
        # Inspect, edit and recover on the exact same visible mesh object.
        # The inspection journal provides revision-bearing recovery entries.
        # Another manual transform must invalidate that old recovery snapshot.
        before = list(self.obj.data.vertices[0].co)  # Compare actual pre-edit coordinates after recovery, not success labels.
        observed = self.call("mesh.inspect", {"object": self.obj.name})
        edited = self.call("mesh.patch", {"object": self.obj.name, "revision": observed["revision"],
            "vertices": [{"index": 0, "value": [-4, -1, -1]}], "present": False})
        inspected = self.call("mesh.inspect", {"object": self.obj.name})  # Freeze the current revision explicitly before enabling recovery controls.
        self.assertTrue(any(item["action"] == "mesh.inspect" for item in self.call("state.inspect")["events"]))
        identity = self.obj.as_pointer()  # Blueprint and rig references require the object pointer to stay unchanged.
        payload = json.dumps({"object": self.obj.name, "revision": inspected["revision"], "checkpoint": edited["checkpoint"], "present": False})
        self.assertEqual(bpy.ops.mimi.ai_collaboration_action(action="mesh.restore", payload=payload), {"FINISHED"})
        self.assertEqual(self.obj.as_pointer(), identity)
        self.assertEqual(list(self.obj.data.vertices[0].co), before)
        self.obj.location.x += 1
        bpy.context.view_layer.update()
        failed = automation.dispatch({"action": "mesh.restore", "params": json.loads(payload)})
        self.assertEqual(failed["error"]["code"], "STALE_REVISION")
        self.assertEqual(self.obj.location.x, 1)

    def test_cancel_in_edit_mode_preserves_user_mode(self):
        # Queue without advancing the generator, then continue manual Edit mode.
        # The owned cancellation branch must not coerce or interrupt that mode.
        # Restore only this fixture's test mode afterward, never a user object.
        def steps():
            yield {"phase": "fixture", "done": 0, "total": 1}
        job = jobs.start_job("fixture", steps())  # A cooperative record is not success until its exact terminal status.
        modes = [item.identifier for item in bpy.ops.object.mode_set.get_rna_type().properties["mode"].enum_items]
        bpy.ops.object.mode_set(mode=next(item for item in modes if item == "EDIT"))
        try:
            self.assertEqual(bpy.ops.mimi.ai_collaboration_action(action="job.cancel", payload=json.dumps({"job": job["id"]})), {"FINISHED"})
            jobs.step_job(job["id"])
            self.assertEqual(bpy.context.mode, "EDIT_MESH")
            self.assertEqual(self.call("job.inspect", {"job": job["id"]})["status"], "cancelled")
        finally:
            bpy.ops.object.mode_set(mode=next(item for item in modes if item == "OBJECT"))

    def test_user_pose_and_weight_paint_modes_are_not_forced(self):
        # Both modes belong to the user; a mutation must wait rather than exit them.
        # The mesh and armature below are newly owned visible acceptance fixtures.
        # Restore only those fixtures' test modes afterward, never an existing rig.
        # Native mode enum identifiers are discovered from actual registered RNA.
        modes = [item.identifier for item in bpy.ops.object.mode_set.get_rna_type().properties["mode"].enum_items]
        self.obj.vertex_groups.new(name="0")
        observed = self.call("mesh.inspect", {"object": self.obj.name})
        params = {"object": self.obj.name, "revision": observed["revision"], "vertices": [{"index": 0, "value": [-4, -1, -1]}]}
        before = list(self.obj.data.vertices[0].co)
        bpy.ops.object.mode_set(mode=next(item for item in modes if item == "WEIGHT_PAINT"))
        try:
            result = automation.dispatch({"action": "mesh.patch", "params": params})
            self.assertEqual(result["error"]["code"], "USER_EDIT_IN_PROGRESS")
            self.assertEqual(bpy.context.mode, "PAINT_WEIGHT")  # The AI cannot change the active user's paint mode.
        finally:
            bpy.ops.object.mode_set(mode=next(item for item in modes if item == "OBJECT"))
        bpy.ops.object.armature_add()  # Create a new fixture rig without modifying any existing user's armature.
        rig = bpy.context.active_object
        rig.name = "collaboration-rig-" + uuid.uuid4().hex[:8]
        bpy.ops.object.mode_set(mode=next(item for item in modes if item == "POSE"))
        try:
            result = automation.dispatch({"action": "mesh.patch", "params": params})
            self.assertEqual(result["error"]["code"], "USER_EDIT_IN_PROGRESS")
            self.assertEqual(bpy.context.mode, "POSE")  # Reject edits without interrupting the user's pose operation.
        finally:
            bpy.ops.object.mode_set(mode=next(item for item in modes if item == "OBJECT"))
        self.assertEqual(list(self.obj.data.vertices[0].co), before)  # Both rejected mutations leave real native geometry unchanged.

    def test_cleanup_failure_is_terminal_and_visible(self):
        # A broken cleanup must not leave the scene permanently busy.
        # Keep the terminal diagnostic warning rather than losing the record.
        # This failure is intentionally fixture-only, with no resources deleted.
        def steps():
            try:
                yield {"phase": "fixture", "done": 1, "total": 2}
            finally:
                raise RuntimeError("fixture cleanup failure")
        job = jobs.start_job("fixture", steps())  # A cooperative record is not success until its exact terminal status.
        jobs.step_job(job["id"])
        self.call("job.cancel", {"job": job["id"]})
        jobs.step_job(job["id"])
        final = self.call("job.inspect", {"job": job["id"]})  # Inspect status without advancing another timer step or replaying work.
        self.assertEqual(final["status"], "cancelled")
        self.assertTrue(any("cleanup failure" in item for item in final["warnings"]))
        self.assertTrue(any(item["id"] == job["id"] for item in self.call("state.inspect")["jobs"]))

    def test_draw_reads_state_without_dispatch_or_rna_writes(self):
        # Exercise both panel helper and exact native button payload generation.
        # Layout methods only record strings and operator identifiers here.
        # Real RNA registration remains required for the screenshot acceptance.
        labels = []  # Record draw output while avoiding any mutation during UI presentation.
        buttons = []  # Inspect the real native operator identity used by every visible button.
        class Layout:
            def label(self, text):
                labels.append(text)
            def box(self):
                return self
            def operator(self, name, text):
                from types import SimpleNamespace
                entry = SimpleNamespace(name=name, text=text)
                buttons.append(entry)
                return entry
        ui.draw_status(Layout(), bpy.context)
        self.assertTrue(any("Shared visible scene" in item for item in labels))
        self.assertTrue(all(item.name == "mimi.ai_collaboration_action" for item in buttons))
        self.assertTrue(ui.MIMI_PT_ai_collaboration_view.is_registered)  # Both real editor sidebar panels must be registered in the desktop.
        self.assertTrue(ui.MIMI_PT_ai_collaboration_graph.is_registered)  # Both real editor sidebar panels must be registered in the desktop.
        self.assertFalse(self.call("state.inspect")["in_game_verified"])


# The visible runner loads this file without exiting Blender or deleting fixtures.
# Timer callbacks stop naturally after each fixture reaches terminal state.
