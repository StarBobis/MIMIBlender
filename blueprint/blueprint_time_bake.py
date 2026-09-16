'''
Bake animation keyframes into per-frame mesh objects for the Time Switch node.

The Time Switch node swaps which object gets drawn based on wall-clock time,
so an animation (shape keys, armature pose, object transforms, constraints)
must first be flattened into a set of static objects: one per sampled frame.
This module samples the evaluated mesh at each requested frame, stores it as
a real mesh datablock, and wires the resulting objects into the frame sockets
of a Time Switch node in frame order.

Topology note: every baked frame comes from the same source mesh, so vertex
count and triangle order are identical across frames.  That keeps the
per-frame drawindexed offsets consistent inside the shared Submesh buffers.
'''
import bpy

from ..i18n.i18n import I18nOperator, tr
from .blueprint_node_time_switch import renumber_time_switch_sockets


class MMT_OT_BakeAnimationToTimeSwitch(I18nOperator):
    '''Sample an animated object at every chosen frame into static mesh objects, then wire them into the Time Switch node'''
    bl_idname = "mimi.bake_animation_to_time_switch"
    bl_label = "Bake Animation to Frames"
    bl_options = {'REGISTER', 'UNDO'}

    # Target Time Switch node identity (filled in by the node's button).
    node_name: bpy.props.StringProperty() # type: ignore
    tree_name: bpy.props.StringProperty() # type: ignore

    source_object: bpy.props.StringProperty(
        name=tr("Source Object"),
        description=tr("Animated mesh object to sample (shape keys, armature, constraints and transforms are baked in)"),
        default="",
    ) # type: ignore

    submesh_name: bpy.props.StringProperty(
        name=tr("Submesh"),
        description=tr("Submesh the baked frames belong to; written onto every created Object Info node"),
        default="",
    ) # type: ignore

    frame_start: bpy.props.IntProperty(
        name=tr("Start Frame"),
        default=1,
    ) # type: ignore
    frame_end: bpy.props.IntProperty(
        name=tr("End Frame"),
        default=24,
    ) # type: ignore
    frame_step: bpy.props.IntProperty(
        name=tr("Frame Step"),
        description=tr("Sample one frame every N frames; larger steps produce fewer frames"),
        default=1,
        min=1,
    ) # type: ignore

    match_scene_fps: bpy.props.BoolProperty(
        name=tr("Sync Node FPS with Scene"),
        description=tr("Set the Time Switch node's FPS to scene_fps / frame_step so the mod plays back at the same speed as the Blender timeline"),
        default=True,
    ) # type: ignore

    def _get_tree_and_node(self):
        tree = bpy.data.node_groups.get(self.tree_name) if self.tree_name else None
        if tree is None or getattr(tree, "bl_idname", "") != 'MIMIBlueprintTreeType':
            return None, None
        node = tree.nodes.get(self.node_name) if self.node_name else None
        if node is None or getattr(node, "bl_idname", "") != 'MIMINode_TimeSwitch':
            return tree, None
        return tree, node

    def invoke(self, context, event):
        tree, node = self._get_tree_and_node()
        if node is None:
            self.report({'WARNING'}, tr("Please run this from a Time Switch node"))
            return {'CANCELLED'}

        scene = context.scene
        self.frame_start = scene.frame_start
        self.frame_end = scene.frame_end

        # Prefill the source object with the currently active mesh object.
        active_obj = getattr(context, "active_object", None)
        if active_obj is not None and active_obj.type == 'MESH':
            self.source_object = active_obj.name

        return context.window_manager.invoke_props_dialog(self, width=420)

    def draw(self, context):
        layout = self.layout
        layout.prop_search(self, "source_object", bpy.data, "objects", text=tr("Source Object"), icon='OBJECT_DATA')

        # The Submesh dropdown uses the same per-tree list the Object Info
        # node uses, so baked nodes resolve their draw call exactly the same
        # way as hand-built ones.
        tree = bpy.data.node_groups.get(self.tree_name) if self.tree_name else None
        if tree is not None:
            layout.prop_search(self, "submesh_name", tree, "ssmt_submesh_items", text=tr("Submesh"), icon='OUTLINER_COLLECTION')

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
        return list(range(self.frame_start, self.frame_end + 1, self.frame_step))

    def execute(self, context):
        tree, node = self._get_tree_and_node()
        if node is None:
            self.report({'ERROR'}, tr("Target Time Switch node not found"))
            return {'CANCELLED'}

        source_obj = bpy.data.objects.get(self.source_object)
        if source_obj is None or source_obj.type != 'MESH' or source_obj.data is None:
            self.report({'ERROR'}, tr("Please choose a valid mesh object as the animation source"))
            return {'CANCELLED'}

        submesh_name = str(self.submesh_name or "").strip()
        if not submesh_name:
            self.report({'ERROR'}, tr("Please choose a Submesh for the baked frames"))
            return {'CANCELLED'}

        frames = self._frame_numbers()
        if len(frames) < 2:
            self.report({'ERROR'}, tr("At least 2 frames are required for a time switch animation"))
            return {'CANCELLED'}
        if len(frames) > 1000:
            # A hard sanity cap: baking is a full depsgraph evaluation per
            # frame, so an accidental huge range would freeze Blender.
            self.report({'ERROR'}, tr("Too many frames ({count}); please increase the frame step").format(count=len(frames)))
            return {'CANCELLED'}

        baked_objects = self._bake_frames(context, source_obj, frames)
        if not baked_objects:
            self.report({'ERROR'}, tr("Baking produced no objects"))
            return {'CANCELLED'}

        self._rebuild_node_wiring(tree, node, baked_objects, submesh_name)

        if self.match_scene_fps:
            scene_fps = context.scene.render.fps / context.scene.render.fps_base
            node.fps = round(scene_fps / self.frame_step, 4)

        tree.update_tag()
        self.report({'INFO'}, tr("Baked {count} frames and wired them into the Time Switch node").format(count=len(baked_objects)))
        return {'FINISHED'}

    def _bake_frames(self, context, source_obj, frames):
        """Sample the evaluated mesh at every frame into a new hidden object."""
        scene = context.scene

        # All baked frames live in their own collection to keep the outliner tidy.
        collection = bpy.data.collections.new("TB_" + source_obj.name)
        scene.collection.children.link(collection)

        baked_objects = []
        original_frame = scene.frame_current
        window_manager = context.window_manager
        window_manager.progress_begin(0, len(frames))
        try:
            for index, frame_number in enumerate(frames):
                scene.frame_set(frame_number)

                # frame_set invalidates the depsgraph; always fetch a fresh one
                # before asking for the evaluated object.
                depsgraph = context.evaluated_depsgraph_get()
                evaluated_obj = source_obj.evaluated_get(depsgraph)

                # Copy the fully evaluated mesh (modifiers, shape keys,
                # armature, constraints all baked into vertex positions).
                mesh = bpy.data.meshes.new_from_object(
                    evaluated_obj,
                    preserve_all_data_layers=True,
                    depsgraph=depsgraph,
                )

                new_obj = bpy.data.objects.new(source_obj.name + "_f" + str(frame_number), mesh)
                # Keep the world placement of this frame as a static transform.
                new_obj.matrix_world = evaluated_obj.matrix_world.copy()

                # Vertex groups live on the object (not the mesh); without the
                # names the exporter cannot address the baked blend weights.
                for vertex_group in source_obj.vertex_groups:
                    new_obj.vertex_groups.new(name=vertex_group.name)

                # The object must enter the view layer before hide_set() can
                # touch it, so link it to the collection first.
                collection.objects.link(new_obj)

                # Baked frames overlap at the same location; hide them so the
                # viewport stays usable.  Export reads the datablocks directly
                # and does not depend on visibility.
                new_obj.hide_set(True)
                new_obj.hide_render = True

                baked_objects.append((frame_number, new_obj))
                window_manager.progress_update(index + 1)
        finally:
            window_manager.progress_end()
            # Restore the frame the user was looking at before baking.
            scene.frame_set(original_frame)

        return baked_objects

    def _rebuild_node_wiring(self, tree, node, baked_objects, submesh_name):
        """Resize the node's frame sockets and wire one Object Info node per frame."""
        # Resize the frame sockets to exactly match the baked frame count.
        while len(node.inputs) < len(baked_objects):
            node.inputs.new('MIMISocketObject', "Frame {count}".format(count=len(node.inputs)))
        while len(node.inputs) > len(baked_objects):
            node.inputs.remove(node.inputs[-1])
        renumber_time_switch_sockets(node)

        # Create one Object Info node per frame in a column left of the switch.
        base_x = node.location.x - 450
        base_y = node.location.y
        for index, (frame_number, baked_obj) in enumerate(baked_objects):
            object_node = tree.nodes.new('MIMINode_Object_Info')
            object_node.location = (base_x, base_y - index * 260)
            object_node.object_name = baked_obj.name
            object_node.submesh_name = submesh_name
            tree.links.new(object_node.outputs[0], node.inputs[index])


classes = (
    MMT_OT_BakeAnimationToTimeSwitch,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
