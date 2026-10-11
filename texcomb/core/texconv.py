"""Wrapper around Microsoft's texconv.exe for precise DDS output.

texconv (from the DirectXTex project, MIT licensed) is the reference tool
for DDS conversion: it controls the exact DXGI format, the sRGB tag, and
mipmap generation — everything Pillow's DDS writer cannot do.

This module is pure python (subprocess only, no bpy) and degrades cleanly:
when texconv.exe cannot be found, is_available() is False and callers fall
back to PNG output / Pillow decoding.

The addon bundles a hash-verified copy at texcomb/tools/texconv.exe.
Lookup order: explicit path -> TEXCONV_PATH env var -> bundled copy -> PATH.
"""

import os
import shutil
import struct
import subprocess
import tempfile

# DXGI output formats the user can pick for DDS export (subset that makes
# sense for game modding pipelines). Names are texconv's own identifiers.
DDS_FORMATS = (
    "R8G8B8A8_UNORM_SRGB",
    "R8G8B8A8_UNORM",
    "BC7_UNORM_SRGB",
    "BC7_UNORM",
    "BC3_UNORM_SRGB",
    "BC3_UNORM",
)

# The default matches the WWMI/3DMigoto naming convention this repo uses.
DEFAULT_DDS_FORMAT = "R8G8B8A8_UNORM_SRGB"

# Environment variable holding a user-provided texconv.exe path.
ENV_VAR = "TEXCONV_PATH"

# Conversion timeout: generous, precision matters more than speed.
_TIMEOUT_SECONDS = 600


def _bundled_path() -> str:
    """Return the path of the texconv.exe bundled with the addon."""
    # This file is texcomb/core/texconv.py; the tool sits in texcomb/tools/.
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(here), "tools", "texconv.exe")


def find_texconv(explicit_path: str = "") -> str:
    """Locate a usable texconv.exe; returns "" when none is found.

    Args:
        explicit_path: optional user-configured path (highest priority).
    """
    candidates = [
        explicit_path,
        os.environ.get(ENV_VAR, ""),
        _bundled_path(),
        shutil.which("texconv") or "",
    ]
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return candidate
    return ""


def is_available(explicit_path: str = "") -> bool:
    """Return True when a texconv.exe can be located."""
    return bool(find_texconv(explicit_path))


def _run_texconv(args, explicit_path: str = "") -> subprocess.CompletedProcess:
    """Run texconv with the given arguments; raises RuntimeError on failure."""
    exe = find_texconv(explicit_path)
    if not exe:
        raise RuntimeError(
            "texconv.exe not found; set the {} environment variable or place "
            "texconv.exe next to the addon under texcomb/tools/".format(ENV_VAR)
        )
    try:
        result = subprocess.run(
            [exe] + args,
            capture_output=True,
            # Bytes mode on purpose: texconv's progress output can contain
            # non-UTF-8 bytes, which would crash text-mode decoding inside
            # a subprocess reader thread. Decoded lazily, only for errors.
            timeout=_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("texconv timed out after {}s".format(_TIMEOUT_SECONDS)) from exc
    if result.returncode != 0:
        output = (result.stdout or b"").decode("utf-8", errors="replace").strip()
        error = (result.stderr or b"").decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            "texconv failed with exit code {}: {}".format(
                result.returncode, output or error
            )
        )
    return result


def _verify_dds_header(path: str, width: int, height: int) -> None:
    """Cheap structural check of a produced DDS file.

    Validates the magic bytes and the expected dimensions so a silent
    conversion failure can never slip through as an empty/corrupt file.
    """
    with open(path, "rb") as handle:
        header = handle.read(20)
    if len(header) < 20 or header[:4] != b"DDS ":
        raise RuntimeError("texconv output is not a DDS file: {}".format(path))
    # DDS_HEADER layout: dwSize(4) dwFlags(4) dwHeight(4) dwWidth(4).
    file_height, file_width = struct.unpack_from("<II", header, 12)
    if (file_width, file_height) != (width, height):
        raise RuntimeError(
            "texconv output size mismatch: expected {}x{}, got {}x{}".format(
                width, height, file_width, file_height
            )
        )


def convert_png_to_dds(
    png_path: str,
    output_path: str,
    dds_format: str = DEFAULT_DDS_FORMAT,
    mipmaps: bool = True,
    srgb: bool = True,
    explicit_path: str = "",
) -> str:
    """Convert a PNG file to DDS via texconv; returns output_path.

    Args:
        png_path: input PNG (8-bit, written by core.export).
        output_path: desired .dds file path.
        dds_format: one of DDS_FORMATS.
        mipmaps: True generates the full mip chain; False keeps level 0 only.
        srgb: True when the PNG holds sRGB-encoded color bytes. The
            matching -srgbi/-srgbo flag pair is passed so texconv tags the
            output WITHOUT converting the pixel values.
        explicit_path: optional user-configured texconv.exe path.
    """
    if dds_format not in DDS_FORMATS:
        raise ValueError(
            "Unsupported DDS format {!r} (expected one of {})".format(
                dds_format, DDS_FORMATS
            )
        )

    output_dir = os.path.dirname(os.path.abspath(output_path))
    args = [
        "-f", dds_format,
        "-m", "0" if mipmaps else "1",
        "-y",               # overwrite existing files without asking
        "-o", output_dir,   # texconv writes <name>.dds next to the source name
    ]
    if srgb:
        # Mark input AND output as sRGB: the bytes pass through unchanged
        # and the DDS gets the correct _SRGB format tag.
        args += ["-srgbi", "-srgbo"]
    args.append(png_path)
    _run_texconv(args, explicit_path)

    # texconv names the output after the input file; rename if different.
    produced = os.path.join(
        output_dir, os.path.splitext(os.path.basename(png_path))[0] + ".dds"
    )
    if not os.path.isfile(produced):
        raise RuntimeError("texconv produced no output for {}".format(png_path))
    if os.path.abspath(produced) != os.path.abspath(output_path):
        # Remove a stale target first so the rename cannot fail.
        if os.path.isfile(output_path):
            os.remove(output_path)
        os.replace(produced, output_path)

    _verify_dds_header(output_path, *decode_dimensions_of_png(png_path))
    return output_path


def decode_dimensions_of_png(path: str):
    """Read (width, height) from a PNG header without decoding it."""
    with open(path, "rb") as handle:
        # PNG signature (8 bytes) + IHDR length/type (8 bytes) then w/h.
        header = handle.read(24)
    if len(header) < 24:
        raise RuntimeError("Not a PNG file: {}".format(path))
    return struct.unpack(">II", header[16:24])


def convert_dds_bytes_to_png(data: bytes, explicit_path: str = "") -> bytes:
    """Decode DDS bytes to PNG bytes via texconv (universal DDS fallback).

    Used when Pillow cannot decode a DDS variant (float formats, future
    DXGI formats). Slow is fine: this path only runs as a fallback.
    """
    with tempfile.TemporaryDirectory(prefix="texcomb_texconv_") as tmpdir:
        src = os.path.join(tmpdir, "input.dds")
        with open(src, "wb") as handle:
            handle.write(data)
        _run_texconv(["-ft", "PNG", "-y", "-o", tmpdir, src], explicit_path)
        png_path = os.path.join(tmpdir, "input.png")
        if not os.path.isfile(png_path):
            raise RuntimeError("texconv produced no PNG for a DDS input")
        with open(png_path, "rb") as handle:
            return handle.read()
