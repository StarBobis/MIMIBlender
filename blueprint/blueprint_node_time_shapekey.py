'''
Time Shape Key blueprint node (shown in the UI as
"ShapeKey Real-time Based Dynamic Mod").

Wall-clock driven shape key weight animation.

The classic shape key workflow of this addon cycles a weight variable through
a [Key] hotkey section.  This node instead animates the weight automatically
on a wall-clock timeline: the user provides one weight per frame (either by
hand or by baking the shape key's animated value from the Blender timeline),
and the exporter writes a small [Present] block that maps the current frame
index to the weight variable every frame:

    [Constants]
    global $shapekey1 = 0

    [Present]
    local $shapekey1_frame
    $shapekey1_frame = ((time % (0.08333333333333333 * 24)) // 0.08333333333333333) % 24
    if $shapekey1_frame == 0
        $shapekey1 = 0.0
    elif $shapekey1_frame == 1
        $shapekey1 = 0.04
    endif

The weight variable is consumed by the existing shape key compute shaders
("x88 = $shapekey1"), so the buffer pipeline needs no changes at all.

The frame-rate independence relies on the same 3Dmigoto facts as the Time
Switch node (wall-clock "time" operand, exact "//" floor division, plain
"global" variables), see blueprint_node_time_switch.py for the references.

Note: the "Generate Shape Key Mod" option of the output node must still be
enabled, because the shape key buffers are only exported then; this node
only replaces the hotkey driver with the time driver.
'''
import bpy

from ..i18n.i18n import I18nOperator, tr, translatable
from ..blueprint.blueprint_time_range import (
    detect_animated_frame_range,
    trailing_static_frame_info,
)
from .blueprint_node_base import MIMINodeBase


class MIMINodeTimeShapeKeyWeightItem(bpy.types.PropertyGroup):
    '''One frame of a Time Shape Key timeline: the weight while this frame is active.'''
    weight: bpy.props.FloatProperty(
        name=tr("Weight"),
        description=tr("Shape key weight while this frame is active (0 means Basis, 1 means full shape key)"),
        default=0.0,
        soft_min=0.0,
        soft_max=1.0,
    ) # type: ignore


class MMT_OT_TimeShapeKey_AddWeight(I18nOperator):
    '''Append one frame to the weight timeline of the time shape key node'''
    bl_idname = "mimi.time_shapekey_add_weight"
    bl_label = "Add Weight Frame"
    bl_options = {'REGISTER', 'UNDO'}

    node_name: bpy.props.StringProperty() # type: ignore

    def execute(self, context):
        tree = getattr(context.space_data, "edit_tree", None) or getattr(context.space_data, "node_tree", None)
        if not tree:
            return {'CANCELLED'}
        node = tree.nodes.get(self.node_name)
        if node:
            node.weights.add()
        return {'FINISHED'}


class MMT_OT_TimeShapeKey_RemoveWeight(I18nOperator):
    '''Remove the last frame from the weight timeline of the time shape key node'''
    bl_idname = "mimi.time_shapekey_remove_weight"
    bl_label = "Remove Weight Frame"
    bl_options = {'REGISTER', 'UNDO'}

    node_name: bpy.props.StringProperty() # type: ignore

    def execute(self, context):
        tree = getattr(context.space_data, "edit_tree", None) or getattr(context.space_data, "node_tree", None)
        if not tree:
            return {'CANCELLED'}
        node = tree.nodes.get(self.node_name)
        if node and len(node.weights) > 0:
            node.weights.remove(len(node.weights) - 1)
        return {'FINISHED'}


