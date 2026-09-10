'''
Base nodes used to build the SSMT blueprint architecture.
Each node type lives in its own py file
so the code is easy to read and understand.
'''
import bpy
from bpy.types import NodeTree, Node, NodeSocket, PropertyGroup

from ..common.global_config import GlobalConfig
from ..i18n.i18n import I18nOperator, tr, translatable



# Custom Socket Types
class MIMISubmeshListItem(PropertyGroup):
    name: bpy.props.StringProperty(name=tr("Submesh"), default="") # type: ignore


@translatable
class MIMISocketObject(NodeSocket):
    '''Custom Socket for Object Data'''
    bl_idname = 'MIMISocketObject'
    bl_label = 'Object Socket'

    def draw_color(self, context, node):
        return (0.0, 0.8, 0.8, 1.0) # Cyan/Teal

    def draw(self, context, layout, node, text):
        layout.label(text=text)

# 1. Define the custom node tree type


@translatable
class MIMIBlueprintTree(NodeTree):
    '''SSMT Mod Logic Blueprint'''
    bl_idname = 'MIMIBlueprintTreeType'
    bl_label = 'SSMT Blueprint'
    bl_icon = 'NODETREE'


# 2. Define the base nodes
class MIMINodeBase(Node):
    @classmethod
    def poll(cls, ntree):
        return ntree.bl_idname == 'MIMIBlueprintTreeType'
    
    def calculate_text_width(self, text, padding=40):
        """Estimate the width required to display the text."""
        if not text:
            return 200
        
        # Chinese characters are roughly twice as wide as English characters
        char_count = 0
        for char in text:
            if '\u4e00' <= char <= '\u9fff':
                char_count += 2
            else:
                char_count += 1
        
        # Each character takes about 12 px of width (the Blender node UI font is fairly wide)
        width = char_count * 12 + padding
        
        # Enforce a minimum width of 200
        return max(200, width)
    
    def update_node_width(self, texts):
        """Update the node width based on the given texts."""
        if not texts:
            return
        
        max_width = 200
        for text in texts:
            width = self.calculate_text_width(text)
            if width > max_width:
                max_width = width
        
        # Reserve extra width for the dropdown (right arrow and margins, about 50 px)
        self.width = max_width + 50
    

class THEHERTA3_OT_OpenPersistentBlueprint(I18nOperator):
    bl_idname = "mimi.open_persistent_blueprint"
    bl_label = "Open Blueprint"
    bl_description = "Open a standalone blueprint window for configuring Mod logic"
    bl_options = {'REGISTER', 'UNDO'}

    blueprint_name: bpy.props.StringProperty(
        name=tr("Blueprint Name"),
        default="",
        options={'SKIP_SAVE'},
    ) # type: ignore
    
    def execute(self, context):
        # 1. Get or create the blueprint tree
        GlobalConfig.read_from_main_json_ssmt4()
        requested_tree_name = str(self.blueprint_name or "").strip()
        tree_name = requested_tree_name or GlobalConfig.get_workspace_name()
        
        # Look for an existing NodeGroup with the same name
        tree = bpy.data.node_groups.get(tree_name)
        if tree and getattr(tree, "bl_idname", "") != 'MIMIBlueprintTreeType':
            tree = None

        if not tree and requested_tree_name:
            from .blueprint_export_helper import BlueprintExportHelper
            tree = BlueprintExportHelper.get_selected_blueprint_tree(requested_tree_name, context=context)

        if not tree:
            # Create a new NodeTree; the type must be our custom bl_idname
            tree = bpy.data.node_groups.new(name=tree_name, type='MIMIBlueprintTreeType')
            tree.use_fake_user = True

        from .blueprint_export_helper import BlueprintExportHelper
        BlueprintExportHelper.set_runtime_blueprint_tree(tree)

        mimi_global_properties = getattr(getattr(context, "scene", None), "mimi_global_properties", None)
        if mimi_global_properties and getattr(mimi_global_properties, "selected_blueprint_name", "") != tree.name:
            mimi_global_properties.selected_blueprint_name = tree.name
        
        # 1.5 Check for an already-open window editing this tree; reuse it instead of closing and reopening.
        target_window = None
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'NODE_EDITOR':
                    for space in area.spaces:
                        if space.type == 'NODE_EDITOR' and space.node_tree == tree:
                            target_window = window
                            break
                if target_window: break
            if target_window: break

        if target_window:
            return {'FINISHED'}

        # 2. Open a separate main window so ordinary child windows do not stay on top of the Blender main UI.
        old_windows = set(context.window_manager.windows)

        try:
            bpy.ops.wm.window_new_main()
        except (AttributeError, RuntimeError):
            bpy.ops.wm.window_new()
        
        new_windows = set(context.window_manager.windows)
        created_window = (new_windows - old_windows).pop() if (new_windows - old_windows) else None
        
        if created_window:
            screen = created_window.screen
            
            target_area = max(screen.areas, key=lambda a: a.width * a.height)
            
            if target_area:
                target_area.ui_type = 'MIMIBlueprintTreeType' # Seems ineffective; the node editor needs the tree type set
                target_area.type = 'NODE_EDITOR'
                
                # Configure space properties
                for space in target_area.spaces:
                    if space.type == 'NODE_EDITOR':
                        space.tree_type = 'MIMIBlueprintTreeType' # Key: switch to the custom tree type
                        space.node_tree = tree # Set the data block to edit
                        space.pin = True # Pin
                        
                        # Try to adjust the view (optional)
                        
        return {'FINISHED'}


