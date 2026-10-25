"""Skip Draw tests: blueprint flag, model state, validation and INI output.

The feature hides a whole Submesh: the generated INI keeps handling = skip and
never re-draws the Submesh with the mod's index buffer.  Four layers have to
agree, so every layer is covered here:

1. the Submesh state folding (common/skip_draw.py),
2. the export validation (mixed marks warn, unsupported combinations raise),
3. the INI sections of the shared builders and of the preset variants that
   wrap their sections in extra state (GIMI, YYSLS, NTEMI),
4. the blueprint UI properties and the parser hand-off.

Run with blender -b --factory-startup --python-exit-code 1 --python this_file.
"""
import importlib
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
addon = importlib.import_module(ROOT.name)
addon.register()

from MIMIBlender.common import skip_draw as skip_draw_module
from MIMIBlender.common.m_ini_builder import M_IniBuilder
from MIMIBlender.games.base import sections as base_sections
from MIMIBlender.games.gimi.exporter import Exporter as GimiExporter
from MIMIBlender.games.ntemi import sections as ntemi_sections
from MIMIBlender.games.yysls import ExportYYSLS
from MIMIBlender.model.draw_call_model import DrawCallModel
from MIMIBlender.utils.log_utils import LOG as LOG_HELPER

DRAW_IB = "94517393"
HIDDEN_SUBMESH = "LOD0.94517393-0"
VISIBLE_SUBMESH = "LOD0.94517393-1"

# Minimal game type for the shared section builders. Skip Draw never reaches
# the vertex layout code, so empty dictionaries are enough.
GAME_TYPE = SimpleNamespace(
    GPU_PreSkinning=False,
    OrderedCategoryNameList=[],
    CategoryStrideDict={},
    CategoryDrawCategoryDict={},
    CategoryExtractSlotDict={},
)


def make_draw(submesh_name, obj_name="mesh_a", skip_draw=False, index_count=3, cross_render_at_submesh=""):
    """One resolved DrawCallModel as the blueprint parser would emit it."""
    draw = DrawCallModel(obj_name=obj_name, submesh_name=submesh_name)
    draw.index_count = index_count
    draw.index_offset = 0
    draw.vertex_count = 3
    draw.skip_draw = skip_draw
    draw.cross_render_at_submesh = cross_render_at_submesh
    # Unused but read by some section builders before the guard.
    draw.texture_slot_binding_list = []
    return draw


def make_submesh(submesh_name, skip_draw=False, first_index=0, extra_draws=None):
    """One Submesh view with the identity fields every section builder reads."""
    drawcall_model_list = [make_draw(submesh_name, skip_draw=skip_draw)]
    drawcall_model_list.extend(extra_draws or [])
    return SimpleNamespace(
        submesh_name=submesh_name,
        display_str=submesh_name,
        match_first_index=first_index,
        match_index_count=3,
        vertex_count=3,
        category_buffer_dict={},
        d3d11_game_type=GAME_TYPE,
        skip_draw=skip_draw,
        drawcall_model_list=drawcall_model_list,
    )


def make_drawib(submesh_model_list, draw_ib=DRAW_IB):
    """DrawIB stand-in exposing only the accessors the sections call."""
    return SimpleNamespace(
        draw_ib=draw_ib,
        # Read at the top of several section builders, before the guard.
        d3d11_game_type=GAME_TYPE,
        submesh_model_list=submesh_model_list,
        submesh_ib_dict={submesh.submesh_name: [0, 1, 2] for submesh in submesh_model_list},
        obj_name_draw_offset={},
        get_submesh_texture_markup_info_list=lambda submesh: [],
        # Same naming rule as DrawIBModel.get_submesh_unique_key.
        get_submesh_texture_override_suffix=lambda submesh: submesh.display_str.replace("-", "_"),
        get_submesh_ib_resource_name=lambda submesh: "Resource_" + submesh.display_str.replace("-", "_") + "_Index",
    )


def flatten(builder):
    """Flatten an M_IniBuilder into plain INI lines for text assertions."""
    lines = []
    for section in builder.ini_section_list:
        lines.extend(section.SectionLineList)
    return lines


def find_block(lines, header):
    """Return the lines of one [section], from its header to the next one."""
    try:
        start = lines.index(header)
    except ValueError:
        raise AssertionError("section not found: " + header + " in " + repr(lines))
    end = start + 1
    while end < len(lines) and not lines[end].strip().startswith("["):
        end += 1
    return lines[start:end]


