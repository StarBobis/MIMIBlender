"""Unit tests for texcomb.core.pixels (float32 plane operations).

These tests run outside Blender: the core package must stay bpy-free.
"""

import numpy as np
import pytest

from texcomb.core import pixels


class TestSrgbConversion:
    """sRGB <-> linear conversion correctness."""

    def test_known_values(self):
        # Build a 1x3 plane with black, mid gray, white in RGB.
        plane = pixels.new_plane(3, 1)
        plane[0, 0] = (0.0, 0.0, 0.0, 0.5)
        plane[0, 1] = (0.5, 0.5, 0.5, 0.5)
        plane[0, 2] = (1.0, 1.0, 1.0, 0.5)

        linear = pixels.srgb_to_linear(plane)

        # Black and white are fixed points of the transfer function.
        assert linear[0, 0, 0] == pytest.approx(0.0, abs=1e-7)
        assert linear[0, 2, 0] == pytest.approx(1.0, abs=1e-7)
        # sRGB 0.5 maps to linear ~0.2140 (the well-known midpoint value).
        assert linear[0, 1, 0] == pytest.approx(0.21404114, abs=1e-6)

    def test_alpha_is_never_converted(self):
        # Alpha is data and must pass through both conversions untouched.
        plane = pixels.new_plane(1, 1, (0.25, 0.5, 0.75, 0.3))
        assert pixels.srgb_to_linear(plane)[0, 0, 3] == pytest.approx(0.3)
        assert pixels.linear_to_srgb(plane)[0, 0, 3] == pytest.approx(0.3)

    def test_uint8_round_trip_is_exact(self):
        # Every one of the 256 byte values must survive the round trip
        # sRGB -> linear -> sRGB -> uint8 unchanged (float64 accumulation
        # keeps the error far below half a step).
        values = np.arange(256, dtype=np.float32) / 255.0
        plane = np.stack([values, values, values, np.ones_like(values)], axis=-1)
        plane = plane.reshape(16, 16, 4)
        round_trip = pixels.to_uint8(
            pixels.linear_to_srgb(pixels.srgb_to_linear(plane))
        )
        assert np.array_equal(round_trip[..., 0].ravel(), np.arange(256, dtype=np.uint8))


class TestResize:
    """Resampling filters: precision and channel synchronization."""

    def test_box_downscale_is_area_average(self):
        # 4x4 -> 2x2 with the box filter must produce exact 2x2 area averages.
        ramp = np.arange(16, dtype=np.float32).reshape(4, 4)
        plane = np.stack([ramp, ramp, ramp, np.ones((4, 4), np.float32)], axis=-1)
        out = pixels.resize_plane(plane, 2, 2, "box")
        # Top-left output pixel averages source values 0, 1, 4, 5.
        assert out[0, 0, 0] == pytest.approx(2.5, abs=1e-6)
        # Bottom-right averages 10, 11, 14, 15.
        assert out[1, 1, 0] == pytest.approx(12.5, abs=1e-6)

    @pytest.mark.parametrize("filter_name", ["box", "bilinear", "lanczos3"])
    def test_constant_plane_survives_any_resize(self, filter_name):
        # Partition of unity: a flat image must stay flat under any filter
        # and any scale direction. This catches broken weight normalization.
        plane = pixels.new_plane(4, 4, (0.3, 0.6, 0.9, 0.4))
        up = pixels.resize_plane(plane, 16, 16, filter_name)
        down = pixels.resize_plane(plane, 2, 2, filter_name)
        assert np.allclose(up, (0.3, 0.6, 0.9, 0.4), atol=1e-5)
        assert np.allclose(down, (0.3, 0.6, 0.9, 0.4), atol=1e-5)

    def test_all_channels_resize_in_one_operation(self):
        # With identical patterns in R and A, both channels must come out
        # bit-identical after resizing: RGB and A can never drift apart.
        pattern = np.arange(64, dtype=np.float32).reshape(8, 8) / 63.0
        zeros = np.zeros_like(pattern)
        plane = np.stack([pattern, zeros, zeros, pattern], axis=-1)
        out = pixels.resize_plane(plane, 5, 3, "lanczos3")
        assert out.shape == (3, 5, 4)
        assert np.array_equal(out[..., 0], out[..., 3])

    def test_same_size_is_returned_unchanged(self):
        plane = pixels.new_plane(4, 4, (0.1, 0.2, 0.3, 0.4))
        out = pixels.resize_plane(plane, 4, 4)
        assert np.array_equal(out, plane)

    def test_unknown_filter_raises(self):
        plane = pixels.new_plane(2, 2)
        with pytest.raises(ValueError):
            pixels.resize_plane(plane, 4, 4, "cubic-whatever")


