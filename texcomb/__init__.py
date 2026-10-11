"""texcomb: texture combiner module of the MIMIBlender addon.

The pure-python image pipeline lives in texcomb.core and must stay
importable without Blender (unit tests run outside Blender with plain
pytest). Registration, which needs a REAL bpy, is therefore skipped when
bpy is absent or is only a stub/namespace package on sys.path.
"""


def _has_real_bpy() -> bool:
    """Return True only when the real Blender bpy module is available.

    A plain find_spec("bpy") is not enough: developer machines may carry a
    fake/namespace "bpy" package for type hinting that finds but cannot
    provide bpy.props / bpy.app. The real module always exposes bpy.app
    with a version, so probe for that.
    """
    try:
        import bpy
    except ImportError:
        return False
    # Real Blender always has bpy.app.version; stubs and namespace
    # packages do not.
    return hasattr(bpy, "app") and hasattr(bpy.app, "version")


# Only import the bpy-dependent registration when running inside Blender.
if _has_real_bpy():
    from .registration import register_all, unregister_all
else:
    # Outside Blender: registration is meaningless, mark it as unavailable.
    register_all = None
    unregister_all = None


def register() -> None:
    """Register texcomb components. Called from the main MIMIBlender plugin."""
    if register_all is None:
        # Outside Blender there is nothing to register into.
        return
    register_all()


def unregister() -> None:
    """Unregister texcomb components. Called from the main MIMIBlender plugin."""
    if unregister_all is None:
        return
    unregister_all()