class SkipDrawStateTests(unittest.TestCase):
    """The per-object flags must fold into one Submesh level state."""

    def test_without_a_mark_the_submesh_stays_visible(self):
        draws = [
            make_draw(HIDDEN_SUBMESH, obj_name="hair_a"),
            make_draw(HIDDEN_SUBMESH, obj_name="hair_b"),
        ]
        state, marked_owner_list, unmarked_owner_list = skip_draw_module.aggregate_skip_draw(draws)
        self.assertFalse(state)
        self.assertEqual(marked_owner_list, [])
        self.assertEqual(unmarked_owner_list, ["hair_a", "hair_b"])

    def test_one_mark_hides_the_whole_submesh(self):
        draws = [
            make_draw(HIDDEN_SUBMESH, obj_name="hair_a", skip_draw=True),
            make_draw(HIDDEN_SUBMESH, obj_name="hair_b"),
        ]
        state, marked_owner_list, unmarked_owner_list = skip_draw_module.aggregate_skip_draw(draws)
        self.assertTrue(state)
        self.assertEqual(marked_owner_list, ["hair_a"])
        # The unmarked object is reported by the export warning instead of
        # being hidden without a trace.
        self.assertEqual(unmarked_owner_list, ["hair_b"])

    def test_predicate_treats_a_missing_flag_as_visible(self):
        # Older Submesh stand-ins (and WWMI views built before this feature)
        # must never be hidden by accident.
        self.assertFalse(skip_draw_module.is_submesh_skipped(SimpleNamespace()))
        self.assertTrue(skip_draw_module.is_submesh_skipped(SimpleNamespace(skip_draw=True)))

    def test_draw_call_default_is_visible(self):
        draw = DrawCallModel(obj_name="mesh_a", submesh_name=HIDDEN_SUBMESH)
        self.assertFalse(draw.skip_draw)


class SkipDrawValidationTests(unittest.TestCase):
    """Export-time checks: warn on mixed marks, reject impossible ones."""

    def setUp(self):
        # Replace the logger so the test can inspect the warning text without
        # depending on the console colour codes. The patch restores the real
        # classmethod after every test.
        self.warning_list = []
        self.log_patcher = patch.object(LOG_HELPER, "warning", staticmethod(self.warning_list.append))
        self.log_patcher.start()
        self.addCleanup(self.log_patcher.stop)

    def test_mixed_marks_only_warn(self):
        submesh = make_submesh(
            HIDDEN_SUBMESH,
            skip_draw=True,
            extra_draws=[make_draw(HIDDEN_SUBMESH, obj_name="unmarked_hair")],
        )
        # No exception: the Submesh is hidden as asked, the warning explains
        # that the second object disappears with it.
        skip_draw_module.validate_skip_draw([make_drawib([submesh])])
        self.assertEqual(len(self.warning_list), 1)
        self.assertIn("unmarked_hair", self.warning_list[0])
        self.assertIn(HIDDEN_SUBMESH, self.warning_list[0])

    def test_clean_state_produces_no_warning(self):
        skip_draw_module.validate_skip_draw([make_drawib([make_submesh(VISIBLE_SUBMESH)])])
        self.assertEqual(self.warning_list, [])

    def test_position_animation_frame_is_rejected(self):
        submesh = make_submesh(HIDDEN_SUBMESH, skip_draw=True)
        model = make_drawib([submesh])
        # The frame draw call proves this Submesh feeds a Position.buf mod.
        model.time_pos_frame_groups = {"$dyn": {0: [make_draw(HIDDEN_SUBMESH, obj_name="frame_0")]}}
        with self.assertRaises(ValueError) as context:
            skip_draw_module.validate_skip_draw([model])
        self.assertIn("Position.buf", str(context.exception))

    def test_cross_ib_guest_is_rejected(self):
        guest = make_submesh(
            HIDDEN_SUBMESH,
            skip_draw=True,
            extra_draws=[],
        )
        # The only draw of the guest is re-issued in another Submesh, which
        # needs the VB backup captured in this very section.
        guest.drawcall_model_list[0].cross_render_at_submesh = VISIBLE_SUBMESH
        with self.assertRaises(ValueError) as context:
            skip_draw_module.validate_skip_draw([make_drawib([guest, make_submesh(VISIBLE_SUBMESH)])])
        self.assertIn("Cross-IB", str(context.exception))

    def test_cross_ib_host_is_rejected(self):
        host = make_submesh(HIDDEN_SUBMESH, skip_draw=True)
        guest = make_submesh(VISIBLE_SUBMESH)
        guest.drawcall_model_list[0].cross_render_at_submesh = HIDDEN_SUBMESH
        with self.assertRaises(ValueError) as context:
            skip_draw_module.validate_skip_draw([make_drawib([host, guest])])
        self.assertIn("Cross-IB", str(context.exception))


