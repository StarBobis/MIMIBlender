"""WWMI shader resource slot export test: slot driven binding, views, no Blend.

Why this test exists
--------------------
Late WuWa captures contain static meshes where the position stream is the only
vertex buffer slot still bound: the vertex shader fetches the vector and texcoord
records from buffers bound to ``vs-t1`` / ``vs-t0``. Such a DrawIB has no Blend
category and no Color category either.

The exporter has to

* bind every category to the slot the capture dumped it from instead of the
  fixed vertex buffer slot, so a shader resource fetched stream is replaced at
  all;
* declare a resource view for such a slot, because a view has to name its
  element format and width while a vertex buffer needs no view;
* keep the vertex buffer binding of the same category as well, so a shader
  variant that reads the input assembler keeps working on the same data;
* never reference ``ResourceBlendBuffer`` when the layout has no Blend category:
  the ini validator aborts the whole mod with "unresolved section reference".

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

# One DrawIB is enough: this test is about one captured layout, not about
# keeping several DrawIBs apart.
DRAW_IB = "DrawIB_SRV"

# The captured layout of the static mesh:
# * slot 0 holds a 12 byte position record,
# * vs-t1 holds an 8 byte tangent + normal record,
# * vs-t0 holds a 16 byte texcoord record,
# * there is neither a Blend nor a Color record.
POSITION_ELEMENT = SimpleNamespace(Category="Position", Format="R32G32B32_FLOAT", ByteWidth=12)
VECTOR_ELEMENTS = [
    SimpleNamespace(Category="Vector", Format="R8G8B8A8_SNORM", ByteWidth=4),
    SimpleNamespace(Category="Vector", Format="R8G8B8A8_SNORM", ByteWidth=4),
]
TEXCOORD_ELEMENTS = [
    SimpleNamespace(Category="Texcoord", Format="R16G16_FLOAT", ByteWidth=4)
    for _ in range(4)
]


def make_draw_ib_model():
    """Minimal DrawIBModelWWMI stand-in that satisfies every section writer."""
    component = SimpleNamespace(
        index_offset=0,
        index_count=300,
        vg_offset=0,
        # A static mesh has no skinning at all, so it owns no vertex group.
        vg_count=0,
    )
    drawcall = SimpleNamespace(
        obj_name="mesh_srv",
        index_count=300,
        index_offset=0,
        vertex_count=100,
        get_submesh_name=lambda: "sub_srv",
        get_drawindexed_str=lambda offset_dict=None: "drawindexed = 300,0,0",
        get_condition_str=lambda: "",
    )
    return SimpleNamespace(
        draw_ib=DRAW_IB,
        wwmi_info=SimpleNamespace(
            vb0_hash="deadbeef",
            cb4_hash="cafebabe",
            components=[component],
            index_count=300,
            shapekeys=SimpleNamespace(
                offsets_hash="", scale_hash="", batches=[], checksum=0,
                dispatch_y=0, vertex_count=0,
            ),
        ),
        mesh_vertex_count=100,
        obj_buffer_model_wwmi=SimpleNamespace(
            shapekey_vertex_ids=[],
            shapekey_offsets=[],
            shapekey_position_buffer_dict={},
            shapekey_vector_buffer_dict={},
            export_shapekey=False,
        ),
        d3d11_game_type=SimpleNamespace(
            # No Blend and no Color: exactly the static mesh layout.
            CategoryStrideDict={"Position": 12, "Vector": 8, "Texcoord": 16},
            get_blendindices_count_wwmi=lambda: 0,
            OrderedCategoryNameList=["Position", "Vector", "Texcoord"],
            # Vector and Texcoord are shader resource fetched in this capture.
            CategoryExtractSlotDict={
                "Position": "vb0", "Vector": "vs-t1", "Texcoord": "vs-t0",
            },
            D3D11ElementList=[POSITION_ELEMENT] + VECTOR_ELEMENTS + TEXCOORD_ELEMENTS,
        ),
        submesh_drawcall_groups=[[drawcall]],
        submesh_model_list=[],
        submesh_texturemarkinfolist_dict={},
        object_texture_binding_resource_list=[],
        object_texture_binding_file_list=[],
        blend_remap=False,
        blend_remap_used_by_index={0: False},
        component_real_vg_count_dict={0: 0},
        ordered_drawcall_model_list=[drawcall],
    )


def render_mod_files():
    """Run the real export loop and capture the generated INI text."""
    exporter = wwmi_exporter.Exporter.__new__(wwmi_exporter.Exporter)
    exporter.drawib_drawibmodel_dict = {DRAW_IB: make_draw_ib_model()}
    exporter.blueprint_model = SimpleNamespace(
        ordered_draw_obj_data_model_list=[],
        keyname_mkey_dict={},
        global_hash_texture_binding_list=[],
    )
    exporter.mod_info_sections_written = False
    exporter.hash_sections_written = False

    written_files = {}

    def capture_save(self, path):
        """Record what the writer would put on disk without touching a file."""
        self.line_list.clear()
        for section in self.ini_section_list:
            if section.SectionName != "":
                self.line_list.append("[" + section.SectionName + "]\n")
            for line in section.SectionLineList:
                self.line_list.append(line + "\n")
        written_files[os.path.basename(path)] = "".join(self.line_list)

    # The helpers below need a real MMT workspace (file copies, texture
    # metadata). They are unrelated to the binding contract under test.
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


class WWMIShaderResourceIniTests(unittest.TestCase):
    """The generated ini of a shader resource fetched static mesh."""

    @classmethod
    def setUpClass(cls):
        cls.files = render_mod_files()
        cls.text = "\n".join(cls.files.values())

    def scoped(self, name):
        """Return the per-DrawIB symbol name the exporter should have used."""
        return name + "_" + DRAW_IB

    def section_body(self, section_name):
        """Return the settings of one generated [section], empty when absent."""
        match = re.search(
            r"^\[" + re.escape(section_name) + r"\]\n(.*?)(?=^\[|\Z)",
            self.text,
            flags=re.MULTILINE | re.DOTALL,
        )
        return match.group(1) if match else ""

    def test_vector_stream_is_bound_to_the_captured_shader_slot(self):
        # The vertex shader fetches the record from vs-t1, so the mod has to
        # replace that slot; binding only vb1 would change nothing in game.
        self.assertIn("vs-t1 = ref " + self.scoped("ResourceVectorBufferSrv"), self.text)
        # The input assembler slot keeps the plain record buffer as well.
        self.assertIn("vb1 = " + self.scoped("ResourceVectorBuffer"), self.text)

    def test_texcoord_stream_switches_between_the_two_view_widths(self):
        # The texcoord record has two documented element widths: half4 groups
        # (the default) and single half2 elements.
        self.assertIn("if $srv_texcoord_half2_" + DRAW_IB, self.text)
        self.assertIn("  vs-t0 = ref " + self.scoped("ResourceTexcoordBufferSrvHalf2"), self.text)
        self.assertIn("  vs-t0 = ref " + self.scoped("ResourceTexcoordBufferSrv"), self.text)
        self.assertIn("global $srv_texcoord_half2_" + DRAW_IB + " = 0", self.text)
        self.assertIn("vb2 = " + self.scoped("ResourceTexcoordBuffer"), self.text)

    def test_shader_resource_views_name_their_element_layout(self):
        # A resource view needs a format and an element width; the vector record
        # is read as one four byte normalized element, the texcoord record as an
        # eight byte half4 element by default.
        vector_body = self.section_body(self.scoped("ResourceVectorBufferSrv"))
        self.assertIn("format = DXGI_FORMAT_R8G8B8A8_SNORM", vector_body)
        self.assertIn("stride = 4", vector_body)
        self.assertIn("filename = Buffers\\" + DRAW_IB + "-Vector.buf", vector_body)

        texcoord_body = self.section_body(self.scoped("ResourceTexcoordBufferSrv"))
        self.assertIn("format = DXGI_FORMAT_R16G16B16A16_FLOAT", texcoord_body)
        self.assertIn("stride = 8", texcoord_body)

        half2_body = self.section_body(self.scoped("ResourceTexcoordBufferSrvHalf2"))
        self.assertIn("format = DXGI_FORMAT_R16G16_FLOAT", half2_body)
        self.assertIn("stride = 4", half2_body)

    def test_static_mesh_never_references_a_blend_buffer(self):
        # No Blend category means no [ResourceBlendBuffer_<drawib>] declaration
        # and no vb4 binding; referencing one used to abort the ini validation.
        # The merged skeleton path declares an empty ResourceBlendBufferOverride
        # on purpose, and that symbol is unrelated to the Blend category.
        self.assertNotIn("ResourceBlendBuffer_" + DRAW_IB, self.text)
        self.assertNotIn("vb4 =", self.text)

    def test_missing_color_category_nulls_the_slot(self):
        # COLOR is not part of this layout, so the slot is cleared instead of
        # leaving a buffer of the previous draw behind.
        self.assertIn("vb3 = null", self.text)
        self.assertNotIn("ResourceColorBuffer", self.text)

    def test_every_referenced_resource_is_declared(self):
        # The ini validator only checks this for the generated file, so assert
        # it here as well: an undeclared Resource symbol breaks the whole mod.
        declared = {
            "[" + name + "]"
            for name in re.findall(r"^\[([^\]\r\n]+)\]$", self.text, flags=re.MULTILINE)
        }
        for reference in re.findall(r"\bref ((?:Resource)[\w.\\-]+)", self.text):
            self.assertIn("[" + reference + "]", declared, reference)

    def test_no_duplicate_sections(self):
        headers = re.findall(r"^\[([^\]\r\n]+)\]$", self.text, flags=re.MULTILINE)
        self.assertEqual(len(headers), len(set(headers)), "duplicate section header")


if __name__ == '__main__':
    try:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(WWMIShaderResourceIniTests)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    finally:
        addon.unregister()
    if not result.wasSuccessful():
        raise AssertionError('WWMI shader resource ini tests failed')
