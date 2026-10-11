"""WWMI multi-DrawIB export test: one mod INI, several independent geometry scopes.

Why this test exists
--------------------
WWMI used to write one INI per DrawIB. The consolidated writer must keep
geometry isolated inside the same 3Dmigoto namespace:

* a repeated ``global`` in ``[Constants]`` is dropped with "Redeclaration", so
  only the alphabetically first INI file decides the value of that variable;
* a repeated section name is only read from the first parsed occurrence, so the
  first file's ``[ResourcePositionBuffer]`` wins for the whole mod.

Before the per-DrawIB scoping this made the second DrawIB of a mod draw with the
first DrawIB's vertex buffers and shape key/vertex counts. The test runs the
real consolidated writer loop with three DrawIBs with different vertex
counts, singleton controls, and isolated geometry symbols in one INI.

Run with blender -b --factory-startup --python-exit-code 1 --python this_file.
"""
import importlib
import os
from pathlib import Path
import re
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
addon = importlib.import_module(ROOT.name)
addon.register()

from MIMIBlender.common.global_config import GlobalConfig
from MIMIBlender.common.mimi_global_properties import MIMIGlobalProperties
from MIMIBlender.common.m_ini_builder import M_IniBuilder, M_IniSection, M_SectionType
from MIMIBlender.games.wwmi import exporter as wwmi_exporter
from MIMIBlender.games.wwmi.names import WWMI_REQUIRED_RUNTIME_VERSION

# Three DrawIBs with deliberately different geometry, which is what makes the
# "first file wins" behaviour visible: their vertex counts must not be equal.
DRAW_IB_LIST = (
    ("DrawIB_0", 0, 30),
    ("DrawIB_1", 1000, 50),
    ("DrawIB_2", 2000, 70),
)

# Symbols that describe the whole mod instead of one draw range. They are
# allowed to repeat, because one file writes them and no draw range reads
# geometry through them.
MOD_LEVEL_SECTIONS = {
    "[ResourceModName]",
    "[ResourceModAuthor]",
    "[ResourceModDesc]",
    "[ResourceModLink]",
    "[ResourceModLogo]",
    # [Constants] and [Present] are singleton engine sections: 3Dmigoto merges
    # every contribution into one section, so a repeated header is required and
    # harmless.
    "[Constants]",
    "[Present]",
}
MOD_LEVEL_VARIABLES = {
    "$required_wwmi_version",
    "$mod_id",
    "$mod_enabled",
    "$object_detected",
    "$mod_visible",
    "$active0",
    "$active1",
    "$active2",
    "$swapkey0",
}


def make_draw_ib_model(draw_ib, index_offset, vertex_count):
    """Minimal DrawIBModelWWMI stand-in that satisfies every section writer."""
    component = SimpleNamespace(
        index_offset=index_offset,
        index_count=vertex_count * 3,
        vg_offset=0,
        vg_count=4,
    )
    drawcall = SimpleNamespace(
        obj_name="mesh_" + draw_ib,
        index_count=vertex_count * 3,
        index_offset=index_offset,
        vertex_count=vertex_count,
        get_submesh_name=lambda: "sub_" + draw_ib,
        get_drawindexed_str=lambda offset_dict=None: (
            "drawindexed = " + str(vertex_count * 3) + "," + str(index_offset) + ",0"
        ),
        get_condition_str=lambda: "",
    )
    return SimpleNamespace(
        draw_ib=draw_ib,
        wwmi_info=SimpleNamespace(
            vb0_hash="deadbeef",
            cb4_hash="cafebabe",
            components=[component],
            index_count=vertex_count * 3,
            shapekeys=SimpleNamespace(
                offsets_hash="", scale_hash="", batches=[], checksum=0,
                dispatch_y=0, vertex_count=0,
            ),
        ),
        mesh_vertex_count=vertex_count,
        obj_buffer_model_wwmi=SimpleNamespace(
            shapekey_vertex_ids=[],
            shapekey_offsets=[],
            shapekey_position_buffer_dict={},
            shapekey_vector_buffer_dict={},
            export_shapekey=False,
        ),
        d3d11_game_type=SimpleNamespace(
            CategoryStrideDict={"Position": 12, "Vector": 4, "Texcoord": 4, "Blend": 4},
            get_blendindices_count_wwmi=lambda: 4,
        ),
        submesh_drawcall_groups=[[drawcall]],
        submesh_model_list=[],
        submesh_texturemarkinfolist_dict={},
        object_texture_binding_resource_list=[],
        object_texture_binding_file_list=[],
        blend_remap=False,
        blend_remap_used_by_index={0: False},
        component_real_vg_count_dict={0: 4},
        ordered_drawcall_model_list=[drawcall],
    )


