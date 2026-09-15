"""Build float32 planes from bpy materials using the pure core.

This is the bridge between the bpy world and the bpy-free core pipeline:
it reads material properties and packed file bytes, then expresses each
material as a core ChannelPlan so all image math happens in texcomb.core.

Only decode failures and user-facing choices are handled here; this module
deliberately contains no pixel algorithms of its own.
"""

from typing import Dict, Optional, Tuple

import bpy
import numpy as np

from ...i18n.i18n import tr
from ..core import channels, decode, pixels
from ..core.atlas import fit_within
from ..core.models import (
    ALPHA_MULTIPLY,
    ALPHA_OPAQUE,
    ALPHA_SEPARATE,
    ChannelPlan,
    ChannelSource,
)
from ..utils.images import get_packed_file
from ..utils.materials import get_diffuse

# Extra texture types that get their own atlas when "Atlas PBR Textures" is
# enabled. Order matters only for stable diagnostics output.
EXTRA_TEXTURE_TYPES = ("metallic", "roughness", "specular", "normal_map", "emission")

# Extra texture types whose pixels are COLORS (sRGB) rather than data.
# Kept empty for now, matching the old behavior of resizing raw values for
# every extra map; upgrading emission to sRGB-aware filtering is a separate
# deliberate step (Phase 2).
_EXTRA_SRGB = frozenset()


def _srgb255_to_linear(color: Tuple[int, ...]) -> Tuple[float, float, float, float]:
    """Convert an (r, g, b, a) sRGB byte tuple to a linear float tuple.

    get_diffuse() returns sRGB bytes; the core pipeline works in linear
    float32, so every color crosses this bridge exactly once.
    """
    plane = np.asarray([[color]], dtype=np.float32) / 255.0
    return tuple(float(v) for v in pixels.srgb_to_linear(plane)[0, 0])


def _decode_cached(
    images: Dict[str, np.ndarray], key: str, packed_file, srgb: bool
) -> np.ndarray:
    """Decode packed bytes once per packed file and cache the plane.

    The cache key uses the packed file's C pointer: plain id() of the bpy
    wrapper object is NOT stable across attribute accesses, as_pointer() is.
    """
    if key not in images:
        images[key] = decode.decode_bytes(packed_file.data, srgb=srgb)
    return images[key]


def build_base_plane(
    mat: bpy.types.Material,
    item: dict,
    content_size: Tuple[int, int],
    images: Dict[str, np.ndarray],
    filter_name: str = "lanczos3",
) -> np.ndarray:
    """Build the albedo RGBA float32 plane for one material.

    Args:
        mat: the bpy material (for diffuse color and per-material options).
        item: the material's structure dict; reads gfx.img_or_color (a
            PackedFile, an sRGB byte color tuple, or None) and gfx.alpha
            ((PackedFile, output socket name) or None) and writes
            gfx.alpha_diagnostic when the alpha texture fails to decode.
        content_size: (width, height) the plane is resized to; all four
            channels of the base image are resized in one operation.
        images: shared decode cache for this atlas build.
        filter_name: resampling filter for all resizing.

    Returns:
        A float32 linear RGBA plane of exactly content_size (unless the
        per-material custom size shrinks it further, like the old thumbnail
        step did).
    """
    img_or_color = item["gfx"]["img_or_color"]
    plan = ChannelPlan()

    if isinstance(img_or_color, tuple):
        # Solid-color material: the diffuse color IS the plane content, and
        # no extra tint is applied on top (matches the old code path).
        plan.base_key = ""
        plan.solid_color = _srgb255_to_linear(img_or_color)
    elif img_or_color is None:
        # Last-resort fallback of the old code: a white plane.
        plan.base_key = ""
        plan.solid_color = (1.0, 1.0, 1.0, 1.0)
    else:
        # Textured material: decode the packed bytes into a linear plane.
        key = "base:{}".format(img_or_color.as_pointer())
        _decode_cached(images, key, img_or_color, srgb=True)
        plan.base_key = key
        # The "blend diffuse color" option multiplies the texture by the
        # material's diffuse color. Its alpha component is always 1.0, so
        # the alpha channel itself is never tinted.
        if getattr(mat, "mimi_smc_diffuse", False):
            plan.diffuse_color = _srgb255_to_linear(get_diffuse(mat))

    # Resolve the alpha strategy: explicit per-material setting first, then
    # the AUTO fallback that follows the Principled Alpha input link.
    _apply_alpha_plan(mat, item, plan, images)

    plane = channels.build_material_plane(
        plan, images, size=content_size, filter_name=filter_name
    )

    # Per-material custom size: shrink the finished plane to fit, keeping
    # aspect (the old code applied PIL thumbnail to the resized texture).
    # Solid-color planes were never thumbnailed by the old code either.
    is_textured = img_or_color is not None and not isinstance(img_or_color, tuple)
    if is_textured and getattr(mat, "mimi_smc_size", False):
        current = (plane.shape[1], plane.shape[0])
        target = fit_within(
            current, (mat.mimi_smc_size_width, mat.mimi_smc_size_height)
        )
        if target != current:
            plane = pixels.resize_plane(plane, target[0], target[1], filter_name)

    return plane


