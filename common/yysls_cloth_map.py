"""Source identity for draw-local native cloth consumption.

An edited vertex number cannot address the game's simulation texture. Keep the
imported ID and reference position through copies and UV splits, then serialize
them in the final exported VB order. Replacement draws use ordinary skinning.
"""

import json
import numpy as np

ID = "mimi_yysls_source_id"
REST = "mimi_yysls_source_position"
TABLE = "mimi_yysls_source_table"
NO_CLOTH = 0xffffffff


def store_source(obj, positions, offset=0, source_ids=None):
    """Capture the decoded game-space reference before editing begins."""
    mesh = obj.data
    points = np.asarray(positions, dtype=np.float32)
    ids = (np.arange(len(points), dtype=np.int32) + int(offset)
           if source_ids is None else np.asarray(source_ids, dtype=np.int32))
    if len(ids) != len(points):
        raise ValueError("YYSLS cloth: source ID count differs from mesh")
    # Object properties keep an independent reference for modifier validation.
    # POINT attributes travel with duplicated vertices and evaluated meshes.
    # Unreferenced legacy points may remain deliberately unmapped (-1).
    # Referencing one later fails export until its source is transferred.
    obj[TABLE] = json.dumps({str(int(i)): p.tolist() for i, p in zip(ids, points) if i >= 0})
    attr = mesh.attributes.new(name=ID, type='INT', domain='POINT')
    attr.data.foreach_set('value', ids)
    attr = mesh.attributes.new(name=REST, type='FLOAT_VECTOR', domain='POINT')
    attr.data.foreach_set('vector', points.ravel())


def merge_sources(objects):
    """Reject old imports and conflicting source spaces before joining."""
    result = {}
    for obj in objects:
        if TABLE not in obj:
            raise ValueError("YYSLS cloth: reimport the original dump to retain source IDs: " + obj.name)
        for key, value in json.loads(obj[TABLE]).items():
            # Different reference meshes must never silently share an ID.
            if key in result and result[key] != value:
                raise ValueError("YYSLS cloth: conflicting source reference at ID " + key)
            result[key] = value
    return result


def pack_map(ids, reference, table, point_indices):
    """Validate evaluated provenance and pack little-endian XYZ/uint ID."""
    ids = np.asarray(ids, dtype=np.int64)
    reference = np.asarray(reference, dtype=np.float32)
    selected = np.asarray(point_indices, dtype=np.int64)
    if reference.shape != (len(ids), 3):
        raise ValueError("YYSLS cloth: invalid source positions")
    if len(selected) and (selected.min() < 0 or selected.max() >= len(ids)):
        raise ValueError("YYSLS cloth: invalid exported point index")
    if not np.isfinite(reference[selected]).all():
        raise ValueError("YYSLS cloth: invalid source positions")
    # Check only exported points. Removed/unreferenced vertices need no map.
    # Interpolated references from subdivision do not identify an original point.
    for point in np.unique(selected):
        source_id = int(ids[point])
        expected = table.get(str(source_id))
        if source_id < 0 or source_id >= NO_CLOTH or expected is None:
            raise ValueError("YYSLS cloth: missing original vertex ID")
        if not np.array_equal(reference[point], np.asarray(expected, dtype=np.float32)):
            raise ValueError("YYSLS cloth: topology generated an unmapped point; transfer source mapping before export")
    payload = np.empty((len(selected), 4), dtype='<u4')
    payload[:, :3] = reference[selected].astype('<f4').view('<u4')
    payload[:, 3] = ids[selected].astype('<u4')
    return payload.view(np.uint8).ravel()


def export_map(obj, mesh, index_loop_map):
    """Use the evaluated mesh and the actual VB deduplication map."""
    source = mesh.attributes.get(ID)
    rest = mesh.attributes.get(REST)
    if source is None or rest is None or not index_loop_map or TABLE not in obj:
        raise ValueError("YYSLS cloth: original source mapping is missing; reimport the dump")
    # The CPU-preskinning path does not expose unique loops and is rejected.
    # Guessing an order here would reproduce the original corruption.
    ids = np.empty(len(mesh.vertices), dtype=np.int32)
    reference = np.empty((len(mesh.vertices), 3), dtype=np.float32)
    source.data.foreach_get('value', ids)
    rest.data.foreach_get('vector', reference.ravel())
    points = [mesh.loops[index_loop_map[i]].vertex_index for i in range(len(index_loop_map))]
    return pack_map(ids, reference, json.loads(obj[TABLE]), points)


def read_draw_source_table(obj, draw):
    """Read provenance before joining the disposable draw meshes."""
    # A recognized original draw name must agree with the blueprint target.
    # Compare ranges only when both names use the same addressing convention.
    source = draw._try_parse_name(draw.obj_name)
    if source is not None:
        source_ib, source_count, source_first, _, _ = source
        named_ib = len(source_ib) == 8 and all(c in "0123456789abcdefABCDEF" for c in source_ib)
        if named_ib and (source_ib.lower() != draw.match_draw_ib.lower()
                         or (bool(source_count) == bool(draw.match_index_count)
                             and (source_count, source_first) != (draw.match_index_count, draw.match_first_index))):
            return None
    if (TABLE not in obj or obj.data.attributes.get(ID) is None
            or obj.data.attributes.get(REST) is None):
        return None
    try:
        table = json.loads(obj[TABLE])
    except (TypeError, ValueError):
        return None
    return table if isinstance(table, dict) else None