class MMT_OT_TimeShapeKey_BakeWeights(I18nOperator):
    '''Sample the animated shape key value of a source object at every chosen frame into the node's weight timeline'''
    bl_idname = "mimi.time_shapekey_bake_weights"
    bl_label = "Bake Shape Key Weights"
    bl_options = {'REGISTER', 'UNDO'}

    # Target node identity (filled in by the node's button).
    node_name: bpy.props.StringProperty() # type: ignore
    tree_name: bpy.props.StringProperty() # type: ignore

    source_object: bpy.props.StringProperty(
        name=tr("Source Object"),
        description=tr("Mesh object whose animated shape key value is sampled"),
        default="",
    ) # type: ignore

    frame_start: bpy.props.IntProperty(
        name=tr("Start Frame"),
        default=1,
    ) # type: ignore
    frame_end: bpy.props.IntProperty(
        name=tr("End Frame"),
        description=tr("Last sampled frame (inclusive). Frames past the last keyframe repeat its weight and look like a pause in each loop"),
        default=24,
    ) # type: ignore
    frame_step: bpy.props.IntProperty(
        name=tr("Frame Step"),
        description=tr("Sample one frame every N frames; larger steps produce fewer frames"),
        default=1,
        min=1,
    ) # type: ignore

    match_scene_fps: bpy.props.BoolProperty(
        name=tr("Set Node FPS to 60"),
        description=tr("Set the node's FPS to 60 after baking"),
        default=True,
    ) # type: ignore

    def _get_tree_and_node(self):
        tree = bpy.data.node_groups.get(self.tree_name) if self.tree_name else None
        if tree is None or getattr(tree, "bl_idname", "") != 'MIMIBlueprintTreeType':
            return None, None
        node = tree.nodes.get(self.node_name) if self.node_name else None
        if node is None or getattr(node, "bl_idname", "") != 'MIMINode_TimeShapeKey':
            return tree, None
        return tree, node

    def invoke(self, context, event):
        tree, node = self._get_tree_and_node()
        if node is None:
            self.report({'WARNING'}, tr("Please run this from a ShapeKey Real-time Based Dynamic Mod node"))
            return {'CANCELLED'}

        scene = context.scene

        # Prefill the source object with the currently active mesh object.
        active_obj = getattr(context, "active_object", None)
        if active_obj is not None and active_obj.type == 'MESH':
            self.source_object = active_obj.name

        # Prefill the sampled range with the keyed range of the shape key
        # action instead of the scene range. Scene ranges usually contain
        # padding past the last keyframe, and sampling that padding makes
        # the weight freeze for a while at the end of every loop.
        source_obj = bpy.data.objects.get(self.source_object)
        keyed_range = detect_animated_frame_range(source_obj)
        if keyed_range is not None:
            self.frame_start, self.frame_end = keyed_range
        else:
            self.frame_start = scene.frame_start
            self.frame_end = scene.frame_end

        return context.window_manager.invoke_props_dialog(self, width=420)

    def draw(self, context):
        layout = self.layout
        layout.prop_search(self, "source_object", bpy.data, "objects", text=tr("Source Object"), icon='OBJECT_DATA')

        row = layout.row(align=True)
        row.prop(self, "frame_start")
        row.prop(self, "frame_end")
        row.prop(self, "frame_step")
        layout.prop(self, "match_scene_fps")

        frame_count = len(self._frame_numbers())
        if frame_count > 0:
            layout.label(text=tr("Will bake {count} frames").format(count=frame_count), icon='INFO')

    def _frame_numbers(self):
        if self.frame_step < 1 or self.frame_end < self.frame_start:
            return []
        # Count samples lazily so an accidental huge range cannot allocate
        # millions of entries before the 1000-frame validation runs.
        return range(self.frame_start, self.frame_end + 1, self.frame_step)

    def _find_shape_key_block(self, source_obj, shapekey_name):
        """Return the shape key block of the source object, or None."""
        shape_keys = getattr(source_obj.data, 'shape_keys', None)
        if shape_keys is None:
            return None
        return shape_keys.key_blocks.get(shapekey_name)

    def execute(self, context):
        tree, node = self._get_tree_and_node()
        if node is None:
            self.report({'ERROR'}, tr("Target ShapeKey Real-time Based Dynamic Mod node not found"))
            return {'CANCELLED'}

        shapekey_name = str(node.shapekey_name or "").strip()
        if not shapekey_name:
            self.report({'ERROR'}, tr("Please fill in the Shape Key Name first"))
            return {'CANCELLED'}

        source_obj = bpy.data.objects.get(self.source_object)
        if source_obj is None or source_obj.type != 'MESH' or source_obj.data is None:
            self.report({'ERROR'}, tr("Please choose a valid mesh object as the animation source"))
            return {'CANCELLED'}

        if self._find_shape_key_block(source_obj, shapekey_name) is None:
            self.report(
                {'ERROR'},
                tr("Object '{name}' has no shape key named '{shapekey}'").format(
                    name=source_obj.name, shapekey=shapekey_name,
                ),
            )
            return {'CANCELLED'}

        frames = self._frame_numbers()
        if len(frames) < 2:
            self.report({'ERROR'}, tr("At least 2 frames are required for a shape key timeline"))
            return {'CANCELLED'}
        if len(frames) > 1000:
            self.report({'ERROR'}, tr("Too many frames ({count}); please increase the frame step").format(count=len(frames)))
            return {'CANCELLED'}

        # Sample the evaluated shape key value at every requested frame.
        # frame_set evaluates the Key datablock animation, so
        # key_block.value already holds the animated value at that frame.
        scene = context.scene
        original_frame = scene.frame_current
        # Restore subframes too; baking should not move the user's time cursor.
        original_subframe = scene.frame_subframe
        sampled_weights = []
        window_manager = context.window_manager
        window_manager.progress_begin(0, len(frames))
        try:
            for index, frame_number in enumerate(frames):
                scene.frame_set(frame_number)
                key_block = self._find_shape_key_block(source_obj, shapekey_name)
                sampled_weights.append(float(key_block.value))
                window_manager.progress_update(index + 1)
        finally:
            window_manager.progress_end()
            scene.frame_set(original_frame, subframe=original_subframe)

        # Replace the whole timeline with the baked samples.
        node.weights.clear()
        for weight in sampled_weights:
            item = node.weights.add()
            item.weight = weight

        if self.match_scene_fps:
            # Bake to a fixed 60 FPS playback speed; the baked value no
            # longer follows the Blender scene frame rate.
            node.fps = 60.0

        # Sampling past the last keyed frame repeats the final weight in
        # every trailing entry, so the weight holds still before each loop
        # and users read that as a playback pause. Warn instead of trimming:
        # a deliberate rest before the loop is valid content.
        static_tail = trailing_static_frame_info(sampled_weights, list(frames), node.fps)
        if static_tail is not None:
            self.report({'WARNING'}, tr(
                "The last {held} baked weight(s) repeat the value of frame {frame}; playback will freeze for about {seconds:.2f} s before each loop. If this is not intended, bake up to frame {frame} instead."
            ).format(held=static_tail["held_frames"], frame=static_tail["last_unique_frame"], seconds=static_tail["held_seconds"]))

        tree.update_tag()
        self.report({'INFO'}, tr("Baked {count} weight frames into the ShapeKey Real-time Based Dynamic Mod node").format(count=len(sampled_weights)))
        return {'FINISHED'}


