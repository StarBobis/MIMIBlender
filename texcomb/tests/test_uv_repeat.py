"""Regression checks for repeated atlas content, independent of Blender."""

import numpy as np
import pytest

from texcomb.core import pixels


@pytest.mark.parametrize("repeat", [(1, 1), (2, 3), (1.5, 1.25)])
def test_repeat_keeps_original_texels(repeat):
    # Each channel contains unique values so shifts and flips are visible.
    tile = np.arange(4 * 4 * 4, dtype=np.float32).reshape(4, 4, 4) / 64
    width = int(4 * repeat[0])
    height = int(4 * repeat[1])
    result = pixels.repeat_plane(tile, repeat, (width, height))
    # Compare in UV order: V=0 is the bottom, not array row zero.
    for y in range(height):
        for x in range(width):
            np.testing.assert_array_equal(result[-1-y, x], tile[-1-(y % 4), x % 4])
    # Building repeated content must not modify the shared decode cache.
    assert tile[0, 0, 0] == 0


def test_uniform_size_resizes_the_repeated_plane():
    # Box filtering at this integer scale keeps repeated cells exact.
    tile = pixels.new_plane(2, 2)
    tile[:, 0, 0] = 1
    result = pixels.repeat_plane(tile, (2, 1), (8, 2), "box")
    # The second copy must be present rather than one stretched source tile.
    np.testing.assert_array_equal(result[0, :, 0], [1, 1, 0, 0, 1, 1, 0, 0])
