"""Total atlas limits lower source regions automatically rather than overflow."""

import pytest

from texcomb.core import layout


def test_sixteen_512_textures_become_256_in_1024_atlas():
    # The user's acceptance case: all sixteen equal sources retain equal detail.
    original = {str(index): (512, 512) for index in range(16)}
    fits, canvas, sizes = layout.pack_budget_atlas(original, (1024, 1024))
    assert canvas == (1024, 1024)
    assert set(sizes.values()) == {(256, 256)}
    assert len(fits) == 16
    # Planning reductions must not modify the caller's original dimensions.
    assert set(original.values()) == {(512, 512)}


def test_mixed_sizes_reduce_large_regions_before_small_ones():
    original = {"large": (1024, 1024), "small": (64, 64), "solid": (32, 32)}
    fits, canvas, sizes = layout.pack_budget_atlas(original, (512, 512), solid_keys=["solid"])
    assert sizes == {"large": (256, 256), "small": (64, 64), "solid": (32, 32)}
    assert max(canvas) <= 512


def test_existing_fit_keeps_every_region_size():
    original = {"a": (128, 128), "b": (64, 64)}
    fits, canvas, sizes = layout.pack_budget_atlas(original, (1024, 1024))
    assert sizes == original
    assert canvas == (256, 128)


def test_rectangular_budget_and_original_floor_are_both_respected():
    original = {str(index): (512, 512) for index in range(16)}
    fits, canvas, sizes = layout.pack_budget_atlas(original, (1024, 512), (1024, 512))
    assert canvas == (1024, 512)
    assert sum(w * h for w, h in sizes.values()) <= 1024 * 512


def test_many_large_sources_fit_small_budget():
    original = {str(index): (2048, 2048) for index in range(64)}
    fits, canvas, sizes = layout.pack_budget_atlas(original, (512, 512))
    assert canvas == (512, 512)
    assert set(sizes.values()) == {(64, 64)}


@pytest.mark.parametrize("source", [(140, 127), (127, 140), (300, 101)])
def test_budget_reductions_use_original_proportions(source):
    # Several reductions expose drift from repeatedly truncating both axes.
    # A single shared scale permits only the final half-pixel rounding error.
    _, _, sizes = layout.pack_budget_atlas({"texture": source}, (16, 16))
    result = sizes["texture"]
    scale = 1.0
    while max(round(axis * scale) for axis in source) > 16:
        scale /= 2
    assert result == tuple(max(1, round(axis * scale)) for axis in source)
    assert all(abs(actual - axis * scale) <= 0.5 for actual, axis in zip(result, source))


def test_canvas_slack_never_enlarges_or_stretches_entries():
    # A wide canvas floor deliberately leaves large empty regions.
    # Packing may move entries, but cannot resize either axis to fill them.
    original = {"square": (64, 64), "rectangle": (140, 127)}
    fits, canvas, sizes = layout.pack_budget_atlas(original, (1024, 512), (1024, 512))
    assert canvas == (1024, 512)
    assert sizes == original
    assert all((fits[key]["w"], fits[key]["h"]) == size for key, size in original.items())


def test_linked_rectangles_keep_one_proportional_reduction():
    # Distinct outputs from one texture family must retain identical sizes.
    # The shared scale is cumulative even when several budget steps are needed.
    original = {"a": (140, 127), "b": (140, 127)}
    _, _, sizes = layout.pack_budget_atlas(original, (32, 16), linked_groups=[{"a", "b"}])
    assert sizes == {"a": (9, 8), "b": (9, 8)}
    assert original == {"a": (140, 127), "b": (140, 127)}


def test_conflicting_floor_is_reported_without_reduction_loop():
    with pytest.raises(ValueError, match="Original game"):
        layout.pack_budget_atlas({"a": (512, 512)}, (512, 512), (1024, 1024))
