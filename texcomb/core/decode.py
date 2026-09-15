"""Decode encoded image bytes/files into float32 planes.

Decoding means: bytes -> straight-alpha RGBA -> float32 in [0, 1], and for
sRGB sources an additional conversion into linear space. All later pipeline
stages only ever see these normalized float32 planes.

Pillow is imported lazily so this module stays importable without it (the
pytest environment may lack Pillow; the Blender environment always has the
vendored copy from texcomb/libs on sys.path).

A texconv-based fallback for files Pillow cannot decode (exotic DDS formats)
is added by Phase 3 in texconv.py; this module stays the Pillow fast path.
"""

import io
import os
from typing import Optional

import numpy as np

from . import pixels

# Cache for the lazily-imported PIL.Image module (None = not tried yet,
# False = tried and unavailable).
_pil_image: Optional[object] = None


def _load_pil():
    """Import PIL.Image lazily, with a clear error when it is missing."""
    global _pil_image
    if _pil_image is not None:
        return _pil_image
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError(
            "Pillow is required to decode image bytes; install it or run "
            "inside Blender where the addon vendors it in texcomb/libs"
        ) from exc
    _pil_image = Image
    return Image


def decode_bytes(data: bytes, srgb: bool = True) -> np.ndarray:
    """Decode encoded image bytes (PNG/TGA/DDS/...) into a float32 plane.

    Args:
        data: the encoded file bytes (e.g. a PackedFile's data).
        srgb: True for color textures (base color, emission): the plane is
            converted to linear space. False for data textures (normal maps,
            masks): values pass through unchanged.

    Returns:
        A float32 plane of shape (H, W, 4), linear if srgb else raw.
    """
    image = _load_pil()
    with image.open(io.BytesIO(data)) as opened:
        # Normalize every source mode (P, LA, CMYK, 16-bit, DDS codecs, ...)
        # to straight-alpha 8-bit RGBA first.
        rgba = opened.convert("RGBA")
        raw = np.asarray(rgba, dtype=np.uint8)

    plane = pixels.from_uint8(raw)
    if srgb:
        plane = pixels.srgb_to_linear(plane)
    return plane


def decode_file(path: str, srgb: bool = True) -> np.ndarray:
    """Decode an image file from disk into a float32 plane.

    Reading the bytes first (instead of letting Pillow open the path) keeps
    one code path for both packed and on-disk images, and lets Phase 3 route
    undecodable files through texconv without changing callers.
    """
    with open(path, "rb") as handle:
        data = handle.read()
    return decode_bytes(data, srgb=srgb)


def image_size_of(path: str) -> tuple:
    """Return the (width, height) of an image file without decoding pixels.

    Used by the layout stage, which needs sizes long before any pixel work.
    """
    image = _load_pil()
    with image.open(path) as opened:
        return tuple(opened.size)


def is_probably_dds(path: str) -> bool:
    """Cheap extension check used to decide decode strategies later."""
    return os.path.splitext(path)[1].lower() == ".dds"
