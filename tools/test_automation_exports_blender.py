"""Validate AI/native manual export handoff in the real visible MCP desktop.

Use new retained source/output fixtures under tmp. No headless process, game
launch, installed Mod overwrite or replacement user scene is used by this suite.
"""
# Export acceptance:
# - Native source parsing and game exporters are not mocked.
# - Existing geometry stays in the current visible user/test scene.
# - Source binding creates recoverable new graphs, not reimported user geometry.
# - Every output directory is a new exclusive path outside the source root.
# - Native UI Generate Mod clicks resolve the bound preset, not host defaults.
# - Artifact closure requires real INIs and every referenced generated file.
# - Source hashes and scene signatures are checked independently.
# - Source/root/revision mistakes fail before native output is generated.
# - A Face Object List port contributes only its own linked row.
# - Face node output overrides cannot escape the explicit generated root.
# - Optional real PGR input proves both geometry and marked-texture file presence.
# - In-game behavior remains explicitly outside these offline artifact checks.
import json
from pathlib import Path
import sys
import unittest
import uuid
from unittest.mock import patch

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from automation_fixture import write_native_workspace, source_hashes, TYPE_NAME, FOLDER_NAME
from MIMIBlender import automation
from MIMIBlender.automation import jobs
from MIMIBlender.automation.preservation import scene_snapshot, verify_scene_snapshot
from MIMIBlender.common.global_config import GlobalConfig

if bpy.app.background or bpy.data.filepath or bpy.context.mode != "OBJECT" or not bpy.context.scene.name.startswith("MIMIBlender MCP Capability Probe"):
    raise RuntimeError("Use the designated visible unsaved test scene without an active user edit")


