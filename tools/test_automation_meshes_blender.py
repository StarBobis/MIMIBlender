"""Verify current-object AI mesh transactions in the real visible MCP desktop.

The user object identity and original shared data remain intact; independent
checkpoint meshes permit manual/AI continuation and recovery without a file swap.
"""
# Transaction acceptance:
# - Tests use the actual structured API and native bpy mesh data.
# - Every case owns a newly created object in the designated visible test scene.
# - Existing user objects are never selected for destructive fixture cleanup.
# - Invalid indices and stale revisions fail before original data changes.
# - Shared source mesh data must stay unchanged when one object is edited.
# - Bone weights, UVs and shape keys stage on private copied data.
# - A visible presentation failure must rollback geometry and group definitions.
# - Restore preserves the current version with a new independent checkpoint.
# - Topology changes require explicit loss acknowledgement for source channels.
# - The same scene object remains referenced by existing blueprints.
# - No headless process or replacement blend is used for validation.
import json
from pathlib import Path
import sys
import unittest
import uuid
from unittest.mock import patch

import bpy

ROOT = Path(__file__).resolve().parents[1]
from MIMIBlender import automation
from MIMIBlender.automation.preservation import object_signature

if bpy.app.background or bpy.data.filepath or bpy.context.mode != "OBJECT" or not bpy.context.scene.name.startswith("MIMIBlender MCP Capability Probe"):
    raise RuntimeError("Use the designated visible unsaved test scene, not user edit/pose work")


