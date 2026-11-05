"""Independent scene-data fingerprints for native export preservation checks.

The native exporters operate on temporary copies. These signatures verify that
preexisting scene objects, geometry, weights, UV/raw attributes and shape keys
are unchanged after generation, rather than trusting exporter return status.
"""
# Preservation scope:
# - Snapshot preexisting datablock identities before creating export temporaries.
# - Mesh coordinates and topology use the actual stored native arrays.
# - Vertex-group names, locks and sparse weights are object-owned state.
# - Shape-key coordinates and values are independent of Basis coordinates.
# - Material slot identities are retained without claiming shader equivalence.
# - Raw POINT/CORNER attributes are hashed when their native type is supported.
# - Object transforms/parents/modifier identities are checked separately.
# - Armature rest bone matrices and hierarchy are included for existing rigs.
# - A mismatch is a preservation error, not an accepted generated artifact.
# - Fingerprinting never applies modifiers or evaluates a replacement scene.
# - No new object, key or file is created by this query helper.
# - Data hashes are local comparison evidence, not source authenticity proofs.
from array import array
import hashlib
import json
import struct

import bpy

from .contract import AutomationError


def foreach_hash(digest, collection, property_name, components=1, kind="f"):
    """Hash a native numeric collection without per-element Python coordinate lists."""
    values = array(kind, [0]) * (len(collection) * components)
    if values:
        collection.foreach_get(property_name, values)
    digest.update(values.tobytes())


def object_signature(obj):
    """Fingerprint one existing mesh/rig object's data and editable identity."""
    digest = hashlib.sha256()  # Compare actual bytes/state, never native success reports.
    state = {"name": obj.name, "type": obj.type, "matrix": [list(row) for row in obj.matrix_world],
             "parent": obj.parent.name if obj.parent else None,
             "modifiers": [(item.name, item.type, item.show_viewport, item.show_render) for item in obj.modifiers],
             "materials": [slot.material.name if slot.material else None for slot in obj.material_slots]}
    if obj.material_slots:
        # Material shader edits are user changes even when slot names are unchanged.
        # Inspect native graphs without evaluating them or editing shared data.
        # The material adapter never calls object_signature from its graph fingerprint.
        from .materials import fingerprint
        state["material_revisions"] = [fingerprint(slot.material) if slot.material else None for slot in obj.material_slots]
    if obj.type == "MESH":
        mesh = obj.data
        state["mesh"] = mesh.name
        state["groups"] = [(group.name, group.lock_weight) for group in obj.vertex_groups]
        foreach_hash(digest, mesh.vertices, "co", 3)  # Stored geometry coordinates remain original.
        foreach_hash(digest, mesh.loops, "vertex_index", kind="i")  # Exact face corner ownership is topology state.
        foreach_hash(digest, mesh.polygons, "loop_start", kind="i")  # Polygon boundaries distinguish equal flat index sequences.
        foreach_hash(digest, mesh.polygons, "loop_total", kind="i")  # Preserve arbitrary user polygon sizes before export triangulates copies.
        for vertex in mesh.vertices:
            digest.update(struct.pack("<I", len(vertex.groups)))
            for group in vertex.groups:
                digest.update(struct.pack("<If", group.group, group.weight))
        for layer in mesh.uv_layers:
            digest.update(layer.name.encode("utf-8"))
            foreach_hash(digest, layer.data, "uv", 2)
        # Raw-byte preservation channels are native INT attributes; color/vector
        # channels cover ordinary custom attributes without changing color space.
        attribute_layouts = {"FLOAT": ("value", 1, "f"), "INT": ("value", 1, "i"),
                             "BOOLEAN": ("value", 1, "i"), "INT8": ("value", 1, "i"),
                             "FLOAT_VECTOR": ("vector", 3, "f"), "FLOAT2": ("vector", 2, "f"),
                             "FLOAT_COLOR": ("color", 4, "f"), "BYTE_COLOR": ("color", 4, "f")}
        for attribute in sorted(mesh.attributes, key=lambda item: item.name):
            digest.update((attribute.name + "|" + attribute.domain + "|" + attribute.data_type).encode("utf-8"))
            if attribute.data_type in attribute_layouts:
                name, count, kind = attribute_layouts[attribute.data_type]
                foreach_hash(digest, attribute.data, name, count, kind)
        if mesh.shape_keys:
            state["keys"] = [(key.name, key.value, key.mute, key.slider_min, key.slider_max) for key in mesh.shape_keys.key_blocks]
            for key in mesh.shape_keys.key_blocks:
                foreach_hash(digest, key.data, "co", 3)
    elif obj.type == "ARMATURE":
        state["bones"] = [(bone.name, bone.parent.name if bone.parent else None,
                           [list(row) for row in bone.matrix_local]) for bone in obj.data.bones]
    digest.update(json.dumps(state, sort_keys=True, allow_nan=False).encode("utf-8"))
    return digest.hexdigest()


def scene_snapshot():
    """Capture every existing scene object, not only the export's selected sources."""
    return {obj: object_signature(obj) for obj in bpy.data.objects}


def verify_scene_snapshot(snapshot):
    """Require unchanged preexisting objects and report exact offending identities."""
    current = set(bpy.data.objects)
    changed = []
    for obj, expected in snapshot.items():
        if obj not in current:
            changed.append("removed-existing-object")
        elif object_signature(obj) != expected:
            changed.append(obj.name)
    if changed:
        raise AutomationError("SOURCE_SCENE_CHANGED", "Native workflow changed preexisting scene data", {"objects": changed})
