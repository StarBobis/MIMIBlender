"""Game atlas budgets: no upscaling, small solids, and fixed block overflow."""

import itertools

import pytest

from texcomb.core import layout


@pytest.mark.parametrize("source,expected", [
    ((500, 500), (256, 256)),
    ((555, 555), (512, 512)),
    # The largest axis picks the resolution; the other axis follows its scale.
    ((500, 300), (256, 154)),
    ((2048, 512), (1024, 256)),
    ((16, 8), (16, 8)),
    (None, (32, 32)),
])
def test_entry_budget(source, expected):
    # Region sizes include padding, so full-size entries still fit a block.
    assert layout.entry_box_size(source, (1, 1), 4, uniform_size=1024) == expected


def check_placements(sizes, fits, extent, block):
    # Every region stays in exactly one block and inside the final canvas.
    for key, fit in fits.items():
        assert (fit["w"], fit["h"]) == sizes[key]
        assert fit["x"] % block + fit["w"] <= block
        assert fit["y"] % block + fit["h"] <= block
        assert fit["y"] + fit["h"] <= extent[1]
        assert fit["x"] + fit["w"] <= extent[0]
    # Check all pairs, not just adjacent entries in packing order.
    for a, b in itertools.combinations(fits.values(), 2):
        overlap = (a["x"] < b["x"] + b["w"] and b["x"] < a["x"] + a["w"]
                   and a["y"] < b["y"] + b["h"] and b["y"] < a["y"] + a["h"])
        assert not overlap


def test_four_quarters_share_one_block():
    sizes = {str(i): (512, 512) for i in range(4)}
    fits, extent = layout.pack_fixed_blocks(sizes, 1024)
    assert extent == (1024, 1024)
    check_placements(sizes, fits, extent, 1024)


def test_fifth_quarter_opens_exactly_one_more_block():
    sizes = {str(i): (512, 512) for i in range(5)}
    fits, extent = layout.pack_fixed_blocks(sizes, 1024)
    assert extent == (2048, 1024)
    check_placements(sizes, fits, extent, 1024)


def test_solids_fill_earlier_block_gaps():
    # One half-width image leaves room for hundreds of tiny color entries.
    sizes = {"texture": (512, 1024)}
    sizes.update({str(i): (32, 32) for i in range(512)})
    fits, extent = layout.pack_fixed_blocks(sizes, 1024)
    assert extent == (1024, 1024)
    check_placements(sizes, fits, extent, 1024)


def test_many_mixed_regions_are_deterministic():
    sizes = {str(i): (2 ** (5 + i % 6), 2 ** (5 + (i * 3) % 6)) for i in range(80)}
    fits, extent = layout.pack_fixed_blocks(sizes, 1024)
    assert (fits, extent) == layout.pack_fixed_blocks(sizes, 1024)
    check_placements(sizes, fits, extent, 1024)


@pytest.mark.parametrize("count,expected", [
    (1, (1024, 1024)), (2, (2048, 1024)), (3, (2048, 2048)),
    (4, (2048, 2048)), (5, (4096, 2048)), (6, (4096, 2048)),
    (8, (4096, 2048)), (9, (4096, 4096)), (16, (4096, 4096)),
    (17, (8192, 4096)),
])
def test_full_blocks_use_minimum_power_of_two_capacity(count, expected):
    # At equal area, square beats 4:1; odd capacity exponents need 2:1.
    sizes = {str(i): (1024, 1024) for i in range(count)}
    fits, extent = layout.pack_fixed_blocks(sizes, 1024)
    assert extent == expected
    assert extent[0] * extent[1] // (1024 * 1024) == 1 << (count - 1).bit_length()
    check_placements(sizes, fits, extent, 1024)


def test_unplaceable_region_fails_clearly():
    with pytest.raises(ValueError, match="does not fit"):
        layout.pack_fixed_blocks({"huge": (2048, 512)}, 1024)
