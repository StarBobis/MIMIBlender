"""Unit tests for texcomb.core.decode and texcomb.core.export.

These need Pillow; the pytest environment has it installed as a user package
(inside Blender the addon's vendored copy is used instead).
"""

import numpy as np
import pytest

from texcomb.core import decode, export, pixels

pytest.importorskip("PIL.Image")


class TestRoundTrip:
    """encode -> decode must be lossless at 8-bit precision."""

    def test_srgb_png_round_trip(self):
        # A small gradient in LINEAR space, as the pipeline would produce.
        ramp = np.linspace(0.0, 1.0, 16, dtype=np.float32).reshape(4, 4)
        plane = np.stack([ramp, ramp, ramp, np.ones_like(ramp)], axis=-1)

        data = export.encode_bytes(plane, "PNG", srgb=True)
        decoded = decode.decode_bytes(data, srgb=True)

        # Compare in sRGB space, not linear space: 8-bit sRGB quantization is
        # non-uniform (finer in darks, coarser in brights), so an sRGB round
        # trip can legitimately shift LINEAR values by more than half a linear
        # step. In sRGB space the round trip is exact for every byte value
        # (proven exhaustively in test_pixels).
        assert np.array_equal(
            pixels.to_uint8(pixels.linear_to_srgb(decoded)),
            pixels.to_uint8(pixels.linear_to_srgb(plane)),
        )

    def test_non_srgb_png_round_trip_is_exact(self):
        ramp = np.linspace(0.0, 1.0, 16, dtype=np.float32).reshape(4, 4)
        plane = np.stack([ramp, ramp, ramp, np.ones_like(ramp)], axis=-1)

        data = export.encode_bytes(plane, "PNG", srgb=False)
        decoded = decode.decode_bytes(data, srgb=False)

        assert np.array_equal(pixels.to_uint8(decoded), pixels.to_uint8(plane))

    def test_tga_preserves_alpha(self):
        plane = pixels.new_plane(2, 2, (0.5, 0.5, 0.5, 0.25))
        data = export.encode_bytes(plane, "TGA", srgb=False)
        decoded = decode.decode_bytes(data, srgb=False)
        # TGA stores straight alpha; 0.25 must survive as 64/255.
        assert np.allclose(decoded[..., 3], 64 / 255.0, atol=1e-6)

    def test_decode_converts_srgb_to_linear(self):
        # sRGB byte 128 (~0.502) must decode to linear ~0.2158.
        image = export.to_bytes_image(pixels.new_plane(1, 1, (0.2158,) * 3 + (1.0,)), srgb=True)
        import io

        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        decoded = decode.decode_bytes(buffer.getvalue(), srgb=True)
        assert decoded[0, 0, 0] == pytest.approx(0.2158, abs=2e-3)


class TestSaveImage:
    def test_save_and_reread_file(self, tmp_path):
        plane = pixels.new_plane(2, 2, (0.1, 0.2, 0.3, 1.0))
        path = str(tmp_path / "out.png")
        assert export.save_image(plane, path) == path
        decoded = decode.decode_file(path, srgb=True)
        assert decoded.shape == (2, 2, 4)

    def test_unknown_extension_raises(self, tmp_path):
        plane = pixels.new_plane(1, 1)
        with pytest.raises(ValueError, match="format"):
            export.save_image(plane, str(tmp_path / "out.xyz"))

    def test_unknown_format_raises(self):
        plane = pixels.new_plane(1, 1)
        with pytest.raises(ValueError, match="Unsupported format"):
            export.encode_bytes(plane, "EXR")
