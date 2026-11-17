"""Create an interaction control group from the selected vertices.

The control group carries the weight of the pull for every vertex of a
region.  The weight has to fall off smoothly towards the border of the
region, otherwise the deformation tears the surface open instead of
stretching it.

The tool therefore feathers the selection: the selected vertices keep the
full weight, and the rings around them receive a smaller weight that grows
smoothly towards the selected ones.  The rings lie outside the selection,
so the weight falls to zero at the border of the region.

The created group is named with the interaction prefix, so it is never
mistaken for a numbered bone group.  The name carries the name of the
object as well, so two objects with the same region label do not end up
in one group.  The exporter deletes the group from the temporary export
copy, so it never reaches the game as a skin weight.
"""

import hashlib

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

    The name also carries a short digest of the label and the object, so
    two labels that only differ in characters that are not allowed in a
    name, such as "Region 1" and "Region1", still get their own group.
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

    # The digest keeps two different regions apart, even when their names
    # look the same after the characters were cleaned up.
    digest_source = (label or "") + "\0" + (object_name or "")
    digest = hashlib.md5(digest_source.encode("utf-8")).hexdigest()[:6]
    return GROUP_PREFIX + clean_label + "_" + clean_object + "_" + digest


def _smooth_step(value):
    """Return the smooth step of a value between zero and one."""
    return value * value * (3.0 - 2.0 * value)


def _build_feathered_weights(bmesh, selected_vertex_index_set, feather_rings):
    """Return the weight of every vertex that belongs to the region.

    The vertices in the selection keep the full weight.  The rings around
    the selection receive a smaller weight that grows smoothly towards the
    selection, so the region fades out towards its border and the surface
    stays continuous.

    The rings are outside the selection on purpose.  If the fade went inwards
    instead, a selection that covers a whole part of the body would give
    every vertex the same weight, and a constant weight has no gradient, so
    the part could not be pulled at all.
    """
    weights = {vertex_index: 1.0 for vertex_index in selected_vertex_index_set}

    # Spread the feather from the selection towards the outside.
    visited = set(selected_vertex_index_set)
    current_ring = set(selected_vertex_index_set)
    for ring_index in range(1, feather_rings + 1):
        # The weight of this ring, counted from the selection outwards.
        # It falls towards zero, so the border of the region ends at zero.
        ratio = ring_index / (feather_rings + 1)
        weight = 1.0 - _smooth_step(ratio)
        next_ring = set()
        for vertex_index in current_ring:
            vertex = bmesh.verts[vertex_index]
            for edge in vertex.link_edges:
                other = edge.other_vert(vertex)
                if other.index in visited:
                    continue
                next_ring.add(other.index)
        for vertex_index in next_ring:
            weights[vertex_index] = weight
        visited.update(next_ring)
        current_ring = next_ring
        if not current_ring:
            break

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
        name=tr("Feather Rings"), default=2, min=1, max=MAX_FEATHER_RINGS,
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

        # The selection lives in the edit cage, which is not the mesh of
        # the object.  A bmesh that is built from the mesh reads the older
        # flags of the mesh and would feather the selection of an earlier
        # run, so the edit cage is used while the object is being edited.
        owns_bmesh = False
        if is_edit_mode(context):
            bmesh_data = bmesh.from_edit_mesh(mesh)
        else:
            bmesh_data = bmesh.new()
            bmesh_data.from_mesh(mesh)
            owns_bmesh = True
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
            # The bmesh of the edit cage belongs to Blender and must not be
            # freed, only a bmesh that was made here may be.
            if owns_bmesh:
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
        if vertex_group is not None:
            # The group is written from scratch, so an older run cannot
            # leave stale weights behind.  The vertex group of a mesh has
            # no element list any more, so the group is removed and made
            # again.  That is much faster than removing the vertices one
            # by one.
            obj.vertex_groups.remove(vertex_group)
        vertex_group = obj.vertex_groups.new(name=group_name)

        for vertex_index, weight in weights.items():
            if weight <= 0.0:
                continue
            vertex_group.add([vertex_index], weight, 'REPLACE')

        entry.object_name = obj.name
        entry.vertex_group = vertex_group.name
        entry.enabled = True

        self.report({'INFO'}, tr("Created the control group {name}").format(name=vertex_group.name))
        return {'FINISHED'}


