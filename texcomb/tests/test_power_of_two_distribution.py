"""Keep automatic dimensions dyadic without changing native texture aspect.

These checks deliberately separate source content from external spacing.
Only exact dyadic aspect ratios can satisfy both requested invariants.
Manual allocations retain their existing arbitrary-dimension contract.
Budget exhaustion must reject a plan rather than squash a thin image.
The two screenshot regressions are tested as square source allocations.
Landscape and portrait fixtures guard against square-only implementations.
A non-power-of-two source can still have a representable dyadic ratio.
An impossible ratio must fail before any atlas placement is accepted.
"""
import pytest

from texcomb.core.layout import pack_budget_atlas, power_of_two_content


@pytest.mark.parametrize("source,bounds,expected", [
    ((1024, 1024), (65, 389), (64, 64)),
    ((4096, 4096), (141, 128), (128, 128)),
    ((1024, 512), (300, 200), (256, 128)),
    ((512, 1024), (200, 300), (128, 256)),
    ((300, 150), (300, 150), (256, 128)),
    ((1, 8), (1, 8), (1, 8)),
])
def test_exact_ratio_and_power_of_two_axes(source, bounds, expected):
    # Cross multiplication is exact; a floating tolerance could hide drift.
    size = power_of_two_content(source, bounds)
    assert size == expected
    assert size[0] * source[1] == size[1] * source[0]
    assert all(axis > 0 and axis & (axis - 1) == 0 for axis in size)


@pytest.mark.parametrize("source,bounds", [
    ((300, 100), (256, 256)),
    ((140, 128), (128, 128)),
    ((1, 8), (1, 4)),
])
def test_impossible_ratios_or_bounds_are_explicit_errors(source, bounds):
    # Silently rounding either axis would claim an invalid success.
    with pytest.raises(ValueError):
        power_of_two_content(source, bounds)


def test_budget_reduction_preserves_ratio_with_external_padding():
    # Mixed portrait and landscape sources must never rotate or stretch.
    sources = {"a": (512, 256), "b": (128, 512), "c": (256, 256)}
    fits, canvas, sizes = pack_budget_atlas(sources, (256, 256), gaps=5, preserve_aspect=True)
    for key, size in sizes.items():
        assert size[0] * sources[key][1] == size[1] * sources[key][0]
        assert all(axis & (axis - 1) == 0 for axis in size)
        # Padding is added after rounding, not subtracted from displayed sizes.
        assert (fits[key]["w"], fits[key]["h"]) == tuple(axis + 5 for axis in size)
        assert fits[key]["x"] + fits[key]["w"] <= canvas[0]
        assert fits[key]["y"] + fits[key]["h"] <= canvas[1]


def test_short_axis_stops_reduction_before_ratio_changes():
    # A one-pixel-wide 1:8 image cannot fit in a four-pixel-high canvas.
    with pytest.raises(ValueError, match="minimum resolution"):
        pack_budget_atlas({"a": (1, 8)}, (4, 4), preserve_aspect=True)


def test_manual_non_dyadic_allocation_is_still_exact():
    # Users may reserve arbitrary bounds; automatic sizing alone is constrained.
    _, _, sizes = pack_budget_atlas({"a": (32, 32)}, (128, 128),
                                    fixed_sizes={"a": (65, 99)}, preserve_aspect=True)
    assert sizes["a"] == (65, 99)
