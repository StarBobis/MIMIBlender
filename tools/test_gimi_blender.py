"""Real Blender registration and blueprint UI regression for GIMI semantics.

Run in a factory-startup background process, never in a user's scene.
No model geometry, external textures or blend files are touched.
"""
import importlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import bpy

# Load the shipped addon entry point so RNA and all imports are tested.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
addon = importlib.import_module(ROOT.name)
addon.register()
config = importlib.import_module(ROOT.name + '.common.global_config').GlobalConfig
blueprint = importlib.import_module(ROOT.name + '.model.blueprint_model').BluePrintModel
texture = addon.blueprint_node_texture


# Record the draw callback's controls without needing a visible UI window.
# The production callback still receives a real registered Blender node.
class Layout:
    def __init__(self):
        self.properties = []
        self.labels = []

    def row(self):
        return self

    def column(self, **kwargs):
        return self

    def box(self):
        return self

    def template_list(self, *args, **kwargs):
        pass

    def operator(self, *args, **kwargs):
        return SimpleNamespace()

    def prop(self, item, name):
        self.properties.append(name)

    def label(self, **kwargs):
        self.labels.append(kwargs.get('text', ''))


# The obsolete switch must not be exposed by registered scene properties.
assert 'gimi_use_orfix' not in bpy.context.scene.mimi_global_properties.bl_rna.properties
config.logic_name = 'GIMI'
tree = bpy.data.node_groups.new('gimi_test', addon.blueprint_node_base.MIMIBlueprintTree.bl_idname)
node = tree.nodes.new('MIMINode_Texture_Bind')
item = node.texture_slot_items.add()

# Stub only workspace lookup; the enum and its update callbacks stay real.
texture._load_submesh_mark_dicts = lambda *args, **kwargs: [
    {'name': 'DiffuseMap', 'type': 'Slot', 'slot': 'ps-t9', 'hash': '12345678', 'filename': 'diffuse.dds'}
]
texture._resolve_upstream_submesh_name = lambda *args: '12345678-0'
item.mark_name = 'DiffuseMap'
item.restore_after_draw = True
layout = Layout()
node.draw_buttons(bpy.context, layout)
assert r'Resource\GIMI\Diffuse' in layout.labels
assert 'slot' not in layout.properties
assert 'restore_after_draw' not in layout.properties
assert '(+restore)' not in item.name

# A semantic keeps closest-node priority even if captured slots differ.
# Two different semantics sharing one captured slot must both survive.
inner = [{'source_type': 'MARK', 'mark_name': 'Diffuse', 'slot': 'ps-t9', 'owner': 'inner'}]
outer = [{'source_type': 'MARK', 'mark_name': 'DiffuseMap', 'slot': 'ps-t0', 'owner': 'outer'},
         {'source_type': 'MARK', 'mark_name': 'LightMap', 'slot': 'ps-t9'}]
merged = blueprint._merge_texture_slot_bindings(inner, outer)
assert len(merged) == 2 and merged[0]['owner'] == 'inner'

# Explicit external RESOURCE rows expose a physical slot with mandatory restore.
# The saved checkbox remains RNA-compatible but is no longer editable in the UI.
item.source_type = 'RESOURCE'
layout = Layout()
node.draw_buttons(bpy.context, layout)
assert 'slot' in layout.properties and 'restore_after_draw' not in layout.properties

# Other presets retain their original physical merge and UI behavior.
config.logic_name = 'ZZMI'
item.source_type = 'MARK'
layout = Layout()
node.draw_buttons(bpy.context, layout)
assert 'slot' in layout.properties and 'restore_after_draw' not in layout.properties
assert len(blueprint._merge_texture_slot_bindings(inner, outer)) == 2
print('RESULT ' + json.dumps({'blender': bpy.app.version_string, 'gimi_registration_ui_nested_merge': 'passed'}))
