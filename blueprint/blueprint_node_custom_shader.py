'''CustomShader node used to replace a draw call with a reusable INI section.'''

import bpy

from .blueprint_node_base import SSMTNodeBase


class SSMTNode_CustomShader(SSMTNodeBase):
    bl_idname = 'SSMTNode_CustomShader'
    bl_label = 'CustomShader'
    bl_icon = 'NODE_COMPOSITING'
    bl_width_min = 420

    mark_name: bpy.props.StringProperty(
        name='MarkName',
        description='CustomShader section suffix. Empty values are assigned a numeric name during export.',
        default='',
        update=lambda self, context: self._refresh_label(),
    )  # type: ignore

    body: bpy.props.StringProperty(
        name='Body',
        description='INI body. {{drawindexed}} is replaced by this Object Info draw call.',
        default='',
        options={'HIDDEN'},
    )  # type: ignore

    body_text: bpy.props.PointerProperty(
        name='Body',
        description='Text datablock containing the CustomShader INI body.',
        type=bpy.types.Text,
    )  # type: ignore

    def _refresh_label(self):
        suffix = str(self.mark_name or '').strip()
        self.label = 'CustomShader ' + suffix if suffix else 'CustomShader'

    def _assign_default_mark_name(self):
        tree = getattr(self, 'id_data', None)
        used = set()
        if tree is not None:
            for node in tree.nodes:
                if node == self or getattr(node, 'bl_idname', '') != self.bl_idname:
                    continue
                name = str(getattr(node, 'mark_name', '') or '').strip()
                if name.isdigit():
                    used.add(name)
        index = 0
        while str(index) in used:
            index += 1
        self.mark_name = str(index)

    def ensure_body_text(self):
        text = self.body_text
        if text is not None:
            return text

        suffix = str(self.mark_name or '').strip() or 'Body'
        text = bpy.data.texts.new('CustomShader_' + suffix)
        if self.body:
            text.write(self.body)
        self.body_text = text
        return text

    def get_body(self):
        if self.body_text is not None:
            return self.body_text.as_string()
        return self.body

    def init(self, context):
        self.outputs.new('SSMTSocketCustomShader', 'CustomShader')
        self._assign_default_mark_name()
        self._refresh_label()

    def draw_buttons(self, context, layout):
        layout.prop(self, 'mark_name', text='MarkName')
        row = layout.row(align=True)
        row.template_ID(self, 'body_text', text='Body')
        op = row.operator('ssmt.edit_custom_shader_body', text='', icon='TEXT')
        op.tree_name = self.id_data.name if self.id_data else ''
        op.node_name = self.name


class SSMT_OT_EditCustomShaderBody(bpy.types.Operator):
    bl_idname = 'ssmt.edit_custom_shader_body'
    bl_label = '编辑 CustomShader Body'
    bl_description = '在独立 Text Editor 中编辑完整的 CustomShader INI 内容'
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    tree_name: bpy.props.StringProperty(options={'HIDDEN'})  # type: ignore
    node_name: bpy.props.StringProperty(options={'HIDDEN'})  # type: ignore

    def execute(self, context):
        tree = bpy.data.node_groups.get(self.tree_name)
        node = tree.nodes.get(self.node_name) if tree else None
        if getattr(node, 'bl_idname', '') != SSMTNode_CustomShader.bl_idname:
            self.report({'ERROR'}, '未找到 CustomShader 节点')
            return {'CANCELLED'}

        text = node.ensure_body_text()
        old_windows = set(context.window_manager.windows)
        try:
            bpy.ops.wm.window_new_main()
        except RuntimeError:
            bpy.ops.wm.window_new()

        new_windows = set(context.window_manager.windows)
        window = next(iter(new_windows - old_windows), None)
        if window is None:
            self.report({'ERROR'}, '无法打开 Text Editor 窗口')
            return {'CANCELLED'}

        area = max(window.screen.areas, key=lambda item: item.width * item.height)
        area.type = 'TEXT_EDITOR'
        area.spaces.active.text = text
        return {'FINISHED'}


classes = (
    SSMT_OT_EditCustomShaderBody,
    SSMTNode_CustomShader,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