class TestComposition:
    """Tiling, pasting, multiply, normal renormalization."""

    def test_tile_repeats_in_both_directions(self):
        plane = pixels.new_plane(2, 1, (1.0, 0.0, 0.0, 1.0))
        tiled = pixels.tile_plane(plane, 3, 2)
        assert tiled.shape == (2, 6, 4)
        assert np.allclose(tiled, (1.0, 0.0, 0.0, 1.0))

    def test_paste_replaces_pixels_raw(self):
        # Paste must REPLACE destination pixels including alpha (no blending).
        canvas = pixels.new_plane(4, 4, (0.0, 0.0, 0.0, 0.0))
        patch = pixels.new_plane(2, 2, (1.0, 1.0, 1.0, 0.7))
        pixels.paste_plane(canvas, patch, 1, 1)
        assert np.allclose(canvas[1, 1], (1.0, 1.0, 1.0, 0.7))
        assert np.allclose(canvas[0, 0], (0.0, 0.0, 0.0, 0.0))

    def test_paste_clips_negative_offset(self):
        # A 2x2 patch at (-1, -1): only its bottom-right pixel lands, at (0, 0).
        canvas = pixels.new_plane(4, 4)
        patch = pixels.new_plane(2, 2, (1.0, 1.0, 1.0, 1.0))
        pixels.paste_plane(canvas, patch, -1, -1)
        assert np.allclose(canvas[0, 0], 1.0)
        assert np.allclose(canvas[0, 1], 0.0)
        assert np.allclose(canvas[1, 0], 0.0)

    def test_paste_fully_outside_is_noop(self):
        canvas = pixels.new_plane(4, 4)
        patch = pixels.new_plane(2, 2, (1.0, 1.0, 1.0, 1.0))
        pixels.paste_plane(canvas, patch, 100, 100)
        assert np.allclose(canvas, 0.0)

    def test_multiply_color(self):
        plane = pixels.new_plane(1, 1, (0.5, 0.5, 0.5, 0.8))
        out = pixels.multiply_color(plane, (0.5, 0.25, 1.0, 1.0))
        # RGB are scaled; alpha is multiplied by 1.0 and therefore kept.
        assert np.allclose(out[0, 0], (0.25, 0.125, 0.5, 0.8))

    def test_renormalize_normals(self):
        plane = pixels.new_plane(2, 1)
        # A shortened vector that resizing might produce.
        plane[0, 0] = (0.6, 0.5, 0.9, 1.0)  # xyz = (0.2, 0.0, 0.8)
        # A zero vector, e.g. transparent padding (0.5, 0.5, 0.5).
        plane[0, 1] = (0.5, 0.5, 0.5, 0.0)
        out = pixels.renormalize_normals(plane)
        # The nonzero vector must come out at unit length.
        xyz = out[0, 0, :3] * 2.0 - 1.0
        assert float(np.linalg.norm(xyz)) == pytest.approx(1.0, abs=1e-5)
        # The zero vector must stay exactly as it was (no NaN, no explosion).
        assert np.allclose(out[0, 1], (0.5, 0.5, 0.5, 0.0))


class TestQuantization:
    """uint8 conversion helpers."""

    def test_to_uint8_clips_and_rounds(self):
        plane = pixels.new_plane(2, 1)
        plane[0, 0] = (-0.5, 0.5, 1.5, 1.0)
        plane[0, 1] = (128 / 255.0, 127 / 255.0, 0.0, 1.0)
        out = pixels.to_uint8(plane)
        # Out-of-range values clip to 0 / 255; 0.5 rounds to 128.
        assert tuple(out[0, 0]) == (0, 128, 255, 255)
        assert tuple(out[0, 1][:2]) == (128, 127)

    def test_from_uint8_scales_to_unit_range(self):
        arr = np.zeros((1, 1, 4), dtype=np.uint8)
        arr[0, 0] = (255, 128, 0, 51)
        out = pixels.from_uint8(arr)
        assert out.dtype == np.float32
        assert out[0, 0, 0] == pytest.approx(1.0)
        assert out[0, 0, 1] == pytest.approx(128 / 255.0)
