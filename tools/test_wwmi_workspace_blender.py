"""Import the optional real Xin workspace in headless Blender.

Run with Blender --background --factory-startup --python-exit-code 1
--python tools/test_wwmi_workspace_blender.py. Set MIMI_WWMI_WORKSPACE
when the fixture lives outside the original MMT cache location.
"""
import importlib
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import bpy
import numpy

# Load the repository under test, never an installed add-on copy.
# Factory startup keeps the user's open Blender scene untouched.
# No workspace buffer or selection record is modified by these tests.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
addon = importlib.import_module(ROOT.name)
addon.register()

from MIMIBlender.common.global_config import GlobalConfig
from MIMIBlender.ui.ui_func_import_mmt import ImprotFromWorkSpaceFull
from MIMIBlender.utils.json_utils import JsonUtils
from MIMIBlender.workspace.mmt_workspace import WorkSpaceModel
from MIMIBlender.workspace.submesh_json import SubmeshJson

WORKSPACE = Path(os.environ.get('MIMI_WWMI_WORKSPACE', r'D:\MMTCacheFolder\WorkSpace\WWMI\Xin'))


class Reporter:
    # Record errors that the importer otherwise only displays in the UI.
    # Successful mesh creation alone is insufficient: blueprint creation matters.
    # Capture every report so partial success cannot mask a broken component.
    def __init__(self):
        self.errors = []

    def report(self, level, message):
        if 'ERROR' in level:
            self.errors.append(message)
        print(level, message)


