"""Float32 pixel operations for the texture combiner core.

Every function here works on numpy arrays of shape (height, width, 4),
dtype float32, values in [0, 1], in LINEAR color space. The alpha channel
is plain data and is never color-converted.

Why float32 planes instead of 8-bit Pillow images:
- All filtering happens once, in linear space, with float64 accumulation,
  so the only quantization step is the final export to 8/16-bit.
- RGB and A always live on the same plane and are resized by the same
  operation, so they can never drift out of alignment.

Performance is intentionally not a goal; clarity and precision are.
"""

import math
from typing import Sequence, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Number of channels on every plane (RGBA).
CHANNEL_COUNT = 4

# sRGB transfer function constants (IEC 61966-2-1).
_SRGB_LINEAR_THRESHOLD = 0.04045
_SRGB_GAMMA = 2.4
_SRGB_SCALE_LOW = 12.92
_SRGB_A = 1.055
_SRGB_B = 0.055

# Rec.709 luma weights, applied in linear space (the physically meaningful
# luma; the old code used Rec.601 weights on sRGB values, which mixes both
# mistakes at once).
_LUMA_WEIGHTS = (0.2126, 0.7152, 0.0722)


# ---------------------------------------------------------------------------
# Plane creation and conversion
# ---------------------------------------------------------------------------

def new_plane(
    width: int,
    height: int,
    color: Sequence[float] = (0.0, 0.0, 0.0, 0.0),
) -> np.ndarray:
    """Create a float32 RGBA plane filled with one linear color."""
    # Allocate the canonical (height, width, 4) layout.
    plane = np.empty((height, width, CHANNEL_COUNT), dtype=np.float32)
    # Broadcast the RGBA fill color over every pixel.
    plane[:, :] = np.asarray(color, dtype=np.float32)
    return plane


def from_uint8(rgb: np.ndarray) -> np.ndarray:
    """Convert a uint8 image (H, W, C) to a float32 plane in [0, 1].

    No colorspace conversion happens here; use srgb_to_linear for that.
    """
    return rgb.astype(np.float32) / 255.0


def to_uint8(plane: np.ndarray) -> np.ndarray:
    """Quantize a float32 plane to uint8 with clipping and rounding.

    This is the ONLY place where precision is deliberately reduced, and the
    pipeline calls it exactly once per output image, at export time.
    """
    return np.clip(plane * 255.0 + 0.5, 0.0, 255.0).astype(np.uint8)


def srgb_to_linear(plane: np.ndarray) -> np.ndarray:
    """Convert the RGB channels of a plane from sRGB to linear.

    Alpha (channel 3, if present) is copied through unchanged: alpha is data,
    not color.
    """
    # Work on a float32 copy so the caller's plane is never mutated.
    out = np.array(plane, dtype=np.float32, copy=True)
    rgb = out[..., :3].astype(np.float64)
    # Piecewise sRGB EOTF, vectorized with a boolean mask.
    low = rgb <= _SRGB_LINEAR_THRESHOLD
    linear = np.empty_like(rgb)
    linear[low] = rgb[low] / _SRGB_SCALE_LOW
    linear[~low] = ((rgb[~low] + _SRGB_B) / _SRGB_A) ** _SRGB_GAMMA
    out[..., :3] = linear
    return out


def linear_to_srgb(plane: np.ndarray) -> np.ndarray:
    """Convert the RGB channels of a plane from linear to sRGB.

    Alpha (channel 3, if present) is copied through unchanged.
    """
    out = np.array(plane, dtype=np.float32, copy=True)
    rgb = np.clip(out[..., :3].astype(np.float64), 0.0, None)
    low = rgb <= (_SRGB_LINEAR_THRESHOLD / _SRGB_SCALE_LOW)
    srgb = np.empty_like(rgb)
    srgb[low] = rgb[low] * _SRGB_SCALE_LOW
    srgb[~low] = _SRGB_A * rgb[~low] ** (1.0 / _SRGB_GAMMA) - _SRGB_B
    out[..., :3] = srgb
    return out


def luma(plane: np.ndarray) -> np.ndarray:
    """Return the Rec.709 luma of a plane as a 2D array (H, W), linear space."""
    # Weighted sum of the linear RGB channels.
    return (
        plane[..., 0] * _LUMA_WEIGHTS[0]
        + plane[..., 1] * _LUMA_WEIGHTS[1]
        + plane[..., 2] * _LUMA_WEIGHTS[2]
    )


