"""Naraka support for the generic interaction deformation.

Naraka skins its meshes in the game's own compute shader, so the position
buffer can be replaced before the skinning reads it.  The position
category of a Naraka extraction is the 40 byte float layout the runtime
shader reads, so the generic backend applies without any change.
"""

from ...common.global_config import LogicName
from ...common.interaction import backend as interaction_backend


def register_backend():
    """Register the interaction backend of this preset."""
    return interaction_backend.register_backend(
        LogicName.Naraka,
        interaction_backend.GpuPreSkinningBackend(),
    )
