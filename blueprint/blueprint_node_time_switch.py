'''
Time Switch blueprint node (shown in the UI as "DrawIndex Based Dynamic Mod").

A wall-clock driven variant of the Switch Key node.

Every input socket of the node stands for one frame (time slice) of a looping
timeline. While Switch Key cycles a variable through a [Key] hotkey section,
this node lets the [Present] command list recompute the variable every frame
from 3Dmigoto's built-in "time" operand, so playback speed only depends on
real time and never on the game's frame rate. An optional toggle key switches
playback on/off: off selects frame zero, and re-enabling starts a fresh loop.

3Dmigoto source facts backing this design (bo3b/3Dmigoto, DirectX11):
- "time" keyword -> ParamOverrideType::TIME (CommandList.h), evaluated as
  (GetTickCount() - ticks_at_launch) / 1000.0f seconds (CommandList.cpp,
  CommandListOperand::evaluate).
- "//" is floor division and "%" is fmod. Operators evaluate float32;
  M_Key.timeline_expression bounds the final floored result with modulo
  so rounding at the cycle boundary never produces an unhandled frame.
- [Present] is a command list run once per frame at DXGI::Present
  (HackerDXGI.cpp, RunFrameActions).
- VariableAssignment::run marks persisted variables dirty on changes;
  SavePersistentSettings writes them later, not on every assignment.
  Animation clocks are transient state and should remain plain globals.
'''
import bpy

from ..i18n.i18n import I18nOperator, tr, translatable
from .blueprint_node_base import MIMINodeBase


class MMT_OT_TimeSwitch_AddSocket(I18nOperator):
    '''Add a new frame socket to the time switch node'''
    bl_idname = "mimi.time_switch_add_socket"
    bl_label = "Add Socket"
    bl_options = {'REGISTER', 'UNDO'}

    node_name: bpy.props.StringProperty() # type: ignore

    def execute(self, context):
        tree = getattr(context.space_data, "edit_tree", None) or getattr(context.space_data, "node_tree", None)
        if not tree:
            return {'CANCELLED'}
        node = tree.nodes.get(self.node_name)
        if node:
            node.inputs.new('MIMISocketObject', "Frame {count}".format(count=len(node.inputs)))
        return {'FINISHED'}


class MMT_OT_TimeSwitch_RemoveSocket(I18nOperator):
    '''Remove the last frame socket from the time switch node'''
    bl_idname = "mimi.time_switch_remove_socket"
    bl_label = "Remove Socket"
    bl_options = {'REGISTER', 'UNDO'}

    node_name: bpy.props.StringProperty() # type: ignore

    def execute(self, context):
        tree = getattr(context.space_data, "edit_tree", None) or getattr(context.space_data, "node_tree", None)
        if not tree:
            return {'CANCELLED'}
        node = tree.nodes.get(self.node_name)
        if node and len(node.inputs) > 0:
            node.inputs.remove(node.inputs[-1])
        return {'FINISHED'}


def renumber_time_switch_sockets(node):
    '''Rename every frame socket to match its index (frame order is the socket order).'''
    for index, socket in enumerate(node.inputs):
        expected_name = "Frame {count}".format(count=index)
        if socket.name != expected_name:
            socket.name = expected_name


