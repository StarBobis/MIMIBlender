"""Unit tests for texcomb.core.channels (alpha merge strategies)."""

import numpy as np
import pytest

from texcomb.core import channels, pixels
from texcomb.core.models import (
    ALPHA_MULTIPLY,
    ALPHA_OPAQUE,
    ALPHA_SEPARATE,
    ChannelPlan,
    ChannelSource,
)


def _base_plane(alpha=0.4):
    """A 2x2 base image with distinct RGB and a flat alpha."""
    plane = pixels.new_plane(2, 2, (0.2, 0.4, 0.6, alpha))
    return plane


class TestAlphaModes:
    """Each alpha strategy produces exactly the documented alpha channel."""

    def test_embedded_keeps_base_alpha(self):
        images = {"base": _base_plane(alpha=0.4)}
        plan = ChannelPlan(base_key="base")  # default mode: embedded
        out = channels.build_material_plane(plan, images)
        assert np.allclose(out[..., 3], 0.4)
        # RGB must be untouched in embedded mode.
        assert np.allclose(out[..., 0], 0.2)

    def test_opaque_forces_alpha_to_one(self):
        images = {"base": _base_plane(alpha=0.4)}
        plan = ChannelPlan(base_key="base", alpha_mode=ALPHA_OPAQUE)
        out = channels.build_material_plane(plan, images)
        assert np.allclose(out[..., 3], 1.0)

    def test_separate_reads_chosen_channel(self):
        # The mask lives in the R channel of a second image.
        mask = pixels.new_plane(2, 2, (0.9, 0.1, 0.1, 0.3))
        images = {"base": _base_plane(), "mask": mask}
        plan = ChannelPlan(
            base_key="base",
            alpha_mode=ALPHA_SEPARATE,
            alpha=ChannelSource(image_key="mask", channel="R"),
        )
        out = channels.build_material_plane(plan, images)
        # Alpha comes from mask.R; the mask's own alpha (0.3) is irrelevant.
        assert np.allclose(out[..., 3], 0.9)
        # RGB still comes from the base image.
        assert np.allclose(out[..., 0], 0.2)

    def test_multiply_stacks_masks(self):
        mask = pixels.new_plane(2, 2, (1.0, 1.0, 1.0, 0.5))
        images = {"base": _base_plane(alpha=0.4), "mask": mask}
        plan = ChannelPlan(
            base_key="base",
            alpha_mode=ALPHA_MULTIPLY,
            alpha=ChannelSource(image_key="mask", channel="A"),
        )
        out = channels.build_material_plane(plan, images)
        # 0.4 (base alpha) * 0.5 (mask alpha) = 0.2.
        assert np.allclose(out[..., 3], 0.2, atol=1e-6)

    def test_constant_alpha_source(self):
        images = {"base": _base_plane()}
        plan = ChannelPlan(
            base_key="base",
            alpha_mode=ALPHA_SEPARATE,
            alpha=ChannelSource(image_key="", constant=0.7),
        )
        out = channels.build_material_plane(plan, images)
        assert np.allclose(out[..., 3], 0.7)

    def test_lum_uses_rec709_linear_weights(self):
        # Pure red has Rec.709 luma exactly 0.2126 in linear space.
        red = pixels.new_plane(2, 2, (1.0, 0.0, 0.0, 1.0))
        images = {"base": _base_plane(), "red": red}
        plan = ChannelPlan(
            base_key="base",
            alpha_mode=ALPHA_SEPARATE,
            alpha=ChannelSource(image_key="red", channel="LUM"),
        )
        out = channels.build_material_plane(plan, images)
        assert np.allclose(out[..., 3], 0.2126, atol=1e-5)


class TestSizingAndTinting:
    """Resizing during the build and the diffuse-color multiply."""

    def test_base_resized_as_one_plane(self):
        # Base is 2x2, target is 4x4: the whole RGBA plane is resized once.
        images = {"base": _base_plane()}
        plan = ChannelPlan(base_key="base")
        out = channels.build_material_plane(plan, images, size=(4, 4))
        assert out.shape == (4, 4, 4)
        # Flat content stays flat under any filter.
        assert np.allclose(out[..., 3], 0.4, atol=1e-5)

    def test_alpha_source_resized_to_base_size(self):
        # A 1x1 mask applied to a 4x4 base must be resized, not crash.
        images = {"base": _base_plane(), "mask": pixels.new_plane(1, 1, (0.25,) * 3 + (1.0,))}
        plan = ChannelPlan(
            base_key="base",
            alpha_mode=ALPHA_SEPARATE,
            alpha=ChannelSource(image_key="mask", channel="R"),
        )
        out = channels.build_material_plane(plan, images, size=(4, 4))
        assert out.shape == (4, 4, 4)
        assert np.allclose(out[..., 3], 0.25, atol=1e-5)

    def test_diffuse_color_multiplies_rgb_not_alpha(self):
        images = {"base": _base_plane(alpha=0.8)}
        plan = ChannelPlan(base_key="base", diffuse_color=(0.5, 1.0, 1.0, 1.0))
        out = channels.build_material_plane(plan, images)
        assert np.allclose(out[..., 0], 0.1, atol=1e-6)
        assert np.allclose(out[..., 3], 0.8)

    def test_solid_color_material(self):
        plan = ChannelPlan(base_key="", solid_color=(0.1, 0.2, 0.3, 0.5))
        out = channels.build_material_plane(plan, {}, size=(2, 2))
        assert out.shape == (2, 2, 4)
        assert np.allclose(out, (0.1, 0.2, 0.3, 0.5))


class TestValidation:
    """Broken plans must fail loudly with clear errors."""

    def test_unknown_alpha_mode_rejected(self):
        plan = ChannelPlan(base_key="base", alpha_mode="bogus")
        with pytest.raises(ValueError, match="alpha_mode"):
            channels.build_material_plane(plan, {"base": _base_plane()})

    def test_unknown_channel_rejected(self):
        plan = ChannelPlan(
            base_key="base",
            alpha_mode=ALPHA_SEPARATE,
            alpha=ChannelSource(image_key="mask", channel="Q"),
        )
        with pytest.raises(ValueError, match="channel"):
            channels.build_material_plane(
                plan, {"base": _base_plane(), "mask": _base_plane()}
            )

    def test_plan_without_any_source_rejected(self):
        plan = ChannelPlan(base_key="", solid_color=None)
        with pytest.raises(ValueError):
            channels.build_material_plane(plan, {}, size=(2, 2))

    def test_missing_image_key_raises_key_error(self):
        plan = ChannelPlan(base_key="missing")
        with pytest.raises(KeyError):
            channels.build_material_plane(plan, {})
