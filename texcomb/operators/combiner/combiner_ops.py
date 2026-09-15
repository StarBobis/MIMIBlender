"""Core operations for combining materials and textures.

This module implements the core functionality for the Material Combiner addon,
including UV mapping analysis, texture extraction, atlas generation, and
material assignment. It handles the complex process of creating optimized
texture atlases from multiple materials while preserving texture quality
and proper UV mapping.

Typical usage example:
    # Running the operator directly (requires directory parameter)
    bpy.ops.mimi.combiner(directory=r'/path/to/save/directory')

Note: When running the operator directly (not from the addon's UI),
the `directory` parameter is required to specify where the atlas image will be saved.
"""

import itertools
import math
import os
import random
import re
from collections import OrderedDict, defaultdict
from itertools import chain
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union, cast

import bpy
import numpy as np

from ...globs import CombineListTypes
from ....i18n.i18n import tr
from ...blender import planes as plane_builder
from ...core import atlas as core_atlas
from ...core import export as core_export
from ...core import layout as core_layout
from ...type_annotations import (
    CombMats,
    MatsUV,
    ObMats,
    Scene,
    SMCObData,
    SMCObDataItem,
    Structure,
    StructureItem,
)
from ...utils.images import get_image_pack_issue, get_packed_file
from ...utils.materials import (
    get_alpha_texture,
    get_alpha_texture_issue,
    get_diffuse,
    get_gfx_textures,
    get_image_from_material,
    sort_materials,
)
from ...utils.objects import align_uv, get_polys, get_uv

Image = None
ImageChops = None
ImageFile = None
ImageType = None
resampling = None


def initialize_pillow() -> bool:
    """Initialize cached Pillow module globals used by combiner helpers."""
    global Image, ImageChops, ImageFile, ImageType, resampling

    try:
        from PIL import Image as pil_image
        from PIL import ImageChops as pil_image_chops
        from PIL import ImageFile as pil_image_file

        Image = pil_image
        ImageChops = pil_image_chops
        ImageFile = pil_image_file
        ImageType = Image.Image

        Image.MAX_IMAGE_PIXELS = None
        try:
            resampling = Image.LANCZOS
        except AttributeError:
            resampling = Image.ANTIALIAS

        if ImageFile:
            ImageFile.LOAD_TRUNCATED_IMAGES = True
        return True
    except ImportError:
        Image = None
        ImageChops = None
        ImageFile = None
        ImageType = None
        resampling = None
        return False


# NOTE: initialize_pillow() is intentionally NOT called at import time. It
# remains available for the "Install Pillow" operator's availability check;
# the actual decoding/encoding paths import Pillow lazily through
# texcomb.core.decode / texcomb.core.export.

atlas_prefix = "Atlas_"
atlas_texture_prefix = "texture_atlas_"
atlas_material_prefix = "material_atlas_"


def validate_ob_data(
    data: Sequence[bpy.types.PropertyGroup],
) -> Optional[Dict[str, Any]]:
    """Validates that the input data contains at least one object.

    Args:
        data: Collection of property group items.

    Returns:
        None if validation passes, otherwise a dictionary with status.
    """
    return (
        None
        if any(item.type == CombineListTypes.OBJECT for item in data)
        else {"CANCELLED"}
    )


def set_ob_mode(scn: Scene, data: SMCObData) -> None:
    """Set active object to Object mode.

    Args:
        scn: Current scene or view layer.
        data: Dictionary of object data items.
    """
    ob = next(
        (item.ob for item in data if item.type == CombineListTypes.OBJECT), None
    )
    if ob:
        scn.objects.active = ob
        bpy.ops.object.mode_set(mode="OBJECT")


def get_data(data: Sequence[bpy.types.PropertyGroup]) -> SMCObData:
    """Extract material data from property group items.

    Builds a dictionary mapping object names to their materials and respective layers.

    Args:
        data: Collection of property group items.

    Returns:
        Dictionary mapping object names to their materials with layer numbers.
    """
    mats = defaultdict(dict)
    for item in data:
        if item.type == CombineListTypes.MATERIAL and item.used:
            mats[item.ob.name][item.mat] = item.layer
    return mats


