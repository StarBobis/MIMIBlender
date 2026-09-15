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

from ..i18n.i18n import tr


_SCENE_PROPS = (
    "mimi_smc_ob_data",
    "mimi_smc_ob_data_id",
    "mimi_smc_list_id",
    "mimi_smc_size",
    "mimi_smc_size_width",
    "mimi_smc_size_height",
    "mimi_smc_crop",
    "mimi_smc_pixel_art",
    "mimi_smc_diffuse_size",
    "mimi_smc_gaps",
    "mimi_smc_save_path",
    "mimi_smc_packer_type",
    "mimi_smc_include_extra_textures",
    "mimi_smc_uniform_size",
    "mimi_smc_uniform_size_value",
    "mimi_smc_image_format",
    "mimi_smc_dds_format",
    "mimi_smc_dds_mipmaps",
    "mimi_smc_texconv_path",
)

_MATERIAL_PROPS = (
    "mimi_root_mat",
    "mimi_smc_diffuse",
    "mimi_smc_size",
    "mimi_smc_size_width",
    "mimi_smc_size_height",
    "mimi_smc_alpha_mode",
    "mimi_smc_alpha_image",
    "mimi_smc_alpha_channel",
)

_DEFAULT_ATLAS_SIZE = "QUAD"
_DEFAULT_DIMENSION = 4096
_MIN_DIMENSION = 8
_MAX_DIMENSION = 8192
_DEFAULT_IMAGE_FORMAT = "PNG"


def _get_image_format_items(self, context):
    # Dynamic items callback so the dropdown entries follow the UI language.
    # The numeric values keep the original ordering stable.
    return [
        ("PNG", "PNG", tr("Portable Network Graphics format, lossless, supports Alpha, best general compatibility"), 0),
        ("TGA", "TGA", tr("Truevision Targa format, lossless, supports Alpha, widely supported by game engines"), 1),
        ("TIFF", "TIFF", tr("Tagged Image File format, lossless, supports Alpha, good for archiving"), 2),
        ("BMP", "BMP", tr("Windows Bitmap format, lossless, supports Alpha, but large in file size"), 3),
        ("DDS", "DDS (texconv)", tr("DirectX Surface format via texconv.exe with explicit DXGI format control, for game modding pipelines"), 4),
    ]


def _get_dds_format_items(self, context):
    # Dynamic items callback so the dropdown entries follow the UI language.
    return [
        ("R8G8B8A8_UNORM_SRGB", "R8G8B8A8_UNORM_SRGB", tr("Uncompressed 8-bit RGBA with sRGB tag; the default for WWMI/3DMigoto diffuse textures"), 0),
        ("R8G8B8A8_UNORM", "R8G8B8A8_UNORM", tr("Uncompressed 8-bit RGBA without sRGB tag; for data textures"), 1),
        ("BC7_UNORM_SRGB", "BC7_UNORM_SRGB", tr("BC7 block compression with sRGB tag; high quality, smaller files"), 2),
        ("BC7_UNORM", "BC7_UNORM", tr("BC7 block compression without sRGB tag; for data textures"), 3),
        ("BC3_UNORM_SRGB", "BC3_UNORM_SRGB", tr("BC3/DXT5 block compression with sRGB tag; broad engine compatibility"), 4),
        ("BC3_UNORM", "BC3_UNORM", tr("BC3/DXT5 block compression without sRGB tag; for data textures"), 5),
    ]


def _get_atlas_size_items(self, context):
    # Dynamic items callback so the dropdown entries follow the UI language.
    return [
        ("PO2", tr("Power of 2"), tr("Combined image size is a power of 2 (e.g. 1024, 2048, 4096)")),
        ("QUAD", tr("Square"), tr("Combined image has equal width and height")),
        ("AUTO", tr("Auto"), tr("Combined image uses the smallest size")),
        ("CUST", tr("Custom"), tr("Scale inner textures proportionally to the specified size")),
        ("STRICTCUST", tr("Strict Custom"), tr("Strictly use the specified width and height without scaling inner textures")),
    ]


_DEFAULT_PACKER_TYPE = "BINARY_TREE"


def _get_alpha_mode_items(self, context):
    # Dynamic items callback so the dropdown entries follow the UI language.
    return [
        (
            "AUTO",
            tr("Auto (Follow Node Links)"),
            tr("Use the image linked to the Principled BSDF Alpha input when present; otherwise keep the base texture's own alpha"),
        ),
        (
            "EMBEDDED",
            tr("Embedded (Base Texture)"),
            tr("Always keep the base texture's own alpha channel, ignoring any node-linked alpha"),
        ),
        (
            "SEPARATE",
            tr("Separate Image"),
            tr("Replace the alpha channel with a channel of the chosen image"),
        ),
        (
            "MULTIPLY",
            tr("Multiply with Image"),
            tr("Multiply the base texture's alpha with a channel of the chosen image (stacked masks)"),
        ),
        (
            "OPAQUE",
            tr("Opaque"),
            tr("Force the alpha channel to fully opaque"),
        ),
    ]


