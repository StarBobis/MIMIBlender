"""
Generic N-object merged sculpting.

Merge any number of mesh objects into one temporary sculpt target, sculpt
it, then write the sculpted vertex positions back into each source object.

Generalizations over the original WWMI-Tools workflow:
- Sources are identified by session UID stamps instead of object names, so
  renaming a source object while sculpting is harmless.
- Every source's relative transform is recorded at merge time, so sources
  with arbitrary location/rotation/scale still receive correct positions.
- Multiple merged groups can exist in one scene at once; each merged object
  carries its own session payload and never mixes data with other groups.
- A discard entry point cleans up session stamps without writing anything.

Idea ported from WWMI-Tools (GPL-3.0) create_merged_object /
transfer_position_data, re-implemented with the generalizations above.

Hard rule (shared with the original): sculpting must not change the vertex
count. Dyntopo, remesh and "merge by distance" break the vertex mapping and
are rejected before any data is written back.
"""

import json
import uuid

import numpy
import bpy

from .obj_utils import ObjUtils

# Custom property that stores the JSON session payload on a merged object.
PROP_SOURCES = "MIMI:MergedSculptSources"

# Custom property stamped onto every source object while a session is open.
# The value is "<session>:<uid>" so several sessions can share one scene.
PROP_SOURCE_UID = "MIMI:MergedSculptUID"

# Name prefix of generated merged objects, for example "mscu_9f2c1e7a".
MERGED_NAME_PREFIX = "mscu_"

# Tolerance used when comparing world matrices before/after sculpting.
MATRIX_EPSILON = 1e-4


