"""PGR support for the generic interaction deformation.

PGR shares the GPU pre-skinning compute path and the position layout of
Naraka, so the same generic backend applies.
"""

from ...common.global_config import LogicName
from ...common.interaction import backend as interaction_backend


def register_backend():
    """Register the interaction backend of this preset."""
    return interaction_backend.register_backend(
        LogicName.PGR,
        interaction_backend.GpuPreSkinningBackend(),
    )