@translatable
class MIMINode_TimeShapeKey(MIMINodeBase):
    '''Time Shape Key: animate a shape key weight on a wall-clock timeline instead of a hotkey'''
    bl_idname = 'MIMINode_TimeShapeKey'
    # The title says what happens at runtime: the shape key deform is
    # recalculated from the animated weight on the GPU, every single frame.
    bl_label = 'ShapeKey Real-time Based Dynamic Mod'
    bl_icon = 'SHAPEKEY_DATA'

    def width_texts(self):
        """Return every text that decides how wide this node has to be."""
        # The title is the longest text here, so an old default title must not
        # shrink the node back to a width that truncates the new name.
        return [self.label, self.shapekey_name, self.comment]

    def update_fps(self, context):
        self.update_node_width(self.width_texts())

    def update_shapekey_name(self, context):
        self.update_node_width(self.width_texts())

    def update_comment(self, context):
        self.update_node_width(self.width_texts())

    shapekey_name: bpy.props.StringProperty(
        name=tr("Shape Key Name"),
        description=tr("Name of the shape key (on the exported objects) whose weight is animated by this timeline"),
        default="",
        update=update_shapekey_name,
    ) # type: ignore
    fps: bpy.props.FloatProperty(
        name=tr("FPS"),
        description=tr("Frames shown per second of wall-clock time; playback speed never depends on the game's frame rate"),
        default=60.0,
        min=0.01,
        soft_max=120.0,
        update=update_fps,
    ) # type: ignore
    weights: bpy.props.CollectionProperty(type=MIMINodeTimeShapeKeyWeightItem) # type: ignore
    # This key controls playback, not a cycle of individual weight values.
    # A disabled time shape contributes zero; other shapes remain untouched.
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
        # The node carries no object data; the output socket only exists so
        # the node can be wired into groups for visual organization.
        self.outputs.new('MIMISocketObject', "Output")
        # Size the node from its texts, so the full title stays readable.
        self.update_node_width(self.width_texts())
        self.use_custom_color = True
        self.color = (0.40, 0.56, 0.44)

    def draw_buttons(self, context, layout):
        layout.prop(self, "shapekey_name", text=tr("Shape Key Name"))
        layout.prop(self, "fps", text=tr("FPS"))
        layout.prop(self, "comment", text=tr("Comment"))
        # Reset only this timeline's weight when the switch is disabled.
        layout.prop(self, "toggle_key", text=tr("Animation Toggle Key"))
        controls = layout.column()
        controls.enabled = bool(self.toggle_key.strip())
        controls.prop(self, "start_enabled", text=tr("Start Enabled"))
        if self.toggle_key.strip():
            layout.label(text=tr("When off: set shape weight to 0"), icon='INFO')

        row = layout.row(align=True)
        op_add = row.operator("mimi.time_shapekey_add_weight", text=tr("Add"), icon='ADD')
        op_add.node_name = self.name
        op_rem = row.operator("mimi.time_shapekey_remove_weight", text=tr("Remove"), icon='REMOVE')
        op_rem.node_name = self.name

        # One weight per frame, in timeline order.
        box = layout.box()
        for index, item in enumerate(self.weights):
            row = box.row(align=True)
            row.label(text=tr("Frame {count}").format(count=index))
            row.prop(item, "weight", text="")
        if len(self.weights) == 0:
            box.label(text=tr("(Empty)"), icon='INFO')

        layout.separator()
        op_bake = layout.operator(
            "mimi.time_shapekey_bake_weights",
            text=tr("Bake Shape Key Weights"),
            icon='ARMATURE_DATA',
        )
        op_bake.node_name = self.name
        tree = self.id_data if getattr(self, "id_data", None) else None
        op_bake.tree_name = tree.name if tree else ""


classes = (
    MIMINodeTimeShapeKeyWeightItem,
    MIMINode_TimeShapeKey,
    MMT_OT_TimeShapeKey_AddWeight,
    MMT_OT_TimeShapeKey_RemoveWeight,
    MMT_OT_TimeShapeKey_BakeWeights,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