def get_mats_uv(scn: Scene, data: SMCObData) -> MatsUV:
    """Get UV coordinates for all selected materials.

    Extracts and aligns UV coordinates from all polygons using the selected
    materials in each object.

    Args:
        scn: Current scene.
        data: Dictionary mapping object names to materials.

    Returns:
        Dictionary mapping object names to materials with UV coordinates.
    """
    mats_uv = defaultdict(lambda: defaultdict(list))
    for ob_n, item in data.items():
        ob = scn.objects[ob_n]
        for idx, polys in get_polys(ob).items():
            mat = ob.data.materials[idx]
            if mat not in item:
                continue
            for poly in polys:
                mats_uv[ob_n][mat].extend(align_uv(get_uv(ob, poly)))
    return mats_uv


def clear_empty_mats(scn: Scene, data: SMCObData, mats_uv: MatsUV) -> None:
    """Remove materials without valid UV coordinates.

    Args:
        scn: Current scene.
        data: Dictionary mapping object names to materials.
        mats_uv: Dictionary mapping object names to materials with UV coordinates.
    """
    for ob_n, item in data.items():
        ob = scn.objects[ob_n]
        for mat in item:
            if mat not in mats_uv[ob_n]:
                _delete_material(ob, mat.name)


def _delete_material(ob: bpy.types.Object, name: str) -> None:
    """Remove a material from an object.

    Args:
        ob: Object to remove material from.
        name: Name of the material to remove.
    """
    if ob.type == "MESH":
        mat_idx = ob.data.materials.find(name)
        if mat_idx >= 0:
            ob.data.materials.pop(index=mat_idx)


def get_duplicates(mats_uv: MatsUV) -> None:
    """Identify and mark duplicate materials.

    Finds visually identical materials and marks duplicates by setting
    their mimi_root_mat property to the first matching material.

    Args:
        mats_uv: Dictionary mapping object names to materials with UV coordinates.
    """
    mat_list = list(chain.from_iterable(mats_uv.values()))
    sorted_mat_list = sort_materials(mat_list)
    for mats in sorted_mat_list:
        mimi_root_mat = mats[0]
        for mat in mats[1:]:
            mat.mimi_root_mat = mimi_root_mat


def get_structure(scn: Scene, data: SMCObData, mats_uv: MatsUV) -> Structure:
    """Build the structure for atlas generation.

    Creates a dictionary mapping materials to their metadata, including
    graphics info, duplicate materials, objects that use them, and UV coordinates.

    Args:
        scn: Current scene.
        data: Dictionary mapping object names to materials.
        mats_uv: Dictionary mapping object names to materials with UV coordinates.

    Returns:
        Dictionary mapping materials to their metadata.
    """
    structure = defaultdict(
        lambda: {
            "gfx": {
                "img_or_color": None,
                "size": (),
                "uv_size": (),
                "metallic": None,
                "roughness": None,
                "specular": None,
                "normal_map": None,
                "emission": None,
                "alpha": None,
                "alpha_diagnostic": "",
                "diagnostic": "",
            },
            "dup": [],
            "ob": [],
            "uv": [],
        }
    )

    for ob_n, item in data.items():
        ob = scn.objects[ob_n]
        for mat in item:
            if mat.name not in ob.data.materials:
                continue
            mimi_root_mat = mat.mimi_root_mat or mat
            if (
                mat.mimi_root_mat
                and mat.mimi_root_mat != mat
                and mat.name not in structure[mimi_root_mat]["dup"]
            ):
                structure[mimi_root_mat]["dup"].append(mat.name)
            if ob.name not in structure[mimi_root_mat]["ob"]:
                structure[mimi_root_mat]["ob"].append(ob.name)
            structure[mimi_root_mat]["uv"].extend(mats_uv[ob_n][mat])

            if scn.mimi_smc_include_extra_textures:
                _set_extra_maps(structure[mimi_root_mat], mimi_root_mat)

    return structure