class THEHERTA3_OT_DeletePersistentBlueprint(I18nOperator):
    bl_idname = "mimi.delete_persistent_blueprint"
    bl_label = "Delete Blueprint"
    bl_description = "Delete the currently selected blueprint"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    blueprint_name: bpy.props.StringProperty(
        name=tr("Blueprint Name"),
        default="",
        options={'SKIP_SAVE'},
    ) # type: ignore

    def _get_target_tree(self, context):
        from .blueprint_export_helper import BlueprintExportHelper

        requested_tree_name = str(self.blueprint_name or "").strip()
        if requested_tree_name == "__NONE__":
            return None

        return BlueprintExportHelper.get_selected_blueprint_tree(requested_tree_name, context=context)

    def invoke(self, context, event):
        target_tree = self._get_target_tree(context)
        if not target_tree:
            self.report({'WARNING'}, tr("There is no blueprint to delete!"))
            return {'CANCELLED'}

        self.blueprint_name = target_tree.name
        return context.window_manager.invoke_props_dialog(self, width=360)

    def draw(self, context):
        layout = self.layout
        layout.label(text=tr("Delete the currently selected blueprint?"), icon='TRASH')
        layout.label(text=self.blueprint_name)
        layout.label(text=tr("This cannot be undone; please confirm this is not a mistake."), icon='ERROR')

    def execute(self, context):
        from .blueprint_export_helper import BlueprintExportHelper

        target_tree = self._get_target_tree(context)
        if not target_tree:
            self.report({'WARNING'}, tr("There is no blueprint to delete!"))
            return {'CANCELLED'}

        for window in context.window_manager.windows:
            for area in window.screen.areas:
                if area.type != 'NODE_EDITOR':
                    continue
                for space in area.spaces:
                    if space.type != 'NODE_EDITOR':
                        continue
                    if getattr(space, "node_tree", None) == target_tree:
                        space.node_tree = None

        if BlueprintExportHelper.runtime_blueprint_tree_name == target_tree.name:
            BlueprintExportHelper.runtime_blueprint_tree_name = ""

        deleted_blueprint_name = target_tree.name
        bpy.data.node_groups.remove(target_tree)

        mimi_global_properties = getattr(getattr(context, "scene", None), "mimi_global_properties", None)
        preferred_blueprint_name = BlueprintExportHelper.get_preferred_blueprint_name(context=context)
        if mimi_global_properties:
            mimi_global_properties.selected_blueprint_name = preferred_blueprint_name or "__NONE__"

        for window in context.window_manager.windows:
            for area in window.screen.areas:
                area.tag_redraw()

        self.report({'INFO'}, tr("Deleted blueprint: ") + deleted_blueprint_name)
        return {'FINISHED'}


