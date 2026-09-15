"""Atlas composition: building the final float32 canvas.

Composition is deliberately dumb: layout decides WHERE things go (Placement),
channels decides WHAT each material's pixels are (build_material_plane), and
this module only pastes planes onto a canvas and applies the final canvas
sizing strategy.
"""

from typing import Iterable, Optional, Tuple

import numpy as np

from . import pixels
from .layout import SIZE_CUST, SIZE_STRICTCUST

# Atlas background: transparent black, so unused padding areas carry alpha 0
# (the old code used (0, 0, 0, 0) for the extra atlases; we use it for all,
# which also makes the padding visually obvious in an image viewer).
BACKGROUND = (0.0, 0.0, 0.0, 0.0)


def compose_atlas(
    items: Iterable[Tuple[np.ndarray, int, int]],
    atlas_size: Tuple[int, int],
    background: Tuple[float, float, float, float] = BACKGROUND,
) -> np.ndarray:
    """Paste planes onto a new canvas of atlas_size.

    Args:
        items: iterable of (plane, paste_x, paste_y) triples. Pasting is a
            raw copy (no blending) and clips at the canvas edges.
        atlas_size: (width, height) of the canvas.
        background: linear RGBA fill color for unused areas.

    Returns:
        The composed float32 canvas of shape (height, width, 4).
    """
    canvas = pixels.new_plane(atlas_size[0], atlas_size[1], background)
    for plane, paste_x, paste_y in items:
        pixels.paste_plane(canvas, plane, paste_x, paste_y)
    return canvas


def fit_within(size: Tuple[int, int], limit: Tuple[int, int]) -> Tuple[int, int]:
    """Scale size down proportionally to fit inside limit (like PIL thumbnail).

    Only shrinks, never enlarges; keeps the aspect ratio. Public because the
    per-material "custom size" option needs the same math.
    """
    width, height = size
    limit_w, limit_h = limit
    ratio = min(limit_w / width, limit_h / height, 1.0)
    return max(1, int(width * ratio)), max(1, int(height * ratio))


def fit_canvas_to(
    canvas: np.ndarray,
    strategy: str,
    custom_size: Optional[Tuple[int, int]],
    filter_name: str = "lanczos3",
) -> np.ndarray:
    """Apply the final canvas sizing strategy after composition.

    CUST: scale the whole atlas down (aspect-preserving) to fit the custom
    size. STRICTCUST: same scaling, then paste onto an exact custom-size
    canvas. All other strategies return the canvas unchanged.
    """
    if strategy not in (SIZE_CUST, SIZE_STRICTCUST) or custom_size is None:
        return canvas

    current_size = (canvas.shape[1], canvas.shape[0])
    target = fit_within(current_size, custom_size)
    if target != current_size:
        # One final whole-canvas resize; still float32 linear space.
        canvas = pixels.resize_plane(canvas, target[0], target[1], filter_name)

    if strategy == SIZE_STRICTCUST and target != custom_size:
        # Strict mode pads the scaled atlas onto the exact requested canvas.
        strict = pixels.new_plane(custom_size[0], custom_size[1], BACKGROUND)
        pixels.paste_plane(strict, canvas, 0, 0)
        return strict

    return canvas
