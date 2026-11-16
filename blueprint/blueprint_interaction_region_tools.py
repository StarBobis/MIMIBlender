"""Create an interaction control group from the selected vertices.

The control group carries the weight of the pull for every vertex of a
region.  The weight has to fall off smoothly towards the border of the
region, otherwise the deformation tears the surface open instead of
stretching it.

The tool therefore feathers the selection: the selected vertices keep the
full weight, and the rings around them receive a smaller weight that grows
smoothly towards the selected ones.

The created group is named with the interaction prefix, so it is never
mistaken for a numbered bone group.  The exporter deletes the group from
the temporary export copy, so it never reaches the game as a skin weight.
"""

import bpy

from ..i18n.i18n import I18nOperator, tr


# The prefix of the control groups this tool creates.
GROUP_PREFIX = "MimiInteraction_"

# The number of rings that are feathered around the selection.
MAX_FEATHER_RINGS = 3

# The mode names Blender uses for the mesh edit mode.  Blender 5.2 reports
# "EDIT_MESH" instead of the older "EDIT".
EDIT_MODE_NAME_LIST = ("EDIT", "EDIT_MESH")


def is_edit_mode(context):
    """Return whether the context is in the mesh edit mode.

    Blender 5.2 renamed the mode to "EDIT_MESH".  The older name is still
    accepted, so the check works on both.
    """
    return getattr(context, "mode", "") in EDIT_MODE_NAME_LIST


def build_group_name(label, object_name):
    """Return the name of the control group of a region.

    The name carries the name of the object, because two objects with the
    same label would otherwise be joined into one group, and then both
    regions would pull both objects.
    """
    clean_label = "".join(
        character for character in (label or "Region")
        if character.isalnum() or character in ("_", "-"))
    if not clean_label:
        clean_label = "Region"
    clean_object = "".join(
        character for character in (object_name or "Object")
        if character.isalnum() or character in ("_", "-"))
    if not clean_object:
        clean_object = "Object"
    return GROUP_PREFIX + clean_label + "_" + clean_object


def _smooth_step(value):
    """Return the smooth step of a value between zero and one."""
    return value * value * (3.0 - 2.0 * value)


def _build_feathered_weights(bmesh, selected_vertex_index_set, feather_rings):
    """Return the weight of every vertex that belongs to the region.

    The vertices in the middle of the selection keep the full weight.  The
    vertices on the border of the selection get no weight at all, and the
    rings between the border and the middle receive a weight that grows
    towards the middle, so the border of the region ends at zero and the
    surface stays continuous.
    """
    weights = {}

    # A vertex is on the border when it touches a vertex that is not part
    # of the selection.  A hidden vertex counts as not selected here, so
    # it also ends the region.
    border_vertex_index_set = set()
    for vertex in bmesh.verts:
        if vertex.index not in selected_vertex_index_set:
            continue
        for edge in vertex.link_edges:
            other = edge.other_vert(vertex)
            if other.index not in selected_vertex_index_set:
                border_vertex_index_set.add(vertex.index)
                break

    if not border_vertex_index_set:
        # The whole connected component is selected, so there is no border
        # to fade out and every vertex keeps the full weight.
        for vertex_index in selected_vertex_index_set:
            weights[vertex_index] = 1.0
        return weights

    # Spread the feather from the border towards the inside.
    visited = set(border_vertex_index_set)
    current_ring = set(border_vertex_index_set)
    for ring_index in range(1, feather_rings + 1):
        # The weight of this ring, counted from the border inwards.
        ratio = (ring_index + 1) / (feather_rings + 1)
        weight = _smooth_step(ratio)
        next_ring = set()
        for vertex_index in current_ring:
            vertex = bmesh.verts[vertex_index]
            for edge in vertex.link_edges:
                other = edge.other_vert(vertex)
                if other.index not in selected_vertex_index_set:
                    continue
                if other.index in visited:
                    continue
                next_ring.add(other.index)
        for vertex_index in next_ring:
            weights[vertex_index] = weight
        visited.update(next_ring)
        current_ring = next_ring
        if not current_ring:
            break

    # Everything that is still unweighted and is not on the border sits in
    # the middle of the region and keeps the full weight.
    for vertex_index in selected_vertex_index_set:
        if vertex_index in weights:
            continue
        if vertex_index in border_vertex_index_set:
            continue
        weights[vertex_index] = 1.0

    return weights


