"""Unit and integration tests for texcomb.core.texconv.

Unit tests cover the locator logic. Integration tests run the real,
hash-verified texconv.exe bundled in texcomb/tools/ and are skipped when it
is unavailable (e.g. a minimal CI environment).
"""

import os
import struct

import numpy as np
import pytest

from texcomb.core import decode, export, pixels, texconv

# DXGI_FORMAT enum values (from Microsoft's dxgiformat.h).
DXGI_FORMAT = {
    "R8G8B8A8_UNORM": 28,
    "R8G8B8A8_UNORM_SRGB": 29,
    "BC3_UNORM": 77,
    "BC3_UNORM_SRGB": 78,
    "BC7_UNORM": 98,
    "BC7_UNORM_SRGB": 99,
}


def _read_dds_header(path):
    """Parse the DDS header fields the tests assert on.

    Layout: magic(4) | dwSize(4) dwFlags(4) dwHeight(4) dwWidth(4)
    dwPitchOrLinearSize(4) dwDepth(4) dwMipMapCount(4) ... pf.dwFourCC @84 |
    DX10 header dxgiFormat @128 (only when dwFourCC == "DX10").
    """
    with open(path, "rb") as handle:
        data = handle.read(148)
    assert data[:4] == b"DDS ", "missing DDS magic bytes"
    height, width = struct.unpack_from("<II", data, 12)
    mip_count = struct.unpack_from("<I", data, 28)[0]
    fourcc = data[84:88]
    dxgi = struct.unpack_from("<I", data, 128)[0] if fourcc == b"DX10" else None
    return width, height, mip_count, dxgi


def _test_plane():
    """A 4x4 plane with distinct RGB and a varying alpha ramp."""
    ramp = np.linspace(0.25, 1.0, 16, dtype=np.float32).reshape(4, 4)
    red = np.full((4, 4), 0.5, dtype=np.float32)
    green = np.full((4, 4), 0.25, dtype=np.float32)
    return np.stack([red, green, ramp, ramp], axis=-1)


class TestLocator:
    """texconv.exe lookup order and graceful absence."""

    def test_bundled_copy_is_found(self):
        # The repo bundles a hash-verified texconv.exe in texcomb/tools/.
        found = texconv.find_texconv()
        assert found
        assert found.lower().endswith("texconv.exe")

    def test_explicit_path_wins(self, tmp_path):
        fake = tmp_path / "texconv.exe"
        fake.write_bytes(b"MZ")
        assert texconv.find_texconv(str(fake)) == str(fake)

    def test_env_var_used_when_no_explicit(self, tmp_path, monkeypatch):
        fake = tmp_path / "texconv-custom.exe"
        fake.write_bytes(b"MZ")
        monkeypatch.setenv(texconv.ENV_VAR, str(fake))
        assert texconv.find_texconv() == str(fake)

    def test_missing_everything_returns_empty(self, monkeypatch):
        monkeypatch.delenv(texconv.ENV_VAR, raising=False)
        monkeypatch.setattr(texconv, "_bundled_path", lambda: "nope.exe")
        monkeypatch.setattr(texconv.shutil, "which", lambda name: None)
        assert texconv.find_texconv() == ""
        assert not texconv.is_available()

    def test_invalid_format_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="DDS format"):
            texconv.convert_png_to_dds(
                "in.png", str(tmp_path / "out.dds"), "BC1_UNORM"
            )


requires_texconv = pytest.mark.skipif(
    not texconv.is_available(), reason="texconv.exe not available"
)


@requires_texconv
class TestConversion:
    """Real texconv.exe conversions (slow is fine; precise is required)."""

    def test_rgba_srgb_round_trip_is_byte_exact(self, tmp_path):
        # plane -> PNG -> DDS(R8G8B8A8_UNORM_SRGB) -> PNG must return the
        # exact same 8-bit values: texconv repackages bytes, it does not
        # reinterpret them (the -srgbi/-srgbo pair prevents conversion).
        plane = _test_plane()
        png_path = export.save_image(
            plane, str(tmp_path / "atlas.png"), srgb=True
        )
        dds_path = texconv.convert_png_to_dds(
            png_path,
            str(tmp_path / "atlas.dds"),
            dds_format="R8G8B8A8_UNORM_SRGB",
            mipmaps=False,
            srgb=True,
        )

        width, height, mips, dxgi = _read_dds_header(dds_path)
        assert (width, height) == (4, 4)
        assert mips == 1
        assert dxgi == DXGI_FORMAT["R8G8B8A8_UNORM_SRGB"]

        with open(dds_path, "rb") as handle:
            png_back = texconv.convert_dds_bytes_to_png(handle.read())
        decoded = decode.decode_bytes(png_back, srgb=False)
        expected = pixels.to_uint8(pixels.linear_to_srgb(plane))
        assert np.array_equal(pixels.to_uint8(decoded), expected)

    def test_full_mipmap_chain(self, tmp_path):
        # A 4x4 image has 3 mip levels (4x4, 2x2, 1x1). BC7 is used here
        # because texconv always writes a DX10 header for BC7, which makes
        # the DXGI format assertable (uncompressed UNORM formats get legacy
        # bitmask headers instead).
        plane = _test_plane()
        png_path = export.save_image(plane, str(tmp_path / "mips.png"), srgb=True)
        dds_path = texconv.convert_png_to_dds(
            png_path,
            str(tmp_path / "mips.dds"),
            dds_format="BC7_UNORM",
            mipmaps=True,
            srgb=False,
        )
        _, _, mips, dxgi = _read_dds_header(dds_path)
        assert mips == 3
        assert dxgi == DXGI_FORMAT["BC7_UNORM"]

    def test_bc7_format_tag(self, tmp_path):
        plane = _test_plane()
        png_path = export.save_image(plane, str(tmp_path / "bc7.png"), srgb=True)
        dds_path = texconv.convert_png_to_dds(
            png_path,
            str(tmp_path / "bc7.dds"),
            dds_format="BC7_UNORM_SRGB",
            mipmaps=False,
            srgb=True,
        )
        _, _, _, dxgi = _read_dds_header(dds_path)
        assert dxgi == DXGI_FORMAT["BC7_UNORM_SRGB"]

    def test_save_dds_end_to_end(self, tmp_path):
        # export.save_dds wraps PNG staging + texconv in one call.
        plane = _test_plane()
        target = str(tmp_path / "direct.dds")
        result = export.save_dds(
            plane, target, "R8G8B8A8_UNORM_SRGB", mipmaps=False, srgb=True
        )
        assert result == target
        width, height, _, dxgi = _read_dds_header(target)
        assert (width, height) == (4, 4)
        assert dxgi == DXGI_FORMAT["R8G8B8A8_UNORM_SRGB"]
