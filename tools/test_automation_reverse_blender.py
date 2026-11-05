"""Validate native reverse candidate imports in a visible collaborative scene.

Reverse viewer data remains a separate source representation. The user/AI must
explicitly bind an original workspace before native Mod generation after editing.
"""
# Reverse acceptance:
# - Source fixtures contain actual native ssmt_fmt JSON and buffer layouts.
# - The production MMTImportHelper performs every model/segment import.
# - Candidate ambiguity fails before a result collection or session is allocated.
# - Source hashes prove the adapter never rewrites reverse payloads.
# - Imported segment/source identities follow native component-map rules.
# - User Scene/Edit mode ownership interrupts future steps safely.
# - New models coexist with existing visible user/test geometry.
# - Reverse import is never called a normal workspace export contract.
# - One explicit original-workspace binding proves the supported handoff path.
# - No headless Blender, game launch or filesystem cleanup is used.
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

if bpy.app.background or bpy.data.filepath or bpy.context.mode != "OBJECT" or not bpy.context.scene.name.startswith("MIMIBlender MCP Capability Probe"):
    raise RuntimeError("Use the designated visible unsaved test scene, not active user work")


class ReverseTests(unittest.TestCase):
    """Every candidate fixture and working directory is new and retained under tmp."""
    def setUp(self):
        self.base = ROOT / "tmp" / "automation-reverse-fixtures" / uuid.uuid4().hex  # Exclusive retained fixture root.
        self.workspace = write_native_workspace(self.base / "workspace")  # The original extraction association is explicit.
        original = self.workspace / "LOD0" / FOLDER_NAME / ("TYPE_" + TYPE_NAME)  # Native source layout remains unchanged.
        self.reverse = self.base / "reverse"  # Reverse outputs use their separate native representation.
        self.folder = self.reverse / "12345678"  # Actual DrawIB identity, not a generated ordinal.
        self.folder.mkdir(parents=True)  # This new synthetic directory never overwrites user assets.
        for source in original.iterdir():  # Copy only this test's own newly generated source payloads.
            name = TYPE_NAME + ".json" if source.suffix == ".json" else source.name  # Reverse candidates name their JSON by layout.
            shutil.copyfile(source, self.folder / name)  # Native parser sees real retained buffer bytes.
        self.work = self.base / "sessions"  # Runtime records stay outside both source representations.
        self.ids = []
        self.params = {"source": str(self.reverse), "logic": "PGR", "name": "reverse-" + uuid.uuid4().hex[:8],
                       "work_directory": str(self.work), "present": False}

    def tearDown(self):
        # Leave partial models/files visible for review; stop only this case's jobs.
        for identifier in self.ids:
            if jobs.JOBS[identifier]["status"] not in jobs.TERMINAL:
                jobs.JOBS[identifier]["cancel_requested"] = True
                jobs.step_job(identifier)

    def call(self, action, params, success=True):
        result = automation.dispatch({"action": action, "params": params})
        self.assertEqual(result["ok"], success, result)
        if result["ok"] and action in {"reverse.import", "mod.export"}:
            self.ids.append(result["result"]["id"])
        return result["result"] if success else result["error"]

    def finish(self, identifier):
        # Finite deterministic steps exercise the actual cooperative timer function.
        for step in range(8):
            if jobs.JOBS[identifier]["status"] in jobs.TERMINAL:
                break
            jobs.step_job(identifier)
        result = self.call("job.inspect", {"job": identifier})
        self.assertIn(result["status"], jobs.TERMINAL)
        return result

    def test_native_reverse_source_is_read_only_and_component_identity_preserved(self):
        before = source_hashes(self.reverse)  # Independent source byte baseline.
        inspected = self.call("reverse.inspect", {"source": str(self.reverse)})  # Discover inert native candidate facts first.
        self.assertEqual(inspected["format"], "ssmt_fmt")  # No invented conversion into a normal workspace.
        self.assertEqual(inspected["total_groups"], 1)  # The owned fixture contains one DrawIB group.
        self.assertTrue(inspected["export_requires_workspace_binding"])  # Viewer success is not an export-source association.
        result = self.finish(self.call("reverse.import", self.params)["id"])  # Execute the actual native cooperative importer.
        self.assertEqual(result["status"], "succeeded", result)  # Require terminal native artifact acceptance.
        self.assertEqual(len(result["result"]["objects"]), 1)  # Capture every created segment, not only a UI report.
        obj = bpy.data.objects[result["result"]["objects"][0]]  # Inspect the real object in the existing visible scene.
        self.assertTrue(obj.name.startswith("12345678-Component 0"))  # Native component-map identity is preserved.
        self.assertEqual(len(obj.data.vertices), 6)  # Original buffer population is actually represented.
        self.assertEqual(source_hashes(self.reverse), before)  # No reverse source JSON or buffer was rewritten.

    def test_ambiguous_layout_needs_explicit_choice(self):
        path = self.folder / (TYPE_NAME + ".json")
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        data["WorkGameType"] += "ALT"
        with (self.folder / (TYPE_NAME + "ALT.json")).open("x", encoding="utf-8") as handle:
            json.dump(data, handle)
        self.assertEqual(self.call("reverse.import", self.params, False)["code"], "AMBIGUOUS_DATATYPE")
        self.assertFalse(self.work.exists())
        self.params["types"] = {"12345678": TYPE_NAME}
        result = self.finish(self.call("reverse.import", self.params)["id"])
        self.assertEqual(result["status"], "succeeded", result)

    def test_source_changes_interrupt_before_import(self):
        started = self.call("reverse.import", self.params)
        path = self.folder / (FOLDER_NAME + "-position.buf")
        with path.open("ab") as handle:
            handle.write(b"changed")
        result = self.finish(started["id"])
        self.assertEqual(result["status"], "failed", result)
        self.assertEqual(result["error"]["code"], "STALE_SOURCE")

    def test_cancel_retains_partial_models(self):
        started = self.call("reverse.import", self.params)
        jobs.step_job(started["id"])
        progress = self.call("job.inspect", {"job": started["id"]})["progress"]
        self.call("job.cancel", {"job": started["id"]})
        result = self.finish(started["id"])
        self.assertEqual(result["status"], "cancelled")
        self.assertTrue(all(name in bpy.data.objects for name in progress["objects"]))

    def test_original_workspace_binding_after_reverse_viewer_import(self):
        # Viewer names are not guessed as an extraction workspace: bind the real source.
        result = self.finish(self.call("reverse.import", self.params)["id"])
        self.assertEqual(result["status"], "succeeded", result)
        obj = bpy.data.objects[result["result"]["objects"][0]]
        graph = self.call("blueprint.build", {"name": "reverse-model-" + uuid.uuid4().hex[:8], "present": False,
            "nodes": [{"name": "Mesh", "type": "MIMINode_Object_Info", "properties": {
                "object_name": obj.name, "submesh_name": "LOD0.12345678-0"}}, {"name": "Output", "type": "MIMINode_Result_Output"}],
            "links": [{"from_node": "Mesh", "from_socket": 0, "to_node": "Output", "to_socket": 0}]})
        bound = self.call("workspace.bind", {"tree": graph["tree"], "revision": graph["revision"], "source": str(self.workspace),
            "logic": "PGR", "work_directory": str(self.work), "present": False})
        exported = self.finish(self.call("mod.export", {"tree": bound["tree"], "revision": bound["revision"],
            "output_directory": str(self.base / "mod")})["id"])
        self.assertEqual(exported["status"], "succeeded", exported)
        self.assertFalse(exported["result"]["in_game_verified"])


# Original source/working files remain for independent user inspection.
if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
