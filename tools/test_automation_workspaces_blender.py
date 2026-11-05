"""Validate cooperative native imports in the existing visible MCP test scene.

Fixtures and session records stay under tmp. Source hashes, user geometry and
configuration snapshots are compared independently of the importer's reports.
No background Blender or replacement user scene is launched by these tests.
"""
# Acceptance boundaries:
# - The public automation API validates and starts every source import.
# - Deterministic tests advance a bounded number of the actual timer steps.
# - Separate live acceptance verifies real automatic timer scheduling.
# - Source fixtures are newly created synthetic buffers, not user resources.
# - The native MMTImportHelper still creates every mesh and graph under test.
# - Source files are hashed before and after the complete native import.
# - Existing scene meshes are hashed before and after importing new components.
# - Existing objects are never cleared to make a test pass.
# - Type ambiguity must fail before a session directory is allocated.
# - Missing source dependencies cannot become partial-success UI reports.
# - Stale source observations cannot authorize the later import request.
# - Source-root containment rejects buffers outside the declared fixture root.
# - Source Import.json must not be created by the AI importer.
# - The private type record must remain in the returned session directory.
# - Frozen native import options apply only during one main-thread step.
# - Transient host/workspace configuration must restore even on exceptions.
# - Cancelling retains already yielded data as explicit partial work.
# - A scene switch interrupts rather than switching the user back.
# - Entering Edit mode interrupts rather than forcing Object mode.
# - Job records use exact IDs and return JSON data, not generator objects.
# - No assertion claims correct in-game rendering from a generated blueprint.
# - Optional real-workspace acceptance is reported separately from fixtures.
import hashlib
import json
from pathlib import Path
import shutil
import sys
import unittest
import uuid

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from automation_fixture import write_native_workspace, source_hashes, TYPE_NAME, FOLDER_NAME
from MIMIBlender import automation
from MIMIBlender.automation import jobs
from MIMIBlender.automation.context import workflow_context
from MIMIBlender.common.global_config import GlobalConfig

if bpy.app.background or bpy.data.filepath or not bpy.context.scene.name.startswith("MIMIBlender MCP Capability Probe"):
    raise RuntimeError("Use the designated visible unsaved test scene, not a user project")


def mesh_hash(obj):
    """Independently fingerprint existing geometry, groups, UVs and shape keys."""
    mesh = obj.data
    data = {"vertices": [[list(vertex.co), [(group.group, group.weight) for group in vertex.groups]] for vertex in mesh.vertices],
            "polygons": [list(polygon.vertices) for polygon in mesh.polygons],
            "groups": [group.name for group in obj.vertex_groups],
            "uv": [[list(item.uv) for item in layer.data] for layer in mesh.uv_layers],
            "materials": [slot.material.name if slot.material else None for slot in obj.material_slots]}
    if mesh.shape_keys:
        data["shapes"] = [(key.name, [list(vertex.co) for vertex in key.data]) for key in mesh.shape_keys.key_blocks]
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


