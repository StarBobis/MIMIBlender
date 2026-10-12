"""Verify imported blueprint coordinates after Blender draws and shrinks frames.

Run without --background, using --factory-startup --python-exit-code 1.
The disposable session saves a screenshot to ignored tmp/ and then exits.
"""
import importlib.util
from pathlib import Path
import sys

import bpy

# Reuse real import fixtures and coordinate assertions from the headless suite.
# This process never opens or saves a user scene or preference file.
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('layout_tests', ROOT / 'tools/test_import_blueprint_layout_blender.py')
tests = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tests)
case = tests.ImportLayoutTests()
case.setUp()
case.make_import(29)
bpy.context.preferences.view.show_splash = False

# The frame's automatic fit happens only when a real node editor draws it.
# Headless checks alone cannot detect a post-draw horizontal reversal.
area = max(bpy.context.screen.areas, key=lambda item: item.width * item.height)
area.type = 'NODE_EDITOR'
area.spaces.active.tree_type = case.tree.bl_idname
area.spaces.active.node_tree = case.tree
area.spaces.active.pin = True
region = next(item for item in area.regions if item.type == 'WINDOW')
stage = 0


def verify():
    global stage
    try:
        # Wait for actual layout passes rather than guessing frame dimensions.
        # The second pass also lets view_all fit newly measured node bounds.
        with bpy.context.temp_override(area=area, region=region):
            for node in case.tree.nodes:
                print(node.name, tuple(node.location), tests.absolute_position(node), flush=True)
            if stage < 2:
                bpy.ops.node.view_all()
                stage += 1
                return 1.0
            case.assert_forward_links()
            output = ROOT / 'tmp/import_blueprint_layout.png'
            output.parent.mkdir(exist_ok=True)
            # Explicit PNG settings keep the screenshot format and suffix aligned.
            bpy.context.scene.render.image_settings.file_format = 'PNG'
            bpy.ops.screen.screenshot(filepath=str(output))
            print('PASS: all imported links flow left to right after frame redraw', flush=True)
        bpy.ops.wm.quit_blender()
    except Exception:
        # Timer exceptions must fail the command, not leave a background GUI.
        # Print the full failure so CI does not mistake a clean quit for success.
        import traceback
        traceback.print_exc()
        import os
        os._exit(1)
    return None


# A bounded timer gives the GPU editor time to complete real frame fitting.
bpy.app.timers.register(verify, first_interval=1.0)
