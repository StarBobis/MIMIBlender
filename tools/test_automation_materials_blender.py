"""Accept native material handoff, shared-data preservation and recovery visibly."""
# Acceptance boundaries:
# - Each case creates only fixture-owned objects/materials/images.
# - No scene replacement, game process or headless Blender is used.
# - Existing untargeted native shader graphs are fingerprinted independently.
# - The target object identity and its shared source mesh remain intact.
# - DATA-linked material slots become private OBJECT overrides on commit.
# - Restore never assigns a mutable shared checkpoint as the current material.
# - Invalid sockets, missing images and stale revisions leave original slots.
# - User Edit mode wins over a requested material transaction.
# - A real presentation failure requires exact original binding rollback.
# - Nested shader edits and checkpoint tampering cannot reuse old observations.
# - Successful image binding does not imply pixel or game shader verification.
import unittest
import uuid
from unittest.mock import patch

import bpy

from MIMIBlender import automation
from MIMIBlender.automation import materials
from MIMIBlender.automation.contract import AutomationError

if bpy.app.background or bpy.data.filepath or bpy.context.mode != "OBJECT" or not bpy.context.scene.name.startswith("MIMIBlender MCP Capability Probe"):
    raise RuntimeError("Use the designated unsaved visible fixture scene")


class MaterialTests(unittest.TestCase):
    """Retain fixture shaders and independent checkpoints for manual review."""

    def setUp(self):
        bpy.ops.mesh.primitive_cube_add()  # Only the new fixture becomes selected/active.
        self.obj = bpy.context.active_object  # Existing user objects are never selected as mutation targets.
        self.obj.name = "material-fixture-" + uuid.uuid4().hex[:8]  # New exclusive names keep earlier test work recoverable.
        self.mat = bpy.data.materials.new("material-source-" + uuid.uuid4().hex[:8])  # Each test owns its independent native source graph.
        self.mat.use_nodes = True  # Fixture setup explicitly enables native nodes, not inspection.
        self.obj.data.materials.append(self.mat)  # Begin with a real DATA-linked material slot shared by the duplicate.
        self.node = next(node for node in self.mat.node_tree.nodes if node.type == "BSDF_PRINCIPLED")
        self.socket = next(item for item in self.node.inputs if item.type == "VALUE" and not item.is_linked)
        self.other = self.obj.copy()  # Model the user's ordinary linked duplicate with shared material slots.
        bpy.context.scene.collection.objects.link(self.other)
        self.before = materials.fingerprint(self.mat)  # Independent original shader/slot preservation evidence.

    def call(self, action, params, ok=True):
        result = automation.dispatch({"action": action, "params": params})
        self.assertEqual(result["ok"], ok, result)  # Stable structured outcomes are the actual acceptance layer.
        return result["result"] if ok else result["error"]

    def params(self, **changes):
        observed = self.call("material.inspect", {"object": self.obj.name, "slot": 0})
        return {"object": self.obj.name, "slot": 0, "revision": observed["revision"], "present": False, **changes}

    def edit(self):
        return [{"node": self.node.name, "socket": self.socket.identifier, "value": 0.2}]

    def test_shared_native_graph_and_slot_preserved_with_recovery(self):
        original = self.socket.default_value  # Store actual native pre-edit data before applying any AI request.
        identity = self.obj.as_pointer()
        result = self.call("material.patch", self.params(inputs=self.edit()))
        self.assertEqual(self.obj.as_pointer(), identity)  # Blueprint/rig references retain the same object.
        self.assertEqual(self.obj.data, self.other.data)  # Shared geometry is not copied or modified by shader edits.
        self.assertEqual(self.other.material_slots[0].material, self.mat)
        self.assertEqual(materials.fingerprint(self.mat), self.before)  # Untargeted shared original shader stays exact.
        self.assertEqual(self.obj.material_slots[0].link, "OBJECT")
        native = self.obj.material_slots[0].material.node_tree.nodes[self.node.name]
        self.assertAlmostEqual(native.inputs[self.socket.identifier].default_value, 0.2)
        restored = self.call("material.restore", self.params(checkpoint=result["checkpoint"]))
        native = self.obj.material_slots[0].material.node_tree.nodes[self.node.name]
        self.assertAlmostEqual(native.inputs[self.socket.identifier].default_value, original)
        self.assertNotEqual(restored["checkpoint"], result["checkpoint"])  # Restored-away current work remains recoverable too.
        self.assertEqual(materials.fingerprint(self.mat), self.before)

    def test_existing_image_binding_does_not_modify_source_graph(self):
        texture = self.mat.node_tree.nodes.new(bpy.types.ShaderNodeTexImage.bl_rna.identifier)
        image = bpy.data.images.new("material-image-" + uuid.uuid4().hex[:8], width=4, height=4)
        before = materials.fingerprint(self.mat)  # Texture-node fixture setup is part of the source baseline.
        self.call("material.patch", self.params(images=[{"node": texture.name, "image": image.name}]))
        current = self.obj.material_slots[0].material.node_tree.nodes[texture.name]
        self.assertEqual(current.image, image)
        self.assertIsNone(texture.image)  # Original native texture node is not rebound on other users.
        self.assertEqual(materials.fingerprint(self.mat), before)
        observed = self.call("material.inspect", {"object": self.obj.name, "slot": 0})
        self.assertFalse(observed["pixel_content_verified"])

    def test_bad_socket_image_and_stale_shader_leave_original_binding(self):
        bad = [{"node": self.node.name, "socket": "missing", "value": 0.5}]
        self.assertEqual(self.call("material.patch", self.params(inputs=bad), False)["code"], "INVALID_SOCKET")
        bad_image = [{"node": self.node.name, "image": "missing"}]
        self.assertEqual(self.call("material.patch", self.params(images=bad_image), False)["code"], "INVALID_IMAGE_BINDING")
        stale = self.params(inputs=self.edit())  # Capture a revision before a user changes shader input data.
        self.socket.default_value = 0.3
        self.assertEqual(self.call("material.patch", stale, False)["code"], "STALE_REVISION")
        self.assertEqual(self.obj.material_slots[0].material, self.mat)
        self.assertEqual(self.obj.material_slots[0].link, "DATA")

    def test_present_failure_rolls_back_exact_shared_slot(self):
        params = self.params(inputs=self.edit(), present=True)
        with patch("MIMIBlender.automation.materials.present_objects", side_effect=AutomationError("PRESENTATION_FAILED", "fixture")):
            self.assertEqual(self.call("material.patch", params, False)["code"], "PRESENTATION_FAILED")
        self.assertEqual(self.obj.material_slots[0].material, self.mat)  # Original live material identity must be restored.
        self.assertEqual(self.obj.material_slots[0].link, "DATA")
        self.assertEqual(materials.fingerprint(self.mat), self.before)
        self.assertEqual(self.other.material_slots[0].material, self.mat)

    def test_nested_group_and_checkpoint_changes_reject_stale_work(self):
        group = bpy.data.node_groups.new("material-group-" + uuid.uuid4().hex[:8], bpy.types.ShaderNodeTree.bl_rna.identifier)
        group_node = self.mat.node_tree.nodes.new(bpy.types.ShaderNodeGroup.bl_rna.identifier)
        group_node.node_tree = group
        nested = group.nodes.new(bpy.types.ShaderNodeValue.bl_rna.identifier)
        stale = self.params(inputs=self.edit())  # A nested shader change must invalidate this observation too.
        nested.location.x += 1
        self.assertEqual(self.call("material.patch", stale, False)["code"], "STALE_REVISION")
        result = self.call("material.patch", self.params(inputs=self.edit()))
        checkpoint = next(item for item in materials.history(self.obj) if item["id"] == result["checkpoint"])
        backup = bpy.data.materials[checkpoint["material"]]
        before = materials.fingerprint(backup)  # Retained groups must be independent of resumed manual source shader edits.
        nested.location.x += 1
        self.assertEqual(materials.fingerprint(backup), before)
        self.assertNotEqual(backup.node_tree.nodes[group_node.name].node_tree, group)
        self.assertNotEqual(self.obj.material_slots[0].material.node_tree.nodes[group_node.name].node_tree, group)
        backup.node_tree.nodes[self.node.name].location.x += 1  # Manual checkpoint tampering cannot silently replace current work.
        self.assertEqual(self.call("material.restore", self.params(checkpoint=result["checkpoint"]), False)["code"], "CHECKPOINT_CHANGED")

    def test_user_edit_mode_remains_owned_by_user(self):
        params = self.params(inputs=self.edit())  # Freeze a valid observation before starting this fixture's manual edit.
        modes = [item.identifier for item in bpy.ops.object.mode_set.get_rna_type().properties["mode"].enum_items]
        bpy.ops.object.mode_set(mode=next(item for item in modes if item == "EDIT"))
        try:
            self.assertEqual(self.call("material.patch", params, False)["code"], "USER_EDIT_IN_PROGRESS")
            self.assertEqual(bpy.context.mode, "EDIT_MESH")  # The API must not switch modes for a convenient write.
        finally:
            bpy.ops.object.mode_set(mode=next(item for item in modes if item == "OBJECT"))
        self.assertEqual(materials.fingerprint(self.mat), self.before)


# The live runner retains all fixture data and never exits the visible Blender.
# Separate native export tests cover artifact creation after material handoff.
