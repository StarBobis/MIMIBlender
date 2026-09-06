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
    ("PNG", "PNG", "Portable Network Graphics format, lossless, supports Alpha, best general compatibility", 0),
    ("TGA", "TGA", "Truevision Targa format, lossless, supports Alpha, widely supported by game engines", 1),
    ("TIFF", "TIFF", "Tagged Image File format, lossless, supports Alpha, good for archiving", 2),
    ("BMP", "BMP", "Windows Bitmap format, lossless, supports Alpha, but large in file size", 3),
]

_ATLAS_SIZE_ITEMS = [
    ("PO2", "Power of 2", "Combined image size is a power of 2 (e.g. 1024, 2048, 4096)"),
    ("QUAD", "Square", "Combined image has equal width and height"),
    ("AUTO", "Auto", "Combined image uses the smallest size"),
    ("CUST", "Custom", "Scale inner textures proportionally to the specified size"),
    ("STRICTCUST", "Strict Custom", "Strictly use the specified width and height without scaling inner textures"),
]

_DEFAULT_PACKER_TYPE = "BINARY_TREE"

_PACKER_TYPE_ITEMS = [
    (
        "MAX_RECTS",
        "Max Rects",
        "Uses the Max Rects bin packing algorithm - balanced speed and efficiency"),
    (
        "BINARY_TREE",
        "Binary Tree",
        "Uses the binary tree bin packing algorithm - simple but less efficient"),
    (
        "RECT_PACK2D",
        "RectPack2D",
        "Uses the RectPack2D algorithm - best for dense packing"),
]


class CombineListEntry(bpy.types.PropertyGroup):
    """Property group representing an object-material mapping for a combination.

    This class defines the data structure for entries in the material combination list.
    Each entry can represent an object, material, or visual separator, and contains
    properties for tracking its selection state and grouping information.
    """

    ob: PointerProperty(
        name="Object",
        type=bpy.types.Object,
        description="Source object containing the material",
    )

    ob_id: IntProperty(
        name="Object ID",
        default=0,
        description="Unique identifier for grouping materials under their parent object",
    )

    mat: PointerProperty(
        name="Material",
        type=bpy.types.Material,
        description="Material instance to be merged",
    )

    layer: IntProperty(
        name="Layer Group",
        min=1,
        max=99,
        step=1,
        default=1,
        description="Materials with the same layer number are merged into the same atlas\n"
        "so that multiple materials can share one atlas",
    )

    used: BoolProperty(
        name="Include",
        default=True,
        description="Include this element in atlas generation",
    )

    type: IntProperty(
        name="Entry Type",
        default=0,
        description="Type of the list entry (object, material, or separator)",
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
        name="Atlas Size",
        items=_ATLAS_SIZE_ITEMS,
        default=_DEFAULT_ATLAS_SIZE,
        description="Size strategy of the texture atlas",
    )

    bpy.types.Scene.smc_packer_type = EnumProperty(
        name="Packing Algorithm",
        items=_PACKER_TYPE_ITEMS,
        default=_DEFAULT_PACKER_TYPE,
        description="Algorithm used to pack textures into the atlas",
    )

    dimension_args = {
        "min": _MIN_DIMENSION,
        "max": _MAX_DIMENSION,
        "description": "Maximum pixel size of the texture",
    }
    bpy.types.Scene.smc_size_width = IntProperty(
        name="Width", default=_DEFAULT_DIMENSION, **dimension_args
    )
    bpy.types.Scene.smc_size_height = IntProperty(
        name="Height", default=_DEFAULT_DIMENSION, **dimension_args
    )

    bpy.types.Scene.smc_crop = BoolProperty(
        name="Crop to UV Bounds",
        default=True,
        description="Removes redundant areas",
    )

    bpy.types.Scene.smc_pixel_art = BoolProperty(
        name="Disable Anti-Aliased Scaling",
        default=False,
        description="Suitable for textures such as pixel art",
    )

    bpy.types.Scene.smc_diffuse_size = IntProperty(
        name="Solid Color Texture Size",
        min=8,
        max=256,
        default=32,
        description="Base texture size of solid-color materials when batching",
    )

    bpy.types.Scene.smc_gaps = IntProperty(
        name="Spacing",
        min=0,
        max=32,
        default=0,
        options={"HIDDEN"},
        description="Spacing between elements in the atlas (pixels)",
    )

    bpy.types.Scene.smc_include_extra_textures = BoolProperty(
        name="Atlas PBR Textures",
        default=False,
        description="Also generate atlases for metallic, roughness, specular, normal, and emission textures",
    )

    bpy.types.Scene.smc_uniform_size = BoolProperty(
        name="Uniform Texture Size",
        default=True,
        description="Force all small textures to be scaled to the same size before packing (may be enlarged or shrunk)",
    )

    bpy.types.Scene.smc_uniform_size_value = IntProperty(
        name="Uniform Size",
        min=8,
        max=8192,
        default=1024,
        description="Pixel size to which all small textures are uniformly scaled (width = height)",
    )

    bpy.types.Scene.smc_image_format = EnumProperty(
        name="Output Format",
        items=_IMAGE_FORMAT_ITEMS,
        default=_DEFAULT_IMAGE_FORMAT,
        description="Format of the atlas output image; PNG supports the Alpha channel",
    )

    bpy.types.Scene.smc_save_path = StringProperty(
        name="Save Location",
        default="",
        subtype="DIR_PATH",
        description="Output directory for the generated atlases",
    )


def _register_material_properties() -> None:
    """Register all material-level custom properties.

    This function adds properties to the Material class for storing
    atlas-specific settings and references to original materials.
    """
    bpy.types.Material.root_mat = PointerProperty(
        name="Base Material",
        type=bpy.types.Material,
        description="Reference to the original material, used to track the material's source",
    )

    bpy.types.Material.smc_diffuse = BoolProperty(
        name="Blend Diffuse Color",
        default=True,
        description="Blend the diffuse color with the texture",
    )

    bpy.types.Material.smc_size = BoolProperty(
        name="Custom Size",
        default=False,
        description="Enable a custom texture size",
    )

    dimension_args = {
        "min": _MIN_DIMENSION,
        "max": _MAX_DIMENSION // 2,
        "description": "Maximum pixel size of the texture",
    }
    bpy.types.Material.smc_size_width = IntProperty(
        name="Width", default=2048, **dimension_args
    )
    bpy.types.Material.smc_size_height = IntProperty(
        name="Height", default=2048, **dimension_args
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
