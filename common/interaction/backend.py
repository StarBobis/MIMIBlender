"""Per-preset capability declaration for the interaction deformation.

Not every game preset can carry the interaction deformation.  The feature
needs three things at once:

* the preset has to skin its meshes in a compute shader, because the
  deformation has to run before the skinning reads the positions,
* the position category has to use the layout the runtime shader reads,
  and
* the preset has to export the position buffer as a raw byte buffer that
  the game can read back.

A preset declares that by registering a backend here.  The shared code
never asks a preset directly, so adding support for another preset never
touches the generic layer.
"""

from . import vertex_layout


# The registered backends, keyed by the logic name of the preset.
_BACKEND_DICT = {}


class GpuPreSkinningBackend:
    """Backend for presets that skin their meshes in a compute shader.

    The deformation replaces the position buffer that the skinning compute
    shader reads, so the preset has to run its skinning from a compute
    shader and has to expose the position category as a raw byte buffer.
    """

    # Shown in the node so the user knows which preset provides it.
    backend_name = "GPU pre-skinning"

    def is_supported_game_type(self, game_type) -> bool:
        """Return True when this preset can carry the deformation."""
        if game_type is None:
            return False
        if not getattr(game_type, "GPU_PreSkinning", False):
            return False
        return vertex_layout.is_supported_deform_layout(game_type)

    def describe_unsupported_game_type(self, game_type) -> str:
        """Return a short reason why the layout was rejected."""
        if game_type is None:
            return "no position data layout"
        if not getattr(game_type, "GPU_PreSkinning", False):
            return "the preset does not skin its meshes in a compute shader"
        return vertex_layout.describe_unsupported_layout(game_type)


def register_backend(logic_name, backend):
    """Register the interaction backend of one preset."""
    _BACKEND_DICT[logic_name] = backend
    return backend


def get_backend(logic_name):
    """Return the interaction backend of one preset, or None."""
    return _BACKEND_DICT.get(logic_name, None)


def get_current_backend():
    """Return the interaction backend of the active preset, or None.

    The preset is read at call time instead of being imported by the
    caller, so a preset module never has to name its own preset here.
    A preset without a backend simply gets no deformation.
    """
    from ..global_config import GlobalConfig
    return get_backend(getattr(GlobalConfig, "logic_name", None))


def has_backend(logic_name) -> bool:
    """Return True when the preset provides an interaction backend."""
    return logic_name in _BACKEND_DICT


def get_backend_logic_name_list() -> list:
    """Return the logic names of every preset with a backend."""
    return sorted(_BACKEND_DICT.keys(), key=str)
