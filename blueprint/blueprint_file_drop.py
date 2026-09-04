'''
蓝图文件拖放支持：
- 拖入 .dds/.png → 在松开鼠标的位置创建贴图节点（SSMTNode_Texture），
  并从文件名尽量解析 Hash 与 Mark Name。
- 拖入 .ib/.buf/.txt → 在松开鼠标的位置创建物体信息节点（SSMTNode_Object_Info），
  并从文件名尽量解析 submesh_name（新格式 DrawIB-Component / 旧格式长名 / 带 LOD 前缀均可）。

通过 bpy.types.FileHandler 接管操作系统拖入 Node Editor 的文件，
仅在当前节点树为 SSMTBlueprintTreeType 时生效，不影响其它编辑器。
'''
import os
import re

import bpy

from ..utils.translate_utils import rpt_
from ..workspace.ssmt_workspace import WorkSpaceModel


TEXTURE_EXTENSIONS = {".dds", ".png"}
MESH_EXTENSIONS = {".ib", ".buf", ".txt"}

# 8位十六进制 Hash（不允许前后紧邻更多十六进制字符，避免截断更长字符串）
HASH_PATTERN = re.compile(r"(?<![0-9a-fA-F])([0-9a-fA-F]{8})(?![0-9a-fA-F])")

DROP_STACK_OFFSET_Y = 60.0


def is_ssmt_blueprint_context(context) -> bool:
    '''当前上下文是否为显示 SSMT 蓝图的节点编辑器。'''
    area = getattr(context, "area", None)
    if not area or area.type != 'NODE_EDITOR':
        return False
    region = getattr(context, "region", None)
    if not region or region.type != 'WINDOW':
        return False
    space = getattr(context, "space_data", None)
    tree = getattr(space, "node_tree", None) if space else None
    return bool(tree) and getattr(tree, "bl_idname", "") == 'SSMTBlueprintTreeType'


def parse_texture_filename(filepath: str):
    '''从贴图文件名尽量解析 (texture_hash, mark_name)。

    常见格式: <Hash>_<MarkName>.dds / <MarkName>_<Hash>.dds。
    找不到 Hash 时仅返回 mark_name。
    '''
    base_name = os.path.splitext(os.path.basename(filepath))[0]
    match = HASH_PATTERN.search(base_name)
    if not match:
        return "", base_name

    texture_hash = match.group(1).lower()
    # Hash 前后的剩余部分取非空的一段作为 Mark Name
    suffix = base_name[match.end():].lstrip("_-. ")
    prefix = base_name[:match.start()].rstrip("_-. ")
    mark_name = (suffix or prefix).strip()
    return texture_hash, mark_name


def parse_mesh_filename(filepath: str) -> str:
    '''从 .ib/.buf/.txt 文件名尽量解析 submesh_name。

    识别成功时返回标准化新格式名（如 LOD0.94517393-0），
    识别失败时回退为原始文件名（不含扩展名）。
    '''
    base_name = os.path.splitext(os.path.basename(filepath))[0]
    try:
        ws_model = WorkSpaceModel()
        parsed = ws_model.parse_any_format_name(base_name)
    except Exception:
        parsed = None
    if parsed and parsed.get("draw_ib"):
        submesh_name = f"{parsed['draw_ib']}-{parsed['component']}"
        lod_name = str(parsed.get("lod") or "")
        if lod_name:
            submesh_name = f"{lod_name}.{submesh_name}"
        return submesh_name
    return base_name


