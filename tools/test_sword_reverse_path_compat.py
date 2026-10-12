"""Check reverse-folder registration for Blender 4.2 and 5.2 without Blender.

Run: python tools/test_sword_reverse_path_compat.py

The real helper and register function are extracted from the panel source.
Only Blender's property factories and class registration are replaced here.
The fake old runtime rejects the same unsupported option as Blender 4.2.
The fake new runtime records options so losing the 5.x flag fails a test.
Actual Blender integration remains in test_sword_reverse_import_blender.py.
"""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest


# Read the production functions rather than copying their compatibility logic.
# This keeps the regression tied to the property registration actually shipped.
ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'sword' / 'ui_panel_sword.py'
TREE = ast.parse(SOURCE.read_text(encoding='utf-8'))
FUNCTION_NAMES = {'_get_sword_reverse_path_options', 'register'}
FUNCTIONS = [node for node in TREE.body
             if isinstance(node, ast.FunctionDef) and node.name in FUNCTION_NAMES]


class ReversePathCompatibilityTests(unittest.TestCase):
    # Use distinct simulated runtimes so one run checks both version branches.
    # This test intentionally needs no installed bpy or other add-on modules.
    def register_for_version(self, version):
        calls = []

        def property_factory(**kwargs):
            # Reject unsupported flags just as the old bpy property API does.
            # Returning the keywords also lets the test inspect other defaults.
            options = kwargs.get('options', set())
            if version < (4, 5, 0) and 'PATH_SUPPORTS_BLEND_RELATIVE' in options:
                raise TypeError('unsupported relative-path option')
            return kwargs

        # The registration function references UI classes but never invokes them.
        # Simple named objects are sufficient to verify their registration calls.
        namespace = {}
        register_function = next(node for node in FUNCTIONS if node.name == 'register')
        for node in ast.walk(register_function):
            if isinstance(node, ast.Name):
                namespace[node.id] = SimpleNamespace(name=node.id)
        namespace.update({
            'bpy': SimpleNamespace(
                app=SimpleNamespace(version=version),
                types=SimpleNamespace(
                    Scene=SimpleNamespace(),
                    StringProperty=SimpleNamespace(bl_rna=SimpleNamespace(
                        # Mirror the RNA capability exposed by real newer Blender.
                        # The production helper does not depend on app.version.
                        properties={'is_path_supports_blend_relative'}
                        if version >= (4, 5, 0) else set(),
                    )),
                ),
                utils=SimpleNamespace(
                    register_class=calls.append,
                    previews=SimpleNamespace(new=lambda: object()),
                ),
            ),
            'preview_collections': {},
            'tr': lambda text: text,
            'set': set,
        })
        # All four factories share the same keyword-recording behavior.
        # Real StringProperty invocation is covered by the Blender integration.
        for name in ('StringProperty', 'CollectionProperty', 'IntProperty', 'EnumProperty'):
            namespace[name] = property_factory
        module = ast.Module(body=FUNCTIONS, type_ignores=[])
        exec(compile(module, str(SOURCE), 'exec'), namespace)
        namespace['register']()
        return namespace, calls

    def test_registration_for_old_and_new_blender(self):
        # 4.5 covers the installed LTS runtime, which also exposes this capability.
        # 5.2 must preserve the original flag, not silently degrade to old behavior.
        for version in ((4, 2, 16), (4, 5, 0), (5, 0, 0), (5, 2, 0)):
            with self.subTest(version=version):
                namespace, calls = self.register_for_version(version)
                scene = namespace['bpy'].types.Scene
                path_property = scene.mimi_sword_custom_reverse_output_folder_path
                expected = {'PATH_SUPPORTS_BLEND_RELATIVE'} if version >= (4, 5, 0) else set()
                self.assertEqual(path_property['options'], expected)
                self.assertEqual(len(calls), 9)
                # Preserve storage/UI settings and the cache invalidation callback.
                # A version fix must not change saved scene data or folder updates.
                self.assertEqual(path_property['default'], '')
                self.assertEqual(path_property['subtype'], 'DIR_PATH')
                self.assertIs(path_property['update'], namespace['_on_sword_reverse_source_changed'])


# Standard unittest exits nonzero on any incompatible registration or lost flag.
# It can be run on developer machines even when Blender is not on PATH.
if __name__ == '__main__':
    unittest.main(verbosity=2)
