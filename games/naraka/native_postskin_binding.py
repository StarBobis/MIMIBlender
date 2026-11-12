"""Source correspondence for the validated vertex/edge-midpoint subdivision.

This module has no Blender dependency. It consumes verified extraction arrays
and exported vertex attributes, retaining the source group identity needed by
the native deformation recipe. Unsupported additions fail before writing INI.
"""
import itertools
import numpy as np
from .native_postskin_data import NativePostSkinError


def bind_subdivision_sources(evidence, vertices, uv, triangles):
    """Return two parent group IDs per vertex; -1 denotes a single parent.

    Position alone cannot identify overlapping surfaces. UV and normal evidence
    select among nearby candidates, while triangle ownership independently
    checks the selected correspondence against the source topology.
    """
    vertices = np.asarray(vertices, dtype=np.float32)
    uv = np.asarray(uv, dtype=np.float32)
    triangles = np.asarray(triangles)
    if vertices.ndim != 2 or vertices.shape[1] != 10 or uv.shape != (len(vertices), 2):
        raise NativePostSkinError("Native export requires P12/N12/TA16 and one float2 UV")
    if not np.isfinite(vertices).all() or not np.isfinite(uv).all():
        raise NativePostSkinError("Exported native attributes contain non-finite values")
    if triangles.ndim != 2 or triangles.shape[1] != 3 or triangles.dtype.kind not in "iu":
        raise NativePostSkinError("Native export requires integer triangle records")
    if not len(triangles) or triangles.min() < 0 or triangles.max() >= len(vertices):
        raise NativePostSkinError("Exported triangles exceed the vertex buffer")
    source = evidence["source_vertices"]
    source_uv = evidence["source_uv"]
    source_triangles = evidence["source_triangles"]
    members, offsets = evidence["members"], evidence["offsets"]
    source_groups = np.empty(len(source), dtype=np.int64)
    for group in range(len(offsets) - 1):
        source_groups[members[offsets[group]:offsets[group + 1]]] = group

    buckets = {}
    def add(point, parents, texcoord, normal):
        key = tuple(np.rint(point.astype(np.float64) * 1e6).astype(np.int64))
        buckets.setdefault(key, []).append((point, parents, texcoord, normal))

    # Candidates carry the actual source-side UV/normal combination. Mixing
    # attributes from unrelated members could falsely resolve an overlap.
    for vertex in range(len(source)):
        add(source[vertex, :3], (int(source_groups[vertex]),), source_uv[vertex], source[vertex, 3:6])
    edges = np.concatenate([source_triangles[:, [0, 1]], source_triangles[:, [1, 2]], source_triangles[:, [2, 0]]])
    edges = np.unique(np.sort(edges, axis=1), axis=0)
    for left, right in edges:
        parents = tuple(sorted((int(source_groups[left]), int(source_groups[right]))))
        add((source[left, :3] + source[right, :3]) * 0.5, parents,
            (source_uv[left] + source_uv[right]) * 0.5,
            (source[left, 3:6] + source[right, 3:6]) * 0.5)

    parents = []
    neighbors = list(itertools.product((-1, 0, 1), repeat=3))
    for vertex, point in enumerate(vertices[:, :3]):
        key = np.rint(point.astype(np.float64) * 1e6).astype(np.int64)
        candidates = []
        for neighbor in neighbors:
            for candidate, origin, texcoord, normal in buckets.get(tuple(key + neighbor), ()):
                distance = float(np.linalg.norm(point - candidate))
                if distance > 1e-7:
                    continue
                direction = normal / max(float(np.linalg.norm(normal)), 1e-20)
                score = (float(np.linalg.norm(uv[vertex] - texcoord)), float(np.linalg.norm(vertices[vertex, 3:6] - direction)), distance)
                candidates.append((distance, origin, score))
        # UV/normal may resolve equally close surfaces, but must not pull a
        # vertex onto a geometrically less accurate nearby edge. The position
        # tolerance admits rounding noise; it is not a surface search radius.
        nearest = min((item[0] for item in candidates), default=float("inf"))
        scores = {}
        for distance, origin, score in candidates:
            if distance <= nearest + 1e-9:
                scores[origin] = min(scores.get(origin, score), score)
        ranked = sorted((score, origin) for origin, score in scores.items())
        if not ranked:
            raise NativePostSkinError("Vertex has no supported source correspondence: " + str(vertex))
        if len(ranked) > 1:
            best, second = ranked[0][0], ranked[1][0]
            if abs(best[0] - second[0]) < 1e-6 and abs(best[1] - second[1]) < 1e-3:
                raise NativePostSkinError("Ambiguous native source correspondence: " + str(vertex))
        parents.append(ranked[0][1])

    # Independent ownership rejects a plausible-looking position match that
    # joins vertices from different original triangles or overlapping surfaces.
    original_faces = {tuple(sorted(set(map(int, row)))) for row in source_groups[source_triangles]}
    for index, triangle in enumerate(triangles):
        owner = tuple(sorted({group for vertex in triangle for group in parents[vertex]}))
        if owner not in original_faces:
            raise NativePostSkinError("Triangle does not belong to a source surface: " + str(index))
    return np.array([origin + (-1,) * (2 - len(origin)) for origin in parents], dtype="<i4")