class SkipDrawSectionTests(unittest.TestCase):
    """The generated INI must keep the match and drop every draw."""

    def render_shared_ib(self, drawib_model, compute_shader=False):
        builder = M_IniBuilder()
        blueprint_model = SimpleNamespace(keyname_mkey_dict={})
        if compute_shader:
            base_sections.add_unity_cs_texture_override_ib_sections(
                ini_builder=builder,
                drawib_model=drawib_model,
                blueprint_model=blueprint_model,
            )
        else:
            base_sections.add_unity_vs_texture_override_ib_sections(
                ini_builder=builder,
                drawib_model=drawib_model,
                blueprint_model=blueprint_model,
            )
        return flatten(builder)

    def assert_hidden_section(self, lines, header):
        """A hidden Submesh keeps hash/match/skip and nothing else."""
        block = find_block(lines, header)
        self.assertIn("handling = skip", block, header)
        self.assertTrue(
            any(line.startswith(skip_draw_module.SKIP_DRAW_COMMENT) for line in block),
            header + " must explain why the draw is skipped",
        )
        self.assertFalse(
            any(line.strip().startswith("drawindexed") for line in block),
            header + " must not redraw the Submesh",
        )
        self.assertFalse(
            any(line.strip().startswith("ib =") for line in block),
            header + " must not bind an index buffer",
        )

    def test_shared_vertex_shader_section_is_skip_only(self):
        lines = self.render_shared_ib(make_drawib([make_submesh(HIDDEN_SUBMESH, skip_draw=True)]))
        self.assert_hidden_section(lines, "[TextureOverride_LOD0.94517393_0]")

    def test_shared_compute_shader_section_is_skip_only(self):
        lines = self.render_shared_ib(make_drawib([make_submesh(HIDDEN_SUBMESH, skip_draw=True)]),
                                      compute_shader=True)
        self.assert_hidden_section(lines, "[TextureOverride_LOD0.94517393_0]")

    def test_visible_submesh_keeps_its_draw(self):
        # Control case: without the flag the old output must not change.
        lines = self.render_shared_ib(make_drawib([make_submesh(VISIBLE_SUBMESH)]))
        block = find_block(lines, "[TextureOverride_LOD0.94517393_1]")
        self.assertIn("handling = skip", block)
        self.assertTrue(any(line.startswith("drawindexed") for line in block))
        self.assertTrue(any(line.startswith("ib = Resource_LOD0.94517393_1_Index") for line in block))
        self.assertFalse(any(line.startswith(skip_draw_module.SKIP_DRAW_COMMENT) for line in block))

    def test_gimi_hidden_submesh_gets_a_bare_skip_section(self):
        # GIMI skips the whole DrawIB once, so the per-Submesh section has no
        # skip line of its own and the helper has to write the whole section.
        exporter = GimiExporter.__new__(GimiExporter)
        builder = M_IniBuilder()
        exporter.add_unity_vs_texture_override_ib_sections(builder, make_drawib([make_submesh(HIDDEN_SUBMESH, skip_draw=True)]))
        lines = flatten(builder)
        self.assert_hidden_section(lines, "[TextureOverride_LOD0.94517393_0]")
        # The DrawIB level skip stays untouched: it hides the original draw.
        self.assertIn("handling = skip", find_block(lines, "[TextureOverride_IB_" + DRAW_IB + "]"))

    def test_yysls_hidden_submesh_closes_the_costume_gate(self):
        # YYSLS wraps every Submesh in "if $costume_mods"; the hidden section
        # must still close that gate, otherwise the rest of the INI is inside
        # a branch that never ends.
        exporter = ExportYYSLS.__new__(ExportYYSLS)
        builder = M_IniBuilder()
        exporter.add_unity_vs_texture_override_ib_sections(builder, make_drawib([make_submesh(HIDDEN_SUBMESH, skip_draw=True)]))
        block = find_block(flatten(builder), "[TextureOverride_LOD0.94517393_0]")
        self.assertIn("if $costume_mods", block)
        self.assertIn("handling = skip", block)
        self.assertEqual(block.count("endif"), 1)
        self.assertFalse(any("drawindexed" in line for line in block))

    def test_ntemi_hidden_part_is_not_redrawn(self):
        # NTEMI re-draws every part inside one DrawIB level section.
        visible = make_submesh(VISIBLE_SUBMESH, skip_draw=False, first_index=0)
        hidden = make_submesh(HIDDEN_SUBMESH, skip_draw=True, first_index=300)
        model = make_drawib([visible, hidden])
        model.index_count = 600
        model.import_json_dict = {}
        lines = []
        ntemi_sections.append_draw_overrides(lines, [model], {}, "", {})
        text = "\n".join(lines)
        hidden_token = "94517393_part01"
        self.assertNotIn("ib = ResourcePart_" + hidden_token + "_IB", text)
        self.assertNotIn("drawindexed", text[text.index(hidden_token):])
        self.assertIn("ib = ResourcePart_94517393_part00_IB", text)
        self.assertIn("; Skip Draw: part " + hidden_token, text)

    def test_every_preset_reads_the_shared_predicate(self):
        # One import line plus one guard per per-Submesh section. A preset
        # that loses its guard silently draws a hidden Submesh, so the count
        # is asserted instead of only "appears somewhere".
        expected_occurrences = {
            "games/base/sections.py": 3,      # VS + CS + import
            "games/efmi.py": 2,
            "games/identityv.py": 2,
            "games/snowbreak.py": 2,
            "games/srmi.py": 2,
            "games/yysls.py": 2,
            "games/zzmi.py": 2,
            "games/zzmidx12.py": 2,
            "games/gf2/exporter.py": 2,
            "games/gimi/exporter.py": 2,
            "games/naraka/exporter.py": 2,
            "games/pgr/exporter.py": 2,
            "games/ntemi/sections.py": 2,
        }
        for relative_path, occurrences in expected_occurrences.items():
            text = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertEqual(
                text.count("is_submesh_skipped"), occurrences,
                relative_path + " lost a Skip Draw guard",
            )
        # WWMI reads the flag from its component draw calls instead.
        wwmi_text = (ROOT / "games/wwmi/exporter.py").read_text(encoding="utf-8")
        self.assertIn("component_skip_draw", wwmi_text)
        self.assertIn("drawindexed_str_list = []", wwmi_text)


