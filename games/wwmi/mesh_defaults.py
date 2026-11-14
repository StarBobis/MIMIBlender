"""Fill missing WWMI attributes on disposable component copies.

The caller prepares modifiers, mirror restoration and triangulation first.
Every temporary part of one DrawIB participates in the projection bounds.
Existing attributes remain authoritative, even when all their values are zero.
COLOR1 belongs to the secondary vertex stream and must not inherit white.
The first UV is empty when absent; the second copies that primary UV.
The third uses the same XZ projection and padding as WWMI-Tools 1.8.0.
A zero-size projection falls back to the center instead of dividing by zero.
This helper never reads or changes another preset's global export defaults.
"""

import numpy


def fill_missing_mesh_data(objects):
    # Fill before joining: otherwise one component's existing layer masks
    # another component's missing layer. Never modify source scene objects.
    meshes = [obj.data for obj in objects]
    projection = None
    for mesh in meshes:
        for name, color in (("COLOR", (0, 0.25, 0, 1)), ("COLOR1", (0, 0, 0, 0))):
            if name not in mesh.attributes:
                attr = mesh.color_attributes.new(name=name, type='FLOAT_COLOR', domain='CORNER')
                values = numpy.tile(color, (len(mesh.loops), 1)).astype(numpy.float32)
                attr.data.foreach_set('color', values.ravel())

        # Explicit writes avoid Blender's implicit copy-from-active-UV default.
        if 'TEXCOORD.xy' not in mesh.uv_layers:
            uv = mesh.uv_layers.new(name='TEXCOORD.xy')
            uv.data.foreach_set('uv', numpy.zeros(len(mesh.loops) * 2, dtype=numpy.float32))
        if 'TEXCOORD1.xy' not in mesh.uv_layers:
            values = numpy.empty(len(mesh.loops) * 2, dtype=numpy.float32)
            mesh.uv_layers['TEXCOORD.xy'].data.foreach_get('uv', values)
            mesh.uv_layers.new(name='TEXCOORD1.xy').data.foreach_set('uv', values)

        if 'TEXCOORD2.xy' in mesh.uv_layers:
            continue
        # Compute one XZ bounding box for all exported component copies.
        # Lazy construction avoids reading positions when no projection is needed.
        if projection is None:
            positions = {}
            for part in meshes:
                coords = numpy.empty(len(part.vertices) * 3, dtype=numpy.float32)
                part.vertices.foreach_get('co', coords)
                positions[part] = coords.reshape(-1, 3)[:, [0, 2]]
            nonempty = [coords for coords in positions.values() if len(coords)]
            all_coords = numpy.vstack(nonempty) if nonempty else numpy.zeros((1, 2))
            lower, upper = all_coords.min(axis=0), all_coords.max(axis=0)
            projection = positions, (lower + upper) * 0.5, float((upper - lower).max())
        positions, center, scale = projection
        # A point-sized object has no projection extent. Use the UV center
        # instead of producing NaNs that would contaminate exported buffers.
        uv = (positions[mesh] - center) / scale * 0.98 + 0.5 if scale > 0 else numpy.full_like(positions[mesh], 0.5)
        indices = numpy.empty(len(mesh.loops), dtype=numpy.int32)
        mesh.loops.foreach_get('vertex_index', indices)
        mesh.uv_layers.new(name='TEXCOORD2.xy').data.foreach_set('uv', uv[indices].ravel())
