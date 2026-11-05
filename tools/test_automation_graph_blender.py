"""Exercise typed settings and copy-on-write graph creation in real Blender.

Run through the visible MCP test runner in a designated unsaved test scene.
All fixtures are in memory. No saved user scene or source workspace is changed.
"""
# Acceptance contract:
# - Every test invokes the actual public automation dispatcher.
# - Schemas and bpy metadata are production code, not test substitutes.
# - Graph identity is explicit even with no active node editor.
# - A build succeeds only by returning a new named tree.
# - A base version must keep its original nodes, links and collection rows.
# - A conflicting version name must never overwrite existing data.
# - Unknown node types cannot become arbitrary bpy node creation requests.
# - Numeric property validation happens before Blender can clamp a value.
# - Enum validation covers both static and callback-declared choices.
# - Object List rows must match their corresponding output sockets.
# - Texture rows must retain enabled state, source type and slot identity.
# - Group interfaces must use native custom object-flow sockets.
# - Invalid graph links cannot be mistaken for partial success.
# - Occupied single-input sockets cannot be replaced accidentally.
# - Directed cycles must invalidate a strict staged graph.
# - Draft graphs must explicitly retain invalidity diagnostics.
# - Failed staging must not leave an extra blueprint datablock.
# - Failed staging must restore legacy Object Info UUID side effects.
# - Node creation must not delete the referenced mesh object.
# - Parent frames are resolved after the node population exists.
# - Settings batches preflight every field before assignment.
# - Assignment failure is injected only at the actual setter boundary.
# - Rollback is tested against the original in-memory setting values.
# - No test patches a game exporter or claims in-game acceptance.
# - No test generates, overwrites or deletes physical Mod files.
# - Existing user preferences and startup files remain unsaved.
# - Exact names avoid dependence on translated default node captions.
# - Socket indices are validated rather than inferred from display labels.
# - The test runner ignores Blender's command-line arguments.
import builtins
import importlib
from pathlib import Path
import sys
import unittest
import uuid
from unittest.mock import patch

import bpy


# Import the repository under test in an isolated process.
# Registration happens once; each test creates uniquely named fixtures.
# Native factory objects are not assumed to survive add-on initialization.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
if bpy.app.background or bpy.data.filepath or not bpy.context.scene.name.startswith("MIMIBlender MCP Capability Probe"):
    raise RuntimeError("Use the designated visible unsaved MCP test scene, not a user project")
addon = importlib.import_module(ROOT.name)
if not hasattr(bpy.types.Scene, "mimi_global_properties"):
    addon.register()
from MIMIBlender import automation
from MIMIBlender.blueprint.blueprint_node_obj import OBJECT_PERSISTENT_ID_KEY
RUN_ID = uuid.uuid4().hex[:6]


