"""Which game presets can consume the cross-IB render configuration.

Cross-IB rendering has two halves:

1. the blueprint half (the node scan, the Skip Draw validation and the two
   user entry points) is game neutral: it only fills
   ``DrawCallModel.cross_render_at_submesh`` with the host Submesh name,
2. the INI half has to be written per preset, because every exporter decides
   how the guest vertex buffers are recovered inside the host's draw call.

A preset may therefore only be listed here when its exporter really turns
that annotation into sections; otherwise the node would look usable and
silently produce nothing.  Keeping the list in one leaf module means the
registry, the node menu, the timeline panel and the post-processor can never
disagree about which presets are supported.
"""

from .global_config import LogicName


# Everything the exports share, including the diagnostic prefix, so a user can
# search the console output for one string no matter which preset failed.
CROSS_IB_ERROR_PREFIX = "Cross-IB Render: "


# Presets whose exporter implements the cross-IB sections.
# - Naraka: the modded vertex data is written into the game's own vertex
#   buffers by a compute shader, so the guest backup captures those buffers.
# - GF2: the vertex buffer slots themselves are replaced by the mod's own
#   resource buffers, so the backup captures the mod's buffers.
CROSS_IB_SUPPORTED_LOGIC_NAMES = (
    LogicName.Naraka,
    LogicName.GF2,
)


def supports_cross_ib(logic_name) -> bool:
    """Return True when this preset can export cross-IB render pairs."""
    return logic_name in CROSS_IB_SUPPORTED_LOGIC_NAMES
