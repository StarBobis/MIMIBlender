"""Landscape rotation preserves sampled colors and tangent-space normals."""

import numpy as np

from texcomb.core import atlas, pixels


def test_clockwise_rotation_matches_uv_transform():
    # Encode unique per-pixel values to catch wrong rotation or axis flips.
    source = np.arange(8 * 4 * 4, dtype=np.float32).reshape(8, 4, 4)
    rotated = atlas.rotate_landscape(source)
    assert rotated.shape == (4, 8, 4)
    for y in range(8):
        for x in range(4):
            # The same texel is reached using the transformed normalized UV.
            u, v = (x + 0.5) / 4, 1 - (y + 0.5) / 8
            new_u, new_v = v, 1 - u
            np.testing.assert_array_equal(rotated[int((1-new_v)*4), int(new_u*8)], source[y, x])


def test_rotated_normals_follow_rotated_tangent_basis():
    source = pixels.new_plane(2, 4, (0.8, 0.6, 0.9, 0.7))
    rotated = atlas.rotate_landscape(source, normal_map=True)
    np.testing.assert_allclose(rotated[0, 0], (0.6, 0.2, 0.9, 0.7), atol=1e-6)
    # Rotating the result must not mutate the original decoded image.
    np.testing.assert_allclose(source[0, 0], (0.8, 0.6, 0.9, 0.7), atol=1e-6)


def test_square_and_landscape_images_remain_unchanged():
    for width, height in ((4, 4), (8, 4)):
        source = pixels.new_plane(width, height)
        assert atlas.rotate_landscape(source) is source
