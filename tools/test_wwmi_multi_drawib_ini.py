"""WWMI multi-DrawIB export test: one mod, several INI files, no symbol reuse.

Why this test exists
--------------------
WWMI writes one INI per DrawIB, but 3Dmigoto loads every INI of a mod into one
global namespace:

* a repeated ``global`` in ``[Constants]`` is dropped with "Redeclaration", so
  only the alphabetically first INI file decides the value of that variable;
* a repeated section name is only read from the first parsed occurrence, so the
  first file's ``[ResourcePositionBuffer]`` wins for the whole mod.

Before the per-DrawIB scoping this made the second DrawIB of a mod draw with the
first DrawIB's vertex buffers and shape key/vertex counts. The test runs the
real per-DrawIB writer loop with three DrawIBs that have different vertex
counts and asserts that no symbol is shared between the generated files.

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
from MIMIBlender.common.m_ini_builder import M_IniBuilder
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


def render_mod_files():
    """Run the real export loop and capture the text of every generated INI."""
    exporter = wwmi_exporter.Exporter.__new__(wwmi_exporter.Exporter)
    exporter.drawib_drawibmodel_dict = {
        draw_ib: make_draw_ib_model(draw_ib, index_offset, vertex_count)
        for draw_ib, index_offset, vertex_count in DRAW_IB_LIST
    }
    exporter.blueprint_model = SimpleNamespace(
        ordered_draw_obj_data_model_list=[],
        keyname_mkey_dict={},
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
                                    with patch.object(wwmi_exporter.M_IniHelper, "add_branch_key_sections", no_op):
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
    """One mod, three DrawIBs: the generated files must not share symbols."""

    @classmethod
    def setUpClass(cls):
        cls.files = render_mod_files()

    def test_every_draw_ib_gets_its_own_file(self):
        self.assertEqual(
            sorted(self.files.keys()),
            ["demo_DrawIB_0.ini", "demo_DrawIB_1.ini", "demo_DrawIB_2.ini"],
        )

    def test_each_file_holds_only_its_own_component_section(self):
        # The component numbering must not leak from one DrawIB into another.
        for draw_ib, _index_offset, _vertex_count in DRAW_IB_LIST:
            sections = collect_sections(self.files["demo_" + draw_ib + ".ini"])
            component_sections = sorted(name for name in sections if name.startswith("[TextureOverrideComponent"))
            self.assertEqual(
                component_sections,
                ["[TextureOverrideComponent0_" + draw_ib + "]"],
                draw_ib + " must only contain its own component section",
            )

    def test_no_symbol_is_shared_between_files(self):
        """This is the regression that used to make the 2nd DrawIB render wrong."""
        variables_by_file = {
            name: collect_variables(text) for name, text in self.files.items()
        }
        sections_by_file = {
            name: collect_sections(text) for name, text in self.files.items()
        }

        file_names = sorted(self.files.keys())
        for index, first in enumerate(file_names):
            for second in file_names[index + 1:]:
                shared_variables = sorted(
                    variables_by_file[first] & variables_by_file[second] - MOD_LEVEL_VARIABLES
                )
                self.assertEqual(
                    shared_variables, [],
                    first + " and " + second + " declare the same global(s): "
                    + str(shared_variables) + "; 3Dmigoto keeps only the first declaration",
                )
                shared_sections = sorted(
                    sections_by_file[first] & sections_by_file[second] - MOD_LEVEL_SECTIONS
                )
                self.assertEqual(
                    shared_sections, [],
                    first + " and " + second + " define the same section(s): "
                    + str(shared_sections) + "; 3Dmigoto only reads the first definition",
                )

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
                declares_global(self.files["demo_" + draw_ib + ".ini"], "$mesh_vertex_count_" + draw_ib),
                draw_ib + " must declare its own vertex count",
            )
            self.assertIn(
                "global $mesh_vertex_count_" + draw_ib + " = " + str(vertex_count),
                self.files["demo_" + draw_ib + ".ini"],
            )

    def test_each_file_binds_its_own_buffers(self):
        for draw_ib, _index_offset, _vertex_count in DRAW_IB_LIST:
            text = self.files["demo_" + draw_ib + ".ini"]
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