class SkipDrawNodeTests(unittest.TestCase):
    """The blueprint UI stores the flag and the parser forwards it."""

    def setUp(self):
        self.tree = bpy.data.node_groups.new("skip_draw_test", "MIMIBlueprintTreeType")

    def tearDown(self):
        # Remove only the factory-process test data, never user files.
        for node_tree in list(bpy.data.node_groups):
            if node_tree.bl_idname == "MIMIBlueprintTreeType":
                bpy.data.node_groups.remove(node_tree)
        for mesh in list(bpy.data.meshes):
            if mesh.name.startswith("skip_draw_"):
                bpy.data.meshes.remove(mesh)
        for obj in list(bpy.data.objects):
            if obj.name.startswith("skip_draw_"):
                bpy.data.objects.remove(obj, do_unlink=True)

    def test_object_info_node_has_the_flag(self):
        node = self.tree.nodes.new("MIMINode_Object_Info")
        self.assertIn("skip_draw", node.bl_rna.properties)
        self.assertFalse(node.skip_draw)
        node.skip_draw = True
        self.assertTrue(node.skip_draw)

    def test_object_list_item_has_the_flag(self):
        node = self.tree.nodes.new("MIMINode_Object_List")
        item = node.object_items.add()
        self.assertFalse(item.skip_draw)
        item.skip_draw = True
        self.assertTrue(item.skip_draw)

    def test_object_info_flag_reaches_the_parser(self):
        # Real mesh and real blueprint, so the Object Info branch is exercised
        # end to end instead of only the property definition.
        mesh = bpy.data.meshes.new("skip_draw_mesh")
        mesh.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [], [(0, 1, 2, 3)])
        mesh.update()
        obj = bpy.data.objects.new("skip_draw_object", mesh)
        bpy.context.scene.collection.objects.link(obj)

        object_node = self.tree.nodes.new("MIMINode_Object_Info")
        object_node.object_name = obj.name
        object_node.submesh_name = HIDDEN_SUBMESH
        object_node.skip_draw = True
        output_node = self.tree.nodes.new("MIMINode_Result_Output")
        self.tree.links.new(object_node.outputs[0], output_node.inputs[0])

        from MIMIBlender.model.blueprint_model import BluePrintModel
        blueprint_model = BluePrintModel(tree=self.tree)
        self.assertEqual(len(blueprint_model.ordered_draw_obj_data_model_list), 1)
        self.assertTrue(blueprint_model.ordered_draw_obj_data_model_list[0].skip_draw)


if __name__ == "__main__":
    try:
        suite = unittest.TestSuite()
        for case in (SkipDrawStateTests, SkipDrawValidationTests, SkipDrawSectionTests, SkipDrawNodeTests):
            suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(case))
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    finally:
        addon.unregister()
    if not result.wasSuccessful():
        sys.exit(1)
