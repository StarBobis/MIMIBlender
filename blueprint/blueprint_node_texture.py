'''
贴图节点：单个节点提供 Hash 出口和 Slot 出口
- Hash 出口 (SSMTSocketObject)：当成“物体”参与蓝图链路，生成独立 [TextureOverride_<hash>] + [Resource<name>]
- Slot 出口 (SSMTSocketTexture)：连到 Object Info 的 texture slot 输入，生成 ps-tX = Resource<name>
'''
import os

import bpy

from ..utils.translate_utils import iface_
from ..common.texture_naming import (
    default_texture_filename,
    default_texture_resource_name,
    normalize_texture_filename,
    normalize_texture_resource_name,
)
from .blueprint_node_base import SSMTNodeBase


def _get_default_texture_filename(texture_hash: str, mark_name: str) -> str:
    return default_texture_filename(texture_hash, mark_name)


# 预览图 mtime 缓存：{预览路径: mtime}
# 源文件变更时触发 image.reload()，保证替换贴图后预览同步刷新。
_preview_mtime_cache: dict = {}


class SSMTNode_Texture(SSMTNodeBase):
    '''贴图节点'''
    bl_idname = 'SSMTNode_Texture'
    bl_label = '贴图'
    bl_icon = 'IMAGE_DATA'

    texture_hash: bpy.props.StringProperty(
        name="Hash",
        description="8位十六进制贴图Hash",
        default="",
        update=lambda self, ctx: self._refresh_label(),
    )  # type: ignore

    mark_name: bpy.props.StringProperty(
        name="Mark Name",
        description="用于注释和默认文件名",
        default="",
        update=lambda self, ctx: self._refresh_label(),
    )  # type: ignore

    resource_name: bpy.props.StringProperty(
        name="Resource Name",
        description="留空时使用 Resource_<MapType>_<Hash>",
        default="",
    )  # type: ignore

    texture_filename: bpy.props.StringProperty(
        name="文件名",
        description="生成目录中的文件名，留空时使用 <Hash>_<MapType>.dds",
        default="",
    )  # type: ignore

    texture_filepath: bpy.props.StringProperty(
        name="文件路径",
        description="源贴图文件路径",
        subtype='FILE_PATH',
        default="",
    )  # type: ignore

    texture_format: bpy.props.EnumProperty(
        name="目标格式",
        description="生成 Mod 时该贴图应转换成的 DXGI 格式；留空/未知时不做转换",
        items=[
            ('AUTO', "自动 / 不转换", "不对源文件做格式转换"),
            ('BC7_UNORM', 'BC7_UNORM', 'BC7_UNORM'),
            ('BC7_UNORM_SRGB', 'BC7_UNORM_SRGB', 'BC7_UNORM_SRGB'),
            ('R8G8B8A8_UNORM', 'R8G8B8A8_UNORM', 'R8G8B8A8_UNORM'),
            ('R8G8B8A8_UNORM_SRGB', 'R8G8B8A8_UNORM_SRGB', 'R8G8B8A8_UNORM_SRGB'),
            ('R10G10B10A2_UNORM', 'R10G10B10A2_UNORM', 'R10G10B10A2_UNORM'),
            ('R11G11B10_FLOAT', 'R11G11B10_FLOAT', 'R11G11B10_FLOAT'),
            ('BC5_UNORM', 'BC5_UNORM', 'BC5_UNORM'),
            ('CUSTOM', '自定义', '手动填写目标格式'),
        ],
        default='AUTO',
    )  # type: ignore

    texture_format_custom: bpy.props.StringProperty(
        name="自定义格式",
        description="手动填写的 DXGI 格式名称",
        default="",
    )  # type: ignore

    @property
    def effective_texture_format(self) -> str:
        """返回实际生效的目标格式字符串，空字符串表示不转换。"""
        fmt = self.texture_format
        if fmt == 'CUSTOM':
            return self.texture_format_custom.strip()
        if fmt == 'AUTO':
            return ''
        return fmt

    def _resolve_preview_path(self) -> str:
        """解析用于预览的图片路径：优先使用同名 .jpg（SSMT 生成的预览图），
        否则直接尝试加载源文件（Blender 可读取 DDS）。"""
        path = str(self.texture_filepath or "").strip()
        if not path:
            return ""
        path = bpy.path.abspath(path)
        if not os.path.isfile(path):
            return ""
        jpg_path = os.path.splitext(path)[0] + ".jpg"
        if os.path.isfile(jpg_path):
            return jpg_path
        return path

    def _get_preview_image(self):
        preview_path = self._resolve_preview_path()
        if not preview_path:
            return None
        try:
            mtime = os.path.getmtime(preview_path)
        except OSError:
            return None
        try:
            image = bpy.data.images.load(preview_path, check_existing=True)
        except Exception as e:
            print(f"[TexturePreview] 预览加载失败: {preview_path}, {e}")
            return None
        # 源文件变化时重载，保证替换贴图后预览同步。
        # 注意：缓存必须放在模块级字典里，不能存节点属性——
        # draw 回调上下文中 Blender 禁止写 ID 数据块（AttributeError）。
        if abs(_preview_mtime_cache.get(preview_path, -1.0) - mtime) > 1e-6:
            try:
                image.reload()
            except Exception:
                pass
            _preview_mtime_cache[preview_path] = mtime
        try:
            image.preview_ensure()
        except Exception:
            return None
        return image

    def _refresh_label(self):
        if self.texture_hash:
            self.label = f"贴图 {self.texture_hash}"
        else:
            self.label = "贴图"

    def get_resource_name(self) -> str:
        name = self.resource_name.strip()
        return normalize_texture_resource_name(name) if name else default_texture_resource_name(self.texture_hash, self.mark_name)

    def get_texture_filename(self) -> str:
        filename = self.texture_filename.strip()
        return normalize_texture_filename(filename) if filename else _get_default_texture_filename(
            self.texture_hash, self.mark_name
        )

    def init(self, context):
        self.width = 220
        self._refresh_label()
        # Hash 出口：当成“物体”用，可连 Group/SwitchKey/Output
        self.outputs.new('SSMTSocketObject', "Hash")
        # Slot 出口：连到 Object Info 的 texture slot 输入
        self.outputs.new('SSMTSocketTexture', "Slot")

    def draw_buttons(self, context, layout):
        col = layout.column(align=True)
        col.prop(self, "texture_hash", text=iface_("Hash"))
        col.prop(self, "mark_name", text=iface_("Mark Name"))
        col.prop(self, "resource_name", text=iface_("Resource Name"))
        col.prop(self, "texture_filename", text=iface_("文件名"))
        col.prop(self, "texture_filepath", text=iface_("文件路径"))
        col.prop(self, "texture_format", text=iface_("目标格式"))
        if self.texture_format == 'CUSTOM':
            col.prop(self, "texture_format_custom", text=iface_("自定义格式"))

        if not self.texture_hash:
            layout.label(text=iface_("Hash 为空时无法生成配置"), icon='ERROR')

        # 预览绘制必须容错：draw 上下文里任何异常都不应破坏节点本身
        try:
            preview_image = self._get_preview_image()
            if preview_image is not None and getattr(preview_image, "preview", None):
                layout.template_icon(icon_value=preview_image.preview.icon_id, scale=6.0)
        except Exception as e:
            print(f"[TexturePreview] 预览绘制失败: {e}")


classes = (
    SSMTNode_Texture,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
