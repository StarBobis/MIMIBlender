"""Render actual blueprint nodes in a disposable Blender GUI session.

Run without -b, with --factory-startup --python-exit-code 1 --python this_file.
Screenshots go to ignored tmp/; no user preferences or existing files are loaded.
"""
import importlib
from pathlib import Path
import sys

import bpy

# Register the checkout, not an installed copy of an older release.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
addon = importlib.import_module(ROOT.name)
addon.register()
# Suppress the delayed startup splash only in this disposable process.
# Do not save preferences; the user's normal startup behavior stays unchanged.
bpy.context.preferences.view.show_splash = False
output_dir = ROOT / 'tmp'
output_dir.mkdir(exist_ok=True)

# Recreate the reported Object List -> Master Mesh Group layout first.
# Keeping the sample small makes both socket labels and dots easy to inspect.
tree = bpy.data.node_groups.new('blueprint_ui_audit', 'MIMIBlueprintTreeType')
tree.use_fake_user = True
source = tree.nodes.new('MIMINode_Object_List')
source.location = (0, 160)
for name in ('body_mesh', 'hair_mesh'):
    addon.blueprint_node_object_list._append_object_list_item(source, name)
target = tree.nodes.new('MIMINode_Object_Group')
target.label = 'Master Mesh Group'
target.location = (420, -50)
target.width = 300
for socket in list(source.outputs)[1:]:
    tree.links.new(socket, target.inputs[-1])

# The largest factory area is a valid editor with a real GPU-drawn window.
area = max(bpy.context.screen.areas, key=lambda item: item.width * item.height)
area.type = 'NODE_EDITOR'
area.spaces.active.tree_type = tree.bl_idname
area.spaces.active.node_tree = tree
area.spaces.active.pin = True
region = next(item for item in area.regions if item.type == 'WINDOW')
stage = 0


def capture():
    global stage
    # Timers allow Blender to finish layout and repaint before each capture.
    # Every stage is bounded; the process always exits after the final frame.
    with bpy.context.temp_override(area=area, region=region):
        if stage == 0:
            bpy.ops.node.view_all()
        elif stage == 1:
            bpy.ops.screen.screenshot(filepath=str(output_dir / 'blueprint_socket_labels.png'))
            # Draw every registered blueprint node, including expanded states.
            # Invalid RNA fields and operator IDs appear as errors in the log.
            for index, cls in enumerate(addon.blueprint_node_base.MIMINodeBase.__subclasses__()):
                node = tree.nodes.new(cls.bl_idname)
                node.location = ((index % 4) * 720, -450 - (index // 4) * 650)
                for name in ('show_details', 'enable_shapekey', 'use_specific_output_folder'):
                    if hasattr(node, name):
                        setattr(node, name, True)
            bpy.ops.node.view_all()
        elif stage == 2:
            # New nodes need a completed layout pass before view_all can fit them.
            bpy.ops.node.view_all()
        elif stage == 3:
            bpy.ops.screen.screenshot(filepath=str(output_dir / 'blueprint_all_nodes_en.png'))
            addon.i18n.apply_language('zh')
            addon.i18n.redraw_all_areas()
        elif stage == 4:
            bpy.ops.screen.screenshot(filepath=str(output_dir / 'blueprint_all_nodes_zh.png'))
            print('PASS: rendered all blueprint nodes in English and Chinese', flush=True)
            bpy.ops.wm.quit_blender()
            return None
    stage += 1
    return 2.0


# Timer errors must terminate rather than leave an unattended GUI process.
def guarded_capture():
    try:
        return capture()
    except Exception:
        import traceback
        traceback.print_exc()
        bpy.ops.wm.quit_blender()
        return None


bpy.app.timers.register(guarded_capture, first_interval=2.0)
