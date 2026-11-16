"""Blender adapter for the source-texture identity used by the combiner.

The planner and the merger both group materials by source texture. This
module turns Blender data into the identity tuples defined by
texcomb/core/source_identity.py. Keeping the conversion here means the
grouping code never has to know how a path or a packed file is read.

Cost rule: a file path that appears only once is already a unique source.
Its bytes are never hashed. A path that appears several times is hashed so a
replaced file cannot be merged with the picture loaded before it. The hash
result is cached for the duration of one planning pass and cleared when a new
pass starts.
"""

import hashlib

import bpy

from ..core import source_identity
from . import images as image_utils
from . import materials as material_utils


def _absolute_image_path(image):
    """Return the absolute file path of one image, or "" when it has none.

    A packed image keeps its original filepath, so identity survives packing.
    Generated images have no filepath and fall back to their pointer.
    """
    if image is None:
        return ""
    filepath = getattr(image, "filepath", "")
    if not filepath:
        return ""
    try:
        return bpy.path.abspath(filepath)
    except (AttributeError, RuntimeError, ValueError):
        # A malformed relative path must not abort a merge; the raw string is
        # still comparable to another image that reports the same string.
        return filepath


def normalized_image_path(image):
    """Return the normalized path used to compare two image sources."""
    return source_identity.normalize_texture_path(_absolute_image_path(image))


def packed_content_digest(image):
    """Hash the packed bytes of one image; "" when no bytes are available.

    PackedFile.data returns the packed payload as bytes. Some generated or
    half-loaded images expose no payload; those must not crash planning.
    """
    packed = image_utils.get_packed_file(image)
    if packed is None:
        return ""
    try:
        data = packed.data
    except (AttributeError, RuntimeError):
        return ""
    if not data:
        return ""
    return hashlib.sha256(data).hexdigest()


def _alpha_source_image(mat):
    """Return the image that drives alpha for this material, or None.

    SEPARATE and MULTIPLY use an explicitly chosen image; AUTO follows the
    shader Alpha input. A material without a linked alpha image has no extra
    source to compare.
    """
    mode = mat.mimi_smc_alpha_mode
    if mode in {"SEPARATE", "MULTIPLY"}:
        return mat.mimi_smc_alpha_image or None
    if mode == "AUTO":
        return material_utils.get_alpha_texture_image(mat)
    return None


def _store_main_identity(structure, mat, identity):
    """Write the base-color identity used by texture_groups/output_groups."""
    structure[mat]["gfx"]["source_key"] = identity


def _store_extra_identity(structure, mat, kind, identity):
    """Write alpha or one extra-map identity into the cached graphics data."""
    gfx = structure[mat]["gfx"]
    if kind is None:
        gfx["alpha_source"] = identity
        return
    gfx.setdefault("map_sources", {})[kind] = identity


def assign_source_identities(structure, include_extra_textures=False):
    """Cache one source identity per material before any grouping runs.

    Base images are grouped by path first. A path that resolves to a single
    datablock is not hashed: the path alone is already unique, which keeps the
    normal imported model (one source datablock reused by many materials)
    free of hashing cost. A path with several datablocks is hashed per block.

    Extra maps follow the same rule and are cached so output_groups can read
    them several times without reading bytes again.
    """
    if not structure:
        return
    # The batch scan has no cross-pass cache: every pass reads the current
    # bytes, so a file replaced between planning and merging is noticed.
    images = {}
    paths = {}
    materials_by_path = {}
    for mat in structure:
        # Grouping needs the image datablock, not its packed bytes. Reading it
        # once here avoids repeated shader-node walks inside the same pass.
        image = material_utils.get_image_from_material(mat)
        images[mat] = image
        if image is None:
            # A solid-color material has no image family to share.
            _store_main_identity(structure, mat,
                                 source_identity.material_identity(mat.as_pointer()))
            continue
        pointer = image.as_pointer()
        if pointer not in paths:
            # Several materials often share one datablock; normalize once.
            paths[pointer] = normalized_image_path(image)
        path = paths[pointer]
        if not path:
            # No file identity: the datablock pointer is the only identity.
            _store_main_identity(structure, mat,
                                 source_identity.build_source_identity("", "", pointer))
            continue
        materials_by_path.setdefault(path, []).append(mat)
    digests = {}
    for path, mats in materials_by_path.items():
        pointers = {images[mat].as_pointer() for mat in mats}
        if len(pointers) == 1:
            # One datablock per path: no byte comparison can change the answer.
            pointer = pointers.pop()
            for mat in mats:
                _store_main_identity(
                    structure, mat,
                    source_identity.build_source_identity(path, "", pointer))
            continue
        # Several datablocks claim one path: compare the bytes they carry.
        for mat in mats:
            pointer = images[mat].as_pointer()
            if pointer not in digests:
                digests[pointer] = packed_content_digest(images[mat])
            _store_main_identity(
                structure, mat,
                source_identity.build_source_identity(
                    path, digests[pointer], pointer))
    _assign_extra_identities(structure, include_extra_textures)


