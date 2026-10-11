"""Source ceilings and game canvas floors are independent size constraints."""

import itertools

import pytest

from texcomb.core import layout


def assert_fits(sizes, fits, canvas):
    # A bigger canvas must never enlarge individual texture regions.
    for key, fit in fits.items():
        assert (fit["w"], fit["h"]) == sizes[key]
        assert fit["x"] + fit["w"] <= canvas[0]
        assert fit["y"] + fit["h"] <= canvas[1]
    # Free rectangles overlap, but actual placed entries never may.
    for a, b in itertools.combinations(fits.values(), 2):
        overlap = (a["x"] < b["x"] + b["w"] and b["x"] < a["x"] + a["w"]
                   and a["y"] < b["y"] + b["h"] and b["y"] < a["y"] + a["h"])
        assert not overlap


@pytest.mark.parametrize("floor,expected", [
    ((1, 1), (512, 512)),
    ((1024, 1024), (1024, 1024)),
    ((2048, 1024), (2048, 1024)),
    ((1024, 2048), (1024, 2048)),
    ((555, 500), (1024, 512)),
])
def test_small_entries_respect_canvas_floor_without_upscaling(floor, expected):
    sizes = {"a": (256, 256), "b": (256, 256), "solid": (32, 32)}
    fits, canvas = layout.pack_tight_atlas(sizes, minimum_size=floor)
    assert canvas == expected
    assert_fits(sizes, fits, canvas)


def test_canvas_can_grow_beyond_original_dimensions():
    sizes = {str(i): (1024, 1024) for i in range(5)}
    fits, canvas = layout.pack_tight_atlas(sizes, minimum_size=(1024, 1024))
    assert canvas == (4096, 2048)
    assert_fits(sizes, fits, canvas)


def test_long_regions_can_use_four_to_one_when_square_cannot_fit():
    # Equal-area square is preferred, but cannot hold this unrotated region.
    fits, canvas = layout.pack_tight_atlas({"wide": (1024, 256)})
    assert canvas == (1024, 256)
    assert_fits({"wide": (1024, 256)}, fits, canvas)


def test_source_tile_ceiling_is_applied_before_uv_repeats():
    # A 500px tile stays 256px even if its UVs span several repetitions.
    assert layout.entry_box_size((500, 500), (2, 3), 0, uniform_size=1024) == (512, 768)


def test_floor_beyond_maximum_output_fails():
    with pytest.raises(ValueError, match="cannot fit"):
        layout.pack_tight_atlas({"a": (32, 32)}, max_axis=1024, minimum_size=(2048, 2048))