def get_size(scn: Scene, data: Structure) -> Dict:
    """Calculate sizes for all material textures.

    Determines the dimensions of each texture based on UV coordinates
    and the material's settings.

    Args:
        scn: Current scene.
        data: Dictionary mapping materials to their metadata.

    Returns:
        Sorted dictionary of materials with size information.
    """
    for mat, item in data.items():
        img = _get_image(mat)
        packed_file = get_packed_file(img)
        item["gfx"]["diagnostic"] = ""
        item["gfx"]["alpha_diagnostic"] = (
            get_alpha_texture_issue(mat, validate_pack=True) or ""
        )
        max_x, max_y = _get_max_uv_coordinates(item["uv"])
        # Clamp the UV repeat factor and degrade NaN to 1 (core helper).
        uv_repeat = core_layout.clamp_uv_repeat(max_x, max_y)
        if not scn.mimi_smc_crop:
            # Whole tiles only: round the repeat up before any sizing math.
            uv_repeat = tuple(math.ceil(x) for x in uv_repeat)
        item["gfx"]["uv_size"] = uv_repeat

        if packed_file:
            img_size = _get_image_size(mat, img)
            item["gfx"]["size"] = core_layout.entry_box_size(
                img_size,
                uv_repeat,
                scn.mimi_smc_gaps,
                crop=scn.mimi_smc_crop,
            )
        else:
            item["gfx"]["size"] = core_layout.entry_box_size(
                None,
                uv_repeat,
                scn.mimi_smc_gaps,
                solid_size=scn.mimi_smc_diffuse_size,
            )
            item["gfx"]["diagnostic"] = _get_texture_fallback_message(mat, img)

        if scn.mimi_smc_uniform_size:
            item["gfx"]["size"] = (scn.mimi_smc_uniform_size_value,) * 2

    return OrderedDict(sorted(data.items(), key=_size_sorting, reverse=True))


def collect_texture_diagnostics(data: Structure) -> List[str]:
    """Collect texture fallback diagnostics from prepared material data."""
    messages = []
    for mat, item in data.items():
        diagnostic = item["gfx"].get("diagnostic")
        if diagnostic:
            messages.append(diagnostic)
        alpha_diagnostic = item["gfx"].get("alpha_diagnostic")
        if alpha_diagnostic:
            messages.append(
                tr("Material '{name}' alpha was not included in the merge: {issue}").format(
                    name=mat.name, issue=alpha_diagnostic
                )
            )
    return messages


def _get_texture_fallback_message(
    mat: bpy.types.Material, img: Optional[bpy.types.Image]
) -> str:
    """Explain why a material will be treated as color-only."""
    if not img:
        return (
            tr("Material '{name}' has no main texture connected to the current output; "
               "it will be treated as a solid color material.")
        ).format(name=mat.name)

    pack_issue = get_image_pack_issue(img)
    if pack_issue:
        return tr("Material '{name}' texture '{image}' cannot be packed and will be treated as solid color: {issue}").format(
            name=mat.name, image=img.name, issue=pack_issue
        )

    return tr("Material '{name}' texture '{image}' failed to pack and will be treated as a solid color material.").format(
        name=mat.name, image=img.name
    )


def _size_sorting(item: Sequence[StructureItem]) -> Tuple[int, int, int]:
    """Key function for sorting materials by size, largest first.

    Python's sort is stable, so entries with equal sizes keep their
    insertion order and the packing stays deterministic.

    NOTE: a 4th key based on gfx["img_or_color"] used to be returned here,
    but that field is only populated later inside get_atlas(), so at sort
    time it was always None — dead code, removed (Phase 4 cleanup).
    """
    size_x, size_y = item[1]["gfx"]["size"]
    return max(size_x, size_y), size_x * size_y, size_x


def _get_image(mat: bpy.types.Material) -> Union[bpy.types.Image, None]:
    """Get the main image from a material's node tree.

    Args:
        mat: Material to extract image from.

    Returns:
        Image from the material or None if not found.
    """
    return get_image_from_material(mat)


def _get_image_size(
    mat: bpy.types.Material, img: bpy.types.Image
) -> Tuple[int, int]:
    """Get the size of an image, respecting material size constraints.

    Args:
        mat: Material containing the image.
        img: Image to get size from.

    Returns:
        Tuple of (width, height) dimensions.
    """
    return (
        (
            min(mat.mimi_smc_size_width, img.size[0]),
            min(mat.mimi_smc_size_height, img.size[1]),
        )
        if mat.mimi_smc_size
        else cast(Tuple[int, int], img.size)
    )


