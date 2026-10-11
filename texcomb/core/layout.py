"""Atlas layout: entry sizing and the bin-packing adapter.

This module owns the "how big is each entry and where does it go" questions.
It adapts the vendored packer algorithms in texcomb.utils.packers (which
still speak the old string-key dict protocol) into clean Placement models.

Sizing rules (kept compatible with the old combiner semantics):
- A textured entry's box = image size * UV repeat + gap padding.
- "Crop to UV bounds" off: the UV repeat is rounded up to whole tiles.
- A solid-color entry's box = fallback square + gap padding.
- "Maximum texture size" downsizes source tiles, then tightly packs their regions.
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
        uniform_size: maximum source size; never a fixed entry or canvas size.
        solid_size: base square size for solid-color entries.

    Returns:
        (box_width, box_height) in pixels, always integers.
    """
    # The saved property name remains compatible with existing blend files,
    # but its meaning is now a source-size ceiling, never an upscaling target.
    if uniform_size is not None:
        if image_size is None:
            return 32, 32
        # One shared scale preserves the source aspect; independent axis
        # rounding would turn rectangular images into distorted rectangles.
        ceiling = floor_power_of_two(min(uniform_size, max(image_size)))
        scale = min(1.0, ceiling / max(image_size))
        tile = tuple(max(1, round(axis * scale)) for axis in image_size)
        repeat = uv_repeat if crop else tuple(math.ceil(x) for x in uv_repeat)
        # Repetition must not inflate the single-tile resolution. Allocate
        # repeated content only after sizing the source tile independently.
        return tuple(math.ceil(axis * factor) for axis, factor in zip(tile, repeat))

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


def fit_proportional_content(source_size, allocation):
    """Fit repeated source content inside an allocation with optional blank space.

    One scale applies to both axes; a square stays square inside a long box.
    Integer pixel rounding can change an edge by less than one pixel only.
    The unused right/bottom region remains blank and is not sampled by UVs.
    This helper is shared by image composition and UV mapping, never packing.
    """
    width, height = source_size
    scale = min(allocation[0] / width, allocation[1] / height)
    return (max(1, min(allocation[0], round(width * scale))),
            max(1, min(allocation[1], round(height * scale))))


def floor_power_of_two(value: float) -> int:
    """Return the largest power of two no greater than a positive size."""
    return 1 << max(0, int(value).bit_length() - 1)


