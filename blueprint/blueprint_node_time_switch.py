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

from ..common.global_config import GlobalConfig, LogicName
from ..i18n.i18n import I18nOperator, tr, translatable
from .blueprint_node_base import MIMINodeBase


def time_switch_owner_key(time_node):
    """Return the graph-provenance key of one DrawIndex timeline node.

    The key is stable for the whole export run and does not depend on object
    names, so re-baking a timeline (which creates new frame objects) keeps
    working.  Re-instancing the same group tree on purpose shares the key,
    exactly like the shared clock, because it is the same node.
    """
    tree = getattr(time_node, "id_data", None)
    tree_name = str(getattr(tree, "name", "") or "")
    node_name = str(getattr(time_node, "name", "") or "")
    return tree_name + "::" + node_name


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
        host_object = getattr(self, "cross_ib_host_object", None)
        host_name = str(getattr(host_object, "name", "") or "")
        return [self.label, self.time_alias, self.comment, host_name]

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

    def update_playback_mode(self, context):
        self.update_node_width(self.width_texts())

    def update_cross_ib_host(self, context):
        # The host name is drawn on the node, so the width has to follow it.
        self.update_node_width(self.width_texts())

    # Playback driver dropdown. LOOP keeps the legacy autoplay behavior;
    # TRIGGER turns the key into a one-shot trigger (every press replays
    # the timeline once from frame 0, then it rests until the next press).
    playback_mode: bpy.props.EnumProperty(
        name=tr("Playback Mode"),
        description=tr("Loop: repeat the timeline forever. Key Trigger: each key press plays the timeline once from frame 0"),
        items=[
            ("LOOP", tr("Loop"), tr("Repeat the timeline forever; the key (if set) toggles playback on/off")),
            ("TRIGGER", tr("Key Trigger (Play Once)"), tr("Each key press plays the timeline once from frame 0; pressing again restarts it")),
        ],
        default="LOOP",
        update=update_playback_mode,
    ) # type: ignore
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

    # Naraka-only batch: every frame of this timeline is drawn inside one host
    # object's draw call, so the frames use the host's material and textures.
    # The properties exist under every preset to keep blend data intact when a
    # file is opened elsewhere; only the Naraka UI and post-processor use them.
    cross_ib_enabled: bpy.props.BoolProperty(
        name=tr("Enable Cross-IB"),
        description=tr("Render this timeline's frames inside the host object's draw call so they use the host's material and textures"),
        default=False,
    ) # type: ignore
    cross_ib_host_object: bpy.props.PointerProperty(
        type=bpy.types.Object,
        name=tr("Host Object"),
        description=tr("Object whose draw call and material the timeline frames should use; it must be part of the exported blueprint and map to exactly one Submesh"),
        update=update_cross_ib_host,
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
        layout.prop(self, "playback_mode", text=tr("Playback Mode"))
        layout.prop(self, "fps", text=tr("FPS"))
        layout.prop(self, "time_alias", text=tr("Time Variable Alias"))
        layout.prop(self, "comment", text=tr("Comment"))
        # In trigger mode the key IS the playback trigger, so the initial
        # on/off state is meaningless and its widget stays disabled.
        is_trigger = self.playback_mode == "TRIGGER"
        # Disable the default-state widget when no runtime switch is generated.
        layout.prop(self, "toggle_key", text=tr("Trigger Key") if is_trigger else tr("Animation Toggle Key"))
        controls = layout.column()
        controls.enabled = bool(self.toggle_key.strip()) and not is_trigger
        controls.prop(self, "start_enabled", text=tr("Start Enabled"))
        if self.toggle_key.strip():
            if is_trigger:
                layout.label(text=tr("Press: play once from frame 0"), icon='INFO')
            else:
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

        # Naraka only: one host object for the whole timeline.  This replaces
        # the old workflow of adding one Cross-IB pair per frame object, which
        # became unmaintainable for baked animations with dozens of frames.
        if GlobalConfig.logic_name == LogicName.Naraka:
            layout.separator()
            box = layout.box()
            box.label(text=tr("Naraka Cross-IB"), icon='LINKED')
            box.prop(self, "cross_ib_enabled", text=tr("Cross-IB Render"))
            host_column = box.column()
            host_column.enabled = self.cross_ib_enabled
            host_column.prop(self, "cross_ib_host_object", text=tr("Host Object"))
            if not self.cross_ib_enabled:
                box.label(text=tr("Render every frame at one host object's draw call"), icon='INFO')
            elif self.cross_ib_host_object is None:
                box.label(text=tr("Choose the host object whose material the frames should use"), icon='ERROR')
            elif getattr(self.cross_ib_host_object, "type", "") != 'MESH':
                box.label(text=tr("The host object must be a mesh object"), icon='ERROR')
            else:
                connected_count = len([socket for socket in self.inputs if socket.is_linked])
                box.label(text=tr("{count} connected frame(s) follow this host").format(count=connected_count), icon='INFO')


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
