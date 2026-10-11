"""Channel merging for the texture combiner core.

This module implements the headline feature of the refactor: building one
material's RGBA float32 plane from explicit per-channel sources, with a
user-selected alpha merge strategy (ChannelPlan).

The old code only supported "whatever happens to be linked to the Principled
Alpha socket, overwriting the base texture's own alpha". Here the strategy
is explicit and testable.
"""

from typing import Dict, Optional, Tuple

import numpy as np

from . import pixels
from .models import (
    ALPHA_EMBEDDED,
    ALPHA_MULTIPLY,
    ALPHA_OPAQUE,
    ALPHA_SEPARATE,
    ChannelPlan,
    ChannelSource,
)

# Map the single-letter channel names to plane channel indices.
_CHANNEL_INDEX = {"R": 0, "G": 1, "B": 2, "A": 3}


def extract_channel(plane: np.ndarray, channel: str) -> np.ndarray:
    """Extract one channel of a plane as a 2D array (H, W).

    "LUM" is Rec.709 luma in linear space; "ONE" is a constant plane of 1.0
    (used when a mask should default to fully present).
    """
    if channel in _CHANNEL_INDEX:
        return plane[..., _CHANNEL_INDEX[channel]]
    if channel == "LUM":
        return pixels.luma(plane)
    if channel == "ONE":
        return np.ones(plane.shape[:2], dtype=np.float32)
    raise ValueError("Unknown channel: {!r}".format(channel))


def _resolve_source(
    source: ChannelSource,
    images: Dict[str, np.ndarray],
    size: Optional[Tuple[int, int]],
    filter_name: str,
) -> np.ndarray:
    """Resolve a ChannelSource to a 2D float32 array of the target size.

    A source without an image_key is a flat constant. Otherwise the named
    image is (optionally) resized as a whole RGBA plane first, so all of its
    channels are filtered by the same operation, and only then is the
    requested channel extracted.
    """
    # Constant source: a flat plane filled with the constant value.
    if not source.image_key:
        if size is None:
            raise ValueError("Constant sources need a target size")
        return np.full((size[1], size[0]), source.constant, dtype=np.float32)

    # Image source: look up the decoded float32 plane.
    if source.image_key not in images:
        raise KeyError(
            "No decoded image stored under key {!r}".format(source.image_key)
        )
    plane = images[source.image_key]

    # Resize the WHOLE plane to the target size before channel extraction,
    # keeping every channel of the source image mutually aligned.
    if size is not None and plane.shape[:2] != (size[1], size[0]):
        plane = pixels.resize_plane(plane, size[0], size[1], filter_name)

    return extract_channel(plane, source.channel).astype(np.float32)


def build_material_plane(
    plan: ChannelPlan,
    images: Dict[str, np.ndarray],
    size: Optional[Tuple[int, int]] = None,
    filter_name: str = "lanczos3",
) -> np.ndarray:
    """Build one material's RGBA float32 plane according to its ChannelPlan.

    Args:
        plan: the channel merge plan for this material (validated first).
        images: decoded float32 linear RGBA planes by key.
        size: optional (width, height) the result is resized to. The base
            image is resized as a whole plane, so its RGB and A channels are
            filtered together, in one operation.
        filter_name: resampling filter for all resizing in this build.

    Returns:
        A float32 plane of shape (H, W, 4) in linear space.
    """
    # Fail loudly on inconsistent plans before doing any pixel work.
    plan.validate()

    # --- Step 1: obtain the base RGBA plane -------------------------------
    if plan.base_key:
        if plan.base_key not in images:
            raise KeyError(
                "No decoded image stored under key {!r}".format(plan.base_key)
            )
        base = images[plan.base_key]
        # Resize all four channels of the base image in ONE operation.
        if size is not None and base.shape[:2] != (size[1], size[0]):
            base = pixels.resize_plane(base, size[0], size[1], filter_name)
        else:
            # Copy so the diffuse multiply below never mutates the cache.
            base = np.array(base, dtype=np.float32, copy=True)
    else:
        # Solid-color material: no base image, fill with the fallback color.
        if size is None:
            raise ValueError("Solid-color materials need a target size")
        base = pixels.new_plane(size[0], size[1], plan.solid_color)

    # --- Step 2: apply the diffuse-color multiplier -----------------------
    # (1, 1, 1, 1) means "no tint", which is the common case.
    if tuple(plan.diffuse_color) != (1.0, 1.0, 1.0, 1.0):
        base = pixels.multiply_color(base, plan.diffuse_color)

    # --- Step 3: resolve the alpha channel according to the strategy ------
    if plan.alpha_mode == ALPHA_EMBEDDED:
        # Keep whatever alpha the base image (or solid color) already has.
        pass
    elif plan.alpha_mode == ALPHA_OPAQUE:
        # Strip alpha: fully opaque everywhere.
        base[..., 3] = 1.0
    elif plan.alpha_mode == ALPHA_SEPARATE:
        # Replace alpha with the chosen channel of the alpha source.
        base[..., 3] = _resolve_source(plan.alpha, images, base.shape[:2][::-1], filter_name)
    elif plan.alpha_mode == ALPHA_MULTIPLY:
        # Combine base alpha with the alpha source (stacked masks).
        extra = _resolve_source(plan.alpha, images, base.shape[:2][::-1], filter_name)
        base[..., 3] = base[..., 3] * extra
    else:
        # validate() already rejects unknown modes; this is defensive only.
        raise ValueError("Unknown alpha_mode: {!r}".format(plan.alpha_mode))

    # Final safety: keep every channel inside [0, 1].
    return np.clip(base, 0.0, 1.0)
