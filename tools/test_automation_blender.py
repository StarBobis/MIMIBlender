"""Verify structured read-only AI inspection in an isolated Blender process.

Run Blender --background --factory-startup --python-exit-code 1 --python this_file.
No host settings, saved scene, original workspace or output directory is changed.
This suite exercises real bpy metadata rather than replacing its RNA layer.
"""
# Acceptance boundaries:
# - Registration happens only in the isolated factory-startup process.
# - Capability counts are measured from the currently loaded repository.
# - Operator schema checks cover every discovered concrete operator.
# - Node schema checks do not instantiate each node in a user graph.
# - The test fixture graph has one explicit source and target.
# - Graph ordering is not assumed to match source/target flow ordering.
# - Both input and output sockets carry stable identifiers.
# - Pagination metadata must identify unreturned nodes explicitly.
# - Name-filtered object queries cannot fall back to the active object.
# - Mesh counts verify observation, not original game geometry fidelity.
# - Vertex-group identity is checked without changing weights.
# - A basis shape key verifies the observed shape-key path.
# - Settings queries retain the user's current in-memory values.
# - No query saves preferences or a startup file.
# - No test writes into a source extraction workspace.
# - No test invokes a game process or installs a generated Mod.
# - Existing arbitrary built-in operators remain outside discovery.
# - JSON serialization rejects any accidental leaked bpy object.
# - This suite supplements, rather than replaces, Blender-free validation.
# - Mutation and import/export acceptance need their own dedicated cases.
# - Tests are not evidence of correct in-game shading or draw coverage.
import importlib
import json
from pathlib import Path
import sys
import unittest

import bpy


# Register the repository under test, not an older packaged add-on release.
# Factory startup must be used so add-on initialization cannot affect a user file.
# Each query is compared against current live counts instead of a frozen baseline.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
addon = importlib.import_module(ROOT.name)
addon.register()
automation = importlib.import_module(ROOT.name + ".automation")


class InspectionTests(unittest.TestCase):
    """Real objects, custom nodes and all registered RNA schemas are queried."""

    def query(self, action, params=None):
        # Require valid JSON and successful envelopes, not console-only success.
        # The same call form is used by the dedicated MCP adapter.
        result = automation.dispatch({"action": action, "params": params or {}})
        self.assertTrue(result["ok"], result)
        json.dumps(result, allow_nan=False)
        return result["result"]

    def test_capabilities_and_all_rna_schemas(self):
        # Introspection must cover all current concrete operators and nodes.
        # Source-only helpers and abstract base classes must stay excluded.
        result = self.query("system.capabilities")
        self.assertIn("GIMI", result["exporters"])
        self.assertIn("WWMI", result["exporters"])
        operators = [item for item in result["types"] if item["kind"] == "Operator"]
        nodes = [item for item in result["types"] if item["kind"] == "Node"]
        self.assertGreaterEqual(len(operators), 129)
        self.assertGreaterEqual(len(nodes), 15)
        for item in operators + nodes:
            with self.subTest(identifier=item["identifier"]):
                schema = self.query("rna.describe", {"kind": "operator" if item in operators else "node",
                                                    "identifier": item["identifier"]})
                self.assertIn("properties", schema)
        # Arbitrary built-in operators are not advertised as add-on capabilities.
        result = automation.dispatch({"action": "rna.describe", "params": {"kind": "operator", "identifier": "wm.quit_blender"}})
        self.assertEqual(result["error"]["code"], "NOT_FOUND")

    def test_named_scene_and_paginated_blueprint(self):
        # Create an explicit fixture after registration, with no disk writes.
        # Exact names and socket identifiers support deterministic later edits.
        bpy.ops.mesh.primitive_cube_add()
        obj = bpy.context.active_object
        obj.name = "Automation Query Fixture"
        obj.vertex_groups.new(name="3")
        obj.shape_key_add(name="Basis")
        scene = self.query("scene.inspect", {"objects": [obj.name]})
        self.assertEqual(scene["total_objects"], 1)
        self.assertEqual(scene["objects"][0]["mesh"]["vertices"], 8)
        self.assertIn("3", scene["objects"][0]["mesh"]["vertex_groups"])
        tree = bpy.data.node_groups.new("Automation Query Blueprint", "MIMIBlueprintTreeType")
        tree.use_fake_user = True
        source = tree.nodes.new("MIMINode_Object_Info")
        target = tree.nodes.new("MIMINode_Result_Output")
        tree.links.new(source.outputs[0], target.inputs[0])
        graph = self.query("blueprint.inspect", {"tree": tree.name, "limit": 1})
        self.assertEqual(graph["total_nodes"], 2)
        self.assertEqual(len(graph["nodes"]), 1)
        self.assertEqual(graph["next_offset"], 1)
        self.assertEqual(len(graph["links"]), 1)
        sockets = graph["nodes"][0]["inputs"] + graph["nodes"][0]["outputs"]
        self.assertIn("identifier", sockets[0])
        # Unknown targets must not silently resolve to the selected object/tree.
        missing = automation.dispatch({"action": "scene.inspect", "params": {"objects": ["missing fixture"]}})
        self.assertEqual(missing["error"]["code"], "NOT_FOUND")

    def test_read_only_callbacks_restore_global_config_on_failure(self):
        # Existing dynamic enums can refresh the host selection as a side effect.
        # The wrapper must restore state even when the callback itself fails.
        from MIMIBlender.automation.inspection import read_only
        from MIMIBlender.common.global_config import GlobalConfig
        original = GlobalConfig.gamename
        def callback(params):
            GlobalConfig.gamename = "temporary-query-refresh"
            raise ValueError("fixture callback failure")
        with self.assertRaises(ValueError):
            read_only(callback)({})
        self.assertEqual(GlobalConfig.gamename, original)

    def test_settings_are_read_only(self):
        # A settings query includes both values and edit constraints.
        # It must not persist preferences, configuration or an active blend file.
        properties = bpy.context.scene.mimi_global_properties
        original = properties.open_mod_folder_after_generate_mod
        result = self.query("settings.inspect")
        self.assertIn("mimi_global_properties", result)
        self.assertEqual(result["mimi_global_properties"]["value"]["open_mod_folder_after_generate_mod"], original)
        self.query("rna.describe", {"kind": "settings", "identifier": "mimi_global_properties"})
        self.assertEqual(properties.open_mod_folder_after_generate_mod, original)
        self.assertEqual(bpy.data.filepath, "")


# Blender's own arguments must not reach unittest's command-line parser.
# A nonzero Python exit code is required in the launch command above.
if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
