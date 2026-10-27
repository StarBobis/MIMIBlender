"""Independent pass-through channels for the two connected texture nodes.

A Slot Texture Bind or Hash Texture Bind node used to expose exactly one Object
input and one Object output. A blueprint that applies the same replacement to
several parts therefore needed one node per part: the rows had to be typed once
per copy, and every later edit (a new image, a different mark, a colour-space
fix) had to be repeated in every copy as well.

Both nodes are transparent pass-throughs: the export parses the objects
upstream of the node first and then tags the draw calls it just produced with
the node's rows. Extending the node to N socket pairs therefore needs one new
rule only - output N belongs to input N, which is exactly how
``BluePrintModel._parse_custom_group`` already picks the connected output of a
custom group. This module owns that rule, the +- buttons that create the socket
pairs and the operators behind those buttons.

Existing files keep working unchanged: a node saved with one pair still has one
channel, its rows still apply to every object that flows through it, and its
socket names are only renumbered once a second channel is added.
"""
import bpy

from ..i18n.i18n import I18nOperator, tr

# The two connected texture nodes that support channels. The socketless global
# nodes have no object flow, so channels make no sense there.
BIND_NODE_IDNAMES = (
    'MIMINode_Texture_Bind',
    'MIMINode_Hash_Texture_Bind',
)

# Upper bound of channel pairs. A texture node with more inputs than this is a
# modelling mistake, and unlimited growth would make the node unusable.
MAX_CHANNELS = 16


def is_channel_bind_node(node):
    """Return True for the texture nodes this module can extend."""
    return str(getattr(node, "bl_idname", "") or "") in BIND_NODE_IDNAMES


def channel_count(node):
    """Return the number of usable channel pairs of one node."""
    return min(len(getattr(node, "inputs", []) or []),
               len(getattr(node, "outputs", []) or []))


def channel_inputs(node, from_socket=None):
    """Return the input sockets the export has to follow for one visit.

    ``from_socket`` is the output the downstream wire starts at, which is how
    the export reaches this node. Channel N is input N plus output N, so only
    that input belongs to this visit. A node with a single pair (every file
    saved before channels existed) and an inconsistent node keep the historical
    behaviour of following every input.
    """
    inputs = list(getattr(node, "inputs", []) or [])
    outputs = list(getattr(node, "outputs", []) or [])
    if from_socket is None or len(inputs) <= 1 or len(inputs) != len(outputs):
        # No pairing decision is possible or needed here.
        return inputs
    try:
        index = outputs.index(from_socket)
    except ValueError:
        # A stale socket pointer: following every input is safer than none.
        return inputs
    return [inputs[index]]


def channel_socket_names(channel_index):
    """Return the input/output names of one 1-based channel number."""
    number = str(int(channel_index))
    return "Object " + number, "Output " + number


def sync_channel_sockets(node):
    """Make both socket lists equally long and number a multi-channel node.

    A single-pair node keeps the historical "Object"/"Output" names so saved
    files look unchanged. From the second channel on every pair is numbered,
    because the wiring only makes sense when the pairing is visible.
    """
    while len(node.outputs) < len(node.inputs):
        node.outputs.new('MIMISocketObject', "Output")
    while len(node.inputs) < len(node.outputs):
        node.inputs.new('MIMISocketObject', "Object")
    if len(node.inputs) <= 1:
        return
    for index in range(len(node.inputs)):
        input_name, output_name = channel_socket_names(index + 1)
        # Renaming a socket keeps its links; only the caption changes.
        if node.inputs[index].name != input_name:
            node.inputs[index].name = input_name
        if node.outputs[index].name != output_name:
            node.outputs[index].name = output_name


def add_channel(node):
    """Append one more channel pair; returns False at the channel limit."""
    if not is_channel_bind_node(node):
        return False
    if len(node.inputs) >= MAX_CHANNELS:
        return False
    node.inputs.new('MIMISocketObject', "Object")
    node.outputs.new('MIMISocketObject', "Output")
    sync_channel_sockets(node)
    return True


