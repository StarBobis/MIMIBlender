'''
MIMIBlender - Blender add-on for MIMITools (3Dmigoto modding).
'''


from .common import global_properties
from .common import gimi_body_outline


# UI panels
from .ui import ui_panel_basic
from .ui import ui_panel_model
from .sword import ui_panel_sword
from .ui import ui_func_import_ssmt
from .ui import ui_panel_fast_texture

from .blueprint import blueprint_node_obj
from .blueprint import blueprint_node_base
from .blueprint import blueprint_node_menu
from .blueprint import blueprint_node_shapekey

from .blueprint import blueprint_node_face_mod
from .blueprint import blueprint_node_group
from .blueprint import blueprint_file_drop
from .blueprint import blueprint_node_highlight

from .ui import ui_func_export

# Texture combiner tool (texcomb) - material merge feature integrated from another add-on
from . import texcomb

bl_info = {
    "name": "MIMIBlender",
    "description": "The Blender add-on for MIMITools",
    "blender": (5, 2, 0),
    "version": (1, 0, 7),
    "location": "View3D",
    "category": "Generic"
}


def register():
    # Fault-tolerant registration per module: in the past a single node class
    # failing to register broke the whole register chain and made all the
    # sidebar panels disappear. This guarantees that one failing module does
    # not affect the others; failures are printed to the console for debugging.
    for step in _register_steps():
        try:
            step()
        except Exception:
            import traceback
            print(f"[MIMIBlender] register step failed: {getattr(step, '__module__', step)}")
            traceback.print_exc()


def _register_steps():
    # 1. Configs
    yield global_properties.register
    yield gimi_body_outline.register

    # 2. UI Panels & Logic
    yield blueprint_node_base.register
    yield blueprint_node_group.register
    yield ui_panel_basic.register
    yield ui_panel_model.register
    yield ui_panel_sword.register
    yield ui_func_import_ssmt.register
    yield ui_panel_fast_texture.register

    # Blueprint system
    # The ShapeKey PropertyGroup must be registered before the Generate Mod node that references it.
    yield blueprint_node_shapekey.register
    yield blueprint_node_obj.register
    yield ui_func_export.register
    yield blueprint_node_menu.register

    yield blueprint_node_face_mod.register
    yield blueprint_file_drop.register
    yield blueprint_node_highlight.register

    # Texture combiner tool (texcomb)
    yield texcomb.register


def unregister():
    # Unregister in the reverse order of register to avoid type dependency issues.
    # Step-by-step fault tolerance: a previous session may have left a half-registered
    # state (for example a class that never registered successfully). Unregistering it
    # directly would raise RuntimeError and break all later unregister steps, causing
    # "already registered" failures and missing panels on the next enable.
    steps = [
        gimi_body_outline.unregister,
        texcomb.unregister,
        blueprint_node_highlight.unregister,
        blueprint_file_drop.unregister,
        blueprint_node_face_mod.unregister,
        blueprint_node_group.unregister,
        blueprint_node_menu.unregister,
        ui_func_export.unregister,
        blueprint_node_obj.unregister,
        blueprint_node_shapekey.unregister,
        ui_panel_fast_texture.unregister,
        ui_func_import_ssmt.unregister,
        ui_panel_sword.unregister,
        ui_panel_model.unregister,
        ui_panel_basic.unregister,
        blueprint_node_base.unregister,
        global_properties.unregister,
    ]
    for step in steps:
        try:
            step()
        except Exception:
            import traceback
            print(f"[MIMIBlender] unregister step failed: {getattr(step, '__module__', step)}")
            traceback.print_exc()


