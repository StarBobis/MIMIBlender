"""Encode float32 planes into image files.

This module is the ONLY place in the pipeline where precision is reduced to
8 bits per channel, and it happens exactly once per output image.

Phase 3 adds DDS output through texconv.exe; everything here stays Pillow so
the PNG/TGA/TIFF/BMP path keeps working without external tools.
"""

import io
import os
import tempfile
from typing import Optional

import numpy as np

from . import pixels

# Output formats the old addon supported; DDS joins them via texconv later.
FORMATS = ("PNG", "TGA", "TIFF", "BMP")

# File extensions per format, used when the caller gives only a directory.
EXTENSIONS = {"PNG": ".png", "TGA": ".tga", "TIFF": ".tif", "BMP": ".bmp"}

# Cache for the lazily-imported PIL.Image module (None = not tried yet).
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
            "Pillow is required to encode images; install it or run inside "
            "Blender where the addon vendors it in texcomb/libs"
        ) from exc
    _pil_image = Image
    return Image


def to_bytes_image(plane: np.ndarray, srgb: bool = True):
    """Convert a float32 plane into an 8-bit PIL RGBA image.

    Args:
        plane: float32 plane in LINEAR space.
        srgb: True for color outputs (applies the linear->sRGB conversion);
            False for data outputs (normal maps, masks) whose values must be
            written unchanged.
    """
    image = _load_pil()
    out = plane
    if srgb:
        out = pixels.linear_to_srgb(out)
    # The single quantization step of the whole pipeline.
    return image.fromarray(pixels.to_uint8(out), "RGBA")


def encode_bytes(
    plane: np.ndarray, image_format: str = "PNG", srgb: bool = True
) -> bytes:
    """Encode a float32 plane into image file bytes of the given format."""
    if image_format not in FORMATS:
        raise ValueError(
            "Unsupported format {!r} (expected one of {})".format(
                image_format, FORMATS
            )
        )
    buffer = io.BytesIO()
    to_bytes_image(plane, srgb=srgb).save(buffer, format=image_format)
    return buffer.getvalue()


def save_image(
    plane: np.ndarray,
    path: str,
    image_format: Optional[str] = None,
    srgb: bool = True,
) -> str:
    """Save a float32 plane to path; returns the path actually written.

    The format defaults to the file extension when not given explicitly.
    """
    if image_format is None:
        # Infer the format from the file extension (".png" -> "PNG").
        extension = os.path.splitext(path)[1].lower().lstrip(".")
        image_format = {
            "png": "PNG",
            "tga": "TGA",
            "tif": "TIFF",
            "tiff": "TIFF",
            "bmp": "BMP",
        }.get(extension)
        if image_format is None:
            raise ValueError(
                "Cannot infer image format from path: {!r}".format(path)
            )
    data = encode_bytes(plane, image_format=image_format, srgb=srgb)
    with open(path, "wb") as handle:
        handle.write(data)
    return path


def save_dds(
    plane: np.ndarray,
    path: str,
    dds_format: str,
    mipmaps: bool = True,
    srgb: bool = True,
    texconv_path: str = "",
) -> str:
    """Save a float32 plane as a DDS file via texconv.exe.

    The plane is first written to a temporary lossless 8-bit PNG (all DDS
    output formats we support are 8-bit per channel, so no precision is
    lost), then converted by texconv, which controls the exact DXGI format,
    the sRGB tag, and mipmap generation. Raises RuntimeError when texconv is
    unavailable so callers can fall back to PNG with a clear message.
    """
    from . import texconv

    with tempfile.TemporaryDirectory(prefix="texcomb_dds_") as tmpdir:
        # The PNG carries the exact final 8-bit values; texconv only
        # repackages them into the requested DDS format.
        png_path = os.path.join(tmpdir, "atlas.png")
        save_image(plane, png_path, image_format="PNG", srgb=srgb)
        texconv.convert_png_to_dds(
            png_path,
            path,
            dds_format=dds_format,
            mipmaps=mipmaps,
            srgb=srgb,
            explicit_path=texconv_path,
        )
    return path