def _get_max_uv_coordinates(
    uv_loops: List[bpy.types.MeshUVLoop],
) -> Tuple[float, float]:
    """Find the maximum UV coordinates across a list of UV loops.

    Args:
        uv_loops: List of UV coordinate vectors.

    Returns:
        Tuple of (max_x, max_y) values.
    """
    max_x = 1
    max_y = 1

    for uv in uv_loops:
        if not math.isnan(uv.x):
            max_x = max(max_x, uv.x)
        if not math.isnan(uv.y):
            max_y = max(max_y, uv.y)

    return max_x, max_y


def get_atlas_size(structure: Structure) -> Tuple[int, int]:
    """Calculate the total size needed for the atlas.

    Args:
        structure: Dictionary mapping materials to their metadata.

    Returns:
        Tuple of (width, height) dimensions for the atlas.
    """
    max_x = 1
    max_y = 1

    for item in structure.values():
        max_x = max(max_x, item["gfx"]["fit"]["x"] + item["gfx"]["size"][0])
        max_y = max(max_y, item["gfx"]["fit"]["y"] + item["gfx"]["size"][1])

    return int(max_x), int(max_y)


def calculate_adjusted_size(
    scn: Scene, size: Tuple[int, int]
) -> Tuple[int, int]:
    """Adjust atlas size based on the chosen sizing strategy.

    PO2/QUAD are applied here; CUST/STRICTCUST keep the natural extent and
    are applied after composition on the finished canvas (see get_atlas).

    Args:
        scn: Current scene with atlas size settings.
        size: Original calculated size.

    Returns:
        Adjusted size based on the selected size strategy.
    """
    return core_layout.adjust_atlas_size(scn.mimi_smc_size, size)


def get_atlas(
    scn: Scene, data: Structure, atlas_size: Tuple[int, int]
) -> Dict[str, np.ndarray]:
    """Generate texture atlas planes for all texture types.

    All pixel math lives in the bpy-free core (texcomb.core): this function
    only walks the structure, delegates per-material plane building to the
    blender adapter (texcomb.blender.planes), and composes the canvases.
    Creates separate atlases for albedo, metallic, roughness, specular,
    normal_map, and emission.

    Args:
        scn: Current scene.
        data: Dictionary mapping materials to their metadata.
        atlas_size: Dimensions for the atlas.

    Returns:
        Dictionary of generated float32 atlas planes by texture type.
    """
    gaps = scn.mimi_smc_gaps
    half_gaps = int(gaps / 2)
    # Shared decode cache so the same texture is never decoded twice.
    images: Dict[str, np.ndarray] = {}

    albedo_items = []
    extra_items = {tex_type: [] for tex_type in plane_builder.EXTRA_TEXTURE_TYPES}

    for mat, item in data.items():
        _set_image_or_color(item, mat)
        fit = item["gfx"].get("fit")
        if not fit:
            continue

        # Content rectangle: the packed box minus its padding.
        content_size = cast(
            Tuple[int, int],
            tuple(int(size - gaps) for size in item["gfx"]["size"]),
        )
        paste_x = int(fit["x"] + half_gaps)
        paste_y = int(fit["y"] + half_gaps)

        try:
            plane = plane_builder.build_base_plane(mat, item, content_size, images)
        except Exception as exc:
            # A texture that fails to decode must not kill the whole merge:
            # degrade the material to its diffuse color and record why (the
            # old code crashed the whole operator in this situation).
            item["gfx"]["diagnostic"] = tr(
                "Material '{name}' texture failed to decode and will be treated as a solid color: {error}"
            ).format(name=mat.name, error=exc)
            fallback_item = dict(item)
            fallback_item["gfx"] = dict(item["gfx"])
            fallback_item["gfx"]["img_or_color"] = get_diffuse(mat)
            fallback_item["gfx"]["alpha"] = None
            plane = plane_builder.build_base_plane(
                mat, fallback_item, content_size, images
            )
        albedo_items.append((plane, paste_x, paste_y))

        if scn.mimi_smc_include_extra_textures:
            for tex_type in plane_builder.EXTRA_TEXTURE_TYPES:
                packed = item["gfx"].get(tex_type)
                if packed is None:
                    continue
                try:
                    extra_plane = plane_builder.build_extra_plane(
                        packed, content_size, tex_type, images
                    )
                except Exception as exc:
                    item["gfx"]["diagnostic"] = tr(
                        "Material '{name}' {type} texture failed to decode and was skipped: {error}"
                    ).format(name=mat.name, type=tex_type, error=exc)
                    continue
                extra_items[tex_type].append((extra_plane, paste_x, paste_y))

    atlases = {"albedo": core_atlas.compose_atlas(albedo_items, atlas_size)}
    for tex_type, items in extra_items.items():
        if items:
            atlases[tex_type] = core_atlas.compose_atlas(items, atlas_size)

    # CUST/STRICTCUST strategies resize/pad the finished canvas at the very
    # end (scale down keeping aspect; strict mode pads to the exact size).
    custom_size = (scn.mimi_smc_size_width, scn.mimi_smc_size_height)
    return {
        tex_type: core_atlas.fit_canvas_to(canvas, scn.mimi_smc_size, custom_size)
        for tex_type, canvas in atlases.items()
    }