class THEHERTA3_OT_RenamePersistentBlueprint(I18nOperator):
    bl_idname = "mimi.rename_persistent_blueprint"
    bl_label = "Rename Blueprint"
    bl_description = "Rename the currently selected blueprint"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    blueprint_name: bpy.props.StringProperty(
        name=tr("Blueprint Name"),
        default="",
        options={'SKIP_SAVE'},
    ) # type: ignore

    new_blueprint_name: bpy.props.StringProperty(
        name=tr("New Blueprint Name"),
        default="",
    ) # type: ignore

    def _get_target_tree(self, context):
        from .blueprint_export_helper import BlueprintExportHelper

        requested_tree_name = str(self.blueprint_name or "").strip()
        if requested_tree_name == "__NONE__":
            return None

        return BlueprintExportHelper.get_selected_blueprint_tree(requested_tree_name, context=context)

    def invoke(self, context, event):
        target_tree = self._get_target_tree(context)
        if not target_tree:
            self.report({'WARNING'}, tr("There is no blueprint to rename!"))
            return {'CANCELLED'}

        self.blueprint_name = target_tree.name
        self.new_blueprint_name = target_tree.name
        return context.window_manager.invoke_props_dialog(self, width=360)

    def draw(self, context):
        layout = self.layout
        layout.label(text=tr("Enter the new blueprint name"), icon='GREASEPENCIL')
        layout.prop(self, "new_blueprint_name", text=tr("Name"))

    def execute(self, context):
        from .blueprint_export_helper import BlueprintExportHelper

        target_tree = self._get_target_tree(context)
        if not target_tree:
            self.report({'WARNING'}, tr("There is no blueprint to rename!"))
            return {'CANCELLED'}

        new_name = str(self.new_blueprint_name or "").strip()
        if not new_name:
            self.report({'ERROR'}, tr("Blueprint name cannot be empty!"))
            return {'CANCELLED'}

        if new_name == "__NONE__":
            self.report({'ERROR'}, tr("Blueprint name cannot use the reserved value __NONE__!"))
            return {'CANCELLED'}

        if new_name == target_tree.name:
            self.report({'INFO'}, tr("Blueprint name is unchanged"))
            return {'CANCELLED'}

        existing_tree = bpy.data.node_groups.get(new_name)
        if existing_tree and existing_tree != target_tree:
            self.report({'ERROR'}, tr("A blueprint with that name already exists; please use a different name!"))
            return {'CANCELLED'}

        old_name = target_tree.name
        target_tree.name = new_name

        if BlueprintExportHelper.runtime_blueprint_tree_name == old_name:
            BlueprintExportHelper.runtime_blueprint_tree_name = target_tree.name

        mimi_global_properties = getattr(getattr(context, "scene", None), "mimi_global_properties", None)
        if mimi_global_properties:
            mimi_global_properties.selected_blueprint_name = target_tree.name

        for window in context.window_manager.windows:
            for area in window.screen.areas:
                area.tag_redraw()

        self.report({'INFO'}, tr("Renamed blueprint to: ") + target_tree.name)
        return {'FINISHED'}
    
@translatable
class MIMIPT_FrameProperties(bpy.types.Panel):
    '''Frame properties panel: with a Frame node selected, adjust its color, transparency, label, etc. from the sidebar'''
    bl_idname = "MIMIPT_FrameProperties"
    bl_label = "Frame Properties"
    bl_space_type = 'NODE_EDITOR'
    bl_region_type = 'UI'
    bl_category = "SSMT"

    @classmethod
    def poll(cls, context):
        # Show only inside an SSMT blueprint tree
        space = context.space_data
        if space.type != 'NODE_EDITOR':
            return False
        tree = getattr(space, "edit_tree", None) or getattr(space, "node_tree", None)
        if not tree or getattr(tree, "bl_idname", "") != 'MIMIBlueprintTreeType':
            return False
        # Check whether a Frame node is selected
        if not context.selected_nodes:
            return False
        for node in context.selected_nodes:
            if node.bl_idname == 'NodeFrame':
                return True
        return False

    def draw(self, context):
        layout = self.layout
        # Collect all selected Frame nodes
        frames = [n for n in context.selected_nodes if n.bl_idname == 'NodeFrame']
        if not frames:
            return

        # Use the first frame's properties as the source; with multiple frames selected, apply them uniformly
        frame = frames[0]

        # === Label ===
        box = layout.box()
        box.label(text=tr("Label"), icon='FONT_DATA')
        col = box.column(align=True)
        col.prop(frame, "label", text=tr("Name"))
        col.prop(frame, "label_size", text=tr("Font Size"))

        # === Appearance ===
        box = layout.box()
        box.label(text=tr("Appearance"), icon='MATERIAL')
        col = box.column(align=True)
        col.prop(frame, "use_custom_color", text=tr("Custom Color"))
        if frame.use_custom_color:
            col.prop(frame, "color", text="")
        col.prop(frame, "shrink", text=tr("Auto Shrink"))

        # === Size ===
        box = layout.box()
        box.label(text=tr("Size"), icon='MESH_PLANE')
        col = box.column(align=True)
        col.prop(frame, "width", text=tr("Width"))
        col.prop(frame, "height", text=tr("Height"))

        # === Extended text ===
        box = layout.box()
        box.label(text=tr("Description Text"), icon='TEXT')
        col = box.column()
        col.prop(frame, "text", text="")

        # === Visibility ===
        box = layout.box()
        box.label(text=tr("Visibility"), icon='HIDE_OFF')
        col = box.column(align=True)
        col.prop(frame, "hide", text=tr("Hide"))
        col.prop(frame, "mute", text=tr("Mute (Disable)"))

        # === Apply-to-all button for multi-selection ===
        if len(frames) > 1:
            layout.separator()
            layout.label(text=tr("Selected {count} Frames").format(count=len(frames)), icon='INFO')
            layout.label(text=tr("After editing the properties above, click the button to apply to all"), icon='LOOP_BACK')
            op = layout.operator("mimi.apply_frame_properties_to_all", text=tr("Apply to All Selected Frames"), icon='CHECKMARK')
            op.source_frame_name = frame.name
            op.tree_name = frame.id_data.name if frame.id_data else ""