def _get_alpha_channel_items(self, context):
    # Dynamic items callback so the dropdown entries follow the UI language.
    return [
        ("A", tr("Alpha"), tr("Use the image's alpha channel")),
        ("R", tr("Red"), tr("Use the image's red channel")),
        ("G", tr("Green"), tr("Use the image's green channel")),
        ("B", tr("Blue"), tr("Use the image's blue channel")),
        (
            "LUM",
            tr("Luminance"),
            tr("Use the image's Rec.709 luminance computed in linear space"),
        ),
    ]


def _get_packer_type_items(self, context):
    # Dynamic items callback so the dropdown entries follow the UI language.
    return [
        (
            "MAX_RECTS",
            tr("Max Rects"),
            tr("Uses the Max Rects bin packing algorithm - balanced speed and efficiency")),
        (
            "BINARY_TREE",
            tr("Binary Tree"),
            tr("Uses the binary tree bin packing algorithm - simple but less efficient")),
        (
            "RECT_PACK2D",
            tr("RectPack2D"),
            tr("Uses the RectPack2D algorithm - best for dense packing")),
    ]


class MIMICombineListEntry(bpy.types.PropertyGroup):
    """Property group representing an object-material mapping for a combination.

    This class defines the data structure for entries in the material combination list.
    Each entry can represent an object, material, or visual separator, and contains
    properties for tracking its selection state and grouping information.
    """

    ob: PointerProperty(
        name=tr("Object"),
        type=bpy.types.Object,
        description=tr("Source object containing the material"),
    )

    ob_id: IntProperty(
        name=tr("Object ID"),
        default=0,
        description=tr("Unique identifier for grouping materials under their parent object"),
    )

    mat: PointerProperty(
        name=tr("Material"),
        type=bpy.types.Material,
        description=tr("Material instance to be merged"),
    )

    layer: IntProperty(
        name=tr("Layer Group"),
        min=1,
        max=99,
        step=1,
        default=1,
        description=tr("Materials with the same layer number are merged into the same atlas\n"
        "so that multiple materials can share one atlas"),
    )

    used: BoolProperty(
        name=tr("Include"),
        default=True,
        description=tr("Include this element in atlas generation"),
    )

    type: IntProperty(
        name=tr("Entry Type"),
        default=0,
        description=tr("Type of the list entry (object, material, or separator)"),
    )