def _set_image_or_color(item: StructureItem, mat: bpy.types.Material) -> None:
    """Set the image or color data for a material.

    Args:
        item: Material metadata.
        mat: Material to extract image or color from.
    """
    image = get_image_from_material(mat)
    item["gfx"]["img_or_color"] = get_packed_file(image) if image else None
    item["gfx"]["alpha"] = get_alpha_texture(mat)

    if not item["gfx"]["img_or_color"]:
        item["gfx"]["img_or_color"] = get_diffuse(mat)


def _set_extra_maps(item: StructureItem, mat: bpy.types.Material) -> None:
    """Set extra maps for a material.

    Args:
        item: Material metadata.
        mat: Material to extract image or color from.
    """
    gfx_textures = get_gfx_textures(mat)
    for gfx_type, packed_file in gfx_textures.items():
        item["gfx"][gfx_type] = packed_file


def align_uvs(
    scn: Scene,
    data: Structure,
    atlas_size: Tuple[int, int],
    size: Tuple[int, int],
) -> None:
    """Align UV coordinates to the atlas positions.

    Transforms UV coordinates to match their new positions in the atlas.

    Args:
        scn: Current scene.
        data: Dictionary mapping materials to their metadata.
        atlas_size: Dimensions of the atlas.
        size: Original calculated size before adjustment.
    """
    size_width, size_height = size

    scaled_width, scaled_height = _get_scale_factors(atlas_size, size)

    margin = scn.mimi_smc_gaps + (0 if scn.mimi_smc_pixel_art else 2)
    border_margin = int(scn.mimi_smc_gaps / 2) + (0 if scn.mimi_smc_pixel_art else 1)

    for item in data.values():
        gfx_size = item["gfx"]["size"]
        gfx_height = gfx_size[1]

        gfx_width_margin, gfx_height_margin = (x - margin for x in gfx_size)

        uv_width, uv_height = item["gfx"]["uv_size"]

        x_offset = item["gfx"]["fit"]["x"] + border_margin
        y_offset = item["gfx"]["fit"]["y"] - border_margin

        for uv in item["uv"]:
            reset_x = uv.x / uv_width * gfx_width_margin
            reset_y = uv.y / uv_height * gfx_height_margin - gfx_height

            uv_x = (reset_x + x_offset) / size_width
            uv_y = (reset_y - y_offset) / size_height

            uv.x = uv_x * scaled_width
            uv.y = uv_y * scaled_height + 1


def _get_scale_factors(
    atlas_size: Tuple[int, int], size: Tuple[int, int]
) -> Tuple[float, float]:
    """Calculate scale factors between original and adjusted atlas sizes.

    Args:
        atlas_size: Dimensions of the atlas.
        size: Original calculated size before adjustment.

    Returns:
        Tuple of (width_factor, height_factor) scaling values.
    """
    scaled_factors = tuple(x / y for x, y in zip(size, atlas_size))

    if all(factor <= 1 for factor in scaled_factors):
        return cast(Tuple[float, float], scaled_factors)

    atlas_width, atlas_height = atlas_size
    size_width, size_height = size

    aspect_ratio = (size_width * atlas_height) / (size_height * atlas_width)
    return (1, 1 / aspect_ratio) if aspect_ratio > 1 else (aspect_ratio, 1)