class SSMT_OT_ApplyFramePropertiesToAll(I18nOperator):
    '''Copy all properties of the first selected Frame to the other selected Frames'''
    bl_idname = "mimi.apply_frame_properties_to_all"
    bl_label = "Apply to All Selected Frames"
    bl_options = {'REGISTER', 'UNDO'}

    source_frame_name: bpy.props.StringProperty()  # type: ignore
    tree_name: bpy.props.StringProperty()          # type: ignore

    def execute(self, context):
        tree = bpy.data.node_groups.get(self.tree_name)
        if not tree:
            return {'CANCELLED'}

        source = tree.nodes.get(self.source_frame_name)
        if not source or source.bl_idname != 'NodeFrame':
            return {'CANCELLED'}

        frames = [n for n in context.selected_nodes if n.bl_idname == 'NodeFrame' and n != source]
        props = [
            'label', 'label_size', 'use_custom_color', 'color',
            'shrink', 'width', 'height', 'text', 'hide', 'mute'
        ]
        for frame in frames:
            for prop in props:
                setattr(frame, prop, getattr(source, prop))

        self.report({'INFO'}, tr("Applied properties of {name} to {count} Frames").format(name=source.label or source.name, count=len(frames)))
        return {'FINISHED'}


def register():
    bpy.utils.register_class(MIMISubmeshListItem)
    bpy.utils.register_class(MIMIBlueprintTree)
    bpy.utils.register_class(MIMISocketObject)
    bpy.utils.register_class(THEHERTA3_OT_OpenPersistentBlueprint)
    bpy.utils.register_class(THEHERTA3_OT_DeletePersistentBlueprint)
    bpy.utils.register_class(THEHERTA3_OT_RenamePersistentBlueprint)
    bpy.utils.register_class(MIMIPT_FrameProperties)
    bpy.utils.register_class(SSMT_OT_ApplyFramePropertiesToAll)
    MIMIBlueprintTree.ssmt_submesh_items = bpy.props.CollectionProperty(type=MIMISubmeshListItem) # type: ignore[attr-defined]
    from .blueprint_export_helper import BlueprintExportHelper
    BlueprintExportHelper.register_workspace_tree_sync_timer()


def unregister():
    from .blueprint_export_helper import BlueprintExportHelper
    BlueprintExportHelper.unregister_workspace_tree_sync_timer()
    del MIMIBlueprintTree.ssmt_submesh_items
    bpy.utils.unregister_class(SSMT_OT_ApplyFramePropertiesToAll)
    bpy.utils.unregister_class(MIMIPT_FrameProperties)
    bpy.utils.unregister_class(THEHERTA3_OT_RenamePersistentBlueprint)
    bpy.utils.unregister_class(THEHERTA3_OT_DeletePersistentBlueprint)
    bpy.utils.unregister_class(MIMISocketObject)
    bpy.utils.unregister_class(THEHERTA3_OT_OpenPersistentBlueprint)
    bpy.utils.unregister_class(MIMIBlueprintTree)
    bpy.utils.unregister_class(MIMISubmeshListItem)
