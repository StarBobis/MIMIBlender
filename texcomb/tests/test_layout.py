"""Unit tests for texcomb.core.layout (sizing + packing adapter)."""

import pytest

from texcomb.core import layout


class TestClampUvRepeat:
    def test_normal_values_pass_through(self):
        assert layout.clamp_uv_repeat(1.5, 3.0) == (1.5, 3.0)

    def test_clamps_below_and_above(self):
        assert layout.clamp_uv_repeat(0.2, 99.0) == (1.0, 25.0)

    def test_nan_degrades_to_one(self):
        assert layout.clamp_uv_repeat(float("nan"), 2.0) == (1.0, 2.0)


class TestEntryBoxSize:
    def test_uniform_size_wins(self):
        size = layout.entry_box_size(
            (512, 256), (1.0, 1.0), gaps=4, uniform_size=1024
        )
        assert size == (1024, 1024)

    def test_solid_color_fallback(self):
        size = layout.entry_box_size(None, (1.0, 1.0), gaps=4, solid_size=32)
        assert size == (36, 36)

    def test_uv_repeat_multiplies_and_gaps_add(self):
        size = layout.entry_box_size((100, 50), (2.0, 3.0), gaps=4)
        assert size == (204, 154)

    def test_crop_off_rounds_repeat_up(self):
        # 1.2 repeats without crop needs two whole tiles.
        size = layout.entry_box_size((100, 100), (1.2, 1.0), gaps=0, crop=False)
        assert size == (200, 100)

    def test_fractional_repeat_ceils_to_int(self):
        # 100 * 1.5 + 0 = 150 exactly; add a fractional case instead.
        size = layout.entry_box_size((101, 101), (1.5, 1.5), gaps=0)
        assert size == (152, 152)  # ceil(151.5)


class TestPackEntries:
    """All three vendored packers must produce sane, non-overlapping boxes."""

    @pytest.mark.parametrize("packer", ["BINARY_TREE", "MAX_RECTS", "RECT_PACK2D"])
    def test_placements_do_not_overlap(self, packer):
        sizes = {"a": (8, 8), "b": (4, 4), "c": (6, 2)}
        placements = layout.pack_entries(sizes, packer, gaps=0)

        # Every entry must be placed.
        assert set(placements) == {"a", "b", "c"}

        # Pairwise rectangle intersection test on the boxes.
        boxes = list(placements.values())
        for first, second in zip(boxes, boxes[1:]):
            overlap_x = first.box_x < second.box_x + second.box_width and (
                second.box_x < first.box_x + first.box_width
            )
            overlap_y = first.box_y < second.box_y + second.box_height and (
                second.box_y < first.box_y + first.box_height
            )
            assert not (overlap_x and overlap_y)

    def test_gaps_become_content_inset(self):
        placements = layout.pack_entries({"a": (12, 12)}, "BINARY_TREE", gaps=4)
        placement = placements["a"]
        # Box keeps the requested size; content is inset by half the gap.
        assert (placement.box_width, placement.box_height) == (12, 12)
        assert (placement.content_width, placement.content_height) == (8, 8)
        assert (placement.paste_x - placement.box_x) == 2

    def test_unplaceable_entry_raises(self, monkeypatch):
        # Simulate a packer that silently drops an entry.
        from texcomb.core import layout as layout_module

        monkeypatch.setattr(
            layout_module,
            "_legacy_pack",
            lambda legacy, packer_type: {
                key: {"gfx": {"size": value["gfx"]["size"]}}
                for key, value in legacy.items()
            },
        )
        with pytest.raises(ValueError, match="no rectangle"):
            layout.pack_entries({"a": (4, 4)}, "BINARY_TREE", gaps=0)


class TestAtlasExtentAndAdjust:
    def test_extent_covers_all_boxes(self):
        placements = layout.pack_entries(
            {"a": (8, 8), "b": (4, 4)}, "BINARY_TREE", gaps=0
        )
        width, height = layout.atlas_extent(placements)
        for placement in placements.values():
            assert placement.box_x + placement.box_width <= width
            assert placement.box_y + placement.box_height <= height

    def test_po2_rounds_up_each_axis(self):
        assert layout.adjust_atlas_size("PO2", (100, 300)) == (128, 512)

    def test_quad_forces_square(self):
        assert layout.adjust_atlas_size("QUAD", (100, 300)) == (300, 300)

    def test_auto_keeps_extent(self):
        assert layout.adjust_atlas_size("AUTO", (100, 300)) == (100, 300)

    def test_custom_strategies_return_custom_size(self):
        assert layout.adjust_atlas_size("CUST", (100, 300), (64, 64)) == (64, 64)
        assert layout.adjust_atlas_size("STRICTCUST", (100, 300), (64, 64)) == (64, 64)