def build_draw_loop_map(mesh, source_tables, check_positions=True):
    """Build the cloth record for each corner in the evaluated export mesh."""
    from ..utils.draw_range_utils import DrawRangeUtils

    # A whole draw uses ordinary skinning if any of its rendered points lost
    # provenance or moved. UV splits and unused source points are harmless.
    records = np.zeros((len(mesh.loops), 4), dtype='<u4')
    records[:, 3] = NO_CLOTH
    if not any(source_tables):
        return records
    source = mesh.attributes.get(ID)
    rest = mesh.attributes.get(REST)
    if (source is None or source.domain != 'POINT' or source.data_type != 'INT'
            or rest is None or rest.domain != 'POINT' or rest.data_type != 'FLOAT_VECTOR'):
        return records

    owners = mesh.attributes.get(DrawRangeUtils.OWNER_ATTRIBUTE)
    if owners is None:
        raise ValueError("YYSLS cloth: export mesh lost polygon ownership")
    loops_by_draw = [[] for _ in source_tables]
    owner_ids = np.empty(len(mesh.polygons), dtype=np.int32)
    owners.data.foreach_get('value', owner_ids)
    for polygon, owner in zip(mesh.polygons, owner_ids):
        if not 1 <= owner <= len(source_tables):
            raise ValueError("YYSLS cloth: export mesh contains unowned polygons")
        loops_by_draw[owner - 1].extend(polygon.loop_indices)

    ids = np.empty(len(mesh.vertices), dtype=np.int32)
    reference = np.empty((len(mesh.vertices), 3), dtype=np.float32)
    positions = np.empty_like(reference)
    loop_points = np.empty(len(mesh.loops), dtype=np.int32)
    source.data.foreach_get('value', ids)
    rest.data.foreach_get('vector', reference.ravel())
    mesh.vertices.foreach_get('co', positions.ravel())
    mesh.loops.foreach_get('vertex_index', loop_points)

    for table, loops in zip(source_tables, loops_by_draw):
        if not table or not loops:
            continue
        points = loop_points[loops]
        # Export copies have already been rotated to the original game space.
        if check_positions and not np.allclose(positions[points], reference[points], rtol=0, atol=2e-6):
            continue
        try:
            records[loops] = pack_map(ids, reference, table, points).view('<u4').reshape(-1, 4)
        except (TypeError, ValueError):
            # Invalid/missing IDs must never reach the simulation texture.
            continue
    return records


def recover_source_ids(positions, faces, corner_uvs, source_positions, source_uvs, source_faces, tolerance=2e-6):
    """Recover a legacy mesh only when oriented triangle constraints are unique.

    This does not assume that vertex order survived editing. Position and UV
    candidates are intersected with original triangle connectivity to a fixed
    point. Ambiguous, retopologized or position-edited meshes are refused.
    Unused points stay unmapped rather than receiving arbitrary simulation IDs.
    """
    from collections import defaultdict
    positions = np.asarray(positions)
    source_positions = np.asarray(source_positions)
    source_uvs = np.asarray(source_uvs)
    candidates = []
    for position in positions:
        candidates.append(set(np.flatnonzero(
            np.max(np.abs(source_positions - position), axis=1) < tolerance).tolist()))
    if len(faces) != len(corner_uvs):
        raise ValueError("YYSLS cloth: face/UV counts differ")
    used = set()
    for face, uvs in zip(faces, corner_uvs):
        if len(face) != 3 or len(uvs) != 3:
            raise ValueError("YYSLS cloth recovery requires triangles")
        for vertex, uv in zip(face, uvs):
            used.add(vertex)
            candidates[vertex] = {i for i in candidates[vertex]
                                  if np.max(np.abs(source_uvs[i] - uv)) < tolerance}
    # Store all cyclic rotations, retaining winding. Blender reverses YYSLS
    # winding at import, so current faces are reversed before matching below.
    lookup = defaultdict(list)
    for triangle in source_faces:
        triangle = tuple(int(i) for i in triangle)
        for rotation in range(3):
            value = triangle[rotation:] + triangle[:rotation]
            lookup[value[0]].append(value)
    changed = True
    while changed:
        changed = False
        for face in faces:
            vertices = list(reversed(face))
            allowed = [t for i in candidates[vertices[0]] for t in lookup[i]
                       if t[1] in candidates[vertices[1]] and t[2] in candidates[vertices[2]]]
            if not allowed:
                raise ValueError("YYSLS cloth: no original oriented triangle matches")
            for corner, vertex in enumerate(vertices):
                narrowed = candidates[vertex] & {t[corner] for t in allowed}
                changed |= narrowed != candidates[vertex]
                candidates[vertex] = narrowed
    if any(len(candidates[i]) != 1 for i in used):
        raise ValueError("YYSLS cloth: original simulation identity is ambiguous")
    result = np.full(len(positions), -1, dtype=np.int32)
    for vertex in used:
        result[vertex] = next(iter(candidates[vertex]))
    return result