class MIMI_OT_InteractionCreateRegion(I18nOperator):
    """Create a control group from the vertices selected in Edit Mode."""

    bl_idname = "mimi.interaction_create_region"
    bl_label = "Create Interaction Region"
    bl_options = {'UNDO'}

    tree_name: bpy.props.StringProperty(default="") # type: ignore
    node_name: bpy.props.StringProperty(default="") # type: ignore
    region_index: bpy.props.IntProperty(default=0, min=0) # type: ignore
    feather_rings: bpy.props.IntProperty(
        name=tr("Feather Rings"), default=2, min=0, max=MAX_FEATHER_RINGS,
    ) # type: ignore

    def _find_edit_target(self, context):
        """Return the single mesh object that is being edited."""
        obj = getattr(context, "object", None)
        if obj is None or obj.type != 'MESH':
            return None
        if not is_edit_mode(context):
            return None
        if obj.library is not None:
            # A linked object cannot carry a new vertex group.
            return None
        if obj.data.users > 1:
            # A shared mesh would change every user of it.
            return None
        return obj

    def execute(self, context):
        from .blueprint_node_interaction import find_interaction_node

        obj = self._find_edit_target(context)
        if obj is None:
            self.report({'WARNING'}, tr("Select one mesh and enter Edit Mode first"))
            return {'CANCELLED'}

        node = find_interaction_node(context, self.tree_name, self.node_name)
        if node is None or not 0 <= self.region_index < len(node.regions):
            self.report({'WARNING'}, tr("The interaction node lost its region row"))
            return {'CANCELLED'}

        import bmesh

        mesh = obj.data
        bmesh_data = bmesh.new()
        bmesh_data.from_mesh(mesh)
        try:
            # The vertex lookup table makes the vertices addressable by
            # their index, which the feather needs.
            bmesh_data.verts.ensure_lookup_table()
            selected_vertex_index_set = {
                vertex.index for vertex in bmesh_data.verts
                if vertex.select and not vertex.hide
            }
            if not selected_vertex_index_set:
                self.report({'WARNING'}, tr("Select at least one vertex first"))
                return {'CANCELLED'}

            weights = _build_feathered_weights(
                bmesh_data, selected_vertex_index_set, self.feather_rings)
        finally:
            bmesh_data.free()

        if not weights:
            self.report({'WARNING'}, tr("The selection did not produce any weight"))
            return {'CANCELLED'}

        # Leave Edit Mode before the group is created: the edit mode undo
        # does not capture the new group, so the user could only undo one
        # half of the operation.
        if is_edit_mode(context):
            bpy.ops.object.mode_set(mode='OBJECT')

        entry = node.regions[self.region_index]

        # The name of the group carries the name of the object, because
        # two objects with the same label would otherwise end up in one
        # merged group, and both regions would pull both objects.
        group_name = build_group_name(entry.label, obj.name)
        vertex_group = obj.vertex_groups.get(group_name)
        if vertex_group is None:
            vertex_group = obj.vertex_groups.new(name=group_name)
        else:
            # The group is written from scratch, so an older run cannot
            # leave stale weights behind.  The vertex group of a mesh has
            # no element list any more, so the vertices are removed one by
            # one.
            for vertex_index in range(len(mesh.vertices)):
                try:
                    vertex_group.remove([vertex_index])
                except RuntimeError:
                    # The vertex does not carry this group.
                    pass

        for vertex_index, weight in weights.items():
            if weight <= 0.0:
                continue
            vertex_group.add([vertex_index], weight, 'REPLACE')

        entry.object_name = obj.name
        entry.vertex_group = vertex_group.name
        entry.enabled = True

        self.report({'INFO'}, tr("Created the control group {name}").format(name=vertex_group.name))
        return {'FINISHED'}


classes = (
    MIMI_OT_InteractionCreateRegion,
)


def register():
    """Register the region tool."""
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    """Unregister the region tool."""
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