def _apply_alpha_plan(
    mat: bpy.types.Material,
    item: dict,
    plan: ChannelPlan,
    images: Dict[str, np.ndarray],
) -> None:
    """Choose and apply the alpha strategy for one material's ChannelPlan.

    Priority: the material's explicit "Alpha Source" setting wins; "AUTO"
    reproduces the classic behavior (follow the image linked to the
    Principled BSDF Alpha input, if any). Any failure degrades gracefully to
    the embedded base alpha plus a diagnostic instead of killing the merge.
    """
    mode = getattr(mat, "mimi_smc_alpha_mode", "AUTO")

    if mode == "OPAQUE":
        plan.alpha_mode = ALPHA_OPAQUE
        return

    if mode == "EMBEDDED":
        # The default ChannelPlan already keeps the base texture's alpha.
        return

    if mode in ("SEPARATE", "MULTIPLY"):
        # Explicit user-chosen image + channel as the alpha source.
        image = getattr(mat, "mimi_smc_alpha_image", None)
        channel_name = getattr(mat, "mimi_smc_alpha_channel", "A")
        packed = get_packed_file(image) if image else None
        if packed is None:
            item["gfx"]["alpha_diagnostic"] = tr(
                "Alpha mode '{mode}' needs a readable alpha image; falling back to the base texture's alpha."
            ).format(mode=mode)
            return
        key = "alpha-x:{}".format(packed.as_pointer())
        # LUM needs linear colors; a plain channel is raw data.
        _decode_cached(images, key, packed, srgb=(channel_name == "LUM"))
        plan.alpha_mode = ALPHA_SEPARATE if mode == "SEPARATE" else ALPHA_MULTIPLY
        plan.alpha = ChannelSource(image_key=key, channel=channel_name)
        return

    # AUTO: a separate alpha texture linked to the Principled Alpha input
    # replaces the base alpha — the old behavior, now only one option.
    alpha_info = item["gfx"].get("alpha")
    if not alpha_info:
        return
    packed_alpha, output_name = alpha_info
    channel_name = "A" if output_name == "Alpha" else "LUM"
    try:
        alpha_key = "alpha:{}".format(packed_alpha.as_pointer())
        # LUM needs linear colors; a plain alpha channel is raw data.
        _decode_cached(
            images, alpha_key, packed_alpha, srgb=(channel_name == "LUM")
        )
        plan.alpha_mode = ALPHA_SEPARATE
        plan.alpha = ChannelSource(image_key=alpha_key, channel=channel_name)
    except Exception as exc:
        # A broken alpha texture must not kill the whole merge: keep the
        # base alpha and record why (surfaced as a warning afterwards).
        item["gfx"]["alpha_diagnostic"] = tr(
            "Failed to apply the alpha texture: {error}"
        ).format(error=exc)


def build_extra_plane(
    packed_file,
    content_size: Tuple[int, int],
    tex_type: str,
    images: Dict[str, np.ndarray],
    filter_name: str = "lanczos3",
) -> np.ndarray:
    """Build one extra-map (metallic/roughness/...) plane for the atlas.

    Data maps keep their raw values (no sRGB conversion). Normal maps are
    renormalized after resizing so their vectors stay unit length — an
    intentional precision upgrade over the old code, which resized normals
    without renormalizing them.
    """
    key = "extra:{}".format(packed_file.as_pointer())
    _decode_cached(images, key, packed_file, srgb=tex_type in _EXTRA_SRGB)
    plane = images[key]

    if plane.shape[:2] != (content_size[1], content_size[0]):
        plane = pixels.resize_plane(
            plane, content_size[0], content_size[1], filter_name
        )
        if tex_type == "normal_map":
            plane = pixels.renormalize_normals(plane)
    return plane
