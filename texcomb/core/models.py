"""Plain data models for the texture combiner core pipeline.

These dataclasses describe WHAT to build, not HOW to build it. They are the
single source of truth for the data shape that flows through the pipeline
stages, replacing the old nested string-key dicts in combiner_ops.py.

Only the standard library is used here. No bpy, no numpy: models carry
references (keys) to images, not the pixel data itself.
"""

from dataclasses import dataclass, field
from typing import Optional, Tuple

# ---------------------------------------------------------------------------
# Alpha merge strategies.
#
# The atlas alpha channel is a DATA channel for the target game shaders (it
# stores masks, not transparency), so the user must be able to choose exactly
# where it comes from instead of relying on incidental node wiring.
# ---------------------------------------------------------------------------

# Keep the base texture's own alpha channel (the old default behavior).
ALPHA_EMBEDDED = "embedded"
# Take alpha from a channel of a second, separate image.
ALPHA_SEPARATE = "separate"
# Multiply the base texture's alpha with a channel of a second image.
ALPHA_MULTIPLY = "multiply"
# Force alpha to a constant (fully opaque by default).
ALPHA_OPAQUE = "opaque"

# All valid alpha modes, for validation and for building UI enums.
ALPHA_MODES = (ALPHA_EMBEDDED, ALPHA_SEPARATE, ALPHA_MULTIPLY, ALPHA_OPAQUE)

# Channel identifiers understood by ChannelSource.
# "LUM" is Rec.709 luma computed in linear space; "ONE" is a constant 1.0.
CHANNELS = ("R", "G", "B", "A", "LUM", "ONE")


@dataclass
class ChannelSource:
    """Where one output channel gets its data from.

    If image_key is empty, the source is a flat constant value.
    Otherwise the source is one channel of the decoded float32 image stored
    under image_key in the decoded-image dictionary.
    """

    # Key into the decoded-image dict; "" means "use the constant below".
    image_key: str = ""
    # One of CHANNELS: which channel of the image to read.
    channel: str = "A"
    # Constant value in [0, 1], used when image_key is "".
    constant: float = 1.0


@dataclass
class ChannelPlan:
    """How to build one material's RGBA plane.

    RGB always come from the base image (or from solid_color when the
    material has no readable base texture). Only the alpha channel is
    configurable, via alpha_mode + alpha source.
    """

    # Key of the decoded base (albedo) image; "" means solid-color material.
    base_key: str = ""
    # Linear RGBA used when base_key is "" (the old "solid color" fallback).
    solid_color: Optional[Tuple[float, float, float, float]] = None
    # One of ALPHA_MODES.
    alpha_mode: str = ALPHA_EMBEDDED
    # Source for the alpha channel in "separate"/"multiply" modes.
    alpha: ChannelSource = field(default_factory=ChannelSource)
    # Linear RGBA multiplier applied to the base image (the old "blend
    # diffuse color" feature). (1, 1, 1, 1) disables the multiply.
    diffuse_color: Tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)

    def validate(self) -> None:
        """Raise ValueError with a clear message if the plan is inconsistent.

        Called by the pipeline before any pixel work happens, so mistakes in
        the bpy collection layer fail loudly instead of producing a corrupt
        atlas.
        """
        # A solid-color material must carry an actual color.
        if not self.base_key and self.solid_color is None:
            raise ValueError(
                "ChannelPlan needs either base_key or solid_color"
            )
        # The alpha mode must be one of the known strategies.
        if self.alpha_mode not in ALPHA_MODES:
            raise ValueError(
                "Unknown alpha_mode: {!r} (expected one of {})".format(
                    self.alpha_mode, ALPHA_MODES
                )
            )
        # Modes that read a second image must name a valid channel for it.
        if self.alpha_mode in (ALPHA_SEPARATE, ALPHA_MULTIPLY):
            if self.alpha.image_key and self.alpha.channel not in CHANNELS:
                raise ValueError(
                    "Unknown alpha channel: {!r} (expected one of {})".format(
                        self.alpha.channel, CHANNELS
                    )
                )


@dataclass
class Placement:
    """Where one material's content lands inside the atlas.

    The "box" is the rectangle reserved by the bin packer; it includes the
    padding (gap) area around the content. The "content" is the actual image
    rectangle that pixels are pasted into. Keeping both makes the UV remap
    math explicit instead of re-deriving margins at the paste site.
    """

    # Identifier chosen by the caller (usually the material name).
    key: str
    # Packer rectangle origin, including the padding area.
    box_x: int
    box_y: int
    # Packer rectangle size, including the padding area.
    box_width: int
    box_height: int
    # Pixel position of the content image inside the atlas.
    paste_x: int
    paste_y: int
    # Content size without padding.
    content_width: int
    content_height: int