class MergedSculptUtils:

    # ------------------------------------------------------------------
    # Merge
    # ------------------------------------------------------------------
    @classmethod
    def create_merged_object(cls, context, clear_modifiers=True):
        """Duplicate the selected mesh objects and join the copies into one
        sculpt target. Returns (merged_object, warnings).

        The vertex order of the merged object strictly matches the order of
        the recorded sources because ObjUtils.join_objects joins the copies
        one at a time. That order is the whole mapping mechanism.
        """
        sources = [obj for obj in context.selected_objects if obj.type == 'MESH']
        if len(sources) < 2:
            raise ValueError("Select at least 2 mesh objects to merge.")

        # Reject ambiguous ownership before creating copies or changing any
        # source stamps. Shared meshes would also edit unselected instances.
        for obj in sources:
            if PROP_SOURCE_UID in obj or PROP_SOURCES in obj:
                raise ValueError(
                    "Object '%s' already belongs to a merged sculpt session." % obj.name)
            cls._check_source_data(obj)

        session = uuid.uuid4().hex

        # The join bakes every copy into the local space of copies[0], so
        # the merged space equals sources[0]'s world space at merge time.
        merged_world = sources[0].matrix_world.copy()

        # Record everything needed to slice the merged data and to convert
        # positions back into each source's local space. Matrices must be
        # captured before the join, because the join rewrites the copies.
        records = []
        for obj in sources:
            try:
                inv_rel = obj.matrix_world.inverted() @ merged_world
            except ValueError:
                raise ValueError(
                    "Object '%s' has a non-invertible transform (zero scale)." % obj.name)
            records.append({
                "uid": uuid.uuid4().hex[:8],
                "name": obj.name,
                "vertex_count": len(obj.data.vertices),
                # inv_rel converts merged-space positions back to this
                # source's local space: v_src = inv_rel @ v_merged.
                "inv_rel_matrix": cls._matrix_rows(inv_rel),
                # Kept only to warn when the source moved during sculpting.
                "world_matrix": cls._matrix_rows(obj.matrix_world),
                "shape_keys": cls._shape_key_names(obj),
            })

        # Duplicate first, stamp afterwards: obj.copy() inherits custom
        # properties, and the copies must never carry source stamps.
        if sources[0].users_collection:
            target_collection = sources[0].users_collection[0]
        else:
            target_collection = context.scene.collection
        copies = []
        for obj in sources:
            copy_obj = ObjUtils.copy_object(
                context, obj, name="temp_mscu_" + obj.name,
                collection=target_collection)
            if clear_modifiers:
                # Sculpting reads undeformed data; leftover modifiers would
                # only confuse the viewport and the write-back math.
                for modifier in list(copy_obj.modifiers):
                    copy_obj.modifiers.remove(modifier)
            copies.append(copy_obj)

        # Stamp each source with "<session>:<uid>" so renames during
        # sculpting cannot break the mapping.
        for obj, record in zip(sources, records):
            ObjUtils.set_custom_property(
                obj, PROP_SOURCE_UID, session + ":" + record["uid"])

        ObjUtils.join_objects(context, copies)

        merged_obj = copies[0]
        # Belt and braces: the merged object is a sculpt target, not a source.
        if PROP_SOURCE_UID in merged_obj:
            del merged_obj[PROP_SOURCE_UID]
        merged_obj.name = MERGED_NAME_PREFIX + session[:8]
        ObjUtils.set_custom_property(merged_obj, PROP_SOURCES, json.dumps({
            "version": 2,
            "session": session,
            "sources": records,
        }))

        # Shape keys: reset all values and activate Basis so sculpt strokes
        # land in Basis instead of silently deforming mesh.vertices.
        warnings = cls._prepare_shape_keys(merged_obj, records)

        ObjUtils.select_obj(merged_obj)
        return merged_obj, warnings

    # ------------------------------------------------------------------
    # Apply
    # ------------------------------------------------------------------
    @classmethod
    def apply_merged_sculpt(cls, context, apply_deltas_to_shapekeys=False):
        """Write the sculpted positions back into every source object,
        clean the session stamps and delete the merged object.
        Returns the number of source objects that received data.

        All validation happens before the first write, so a failure leaves
        every source object untouched.
        """
        merged_obj = cls._find_merged_object(context)
        payload = json.loads(merged_obj[PROP_SOURCES])
        records = payload["sources"]

        # Pre-flight checks: resolve sources and verify every vertex count
        # before touching any data (atomic from the user's point of view).
        resolved, missing, conflicts = cls._resolve_sources(payload)
        if missing:
            raise ValueError("Missing source objects: " + ", ".join(missing))
        if conflicts:
            raise ValueError(
                "Duplicated source objects (same session UID): "
                + ", ".join(conflicts))
        for obj, record in resolved:
            cls._check_source_data(obj)
            if len(obj.data.vertices) != record["vertex_count"]:
                raise ValueError(
                    "Vertex count of '%s' changed (%d -> %d)."
                    % (record["name"], record["vertex_count"],
                       len(obj.data.vertices)))
        expected_total = sum(record["vertex_count"] for record in records)
        actual_total = len(merged_obj.data.vertices)
        if actual_total != expected_total:
            raise ValueError(
                "Merged vertex count changed (%d -> %d). "
                "Dyntopo/remesh is not supported."
                % (expected_total, actual_total))

        # Read the sculpted positions once: Basis key when shape keys exist,
        # otherwise the undeformed mesh coordinates (modifier-immune).
        merged_positions = cls._read_merged_positions(merged_obj)

        # Prepare every write and backup before touching any source. A
        # malformed matrix or incompatible target must not cause half-apply.
        writes = []
        offset = 0
        for obj, record in resolved:
            count = record["vertex_count"]
            chunk = merged_positions[offset:offset + count]
            local_positions = cls._transform_positions(chunk, record["inv_rel_matrix"])
            if not numpy.isfinite(local_positions).all():
                raise ValueError("Sculpt positions contain non-finite values.")
            keys = obj.data.shape_keys
            if keys is None:
                targets = [obj.data.vertices]
                delta = None
            else:
                basis = keys.reference_key
                delta = local_positions - cls._read_flat_positions(basis.data, count)
                targets = ([key.data for key in keys.key_blocks]
                           if apply_deltas_to_shapekeys else [basis.data])
            for target in targets:
                before = cls._read_flat_positions(target, count)
                after = before + delta if keys is not None and apply_deltas_to_shapekeys else local_positions
                writes.append((obj.data, target, before, after))
            offset += count

        # Keep the session intact if an unexpected Blender write fails.
        # Include the current target in rollback in case it was partly written.
        attempted = []
        try:
            for mesh, target, before, after in writes:
                attempted.append((mesh, target, before))
                cls._write_flat_positions(target, after)
                mesh.update()
        except Exception:
            for mesh, target, before in reversed(attempted):
                cls._write_flat_positions(target, before)
                mesh.update()
            raise

        cls._cleanup_stamps(resolved, payload["session"])
        cls._remove_merged_object(merged_obj)
        return len(resolved)

    # ------------------------------------------------------------------
    # Discard / validate
    # ------------------------------------------------------------------
    @classmethod
    def discard_merged_sculpt(cls, context):
        """Delete the merged object without writing anything back and remove
        the session stamps from its source objects."""
        merged_obj = cls._find_merged_object(context)
        payload = json.loads(merged_obj[PROP_SOURCES])
        # Clear all exact stamps, including duplicated sources which cannot
        # be resolved for apply. Never remove another session's stamp.
        expected = {payload["session"] + ":" + r["uid"] for r in payload["sources"]}
        for obj in bpy.data.objects:
            if obj.get(PROP_SOURCE_UID) in expected:
                del obj[PROP_SOURCE_UID]
        cls._remove_merged_object(merged_obj)

    @classmethod
    def validate_merged_sculpt(cls, context):
        """Read-only health check. Returns a list of human-readable issues;
        an empty list means the session can be applied safely."""
        issues = []
        merged_obj = cls._find_merged_object(context)
        payload = json.loads(merged_obj[PROP_SOURCES])

        resolved, missing, conflicts = cls._resolve_sources(payload)
        for name in missing:
            issues.append("missing source object: " + name)
        for name in conflicts:
            issues.append("duplicated source object: " + name)

        for obj, record in resolved:
            try:
                cls._check_source_data(obj)
            except ValueError as error:
                issues.append(str(error))
                continue
            if len(obj.data.vertices) != record["vertex_count"]:
                issues.append(
                    "vertex count changed: %s (%d -> %d)"
                    % (record["name"], record["vertex_count"],
                       len(obj.data.vertices)))
            if not cls._matrix_close(
                    cls._matrix_rows(obj.matrix_world), record["world_matrix"]):
                issues.append("moved during sculpting: " + record["name"])

        expected_total = sum(r["vertex_count"] for r in payload["sources"])
        actual_total = len(merged_obj.data.vertices)
        if actual_total != expected_total:
            issues.append(
                "merged object was remeshed (%d -> %d vertices)"
                % (expected_total, actual_total))
        return issues

    # ------------------------------------------------------------------
    # Lookup helpers
    # ------------------------------------------------------------------
    @classmethod
    def _find_merged_object(cls, context):
        """Locate the merged sculpt object to operate on: the active object,
        then the selection, then the scene (which must hold exactly one)."""
        active = context.view_layer.objects.active
        if active is not None and active.name in context.scene.objects and PROP_SOURCES in active:
            return active
        for obj in context.selected_objects:
            if obj.name in context.scene.objects and PROP_SOURCES in obj:
                return obj
        candidates = [obj for obj in context.scene.objects if PROP_SOURCES in obj]
        if len(candidates) == 1:
            return candidates[0]
        if not candidates:
            raise ValueError("No merged sculpt object found in the scene.")
        raise ValueError(
            "Several merged sculpt objects exist; select the one to use.")

    @classmethod
    def _resolve_sources(cls, payload):
        """Resolve sources only by exact session UID, never by object name.
        Names are diagnostic labels; renames do not affect identity.
        Returns (resolved_pairs, missing_names, conflict_names)."""
        session = payload["session"]

        # Index all stamped objects once: stamp value -> list of objects.
        stamped = {}
        for obj in bpy.data.objects:
            value = obj.get(PROP_SOURCE_UID)
            if isinstance(value, str):
                stamped.setdefault(value, []).append(obj)

        resolved = []
        missing = []
        conflicts = []
        for record in payload["sources"]:
            matches = stamped.get(session + ":" + record["uid"], [])
            if len(matches) > 1:
                # The user duplicated a source object; refuse to guess.
                conflicts.append(record["name"])
                continue
            obj = matches[0] if matches else None
            # A reused name is not proof of identity. Missing stamps require
            # explicit recovery, never an automatic write into another object.
            if obj is None:
                missing.append(record["name"])
                continue
            resolved.append((obj, record))
        return resolved, missing, conflicts

    @classmethod
    def _cleanup_stamps(cls, resolved, session):
        """Remove only stamps owned by the session being completed."""
        for obj, record in resolved:
            if obj.get(PROP_SOURCE_UID) == session + ":" + record["uid"]:
                del obj[PROP_SOURCE_UID]

    @classmethod
    def _remove_merged_object(cls, merged_obj):
        """Delete the merged object and its now-orphaned mesh data."""
        mesh = merged_obj.data
        bpy.data.objects.remove(merged_obj, do_unlink=True)
        if mesh is not None and mesh.users == 0:
            bpy.data.meshes.remove(mesh)

    # ------------------------------------------------------------------
    # Position I/O
    # ------------------------------------------------------------------
    @classmethod
    def _read_merged_positions(cls, merged_obj):
        """Read the sculpted positions of the merged object as an (N, 3)
        float64 array. Shape keys take priority because sculpt strokes land
        in the active key (Basis) when keys exist."""
        vertex_count = len(merged_obj.data.vertices)
        flat = numpy.empty(vertex_count * 3, dtype=numpy.float32)
        shape_keys = merged_obj.data.shape_keys
        if shape_keys is not None:
            shape_keys.reference_key.data.foreach_get('co', flat)
        else:
            merged_obj.data.vertices.foreach_get('undeformed_co', flat)
        return flat.reshape(vertex_count, 3).astype(numpy.float64)

    @classmethod
    def _read_flat_positions(cls, point_data, vertex_count):
        """foreach_get 'co' of a vertex/key-point collection into (N, 3)."""
        flat = numpy.empty(vertex_count * 3, dtype=numpy.float32)
        point_data.foreach_get('co', flat)
        return flat.reshape(vertex_count, 3).astype(numpy.float64)

    @classmethod
    def _write_flat_positions(cls, point_data, positions):
        """foreach_set 'co' of a vertex/key-point collection from (N, 3)."""
        flat = numpy.ascontiguousarray(
            positions.reshape(-1), dtype=numpy.float32)
        point_data.foreach_set('co', flat)

    @classmethod
    def _transform_positions(cls, positions, matrix_rows):
        """Apply a 4x4 row-major matrix to an (N, 3) position array."""
        matrix = numpy.asarray(matrix_rows, dtype=numpy.float64).reshape(4, 4)
        ones = numpy.ones((positions.shape[0], 1), dtype=numpy.float64)
        homogeneous = numpy.hstack([positions, ones])
        transformed = homogeneous @ matrix.T
        return transformed[:, :3]

    # ------------------------------------------------------------------
    # Small data helpers
    # ------------------------------------------------------------------
    @classmethod
    def _prepare_shape_keys(cls, merged_obj, records):
        """Reset key values, activate Basis, and warn about mismatched key
        sets (Blender's join drops keys missing on the active object)."""
        key_sets = {frozenset(record["shape_keys"]) for record in records}
        warnings = []
        if len(key_sets) > 1:
            warnings.append(
                "Source objects have different shape keys; keys missing on "
                "the first object were dropped by the join.")

        shape_keys = merged_obj.data.shape_keys
        if shape_keys is None:
            return warnings
        for key_block in shape_keys.key_blocks:
            key_block.value = 0.0
        # Sculpt strokes write into the active key; make sure it is Basis.
        for index, key_block in enumerate(shape_keys.key_blocks):
            if key_block == shape_keys.reference_key:
                merged_obj.active_shape_key_index = index
                break
        return warnings

    @classmethod
    def _check_source_data(cls, obj):
        """Reject data that cannot be written independently and safely.

        Linked duplicates may include unselected objects. Reject instead of
        silently making meshes single-user and changing the user's setup.
        Edit mode owns a separate mesh buffer, so it is also not writable.
        """
        if obj.type != 'MESH':
            raise ValueError("Source '%s' is no longer a mesh object." % obj.name)
        mesh = obj.data
        if mesh.users > 1:
            raise ValueError("Object '%s' uses a shared mesh; make it single-user first." % obj.name)
        if not obj.is_editable or not mesh.is_editable or mesh.is_editmode:
            raise ValueError("Object '%s' must have editable mesh data in Object mode." % obj.name)
        if mesh.shape_keys is not None and not mesh.shape_keys.is_editable:
            raise ValueError("Shape keys of '%s' are not editable." % obj.name)

    @classmethod
    def _shape_key_names(cls, obj):
        """List of shape key names of an object (empty list when none)."""
        if obj.data.shape_keys is None:
            return []
        return [key_block.name for key_block in obj.data.shape_keys.key_blocks]

    @classmethod
    def _matrix_rows(cls, matrix):
        """Convert a mathutils.Matrix into a JSON-friendly list of rows."""
        return [list(row) for row in matrix]

    @classmethod
    def _matrix_close(cls, rows_a, rows_b):
        """Epsilon comparison of two 4x4 row-major matrices."""
        for row_a, row_b in zip(rows_a, rows_b):
            for value_a, value_b in zip(row_a, row_b):
                if abs(value_a - value_b) > MATRIX_EPSILON:
                    return False
        return True