def remove_channel(node):
    """Remove the last channel pair.

    Returns ``(removed, reason)``. The last remaining pair is never removed
    (a node without sockets would silently drop out of the object flow), and a
    wired pair is refused instead of quietly deleting the user's links.
    """
    if not is_channel_bind_node(node):
        return False, "unsupported"
    if len(node.inputs) <= 1 or len(node.outputs) <= 1:
        return False, "last"
    last_input = node.inputs[-1]
    last_output = node.outputs[-1]
    if last_input.is_linked or last_output.is_linked:
        return False, "linked"
    node.inputs.remove(last_input)
    node.outputs.remove(last_output)
    sync_channel_sockets(node)
    return True, ""


def draw_channel_controls(layout, node, tree):
    """Draw the channel count with its add/remove buttons."""
    row = layout.row(align=True)
    row.label(text=tr("Channels: {count}").format(count=channel_count(node)), icon='NODETREE')
    tree_name = getattr(tree, "name", "") if tree else ""
    add = row.operator("mimi.texture_bind_add_channel", text="", icon='ADD')
    add.node_name = node.name
    add.tree_name = tree_name
    remove = row.operator("mimi.texture_bind_remove_channel", text="", icon='REMOVE')
    remove.node_name = node.name
    remove.tree_name = tree_name
    if len(node.inputs) != len(node.outputs):
        # Only a hand-edited or older graph can reach this state; one add
        # repairs it because the operators always create a complete pair.
        layout.label(text=tr("Channel inputs and outputs are out of sync; add one channel to repair it"), icon='ERROR')
    elif channel_count(node) > 1:
        # The rows are the point of the feature, so name the sharing explicitly.
        layout.label(text=tr("Every channel shares the same rows: channel N passes input N to output N"), icon='INFO')


def _resolve_node(operator, context):
    """Resolve the node an operator was invoked from, never another tree."""
    tree = bpy.data.node_groups.get(operator.tree_name) if operator.tree_name else None
    if tree is None and not operator.tree_name:
        tree = getattr(context.space_data, "edit_tree", None) or getattr(context.space_data, "node_tree", None)
    if tree is None:
        return None, None
    return tree, tree.nodes.get(operator.node_name)


class MIMI_OT_TextureBindAddChannel(I18nOperator):
    """Add one pass-through channel to a connected texture node."""
    bl_idname = "mimi.texture_bind_add_channel"
    bl_label = "Add Channel"
    bl_description = "Add another pass-through channel; channel N pairs input N with output N and shares this node's rows"
    bl_options = {'REGISTER', 'UNDO'}

    node_name: bpy.props.StringProperty() # type: ignore
    tree_name: bpy.props.StringProperty() # type: ignore

    def execute(self, context):
        tree, node = _resolve_node(self, context)
        if node is None or not is_channel_bind_node(node):
            self.report({'ERROR'}, tr("Texture node was not found"))
            return {'CANCELLED'}
        if not add_channel(node):
            self.report({'WARNING'}, tr("This node already has the maximum of {count} channels").format(count=MAX_CHANNELS))
            return {'CANCELLED'}
        self.report({'INFO'}, tr("Added channel {count}").format(count=channel_count(node)))
        return {'FINISHED'}


class MIMI_OT_TextureBindRemoveChannel(I18nOperator):
    """Remove the last channel pair of a connected texture node."""
    bl_idname = "mimi.texture_bind_remove_channel"
    bl_label = "Remove Channel"
    bl_description = "Remove the last channel; disconnect its wires first and keep at least one channel"
    bl_options = {'REGISTER', 'UNDO'}

    node_name: bpy.props.StringProperty() # type: ignore
    tree_name: bpy.props.StringProperty() # type: ignore

    def execute(self, context):
        tree, node = _resolve_node(self, context)
        if node is None or not is_channel_bind_node(node):
            self.report({'ERROR'}, tr("Texture node was not found"))
            return {'CANCELLED'}
        removed, reason = remove_channel(node)
        if not removed:
            if reason == "linked":
                self.report({'WARNING'}, tr("The last channel is still connected; disconnect its wires first"))
            else:
                self.report({'WARNING'}, tr("At least one channel has to stay"))
            return {'CANCELLED'}
        self.report({'INFO'}, tr("Removed the last channel"))
        return {'FINISHED'}


classes = (
    MIMI_OT_TextureBindAddChannel,
    MIMI_OT_TextureBindRemoveChannel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