class SSMT_OT_BlueprintFileDrop(bpy.types.Operator):
    '''拖放文件到 SSMT 蓝图，在松开鼠标的位置创建对应节点'''
    bl_idname = "ssmt.blueprint_file_drop"
    bl_label = "拖放文件到蓝图"
    bl_options = {'UNDO'}

    # FileHandler 会把单文件写入 filepath；要接收多文件，则必须同时声明
    # directory 与 files（名称和类型均是 Blender 约定的一部分）。
    filepath: bpy.props.StringProperty(  # type: ignore
        subtype='FILE_PATH',
        options={'HIDDEN', 'SKIP_SAVE'},
    )
    directory: bpy.props.StringProperty(  # type: ignore
        subtype='DIR_PATH',
        options={'HIDDEN', 'SKIP_SAVE'},
    )
    files: bpy.props.CollectionProperty(  # type: ignore
        type=bpy.types.OperatorFileListElement,
        options={'HIDDEN', 'SKIP_SAVE'},
    )

    def _filepaths(self):
        '''返回本次拖放中 Blender 传入的全部文件路径。'''
        if self.directory and len(self.files) > 0:
            return [
                os.path.join(self.directory, file_element.name)
                for file_element in self.files
                if file_element.name
            ]
        return [self.filepath] if self.filepath else []

    def _create_texture_node(self, tree, location, filepath):
        node = tree.nodes.new(type='SSMTNode_Texture')
        node.location = location
        texture_hash, mark_name = parse_texture_filename(filepath)
        if texture_hash:
            node.texture_hash = texture_hash
        if mark_name:
            node.mark_name = mark_name
        node.texture_filepath = filepath
        node.texture_filename = os.path.basename(filepath)
        return node

    def _create_mesh_info_node(self, tree, location, filepath):
        node = tree.nodes.new(type='SSMTNode_Object_Info')
        node.location = location
        node.submesh_name = parse_mesh_filename(filepath)
        return node

    def invoke(self, context, event):
        space = getattr(context, "space_data", None)
        tree = getattr(space, "node_tree", None) if space else None
        if tree is None or getattr(tree, "bl_idname", "") != 'SSMTBlueprintTreeType':
            return {'CANCELLED'}

        # FileHandler 的 poll_drop 限定在 WINDOW region，因此这里的
        # mouse_region_x/y 就是松开鼠标时的画布区域坐标。
        region = getattr(context, "region", None)
        if region is None or region.type != 'WINDOW':
            return {'CANCELLED'}

        # 不直接调用 region.view2d.region_to_view：节点坐标还需要处理
        # Blender 的 UI_SCALE_FAC。这个 SpaceNodeEditor 方法与原生
        # NODE_OT_add_file 使用完全相同的换算流程。
        space.cursor_location_from_region(
            event.mouse_region_x,
            event.mouse_region_y,
        )
        base_location = tuple(space.cursor_location)

        filepaths = self._filepaths()
        if not filepaths:
            return {'CANCELLED'}

        for other_node in tree.nodes:
            other_node.select = False

        created_nodes = []
        for stack_index, filepath in enumerate(filepaths):
            location = (
                base_location[0],
                base_location[1] - stack_index * DROP_STACK_OFFSET_Y,
            )
            extension = os.path.splitext(filepath)[1].lower()
            if extension in TEXTURE_EXTENSIONS:
                node = self._create_texture_node(tree, location, filepath)
            elif extension in MESH_EXTENSIONS:
                node = self._create_mesh_info_node(tree, location, filepath)
            else:
                continue
            node.select = True
            created_nodes.append(node)

        if not created_nodes:
            return {'CANCELLED'}

        tree.nodes.active = created_nodes[0]

        if len(created_nodes) == 1:
            message = rpt_("已从文件创建节点: {name}").format(
                name=os.path.basename(filepaths[0]),
            )
        else:
            message = rpt_("已从文件创建 {count} 个节点").format(
                count=len(created_nodes),
            )
        self.report({'INFO'}, message)
        return {'FINISHED'}


classes = [SSMT_OT_BlueprintFileDrop]

class SSMT_FH_BlueprintFileDrop(bpy.types.FileHandler):
    '''接管操作系统拖入 SSMT 蓝图编辑器的文件'''
    bl_idname = "SSMT_FH_BlueprintFileDrop"
    bl_label = "拖放文件到SSMT蓝图"
    bl_import_operator = "ssmt.blueprint_file_drop"
    bl_file_extensions = ".dds;.png;.ib;.buf;.txt"

    @classmethod
    def poll_drop(cls, context):
        return is_ssmt_blueprint_context(context)

classes.append(SSMT_FH_BlueprintFileDrop)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
