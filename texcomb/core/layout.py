"""Atlas layout: entry sizing and the bin-packing adapter.

This module owns the "how big is each entry and where does it go" questions.
It adapts the vendored packer algorithms in texcomb.utils.packers (which
still speak the old string-key dict protocol) into clean Placement models.

Sizing rules (kept compatible with the old combiner semantics):
- A textured entry's box = image size * UV repeat + gap padding.
- "Crop to UV bounds" off: the UV repeat is rounded up to whole tiles.
- A solid-color entry's box = fallback square + gap padding.
- "Uniform size" overrides everything with a fixed square.
"""

import math
from typing import Dict, Optional, Tuple

from ..utils.packers import pack as _legacy_pack
from .models import Placement

# The old code clips the UV repeat factor to this range; 25 tiles is already
# far beyond any sane use, and it guards the atlas size from exploding when
# a broken UV island runs to huge coordinates.
UV_REPEAT_MIN = 1
UV_REPEAT_MAX = 25

# Atlas size strategy identifiers (same values the UI enum uses).
SIZE_PO2 = "PO2"
SIZE_QUAD = "QUAD"
SIZE_AUTO = "AUTO"
SIZE_CUST = "CUST"
SIZE_STRICTCUST = "STRICTCUST"


def clamp_uv_repeat(max_u: float, max_v: float) -> Tuple[float, float]:
    """Clamp the maximum UV coordinates to the allowed repeat range.

    NaN values (broken UVs) degrade to 1 so one bad island cannot poison the
    whole atlas.
    """
    def _clamp(value: float) -> float:
        if value != value:  # NaN check without importing math.isnan here.
            return float(UV_REPEAT_MIN)
        return float(min(max(value, UV_REPEAT_MIN), UV_REPEAT_MAX))

    return _clamp(max_u), _clamp(max_v)


def entry_box_size(
    image_size: Optional[Tuple[int, int]],
    uv_repeat: Tuple[float, float],
    gaps: int,
    crop: bool = True,
    uniform_size: Optional[int] = None,
    solid_size: int = 32,
) -> Tuple[int, int]:
    """Compute the box size (content + padding) for one atlas entry.

    Args:
        image_size: (width, height) of the decoded base image, or None for a
            solid-color entry.
        uv_repeat: clamped (repeat_u, repeat_v) from clamp_uv_repeat.
        gaps: padding added around the content (total per axis).
        crop: when False, round the UV repeat up to whole tiles.
        uniform_size: when set, every entry gets this square size.
        solid_size: base square size for solid-color entries.

    Returns:
        (box_width, box_height) in pixels, always integers.
    """
    # Uniform size wins over everything (the old code applies it last too).
    if uniform_size is not None:
        return uniform_size, uniform_size

    # Solid-color entries get a small fixed square.
    if image_size is None:
        return solid_size + gaps, solid_size + gaps

    repeat_u, repeat_v = uv_repeat
    if not crop:
        # Whole tiles only: 1.2 repeats still needs two full copies.
        repeat_u = math.ceil(repeat_u)
        repeat_v = math.ceil(repeat_v)

    # ceil (not int/truncation) so the content can never overflow the box.
    box_width = math.ceil(image_size[0] * repeat_u + gaps)
    box_height = math.ceil(image_size[1] * repeat_v + gaps)
    return box_width, box_height


def pack_entries(
    box_sizes: Dict[str, Tuple[int, int]],
    packer_type: str,
    gaps: int,
) -> Dict[str, Placement]:
    """Bin-pack the entries and return their placements.

    This is an adapter: the vendored packers still speak the old protocol
    ({key: {"gfx": {"size": ...}}} in, {"gfx": {"fit": ...}} out). All of
    that translation lives here so the rest of the core never sees it.

    Known limitation inherited from the old code: the RECT_PACK2D packer may
    rotate (flip) boxes; the combiner pastes content unrotated, which the old
    code never handled either. Prefer MAX_RECTS or BINARY_TREE for now.
    """
    # Build the legacy input shape the vendored packers expect.
    legacy = {key: {"gfx": {"size": size}} for key, size in box_sizes.items()}
    packed = _legacy_pack(legacy, packer_type)

    half_gaps = gaps // 2
    placements = {}
    for key, item in packed.items():
        fit = item["gfx"].get("fit")
        if fit is None:
            # The packer could not place this entry; fail loudly instead of
            # silently dropping the material like the old code did.
            raise ValueError("Packer placed no rectangle for {!r}".format(key))
        box_width = int(fit["w"])
        box_height = int(fit["h"])
        placements[key] = Placement(
            key=key,
            box_x=int(fit["x"]),
            box_y=int(fit["y"]),
            box_width=box_width,
            box_height=box_height,
            # The content sits centered in the padding: half a gap inset.
            paste_x=int(fit["x"]) + half_gaps,
            paste_y=int(fit["y"]) + half_gaps,
            content_width=box_width - gaps,
            content_height=box_height - gaps,
        )
    return placements


def atlas_extent(placements: Dict[str, Placement]) -> Tuple[int, int]:
    """Return the smallest atlas size that contains all placements."""
    max_x = 1
    max_y = 1
    for placement in placements.values():
        max_x = max(max_x, placement.box_x + placement.box_width)
        max_y = max(max_y, placement.box_y + placement.box_height)
    return max_x, max_y


def adjust_atlas_size(
    strategy: str,
    size: Tuple[int, int],
    custom_size: Optional[Tuple[int, int]] = None,
) -> Tuple[int, int]:
    """Adjust the atlas size according to the chosen strategy.

    PO2 rounds each axis up to a power of two, QUAD forces a square, AUTO
    keeps the packed extent. CUST/STRICTCUST hand back the custom size; the
    difference between them (scale vs. strict canvas) is applied when the
    canvas is finalized in atlas.fit_canvas_to().
    """
    if strategy == SIZE_PO2:
        # Next power of two per axis (bit_length trick, exact for ints >= 1).
        return tuple(1 << int(axis - 1).bit_length() for axis in size)
    if strategy == SIZE_QUAD:
        side = max(size)
        return side, side
    if strategy in (SIZE_CUST, SIZE_STRICTCUST) and custom_size is not None:
        return custom_size
    # AUTO and any unknown strategy: keep the natural packed extent.
    return size
