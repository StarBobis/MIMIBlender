"""Virtual repeat sampling must equal the former fully tiled pixel pipeline.

Square repeat envelopes preserve source aspect but can cover many source tiles.
Production must not allocate a giant repeated source just to downsize it.
The small reference images below deliberately use the old implementation.
Whole grids and fractional V crops must keep identical filtering and phase.
This oracle also covers grids bigger than the final output in both axes.
"""
import math
from unittest.mock import patch

import numpy as np
import pytest

from texcomb.core import pixels


@pytest.mark.parametrize("repeat", [(1, 1), (2, 8), (8, 8), (1.5, 1.25), (1.1, 6.07)])
@pytest.mark.parametrize("size", [(7, 5), (32, 24), (64, 64)])
@pytest.mark.parametrize("filter_name", ["box", "bilinear", "lanczos3"])
def test_virtual_sampling_matches_materialized_reference(repeat, size, filter_name):
    # Non-square, non-constant tiles expose incorrect row offsets and wrapping.
    source = np.random.default_rng(42).random((6, 8, 4), dtype=np.float32)
    tiled = np.tile(source, (math.ceil(repeat[1]), math.ceil(repeat[0]), 1))
    cropped = tiled[-math.ceil(6 * repeat[1]):, :math.ceil(8 * repeat[0])]
    expected = pixels.resize_plane(cropped, *size, filter_name)
    # Reject the old memory-intensive allocation even if the pixels are right.
    # Indexing must reproduce the exact same clamped outer edges as before.
    with patch.object(pixels.np, "tile", side_effect=AssertionError("Materialized grid")):
        actual = pixels.repeat_plane(source, repeat, size, filter_name)
    np.testing.assert_allclose(actual, expected, atol=1e-6)


def test_unscaled_fractional_grid_uses_bottom_crop():
    # This takes both direct-index paths without invoking any filtering table.
    source = np.arange(6 * 8 * 4, dtype=np.float32).reshape(6, 8, 4)
    expected = np.tile(source, (2, 2, 1))[-8:, :12]
    np.testing.assert_array_equal(pixels.repeat_plane(source, (1.5, 1.25), (12, 8)), expected)
