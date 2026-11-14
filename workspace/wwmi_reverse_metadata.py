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
import re
import numpy


PROPERTY_NAME = "mimi_wwmi_reverse_shape_metadata"

# Fields that describe the game's original dispatch, not the compact Mod buffer.
RUNTIME_FIELDS = ("vertex_offset", "dispatch_y", "checksum")
RUNTIME_LIMITS = {
    "vertex_offset": (0, 0xFFFFFFFF),
    "dispatch_y": (1, 0xFFFFFFFF),
    "checksum": (0, 0xFFFFFFFF),
}


def required_shape_key_count(objects, ignore_muted=False):
    """Find the highest changed native slot without inspecting source provenance.

    Shape-less components are valid input. Muted keys omitted by the exporter
    must not make historical reverse metadata a prerequisite for generation.
    Inspect the disposable export mesh, never edit source coordinates/properties.
    """
    highest = -1
    for obj in objects:
        shapes = getattr(getattr(obj, "data", None), "shape_keys", None)
        keys = getattr(shapes, "key_blocks", [])
        basis = getattr(shapes, "reference_key", None) or (keys[0] if keys else None)
        candidates = []
        for key in keys:
            if key == basis:
                continue
            if ignore_muted and getattr(key, "mute", False):
                continue
            match = re.search(r'.*(?:deform|custom)[_ -]*(\d+).*', key.name.lower())
            if match:
                candidates.append((int(match.group(1)), key))
        # Only inspect successively higher candidates. A high, untouched key
        # or a changed loose vertex absent from the IB creates no sparse data.
        # This matches get_shapekey_cache's threshold and avoids false capacity
        # requirements from names alone. Small schema fixtures may omit geometry.
        base = None
        used = None
        for key_id, key in sorted(candidates, key=lambda item: item[0], reverse=True):
            if key_id < highest:
                break
            if hasattr(key, "data") and hasattr(basis, "data"):
                if base is None:
                    base = numpy.empty((len(basis.data), 3), dtype=numpy.float32)
                    basis.data.foreach_get('co', base.ravel())
                    used = sorted({loop.vertex_index for loop in obj.data.loops})
                coords = numpy.empty_like(base)
                key.data.foreach_get('co', coords.ravel())
                if not numpy.any(numpy.linalg.norm(coords[used] - base[used], axis=1) >= 1e-9):
                    continue
            highest = max(highest, key_id)
            break
    return highest + 1


def _native_capacity(batches):
    # Earlier batches preserve imported ID boundaries. The last dispatch still
    # has 127 addressable slots even when the capture populated fewer of them.
    if not batches:
        return 0
    return sum(127 if batch.get("shapekey_count") is None else int(batch["shapekey_count"])
               for batch in batches[:-1]) + 127


def _required_native_batches(batches, key_count):
    # An unused trailing dispatch is not a dependency of an earlier shape key.
    # Keep zero-length prefixes so stored runtime batch numbers never shift.
    end = 0
    for index, batch in enumerate(batches):
        if not isinstance(batch, dict):
            raise ValueError("WWMI malformed required shape batch " + str(index))
        count = batch.get("shapekey_count")
        count = 127 if count is None else _integer(count, _fail_runtime)
        if not 0 <= count <= 127:
            _fail_runtime("invalid required shape batch size")
        end += count
        if key_count <= end:
            return batches[:index + 1]
    return batches


def _fail_runtime(reason):
    raise ValueError("WWMI original shape runtime metadata: " + reason)


def validate_runtime_batch(batch):
    """Validate a consumed runtime identity even if a caller bypassed resolution.

    Legacy single-batch defaults are normalized by their schema adapter before
    this boundary. Explicit batches must contain all three runtime fields.
    Integer conversion must never round a checksum or wrap an unsigned base.
    """
    row = _read_batch(deepcopy(batch), _fail_runtime)
    if any(row.get(field) is None for field in RUNTIME_FIELDS):
        _fail_runtime("incomplete required batch")
    return row


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


def _read_batch(batch, fail):
    """Copy one recorded batch and classify how much of it is evidence.

    A batch is trusted only while its writer did not invalidate it: an
    explicit ``runtime_metadata_complete: false`` means the values were
    defaulted instead of recovered, so they are cleared rather than compared.
    Legacy records without the marker keep whatever fields they actually hold.
    Present values are always type-checked and range-checked, even when the
    record later turns out to be incomplete; only absent fields are ignored.
    """
    # Older writers could omit the marker entirely; only an explicit false
    # disqualifies a record. A missing marker must stay backward compatible.
    if batch.get("runtime_metadata_complete") is False:
        batch = {key: value for key, value in batch.items() if key not in RUNTIME_FIELDS}
        batch.update({field: None for field in RUNTIME_FIELDS})
    for field in RUNTIME_FIELDS:
        value = batch.get(field)
        if value is None:
            continue
        number = _integer(value, fail)
        LOWER, UPPER = RUNTIME_LIMITS[field]
        if not LOWER <= number <= UPPER:
            fail("invalid original runtime batch metadata")
        batch[field] = number
    count = batch.get("shapekey_count", 127)
    if count is not None:
        number = _integer(count, fail)
        # 127 populated slots per batch is the runtime's hard limit.
        if not 0 <= number <= 127:
            fail("invalid original runtime batch metadata")
        batch["shapekey_count"] = number
    offset = batch.get("shapekey_offset")
    if offset is not None:
        batch["shapekey_offset"] = _integer(offset, fail)
    return batch