class MeshTests(unittest.TestCase):
    """Each test keeps all owned scene data for inspection instead of deleting it."""
    def setUp(self):
        # A primitive fixture is created only after the visible/test-scene guard.
        bpy.ops.mesh.primitive_cube_add()
        self.obj = bpy.context.active_object
        self.obj.name = "mesh-fixture-" + uuid.uuid4().hex[:8]

    def call(self, action, params, success=True):
        # Stable structured failure codes are part of the collaborative contract.
        result = automation.dispatch({"action": action, "params": params})
        self.assertEqual(result["ok"], success, result)
        return result["result"] if success else result["error"]

    def params(self, **values):
        # Read the actual current revision after any manual or prior AI edit.
        state = self.call("mesh.inspect", {"object": self.obj.name})
        return {"object": self.obj.name, "revision": state["revision"], "present": False, **values}

    def test_shared_data_edit_preserves_other_user_and_object_identity(self):
        # A separate object shares the old data as ordinary manual linked duplicates do.
        other = self.obj.copy()  # Reproduce a normal user-linked duplicate.
        bpy.context.scene.collection.objects.link(other)  # Both objects remain in the visible scene.
        old = self.obj.data  # Shared source data must not be mutated by the AI edit.
        identity = self.obj.as_pointer()  # Blueprint and rig references depend on stable object identity.
        before = object_signature(other)  # Independently fingerprint the untargeted linked object.
        result = self.call("mesh.patch", self.params(vertices=[{"index": 0, "value": [-2, -1, -1]}]))  # Use the actual staged API transaction.
        self.assertEqual(self.obj.as_pointer(), identity)  # The user resumes work on the same object.
        self.assertNotEqual(self.obj.data, old)  # A private edited mesh was assigned.
        self.assertEqual(other.data, old)  # Other users keep the original shared mesh.
        self.assertEqual(object_signature(other), before)  # Their geometry/material/group state stays identical.
        self.assertEqual(list(self.obj.data.vertices[0].co), [-2, -1, -1])  # The intended local edit actually committed.
        self.assertEqual(len(result["checkpoint"]), 32)  # Recovery uses a precise independent checkpoint identity.

    def test_restore_retains_current_version_and_recovers_old_geometry(self):
        # Restore works on the same object and leaves both historical versions available.
        before = [list(vertex.co) for vertex in self.obj.data.vertices]  # Capture actual pre-edit local geometry.
        edited = self.call("mesh.patch", self.params(vertices=[{"index": 0, "value": [-3, -1, -1]}]))  # Commit a distinct user-visible version.
        result = self.call("mesh.restore", self.params(checkpoint=edited["checkpoint"]))  # Restore with a fresh current revision.
        self.assertEqual([list(vertex.co) for vertex in self.obj.data.vertices], before)  # Recovery is actual data, not a status message.
        self.assertNotEqual(result["checkpoint"], edited["checkpoint"])  # Restored-away current work gets its own checkpoint.
        self.assertEqual(len(self.call("mesh.inspect", {"object": self.obj.name})["checkpoints"]), 2)  # Both versions remain independently available.

    def test_weights_uvs_and_shape_keys_survive_transaction(self):
        # Coordinates, bone membership and UV loops use independent native channels.
        self.obj.vertex_groups.new(name="0")
        result = self.call("mesh.patch", self.params(
            weights=[{"group": "0", "values": [{"index": 0, "weight": 0.75}]},
                     {"group": "1", "values": [{"index": 1, "weight": 1.0}]}],
            uvs=[{"layer": "AI UV", "create": True, "values": [{"index": 0, "value": [0.2, 0.3]}]}],
            shape_keys=[{"name": "AI Shape", "create": True, "vertices": [{"index": 0, "value": [-2, -1, -1]}], "value": 0.5}]))
        self.assertAlmostEqual(self.obj.vertex_groups["0"].weight(0), 0.75)
        self.assertAlmostEqual(self.obj.vertex_groups["1"].weight(1), 1.0)
        self.assertAlmostEqual(self.obj.data.uv_layers["AI UV"].data[0].uv[0], 0.2)
        self.assertEqual(list(self.obj.data.shape_keys.key_blocks["AI Shape"].data[0].co), [-2, -1, -1])
        self.assertEqual(self.obj.data.shape_keys.key_blocks["AI Shape"].value, 0.5)
        self.call("mesh.restore", self.params(checkpoint=result["checkpoint"]))
        self.assertNotIn("1", self.obj.vertex_groups)
        self.assertIsNone(self.obj.data.shape_keys)

    def test_invalid_indices_and_stale_observations_leave_original_data(self):
        # An invalid staged coordinate must not touch the original shared mesh.
        original = self.obj.data
        revision = object_signature(self.obj)
        error = self.call("mesh.patch", self.params(vertices=[{"index": 99, "value": [0, 0, 0]}]), False)
        self.assertEqual(error["code"], "INVALID_INDEX")  # Bad indices fail staging before touching original data.
        self.assertEqual(self.obj.data, original)
        self.obj.location.x = 2.0
        bpy.context.view_layer.update()
        error = self.call("mesh.patch", {"object": self.obj.name, "revision": revision,
            "vertices": [{"index": 0, "value": [0, 0, 0]}]}, False)
        self.assertEqual(error["code"], "STALE_REVISION")
        self.assertEqual(self.obj.data, original)

    def test_visible_failure_rolls_back_same_object_data(self):
        # The UI layer must not publish failed presentation with committed geometry.
        before = object_signature(self.obj)
        data = self.obj.data
        params = self.params(vertices=[{"index": 0, "value": [-2, -1, -1]}])
        params["present"] = True
        from MIMIBlender.automation.contract import AutomationError
        with patch("MIMIBlender.automation.meshes.present_objects", side_effect=AutomationError("PRESENTATION_FAILED", "fixture")):
            error = self.call("mesh.patch", params, False)
        self.assertEqual(error["code"], "PRESENTATION_FAILED")  # The UI error stays an explicit failed transaction.
        self.assertEqual(self.obj.data, data)  # A failed presentation cannot leave newly edited data assigned.
        self.assertEqual(object_signature(self.obj), before)  # Geometry, groups and transforms really rollback.

    def test_basis_target_required_and_locked_groups_preserved(self):
        # A generic vertex update cannot silently choose between Basis and live keys.
        self.obj.shape_key_add(name="Basis")
        error = self.call("mesh.patch", self.params(vertices=[{"index": 0, "value": [-2, -1, -1]}]), False)
        self.assertEqual(error["code"], "SHAPE_KEY_TARGET_REQUIRED")
        result = self.call("mesh.patch", self.params(shape_keys=[{"name": "Basis", "vertices": [{"index": 0, "value": [-2, -1, -1]}]}]))
        self.assertEqual(list(self.obj.data.shape_keys.key_blocks["Basis"].data[0].co), [-2, -1, -1])
        group = self.obj.vertex_groups.new(name="locked")
        group.lock_weight = True
        error = self.call("mesh.patch", self.params(weights=[{"group": "locked", "values": [{"index": 0, "weight": 1.0}]}]), False)
        self.assertEqual(error["code"], "LOCKED_GROUP")

    def test_explicit_topology_replacement_and_raw_loss_guard(self):
        # Source raw game payloads are not discarded without a caller acknowledgement.
        data_types = [item.identifier for item in bpy.types.Attribute.bl_rna.properties["data_type"].enum_items]
        domains = [item.identifier for item in bpy.types.Attribute.bl_rna.properties["domain"].enum_items]
        self.obj.data.attributes.new("3DMigoto:RawTest", type=next(item for item in data_types if item == "INT"),
                                     domain=next(item for item in domains if item == "POINT"))
        geometry = {"positions": [[0, 0, 0], [1, 0, 0], [0, 1, 0]], "faces": [[0, 1, 2]]}
        error = self.call("mesh.patch", self.params(geometry=geometry), False)
        self.assertEqual(error["code"], "RAW_CHANNELS_REQUIRE_ACK")
        params = self.params(geometry=geometry, drop_raw_attributes=True,
                             uvs=[{"layer": "UVMap", "create": True, "values": [{"index": 0, "value": [0, 0]}]}])
        result = self.call("mesh.patch", params)
        self.assertEqual(len(self.obj.data.vertices), 3)
        self.assertEqual(len(self.obj.data.polygons), 1)
        self.call("mesh.restore", self.params(checkpoint=result["checkpoint"]))
        self.assertEqual(len(self.obj.data.vertices), 8)
        self.assertIn("3DMigoto:RawTest", self.obj.data.attributes)

    def test_edit_mode_is_not_forced_and_real_presentation_is_visible(self):
        # User Edit mode owns the mesh; AI must wait rather than changing modes.
        params = self.params(vertices=[{"index": 0, "value": [-2, -1, -1]}])
        modes = [item.identifier for item in bpy.ops.object.mode_set.get_rna_type().properties["mode"].enum_items]
        try:
            bpy.ops.object.mode_set(mode=next(item for item in modes if item == "EDIT"))
            error = self.call("mesh.patch", params, False)
            self.assertEqual(error["code"], "USER_EDIT_IN_PROGRESS")
            self.assertEqual(bpy.context.mode, "EDIT_MESH")
        finally:
            bpy.ops.object.mode_set(mode=next(item for item in modes if item == "OBJECT"))
        params = self.params(vertices=[{"index": 0, "value": [-2, -1, -1]}])
        params["present"] = True
        result = self.call("mesh.patch", params)
        self.assertTrue(result["presentation"]["visible"])
        self.assertEqual(bpy.context.active_object, self.obj)


# No filesystem or scene-wide fixture deletion occurs after these cases.
if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
