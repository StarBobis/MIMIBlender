"""Keep object draw ranges tied to the polygons actually written to the IB."""
import numpy


class DrawRangeUtils:
    # This attribute exists only on disposable export copies, never source meshes.
    # Blender carries FACE attributes through joins and supported modifiers.
    # It is not a vertex semantic, so it adds no bytes to the game buffers.
    OWNER_ATTRIBUTE = 'mimi_export_draw_owner'

    @classmethod
    def tag_object(cls, obj, owner):
        # Replace inherited tags on the copy so previous exports cannot leak IDs.
        # Tag after source triangulation to cover every exported source triangle.
        mesh = obj.data
        existing = mesh.attributes.get(cls.OWNER_ATTRIBUTE)
        if existing is not None:
            mesh.attributes.remove(existing)
        attribute = mesh.attributes.new(cls.OWNER_ATTRIBUTE, 'INT', 'FACE')
        values = numpy.full(len(mesh.polygons), owner, dtype=numpy.int32)
        attribute.data.foreach_set('value', values)

    @classmethod
    def align_buffer_ranges(cls, mesh, ib, draws):
        # The buffer builders traverse polygons and may reverse triangle winding.
        # Preserve each whole triangle and every VB/loop mapping unchanged.
        # Only reorder complete polygon index spans into their owning draw.
        attribute = mesh.attributes.get(cls.OWNER_ATTRIBUTE)
        if attribute is None or len(attribute.data) != len(mesh.polygons):
            raise ValueError('Export mesh lost polygon ownership; refusing unsafe draw ranges')
        owners = numpy.empty(len(mesh.polygons), dtype=numpy.int32)
        attribute.data.foreach_get('value', owners)
        # Each owner has its own bucket even if names repeat across branches.
        # Empty buckets remain valid zero-length draws without stealing faces.
        # Bucket order is the same order used to tag temporary source objects.
        # The exact mesh is essential: a second depsgraph evaluation may differ.
        segments = [[] for draw in draws]
        cursor = 0
        for polygon, owner in zip(mesh.polygons, owners):
            # Reject lost/generated ownership instead of silently assigning a key.
            # One-based IDs leave zero available to detect unassigned new faces.
            if owner < 1 or owner > len(draws) or polygon.loop_total != 3:
                raise ValueError('Export mesh contains unowned or non-triangular polygons')
            end = cursor + polygon.loop_total
            segments[owner - 1].extend(ib[cursor:end])
            cursor = end
        if cursor != len(ib):
            raise ValueError('Export IB does not match evaluated polygon spans')

        # Derive count AND offset from the actual output, not pre-join estimates.
        # An object can span disconnected upper/lower geometry or modifier copies.
        # All its triangles now form one range under the original key condition.
        ordered_ib = []
        for draw, segment in zip(draws, segments):
            draw.index_offset = len(ordered_ib)
            draw.index_count = len(segment)
            ordered_ib.extend(segment)
        return ordered_ib
