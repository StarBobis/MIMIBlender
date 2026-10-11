"""User interface components for the Material Combiner addon.

This package contains the UI panels and interface elements for the Material Combiner:
- credits_panel: Developer credits and support links.
- main_panel: Primary interface for material combination settings.
- property_panel: Material-specific property configuration.
- selection_menu: Material selection and management interface.
"""

from . import (
    main_panel,
    property_panel,
    selection_menu,
)

__all__ = [
    "main_panel",
    "property_panel",
    "selection_menu",
]
