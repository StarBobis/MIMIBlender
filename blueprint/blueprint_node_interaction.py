"""Blueprint node for the generic interaction deformation.

The node has no sockets: the object routes of the blueprint keep owning
the drawing, and this node only declares which regions of the model may be
pulled at runtime.  A region points at a mesh that is part of the normal
mod output and at a control vertex group that carries the weight of the
pull.

The pull itself is a vector whose length is a fraction of the longest
side of the model, so the same value behaves the same way on a large and
on a small body.
"""

import bpy

from ..common.global_config import GlobalConfig
from ..common.interaction import backend as interaction_backend
from ..i18n.i18n import I18nOperator, tr, translatable
from .blueprint_node_base import MIMINodeBase


INTERACTION_NODE_ID = "MIMINode_InteractionDeformation"

# The runtime layout carries the weight and the gradient of two regions.
MAX_INTERACTION_REGIONS = 2

# The prefix of the control vertex groups this feature creates.  The
# prefix keeps them apart from the numbered bone groups, which the
# exporter would otherwise treat as skin weights.
CONTROL_GROUP_PREFIX = "MimiInteraction_"


class MIMIInteractionRegion(bpy.types.PropertyGroup):
    """One pullable region of the model."""

    label: bpy.props.StringProperty(name=tr("Region Name"), default="") # type: ignore
    enabled: bpy.props.BoolProperty(name=tr("Enable Region"), default=True) # type: ignore
    object_name: bpy.props.StringProperty(
        name=tr("Region Object"), default="",
        description=tr("Choose a mesh that is already part of the normal Mod output"),
    ) # type: ignore
    vertex_group: bpy.props.StringProperty(
        name=tr("Control Vertex Group"), default="",
        description=tr("The vertex group weights decide how far each vertex is pulled"),
    ) # type: ignore
    source_group: bpy.props.StringProperty(default="") # type: ignore
    offset: bpy.props.FloatVectorProperty(
        name=tr("Pull"), size=3, default=(0.0, 0.0, 0.0),
        min=-1.0, max=1.0,
        description=tr("Pull direction and strength; the length is a fraction of the "
                       "distance this region can be pulled safely"),
    ) # type: ignore


class MIMI_UL_InteractionRegions(bpy.types.UIList):
    """The list of the pullable regions of the node."""

    bl_idname = "MIMI_UL_InteractionRegions"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)
            row.prop(item, "enabled", text="")
            row.prop(item, "label", text="", emboss=False, icon='GROUP_VERTEX')
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text="", icon='GROUP_VERTEX')


def find_interaction_node(context, tree_name, node_name):
    """Return the interaction node with the given name, or None.

    The lookup works on a named tree so a button in a popup still finds
    its own node.
    """
    if tree_name:
        tree = bpy.data.node_groups.get(tree_name)
    else:
        space = getattr(context, "space_data", None)
        tree = getattr(space, "edit_tree", None) or getattr(space, "node_tree", None)
        if tree is None:
            tree = getattr(getattr(context, "node", None), "id_data", None)
    if tree is None or not node_name:
        return None
    node = tree.nodes.get(node_name)
    if getattr(node, "bl_idname", "") != INTERACTION_NODE_ID:
        return None
    return node


class MIMI_OT_InteractionAddRegion(I18nOperator):
    """Add one more pullable region to the node."""

    bl_idname = "mimi.interaction_add_region"
    bl_label = "Add Interaction Region"
    bl_options = {'REGISTER', 'UNDO'}

    tree_name: bpy.props.StringProperty(default="") # type: ignore
    node_name: bpy.props.StringProperty(default="") # type: ignore

    def execute(self, context):
        node = find_interaction_node(context, self.tree_name, self.node_name)
        if node is None:
            return {'CANCELLED'}
        if len(node.regions) >= MAX_INTERACTION_REGIONS:
            self.report({'WARNING'}, tr("This version supports at most two interaction regions"))
            return {'CANCELLED'}
        entry = node.regions.add()
        entry.label = tr("Region {number}").format(number=len(node.regions))
        node.region_index = len(node.regions) - 1
        return {'FINISHED'}


class MIMI_OT_InteractionRemoveRegion(I18nOperator):
    """Remove one pullable region from the node."""

    bl_idname = "mimi.interaction_remove_region"
    bl_label = "Remove Interaction Region"
    bl_options = {'REGISTER', 'UNDO'}

    tree_name: bpy.props.StringProperty(default="") # type: ignore
    node_name: bpy.props.StringProperty(default="") # type: ignore

    def execute(self, context):
        node = find_interaction_node(context, self.tree_name, self.node_name)
        if node is None or not 0 <= node.region_index < len(node.regions):
            return {'CANCELLED'}
        index = node.region_index
        node.regions.remove(index)
        node.region_index = min(index, max(0, len(node.regions) - 1))
        return {'FINISHED'}