@translatable
class MIMINode_TimeSwitch(MIMINodeBase):
    '''Time Switch assigns each connected branch to one frame of a looping wall-clock timeline'''
    bl_idname = 'MIMINode_TimeSwitch'
    # The title tells the user which part of the mesh data is switched: this
    # node switches whole DrawIndexed calls, one per connected frame.
    bl_label = 'DrawIndex Based Dynamic Mod'
    bl_icon = 'TIME'

    def width_texts(self):
        """Return every text that decides how wide this node has to be."""
        # The title is the longest text here, so an old default title must not
        # shrink the node back to a width that truncates the new name.
        return [self.label, self.time_alias, self.comment]

    def update_fps(self, context):
        self.update_node_width(self.width_texts())

    def update_time_alias(self, context):
        # Match the 3Dmigoto identifier alphabet; export separately checks
        # the leading character and reserved internal variable names.
        sanitized_alias = "".join(
            char for char in str(self.time_alias or "")
            if char.isascii() and (char.isalnum() or char == "_")
        )
        if self.time_alias != sanitized_alias:
            self.time_alias = sanitized_alias
            return
        self.update_node_width(self.width_texts())

    def update_comment(self, context):
        self.update_node_width(self.width_texts())

    fps: bpy.props.FloatProperty(
        name=tr("FPS"),
        description=tr("Frames shown per second of wall-clock time; playback speed never depends on the game's frame rate"),
        default=60.0,
        min=0.01,
        soft_max=120.0,
        update=update_fps,
    ) # type: ignore
    time_alias: bpy.props.StringProperty(
        name=tr("Time Variable Alias"),
        description=tr("Start with an ASCII letter or underscore; use letters, digits or underscores. Aliases are case-insensitive and share one timeline."),
        default="",
        update=update_time_alias,
    ) # type: ignore
    # Optional runtime control; an empty key preserves legacy autoplay.
    # Keeping these as native RNA properties also stores them in blend files.
    toggle_key: bpy.props.StringProperty(
        name=tr("Animation Toggle Key"),
        description=tr("Optional key, such as F6 or CTRL F6. Leave blank for autoplay. Enabling restarts at frame 0."),
        default="",
    ) # type: ignore
    start_enabled: bpy.props.BoolProperty(
        name=tr("Start Enabled"),
        description=tr("Initial animation state on load or reload; only used when a toggle key is set."),
        default=True,
    ) # type: ignore
    comment: bpy.props.StringProperty(
        name=tr("Comment"),
        description=tr("Comment text; written into the config table as comments"),
        default="",
        update=update_comment,
    ) # type: ignore

    def init(self, context):
        # The default title is instance data, so bake in the active language.
        self.label = self.default_title()
        self.inputs.new('MIMISocketObject', "Frame 0")
        self.outputs.new('MIMISocketObject', "Output")
        # Size the node from its texts, so the full title stays readable.
        self.update_node_width(self.width_texts())
        self.use_custom_color = True
        self.color = (0.40, 0.44, 0.60)

    def draw_buttons(self, context, layout):
        layout.prop(self, "fps", text=tr("FPS"))
        layout.prop(self, "time_alias", text=tr("Time Variable Alias"))
        layout.prop(self, "comment", text=tr("Comment"))
        # Disable the default-state widget when no runtime switch is generated.
        layout.prop(self, "toggle_key", text=tr("Animation Toggle Key"))
        controls = layout.column()
        controls.enabled = bool(self.toggle_key.strip())
        controls.prop(self, "start_enabled", text=tr("Start Enabled"))
        if self.toggle_key.strip():
            layout.label(text=tr("When off: show frame 0"), icon='INFO')

        row = layout.row(align=True)
        op_add = row.operator("mimi.time_switch_add_socket", text=tr("Add"), icon='ADD')
        op_add.node_name = self.name

        op_rem = row.operator("mimi.time_switch_remove_socket", text=tr("Remove"), icon='REMOVE')
        op_rem.node_name = self.name

        layout.separator()
        # One-click baking: sample an animated object into per-frame objects
        # and wire them into this node's frame sockets in order.
        op_bake = layout.operator(
            "mimi.bake_animation_to_time_switch",
            text=tr("Bake Animation to Frames"),
            icon='ARMATURE_DATA',
        )
        op_bake.node_name = self.name
        tree = self.id_data if getattr(self, "id_data", None) else None
        op_bake.tree_name = tree.name if tree else ""


classes = (
    MIMINode_TimeSwitch,
    MMT_OT_TimeSwitch_AddSocket,
    MMT_OT_TimeSwitch_RemoveSocket,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