def get_comb_mats(
    scn: Scene, atlases: Dict[str, np.ndarray], mats_uv: MatsUV
) -> CombMats:
    """Create materials for the generated atlases.

    Args:
        scn: Current scene.
        atlases: Dictionary of generated float32 atlas planes by texture type.
        mats_uv: Dictionary mapping object names to materials with UV coordinates.

    Returns:
        Dictionary mapping layer indices to materials.
    """
    unique_id = _get_unique_id(scn)
    layers = _get_layers(scn, mats_uv)

    textures = {}
    for tex_type, atlas in atlases.items():
        path = _save_atlas_with_type(scn, atlas, tex_type, unique_id)
        textures[tex_type] = _create_texture(path, unique_id, tex_type)

    return cast(
        CombMats,
        {
            idx: _create_material_multi(textures, unique_id, idx)
            for idx in layers
        },
    )


def _get_layers(scn: Scene, mats_uv: MatsUV) -> Set[int]:
    """Get all unique layer indices from selected materials.

    Args:
        scn: Current scene.
        mats_uv: Dictionary mapping object names to materials with UV coordinates.

    Returns:
        Set of unique layer indices.
    """
    return {
        item.layer
        for item in scn.mimi_smc_ob_data
        if item.type == CombineListTypes.MATERIAL
        and item.used
        and item.mat in mats_uv[item.ob.name]
    }


def _get_unique_id(scn: Scene) -> str:
    """Generate a unique ID for the atlas.

    Args:
        scn: Current scene.

    Returns:
        Unique ID string for the atlas.
    """
    existed_ids = set()
    _add_ids_from_existing_materials(scn, existed_ids)

    if not os.path.isdir(scn.mimi_smc_save_path):
        return _generate_random_unique_id(existed_ids)

    _add_ids_from_existing_files(scn, existed_ids)
    unique_id = next(
        x for x in itertools.count(start=1) if x not in existed_ids
    )
    return "{:05d}".format(unique_id)


def _add_ids_from_existing_materials(scn: Scene, existed_ids: Set[int]) -> None:
    """Add IDs from existing atlas materials to the set.

    Args:
        scn: The current scene.
        existed_ids: Set to add IDs to.
    """
    atlas_material_pattern = re.compile(
        r"{}(\d+)_\d+".format(atlas_material_prefix)
    )
    for item in scn.mimi_smc_ob_data:
        if item.type != CombineListTypes.MATERIAL:
            continue

        match = atlas_material_pattern.fullmatch(item.mat.name)
        if match:
            existed_ids.add(int(match.group(1)))


def _generate_random_unique_id(existed_ids: Set[int]) -> str:
    """Generate a random unique ID.

    Args:
        existed_ids: Set of existing IDs to avoid.

    Returns:
        Random unique ID string.
    """
    unused_ids = set(range(10000, 99999)) - existed_ids
    return str(random.choice(list(unused_ids)))


def _add_ids_from_existing_files(scn: Scene, existed_ids: Set[int]) -> None:
    """Add IDs from existing atlas files to the set.

    Args:
        scn: The current scene.
        existed_ids: Set to add IDs to.
    """
    atlas_file_pattern = re.compile(r"{}(\d+).png".format(atlas_prefix))
    for file_name in os.listdir(scn.mimi_smc_save_path):
        match = atlas_file_pattern.fullmatch(file_name)
        if match:
            existed_ids.add(int(match.group(1)))


def _save_atlas_with_type(
    scn: Scene, atlas: np.ndarray, tex_type: str, unique_id: str
) -> str:
    """Save an atlas plane to disk with texture type in the name.

    Args:
        scn: Current scene.
        atlas: Generated float32 atlas plane.
        tex_type: Type of texture (albedo, metallic, etc.).
        unique_id: Unique ID for the atlas.

    Returns:
        Path to the saved atlas image.
    """
    ext = {
        "PNG": "png",
        "TGA": "tga",
        "TIFF": "tif",
        "BMP": "bmp",
        "DDS": "dds",
    }.get(scn.mimi_smc_image_format, "png")

    filename = "{}{}{}.{}".format(
        atlas_prefix,
        "{}_".format(tex_type.title()) if tex_type != "albedo" else "",
        unique_id,
        ext,
    )

    path = os.path.join(scn.mimi_smc_save_path, filename)
    # Albedo is a color and gets the linear->sRGB conversion; every other
    # map is data and is written with its values untouched. The core export
    # performs the single 8-bit quantization step of the whole pipeline.
    if scn.mimi_smc_image_format == "DDS":
        # DDS goes through texconv.exe, which controls the exact DXGI
        # format, the sRGB tag, and mipmap generation.
        core_export.save_dds(
            atlas,
            path,
            dds_format=scn.mimi_smc_dds_format,
            mipmaps=scn.mimi_smc_dds_mipmaps,
            srgb=(tex_type == "albedo"),
            texconv_path=scn.mimi_smc_texconv_path,
        )
        return path
    core_export.save_image(
        atlas,
        path,
        image_format=scn.mimi_smc_image_format,
        srgb=(tex_type == "albedo"),
    )
    return path


