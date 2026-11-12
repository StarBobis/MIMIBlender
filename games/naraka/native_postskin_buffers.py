"""Generate native CS input arrays from verified source correspondence.

The returned arrays are model-owned resources. Package shaders only execute
the shared operations; they do not infer topology or bindings at runtime.
This first recipe supports the measured single-batch, 40-byte output layout.
"""
import numpy as np
from .native_postskin_data import NativePostSkinError


def build_native_buffers(evidence, parents, triangles):
    """Build the exact affine expansion and native normal CSR tables.

    Three transform families represent simulation*g*scale, bones, and bones*g.
    Signed weights add the full skinned term and subtract its alpha*g part.
    This avoids interpolating alpha and position independently, which introduces
    cross terms when neighboring source vertices have different blend values.

    Input contract:
        evidence is produced by load_native_postskin and has verified files.
        parents is produced by bind_subdivision_sources, with two signed IDs.
        A negative second ID denotes an original source vertex/group.
        Two IDs denote the equally weighted endpoints of a subdivided edge.
        triangles references the final exported render vertex buffer.
        Triangles have already passed source-surface ownership checks.

    Position records use the original native mixed float/integer layout:
        uint target_group, uint influence_start, uint influence_end, padding;
        float alpha followed by native padding fields.
        Each generated target group owns exactly one exported render vertex.
        Source influences retain their frame-local coordinates and frame IDs.
        The synthetic bone families follow the original simulation frame IDs.
        Alpha is one because all blend terms are represented explicitly.
        Original live blend/scale values are consumed by the Package helper.

    Normal resources use a separate grouping:
        UV-split vertices with equal source correspondence remain welded.
        Adjacency entries are triangle-corner indices, including corner order.
        Target groups inherit the affected original native normal groups.
        Zero-filled output resources are allocations, not captured poses.
        Their contents are populated from live inputs by the Package runtime.

    Output is a dictionary of arrays and dispatch sizes, with no disk mutation.
    The export layer chooses resource names, writes files and emits scoped calls.
    Generation never disables either native pass as an error-recovery fallback.
    Unsupported batch layouts fail before a partial resource set is returned.
    """
    parents = np.asarray(parents)
    triangles = np.asarray(triangles)
    if parents.ndim != 2 or parents.shape[1] != 2 or parents.dtype.kind not in "iu":
        raise NativePostSkinError("Invalid native source-parent records")
    count = len(parents)
    if not 0 < count <= 65535 * 64:
        raise NativePostSkinError("Native vertex count exceeds dispatch capacity")
    members, offsets = evidence["members"], evidence["offsets"]
    group_count = len(offsets) - 1
    if np.any(parents[:, 0] < 0) or np.any(parents >= group_count) or np.any(parents[:, 1] < -1):
        raise NativePostSkinError("Native parent group exceeds source table")
    if triangles.ndim != 2 or triangles.shape[1] != 3 or triangles.dtype.kind not in "iu":
        raise NativePostSkinError("Native normal input requires integer triangles")
    if not triangles.size or triangles.min() < 0 or triangles.max() >= count:
        raise NativePostSkinError("Native normal triangles exceed exported vertices")

    # The measured recipe uses one batch and local-depth mode zero. The helper
    # preserves dynamic g/scale, but multi-batch offset selection needs another
    # validated recipe rather than interpreting those records as this format.
    inputs = evidence["position_inputs"]
    cb = np.frombuffer(inputs["cs-cb0"], "<u4")
    batch = np.frombuffer(inputs["cs-t0"], "<u4")
    frame_offsets = np.frombuffer(inputs["cs-t1"], "<u4")
    if len(cb) != 12 or tuple(cb[:2]) != (1, 1) or cb[4] != 0 or cb[6] != 0:
        raise NativePostSkinError("Unsupported native batch or depth-conversion mode")
    if len(batch) != 4 or batch[0] != 0 or batch[2] != 0 or not len(frame_offsets) or frame_offsets[0] != 0:
        raise NativePostSkinError("Unsupported native frame-base selection")
    source = evidence["source_vertices"]
    blend = np.frombuffer(evidence["source_blend_bytes"], dtype=np.dtype([("w", "<f4", 4), ("i", "<i4", 4)]))
    bone_count, frame_count = evidence["bone_count"], evidence["frame_count"]
    if not np.isfinite(blend["w"]).all() or np.any(blend["w"] < 0) or not np.allclose(blend["w"].sum(1), 1, atol=1e-4):
        raise NativePostSkinError("Invalid native source skinning weights")
    if np.any(blend["i"] < 0) or np.any(blend["i"] >= bone_count):
        raise NativePostSkinError("Source bone index exceeds captured skeleton")
    records = evidence["position_records"]
    record_int = records.view("<u4")
    influences = evidence["position_influences"]
    by_group = {int(row[0]): index for index, row in enumerate(record_int)}
    rows, terms = [], []
    for vertex, pair in enumerate(parents):
        origin = pair[pair >= 0]
        start = len(terms)
        for group in origin:
            source_vertex = int(members[offsets[group]])
            beta = 1.0 / len(origin)
            record = by_group.get(int(group))
            alpha = float(records[record, 4]) if record is not None else 0.0
            for weight, bone in zip(blend["w"][source_vertex], blend["i"][source_vertex]):
                if weight == 0:
                    continue
                # Synthetic bone frames use depth factors one and the same
                # local source position as the original skinning calculation.
                for factor, frame in [(beta * weight, frame_count + bone), (-beta * alpha * weight, frame_count + bone_count + bone)]:
                    if factor == 0:
                        continue
                    term = np.zeros(8, "<f4")
                    term[0], term[1:4] = factor, source[source_vertex, :3]
                    term.view("<u4")[4] = frame
                    terms.append(term)
            if record is not None:
                left, right = record_int[record, 1:3]
                for original in influences[left:right]:
                    term = original.copy()
                    term[0] *= beta * alpha
                    terms.append(term)
        row = np.zeros(8, "<f4")
        row.view("<u4")[:3] = vertex, start, len(terms)
        row[4] = 1
        rows.append(row)

    # Weld UV-split render vertices according to source group correspondence.
    # Native normal recomputation uses these groups, not raw export indices.
    keys = [tuple(sorted(map(int, pair[pair >= 0]))) for pair in parents]
    groups = {}
    render_groups = np.array([groups.setdefault(key, len(groups)) for key in keys], "<u4")
    normal_members = np.argsort(render_groups, kind="stable").astype("<u4")
    normal_offsets = np.concatenate(([0], np.cumsum(np.bincount(render_groups, minlength=len(groups))))).astype("<u4")
    normal_triangles = render_groups[triangles].astype("<u4")
    flat = normal_triangles.ravel()
    adjacency = np.argsort(flat, kind="stable").astype("<u4")
    adjacency_offsets = np.concatenate(([0], np.cumsum(np.bincount(flat, minlength=len(groups))))).astype("<u4")
    targets = set(map(int, evidence["normal_targets"]))
    normal_targets = np.array([groups[key] for key in groups if any(parent in targets for parent in key)], "<u4")
    # Every render vertex and triangle corner has exactly one owner. Preserve
    # stable order so regression comparison can detect accidental remapping.
    assert np.array_equal(np.sort(normal_members), np.arange(count))
    assert np.array_equal(np.sort(adjacency), np.arange(len(flat)))
    vertex_dispatch = (count + 63) // 64
    total_frames = frame_count + 2 * bone_count
    position_cb = np.array([1, 1, vertex_dispatch, count, 0, 0, 0, 0x3f800000, 0x3f800000, 0, 0, 0], "<u4")
    arrays = {
        "position-mapping": np.asarray(rows, dtype="<f4"),
        "position-influences": np.asarray(terms, dtype="<f4"),
        "position-members": np.arange(count, dtype="<u4"),
        "position-offsets": np.arange(count + 1, dtype="<u4"),
        "position-batch": np.array([0, count, 0, 0], "<u4"),
        "position-cb": position_cb,
        "normal-triangles": normal_triangles,
        "normal-targets": normal_targets,
        "normal-members": normal_members,
        "normal-offsets": normal_offsets,
        "normal-adjacency": adjacency,
        "normal-adjacency-offsets": adjacency_offsets,
        "normal-cb": np.array([len(normal_targets), 0, 0, 0], "<u4"),
        "limits-cb": np.array([count, 0, 0, 0], "<u4"),
        "extended-frames": np.zeros((total_frames, 20), "<f4"),
        "normal-shadow": np.zeros((count, 10), "<u4"),
    }
    return {"arrays": arrays, "vertex_count": count, "frame_count": total_frames,
            "vertex_dispatch": vertex_dispatch, "frame_dispatch": (total_frames + 63) // 64,
            "normal_dispatch": (len(normal_targets) + 63) // 64}