# ---------------------------------------------------------------------------
# Resampling
# ---------------------------------------------------------------------------

# Each filter is (kernel function, support radius in source pixels).
def _kernel_box(x: float) -> float:
    # Nearest-neighbor-like flat kernel; used mainly for pixel art.
    return 1.0 if abs(x) <= 0.5 else 0.0


def _kernel_triangle(x: float) -> float:
    # Bilinear tent kernel.
    x = abs(x)
    return 1.0 - x if x < 1.0 else 0.0


def _kernel_lanczos3(x: float) -> float:
    # Lanczos-3: sinc(x) * sinc(x / 3) inside |x| < 3, zero outside.
    x = abs(x)
    if x >= 3.0:
        return 0.0
    if x == 0.0:
        return 1.0
    pi_x = math.pi * x
    pi_x_3 = pi_x / 3.0
    return (math.sin(pi_x) / pi_x) * (math.sin(pi_x_3) / pi_x_3)


FILTERS = {
    "box": (_kernel_box, 0.5),
    "bilinear": (_kernel_triangle, 1.0),
    "lanczos3": (_kernel_lanczos3, 3.0),
}


def _resize_table(
    src_size: int, dst_size: int, filter_name: str
) -> Tuple[np.ndarray, np.ndarray]:
    """Precompute resampling indices and weights for one axis.

    Returns (indices, weights), both int32/float64 arrays of shape
    (dst_size, taps): output pixel i is sum_t weights[i, t] * src[indices[i, t]].

    When downscaling (ratio > 1), the kernel is widened by the ratio so the
    result is properly anti-aliased (this is what PIL's LANCZOS does too).
    Indices are clamped to the valid range, which reproduces edge pixels
    instead of wrapping or fading to black.
    """
    kernel, support = FILTERS[filter_name]
    ratio = src_size / dst_size
    # filter_scale > 1 only when downscaling; upscale keeps the base support.
    filter_scale = max(ratio, 1.0)
    radius = support * filter_scale
    taps = max(1, int(math.ceil(radius * 2.0)))

    indices = np.zeros((dst_size, taps), dtype=np.int32)
    weights = np.zeros((dst_size, taps), dtype=np.float64)

    for i in range(dst_size):
        # Center of dst pixel i in source coordinates (pixel-center mapping).
        center = (i + 0.5) * ratio
        # Source pixels whose kernel support overlaps this dst pixel.
        first = int(math.ceil(center - radius - 0.5))
        for t in range(taps):
            src = first + t
            # Evaluate the kernel in filter-scaled space around the center.
            w = kernel((src + 0.5 - center) / filter_scale)
            # Clamp to valid range: out-of-range taps just repeat the edge.
            indices[i, t] = min(max(src, 0), src_size - 1)
            weights[i, t] = w
        # Normalize so a constant image stays constant (partition of unity).
        total = weights[i].sum()
        if total > 0.0:
            weights[i] /= total
        else:
            # Degenerate case (should not happen): fall back to nearest pixel.
            nearest = min(max(int(center), 0), src_size - 1)
            indices[i, :] = nearest
            weights[i, :] = 0.0
            weights[i, 0] = 1.0

    return indices, weights


def _resize_axis(
    plane: np.ndarray, indices: np.ndarray, weights: np.ndarray, axis: int
) -> np.ndarray:
    """Apply a precomputed resampling table along one axis of an RGBA plane.

    Accumulation is done in float64 to keep rounding error far below the
    final 8-bit quantization step.
    """
    taps = indices.shape[1]
    if axis == 0:
        # Vertical: output row i = weighted sum of source rows indices[i, :].
        out_shape = (indices.shape[0], plane.shape[1], plane.shape[2])
        out = np.zeros(out_shape, dtype=np.float64)
        for t in range(taps):
            out += plane[indices[:, t], :, :] * weights[:, t, None, None]
    else:
        # Horizontal: output column i = weighted sum of source columns.
        out_shape = (plane.shape[0], indices.shape[0], plane.shape[2])
        out = np.zeros(out_shape, dtype=np.float64)
        for t in range(taps):
            out += plane[:, indices[:, t], :] * weights[None, :, t, None]
    return out.astype(np.float32)