class WorkspaceTests(unittest.TestCase):
    """Every test owns an exclusive source fixture and working-root namespace."""

    def setUp(self):
        # Keep generated evidence instead of recursively deleting test directories.
        # Native LOD/type folder naming belongs to the external source contract.
        self.base = ROOT / "tmp" / "automation-test-fixtures" / uuid.uuid4().hex
        self.source = write_native_workspace(self.base / "source")
        self.work = self.base / "sessions"
        self.name = "ai-import-" + uuid.uuid4().hex[:10]
        self.params = {"source": str(self.source), "logic": "PGR", "name": self.name,
                       "work_directory": str(self.work), "present": False}
        self.jobs = []

    def tearDown(self):
        # A failing assertion must not leave an owned test job blocking later cases.
        # Cancellation retains partial data and never deletes user resources.
        for identifier in self.jobs:
            if jobs.JOBS[identifier]["status"] not in jobs.TERMINAL:
                jobs.JOBS[identifier]["cancel_requested"] = True
                jobs.step_job(identifier)

    def call(self, action, params, success=True):
        # The same request/result contract is used by external MCP callers.
        # Stable error codes are asserted rather than translated UI captions.
        result = automation.dispatch({"action": action, "params": params})
        self.assertEqual(result["ok"], success, result)
        if action == "workspace.import" and result["ok"]:
            self.jobs.append(result["result"]["id"])
        return result["result"] if success else result["error"]

    def finish(self, identifier):
        # This is bounded deterministic execution of the real step function.
        # It does not sleep or busy-poll a separate running process/job.
        for index in range(5):
            if jobs.JOBS[identifier]["status"] in jobs.TERMINAL:
                break
            jobs.step_job(identifier)
        result = self.call("job.inspect", {"job": identifier})
        self.assertIn(result["status"], jobs.TERMINAL)
        return result

    def test_native_import_preserves_source_user_geometry_and_settings(self):
        # Actual source bytes and preexisting user geometry must stay identical.
        # A FINISHED-like status alone would not establish either preservation.
        sources = source_hashes(self.source)  # Hash bytes independently of the production stat token.
        original = {obj: mesh_hash(obj) for obj in bpy.data.objects if obj.type == "MESH"}  # Existing user/test geometry is the preservation baseline.
        host = (GlobalConfig.gamename, GlobalConfig.workspacename, GlobalConfig.logic_name)  # Host choices must not become the AI session defaults.
        mirror = bpy.context.scene.mimi_global_properties.mirror_workflow_mode  # Capture the user's current import orientation.
        inspection = self.call("workspace.inspect", {"source": str(self.source)})  # Observe before requesting the native import.
        self.assertEqual(inspection["total_components"], 1)  # The synthetic fixture has exactly one component.
        self.assertTrue(inspection["components"][0]["choices"][0]["valid"])  # Dependencies are actually present.
        self.params["source_revision"] = inspection["revision"]  # Tie the request to that observation.
        started = self.call("workspace.import", self.params)  # Production validation queues a real generator.
        self.assertEqual(started["status"], "queued")  # Queuing is not declared complete.
        completed = self.finish(started["id"])  # Exercise the real cooperative native step function.
        self.assertEqual(completed["status"], "succeeded", completed)  # Require terminal artifact acceptance.
        result = completed["result"]  # The published result contains only JSON identities/metadata.
        self.assertEqual(len(result["objects"]), 1)  # No silently missing or duplicated segment object.
        obj = bpy.data.objects[result["objects"][0]]  # Inspect the produced native bpy mesh.
        self.assertEqual(len(obj.data.vertices), 6)  # VertexCount zero must infer the real buffer population.
        self.assertEqual(len(obj.data.polygons), 2)  # Both source triangles must survive.
        self.assertEqual(source_hashes(self.source), sources)  # No source JSON or buffer was modified.
        self.assertEqual({item: mesh_hash(item) for item in original}, original)  # New imports cannot transform old user meshes.
        self.assertEqual((GlobalConfig.gamename, GlobalConfig.workspacename, GlobalConfig.logic_name), host)  # Transient global routing is restored.
        self.assertEqual(bpy.context.scene.mimi_global_properties.mirror_workflow_mode, mirror)  # Frozen request settings do not persist into manual work.
        self.assertIsNone(GlobalConfig._automation_override)  # No lingering scope may influence the next user operation.
        self.assertFalse((self.source / "Import.json").exists())  # Original assets remain read-only.
        record = Path(result["workflow"]["import_selection"])  # Type decisions belong to the new private session.
        self.assertTrue(record.is_file())  # A real selection record was produced.
        self.assertIn(self.work, record.parents)  # It cannot be redirected into the source or game Mods root.
        self.assertIn("mimi_ai_workflow", bpy.data.node_groups[result["tree"]])  # Ordinary user saves retain workflow provenance.

    def test_cancellation_retains_visible_partial_artifacts(self):
        # Cancel after the first native component has been committed/yielded.
        # The partial mesh must remain editable rather than being silently deleted.
        started = self.call("workspace.import", self.params)
        jobs.step_job(started["id"])
        progress = self.call("job.inspect", {"job": started["id"]})["progress"]
        self.assertEqual(progress["done"], 1)
        self.call("job.cancel", {"job": started["id"]})
        cancelled = self.finish(started["id"])
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertTrue(all(name in bpy.data.objects for name in progress["objects"]))
        self.assertEqual(bpy.data.collections[progress["collection"]]["mimi_ai_import_status"], "partial")
        self.assertIsNone(GlobalConfig._automation_override)

    def test_scene_change_does_not_replace_user_scene(self):
        # Simulate a stale scene identity without opening/replacing any real file.
        # The job must terminate before its generator creates session artifacts.
        current = bpy.context.scene
        started = self.call("workspace.import", self.params)
        jobs.JOBS[started["id"]]["scene_pointer"] = -1
        result = self.finish(started["id"])
        self.assertEqual(result["status"], "interrupted")
        self.assertEqual(result["error"]["code"], "SCENE_CHANGED")
        self.assertEqual(bpy.context.scene, current)
        self.assertFalse(self.work.exists())

    def test_user_edit_mode_interrupts_without_forcing_mode_switch(self):
        # Enter Edit mode on a newly created fixture object after queuing a job.
        # The workflow must stop while leaving the user's current mode untouched.
        started = self.call("workspace.import", self.params)
        bpy.ops.mesh.primitive_cube_add()
        modes = [item.identifier for item in bpy.ops.object.mode_set.get_rna_type().properties["mode"].enum_items]
        try:
            bpy.ops.object.mode_set(mode=next(item for item in modes if item == "EDIT"))
            result = self.finish(started["id"])
            self.assertEqual(result["status"], "interrupted")
            self.assertEqual(result["error"]["code"], "USER_EDIT_IN_PROGRESS")
            self.assertEqual(bpy.context.mode, "EDIT_MESH")
        finally:
            bpy.ops.object.mode_set(mode=next(item for item in modes if item == "OBJECT"))
        self.assertFalse(self.work.exists())

    def test_type_ambiguity_fails_before_creating_work(self):
        # Two equally valid native layouts need an explicit caller choice.
        # The API must not quietly choose the first directory that happens to sort.
        original = self.source / "LOD0" / FOLDER_NAME / ("TYPE_" + TYPE_NAME)
        alternate = original.with_name("TYPE_" + TYPE_NAME + "ALT")
        shutil.copytree(original, alternate)
        path = alternate / (FOLDER_NAME + ".json")
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        data["WorkGameType"] += "ALT"
        with path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle)
        error = self.call("workspace.import", self.params, False)
        self.assertEqual(error["code"], "AMBIGUOUS_DATATYPE")
        self.assertFalse(self.work.exists())
        self.params["types"] = {"LOD0.12345678-0": TYPE_NAME}
        result = self.finish(self.call("workspace.import", self.params)["id"])
        self.assertEqual(result["status"], "succeeded", result)

    def test_stale_source_observation_is_rejected(self):
        # Change only this test's owned source JSON after observing its revision.
        # The original source token must not authorize the now different request.
        state = self.call("workspace.inspect", {"source": str(self.source)})
        path = self.source / "LOD0" / FOLDER_NAME / ("TYPE_" + TYPE_NAME) / (FOLDER_NAME + ".json")
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        data["VertexCount"] = 6
        with path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle)
        self.params["source_revision"] = state["revision"]
        self.assertEqual(self.call("workspace.import", self.params, False)["code"], "STALE_SOURCE")
        self.assertFalse(self.work.exists())

    def test_user_rename_keeps_source_binding_identity(self):
        # Rename an already yielded object before the final graph is created.
        # The source mapping must follow its native pointer rather than old text.
        started = self.call("workspace.import", self.params)
        jobs.step_job(started["id"])
        progress = self.call("job.inspect", {"job": started["id"]})["progress"]
        obj = bpy.data.objects[progress["objects"][0]]
        obj.name = "user-renamed-" + uuid.uuid4().hex[:8]
        finished = self.finish(started["id"])
        self.assertEqual(finished["status"], "succeeded", finished)
        self.assertIn(obj.name, finished["result"]["objects"])
        self.assertEqual(obj["mimi_ai_session"], progress["session"])

    def test_user_transform_is_not_overwritten_by_final_binding(self):
        # The user can take ownership of a visible component between timer steps.
        # Final native alignment/binding must stop instead of replacing that edit.
        started = self.call("workspace.import", self.params)
        jobs.step_job(started["id"])
        obj = bpy.data.objects[jobs.JOBS[started["id"]]["progress"]["objects"][0]]
        obj.location.x = 3.0
        result = self.finish(started["id"])
        self.assertEqual(result["status"], "interrupted")
        self.assertEqual(result["error"]["code"], "USER_EDIT_DETECTED")
        self.assertEqual(obj.location.x, 3.0)

    def test_source_escape_and_unsafe_workspace_names_are_rejected(self):
        # Source dependency paths cannot leave the explicitly authorized root.
        # Workspace labels cannot later become an INI path traversal either.
        self.params["workspace_name"] = "../../unsafe-output"
        self.assertEqual(self.call("workspace.import", self.params, False)["code"], "INVALID_WORKSPACE_NAME")
        self.params.pop("workspace_name")
        path = self.source / "LOD0" / FOLDER_NAME / ("TYPE_" + TYPE_NAME) / (FOLDER_NAME + ".json")
        with path.open("r", encoding="utf-8") as handle:
            metadata = json.load(handle)
        metadata["CategoryBufferList"][0]["FileName"] = "../../../../outside.buf"
        with path.open("w", encoding="utf-8") as handle:
            json.dump(metadata, handle)
        source = self.call("workspace.inspect", {"source": str(self.source)})
        candidate = source["components"][0]["choices"][0]
        self.assertFalse(candidate["valid"])
        self.assertEqual(candidate["errors"][0]["code"], "SOURCE_PATH_ESCAPE")
        self.assertFalse(self.work.exists())

    @unittest.skipUnless((ROOT / "tmp" / "pgr-split-check").is_dir(), "Optional cached PGR source workspace is unavailable")
    def test_optional_real_cached_workspace_source_bytes_preserved(self):
        # This cache contains real PGR buffer payloads with the split UV layout.
        # It is not a synthetic source fixture and no file is copied or rewritten.
        source = ROOT / "tmp" / "pgr-split-check"
        before = source_hashes(source)
        params = dict(self.params, source=str(source), workspace_name="pgr-source-review")
        result = self.finish(self.call("workspace.import", params)["id"])
        self.assertEqual(result["status"], "succeeded", result)
        self.assertEqual(result["result"]["components"], 2)
        self.assertEqual(source_hashes(source), before)

    def test_context_restores_host_state_after_failure(self):
        # Existing path helpers must honor explicit scope only within this block.
        # Restoration is checked after an exception, not only the success route.
        host = (GlobalConfig.logic_name, GlobalConfig.workspacename)
        config = {"workspace": str(self.source), "workspace_name": "owned-scope", "logic": "PGR",
                  "import_selection": str(self.base / "selection.json"), "output": str(self.base / "output")}
        with self.assertRaises(ValueError):
            with workflow_context(config, {"mirror_workflow_mode": "NON_MIRRORED"}):
                self.assertEqual(GlobalConfig.path_workspace_folder(), str(self.source))
                self.assertEqual(GlobalConfig.path_import_selection_json(), config["import_selection"])
                self.assertEqual(GlobalConfig.path_mods_folder(), config["output"])
                GlobalConfig.read_from_main_json()
                self.assertEqual(GlobalConfig.logic_name, "PGR")
                raise ValueError("owned fixture failure")
        self.assertEqual((GlobalConfig.logic_name, GlobalConfig.workspacename), host)
        self.assertIsNone(GlobalConfig._automation_override)

    def test_job_queries_do_not_expose_mutable_runtime_records(self):
        # Editing a returned progress dictionary cannot change the running job.
        # Cooperative cancellation then terminates this deliberately unadvanced job.
        started = self.call("workspace.import", self.params)
        observed = self.call("job.inspect", {"job": started["id"]})
        observed["progress"]["done"] = 999
        self.assertEqual(jobs.JOBS[started["id"]]["progress"]["done"], 0)
        self.call("job.cancel", {"job": started["id"]})
        self.assertEqual(self.finish(started["id"])["status"], "cancelled")


# All cases run in one real visible desktop and leave it open for inspection.
# The fixture runner reports structured results without calling sys.exit.
if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
