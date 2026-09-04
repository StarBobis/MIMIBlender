"""Type extension and property registration for the Material Combiner addon.

This module extends Blender's type system with custom property groups,
preferences, and runtime properties needed by the Material Combiner.
It provides centralized registration and unregistration of all custom
properties to ensure proper cleanup.
"""

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)


_SCENE_PROPS = (
    "smc_ob_data",
    "smc_ob_data_id",
    "smc_list_id",
    "smc_size",
    "smc_size_width",
    "smc_size_height",
    "smc_crop",
    "smc_pixel_art",
    "smc_diffuse_size",
    "smc_gaps",
    "smc_save_path",
    "smc_packer_type",
    "smc_include_extra_textures",
    "smc_uniform_size",
    "smc_uniform_size_value",
    "smc_image_format",
)

_MATERIAL_PROPS = (
    "root_mat",
    "smc_diffuse",
    "smc_size",
    "smc_size_width",
    "smc_size_height",
)

_DEFAULT_ATLAS_SIZE = "QUAD"
_DEFAULT_DIMENSION = 4096
_MIN_DIMENSION = 8
_MAX_DIMENSION = 8192
_DEFAULT_IMAGE_FORMAT = "PNG"

_IMAGE_FORMAT_ITEMS = [
    ("PNG", "PNG", "便携网络图形格式，无损，支持 Alpha，通用性最佳", 0),
    ("TGA", "TGA", "Truevision Targa 格式，无损，支持 Alpha，游戏引擎广泛支持", 1),
    ("TIFF", "TIFF", "标签图像文件格式，无损，支持 Alpha，适合存档", 2),
    ("BMP", "BMP", "Windows 位图格式，无损，支持 Alpha，但文件体积较大", 3),
]

_ATLAS_SIZE_ITEMS = [
    ("PO2", "2的幂", "合并后的图片尺寸取2的幂（如 1024、2048、4096）"),
    ("QUAD", "正方形", "合并后的图片宽度和高度相等"),
    ("AUTO", "自动", "合并后的图片取最小尺寸"),
    ("CUST", "自定义", "按指定的尺寸等比缩放内部贴图"),
    ("STRICTCUST", "严格自定义", "严格使用指定的宽高，不缩放内部贴图"),
]

_DEFAULT_PACKER_TYPE = "BINARY_TREE"

_PACKER_TYPE_ITEMS = [
    (
        "MAX_RECTS",
        "最大矩形",
        "使用 Max Rects 装箱算法 - 速度和效率均衡"),
    (
        "BINARY_TREE",
        "二叉树",
        "使用二叉树装箱算法 - 简单但效率较低"),
    (
        "RECT_PACK2D",
        "RectPack2D",
        "使用 RectPack2D 算法 - 密集排列效果最佳"),
]


class CombineListEntry(bpy.types.PropertyGroup):
    """Property group representing an object-material mapping for a combination.

    This class defines the data structure for entries in the material combination list.
    Each entry can represent an object, material, or visual separator, and contains
    properties for tracking its selection state and grouping information.
    """

    ob: PointerProperty(
        name="物体",
        type=bpy.types.Object,
        description="包含材质的源物体",
    )

    ob_id: IntProperty(
        name="物体ID",
        default=0,
        description="用于将材质分组到其父物体下的唯一标识符",
    )

    mat: PointerProperty(
        name="材质",
        type=bpy.types.Material,
        description="要合并的材质实例",
    )

    layer: IntProperty(
        name="图层组",
        min=1,
        max=99,
        step=1,
        default=1,
        description="相同图层编号的材质会被合并到同一张图集中\n"
        "用于创建多个材质关联到同一图集",
    )

    used: BoolProperty(
        name="包含",
        default=True,
        description="将此元素包含在图集生成中",
    )

    type: IntProperty(
        name="条目类型",
        default=0,
        description="列表条目的类型（物体、材质或分隔符）",
    )