class ExportTests(unittest.TestCase):
    """Each case owns new fixtures and records exact cooperative job identities."""
    def setUp(self):
        # No fixture directory is automatically removed after a test.
        self.base = ROOT / "tmp" / "automation-export-fixtures" / uuid.uuid4().hex  # Exclusive retained test namespace.
        self.source = write_native_workspace(self.base / "source")  # Source generation is synthetic; import/export remain native.
        self.work = self.base / "sessions"  # Session decisions stay outside the source asset tree.
        self.ids = []  # Every started test-owned cooperative job is tracked.
        started = self.call("workspace.import", {"source": str(self.source), "logic": "PGR",  # Use the real public source import contract.
            "name": "export-fixture-" + uuid.uuid4().hex[:8], "work_directory": str(self.work), "present": False})
        completed = self.finish(started["id"])  # Advance the actual timer-step implementation deterministically.
        self.assertEqual(completed["status"], "succeeded", completed)  # Failed imports cannot seed export acceptance tests.
        self.tree = bpy.data.node_groups[completed["result"]["tree"]]  # Retain the actual user-editable native graph.
        self.obj = bpy.data.objects[completed["result"]["objects"][0]]  # Verify the same visible scene object, not an offline copy.

    def tearDown(self):
        # Assertion failures must not leave a test-owned job blocking later cases.
        for identifier in self.ids:
            if jobs.JOBS[identifier]["status"] not in jobs.TERMINAL:
                jobs.JOBS[identifier]["cancel_requested"] = True
                jobs.step_job(identifier)

    def call(self, action, params, success=True):
        # Use the production API envelope, not internal exporter success strings.
        result = automation.dispatch({"action": action, "params": params})
        self.assertEqual(result["ok"], success, result)
        if result["ok"] and action in {"workspace.import", "mod.export"}:
            self.ids.append(result["result"]["id"])
        return result["result"] if success else result["error"]

    def finish(self, identifier):
        # Deterministic finite execution uses the same function as real timers.
        # These fixtures contain no asynchronous texture conversion batch.
        for step in range(8):
            if jobs.JOBS[identifier]["status"] in jobs.TERMINAL:
                break
            jobs.step_job(identifier)
        record = self.call("job.inspect", {"job": identifier})
        self.assertIn(record["status"], jobs.TERMINAL, record)
        return record

    def params(self, tree=None):
        # The current graph query supplies a fresh expected revision.
        tree = tree or self.tree  # An explicit alternate bound graph can be tested without changing scene files.
        state = self.call("blueprint.inspect", {"tree": tree.name})  # Read the current revision instead of reusing a stale import token.
        return {"tree": tree.name, "revision": state["revision"],
                "output_directory": str(self.base / ("mod-" + uuid.uuid4().hex))}

    def test_conversion_cache_cannot_write_original_source(self):
        # Cache creation is a write even before the Mod directory exists.
        # A source-contained user override must fail with no source-byte changes.
        # Native import/export context stays active only during bounded steps.
        params = self.params()
        params["settings"] = {"texture_format_cache_folder": str(self.source / "cache")}
        before = source_hashes(self.source)
        result = self.finish(self.call("mod.export", params)["id"])
        self.assertEqual(result["status"], "failed", result)
        self.assertEqual(result["error"]["code"], "SOURCE_WRITE_FORBIDDEN")
        self.assertFalse((self.source / "cache").exists())
        self.assertEqual(source_hashes(self.source), before)

    def test_user_mesh_edit_after_phase_yield_stops_native_writer(self):
        # Resume manual editing after preparation yielded the visible desktop.
        # Recheck actual scene state before any native buffer writer is invoked.
        # The user's new coordinate is retained instead of being rolled back.
        params = self.params()
        started = self.call("mod.export", params)
        jobs.step_job(started["id"])
        self.obj.data.vertices[0].co.x += 0.5
        changed = self.obj.data.vertices[0].co.x
        result = self.finish(started["id"])
        self.assertEqual(result["status"], "failed", result)
        self.assertEqual(result["error"]["code"], "SOURCE_SCENE_CHANGED")
        self.assertEqual(self.obj.data.vertices[0].co.x, changed)
        self.assertFalse(list(Path(params["output_directory"]).glob("*.ini")))

    def test_owned_conversion_cancel_retains_partial_work(self):
        # Mock only the non-bpy conversion worker boundary, never native exporters.
        # Cooperative cancellation closes its owning generator and no later batch.
        # A current native step is deliberately not advertised as interruptible.
        from MIMIBlender.common import texture_format_service as textures
        flag = {"running": False}
        def start(batch, outcome=None):
            flag["running"] = True
            return 1
        image = self.base / "input.png"
        image.write_bytes(b"fixture conversion input")
        batch = [{"source": str(image), "label": "fixture"}]
        worker = object()
        params = self.params()
        with patch.object(textures, "collect_tree_jobs", return_value=batch), patch.object(textures, "plan_for_job", return_value=object()), \
             patch.object(textures, "start_conversion", side_effect=start), patch.object(textures, "is_running", side_effect=lambda: flag["running"]), \
             patch.object(textures, "_WORKER", worker), patch.object(textures, "cancel_conversion") as cancel:
            started = self.call("mod.export", params)
            jobs.step_job(started["id"])
            self.assertEqual(jobs.JOBS[started["id"]]["progress"]["phase"], "converting")
            self.call("job.cancel", {"job": started["id"]})
            result = self.finish(started["id"])
            self.assertEqual(result["status"], "cancelled", result)
            cancel.assert_called_once()
            flag["running"] = False  # A later export must not own a replacement user's independent worker.
            later = self.call("mod.export", self.params())
            jobs.step_job(later["id"])
            with patch.object(textures, "_WORKER", object()):
                self.call("job.cancel", {"job": later["id"]})
                self.assertEqual(self.finish(later["id"])["status"], "cancelled")
            cancel.assert_called_once()  # The unrelated newer worker was never cancelled by the old owner.
        self.assertFalse(Path(params["output_directory"]).exists())
        self.assertEqual(image.read_bytes(), b"fixture conversion input")

    def test_conversion_stage_failure_keeps_exact_batch_error(self):
        # Exercise the production plain-file worker bookkeeping with a broken stage.
        # Later global success must not replace an earlier owner's failed outcome.
        # Restore unrelated native service display state after this fixture probe.
        from MIMIBlender.common import texture_format_service as textures
        saved = json.loads(json.dumps(textures._STATE))  # Preserve independent copies of mutable diagnostic lists.
        outcome = {}
        try:
            with patch.object(textures.dds_match, "DDSReplacementStage", side_effect=RuntimeError("fixture stage failure")):
                textures._worker([], None, outcome)
            self.assertTrue(outcome["finished"])
            self.assertTrue(any("fixture stage failure" in item for item in outcome["errors"]))
            textures._STATE["errors"] = []
            self.assertTrue(outcome["errors"])
        finally:
            textures._STATE.clear()
            textures._STATE.update(saved)

    def test_owned_conversion_failure_is_not_global_success(self):
        # A later/global success cannot authorize this exact failed conversion.
        # Mock file conversion only; the real export generator evaluates outcome.
        # Failed preparation must not allocate a successful Mod artifact folder.
        from MIMIBlender.common import texture_format_service as textures
        image = self.base / "failed-input.png"
        image.write_bytes(b"owned conversion fixture")
        def start(batch, outcome=None):
            outcome.update(finished=True, errors=["fixture owned conversion failure"], cancelled=False)
            return 1
        params = self.params()
        with patch.object(textures, "collect_tree_jobs", return_value=[{"source": str(image), "label": "fixture"}]), \
             patch.object(textures, "plan_for_job", return_value=object()), patch.object(textures, "start_conversion", side_effect=start):
            result = self.finish(self.call("mod.export", params)["id"])
        self.assertEqual(result["status"], "failed", result)
        self.assertEqual(result["error"]["code"], "TEXTURE_CONVERSION_FAILED")
        self.assertFalse(Path(params["output_directory"]).exists())

    def test_changed_source_after_export_yield_is_not_reused(self):
        # Source observations must be refreshed after the user-visible yield.
        # Retain a new fixture source version instead of silently exporting old data.
        # File-generation success cannot be inherited from this changed source.
        params = self.params()
        started = self.call("mod.export", params)
        jobs.step_job(started["id"])
        source = next(self.source.rglob("*.buf"))
        changed = source.read_bytes() + b"fixture source edit"
        source.write_bytes(changed)
        result = self.finish(started["id"])
        self.assertEqual(result["status"], "failed", result)
        self.assertEqual(result["error"]["code"], "STALE_SOURCE")
        self.assertEqual(source.read_bytes(), changed)
        self.assertFalse(list(Path(params["output_directory"]).glob("*.ini")))

    def test_native_generation_failure_retains_output_and_user_data(self):
        # An allocated partial artifact folder remains recoverable on failure.
        # Independent signatures verify that unrelated original objects survive.
        # No generated-file failure is promoted into game or artifact success.
        from MIMIBlender.automation.contract import AutomationError
        params = self.params()
        before = scene_snapshot()
        with patch("MIMIBlender.ui.ui_func_export._export_regular_output", side_effect=AutomationError("NATIVE_EXPORT_FAILED", "fixture")):
            result = self.finish(self.call("mod.export", params)["id"])
        self.assertEqual(result["status"], "failed", result)
        self.assertEqual(result["error"]["code"], "NATIVE_EXPORT_FAILED")
        self.assertTrue(Path(params["output_directory"]).is_dir())
        verify_scene_snapshot(before)

    def test_native_export_has_real_files_and_preserves_scene_source(self):
        # Byte hashes and geometry snapshots independently verify preservation.
        before = source_hashes(self.source)  # Original source bytes are the independent preservation baseline.
        scene = scene_snapshot()  # Include existing user objects unrelated to this export.
        result = self.finish(self.call("mod.export", self.params())["id"])  # Run the actual native exporter through its cooperative job.
        self.assertEqual(result["status"], "succeeded", result)  # Require terminal audited acceptance.
        artifact = result["result"]  # The result publishes real generated-file evidence.
        self.assertTrue(artifact["scene_preserved"])  # Native temporary copies must not alter original scene data.
        self.assertFalse(artifact["in_game_verified"])  # Artifact success is never upgraded to runtime proof.
        self.assertTrue(any(item["path"].endswith(".ini") for item in artifact["files"]))  # An actual configuration file exists.
        self.assertTrue(any(item["path"].endswith(".buf") for item in artifact["files"]))  # Native geometry buffers were actually written.
        verify_scene_snapshot(scene)  # Independently recheck preservation outside the exporter implementation.
        self.assertEqual(source_hashes(self.source), before)  # Source buffers and JSON remain unchanged.
        self.assertFalse((self.source / "Import.json").exists())  # Type decisions were not written into original assets.

    def test_existing_destination_and_stale_graph_fail_before_output(self):
        # Neither an old graph observation nor an existing directory is overwrite permission.
        params = self.params()
        self.tree.nodes.new("MIMINode_Texture_Bind")
        self.assertEqual(self.call("mod.export", params, False)["code"], "STALE_REVISION")
        params = self.params()
        Path(params["output_directory"]).mkdir()
        self.assertEqual(self.call("mod.export", params, False)["code"], "ALREADY_EXISTS")

    def test_user_graph_edit_interrupts_queued_export(self):
        # A user edit after queuing must stop the job before its output allocation.
        params = self.params()  # Capture a valid current observation before queuing.
        started = self.call("mod.export", params)  # Source/target preflight passes for this revision.
        next(node for node in self.tree.nodes if node.bl_idname == "MIMINode_Result_Output").enable_shapekey = True  # Simulate a user's later manual edit.
        result = self.finish(started["id"])  # The queued step must recheck its revision.
        self.assertEqual(result["status"], "interrupted", result)  # User ownership wins instead of stale generation.
        self.assertEqual(result["error"]["code"], "USER_EDIT_DETECTED")  # Stable feedback supports safe retry after rereading.
        self.assertFalse(Path(params["output_directory"]).exists())  # No output is created from that stale request.

    def test_binding_manual_graph_does_not_reimport_geometry(self):
        # Build a user-style unbound graph over an already edited native mesh.
        manual = self.call("blueprint.build", {"name": "manual-" + uuid.uuid4().hex[:8], "present": False,
            "nodes": [{"name": "Mesh", "type": "MIMINode_Object_Info", "properties": {
                "object_name": self.obj.name, "submesh_name": "LOD0.12345678-0"}},
                {"name": "Output", "type": "MIMINode_Result_Output"}],
            "links": [{"from_node": "Mesh", "from_socket": 0, "to_node": "Output", "to_socket": 0}]})
        before = scene_snapshot()
        bound = self.call("workspace.bind", {"tree": manual["tree"], "revision": manual["revision"],
            "source": str(self.source), "logic": "PGR", "work_directory": str(self.work), "present": False})
        verify_scene_snapshot(before)
        self.assertNotEqual(bound["tree"], manual["tree"])
        self.assertNotIn("mimi_ai_workflow", bpy.data.node_groups[manual["tree"]])
        result = self.finish(self.call("mod.export", self.params(bpy.data.node_groups[bound["tree"]]))["id"])
        self.assertEqual(result["status"], "succeeded", result)

    def test_manual_generate_uses_bound_game_not_host_selected_game(self):
        # A real registered native operator must use the AI tree's source/preset.
        # The ordinary host state remains restored after each cooperative step.
        original = GlobalConfig.logic_name
        output = next(node for node in self.tree.nodes if node.bl_idname == "MIMINode_Result_Output")
        try:
            GlobalConfig.logic_name = "UNSUPPORTED_HOST_SELECTION"
            status = bpy.ops.mimi.generate_mod_blueprint(tree_name=self.tree.name, node_name=output.name)
            self.assertEqual(status, {"FINISHED"})
            identifier = self.tree["mimi_ai_last_export_job"]
            self.ids.append(identifier)
            result = self.finish(identifier)
            self.assertEqual(result["status"], "succeeded", result)
            self.assertEqual(GlobalConfig.logic_name, "UNSUPPORTED_HOST_SELECTION")
        finally:
            GlobalConfig.logic_name = original

    def test_face_object_list_ports_and_safe_output_override(self):
        # Reclassify only this test's owned fixture as a native GIMI Face source.
        path = self.source / "LOD0" / FOLDER_NAME / ("TYPE_" + TYPE_NAME) / (FOLDER_NAME + ".json")
        with path.open("r", encoding="utf-8") as handle:
            metadata = json.load(handle)
        metadata.update(GamePreset="GIMI", VertexCount=6, SubMeshRole="Face")
        with path.open("w", encoding="utf-8") as handle:
            json.dump(metadata, handle)
        imported = self.finish(self.call("workspace.import", {"source": str(self.source), "logic": "GIMI",
            "name": "gimi-face-" + uuid.uuid4().hex[:8], "work_directory": str(self.work), "present": False})["id"])
        self.assertEqual(imported["status"], "succeeded", imported)
        tree = bpy.data.node_groups[imported["result"]["tree"]]
        node = next(node for node in tree.nodes if node.bl_idname == "MIMINode_Face_Mod_Export")
        from MIMIBlender.blueprint.blueprint_node_face_mod import _collect_object_nodes
        self.assertEqual(len(_collect_object_nodes(node)), 1)
        node.use_specific_output_folder = True
        node.output_folder = str(self.source)
        before = source_hashes(self.source)
        params = self.params(tree)
        params["output_node"] = node.name
        result = self.finish(self.call("mod.export", params)["id"])
        self.assertEqual(result["status"], "succeeded", result)
        self.assertTrue(any(item["path"].endswith("Face.ini") for item in result["result"]["files"]))
        self.assertEqual(source_hashes(self.source), before)

    @unittest.skipUnless((ROOT / "tmp" / "pgr-split-check").is_dir(), "Optional real cached PGR sources unavailable")
    def test_native_hash_refresh_uses_bound_source_context(self):
        # Manual texture refresh must not inspect the unrelated host workspace.
        imported = self.finish(self.call("workspace.import", {"source": str(ROOT / "tmp" / "pgr-split-check"),
            "logic": "PGR", "name": "hash-context-" + uuid.uuid4().hex[:8],
            "work_directory": str(self.work), "present": False})["id"])
        self.assertEqual(imported["status"], "succeeded", imported)
        base = bpy.data.node_groups[imported["result"]["tree"]]
        source = next(node for node in base.nodes if node.bl_idname == "MIMINode_Object_List")
        output = next(node for node in base.nodes if node.bl_idname == "MIMINode_Result_Output")
        state = self.call("blueprint.inspect", {"tree": base.name})
        clone = self.call("blueprint.build", {"name": "hash-edit-" + uuid.uuid4().hex[:8],
            "base_tree": base.name, "base_revision": state["revision"], "replace_links": True, "present": False,
            "nodes": [{"name": "Hash", "type": "MIMINode_Hash_Texture_Bind"}], "links": [
                {"from_node": source.name, "from_socket": 0, "to_node": "Hash", "to_socket": 0},
                {"from_node": "Hash", "from_socket": 0, "to_node": output.name, "to_socket": 0}]})
        tree = bpy.data.node_groups[clone["tree"]]
        original = GlobalConfig.logic_name
        try:
            GlobalConfig.logic_name = "UNRELATED_HOST"
            status = bpy.ops.mimi.texhashbind_autofill(tree_name=tree.name, node_name="Hash")
            self.assertEqual(status, {"FINISHED"})
            # Native Hash auto-fill deduplicates by mark name, not by Submesh.
            # Both captures share DiffuseMap; one per-mark row is intentional.
            self.assertEqual(len(tree.nodes["Hash"].texture_hash_items), 1)
            self.assertIn(tree.nodes["Hash"].texture_hash_items[0].texture_hash, {"d6f03865", "e3f45a4f"})
            self.assertEqual(GlobalConfig.logic_name, "UNRELATED_HOST")
        finally:
            GlobalConfig.logic_name = original

    @unittest.skipUnless((ROOT / "tmp" / "pgr-split-check").is_dir(), "Optional real cached PGR sources unavailable")
    def test_real_cached_no_lod_workspace_exports_marked_textures(self):
        # The native short-name lookup must support the legacy empty LOD key.
        imported = self.finish(self.call("workspace.import", {"source": str(ROOT / "tmp" / "pgr-split-check"),
            "logic": "PGR", "name": "pgr-textured-" + uuid.uuid4().hex[:8],
            "work_directory": str(self.work), "present": False})["id"])
        self.assertEqual(imported["status"], "succeeded", imported)
        tree = bpy.data.node_groups[imported["result"]["tree"]]
        result = self.finish(self.call("mod.export", self.params(tree))["id"])
        self.assertEqual(result["status"], "succeeded", result)
        textures = [item for item in result["result"]["files"] if item["path"].endswith(".dds")]
        self.assertEqual(len(textures), 2)


# All output fixtures are retained for independent artifact inspection.
# The visible runner reports results without exiting Blender or opening a game.
if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