def render_mod_files(models=None, keys=None):
    """Run the real export loop and capture the text of every generated INI."""
    exporter = wwmi_exporter.Exporter.__new__(wwmi_exporter.Exporter)
    exporter.drawib_drawibmodel_dict = models if models is not None else {
        draw_ib: make_draw_ib_model(draw_ib, index_offset, vertex_count)
        for draw_ib, index_offset, vertex_count in DRAW_IB_LIST
    }
    exporter.blueprint_model = SimpleNamespace(
        ordered_draw_obj_data_model_list=[],
        keyname_mkey_dict=keys or {},
        global_hash_texture_binding_list=[],
    )
    exporter.mod_info_sections_written = False
    exporter.hash_sections_written = False

    written_files = {}

    def capture_save(self, path):
        """Record what the writer would put on disk without touching any file."""
        self.line_list.clear()
        for section in self.ini_section_list:
            if section.SectionName != "":
                self.line_list.append("[" + section.SectionName + "]\n")
            for line in section.SectionLineList:
                self.line_list.append(line + "\n")
        written_files[os.path.basename(path)] = "".join(self.line_list)

    # The helpers below need a real MMT workspace (file copies, texture
    # metadata). They are unrelated to the naming contract under test.
    no_op = staticmethod(lambda *args, **kwargs: None)
    with patch.object(M_IniBuilder, "save_to_file_not_reorder", capture_save):
        with patch.object(wwmi_exporter.M_IniHelper, "move_slot_style_textures", no_op):
            with patch.object(wwmi_exporter.M_IniHelper, "move_object_texture_binding_files", no_op):
                with patch.object(wwmi_exporter.M_IniHelper, "generate_hash_style_texture_ini", no_op):
                    with patch.object(wwmi_exporter.M_IniHelper, "generate_shared_slot_style_texture_ini", no_op):
                        with patch.object(wwmi_exporter.M_IniHelper, "add_object_texture_binding_resource_sections", no_op):
                            with patch.object(wwmi_exporter.M_IniHelper, "generate_hash_style_global_texture_ini", no_op):
                                with patch.object(wwmi_exporter.M_IniHelper, "generate_hash_style_object_texture_ini", no_op):
                                    with patch.object(GlobalConfig, "ini_buffer_filename", staticmethod(lambda name: "Buffers\\" + name)):
                                        with patch.object(GlobalConfig, "get_generated_mod_name", classmethod(lambda cls: "demo")):
                                            with patch.object(GlobalConfig, "path_generate_mod_folder", classmethod(lambda cls: os.getcwd())):
                                                with patch.object(MIMIGlobalProperties, "import_merged_vgmap", return_value="MERGED"):
                                                    GlobalConfig.initialize_key_count()
                                                    exporter.generate_unreal_vs_config_ini()
    return written_files


def collect_sections(text):
    """Return the bracketed section headers of one generated INI."""
    return {"[" + name + "]" for name in re.findall(r"^\[([^\]\r\n]+)\]$", text, flags=re.MULTILINE)}


def collect_variables(text):
    """Return every declared variable name of one generated INI."""
    names = set(re.findall(r"^global(?: persist)?\s+(\$[A-Za-z0-9_]+)", text, flags=re.MULTILINE))
    names.update(re.findall(r"^(\$[A-Za-z0-9_]+)\s*=", text, flags=re.MULTILINE))
    return names


