"""Unit tests for texcomb.core.atlas (canvas composition and sizing)."""

import numpy as np

from texcomb.core import atlas, pixels


class TestComposeAtlas:
    def test_planes_land_at_their_positions(self):
        red = pixels.new_plane(2, 2, (1.0, 0.0, 0.0, 1.0))
        green = pixels.new_plane(2, 2, (0.0, 1.0, 0.0, 0.5))
        canvas = atlas.compose_atlas([(red, 0, 0), (green, 2, 2)], (4, 4))

        # Top-left quadrant is red, bottom-right is green with alpha 0.5.
        assert np.allclose(canvas[0, 0], (1.0, 0.0, 0.0, 1.0))
        assert np.allclose(canvas[3, 3], (0.0, 1.0, 0.0, 0.5))

    def test_background_is_transparent_black(self):
        canvas = atlas.compose_atlas([], (2, 2))
        assert np.allclose(canvas, 0.0)

    def test_canvas_size_matches_request(self):
        canvas = atlas.compose_atlas([], (7, 3))
        assert canvas.shape == (3, 7, 4)


class TestFitCanvasTo:
    def test_cust_scales_down_keeping_aspect(self):
        canvas = atlas.compose_atlas([], (8, 4))
        out = atlas.fit_canvas_to(canvas, "CUST", (4, 4))
        # 8x4 must shrink to fit 4x4 keeping aspect: 4x2.
        assert out.shape == (2, 4, 4)

    def test_cust_never_enlarges(self):
        canvas = atlas.compose_atlas([], (4, 4))
        out = atlas.fit_canvas_to(canvas, "CUST", (8, 8))
        assert out.shape == (4, 4, 4)

    def test_strictcust_pads_to_exact_size(self):
        canvas = atlas.compose_atlas([], (8, 4))
        out = atlas.fit_canvas_to(canvas, "STRICTCUST", (4, 4))
        # Scaled to 4x2, then pasted onto an exact 4x4 canvas.
        assert out.shape == (4, 4, 4)

    def test_other_strategies_pass_through(self):
        canvas = atlas.compose_atlas([], (8, 4))
        assert atlas.fit_canvas_to(canvas, "PO2", None) is canvas
        assert atlas.fit_canvas_to(canvas, "AUTO", None) is canvas