class GraphTests(unittest.TestCase):
    """Named in-memory fixtures make every request independently reproducible."""

    def setUp(self):
        # Use one unbound mesh as a graph source, not an existing user object.
        # Every test version name derives from its unique unittest method name.
        bpy.ops.mesh.primitive_cube_add()
        self.obj = bpy.context.active_object
        self.obj.name = self._testMethodName + " mesh"
        self.name = RUN_ID + "_" + self._testMethodName

    def call(self, action, params, success=True):
        # All graph actions must use stable envelopes through the public entry.
        # A failure helper verifies error status rather than swallowing exceptions.
        if action == "blueprint.build":
            params.setdefault("present", False)
        result = automation.dispatch({"action": action, "params": params})
        self.assertEqual(result["ok"], success, result)
        return result["result"] if success else result["error"]

    def spec(self, name=None):
        # The minimal complete graph contains one Object Info and one Output.
        # It uses no implicit workspace, editor selection or output node lookup.
        return {"name": name or self.name, "nodes": [
            {"name": "Mesh", "type": "MIMINode_Object_Info", "properties": {"object_name": self.obj.name}},
            {"name": "Output", "type": "MIMINode_Result_Output"},
        ], "links": [{"from_node": "Mesh", "from_socket": 0, "to_node": "Output", "to_socket": 0}]}

    def test_new_graph_and_version_preservation(self):
        # Copy-on-write edits must keep the original version's graph unchanged.
        # The new version changes one property while retaining object flow.
        first = self.call("blueprint.build", self.spec())  # Establish a valid observed base version.
        base = bpy.data.node_groups[first["tree"]]  # Hold the actual native tree for preservation checks.
        second = self.call("blueprint.build", {"name": self.name + " v2", "base_tree": base.name, "base_revision": first["revision"],
            "nodes": [{"name": "Mesh", "type": "MIMINode_Object_Info", "properties": {"skip_draw": True}}]})
        self.assertTrue(second["validation"]["valid"])  # The patched version remains export-graph structurally valid.
        self.assertFalse(base.nodes["Mesh"].skip_draw)  # The user's original flag is untouched.
        self.assertTrue(bpy.data.node_groups[second["tree"]].nodes["Mesh"].skip_draw)  # Only the new version has the AI change.
        self.assertEqual(len(base.links), 1)  # Copying must not steal the original edge.
        self.assertEqual(second["graph"]["total_nodes"], 2)  # No hidden duplicate source/output nodes.
        error = self.call("blueprint.build", self.spec(), False)  # Reusing the name must refuse overwrite.
        self.assertEqual(error["code"], "ALREADY_EXISTS")  # Clients can repair a name conflict deterministically.

    def test_failed_build_restores_uuid_and_discards_only_stage(self):
        # Native Object Info assignment creates an object UUID before linking.
        # An invalid socket must undo that side effect and discard the new tree.
        self.assertNotIn(OBJECT_PERSISTENT_ID_KEY, self.obj)
        old_trees = set(bpy.data.node_groups)
        spec = self.spec()
        spec["links"][0]["from_socket"] = 99
        error = self.call("blueprint.build", spec, False)
        self.assertEqual(error["code"], "INVALID_SOCKET")
        self.assertEqual(set(bpy.data.node_groups), old_trees)
        self.assertNotIn(OBJECT_PERSISTENT_ID_KEY, self.obj)
        self.assertIn(self.obj.name, bpy.data.objects)

    def test_direct_cycles_and_occupied_inputs_fail(self):
        # A custom texture pass-through makes a simple directed cycle possible.
        # Adding that cycle must fail even if Blender accepted the native links.
        spec = {"name": self.name, "nodes": [
            {"name": "A", "type": "MIMINode_Texture_Bind"},
            {"name": "B", "type": "MIMINode_Texture_Bind"},
            {"name": "Output", "type": "MIMINode_Result_Output"},
        ], "links": [
            {"from_node": "A", "from_socket": 0, "to_node": "B", "to_socket": 0},
            {"from_node": "B", "from_socket": 0, "to_node": "A", "to_socket": 0},
        ]}
        error = self.call("blueprint.build", spec, False)
        self.assertEqual(error["code"], "INVALID_BLUEPRINT")
        self.assertIn("GRAPH_CYCLE", [item["code"] for item in error["details"]["errors"]])
        # Duplicate single-input connections cannot replace existing branches.
        # The duplicate request must leave no staged tree behind either.
        duplicate = self.spec(self.name + " duplicate")
        duplicate["links"].append(dict(duplicate["links"][0]))
        self.assertEqual(self.call("blueprint.build", duplicate, False)["code"], "INPUT_OCCUPIED")

    def test_object_list_rows_and_texture_rows(self):
        # Native list helpers create one aggregate socket plus one per row.
        # Texture rows remain typed RNA data rather than opaque dictionary blobs.
        result = self.call("blueprint.build", {"name": self.name, "nodes": [
            {"name": "Objects", "type": "MIMINode_Object_List", "properties": {"object_items": [
                {"object_name": self.obj.name, "submesh_name": "LOD0.12345678-0", "skip_draw": False}]}},
            {"name": "Texture", "type": "MIMINode_Texture_Bind", "properties": {"texture_slot_items": [
                {"slot": "ps-t0", "source_type": "FILE", "file_path": "C:/fixture/texture.dds"}]}},
            {"name": "Output", "type": "MIMINode_Result_Output"},
        ], "links": [
            {"from_node": "Objects", "from_socket": 0, "to_node": "Texture", "to_socket": 0},
            {"from_node": "Texture", "from_socket": 0, "to_node": "Output", "to_socket": 0},
        ]})
        tree = bpy.data.node_groups[result["tree"]]
        self.assertEqual(len(tree.nodes["Objects"].outputs), 2)
        self.assertEqual(tree.nodes["Objects"].object_items[0].object_ref, self.obj)
        self.assertEqual(tree.nodes["Texture"].texture_slot_items[0].source_type, "FILE")
        # Native tree copying must also preserve custom collection rows.
        # It may not rely on ID-property JSON copies that lose PropertyGroups.
        copy = self.call("blueprint.build", {"name": self.name + " v2", "base_tree": tree.name, "base_revision": result["revision"], "nodes": []})
        self.assertEqual(len(bpy.data.node_groups[copy["tree"]].nodes["Objects"].object_items), 1)

    def test_static_enum_and_numeric_constraints(self):
        # Declared hard numeric limits are checked before native RNA clamping.
        # Enum identifiers come from registration, never hardcoded in edit code.
        spec = self.spec()
        spec["nodes"].append({"name": "Timeline", "type": "MIMINode_TimeSwitch", "properties": {"fps": -1.0}})
        self.assertEqual(self.call("blueprint.build", spec, False)["code"], "INVALID_ARGUMENT")
        spec["nodes"][-1]["properties"] = {"playback_mode": "not-a-mode"}
        self.assertEqual(self.call("blueprint.build", spec, False)["code"], "INVALID_ARGUMENT")
        spec["nodes"][-1]["properties"] = {"playback_mode": "TRIGGER", "fps": 30.0}
        result = self.call("blueprint.build", spec)
        self.assertEqual(bpy.data.node_groups[result["tree"]].nodes["Timeline"].fps, 30.0)

    def test_draft_and_missing_reference_diagnostics(self):
        # Draft mode is explicit; validation still reports missing references.
        # A strict retry with the same invalid object must fail and roll back.
        spec = self.spec()
        spec["nodes"][0]["properties"]["object_name"] = "missing-source-object"
        spec["strict"] = False
        result = self.call("blueprint.build", spec)
        self.assertFalse(result["validation"]["valid"])
        checked = self.call("blueprint.validate", {"tree": result["tree"]})
        self.assertFalse(checked["valid"])
        spec["name"] += " strict"
        spec["strict"] = True
        self.assertEqual(self.call("blueprint.build", spec, False)["code"], "INVALID_BLUEPRINT")

    def test_custom_group_interface_and_pointer(self):
        # A child tree has native interface sockets and native group primitives.
        # The parent uses an exact named pointer to the child's registered type.
        child = self.call("blueprint.build", {"name": self.name + " child", "interface": [
            {"name": "Object", "direction": "INPUT"}, {"name": "Result", "direction": "OUTPUT"}],
            "nodes": [{"name": "In", "type": "NodeGroupInput"}, {"name": "Out", "type": "NodeGroupOutput"}],
            "links": [{"from_node": "In", "from_socket": 0, "to_node": "Out", "to_socket": 0}]})
        spec = self.spec()
        spec["nodes"].append({"name": "Group", "type": "SSMTBlueprintGroupNode", "properties": {"node_tree": child["tree"]}})
        spec["links"] = [
            {"from_node": "Mesh", "from_socket": 0, "to_node": "Group", "to_socket": 0},
            {"from_node": "Group", "from_socket": 0, "to_node": "Output", "to_socket": 0}]
        result = self.call("blueprint.build", spec)
        self.assertTrue(result["validation"]["valid"])

    def test_settings_dynamic_enum_and_preflight(self):
        # Resolve callback-declared enum identifiers from deferred RNA metadata.
        # Invalid sibling values cannot apply a preceding valid bool change.
        properties = bpy.context.scene.mimi_global_properties
        original_mode = properties.workspace_source_mode
        original_open = properties.open_mod_folder_after_generate_mod
        result = self.call("settings.update", {"owner": "mimi_global_properties", "values": {"workspace_source_mode": "CUSTOM"}})
        self.assertEqual(result["values"]["workspace_source_mode"], "CUSTOM")
        error = self.call("settings.update", {"owner": "mimi_global_properties", "values": {
            "open_mod_folder_after_generate_mod": not original_open, "workspace_source_mode": "invalid"}}, False)
        self.assertEqual(error["code"], "INVALID_ARGUMENT")
        self.assertEqual(properties.open_mod_folder_after_generate_mod, original_open)
        self.call("settings.update", {"owner": "mimi_global_properties", "values": {"workspace_source_mode": original_mode}})

    def test_stale_user_edit_is_not_overwritten(self):
        # Simulate a user editing the graph after the AI's state query.
        # The old observation token must not authorize a new patch version.
        first = self.call("blueprint.build", self.spec())
        tree = bpy.data.node_groups[first["tree"]]
        tree.nodes["Mesh"].skip_draw = True
        error = self.call("blueprint.build", {"name": self.name + " stale", "base_tree": tree.name,
            "base_revision": first["revision"], "nodes": []}, False)
        self.assertEqual(error["code"], "STALE_REVISION")
        self.assertTrue(tree.nodes["Mesh"].skip_draw)
        self.assertNotIn(self.name + " stale", bpy.data.node_groups)

    def test_presentation_failure_restores_user_editor(self):
        # Simulate an exception after the new graph was bound to its editor.
        # Rollback must restore the prior graph before discarding the new stage.
        spec = self.spec()
        spec["present"] = True
        first = self.call("blueprint.build", spec)
        next_spec = {"name": self.name + " failed", "base_tree": first["tree"],
                     "base_revision": first["revision"], "nodes": [], "present": True}
        with patch("MIMIBlender.automation.presentation.redraw", side_effect=[ValueError("injected redraw failure"), None]):
            error = self.call("blueprint.build", next_spec, False)
        self.assertEqual(error["code"], "PRESENTATION_FAILED")
        self.assertNotIn(next_spec["name"], bpy.data.node_groups)
        self.assertEqual(bpy.context.scene.mimi_global_properties.selected_blueprint_name, first["tree"])
        areas = [area for area in bpy.context.window.screen.areas if area.type == "NODE_EDITOR"]
        self.assertTrue(any(area.spaces.active.node_tree.name == first["tree"] for area in areas))

    def test_visible_presentation_updates_real_editor(self):
        # The result must be bound to a real existing desktop editor.
        # Users should not need a click to reveal the graph the AI just built.
        spec = self.spec()
        spec["present"] = True
        result = self.call("blueprint.build", spec)
        self.assertTrue(result["presentation"]["visible"])
        self.assertEqual(bpy.context.scene.mimi_global_properties.selected_blueprint_name, result["tree"])
        areas = [area for area in bpy.context.window.screen.areas if area.type == "NODE_EDITOR"]
        self.assertTrue(any(area.spaces.active.node_tree.name == result["tree"] for area in areas))
        shown = self.call("scene.present", {"objects": [self.obj.name]})
        self.assertTrue(shown["visible"])
        self.assertEqual(bpy.context.active_object, self.obj)
        self.assertTrue(self.obj.select_get())

    def test_settings_assignment_failure_rolls_back(self):
        # Inject a setter failure after one real setting has changed.
        # Rollback must restore that first setting and retain the original error.
        properties = bpy.context.scene.mimi_global_properties
        original = properties.open_mod_folder_after_generate_mod
        def setter(owner, name, value):
            if name == "apply_all_modifiers" and value is True:
                raise ValueError("injected setter failure")
            builtins.setattr(owner, name, value)
        with patch("MIMIBlender.automation.properties.setattr", side_effect=setter, create=True):
            error = self.call("settings.update", {"owner": "mimi_global_properties", "values": {
                "open_mod_folder_after_generate_mod": not original, "apply_all_modifiers": True}}, False)
        self.assertEqual(error["code"], "ASSIGNMENT_FAILED")
        self.assertEqual(properties.open_mod_folder_after_generate_mod, original)


# This suite is independent of private game fixtures and generates no files.
# Existing regression suites still own exporter and texture-format acceptance.
# The visible MCP runner reports failures without terminating Blender.
if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