def _register_scene_properties() -> None:
    """Register all scene-level custom properties.

    This function adds properties to the Scene class for storing
    object data, atlas configuration, and output settings.
    """
    bpy.types.Scene.mimi_smc_ob_data = CollectionProperty(type=MIMICombineListEntry)
    bpy.types.Scene.mimi_smc_ob_data_id = IntProperty(default=0)
    bpy.types.Scene.mimi_smc_list_id = IntProperty(default=0)

    bpy.types.Scene.mimi_smc_size = EnumProperty(
        name=tr("Atlas Size"),
        items=_get_atlas_size_items,
        # Dynamic items only allow integer (0-based) defaults: 1 == "QUAD".
        default=1,
        description=tr("Size strategy of the texture atlas"),
    )

    bpy.types.Scene.mimi_smc_packer_type = EnumProperty(
        name=tr("Packing Algorithm"),
        items=_get_packer_type_items,
        # Dynamic items only allow integer (0-based) defaults: 1 == "BINARY_TREE".
        default=1,
        description=tr("Algorithm used to pack textures into the atlas"),
    )

    dimension_args = {
        "min": _MIN_DIMENSION,
        "max": _MAX_DIMENSION,
        "description": tr("Maximum pixel size of the texture"),
    }
    bpy.types.Scene.mimi_smc_size_width = IntProperty(
        name=tr("Width"), default=_DEFAULT_DIMENSION, **dimension_args
    )
    bpy.types.Scene.mimi_smc_size_height = IntProperty(
        name=tr("Height"), default=_DEFAULT_DIMENSION, **dimension_args
    )

    bpy.types.Scene.mimi_smc_crop = BoolProperty(
        name=tr("Crop to UV Bounds"),
        default=True,
        description=tr("Removes redundant areas"),
    )

    bpy.types.Scene.mimi_smc_pixel_art = BoolProperty(
        name=tr("Disable Anti-Aliased Scaling"),
        default=False,
        description=tr("Suitable for textures such as pixel art"),
    )

    bpy.types.Scene.mimi_smc_diffuse_size = IntProperty(
        name=tr("Solid Color Texture Size"),
        min=8,
        max=256,
        default=32,
        description=tr("Base texture size of solid-color materials when batching"),
    )

    bpy.types.Scene.mimi_smc_gaps = IntProperty(
        name=tr("Spacing"),
        min=0,
        max=32,
        default=0,
        options={"HIDDEN"},
        description=tr("Spacing between elements in the atlas (pixels)"),
    )

    bpy.types.Scene.mimi_smc_include_extra_textures = BoolProperty(
        name=tr("Atlas PBR Textures"),
        default=False,
        description=tr("Also generate atlases for metallic, roughness, specular, normal, and emission textures"),
    )

    bpy.types.Scene.mimi_smc_uniform_size = BoolProperty(
        name=tr("Uniform Texture Size"),
        default=True,
        description=tr("Force all small textures to be scaled to the same size before packing (may be enlarged or shrunk)"),
    )

    bpy.types.Scene.mimi_smc_uniform_size_value = IntProperty(
        name=tr("Uniform Size"),
        min=8,
        max=8192,
        default=1024,
        description=tr("Pixel size to which all small textures are uniformly scaled (width = height)"),
    )

    bpy.types.Scene.mimi_smc_image_format = EnumProperty(
        name=tr("Output Format"),
        items=_get_image_format_items,
        # Dynamic items only allow integer (0-based) defaults; the first item
        # ("PNG") is the intended default, so the argument is omitted.
        description=tr("Format of the atlas output image; PNG supports the Alpha channel"),
    )

    bpy.types.Scene.mimi_smc_dds_format = EnumProperty(
        name=tr("DDS Pixel Format"),
        items=_get_dds_format_items,
        description=tr("DXGI format written by texconv.exe for DDS output"),
    )

    bpy.types.Scene.mimi_smc_dds_mipmaps = BoolProperty(
        name=tr("Generate Mipmaps"),
        default=True,
        description=tr("Generate the full mipmap chain for DDS output"),
    )

    bpy.types.Scene.mimi_smc_texconv_path = StringProperty(
        name=tr("texconv.exe Path"),
        default="",
        subtype="FILE_PATH",
        description=tr("Optional path to a custom texconv.exe; leave empty to use the bundled copy or the TEXCONV_PATH environment variable"),
    )

    bpy.types.Scene.mimi_smc_save_path = StringProperty(
        name=tr("Save Location"),
        default="",
        subtype="DIR_PATH",
        description=tr("Output directory for the generated atlases"),
    )


def _register_material_properties() -> None:
    """Register all material-level custom properties.

    This function adds properties to the Material class for storing
    atlas-specific settings and references to original materials.
    """
    bpy.types.Material.mimi_root_mat = PointerProperty(
        name=tr("Base Material"),
        type=bpy.types.Material,
        description=tr("Reference to the original material, used to track the material's source"),
    )

    bpy.types.Material.mimi_smc_diffuse = BoolProperty(
        name=tr("Blend Diffuse Color"),
        default=True,
        description=tr("Blend the diffuse color with the texture"),
    )

    bpy.types.Material.mimi_smc_size = BoolProperty(
        name=tr("Custom Size"),
        default=False,
        description=tr("Enable a custom texture size"),
    )

    dimension_args = {
        "min": _MIN_DIMENSION,
        "max": _MAX_DIMENSION // 2,
        "description": tr("Maximum pixel size of the texture"),
    }
    bpy.types.Material.mimi_smc_size_width = IntProperty(
        name=tr("Width"), default=2048, **dimension_args
    )
    bpy.types.Material.mimi_smc_size_height = IntProperty(
        name=tr("Height"), default=2048, **dimension_args
    )

    bpy.types.Material.mimi_smc_alpha_mode = EnumProperty(
        name=tr("Alpha Source"),
        items=_get_alpha_mode_items,
        # Dynamic items only allow integer (0-based) defaults: 0 == "AUTO".
        default=0,
        description=tr("Where the merged atlas alpha channel comes from"),
    )

    bpy.types.Material.mimi_smc_alpha_image = PointerProperty(
        name=tr("Alpha Image"),
        type=bpy.types.Image,
        description=tr("Image providing the alpha channel in Separate/Multiply mode"),
    )

    bpy.types.Material.mimi_smc_alpha_channel = EnumProperty(
        name=tr("Alpha Channel"),
        items=_get_alpha_channel_items,
        # Dynamic items only allow integer (0-based) defaults: 0 == "A".
        default=0,
        description=tr("Which channel of the alpha image is used as the alpha value"),
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
