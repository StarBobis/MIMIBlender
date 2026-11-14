"""Shared geometry weld with explicit per-game output semantics.

This module never builds indices or changes vertex ownership.
It receives the final structured vertices and the existing triangle indices.
Fields not selected by a game's outline policy remain byte-for-byte intact.
The caller opts in; legacy exports keep their previous implementation.
"""

import numpy


def validate_outline_layout(dtype, preset, options):
    # Validate before temporary model construction as well as direct buffer calls.
    # Opting into modern reconstruction must never silently write the wrong field.
    from ..i18n.i18n import tr
    target = 'TEXCOORD1' if preset == 'ZZMI' else 'COLOR' if preset == 'HIMI' and options.get('himi_target') == 'COLOR' else 'TANGENT'
    required = {'POSITION': 3, target: 4 if target == 'COLOR' else 2 if target == 'TEXCOORD1' else 3}
    if preset == 'ZZMI' or options.get('custom_normals'):
        required['NORMAL'] = 3
    if preset == 'ZZMI':
        required['TANGENT'] = 4
    for name, width in required.items():
        if name not in (dtype.names or ()) or not dtype.fields[name][0].shape or dtype.fields[name][0].shape[0] < width:
            raise ValueError(tr('Outline rebuild is missing a required vertex semantic'))
    if target == 'TEXCOORD1' and dtype.fields[target][0].base.kind != 'f':
        raise ValueError(tr('ZZMI outline rebuild requires floating TEXCOORD1'))
    return target


def unit_vectors(values):
    # Degenerate faces contribute zero instead of NaNs to neighboring welds.
    norms = numpy.linalg.norm(values, axis=1, keepdims=True)
    return values / numpy.where(norms > 0, norms, 1)


def weld_directions(positions, indices, precision=8, normals=None):
    # atan2 preserves obtuse interior angles, unlike abs-based arccos.
    # Group corners rather than vertices so split seams share the weld.
    indices = numpy.asarray(indices, dtype=numpy.int64).reshape(-1)
    if len(indices) % 3 or numpy.any(indices < 0) or numpy.any(indices >= len(positions)):
        from ..i18n.i18n import tr
        raise ValueError(tr('Outline rebuild requires valid triangle indices'))
    result = numpy.zeros((len(positions), 3), dtype=numpy.float64)
    if not len(indices):
        return result
    corners = positions[indices].reshape(-1, 3, 3)
    angles = []
    for corner in range(3):
        a = corners[:, (corner + 1) % 3] - corners[:, corner]
        b = corners[:, (corner + 2) % 3] - corners[:, corner]
        angles.append(numpy.arctan2(numpy.linalg.norm(numpy.cross(a, b), axis=1), numpy.einsum('ij,ij->i', a, b)))
    weights = numpy.stack(angles, axis=1).reshape(-1, 1)
    if normals is None:
        faces = unit_vectors(numpy.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0]))
        directions = numpy.repeat(faces, 3, axis=0)
    else:
        # Custom normals are a deliberate opt-in, never an implicit fallback.
        directions = unit_vectors(normals[indices])
    groups, inverse = numpy.unique(numpy.round(positions[indices], precision), axis=0, return_inverse=True)
    accumulated = numpy.zeros((len(groups), 3), dtype=numpy.float64)
    numpy.add.at(accumulated, inverse, directions * weights)
    result[indices] = unit_vectors(accumulated[inverse])
    return result


def decode_direction(values):
    # Integer NORMAL/TANGENT fields have already passed the format packer.
    # Decode them once for math and encode once at the output boundary.
    dtype = values.dtype
    if dtype.kind == 'i':
        return numpy.maximum(values.astype(float) / numpy.iinfo(dtype).max, -1)
    if dtype.kind == 'u':
        return values.astype(float) / numpy.iinfo(dtype).max * 2 - 1
    return values.astype(float)


def encode_direction(values, dtype):
    if dtype.kind == 'u':
        return numpy.rint((numpy.clip(values, -1, 1) + 1) * .5 * numpy.iinfo(dtype).max).astype(dtype)
    if dtype.kind == 'i':
        return numpy.rint(numpy.clip(values, -1, 1) * numpy.iinfo(dtype).max).astype(dtype)
    return values.astype(dtype)


def rebuild_outline(vertices, indices, preset, options):
    # Work on a private structured buffer; never mutate the source mesh.
    vb = vertices.copy()
    names = vb.dtype.names or ()
    target = validate_outline_layout(vb.dtype, preset, options)
    if not len(vb):
        return vb
    normal = decode_direction(vb['NORMAL'])[:, :3] if 'NORMAL' in names else None
    weld = weld_directions(vb['POSITION'][:, :3].astype(float), indices,
                           int(options.get('precision', 8)), normal if options.get('custom_normals') else None)
    # Unreferenced vertices retain their original bytes, including loose points.
    used = numpy.unique(numpy.asarray(indices, dtype=numpy.int64).reshape(-1))
    field = vb[target]
    if target == 'COLOR':
        # COLOR is UNORM or float color, not a signed direction. Preserve alpha.
        rgb = (weld[used] + 1) * .5
        if field.dtype.kind in 'ui':
            rgb = numpy.rint(rgb * numpy.iinfo(field.dtype).max)
        field[used, :3] = rgb.astype(field.dtype)
    elif target == 'TANGENT':
        field[used, :3] = encode_direction(weld[used], field.dtype)
        if field.shape[1] >= 4:
            # Retain the established Unity export convention for tangent.w.
            w = decode_direction(field[used, 3])
            field[used, 3] = encode_direction(numpy.where(w >= 0, -1, 1), field.dtype)
    else:
        # Project into the exported smooth TBN basis, leaving TANGENT intact.
        tangent = decode_direction(vb['TANGENT'])
        tangent_xyz = unit_vectors(tangent[:, :3])
        # The existing Unity packer negates Blender's bitangent sign in w.
        bitangent = numpy.cross(normal, tangent_xyz) * -tangent[:, 3:4]
        projected = numpy.stack((numpy.einsum('ij,ij->i', weld, tangent_xyz), numpy.einsum('ij,ij->i', weld, bitangent)), axis=1)
        angle = numpy.degrees(numpy.arccos(numpy.clip(numpy.einsum('ij,ij->i', weld, normal), -1, 1)))
        projected[angle < float(options.get('gate', 10))] = 0
        field[used, :2] = projected[used].astype(field.dtype)
    return vb