def declares_global(text, variable_name):
    """Exact global declaration lookup.

    A plain substring search is not enough: "$mesh_vertex_count" is a prefix of
    the scoped "$mesh_vertex_count_<DrawIB>", which is exactly the difference
    this test is about.
    """
    pattern = r"^global(?: persist)?\s+" + re.escape(variable_name) + r"\s*="
    return re.search(pattern, text, flags=re.MULTILINE) is not None


class WWMIMultiDrawIBExportTests(unittest.TestCase):
    """One mod INI: shared controls and three isolated geometry scopes."""

    @classmethod
    def setUpClass(cls):
        cls.files = render_mod_files()

    def test_real_model_filters_drawcalls_and_metadata_by_lod(self):
        from contextlib import ExitStack
        from MIMIBlender.games.wwmi import model as wwmi_model
        from MIMIBlender.model.draw_call_model import DrawCallModel
        # Run the actual constructor through metadata assembly for each LOD.
        # Stop at geometry merging: no captured workspace is needed here.
        names = ['LOD0.deadbeef-0', 'LOD0.deadbeef-1', 'LOD1.deadbeef-0']
        blueprint = SimpleNamespace(ordered_draw_obj_data_model_list=[
            DrawCallModel(obj_name='mesh' + str(index), submesh_name=name)
            for index, name in enumerate(names)])
        class GeometryReached(Exception):
            pass
        with ExitStack() as stack:
            stack.enter_context(patch.object(wwmi_model.MMTWorkSpace, 'get_drawib_aliasname_dict', return_value={}))
            stack.enter_context(patch.object(wwmi_model.MMTWorkSpace, 'get_ordered_submesh_name_list_by_drawib', return_value=names))
            stack.enter_context(patch.object(wwmi_model.MMTWorkSpace, 'check_and_get_submesh_json_path', side_effect=lambda name: name))
            stack.enter_context(patch.object(wwmi_model, 'SubmeshJson', side_effect=lambda path: SimpleNamespace(JsonDict={}, path=path)))
            stack.enter_context(patch.object(wwmi_model.D3D11GameType, 'from_submesh_json_dict', return_value=SimpleNamespace()))
            metadata = stack.enter_context(patch.object(wwmi_model.WWMIInfoHelper, 'build_from_json_list', return_value=SimpleNamespace()))
            stack.enter_context(patch.object(wwmi_model.DrawIBModelWWMI, 'build_merged_object', side_effect=GeometryReached))
            for lod in ('LOD0', 'LOD1'):
                instance = wwmi_model.DrawIBModelWWMI.__new__(wwmi_model.DrawIBModelWWMI)
                with self.assertRaises(GeometryReached):
                    instance.__init__(draw_ib='deadbeef', blueprint_model=blueprint, lod_name=lod)
                expected = [name for name in names if name.startswith(lod + '.')]
                self.assertEqual([item.path for item in metadata.call_args.args[0]], expected)
                self.assertEqual([draw.get_submesh_name() for draw in instance.ordered_drawcall_model_list], expected)
                self.assertEqual(instance.draw_ib, 'deadbeef_' + lod)
                self.assertEqual(instance.source_draw_ib, 'deadbeef')

    def test_shape_controls_shared_but_compute_resources_scoped(self):
        from MIMIBlender.common.m_key import M_Key
        from MIMIBlender.games.wwmi import shapekeys
        # The same shape animation drives several meshes, but its buffers
        # and dispatch vertex counts must still belong to each mesh scope.
        key = M_Key(key_name='$shapeweight', key_type='time_shapekey',
                    value_list=[0, 1], weight_list=[0.0, 1.0])
        models = {name: make_draw_ib_model(name, offset, count)
                  for name, offset, count in DRAW_IB_LIST}
        for model in models.values():
            model.obj_buffer_model_wwmi.shapekey_position_buffer_dict = {'Smile': b'', 'SmileExtra': b''}
            model.obj_buffer_model_wwmi.shapekey_vector_buffer_dict = {'Smile': b'', 'SmileExtra': b''}
        with patch.object(shapekeys, 'copy_wwmi_shapekey_shaders_to_mod_folder'):
            with patch.object(shapekeys.BlueprintExportHelper, 'get_current_shapekeyname_mkey_dict', return_value={'Smile': key, 'SmileExtra': key}):
                text = render_mod_files(models=models)['demo.ini']
        self.assertEqual(text.count('global $shapeweight ='), 1)
        for name in models:
            self.assertIn('[ResourceShapeKeyPosition_Smile_' + name + ']', text)
            self.assertIn('[CommandListApplyShapeKeysPosition_' + name + ']', text)

    def test_shared_slot_texture_resource_and_copy_are_singletons(self):
        from contextlib import ExitStack
        from MIMIBlender.common import m_ini_helper as helper_module
        # Use the real cross-model texture helper. Only workspace/file I/O
        # is mocked: three geometry scopes must share one resource and copy.
        mark = SimpleNamespace(mark_type='SharedSlot', mark_hash='abcd',
                               mark_name='Diffuse', get_resource_name=lambda: 'ResourceSharedDiffuse')
        models = {}
        for name, offset, count in DRAW_IB_LIST:
            model = make_draw_ib_model(name, offset, count)
            model.submesh_model_list = [SimpleNamespace(submesh_name=name)]
            model.get_submesh_texture_markup_info_list = lambda submesh: [mark]
            model.get_submesh_part_name = lambda submesh: '0'
            models[name] = model
        builder = M_IniBuilder()
        with ExitStack() as stack:
            stack.enter_context(patch.object(MIMIGlobalProperties, 'forbid_auto_texture_ini', return_value=False))
            stack.enter_context(patch.object(wwmi_exporter.M_IniHelper, '_count_marked_textures', return_value=1))
            stack.enter_context(patch.object(wwmi_exporter.M_IniHelper, '_get_slot_texture_source_path', return_value='source.dds'))
            stack.enter_context(patch.object(helper_module.MMTWorkSpace, 'get_hash_deduped_texture_info_dict', return_value={}))
            stack.enter_context(patch.object(helper_module.os.path, 'exists', side_effect=lambda path: path == 'source.dds'))
            copied = stack.enter_context(patch.object(helper_module.shutil, 'copy2'))
            stack.enter_context(patch.object(GlobalConfig, 'path_generatemod_texture_folder', return_value='Textures/'))
            stack.enter_context(patch.object(GlobalConfig, 'ini_texture_filename', side_effect=lambda name: 'Textures/' + name))
            wwmi_exporter.M_IniHelper.generate_shared_slot_style_texture_ini(builder, models)
        text = '\n'.join(line for section in builder.ini_section_list for line in section.SectionLineList)
        self.assertEqual(text.count('[ResourceSharedDiffuse]'), 1)
        self.assertEqual(copied.call_count, 1)

    def test_shared_hotkeys_and_timelines_are_declared_once(self):
        from MIMIBlender.common.m_key import M_Key
        # Exercise the real shared helper rather than mocking controls away.
        # One classic switch and one timer must serve all three draw scopes.
        keys = {
            '$swapkey0': M_Key(key_name='$swapkey0', key_value='F6', value_list=[0, 1]),
            '$clock': M_Key(key_name='$clock', key_type='time', value_list=[0, 1]),
        }
        text = render_mod_files(keys=keys)['demo.ini']
        self.assertEqual(text.count('global persist $swapkey0 ='), 1)
        self.assertEqual(text.count('global $clock ='), 1)
        for index in range(3):
            self.assertEqual(text.count('global $active' + str(index) + '\n'), 1)
            self.assertIn('$active' + str(index) + ' = 1', text)

    def test_same_ib_lod_buffers_keep_distinct_identities(self):
        # Runtime ranges differ, even though both scopes share one raw IB.
        # Each LOD must bind its own buffers and vertex-count globals.
        models = {name: make_draw_ib_model(name, offset, count) for name, offset, count in (
            ('deadbeef_LOD0', 0, 30), ('deadbeef_LOD1', 1000, 10))}
        text = render_mod_files(models=models)['demo.ini']
        for name, model in models.items():
            self.assertIn('Buffers\\' + name + '-Position.buf', text)
            self.assertIn('global $mesh_vertex_count_' + name + ' = ' + str(model.mesh_vertex_count), text)

    def test_ambiguous_lod_runtime_match_fails_before_save(self):
        # A scoped section name cannot fix indistinguishable runtime matches.
        # Refuse both scopes instead of creating a syntactically valid conflict.
        models = {name: make_draw_ib_model(name, 0, 30)
                  for name in ('deadbeef_LOD0', 'deadbeef_LOD1')}
        with self.assertRaisesRegex(ValueError, 'ambiguous component match'):
            render_mod_files(models=models)

    def test_validator_rejects_conflicts_and_missing_commands(self):
        from MIMIBlender.common.m_ini_builder import M_IniSection, M_SectionType
        from MIMIBlender.games.wwmi.ini_validation import validate_ini_builder
        # Validate literal section headers too, not only SectionName attributes.
        # Resource sharing is safe only when the complete settings agree.
        cases = [
            ('[ResourceX]\nfilename = a.buf\n[resourcex]\nfilename = b.buf', 'duplicate section'),
            ('[Constants]\nglobal $x = 0\nglobal persist $X = 1', 'duplicate global'),
            ('[CommandListX]\nrun = CommandListMissing', 'unresolved section'),
        ]
        for body, message in cases:
            builder = M_IniBuilder()
            section = M_IniSection(M_SectionType.CommandList)
            section.SectionLineList = body.splitlines()
            builder.append_section(section)
            with self.assertRaisesRegex(ValueError, message):
                validate_ini_builder(builder)
        builder = M_IniBuilder()
        section = M_IniSection(M_SectionType.CommandList)
        section.SectionLineList = '[ResourceX]\nfilename = a.buf\n[resourcex]\nfilename = a.buf'.splitlines()
        builder.append_section(section)
        validate_ini_builder(builder)
        self.assertEqual(sum(line.lower() == '[resourcex]' for line in section.SectionLineList), 1)

    def test_legacy_migration_preserves_user_edits(self):
        import hashlib
        import tempfile
        from MIMIBlender.games.wwmi.ini_validation import disable_legacy_ini_files
        # Reproduce the builder checksum and CRLF conversion on Windows.
        # A user-edited legacy file must stop migration without being touched.
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / 'demo_deadbeef.ini'
            body = '[ResourcePositionBuffer_deadbeef]\nfilename = a.buf\n; WWMIv1\n'
            text = body + '\n;sha256=' + hashlib.sha256(body.encode()).hexdigest() + '\n\n'
            file.write_text(text, encoding='utf-8')
            disable_legacy_ini_files(folder, 'demo', ['deadbeef'])
            self.assertFalse(file.exists())
            self.assertEqual(file.with_suffix('.ini.disabled').read_text(), text)
            file.write_text(text.replace('a.buf', 'edited.buf'), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'edited or unrecognized'):
                disable_legacy_ini_files(folder, 'demo', ['deadbeef'])
            self.assertIn('edited.buf', file.read_text())

    def test_migration_uses_real_writer_and_keeps_backups(self):
        import tempfile
        from MIMIBlender.games.wwmi.ini_validation import disable_legacy_ini_files
        # Exercise the actual writer checksum, not only a handmade footer.
        # Even scopes removed from the blueprint must no longer load twice.
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / 'demo_removed.ini'
            builder = M_IniBuilder()
            resource = M_IniSection(M_SectionType.ResourceBuffer)
            resource.append('[ResourcePositionBuffer_removed]')
            resource.append('filename = a.buf')
            resource.append('; WWMIv1')
            builder.append_section(resource)
            builder.save_to_file_not_reorder(str(file))
            file.with_suffix('.ini.disabled').write_text('previous backup')
            disable_legacy_ini_files(folder, 'demo', [])
            self.assertFalse(file.exists())
            self.assertEqual(file.with_suffix('.ini.disabled').read_text(), 'previous backup')
            self.assertTrue(file.with_suffix('.ini.disabled.1').is_file())

    def test_migration_preflights_all_files(self):
        import hashlib
        import tempfile
        from MIMIBlender.games.wwmi.ini_validation import disable_legacy_ini_files
        # A valid candidate sorted before an edited one must remain active
        # when migration is refused; no partial rename may occur.
        with tempfile.TemporaryDirectory() as folder:
            good = Path(folder) / 'demo_a.ini'
            body = '[ResourcePositionBuffer_a]\n; WWMIv1\n'
            good.write_text(body + '\n;sha256=' + hashlib.sha256(body.encode()).hexdigest())
            (Path(folder) / 'demo_b.ini').write_text('user edited')
            with self.assertRaisesRegex(ValueError, 'edited or unrecognized'):
                disable_legacy_ini_files(folder, 'demo', ['a', 'b'])
            self.assertTrue(good.is_file())

    def test_all_draw_ibs_share_one_file(self):
        self.assertEqual(list(self.files), ["demo.ini"])
        sections = collect_sections(self.files["demo.ini"])
        for draw_ib, _, _ in DRAW_IB_LIST:
            self.assertIn("[TextureOverrideComponent0_" + draw_ib + "]", sections)

    def test_no_duplicate_sections_or_globals(self):
        # Sets alone hid repeated declarations in the earlier regression.
        # Compare the actual occurrence list case-insensitively instead.
        text = self.files["demo.ini"]
        sections = re.findall(r"^\[([^\]\r\n]+)\]$", text, re.MULTILINE)
        globals_ = re.findall(r"^global(?: persist)?\s+(\$[^\s=]+)", text, re.MULTILINE)
        self.assertEqual(len(sections), len(set(name.lower() for name in sections)))
        self.assertEqual(len(globals_), len(set(name.lower() for name in globals_)))
        self.assertEqual(text.count("[Constants]"), 1)
        self.assertEqual(text.count("[Present]"), 1)

    def test_registration_uses_detected_scope(self):
        # A later LOD must not register the first model's object GUID.
        text = self.files["demo.ini"]
        for draw_ib, _, _ in DRAW_IB_LIST:
            self.assertIn("if $object_detected_" + draw_ib, text)
            self.assertIn("$object_detected_" + draw_ib + " = 1", text)

    def test_vertex_counts_are_not_redeclared_across_files(self):
        # The concrete failure: three files each declared
        # "global $mesh_vertex_count = <own value>" and only the first survived.
        for _name, text in self.files.items():
            self.assertFalse(
                declares_global(text, "$mesh_vertex_count"),
                "the unscoped global would be dropped for every file but the first",
            )
        for draw_ib, _index_offset, vertex_count in DRAW_IB_LIST:
            self.assertTrue(
                declares_global(self.files["demo.ini"], "$mesh_vertex_count_" + draw_ib),
                draw_ib + " must declare its own vertex count",
            )
            self.assertIn(
                "global $mesh_vertex_count_" + draw_ib + " = " + str(vertex_count),
                self.files["demo.ini"],
            )

    def test_each_file_binds_its_own_buffers(self):
        for draw_ib, _index_offset, _vertex_count in DRAW_IB_LIST:
            text = self.files["demo.ini"]
            self.assertIn("[ResourcePositionBuffer_" + draw_ib + "]", text)
            self.assertIn("filename = Buffers\\" + draw_ib + "-Position.buf", text)
            self.assertIn("[ResourceIndexBuffer_" + draw_ib + "]", text)
            self.assertIn("filename = Buffers\\" + draw_ib + "-Component1.buf", text)

    def test_runtime_api_names_are_untouched(self):
        for name, text in self.files.items():
            for runtime_line in re.findall(r"^.*WWMIv1.*$", text, flags=re.MULTILINE):
                # A DrawIB suffix inside the runtime namespace would silently
                # break registration, so the namespace must stay verbatim.
                for draw_ib, _index_offset, _vertex_count in DRAW_IB_LIST:
                    self.assertNotIn("WWMIv1\\" + draw_ib, runtime_line, name)
                    self.assertNotIn("WWMIv1\\\\" + draw_ib, runtime_line, name)

    def test_required_version_is_the_tested_runtime(self):
        for name, text in self.files.items():
            self.assertIn(
                "global $required_wwmi_version = " + WWMI_REQUIRED_RUNTIME_VERSION,
                text,
                name,
            )


if __name__ == '__main__':
    try:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(WWMIMultiDrawIBExportTests)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    finally:
        addon.unregister()
    if not result.wasSuccessful():
        raise AssertionError('WWMI multi DrawIB export tests failed')