def power_of_two_content(source_size, bounds):
    """Fit exact source proportions using power-of-two dimensions only.

    Reduced source axes must themselves be powers of two. For example,
    300x150 can become 128x64, but 300x100 cannot satisfy both contracts.
    Reject that impossible case instead of quietly distorting the texture.
    Bounds apply before packing; padding never participates in this math.
    """
    width, height = (int(axis) for axis in source_size)
    if min(width, height, *bounds) < 1:
        raise ValueError("Texture dimensions must be positive")
    divisor = math.gcd(width, height)
    ratio = (width // divisor, height // divisor)
    if any(axis & (axis - 1) for axis in ratio):
        raise ValueError("Source aspect ratio cannot use power-of-two dimensions")
    # A single multiplier preserves the exact reduced ratio on both axes.
    # Do not clamp either axis independently when the bounds are too small.
    scale = min(bound / axis for bound, axis in zip(bounds, ratio))
    if scale < 1:
        raise ValueError("Texture bounds cannot preserve the source aspect ratio")
    factor = floor_power_of_two(scale)
    return tuple(axis * factor for axis in ratio)


def pack_fixed_blocks(box_sizes: Dict, block_size: int) -> Tuple[Dict, Tuple[int, int]]:
    """Pack unrotated boxes into fixed square blocks of one larger image.

    Best-area-fit uses the gaps in earlier blocks before opening a new one.
    Choose the smallest power-of-two capacity that contains all blocks.
    At equal capacity prefer square, then 2:1, then 4:1 layouts. Blank
    blocks are allowed only as required by the chosen power-of-two canvas.
    """
    block_size = floor_power_of_two(block_size)
    blocks = []
    fits = {}
    # Large entries first make fragmented free space much less likely.
    ordered = sorted(box_sizes, key=lambda key: (
        box_sizes[key][0] * box_sizes[key][1], max(box_sizes[key])
    ), reverse=True)
    for key in ordered:
        width, height = box_sizes[key]
        if min(width, height) < 1 or max(width, height) > block_size:
            raise ValueError("Entry does not fit fixed atlas block: {!r}".format(key))
        candidates = []
        for block_index, free_rects in enumerate(blocks):
            for x, y, free_w, free_h in free_rects:
                if width <= free_w and height <= free_h:
                    candidates.append((free_w * free_h - width * height,
                                       min(free_w - width, free_h - height),
                                       block_index, y, x))
        if candidates:
            _, _, block_index, y, x = min(candidates)
        else:
            # Add exactly one block only when no existing free region fits.
            block_index = len(blocks)
            blocks.append([(0, 0, block_size, block_size)])
            x, y = 0, 0
        fits[key] = {"x": x + block_index * block_size, "y": y,
                     "w": width, "h": height}
        remaining = []
        for fx, fy, fw, fh in blocks[block_index]:
            # Free rectangles can overlap; split every rectangle intersecting
            # the placement so future entries can never overlap placed boxes.
            if x >= fx + fw or x + width <= fx or y >= fy + fh or y + height <= fy:
                remaining.append((fx, fy, fw, fh))
                continue
            if x > fx:
                remaining.append((fx, fy, x - fx, fh))
            if x + width < fx + fw:
                remaining.append((x + width, fy, fx + fw - x - width, fh))
            if y > fy:
                remaining.append((fx, fy, fw, y - fy))
            if y + height < fy + fh:
                remaining.append((fx, y + height, fw, fy + fh - y - height))
        # Remove duplicate and contained regions to keep the search small.
        remaining = list(dict.fromkeys(remaining))
        blocks[block_index] = [rect for rect in remaining if not any(
            other != rect and other[0] <= rect[0] and other[1] <= rect[1]
            and other[0] + other[2] >= rect[0] + rect[2]
            and other[1] + other[3] >= rect[1] + rect[3]
            for other in remaining
        )]
    # Reposition whole blocks without changing regions inside each block.
    # Round capacity up, not each axis independently: this keeps padding
    # minimal. Splitting the exponent evenly gives the preferred shape;
    # even exponents produce squares, odd exponents produce 2:1 rectangles.
    # A 4:1 rectangle has the same area as a square, so loses that tie.
    count = max(1, len(blocks))
    capacity_exponent = (count - 1).bit_length()
    rows = 1 << (capacity_exponent // 2)
    columns = 1 << (capacity_exponent - capacity_exponent // 2)
    for fit in fits.values():
        block_index, local_x = divmod(fit["x"], block_size)
        fit["x"] = (block_index % columns) * block_size + local_x
        fit["y"] += (block_index // columns) * block_size
    return fits, (columns * block_size, rows * block_size)


def _pack_canvas(box_sizes: Dict, width: int, height: int) -> Optional[Dict]:
    """Try one unrotated MaxRects layout without any fixed tile boundaries."""
    free = [(0, 0, width, height)]
    fits = {}
    ordered = sorted(box_sizes, key=lambda key: (
        box_sizes[key][0] * box_sizes[key][1], max(box_sizes[key])
    ), reverse=True)
    for key in ordered:
        w, h = box_sizes[key]
        choices = [(fw * fh - w * h, min(fw - w, fh - h), y, x)
                   for x, y, fw, fh in free if w <= fw and h <= fh]
        if not choices:
            return None
        _, _, y, x = min(choices)
        fits[key] = {"x": x, "y": y, "w": w, "h": h}
        remaining = []
        # Split every overlapping free region, not only the chosen region.
        # This keeps placements disjoint even though free regions overlap.
        for fx, fy, fw, fh in free:
            if x >= fx + fw or x + w <= fx or y >= fy + fh or y + h <= fy:
                remaining.append((fx, fy, fw, fh))
                continue
            if x > fx:
                remaining.append((fx, fy, x - fx, fh))
            if x + w < fx + fw:
                remaining.append((x + w, fy, fx + fw - x - w, fh))
            if y > fy:
                remaining.append((fx, fy, fw, y - fy))
            if y + h < fy + fh:
                remaining.append((fx, y + h, fw, fy + fh - y - h))
        # Prune contained rectangles so candidate searches stay manageable.
        remaining = list(dict.fromkeys(remaining))
        free = [rect for rect in remaining if not any(
            other != rect and other[0] <= rect[0] and other[1] <= rect[1]
            and other[0] + other[2] >= rect[0] + rect[2]
            and other[1] + other[3] >= rect[1] + rect[3]
            for other in remaining
        )]
    return fits


def pack_tight_atlas(
    box_sizes: Dict,
    max_axis: int = 16384,
    minimum_size: Tuple[int, int] = (1, 1),
    maximum_size: Optional[Tuple[int, int]] = None,
) -> Tuple[Dict, Tuple[int, int]]:
    """Search increasing canvas capacities, preferring 1:1, 2:1, then 4:1.

    Both axes are powers of two. The source-size ceiling is intentionally
    absent from this function: a small collection can produce a small atlas,
    and a large collection can exceed the size of any individual source.
    minimum_size is the game's original canvas floor; it adds empty space,
    never scales entry sizes or changes coordinates inside a placed region.
    """
    if any(min(size) < 1 for size in box_sizes.values()):
        raise ValueError("Atlas entries must have positive sizes")
    # Round canvas floors upward so non-power-of-two input is never undershot.
    min_width, min_height = (1 << (max(1, int(axis)) - 1).bit_length()
                             for axis in minimum_size)
    # Per-axis output ceilings may be rectangular and must never be exceeded.
    max_width, max_height = maximum_size or (max_axis, max_axis)
    max_width, max_height = (floor_power_of_two(min(axis, max_axis))
                             for axis in (max_width, max_height))
    area = sum(w * h for w, h in box_sizes.values())
    first_exponent = (max(1, area, min_width * min_height) - 1).bit_length()
    limit_exponent = floor_power_of_two(max_axis).bit_length() - 1
    for capacity in range(first_exponent, 2 * limit_exponent + 1):
        for ratio in (0, 1, 2):
            # Powers-of-two axes require equal parity of area and ratio.
            if capacity < ratio or (capacity - ratio) % 2:
                continue
            wide = 1 << ((capacity + ratio) // 2)
            narrow = 1 << ((capacity - ratio) // 2)
            if wide > max_axis:
                continue
            for width, height in dict.fromkeys([(wide, narrow), (narrow, wide)]):
                # Canvas floors constrain output only, independently per axis.
                if width < min_width or height < min_height:
                    continue
                if width > max_width or height > max_height:
                    continue
                # Cheap bounds checks avoid unnecessary packing attempts.
                if any(w > width or h > height for w, h in box_sizes.values()):
                    continue
                fits = _pack_canvas(box_sizes, width, height)
                if fits is not None:
                    return fits, (width, height)
    raise ValueError("Textures cannot fit within the maximum atlas dimensions")


def pack_budget_atlas(
    box_sizes: Dict,
    maximum_size: Tuple[int, int],
    minimum_size: Tuple[int, int] = (1, 1),
    solid_keys=(),
    fixed_sizes=None,
    gaps: int = 0,
    linked_groups=(),
    preserve_aspect=False,
) -> Tuple[Dict, Tuple[int, int], Dict]:
    """Reduce large regions until one atlas fits the explicit pixel budget.

    Each step halves one largest adjustable region along both axes, keeping
    its aspect ratio until an axis reaches one texel. Small entries wait
    until larger entries have caught up. Solid regions keep their initial size.
    fixed_sizes overrides exact content dimensions and excludes those entries
    from shrinking. gaps adds external padding without reducing that content.
    linked_groups ties separate output regions to one shared content resolution;
    reductions apply to the entire group and never count as output deduplication.
    preserve_aspect stops power-of-two plans when either axis reaches one;
    shrinking only the longer axis would violate their exact source ratio.
    """
    maximum = tuple(floor_power_of_two(axis) for axis in maximum_size)
    minimum = tuple(1 << (max(1, int(axis)) - 1).bit_length() for axis in minimum_size)
    if any(low > high for low, high in zip(minimum, maximum)):
        raise ValueError("Original game texture size exceeds total maximum texture size")
    sizes = dict(box_sizes)
    solids = set(solid_keys)
    # Overrides describe exact content dimensions, excluding external padding.
    # A locked region never joins the reduction candidates, even when too big.
    fixed = dict(fixed_sizes or {})
    if set(fixed) - set(sizes):
        raise ValueError("Fixed texture sizes reference missing materials")
    # Linked entries occupy distinct boxes but must share one content size.
    # Identical output entries are collapsed by the adapter before this call.
    linked = [set(group) for group in linked_groups]
    membership = {}
    for group in linked:
        if group - set(sizes) or any(key in membership for key in group):
            raise ValueError("Linked texture groups must be disjoint and reference existing entries")
        locked = {fixed[key] for key in group if key in fixed}
        if len(locked) > 1:
            raise ValueError("Conflicting fixed sizes for shared texture")
        size = next(iter(locked)) if locked else tuple(max(sizes[key][axis] for key in group) for axis in (0, 1))
        for key in group:
            sizes[key] = size
            membership[key] = group
            if locked:
                fixed[key] = size
    sizes.update(fixed)
    if any(min(size) < 1 for size in sizes.values()) or gaps < 0:
        raise ValueError("Texture dimensions must be positive and spacing non-negative")
    # Keep the initial proportions as the reference for every reduction.
    # Repeatedly halving rounded dimensions accumulates aspect-ratio drift.
    # Each linked family shares this reference and one cumulative scale.
    preferred_sizes = dict(sizes)
    scales = dict.fromkeys(sizes, 1.0)
    while True:
        try:
            # Padding remains constant while automatic content is reduced.
            # This makes a requested 512x512 region stay exactly 512x512.
            boxes = {key: tuple(axis + gaps for axis in size)
                     for key, size in sizes.items()}
            fits, canvas = pack_tight_atlas(boxes, minimum_size=minimum,
                                           maximum_size=maximum)
            return fits, canvas, sizes
        except ValueError:
            # No layout fits yet. Choose the largest reducible texture;
            # Python's stable max keeps ties deterministic across runs.
            candidates = [key for key, size in sizes.items()
                          if not (membership.get(key, {key}) & (solids | set(fixed)))
                          and (min(size) if preserve_aspect else max(size)) > 1]
            if not candidates:
                raise ValueError("Texture regions cannot fit total maximum texture size, even at minimum resolution")
            key = max(candidates, key=lambda entry: (
                sizes[entry][0] * sizes[entry][1], max(sizes[entry])
            ))
            # Scale both axes from the original preference, never rounded output.
            # Unused canvas space is acceptable; it must not change this ratio.
            scale = scales[key] / 2
            reduced = tuple(max(1, round(axis * scale)) for axis in preferred_sizes[key])
            # Shared textures shrink as one unit, never diverging between rows.
            # Once an axis reaches one pixel, integer resolution is the limit.
            for member in membership.get(key, {key}):
                sizes[member] = reduced
                scales[member] = scale


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
) -> Tuple[int, int]:
    """Adjust the packed atlas extent according to the sizing strategy.

    PO2 rounds each axis up to a power of two; QUAD forces a square;
    everything else (AUTO and the custom strategies) keeps the natural
    packed extent. CUST/STRICTCUST are intentionally NOT handled here: their
    scale-down/pad step must happen AFTER composition, on the finished
    canvas, which is what atlas.fit_canvas_to() does.
    """
    if strategy == SIZE_PO2:
        # Next power of two per axis (bit_length trick, exact for ints >= 1).
        return tuple(1 << int(axis - 1).bit_length() for axis in size)
    if strategy == SIZE_QUAD:
        side = max(size)
        return side, side
    return size
