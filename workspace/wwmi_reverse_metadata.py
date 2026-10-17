"""Preserve reverse-import runtime batches without replacing native skeletons.

A reverse Mod can contain more shape batches than an older game extraction.
Its compact vertex counts are not original dispatch sizes or checksums.
Only recorded runtime identities may extend the native extraction's batches.
No filesystem search, checksum inference, or source mesh edits happen here.
This helper does not decide which component should own a triangle.
Bone palettes remain governed by the selected export architecture.
Persisted records are evidence to validate, not permission to trust a source.
Only the selected draw's connected objects may contribute such records.
"""

from copy import deepcopy
import json


PROPERTY_NAME = "mimi_wwmi_reverse_shape_metadata"


def capture_reverse_shape_metadata(obj, shapekey_buffers):
    """Store portable source metadata on each reverse-imported object.

    Component match ranges refer to the original game, not the edited Mod IB.
    They distinguish a reverse source from a normal per-component extraction.
    JSON avoids Blender ID-property limitations on nested heterogeneous lists.
    An old project needs an explicit metadata attachment; never guess its source.
    """
    ranges = shapekey_buffers.get("source_match_components")
    shapes = shapekey_buffers.get("metadata", {})
    if not ranges or not shapes.get("batches"):
        return
    payload = {"version": 1, "components": ranges, "shapekeys": shapes}
    obj[PROPERTY_NAME] = json.dumps(payload, sort_keys=True)


def _integer(value, fail):
    # Numeric strings are accepted for older JSON writers, but never round data.
    # Rounding a checksum or a vertex base would fabricate a runtime identity.
    # Malformed values must retain the same DrawIB/object context as conflicts.
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        fail("contains a non-integer runtime value")
    if isinstance(value, bool) or (not isinstance(value, str) and value != number):
        fail("contains a non-integer runtime value")
    return number


def _runtime_batches(shapes, fail):
    """Normalize only recorded runtime fields, never compact buffer addresses.

    Every batch must be complete before it can supplement an extraction.
    Shape IDs are consecutive across the recorded per-batch key counts.
    Missing count fields retain the established legacy 127-slot convention.
    The original vertex base is unrelated to the compact buffer's vertex base.
    """
    result = []
    key_offset = 0
    for batch in shapes.get("batches", []):
        if batch.get("runtime_metadata_complete") is False:
            fail("incomplete original runtime batch metadata")
        required = ("vertex_offset", "dispatch_y", "checksum")
        if any(batch.get(field) is None for field in required):
            fail("missing original runtime batch metadata")
        values = {field: _integer(batch[field], fail) for field in required}
        count = _integer(batch.get("shapekey_count", 127), fail)
        if (values["vertex_offset"] < 0 or values["dispatch_y"] <= 0
                or not 0 <= values["checksum"] <= 0xFFFFFFFF
                or not 0 <= count <= 127):
            fail("invalid original runtime batch metadata")
        if _integer(batch.get("shapekey_offset", key_offset), fail) != key_offset:
            fail("nonconsecutive original shape key ID boundaries")
        values["shapekey_count"] = count
        values["shapekey_offset"] = key_offset
        values["runtime_metadata_complete"] = True
        result.append(values)
        key_offset += count
    if not result:
        fail("no original runtime batches were recorded")
    return result


def resolve_reverse_shape_metadata(info, objects, draw_ib):
    """Extend batches from explicitly attached, matching reverse sources.

    Native component palettes and vertex counts remain authoritative.
    All overlapping runtime dispatches must agree, including shape boundaries.
    Multiple source objects may repeat or extend the same batch sequence.
    Conflicting sources fail rather than silently winning by object order.
    """
    original = info.shapekeys
    selected = deepcopy(original.batches)
    seen = set()
    for obj in objects:
        if obj is None:
            continue
        # Include the source object so a mismatched blueprint binding is visible.
        # Do not mutate the native info until every participating source passes.
        # A failure therefore leaves even this in-memory metadata unchanged.
        def fail(reason):
            name = getattr(obj, "name", "unknown")
            raise ValueError("WWMI DrawIB " + draw_ib + ", object '" + name
                             + "': reverse shape metadata " + reason + ".")

        text = obj.get(PROPERTY_NAME)
        if not text:
            continue
        if not isinstance(text, str):
            fail("must be stored as JSON text")
        if text in seen:
            continue
        seen.add(text)
        try:
            payload = json.loads(text)
            if payload.get("version") != 1:
                fail("has an unsupported schema version")
            rows = sorted(payload["components"], key=lambda row: _integer(row["ComponentIndex"], fail))
            actual = [(_integer(row["ComponentIndex"], fail), _integer(row["MatchFirstIndex"], fail),
                       _integer(row["MatchIndexCount"], fail)) for row in rows]
            expected = [(index, component.index_offset, component.index_count)
                        for index, component in enumerate(info.components)]
            if actual != expected:
                fail("does not match the target component draw ranges")
            shapes = payload["shapekeys"]

            # Original resource hashes anchor this metadata to the target model.
            # A scale hash may be absent, but two known scale hashes must agree.
            # An empty offsets hash cannot establish a safe target association.
            if not original.offsets_hash or shapes.get("offsets_hash") != original.offsets_hash:
                fail("does not match the target shape offsets hash")
            scale = shapes.get("scale_hash")
            if scale and original.scale_hash and scale != original.scale_hash:
                fail("does not match the target shape scale hash")
            batches = _runtime_batches(shapes, fail)
            native = _runtime_batches({"batches": selected}, fail) if selected else []
            if batches[:min(len(batches), len(native))] != native[:min(len(batches), len(native))]:
                fail("conflicts with an existing original runtime batch")
            if len(batches) > len(selected):
                selected = batches
        except (KeyError, TypeError, AttributeError, json.JSONDecodeError) as error:
            fail("is malformed (" + str(error) + ")")

    # Preserve the native header and skeleton; only validated batches change.
    # No source object's property or shape data is rewritten during resolution.
    # Compact reverse vertex counts never replace original mesh vertex counts.
    original.batches = selected