# Fixture notes:
# The source directory is optional on machines without the user's MMT cache.
# Synthetic layout tests remain mandatory on every machine.
# The source JSON supplies component vertex origins and exact vertex counts.
# The raw CB supplies sparse ranges and the sparse-entry origin at word 261.
# Neither origin can substitute for the other.
# Shader-state words beyond the first offset table must never become batches.
# All source resources are opened read-only through the production parser.
# Saving Import.json is mocked because it records the user's export selection.
# The mock is asserted so removing that production write cannot hide a failure.
# Blender creates all test objects inside its isolated background scene.
# The test does not save a blend file or touch the running interactive scene.
# Basis-only components are legal when none of the sparse entries target them.
# Animated components must retain every populated key's original numeric ID.
# Node output and selection checks verify usability after the import completes.
class WorkspaceTests(unittest.TestCase):
    @unittest.skipUnless(WORKSPACE.is_dir(), 'Optional real WWMI workspace is unavailable')
    def test_real_workspace_meshes_shapekeys_and_blueprint(self):
        # Resolve the actual eight components through the production scanner.
        # Patch only selection paths and the final disk write, not mesh parsing.
        # This exercises the full import and node-generation workflow in Blender.
        GlobalConfig.read_from_main_json()
        reporter = Reporter()
        with patch.object(GlobalConfig, 'path_workspace_folder', return_value=str(WORKSPACE)), patch.object(GlobalConfig, 'get_workspace_name', return_value=WORKSPACE.name), patch.object(JsonUtils, 'SaveToFile') as save:
            model = WorkSpaceModel()
            self.assertEqual(sum(len(comps) for comps in model.lod_components['LOD0'].values()), 8)
            ImprotFromWorkSpaceFull(reporter, bpy.context)
            self.assertEqual(reporter.errors, [])
            self.assertEqual(len(save.call_args.kwargs['json_dict']), 8)

            # Every source component must become one named, usable mesh object.
            # Compare a sparse key's actual positions, not just its existence.
            # These checks catch accidental shape-key skipping or wrong windows.
            for draw_ib, components in model.lod_components['LOD0'].items():
                for component_index, folder_name in components.items():
                    name = model.get_display_name('LOD0', draw_ib, component_index)
                    obj = bpy.data.objects.get(name)
                    self.assertIsNotNone(obj, name)
                    folder = Path(model.get_folder_path('LOD0', draw_ib, component_index))
                    json_path = next(folder.glob('TYPE_*/*.json'))
                    source = SubmeshJson(str(json_path))
                    self.assertEqual(len(obj.data.vertices), source.VertexCount)
                    keys = obj.data.shape_keys.key_blocks

                    # Raw CB offsets describe global sparse entries; vertex IDs
                    # must be shifted by this component's POSITION vertex origin.
                    # Repeated vertex IDs add deltas, matching runtime semantics.
                    offsets = numpy.fromfile(json_path.with_name(folder_name + '-ShapeKeyOffset.buf'), dtype='<u4')
                    ids = numpy.fromfile(json_path.with_name(folder_name + '-ShapeKeyVertexId.buf'), dtype='<u4')
                    deltas = numpy.fromfile(json_path.with_name(folder_name + '-ShapeKeyVertexOffset.buf'), dtype='<f2').reshape(-1, 6)
                    # A component outside all sparse vertex windows correctly
                    # keeps only Basis. Check expected IDs before reading a key.
                    # This prevents treating a genuinely static component as lost data.
                    expected_names = ['Basis']
                    for slot in range(127):
                        start = int(offsets[261]) + int(offsets[slot])
                        end = int(offsets[261]) + int(offsets[slot + 1])
                        local = ids[start:end].astype(numpy.int64) - source.VertexOffset
                        if numpy.any((local >= 0) & (local < source.VertexCount)):
                            expected_names.append(f'Deform {slot}')
                    self.assertEqual([key.name for key in keys], expected_names)
                    if len(keys) == 1:
                        continue
                    key = keys[1]
                    slot = int(key.name.split()[-1])
                    start = int(offsets[261]) + int(offsets[slot])
                    end = int(offsets[261]) + int(offsets[slot + 1])
                    local_ids = ids[start:end].astype(numpy.int64) - source.VertexOffset
                    mask = (local_ids >= 0) & (local_ids < source.VertexCount)
                    basis = numpy.empty(source.VertexCount * 3, dtype=numpy.float32)
                    keys['Basis'].data.foreach_get('co', basis)
                    expected = basis.reshape(-1, 3).copy()
                    # WWMI import bakes a 180-degree Z rotation and 0.01 scale
                    # into Basis and keys. Apply that same linear map to deltas.
                    # This comparison uses the final scene coordinates, not raw game units.
                    scene_deltas = deltas[start:end, :3][mask].astype(numpy.float32)
                    scene_deltas *= numpy.array([-0.01, -0.01, 0.01], dtype=numpy.float32)
                    numpy.add.at(expected, local_ids[mask], scene_deltas)
                    actual = numpy.empty_like(basis)
                    key.data.foreach_get('co', actual)
                    numpy.testing.assert_allclose(actual.reshape(-1, 3), expected, atol=1e-6)

            # Verify the blueprint and its output, not merely leftover raw meshes.
            # Failed imports used to leave meshes while reporting zero successes.
            # The newly selected blueprint must reference this workspace.
            tree = bpy.data.node_groups.get(WORKSPACE.name)
            self.assertIsNotNone(tree)
            self.assertEqual(tree.bl_idname, 'MIMIBlueprintTreeType')
            self.assertTrue(any(node.bl_idname == 'MIMINode_Result_Output' for node in tree.nodes))
            self.assertGreater(len(tree.links), 0)
            # Compare editor-space coordinates, including each frame ancestor.
            # The real full import must put every source before its target.
            def absolute_x(node):
                x = node.location.x
                parent = node.parent
                while parent is not None:
                    x += parent.location.x
                    parent = parent.parent
                return x
            for link in tree.links:
                self.assertGreaterEqual(absolute_x(link.to_node) - absolute_x(link.from_node) - link.from_node.width, 80.0)
            self.assertEqual(bpy.context.scene.mimi_global_properties.selected_blueprint_name, tree.name)
            print('Verified eight meshes, sparse shape-key coordinates, Import.json selection and blueprint.')


# Ignore Blender's own command-line flags when running the unittest runner.
if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