def _assign_extra_identities(structure, include_extra_textures):
    """Cache alpha and extra-map identities with the same cost rule.

    Every pass clears the old alpha and map entries first: a material can
    lose its alpha image or an extra-map socket between planning and a direct
    merge call, and a stale cached identity would then disagree with what the
    composer actually bakes.
    """
    for mat in structure:
        gfx = structure[mat]["gfx"]
        gfx["alpha_source"] = None
        gfx["map_sources"] = {}
        # Record which scene setting produced the map cache. output_groups can
        # then tell an empty result from a scan that never included PBR maps.
        gfx["map_scan"] = bool(include_extra_textures)
    entries = []
    for mat in structure:
        alpha_image = _alpha_source_image(mat)
        if alpha_image is not None:
            entries.append((mat, alpha_image, None))
        if include_extra_textures:
            for kind, image in material_utils.get_gfx_texture_images(mat).items():
                entries.append((mat, image, kind))
    if not entries:
        return
    # The same batch rule as the base image: a unique path needs no hash, and
    # a path shared by several datablocks gets one hash per datablock.
    by_path = {}
    without_path = []
    for mat, image, kind in entries:
        path = normalized_image_path(image)
        if path:
            by_path.setdefault(path, []).append((mat, image, kind))
        else:
            without_path.append((mat, image, kind))
    for path, items in by_path.items():
        pointers = {image.as_pointer() for _, image, _ in items}
        digests = {}
        if len(pointers) > 1:
            for _, image, _ in items:
                pointer = image.as_pointer()
                if pointer not in digests:
                    digests[pointer] = packed_content_digest(image)
        for mat, image, kind in items:
            _store_extra_identity(
                structure, mat, kind,
                source_identity.build_source_identity(
                    path, digests.get(image.as_pointer(), ""), image.as_pointer()))
    # No file path: the datablock is the only identity. Hashing here would
    # compare unrelated generated images that happen to look alike.
    for mat, image, kind in without_path:
        _store_extra_identity(
            structure, mat, kind,
            source_identity.build_source_identity("", "", image.as_pointer()))


def material_source_key(mat):
    """Identity used when a caller skipped assign_source_identities.

    The fallback still hashes the bytes, so two datablocks of one path with
    different content stay apart even without the batch scan. Product entry
    points always assign first, so this path only guards direct callers.
    """
    image = material_utils.get_image_from_material(mat)
    if image is None:
        return source_identity.material_identity(mat.as_pointer())
    return image_source_key(image)


def image_source_key(image):
    """Return the identity of any image, including alpha and PBR sources.

    This is the on-demand fallback for a structure that skipped the batch
    scan. It always hashes the current bytes instead of caching an identity:
    a packed payload can be replaced while the Image datablock pointer stays
    the same, and a stale identity would merge two different pictures.
    """
    if image is None:
        return None
    return source_identity.build_source_identity(
        normalized_image_path(image),
        packed_content_digest(image),
        image.as_pointer(),
    )
