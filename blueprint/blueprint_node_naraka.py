'''
Naraka-only blueprint nodes.

Currently this module holds the cross-IB render configuration node:
a standalone node (no sockets, no connections required) that stores
source -> target object pairs. At mod generation time every pair is
resolved by BluePrintModel:

- Source object (guest): its drawindexed lines are removed from its own
  Submesh section and re-emitted inside the target's section instead.
  Each drawindexed keeps the switch conditions it earned from its wiring.
- Target object (host): its Submesh section receives the cross-IB block
  (guest IB + guest VB backups switched in) after its own drawindexed.
- The guest Submesh section also captures its DrawIB's VB bindings into
  backup resources (ref vb0 / ref vb1) so the host side can rebind them.

The generated resource names carry the Submesh identity and the slot,
e.g. Resource_LOD0_fd1dede6_0_BK_VB0, so any number of pairs never collide.
'''
import bpy
from bpy.types import PropertyGroup, UIList

from ..common.global_config import GlobalConfig
from ..common.global_config import LogicName
from ..i18n.i18n import I18nOperator, tr, translatable
from .blueprint_node_base import MIMINodeBase


class MIMICrossIBPairItem(PropertyGroup):
    '''One cross-IB pair: the source object's draws are rendered during the target object's draw call'''
    # Both names are plain object names, picked from bpy.data.objects.
    source_object: bpy.props.StringProperty(name=tr("Source Object"), default="") # type: ignore
    target_object: bpy.props.StringProperty(name=tr("Target Object"), default="") # type: ignore


class MIMI_UL_CrossIBPairList(UIList):
    '''UIList drawing one cross-IB pair row: source object -> target object'''
    # Explicit idname following the Blender "_UL_" convention.
    bl_idname = "MIMI_UL_CrossIBPairList"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)
            # Guest side: the object whose draws will move into the target's draw call.
            row.prop_search(item, "source_object", bpy.data, "objects", text="", icon='OBJECT_DATA')
            # Arrow icon only; a text arrow risks garbled characters on some systems.
            row.label(text="", icon='FORWARD')
            # Host side: the object whose draw call will render the guest.
            row.prop_search(item, "target_object", bpy.data, "objects", text="", icon='OBJECT_DATA')
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text="", icon='LINKED')


class SSMT_OT_CrossIBPairAdd(I18nOperator):
    '''Add a new cross-IB pair to the node'''
    bl_idname = "mimi.cross_ib_pair_add"
    bl_label = "Add Pair"
    bl_options = {'REGISTER', 'UNDO'}

    node_name: bpy.props.StringProperty() # type: ignore
    tree_name: bpy.props.StringProperty() # type: ignore

    def execute(self, context):
        node = _find_cross_ib_node(context, self.tree_name, self.node_name)
        if node is None:
            return {'CANCELLED'}
        pair = node.pairs.add()
        # Make the new row active so the user can edit it right away.
        node.active_pair_index = len(node.pairs) - 1
        pair.source_object = ""
        pair.target_object = ""
        return {'FINISHED'}


class SSMT_OT_CrossIBPairRemove(I18nOperator):
    '''Remove the active cross-IB pair from the node'''
    bl_idname = "mimi.cross_ib_pair_remove"
    bl_label = "Remove Pair"
    bl_options = {'REGISTER', 'UNDO'}

    node_name: bpy.props.StringProperty() # type: ignore
    tree_name: bpy.props.StringProperty() # type: ignore

    def execute(self, context):
        node = _find_cross_ib_node(context, self.tree_name, self.node_name)
        if node is None:
            return {'CANCELLED'}
        index = node.active_pair_index
        if index < 0 or index >= len(node.pairs):
            return {'CANCELLED'}
        node.pairs.remove(index)
        # Keep the active index inside the valid range after removal.
        node.active_pair_index = min(index, len(node.pairs) - 1)
        return {'FINISHED'}


def _find_cross_ib_node(context, tree_name: str, node_name: str):
    '''Resolve the target node from the current editor tree, with a name fallback.'''
    tree = getattr(context.space_data, "edit_tree", None) or getattr(context.space_data, "node_tree", None)
    if not tree and tree_name:
        tree = bpy.data.node_groups.get(tree_name)
    if not tree:
        return None
    return tree.nodes.get(node_name)


@translatable
class MIMINode_NarakaCrossIBRender(MIMINodeBase):
    '''Cross-IB render pairs for the Naraka preset (standalone config node, no connections needed)'''
    bl_idname = 'MIMINode_NarakaCrossIBRender'
    bl_label = 'Naraka Cross-IB Render'
    bl_icon = 'LINKED'

    # The pair list is the whole state of this node; it is scanned globally
    # at Generate Mod time, so the node never needs to be linked anywhere.
    pairs: bpy.props.CollectionProperty(type=MIMICrossIBPairItem) # type: ignore
    active_pair_index: bpy.props.IntProperty(default=0) # type: ignore

    def init(self, context):
        # The default title is instance data, so bake in the active language.
        self.label = tr("Naraka Cross-IB Render")
        self.width = 420
        self.use_custom_color = True
        self.color = (0.54, 0.34, 0.54)

    def draw_buttons(self, context, layout):
        if GlobalConfig.logic_name != LogicName.Naraka:
            layout.label(text=tr("This node only works under the Naraka game preset"), icon='ERROR')

        layout.label(text=tr("Each row: source object's draws are rendered in the target object's draw call"), icon='INFO')

        # Pair list with add/remove buttons next to it.
        row = layout.row(align=True)
        row.template_list(
            MIMI_UL_CrossIBPairList.bl_idname, "",
            self, "pairs",
            self, "active_pair_index",
            rows=4,
        )
        col = row.column(align=True)
        op_add = col.operator(SSMT_OT_CrossIBPairAdd.bl_idname, text="", icon='ADD')
        op_add.node_name = self.name
        op_add.tree_name = self.id_data.name if self.id_data else ""
        op_remove = col.operator(SSMT_OT_CrossIBPairRemove.bl_idname, text="", icon='REMOVE')
        op_remove.node_name = self.name
        op_remove.tree_name = self.id_data.name if self.id_data else ""


classes = (
    MIMICrossIBPairItem,
    MIMI_UL_CrossIBPairList,
    SSMT_OT_CrossIBPairAdd,
    SSMT_OT_CrossIBPairRemove,
    MIMINode_NarakaCrossIBRender,
)


def register():
    # MIMICrossIBPairItem must register first: the node's CollectionProperty
    # references its type at registration time.
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