def _register_scene_properties() -> None:
    """Register all scene-level custom properties.

    This function adds properties to the Scene class for storing
    object data, atlas configuration, and output settings.
    """
    bpy.types.Scene.smc_ob_data = CollectionProperty(type=CombineListEntry)
    bpy.types.Scene.smc_ob_data_id = IntProperty(default=0)
    bpy.types.Scene.smc_list_id = IntProperty(default=0)

    bpy.types.Scene.smc_size = EnumProperty(
        name="图集尺寸",
        items=_ATLAS_SIZE_ITEMS,
        default=_DEFAULT_ATLAS_SIZE,
        description="纹理图集的尺寸策略",
    )

    bpy.types.Scene.smc_packer_type = EnumProperty(
        name="打包算法",
        items=_PACKER_TYPE_ITEMS,
        default=_DEFAULT_PACKER_TYPE,
        description="将纹理打包到图集中使用的算法",
    )

    dimension_args = {
        "min": _MIN_DIMENSION,
        "max": _MAX_DIMENSION,
        "description": "纹理的最大像素尺寸",
    }
    bpy.types.Scene.smc_size_width = IntProperty(
        name="宽度", default=_DEFAULT_DIMENSION, **dimension_args
    )
    bpy.types.Scene.smc_size_height = IntProperty(
        name="高度", default=_DEFAULT_DIMENSION, **dimension_args
    )

    bpy.types.Scene.smc_crop = BoolProperty(
        name="根据UV边界裁剪",
        default=True,
        description="可去掉多余区域",
    )

    bpy.types.Scene.smc_pixel_art = BoolProperty(
        name="禁用抗锯齿缩放",
        default=False,
        description="适合像素画之类的贴图",
    )

    bpy.types.Scene.smc_diffuse_size = IntProperty(
        name="纯色纹理尺寸",
        min=8,
        max=256,
        default=32,
        description="纯色材质在合批时的基础纹理大小",
    )

    bpy.types.Scene.smc_gaps = IntProperty(
        name="间距",
        min=0,
        max=32,
        default=0,
        options={"HIDDEN"},
        description="图集中元素之间的间距（像素）",
    )

    bpy.types.Scene.smc_include_extra_textures = BoolProperty(
        name="图集PBR贴图",
        default=False,
        description="同时生成金属度、粗糙度、高光、法线和自发光贴图的图集",
    )

    bpy.types.Scene.smc_uniform_size = BoolProperty(
        name="统一贴图尺寸",
        default=True,
        description="强制所有小贴图缩放到相同尺寸后再打包（可放大或缩小）",
    )

    bpy.types.Scene.smc_uniform_size_value = IntProperty(
        name="统一尺寸",
        min=8,
        max=8192,
        default=1024,
        description="所有小贴图统一缩放到的像素尺寸（宽=高）",
    )

    bpy.types.Scene.smc_image_format = EnumProperty(
        name="输出格式",
        items=_IMAGE_FORMAT_ITEMS,
        default=_DEFAULT_IMAGE_FORMAT,
        description="图集输出图片的格式，PNG 支持 Alpha 通道",
    )

    bpy.types.Scene.smc_save_path = StringProperty(
        name="保存位置",
        default="",
        subtype="DIR_PATH",
        description="生成图集的输出目录",
    )


def _register_material_properties() -> None:
    """Register all material-level custom properties.

    This function adds properties to the Material class for storing
    atlas-specific settings and references to original materials.
    """
    bpy.types.Material.root_mat = PointerProperty(
        name="基础材质",
        type=bpy.types.Material,
        description="原始材质的引用，用于追踪材质来源",
    )

    bpy.types.Material.smc_diffuse = BoolProperty(
        name="混合漫射颜色",
        default=True,
        description="将漫射颜色与纹理混合",
    )

    bpy.types.Material.smc_size = BoolProperty(
        name="自定义尺寸",
        default=False,
        description="启用自定义纹理尺寸",
    )

    dimension_args = {
        "min": _MIN_DIMENSION,
        "max": _MAX_DIMENSION // 2,
        "description": "纹理的最大像素尺寸",
    }
    bpy.types.Material.smc_size_width = IntProperty(
        name="宽度", default=2048, **dimension_args
    )
    bpy.types.Material.smc_size_height = IntProperty(
        name="高度", default=2048, **dimension_args
    )


def register() -> None:
    """Register all custom properties and types.

    This function initializes all custom properties on Scene and Material
    objects required by the Material Combiner addon. Called during addon
    registration.
    """
    _register_scene_properties()
    _register_material_properties()


def unregister() -> None:
    """Unregister all custom properties and types.

    This function removes all custom properties added to Scene and Material
    objects by the Material Combiner addon. Called during addon unregistration
    to prevent property leaks and ensure clean uninstallation.
    """
    for prop in _SCENE_PROPS:
        if hasattr(bpy.types.Scene, prop):
            delattr(bpy.types.Scene, prop)

    for prop in _MATERIAL_PROPS:
        if hasattr(bpy.types.Material, prop):
            delattr(bpy.types.Material, prop)