@translatable
class MIMINode_InteractionDeformation(MIMINodeBase):
    """Node that declares the pullable regions of the exported model."""

    bl_idname = INTERACTION_NODE_ID
    bl_label = "Chest Interaction Jiggle System"
    bl_icon = 'MOD_SIMPLIFY'
    bl_width_min = 320

    enabled: bpy.props.BoolProperty(name=tr("Enable Interaction Deformation"), default=True) # type: ignore
    # Existing files retain the fixed-pull path until the user opts in.
    mouse_drag: bpy.props.BoolProperty(name=tr("Mouse drag and spring return"), default=False) # type: ignore
    drag_strength: bpy.props.FloatProperty(default=0.7, min=0.01, max=1.0,
        description=tr('Fraction of the safe pull distance; start at 0.7')) # type: ignore
    drag_sensitivity: bpy.props.FloatProperty(default=2.0, min=0.1, max=10.0) # type: ignore
    spring_frequency: bpy.props.FloatProperty(default=3.5, min=0.1, max=20.0,
        description=tr('Oscillations per second; higher values bounce faster')) # type: ignore
    damping_ratio: bpy.props.FloatProperty(default=0.24, min=0.01, max=2.0,
        description=tr('Low damping keeps bouncing longer; 1 returns without oscillation')) # type: ignore
    flip_y: bpy.props.BoolProperty(default=True) # type: ignore
    reversed_z: bpy.props.BoolProperty(default=True) # type: ignore
    pick_vs: bpy.props.StringProperty(default="") # type: ignore
    pick_ps: bpy.props.StringProperty(default="") # type: ignore
    show_advanced: bpy.props.BoolProperty(default=False) # type: ignore
    show_debug: bpy.props.BoolProperty(default=False,
        description=tr('Show the in-game status labels and cursor; export and reload the Mod to apply')) # type: ignore
    capture_directory: bpy.props.StringProperty(default='', subtype='DIR_PATH') # type: ignore
    regions: bpy.props.CollectionProperty(type=MIMIInteractionRegion) # type: ignore
    region_index: bpy.props.IntProperty(default=0, min=0) # type: ignore

    def init(self, context):
        self.label = self.default_title()
        self.width = 360
        self.use_custom_color = True
        self.color = (0.30, 0.40, 0.45)
        entry = self.regions.add()
        entry.label = tr("Region {number}").format(number=1)
        self.mouse_drag = True

    def width_texts(self):
        return [self.label]

    def draw_buttons(self, context, layout):
        if not interaction_backend.has_backend(GlobalConfig.logic_name):
            layout.label(text=tr("This preset does not provide the interaction deformation"), icon='ERROR')
        layout.prop(self, "enabled", text=tr("Enable Interaction Deformation"))
        layout.label(text=tr("Independent settings; keep the existing output links"), icon='INFO')
        layout.prop(self, "mouse_drag", text=tr("Mouse drag and spring return"))
        if self.mouse_drag:
            layout.prop(self, 'show_debug', text=tr('Show interaction debug information'))
            help_box = layout.box()
            help_box.label(text=tr("1. Choose the body mesh and a region"))
            help_box.label(text=tr("2. Copy an existing group or select vertices"))
            help_box.label(text=tr("3. Export; Alt + left drag, release to bounce"))
            if GlobalConfig.logic_name != 'Naraka':
                help_box.label(text=tr("Mouse drag export currently supports Naraka only"), icon='ERROR')
            layout.prop(self, 'drag_strength', text=tr('Maximum pull'))
            layout.prop(self, 'spring_frequency', text=tr('Bounce speed'))
            layout.prop(self, 'damping_ratio', text=tr('Damping (higher stops sooner)'))

        settings = layout.column()
        settings.enabled = self.enabled

        box = settings.box()
        box.label(text=tr("Interaction Regions (Up to 2)"))
        row = box.row(align=True)
        row.template_list(MIMI_UL_InteractionRegions.bl_idname, "", self, "regions", self, "region_index", rows=2)
        buttons = row.column(align=True)
        add_row = buttons.row(align=True)
        add_row.enabled = len(self.regions) < MAX_INTERACTION_REGIONS
        add = add_row.operator(MIMI_OT_InteractionAddRegion.bl_idname, text="", icon='ADD')
        add.tree_name = self.id_data.name if self.id_data else ""
        add.node_name = self.name
        remove_row = buttons.row(align=True)
        remove_row.enabled = 0 <= self.region_index < len(self.regions)
        remove = remove_row.operator(MIMI_OT_InteractionRemoveRegion.bl_idname, text="", icon='REMOVE')
        remove.tree_name = self.id_data.name if self.id_data else ""
        remove.node_name = self.name

        if 0 <= self.region_index < len(self.regions):
            entry = self.regions[self.region_index]
            detail = box.column()
            detail.enabled = entry.enabled
            detail.prop(entry, "label", text=tr("Region Name"))
            detail.prop_search(entry, "object_name", bpy.data, "objects", text=tr("Region Object"), icon='OBJECT_DATA')
            obj = bpy.data.objects.get(entry.object_name)
            if obj is not None and obj.type == 'MESH':
                detail.prop_search(entry, "vertex_group", obj, "vertex_groups", text=tr("Control Vertex Group"), icon='GROUP_VERTEX')
            else:
                detail.prop(entry, "vertex_group", text=tr("Control Vertex Group"))
                if entry.object_name:
                    detail.label(text=tr("Choose an existing mesh object"), icon='ERROR')
            if obj is not None and obj.type == 'MESH':
                detail.prop_search(entry, 'source_group', obj, 'vertex_groups', text=tr('Existing vertex group'))
                copy_group = detail.operator('mimi.interaction_copy_group', text=tr('Copy weights to this region'), icon='DUPLICATE')
                copy_group.tree_name = self.id_data.name
                copy_group.node_name = self.name
                copy_group.region_index = self.region_index
            if not self.mouse_drag:
                detail.prop(entry, "offset", text=tr("Pull"))
            group = obj.vertex_groups.get(entry.vertex_group) if obj and obj.type == 'MESH' else None
            if group and group.name.startswith(CONTROL_GROUP_PREFIX):
                detail.label(text=tr('Control group ready; check its weight falloff'), icon='CHECKMARK')
            else:
                detail.label(text=tr('Create or copy a control group below'), icon='INFO')
            create_row = detail.row()
            create_row.enabled = getattr(context, 'mode', '') in ('EDIT', 'EDIT_MESH')
            create_region = create_row.operator(
                "mimi.interaction_create_region",
                text=tr("Create Region from Selected Vertices"), icon='GROUP_VERTEX',
            )
            create_region.tree_name = self.id_data.name if self.id_data else ""
            create_region.node_name = self.name
            create_region.region_index = self.region_index
            detail.label(text=tr("Select mesh vertices in Edit Mode first"))
        else:
            box.label(text=tr("Add at least one enabled region before exporting"), icon='INFO')

        if not self.mouse_drag:
            box.label(text=tr("The pull strength is a fraction of the safe distance"))
            box.label(text=tr("A narrow control group can only be pulled a little"))
            box.label(text=tr("Control groups must not use a numbered bone group name"))
            box.label(text=tr("Let the create region button make the control group"))
            box.label(text=tr("A control group name has to start with {prefix}").format(
                prefix=CONTROL_GROUP_PREFIX))
        if self.mouse_drag:
            layout.prop(self, 'capture_directory', text=tr('FrameAnalysis folder (latest if empty)'))
            detect = layout.operator('mimi.interaction_detect_picker', text=tr('Configure picking from capture'), icon='VIEWZOOM')
            detect.tree_name = self.id_data.name
            detect.node_name = self.name
            layout.prop(self, 'show_advanced', text=tr('Picking setup and advanced settings'), icon='TRIA_DOWN' if self.show_advanced else 'TRIA_RIGHT')
            if self.show_advanced:
                layout.label(text=tr('Main-pass shader hashes from FrameAnalysis'))
                layout.prop(self, 'pick_vs', text='VS')
                layout.prop(self, 'pick_ps', text='PS')
                layout.prop(self, 'drag_sensitivity', text=tr('Drag sensitivity'))
                layout.prop(self, 'flip_y', text=tr('Flip cursor Y'))
                layout.prop(self, 'reversed_z', text=tr('Reversed depth'))
            if not self.pick_vs or not self.pick_ps:
                layout.label(text=tr('Picking setup required before export'), icon='ERROR')
            else:
                layout.label(text=tr('Picking shaders configured from capture'), icon='CHECKMARK')


def register():
    """Register the node, its list and its operators."""
    for cls in (MIMIInteractionRegion, MIMI_UL_InteractionRegions, MIMI_OT_InteractionAddRegion,
                MIMI_OT_InteractionRemoveRegion, MIMINode_InteractionDeformation):
        bpy.utils.register_class(cls)


def unregister():
    """Unregister the node, its list and its operators."""
    for cls in (MIMINode_InteractionDeformation, MIMI_OT_InteractionRemoveRegion,
                MIMI_OT_InteractionAddRegion, MIMI_UL_InteractionRegions, MIMIInteractionRegion):
        bpy.utils.unregister_class(cls)