class MIMI_OT_InteractionDetectPicker(I18nOperator):
    """Read capture evidence; never require novices to copy shader hashes."""
    bl_idname = 'mimi.interaction_detect_picker'
    bl_label = 'Configure picking from capture'
    bl_options = {'REGISTER', 'UNDO'}
    tree_name: bpy.props.StringProperty(default='') # type: ignore
    node_name: bpy.props.StringProperty(default='') # type: ignore

    def execute(self, context):
        import re
        from pathlib import Path
        from .blueprint_node_interaction import find_interaction_node
        from ..common.global_config import GlobalConfig
        from ..common.interaction.capture import find_picker_shaders
        node = find_interaction_node(context,self.tree_name,self.node_name)
        if node is None or not node.regions:
            return {'CANCELLED'}
        entry = node.regions[min(node.region_index,len(node.regions)-1)]
        match = re.search(r'(?:^|\.)([0-9a-fA-F]{8})-',entry.object_name)
        if not match:
            self.report({'ERROR'},tr('Choose an imported mesh object first'))
            return {'CANCELLED'}
        folder = node.capture_directory
        if not folder:
            captures = sorted(Path(GlobalConfig.current_game_migoto_folder).glob('FrameAnalysis-*'))
            folder = str(captures[-1]) if captures else ''
        try:
            vs,ps = find_picker_shaders(bpy.path.abspath(folder),match[1])
        except (OSError,ValueError) as error:
            self.report({'ERROR'},tr('Picking configuration failed') + ': ' + tr(str(error)))
            return {'CANCELLED'}
        node.pick_vs,node.pick_ps = vs,ps
        node.capture_directory = folder
        self.report({'INFO'},tr('Picking shaders configured from capture'))
        return {'FINISHED'}


class MIMI_OT_InteractionCopyGroup(I18nOperator):
    """Copy authored weights without changing the original bone group.

    A new control group is always created. Blender undo owns the entire
    operation and the original rig weights remain available to skinning.
    """
    bl_idname = 'mimi.interaction_copy_group'
    bl_label = 'Copy weights to this region'
    bl_options = {'REGISTER', 'UNDO'}
    tree_name: bpy.props.StringProperty(default='') # type: ignore
    node_name: bpy.props.StringProperty(default='') # type: ignore
    region_index: bpy.props.IntProperty(default=0) # type: ignore

    def execute(self, context):
        from .blueprint_node_interaction import find_interaction_node
        node = find_interaction_node(context, self.tree_name, self.node_name)
        if node is None or not 0 <= self.region_index < len(node.regions):
            return {'CANCELLED'}
        entry = node.regions[self.region_index]
        obj = bpy.data.objects.get(entry.object_name)
        if obj is None or obj.type != 'MESH' or obj.mode != 'OBJECT' or obj.library:
            self.report({'WARNING'}, tr('Choose a local mesh in Object Mode first'))
            return {'CANCELLED'}
        source = obj.vertex_groups.get(entry.source_group)
        if source is None:
            self.report({'WARNING'}, tr('Choose an existing vertex group first'))
            return {'CANCELLED'}
        weights = [(v.index, g.weight) for v in obj.data.vertices
                   for g in v.groups if g.group == source.index and g.weight > 0]
        if not weights:
            self.report({'WARNING'}, tr('The source vertex group has no weights'))
            return {'CANCELLED'}
        # Never overwrite an existing group, even if its generated name
        # matches. Blender adds a suffix and the entry follows the real name.
        group = obj.vertex_groups.new(name=build_group_name(entry.label, obj.name))
        for index, weight in weights:
            group.add([index], weight, 'REPLACE')
        entry.vertex_group = group.name
        entry.enabled = True
        self.report({'INFO'}, tr('Control group ready; check its weight falloff'))
        return {'FINISHED'}


classes = (
    MIMI_OT_InteractionCreateRegion,
    MIMI_OT_InteractionCopyGroup,
    MIMI_OT_InteractionDetectPicker,
)


def register():
    """Register the region tool."""
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    """Unregister the region tool."""
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
