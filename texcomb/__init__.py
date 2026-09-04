

from .registration import register_all, unregister_all  # noqa: E402


def register() -> None:
    """Register texcomb components. Called from the main TheHerta4 plugin."""
    register_all()


def unregister() -> None:
    """Unregister texcomb components. Called from the main TheHerta4 plugin."""
    unregister_all()