def resize_plane(
    plane: np.ndarray, width: int, height: int, filter_name: str = "lanczos3"
) -> np.ndarray:
    """Resize a float32 RGBA plane to (width, height).

    The filter runs on all four channels of the same plane in one pass, so
    RGB and alpha stay perfectly in sync. Upscaling and downscaling both use
    the same separable kernel with anti-aliasing.
    """
    if filter_name not in FILTERS:
        raise ValueError("Unknown filter: {!r}".format(filter_name))
    src_height, src_width = plane.shape[:2]
    # Fast path: nothing to do (also avoids building identity tables).
    if (src_width, src_height) == (width, height):
        return plane
    # Horizontal pass first, then vertical (separable convolution).
    out = plane
    if src_width != width:
        indices, weights = _resize_table(src_width, width, filter_name)
        out = _resize_axis(out, indices, weights, axis=1)
    if src_height != height:
        indices, weights = _resize_table(src_height, height, filter_name)
        out = _resize_axis(out, indices, weights, axis=0)
    return out


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------

def tile_plane(plane: np.ndarray, tiles_x: int, tiles_y: int) -> np.ndarray:
    """Repeat a plane tiles_x times horizontally and tiles_y times vertically.

    Used for UV islands that extend beyond the 0-1 range (the old code's
    _get_uv_image did the same with a manual paste loop; np.tile is the same
    math expressed in one line).
    """
    return np.tile(plane, (tiles_y, tiles_x, 1))


def paste_plane(
    canvas: np.ndarray, plane: np.ndarray, x: int, y: int
) -> np.ndarray:
    """Copy plane onto canvas at offset (x, y), clipping at canvas edges.

    This is a raw copy of all four channels (like PIL's paste without a
    mask): the source pixels REPLACE the destination pixels, including
    alpha. No blending is applied.
    """
    src_height, src_width = plane.shape[:2]
    dst_height, dst_width = canvas.shape[:2]

    # Clip the source rectangle against the canvas bounds.
    dst_x0, dst_y0 = max(x, 0), max(y, 0)
    dst_x1 = min(x + src_width, dst_width)
    dst_y1 = min(y + src_height, dst_height)
    if dst_x1 <= dst_x0 or dst_y1 <= dst_y0:
        # Fully outside the canvas: nothing to paste.
        return canvas

    # Map the clipped destination rectangle back into source coordinates.
    src_x0, src_y0 = dst_x0 - x, dst_y0 - y
    src_x1 = src_x0 + (dst_x1 - dst_x0)
    src_y1 = src_y0 + (dst_y1 - dst_y0)

    canvas[dst_y0:dst_y1, dst_x0:dst_x1] = plane[src_y0:src_y1, src_x0:src_x1]
    return canvas


def multiply_color(plane: np.ndarray, color: Sequence[float]) -> np.ndarray:
    """Multiply a plane by a linear RGBA color, channel by channel.

    Equivalent to the old ImageChops.multiply step for the "blend diffuse
    color" option, but in linear float32 instead of quantized sRGB bytes.
    With the usual color (r, g, b, 1.0) the alpha channel is unchanged.
    """
    factor = np.asarray(color, dtype=np.float32)
    return np.clip(plane * factor, 0.0, 1.0)


def renormalize_normals(plane: np.ndarray) -> np.ndarray:
    """Renormalize XYZ stored in RGB after resampling a normal map.

    Resizing blends vectors and shortens them; game shaders expect unit
    length. Pixels whose vector is zero (atlas padding areas) are left as-is
    so padding stays transparent black instead of becoming NaN.
    """
    out = np.array(plane, dtype=np.float32, copy=True)
    # Decode from [0, 1] texture space to [-1, 1] vector space.
    xyz = out[..., :3].astype(np.float64) * 2.0 - 1.0
    length = np.sqrt((xyz * xyz).sum(axis=-1, keepdims=True))
    # Only normalize pixels that actually contain a vector.
    nonzero = length[..., 0] > 1e-6
    safe_length = np.where(nonzero[..., None], length, 1.0)
    xyz = xyz / safe_length
    out[..., :3] = xyz * 0.5 + 0.5
    # Leave zero-vector pixels at their original value (padding areas).
    out[..., :3] = np.where(nonzero[..., None], out[..., :3], plane[..., :3])
    return out
