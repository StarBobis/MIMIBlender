"""Pure layout regression tests for exact manual locks and external padding.

These tests do not import bpy or touch a scene. The Blender integration suite
separately covers RNA edits, stale plans, UV remapping and actual image output.

Regression intent:
- Preserve the user's hero-texture resolution inside a finite atlas budget.
- Reduce only the remaining automatic textures when extra space is needed.
- Verify all rectangle pairs, because adjacent-only checks miss overlaps.
- Verify box boundaries after the packer chooses the final canvas dimensions.
- Reject impossible geometric layouts even when their total area is small.
- Preserve the caller's source preferences across repeated planning attempts.
- Measure content and external padding separately for rectangular manual locks.
- Allow a manual allocation to exceed a small automatic source preference.
- Restore automatic allocation by replanning from the original source sizes.
- Validate fixed material keys before entering the reduction loop.
- Reject empty dimensions instead of accepting a zero-area material region.
- Reject negative spacing rather than creating overlapping content regions.
- Report canvas floor conflicts independently of content-size reduction.
- Keep these cases deterministic and independent of Blender scene state.
- Use synthetic dimensions only, without image files or memory-heavy atlases.
- Integration assertions supplement rather than replace these numeric checks.
"""

import pytest

from texcomb.core.layout import pack_budget_atlas


def check_rectangles(fits, canvas):
    """Every box must be inside the canvas and disjoint from every other box."""
    boxes = list(fits.values())
    for index, box in enumerate(boxes):
        assert box["x"] >= 0 and box["y"] >= 0
        assert box["x"] + box["w"] <= canvas[0]
        assert box["y"] + box["h"] <= canvas[1]
        # Check every pair, not just consecutive boxes in packing order.
        for other in boxes[index + 1:]:
            separated = (box["x"] + box["w"] <= other["x"] or
                         other["x"] + other["w"] <= box["x"] or
                         box["y"] + box["h"] <= other["y"] or
                         other["y"] + other["h"] <= box["y"])
            assert separated


def test_hero_lock_reduces_other_fifteen_regions():
    """The user's 1024-square atlas example must preserve the hero's 512 square."""
    sizes = {str(index): (512, 512) for index in range(16)}
    fits, canvas, planned = pack_budget_atlas(sizes, (1024, 1024),
                                            fixed_sizes={"0": (512, 512)})
    assert planned["0"] == (512, 512)
    assert all(max(size) < 512 for key, size in planned.items() if key != "0")
    # The planner does not mutate the caller's preferred/source dimensions.
    assert all(size == (512, 512) for size in sizes.values())
    check_rectangles(fits, canvas)


def test_impossible_geometry_is_not_an_area_only_success():
    """Two 700x600 boxes use less total area but cannot fit a 1024-square atlas."""
    fixed = {"a": (700, 600), "b": (700, 600)}
    assert sum(w * h for w, h in fixed.values()) < 1024 * 1024
    with pytest.raises(ValueError, match="minimum resolution"):
        pack_budget_atlas(fixed, (1024, 1024), fixed_sizes=fixed)
    assert fixed["a"] == (700, 600)


def test_gap_is_not_subtracted_from_locked_content():
    """A fixed 64x32 content rectangle occupies a 68x36 padded box."""
    fits, canvas, planned = pack_budget_atlas(
        {"a": (64, 64), "b": (64, 64)}, (128, 128),
        fixed_sizes={"a": (64, 32)}, gaps=4,
    )
    assert planned["a"] == (64, 32)
    assert (fits["a"]["w"], fits["a"]["h"]) == (68, 36)
    check_rectangles(fits, canvas)


def test_fixed_size_can_exceed_automatic_source_preference():
    """Manual resolution is an intentional override, not another source ceiling."""
    _, _, planned = pack_budget_atlas({"a": (32, 32)}, (512, 512),
                                     fixed_sizes={"a": (256, 128)})
    assert planned["a"] == (256, 128)


def test_releasing_lock_restores_default_budget_distribution():
    """Replanning from source sizes avoids accumulating reductions between runs."""
    sources = {"a": (256, 256), "b": (256, 256)}
    _, _, locked = pack_budget_atlas(sources, (256, 256), fixed_sizes={"a": (128, 128)})
    _, _, automatic = pack_budget_atlas(sources, (256, 256))
    assert locked["a"] == (128, 128)
    assert automatic == {"a": (128, 128), "b": (128, 128)}


@pytest.mark.parametrize("fixed,gaps", [({"missing": (1, 1)}, 0), ({"a": (0, 1)}, 0), ({}, -1)])
def test_invalid_constraints_fail_before_packing(fixed, gaps):
    """Missing keys, empty dimensions and negative padding cannot become plans."""
    with pytest.raises(ValueError):
        pack_budget_atlas({"a": (32, 32)}, (128, 128), fixed_sizes=fixed, gaps=gaps)


def test_canvas_floor_conflict_is_not_solved_by_shrinking_content():
    """A canvas minimum above its maximum is an input error, not a texture issue."""
    with pytest.raises(ValueError, match="Original game"):
        pack_budget_atlas({"a": (32, 32)}, (128, 128), minimum_size=(256, 128))


def test_linked_outputs_reduce_together_but_keep_separate_boxes():
    """Tint variants share a resolution budget, not one rendered rectangle."""
    fits, canvas, sizes = pack_budget_atlas(
        {"a": (512, 512), "b": (256, 256), "c": (512, 512)}, (512, 512),
        linked_groups=[{"a", "b"}],
    )
    assert sizes["a"] == sizes["b"]
    assert fits["a"] != fits["b"]
    check_rectangles(fits, canvas)


def test_one_linked_lock_pins_every_variant():
    """A manual request on one source peer applies to the entire texture group."""
    _, _, sizes = pack_budget_atlas({"a": (32, 32), "b": (32, 32)}, (512, 512),
                                   fixed_sizes={"b": (128, 64)}, linked_groups=[{"a", "b"}])
    assert sizes == {"a": (128, 64), "b": (128, 64)}


def test_linked_conflicting_manual_requests_are_rejected():
    """Ambiguous constraints must not pick an arbitrary material as winner."""
    with pytest.raises(ValueError, match="Conflicting"):
        pack_budget_atlas({"a": (32, 32), "b": (32, 32)}, (512, 512),
                          fixed_sizes={"a": (128, 64), "b": (64, 64)}, linked_groups=[{"a", "b"}])


def test_linked_groups_require_disjoint_existing_keys():
    """Reject malformed memberships instead of silently shrinking wrong entries."""
    for groups in ([{"missing"}], [{"a"}, {"a", "b"}]):
        with pytest.raises(ValueError, match="disjoint"):
            pack_budget_atlas({"a": (32, 32), "b": (32, 32)}, (512, 512), linked_groups=groups)
