'''
Time Position Switch blueprint node: wall-clock driven Position.buf switching.

Every input socket stands for one frame (time slice) of a looping timeline,
exactly like the Time Switch node.  The difference is what gets switched:

- Time Switch swaps which object gets drawn (a full mesh swap, one
  drawindexed call per frame inside the shared submesh buffers).
- Time Position Switch keeps one single drawindexed call for the base
  object and only replaces the CONTENT of the Position buffer every frame.
  The frame objects connected here never reach the merged submesh buffers;
  only their Position bytes are exported as side buffer files, and the
  [Present] command list copies the current frame's bytes into the real
  Position resource:

      if $dyntime0 == 0
          ResourceXXXXPosition = copy ResourceXXXXPositionTimeFrame.dyntime0_0
      elif $dyntime0 == 1
          ResourceXXXXPosition = copy ResourceXXXXPositionTimeFrame.dyntime0_1
      endif

  3Dmigoto's "dst = copy src" reuses the cached destination buffer when it
  is compatible (CommandList.cpp ResourceCopyOperation::run ->
  RecreateCompatibleResource), so per-frame copies cost one GPU
  CopyResource call instead of a new allocation.

Rules (enforced at export time with clear error messages):
- The base object of the animated submesh must be connected to the output
  normally (an Object Info node outside this node); the frames replace its
  position data, everything else (IB, Texcoord, Blend, ...) stays shared.
- Every frame must retain exported indices, vertex ordering and all shared
  non-Position attributes. Baking topology-changing modifiers or separate
  normal/UV animation requires DrawIndexed switching instead.
- One draw call per animated submesh (the base object), because a frame
  replaces the whole submesh position range.
- One shared timeline and common outer gate per DrawIB are required.
- WWMI, NTEMI, EFMI and unsupported GPU pre-skinning paths are rejected.
  Naraka/NarakaM/AILIMIT/ZZMIDX12 shared Position skinning paths are allowed.
- Shape keys use a separate animated seed; the shape reference stays fixed.
  Empty frames and disabled gates restore the original Position buffer.
- An optional playback key restores the base while off. Re-enabling starts
  at frame zero; leaving the key blank preserves the original autoplay mode.

The frame-rate independence relies on the same 3Dmigoto facts as the Time
Switch node (wall-clock "time" operand, exact "//" floor division, plain
"global" variables), see blueprint_node_time_switch.py for the references.
'''
import bpy

from ..i18n.i18n import tr, translatable
from .blueprint_node_base import MIMINodeBase


@translatable
class MIMINode_TimePosSwitch(MIMINodeBase):
    '''Time Position Switch: the Position buffer content cycles through the connected frames on a wall-clock timeline'''
    bl_idname = 'MIMINode_TimePosSwitch'
    bl_label = 'Time Position Switch'
    bl_icon = 'TIME'

    def update_fps(self, context):
        self.update_node_width([self.time_alias, self.comment])

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
        self.update_node_width([self.time_alias, self.comment])

    def update_comment(self, context):
        self.update_node_width([self.time_alias, self.comment])

    fps: bpy.props.FloatProperty(
        name=tr("FPS"),
        description=tr("Frames shown per second of wall-clock time; playback speed never depends on the game's frame rate"),
        default=12.0,
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
    # Use the same control contract as draw and shape timelines.
    # Defaults keep existing node trees playing without keyboard setup.
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
        self.label = tr("Time Position Switch")
        self.inputs.new('MIMISocketObject', "Frame 0")
        self.outputs.new('MIMISocketObject', "Output")
        self.width = 200
        self.use_custom_color = True
        self.color = (0.52, 0.40, 0.60)

    def draw_buttons(self, context, layout):
        layout.prop(self, "fps", text=tr("FPS"))
        layout.prop(self, "time_alias", text=tr("Time Variable Alias"))
        layout.prop(self, "comment", text=tr("Comment"))
        # Expose the off behavior beside the key so it is not confused with
        # hiding the model or freezing its last deformed frame.
        layout.prop(self, "toggle_key", text=tr("Animation Toggle Key"))
        controls = layout.column()
        controls.enabled = bool(self.toggle_key.strip())
        controls.prop(self, "start_enabled", text=tr("Start Enabled"))
        if self.toggle_key.strip():
            layout.label(text=tr("When off: restore base Position"), icon='INFO')

        # The socket add/remove operators of the Time Switch node are generic
        # (they only append/remove "Frame N" input sockets by node name), so
        # this node reuses them instead of duplicating the code.
        row = layout.row(align=True)
        op_add = row.operator("mimi.time_switch_add_socket", text=tr("Add"), icon='ADD')
        op_add.node_name = self.name

        op_rem = row.operator("mimi.time_switch_remove_socket", text=tr("Remove"), icon='REMOVE')
        op_rem.node_name = self.name

        layout.separator()
        # Same baker as the Time Switch node: baked frames have identical
        # topology, which this node strictly requires.
        op_bake = layout.operator(
            "mimi.bake_animation_to_time_switch",
            text=tr("Bake Animation to Frames"),
            icon='ARMATURE_DATA',
        )
        op_bake.node_name = self.name
        tree = self.id_data if getattr(self, "id_data", None) else None
        op_bake.tree_name = tree.name if tree else ""

        # Short inline reminder of the base-object rule, so users do not
        # have to read the documentation before the first export.
        layout.label(text=tr("The base object must also be connected normally"), icon='INFO')


classes = (
    MIMINode_TimePosSwitch,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