def _create_texture(
    path: str, unique_id: str, tex_type: str = "albedo"
) -> bpy.types.Texture:
    """Create a Blender texture from an atlas image.

    Args:
        path: Path to the atlas image.
        unique_id: Unique ID for the atlas.
        tex_type: Type of texture.

    Returns:
        Created Blender texture.
    """
    texture_name = "{}{}{}".format(
        atlas_texture_prefix,
        '{}_'.format(tex_type) if tex_type != "albedo" else "",
        unique_id,
    )

    texture = bpy.data.textures.new(texture_name, "IMAGE")
    image = bpy.data.images.load(path)
    texture.image = image
    return texture


def _create_material_multi(
    textures: Dict[str, bpy.types.Texture], unique_id: str, idx: int
) -> bpy.types.Material:
    """Create a Blender material using multiple atlas textures.

    Args:
        textures: Dictionary of atlas textures by type.
        unique_id: Unique ID for the atlas.
        idx: Layer index for the material.

    Returns:
        Created Blender material.
    """
    mat = bpy.data.materials.new(
        name="{}{}_{}".format(atlas_material_prefix, unique_id, idx)
    )
    _configure_material_multi(mat, textures)
    return mat


def _configure_material_multi(  # noqa: PLR0915
    mat: bpy.types.Material, textures: Dict[str, bpy.types.Texture]
) -> None:
    """Configure a modern (Cycles/Eevee) material with multiple atlas textures.

    Args:
        mat: Material to configure.
        textures: Dictionary of atlas textures by type.
    """
    mat.blend_method = "CLIP"
    mat.use_backface_culling = True
    mat.use_nodes = True

    node_tree = mat.node_tree
    # node_bsdf = node_tree.nodes["Principled BSDF"]
    # Name-based lookup depends on the UI language; a Chinese name would not be found
    # Look up by node type instead
    node_bsdf = next(
        n for n in node_tree.nodes if n.type == "BSDF_PRINCIPLED"
    )

    # Position offset for texture nodes
    x_offset = -600
    y_offset = 400
    y_spacing = 300

    def _mark_channel_packed(node) -> None:
        # Atlas textures pack data into the alpha channel: CHANNEL_PACKED keeps
        # it available as data instead of letting Blender read it as coverage.
        try:
            if node.image is not None:
                node.image.alpha_mode = "CHANNEL_PACKED"
        except (AttributeError, TypeError, ValueError):
            pass

    # Configure albedo texture
    if "albedo" in textures:
        node_albedo = node_tree.nodes.new(type="ShaderNodeTexImage")
        node_albedo.image = textures["albedo"].image
        node_albedo.label = "Diffuse Atlas"
        node_albedo.location = x_offset, y_offset
        _mark_channel_packed(node_albedo)

        node_tree.links.new(
            node_albedo.outputs["Color"], node_bsdf.inputs["Base Color"]
        )
        node_tree.links.new(
            node_albedo.outputs["Alpha"], node_bsdf.inputs["Alpha"]
        )

    # Configure metallic texture if exists
    if "metallic" in textures:
        node_metallic = node_tree.nodes.new(type="ShaderNodeTexImage")
        node_metallic.image = textures["metallic"].image
        node_metallic.label = "Metallic Atlas"
        node_metallic.location = x_offset, y_offset - y_spacing
        node_metallic.image.colorspace_settings.name = "Non-Color"
        _mark_channel_packed(node_metallic)

        node_tree.links.new(
            node_metallic.outputs["Color"], node_bsdf.inputs["Metallic"]
        )

    # Configure roughness texture if exists
    if "roughness" in textures:
        node_roughness = node_tree.nodes.new(type="ShaderNodeTexImage")
        node_roughness.image = textures["roughness"].image
        node_roughness.label = "Roughness Atlas"
        node_roughness.location = x_offset, y_offset - y_spacing * 2
        node_roughness.image.colorspace_settings.name = "Non-Color"
        _mark_channel_packed(node_roughness)

        node_tree.links.new(
            node_roughness.outputs["Color"], node_bsdf.inputs["Roughness"]
        )

    # Configure specular texture if exists
    if "specular" in textures:
        node_specular = node_tree.nodes.new(type="ShaderNodeTexImage")
        node_specular.image = textures["specular"].image
        node_specular.label = "Specular Atlas"
        node_specular.location = x_offset, y_offset - y_spacing * 3
        node_specular.image.colorspace_settings.name = "Non-Color"
        _mark_channel_packed(node_specular)

        node_tree.links.new(
            node_specular.outputs["Color"], node_bsdf.inputs["Specular Tint"]
        )

    # Configure emission texture if exists
    if "emission" in textures:
        node_emission = node_tree.nodes.new(type="ShaderNodeTexImage")
        node_emission.image = textures["emission"].image
        node_emission.label = "Emission Atlas"
        node_emission.location = x_offset, y_offset - y_spacing * 4
        _mark_channel_packed(node_emission)

        node_tree.links.new(
            node_emission.outputs["Color"], node_bsdf.inputs["Emission Color"]
        )

        node_bsdf.inputs["Emission Strength"].default_value = 1.0

    # Configure normal map if exists
    if "normal_map" in textures:
        node_normal_tex = node_tree.nodes.new(type="ShaderNodeTexImage")
        node_normal_tex.image = textures["normal_map"].image
        node_normal_tex.label = "Normal Map Atlas"
        node_normal_tex.location = x_offset - 300, y_offset - y_spacing * 5
        node_normal_tex.image.colorspace_settings.name = "Non-Color"
        _mark_channel_packed(node_normal_tex)

        # Add Normal Map node
        node_normal_map = node_tree.nodes.new(type="ShaderNodeNormalMap")
        node_normal_map.location = x_offset, y_offset - y_spacing * 5

        node_tree.links.new(
            node_normal_tex.outputs["Color"], node_normal_map.inputs["Color"]
        )
        node_tree.links.new(
            node_normal_map.outputs["Normal"], node_bsdf.inputs["Normal"]
        )