def _merge_source(selected, incoming, fail):
    """Merge one source's recorded batches into the current sequence.

    Overlapping batches may fill fields the extraction never recorded, but
    every field both sides record must agree. A batch only the source records
    extends the extraction only when all of it is original runtime data;
    otherwise the export would need a fabricated checksum or dispatch size.
    Compact buffer addresses and counts never enter the runtime identity.
    """
    merged = [deepcopy(row) for row in selected]
    rows = [_read_batch(raw, fail) for raw in incoming]
    # Verify the source's own sequence before it can touch any target batch.
    # Compact offsets restart at zero for every source, like the extraction.
    source_offset = 0
    for row in rows:
        recorded = row.get("shapekey_offset")
        if recorded is not None and recorded != source_offset:
            fail("nonconsecutive original shape key ID boundaries")
        source_offset += 127 if row.get("shapekey_count") is None else row["shapekey_count"]
    for index, row in enumerate(rows):
        if index < len(merged):
            target = merged[index]
            for field in RUNTIME_FIELDS:
                value = row.get(field)
                if value is None:
                    continue
                current = target.get(field)
                if current is None:
                    target[field] = deepcopy(value)
                elif _integer(current, fail) != value:
                    fail("conflicts with an existing original runtime batch")
            for field in ("shapekey_count", "shapekey_offset"):
                value = row.get(field)
                if value is None:
                    continue
                if target.get(field) is None:
                    target[field] = deepcopy(value)
                elif _integer(target[field], fail) != value:
                    fail("conflicts with an existing original runtime batch")
            continue
        missing = [field for field in RUNTIME_FIELDS if row.get(field) is None]
        if missing:
            fail("batch " + str(index) + " is missing original runtime batch metadata ("
                 + ", ".join(missing) + ")")
        # A compact address or Mod vertex count is not a runtime identity.
        merged.append({key: value for key, value in row.items()
                       if key not in ("buffer_vertex_offset", "vertex_count")})
    return merged


def _finalize_batches(batches, fail):
    """Validate the batch sequence and recompute its recorded completeness.

    Shape key IDs are consecutive across the per-batch key counts, so a
    recorded boundary that disagrees with the accumulated total is corrupt.
    Completeness is derived from the stored values, not from a copied flag.
    """
    result = []
    key_offset = 0
    for batch in batches:
        if not isinstance(batch, dict):
            fail("contains a malformed runtime batch record")
        count = batch.get("shapekey_count", 127)
        count = 127 if count is None else _integer(count, fail)
        recorded = batch.get("shapekey_offset")
        if recorded is not None and _integer(recorded, fail) != key_offset:
            fail("nonconsecutive original shape key ID boundaries")
        row = deepcopy(batch)
        row["shapekey_count"] = count
        row["shapekey_offset"] = key_offset
        row["runtime_metadata_complete"] = all(
            row.get(field) is not None for field in RUNTIME_FIELDS)
        result.append(row)
        key_offset += count
    return result


def resolve_reverse_shape_metadata(info, objects, draw_ib, required_key_count=None):
    """Extend batches from explicitly attached, matching reverse sources.

    Native component palettes and vertex counts remain authoritative.
    All overlapping runtime dispatches must agree, including shape boundaries.
    Multiple source objects may repeat or extend the same batch sequence.
    Conflicting complete sources fail rather than silently winning by order.
    A source that records less than the target already has cannot block the
    export: it contributes no batch, so its missing fields are simply unused.
    """
    original = info.shapekeys

    # Upstream exports against the selected workspace Metadata.json. Source
    # object provenance is not another required equality check. Only consult
    # our optional reverse sidecar when the requested export needs data that
    # the selected workspace does not already provide.
    if required_key_count == 0:
        original.batches = []
        return

    def fail_workspace(reason):
        raise ValueError("WWMI DrawIB " + draw_ib + ", workspace: shape metadata "
                         + reason + ".")

    # Copy first so a later failure leaves even in-memory metadata unchanged.
    required = (original.batches if required_key_count is None else
                _required_native_batches(original.batches, required_key_count))
    selected = _finalize_batches(
        [_read_batch(deepcopy(batch), fail_workspace) for batch in required], fail_workspace)
    # Ignore historical sidecars, not the consumed native identity validation.
    # Truncate unused metadata before converting/counting or validating it.
    if (required_key_count is not None
            and required_key_count <= _native_capacity(selected)
            and all(row["runtime_metadata_complete"] for row in selected)):
        original.batches = selected
        return
    seen = set()
    for obj in objects:
        if obj is None:
            continue
        # Include the source object so a mismatched blueprint binding is visible.
        # Do not mutate the native info until every participating source passes.
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

            # Known hashes must agree even when the source adds no metadata.
            # Legacy reverse imports may omit hashes and runtime identities.
            # Such records need no association when the target is unchanged.
            offsets = (shapes.get("offsets_hash") or "").lower()
            target_offsets = (original.offsets_hash or "").lower()
            if offsets and target_offsets and offsets != target_offsets:
                fail("does not match the target shape offsets hash")
            scale = (shapes.get("scale_hash") or "").lower()
            if scale and original.scale_hash and scale != original.scale_hash.lower():
                fail("does not match the target shape scale hash")
            merged = _merge_source(selected, shapes.get("batches", []), fail)
            # Filling a field or extending batches still requires the original
            # resource identity. Never infer it from component ranges alone.
            # Merge on copies so rejected sources leave the target untouched.
            if merged != selected and (not target_offsets or offsets != target_offsets):
                fail("does not match the target shape offsets hash")
            selected = merged
        except (KeyError, TypeError, AttributeError, json.JSONDecodeError) as error:
            fail("is malformed (" + str(error) + ")")

    # Preserve the native header and skeleton; only validated batches change.
    # No source object's property or shape data is rewritten during resolution.
    # Compact reverse vertex counts never replace original mesh vertex counts.
    if required_key_count is not None:
        selected = _required_native_batches(selected, required_key_count)
    original.batches = _finalize_batches(selected, fail_workspace)