def assign_comb_mats(scn: Scene, data: SMCObData, comb_mats: CombMats) -> None:
    """Assign combined materials to objects.

    Args:
        scn: Current scene.
        data: Dictionary mapping object names to materials.
        comb_mats: Dictionary mapping layer indices to materials.
    """
    for ob_n, item in data.items():
        ob = scn.objects[ob_n]
        ob_materials = ob.data.materials
        _assign_mats(item, comb_mats, ob_materials)
        _assign_mats_to_polys(item, comb_mats, ob, ob_materials)


def _assign_mats(
    item: SMCObDataItem, comb_mats: CombMats, ob_materials: ObMats
) -> None:
    """Add combined materials to an object's material slots.

    Args:
        item: Dictionary mapping materials to layer indices.
        comb_mats: Dictionary mapping layer indices to materials.
        ob_materials: Object's material collection.
    """
    for idx in set(item.values()):
        if idx in comb_mats:
            ob_materials.append(comb_mats[idx])


def _assign_mats_to_polys(
    item: SMCObDataItem,
    comb_mats: CombMats,
    ob: bpy.types.Object,
    ob_materials: ObMats,
) -> None:
    """Assign materials to polygons based on their layer.

    Args:
        item: Dictionary mapping materials to layer indices.
        comb_mats: Dictionary mapping layer indices to materials.
        ob: Object to assign materials to.
        ob_materials: Object's material collection.
    """
    for idx, polys in get_polys(ob).items():
        if ob_materials[idx] not in item:
            continue

        mat_name = comb_mats[item[ob_materials[idx]]].name
        mat_idx = ob_materials.find(mat_name)
        for poly in polys:
            poly.material_index = mat_idx


def clear_mats(scn: Scene, mats_uv: MatsUV) -> None:
    """Remove original materials from objects after a combination.

    Args:
        scn: Current scene.
        mats_uv: Dictionary mapping object names to materials with UV coordinates.
    """
    for ob_n, item in mats_uv.items():
        ob = scn.objects[ob_n]
        for mat in item:
            _delete_material(ob, mat.name)
