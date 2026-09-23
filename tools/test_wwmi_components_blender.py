"""WWMI component section tests.

Two behaviours are covered here:

1. An unassigned Submesh keeps its own section. The blueprint may assign
   objects to only some Submeshes of a DrawIB, and every Submesh still needs
   its [TextureOverrideComponentN] section with its own match / vertex group
   metadata so the component numbering cannot drift. The unassigned Submesh
   merely gets no draw and takes no part in the skeleton merge.
2. Every symbol that describes a draw range carries the DrawIB suffix, because
   all INI files of a mod share one 3Dmigoto namespace and a repeated section
   name or global variable is only read once (first file parsed wins).

Run with blender -b --factory-startup --python-exit-code 1 --python this_file.
"""
import importlib
import re
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
addon = importlib.import_module(ROOT.name)
addon.register()

from MIMIBlender.common.m_ini_builder import M_IniBuilder
from MIMIBlender.games.wwmi import blend_remap, exporter as wwmi_exporter, shapekeys
from MIMIBlender.games.wwmi.names import WWMI_REQUIRED_RUNTIME_VERSION, scoped_name
from MIMIBlender.model.draw_call_model import DrawCallModel
from MIMIBlender.workspace.wwmi_info import WWMIInfoComponent

DRAW_IB = '94517393'


def make_component(index_offset, index_count, vg_offset, vg_count):
    """One component entry exactly as WWMIInfoHelper builds it."""
    return WWMIInfoComponent(
        vertex_offset=0,
        vertex_count=1,
        index_offset=index_offset,
        index_count=index_count,
        vg_offset=vg_offset,
        vg_count=vg_count,
        vg_map={},
    )


def make_draw_call(obj_name, index_count, index_offset, vertex_count):
    """A resolved DrawCallModel that produces one drawindexed line."""
    draw_call = DrawCallModel(obj_name=obj_name, submesh_name='LOD0.94517393-0')
    draw_call.index_count = index_count
    draw_call.index_offset = index_offset
    draw_call.vertex_count = vertex_count
    return draw_call


def make_model(with_key=False, draw_ib=DRAW_IB):
    """DrawIB stand-in: component 1 has no object in the blueprint."""
    components = [
        make_component(index_offset=0, index_count=111, vg_offset=0, vg_count=11),
        make_component(index_offset=111, index_count=222, vg_offset=11, vg_count=22),
        make_component(index_offset=333, index_count=444, vg_offset=33, vg_count=44),
    ]
    keyname_mkey_dict = {'$swapkey0': object()} if with_key else {}
    return SimpleNamespace(
        draw_ib=draw_ib,
        wwmi_info=SimpleNamespace(
            vb0_hash='82aa82e1',
            cb4_hash='cafebabe',
            components=components,
            index_count=777,
            shapekeys=SimpleNamespace(
                offsets_hash='', scale_hash='', batches=[], checksum=0,
                dispatch_y=0, vertex_count=0,
            ),
        ),
        mesh_vertex_count=30,
        obj_buffer_model_wwmi=SimpleNamespace(
            shapekey_vertex_ids=[],
            shapekey_offsets=[],
            shapekey_position_buffer_dict={},
            shapekey_vector_buffer_dict={},
            export_shapekey=False,
        ),
        submesh_drawcall_groups=[
            [make_draw_call('mesh_a', 111, 0, 10)],
            [],
            [make_draw_call('mesh_c', 444, 333, 30)],
        ],
        # Only components with objects can appear in the name keyed map, which
        # is exactly why the index keyed map has to exist.
        blend_remap_used={'TEMP_mesh_a': False, 'TEMP_mesh_c': True},
        blend_remap_used_by_index={0: False, 2: True},
        blend_remap=True,
        component_real_vg_count_dict={0: 5, 2: 7},
        d3d11_game_type=SimpleNamespace(
            get_blendindices_count_wwmi=lambda: 4,
            CategoryStrideDict={"Position": 12, "Vector": 4, "Texcoord": 4, "Blend": 4},
        ),
        blueprint_model=SimpleNamespace(keyname_mkey_dict=keyname_mkey_dict),
    )


def make_exporter(model):
    """Exporter instance wired without touching a workspace."""
    exporter = wwmi_exporter.Exporter.__new__(wwmi_exporter.Exporter)
    exporter.blueprint_model = model.blueprint_model
    exporter.drawib_drawibmodel_dict = {model.draw_ib: model}
    exporter.mod_info_sections_written = False
    exporter.hash_sections_written = False
    return exporter


def render_component_sections(model, vgmap_mode):
    """Run the real exporter method and return its INI lines."""
    exporter = make_exporter(model)
    ini_builder = M_IniBuilder()
    with patch.object(wwmi_exporter.MIMIGlobalProperties, 'import_merged_vgmap', return_value=vgmap_mode):
        exporter.add_texture_override_component(ini_builder=ini_builder, draw_ib_model=model)
    return [line for section in ini_builder.ini_section_list for line in section.SectionLineList]


def render_lines(builder):
    """Flatten a builder into plain INI lines for text assertions."""
    return [line for section in builder.ini_section_list for line in section.SectionLineList]


def split_sections(lines):
    """Group INI lines per [TextureOverrideComponent...] section."""
    sections = {}
    current_name = None
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('[TextureOverrideComponent'):
            current_name = stripped
            sections[current_name] = []
            continue
        if current_name is not None:
            sections[current_name].append(stripped)
    return sections


class WWMIComponentTests(unittest.TestCase):
    def test_every_submesh_keeps_its_section(self):
        # The unassigned Submesh in the middle must not shift the components
        # that follow it, so each section carries its own metadata.
        lines = render_component_sections(make_model(), 'MERGED')
        sections = split_sections(lines)

        self.assertEqual(
            sorted(sections.keys()),
            sorted([
                '[' + scoped_name('TextureOverrideComponent0', DRAW_IB) + ']',
                '[' + scoped_name('TextureOverrideComponent1', DRAW_IB) + ']',
                '[' + scoped_name('TextureOverrideComponent2', DRAW_IB) + ']',
            ]),
        )
        first = sections['[' + scoped_name('TextureOverrideComponent0', DRAW_IB) + ']']
        self.assertIn('match_first_index = 0', first)
        self.assertIn('match_index_count = 111', first)
        self.assertIn('$object_detected = 1', first)

        # The empty component keeps its own match range but must not take part
        # in the skeleton merge: its component level VG range does not describe
        # the merged vertex group layout.
        empty_section = sections['[' + scoped_name('TextureOverrideComponent1', DRAW_IB) + ']']
        self.assertIn('match_first_index = 111', empty_section)
        self.assertIn('match_index_count = 222', empty_section)
        self.assertIn('$object_detected = 1', empty_section)
        self.assertFalse(any(line.startswith('$\\WWMIv1\\vg_offset') for line in empty_section), empty_section)
        self.assertFalse(any(line.startswith('$\\WWMIv1\\vg_count') for line in empty_section), empty_section)
        self.assertFalse(any('MergeSkeleton' in line for line in empty_section), empty_section)
        self.assertFalse(any(line.startswith('run = ') for line in empty_section), empty_section)

        # The following component is not shifted onto the empty one's data and
        # still merges for its own vertex group range.
        third_section = sections['[' + scoped_name('TextureOverrideComponent2', DRAW_IB) + ']']
        self.assertIn('match_first_index = 333', third_section)
        self.assertIn('match_index_count = 444', third_section)
        self.assertIn('$\\WWMIv1\\vg_offset = 33', third_section)
        self.assertIn('$\\WWMIv1\\vg_count = 44', third_section)
        self.assertIn('run = ' + scoped_name('CommandListMergeSkeleton', DRAW_IB), third_section)

        # Draws only where the blueprint assigned objects; the unassigned
        # Submesh is skipped instead of drawn from the mod's buffer.
        self.assertTrue(any(line.startswith('drawindexed = 111,0,0') for line in first))
        self.assertTrue(any(line.startswith('drawindexed = 444,333,0') for line in third_section))
        self.assertFalse(any('drawindexed' in line for line in empty_section))
        self.assertIn('handling = skip', empty_section)
        self.assertIn('; Draw skipped: No matching custom components found', empty_section)

        # No empty if-block is left behind anywhere.
        for name, section in sections.items():
            for index, line in enumerate(section):
                if line.startswith('if ') and index + 1 < len(section):
                    self.assertFalse(section[index + 1].startswith('endif'), name)

    def test_per_component_mode_uses_the_same_numbering(self):
        # The non merged vgmap mode shares the component enumeration.
        sections = split_sections(render_component_sections(make_model(), 'PER_COMPONENT'))
        self.assertEqual(len(sections), 3)
        empty = sections['[' + scoped_name('TextureOverrideComponent1', DRAW_IB) + ']']
        self.assertIn('handling = skip', empty)
        self.assertFalse(any('drawindexed' in line for line in empty))
        third = sections['[' + scoped_name('TextureOverrideComponent2', DRAW_IB) + ']']
        self.assertTrue(any('drawindexed = 444,333,0' in line for line in third))
        # Without the merged skeleton workflow no merge is requested at all.
        self.assertFalse(any('MergeSkeleton' in line for line in third))

    def test_active_flag_and_blend_remap_reference_real_index(self):
        sections = split_sections(render_component_sections(make_model(with_key=True), 'MERGED'))
        # The mod-active flag is written for every component, assigned or not.
        for section in sections.values():
            self.assertTrue(any(line.startswith('$active') for line in section), section)

        # A remapped component is referenced by its real index, so the
        # reference matches the resource that blend_remap declares.
        third_section = sections['[' + scoped_name('TextureOverrideComponent2', DRAW_IB) + ']']
        self.assertIn(
            scoped_name('ResourceBlendBufferOverride', DRAW_IB)
            + ' = ref ' + scoped_name('ResourceRemappedBlendBufferComponent2', DRAW_IB),
            third_section,
        )
        self.assertIn(
            scoped_name('ResourceMergedSkeletonOverride', DRAW_IB)
            + ' = ref ' + scoped_name('ResourceRemappedSkeletonComponent2', DRAW_IB),
            third_section,
        )
        # The empty component is not remapped and must not reference anything.
        empty_section = sections['[' + scoped_name('TextureOverrideComponent1', DRAW_IB) + ']']
        self.assertFalse(any('Remapped' in line for line in empty_section))

    def test_blend_remap_resources_follow_real_index(self):
        model = make_model()
        ini_builder = M_IniBuilder()
        with patch.object(blend_remap.MIMIGlobalProperties, 'import_merged_vgmap', return_value='MERGED'):
            blend_remap.add_blend_remap_sections(ini_builder=ini_builder, draw_ib_model=model)
        text = '\n'.join(render_lines(ini_builder))

        self.assertIn('[' + scoped_name('ResourceRemappedBlendBufferComponent2', DRAW_IB) + ']', text)
        self.assertIn('[' + scoped_name('ResourceRemappedSkeletonComponent2', DRAW_IB) + ']', text)
        self.assertNotIn('[' + scoped_name('ResourceRemappedBlendBufferComponent0', DRAW_IB) + ']', text)
        self.assertNotIn('[' + scoped_name('ResourceRemappedBlendBufferComponent1', DRAW_IB) + ']', text)
        # vg_count is looked up by the real index (7), not by a compacted one.
        self.assertIn('$\\WWMIv1\\vg_count = 7', text)
        # blend_remap_id stays compact: the remap buffers are packed in order.
        self.assertIn('$\\WWMIv1\\blend_remap_id = 0', text)
        self.assertNotIn('$\\WWMIv1\\blend_remap_id = 2', text)


class WWMISkeletonMergeGuardTests(unittest.TestCase):
    """The merge shader copies whatever is in cs-cb8 without validating it."""

    def merge_lines(self):
        model = make_model()
        ini_builder = M_IniBuilder()
        with patch.object(blend_remap.MIMIGlobalProperties, 'import_merged_vgmap', return_value='MERGED'):
            blend_remap.add_commandlist_merge_skeleton_section(ini_builder=ini_builder, draw_ib_model=model)
        return [line.strip() for line in render_lines(ini_builder)]

    def test_both_merges_are_guarded_by_the_bone_data_marker(self):
        lines = self.merge_lines()
        text = '\n'.join(lines)

        self.assertIn('[' + scoped_name('CommandListMergeSkeleton', DRAW_IB) + ']', lines)
        # Regular skeleton: only merge while vs-cb4 still carries bone data.
        self.assertIn('if vs-cb4 == ' + blend_remap.BONE_DATA_FILTER_INDEX, lines)
        # Extra skeleton: only merge while BOTH slots carry bone data.
        self.assertIn(
            'if vs-cb4 == ' + blend_remap.BONE_DATA_FILTER_INDEX
            + ' && vs-cb3 == ' + blend_remap.BONE_DATA_FILTER_INDEX,
            lines,
        )
        # Every dispatch sits inside one of the two guarded blocks.
        guard_depth = 0
        seen_dispatches = 0
        for line in lines:
            if line.startswith('if '):
                guard_depth += 1
            elif line == 'endif':
                guard_depth -= 1
            elif line.startswith('run = CustomShader\\WWMIv1\\SkeletonMerger'):
                self.assertGreaterEqual(guard_depth, 2, "SkeletonMerger must run inside both guards")
                seen_dispatches += 1
        self.assertEqual(seen_dispatches, 2, "one merge for the regular and one for the extra skeleton")
        self.assertEqual(guard_depth, 0, text)

    def test_merge_status_tracks_regular_then_extra(self):
        text = '\n'.join(self.merge_lines())
        status = '$' + scoped_name('merge_status_id', DRAW_IB)

        # Step 1 runs only while nothing was merged yet and records status 1.
        self.assertIn('if ' + status + ' == 0', text)
        self.assertIn(status + ' = 1', text)
        # Step 2 runs only after the regular skeleton was merged and records 2.
        self.assertIn('if ' + status + ' == 1', text)
        self.assertIn(status + ' = 2', text)

    def test_update_commandlist_resets_every_component_status(self):
        model = make_model()
        ini_builder = M_IniBuilder()
        with patch.object(blend_remap.MIMIGlobalProperties, 'import_merged_vgmap', return_value='MERGED'):
            blend_remap.add_commandlist_update_merged_skeleton(ini_builder=ini_builder, draw_ib_model=model)
        lines = [line.strip() for line in render_lines(ini_builder)]

        self.assertIn('[' + scoped_name('CommandListUpdateMergedSkeleton', DRAW_IB) + ']', lines)
        for component_index in range(len(model.wwmi_info.components)):
            self.assertIn(
                '$' + scoped_name('merge_status_id_' + str(component_index), DRAW_IB) + ' = 0',
                lines,
            )


class WWMINamingTests(unittest.TestCase):
    """Every draw range symbol must be unique per DrawIB."""

    def render_full_ini(self, model, vgmap_mode='MERGED'):
        """Render every section the WWMI exporter writes for one DrawIB."""
        exporter = make_exporter(model)
        ini_builder = M_IniBuilder()
        with patch.object(wwmi_exporter.MIMIGlobalProperties, 'import_merged_vgmap', return_value=vgmap_mode):
            with patch.object(blend_remap.MIMIGlobalProperties, 'import_merged_vgmap', return_value=vgmap_mode):
                with patch.object(shapekeys.MIMIGlobalProperties, 'import_merged_vgmap', return_value=vgmap_mode):
                    exporter.add_constants_section(ini_builder=ini_builder, draw_ib_model=model)
                    exporter.add_present_section(ini_builder=ini_builder, draw_ib_model=model)
                    exporter.add_commandlist_register_mod_section(ini_builder=ini_builder, draw_ib_model=model)
                    blend_remap.add_commandlist_update_merged_skeleton(ini_builder=ini_builder, draw_ib_model=model)
                    blend_remap.add_blend_remap_sections(ini_builder=ini_builder, draw_ib_model=model)
                    exporter.add_resource_mod_info_section_default(ini_builder=ini_builder, draw_ib_model=model)
                    exporter.add_texture_override_mark_bone_data_cb(ini_builder=ini_builder, draw_ib_model=model)
                    blend_remap.add_commandlist_merge_skeleton_section(ini_builder=ini_builder, draw_ib_model=model)
                    exporter.add_commandlist_trigger_shared_cleanup_section(ini_builder=ini_builder, draw_ib_model=model)
                    exporter.add_texture_override_component(ini_builder=ini_builder, draw_ib_model=model)
                    shapekeys.add_texture_override_shapekeys(ini_builder=ini_builder, draw_ib_model=model)
                    shapekeys.add_resource_shapekeys(ini_builder=ini_builder, draw_ib_model=model)
                    blend_remap.add_resource_merged_skeleton(ini_builder=ini_builder, draw_ib_model=model)
                    exporter.add_resource_buffer(ini_builder=ini_builder, draw_ib_model=model)
        return [line.strip() for line in render_lines(ini_builder)]

    def test_required_runtime_version_is_the_tested_one(self):
        lines = self.render_full_ini(make_model())
        self.assertIn(
            'global $required_wwmi_version = ' + WWMI_REQUIRED_RUNTIME_VERSION,
            lines,
        )

    def test_draw_range_symbols_carry_the_draw_ib(self):
        lines = self.render_full_ini(make_model())
        text = '\n'.join(lines)

        # Buffers, command lists and section headers of one draw range.
        for bare_name in (
            'ResourceIndexBuffer',
            'ResourcePositionBuffer',
            'ResourceMergedSkeleton',
            'CommandListMergeSkeleton',
            'CommandListOverrideSharedResources',
            'TextureOverrideComponent0',
            'TextureOverrideMarkBoneDataCB',
        ):
            self.assertIn('[' + scoped_name(bare_name, DRAW_IB) + ']', lines, bare_name)
            self.assertNotIn('[' + bare_name + ']', lines, bare_name + " must not be emitted unscoped")

        # Globals that describe the geometry of the draw range.
        for bare_variable in (
            'mesh_vertex_count',
            'object_guid',
            'shapekey_vertex_count',
            'merge_status_id',
        ):
            self.assertIn('$' + scoped_name(bare_variable, DRAW_IB), text, bare_variable)

    def test_mod_level_symbols_stay_global(self):
        lines = self.render_full_ini(make_model())
        text = '\n'.join(lines)

        # Registration is a property of the whole mod, not of one draw range.
        # "global persist $x = 0" has to be handled as well, so the head is
        # taken from the last whitespace separated word before the "=".
        global_heads = []
        for line in lines:
            if not line.startswith('global '):
                continue
            head = line.split('=', 1)[0].strip().split()[-1]
            global_heads.append(head)
        for global_name in ('$mod_id', '$mod_enabled', '$object_detected', '$required_wwmi_version'):
            self.assertIn(global_name, global_heads, global_name)
            self.assertNotIn(global_name + '_' + DRAW_IB, global_heads, global_name + " must stay global")

    def test_runtime_namespace_is_never_renamed(self):
        lines = self.render_full_ini(make_model())
        # The WWMI runtime looks its own variables and resources up by exact
        # name, so a suffix there would silently break the mod.
        runtime_variables = sorted({line.split('=')[0].strip() for line in lines if line.startswith('$\\WWMIv1\\')})
        self.assertTrue(runtime_variables, "the export must talk to the runtime namespace")
        for variable in runtime_variables:
            self.assertNotIn('_' + DRAW_IB, variable, variable)

        for line in lines:
            if 'Resource\\WWMIv1\\' in line:
                self.assertNotIn('_' + DRAW_IB, line, line)

    def test_two_draw_ibs_do_not_share_any_symbol(self):
        """The real bug this guards: the second DrawIB inheriting the first one's
        vertex count, buffers and skeleton, because 3Dmigoto only reads the first
        declaration of a global and the first definition of a section."""
        first = self.render_full_ini(make_model(draw_ib='11111111'))
        second = self.render_full_ini(make_model(draw_ib='22222222'))

        def symbols(lines):
            """Collect only the symbol names, never the values.

            ``local`` variables live inside one command list and cannot leak
            into another INI, so they are not part of the namespace contract.
            """
            found = set()
            for line in lines:
                text = line.strip()
                if text.startswith('[') and text.endswith(']'):
                    found.add(text)
                elif text.startswith('local '):
                    continue
                elif text.startswith('global ') or text.startswith('$'):
                    head = text.split('=', 1)[0].strip()
                    if head.startswith('$'):
                        found.add(head)
            return found

        first_symbols = symbols(first)
        second_symbols = symbols(second)
        self.assertTrue(first_symbols and second_symbols, "the export must emit symbols")
        # Structural sanity: the two exports really do describe different
        # DrawIBs, so the comparison below is meaningful.
        self.assertIn('[' + scoped_name('TextureOverrideComponent0', '11111111') + ']', first_symbols)
        self.assertIn('[' + scoped_name('TextureOverrideComponent0', '22222222') + ']', second_symbols)

        # These symbols describe the whole mod rather than one draw range, so
        # they are intentionally identical in every INI of the mod. Each of them
        # is written by exactly one file, and the ones that do repeat always
        # describe the same single thing (the mod metadata, one mod id, one
        # "object is on screen" flag), so no DrawIB can read another DrawIB's
        # geometry through them.
        mod_level_sections = {
            '[ResourceModName]',
            '[ResourceModAuthor]',
            '[ResourceModDesc]',
            '[ResourceModLink]',
            '[ResourceModLogo]',
        }
        mod_level_variables = {'$mod_id', '$mod_enabled', '$object_detected'}
        # Declared as "local" but written on its own line, so the symbol scan
        # sees it; it never leaves the command list it belongs to.
        command_list_locals = {'$blend_remaps_initialized'}
        shared = sorted(
            name for name in first_symbols & second_symbols
            if 'WWMIv1' not in name
            and name not in mod_level_sections
            and name not in mod_level_variables
            and name not in command_list_locals
        )
        self.assertEqual(
            shared, [],
            "these symbols would collide in 3Dmigoto and the first parsed INI would win: " + str(shared),
        )


class WWMIHotkeyVisibilityTests(unittest.TestCase):
    """Hotkeys must work whichever draw range of the mod is on screen.

    The [Key] sections used to be gated on $active0, the flag of the first
    exported DrawIB. A mod whose first DrawIB was not the visible one therefore
    had completely dead hotkeys, because $mod_visible was never set by the
    other draw ranges either.
    """

    def render_key_lines(self, draw_ib):
        """Run the real key section writer for one export position."""
        from MIMIBlender.common.global_config import GlobalConfig
        from MIMIBlender.common.m_ini_helper import M_IniHelper
        from MIMIBlender.common.m_key import M_Key

        mkey = M_Key(
            key_name='$swapkey0',
            key_value='VK_F5',
            value_list=[0, 1],
            initialize_vk_str='VK_F5',
        )
        ini_builder = M_IniBuilder()
        previous_number = GlobalConfig.generated_mod_number
        try:
            # Emulate the state right after the first draw range was counted.
            GlobalConfig.generated_mod_number = 1
            M_IniHelper.add_branch_key_sections(
                ini_builder=ini_builder,
                key_name_mkey_dict={'$swapkey0': mkey},
            )
        finally:
            GlobalConfig.generated_mod_number = previous_number
        return [line.strip() for line in render_lines(ini_builder)]

    def test_hotkey_condition_uses_the_mod_visibility_flag(self):
        lines = self.render_key_lines(DRAW_IB)
        self.assertIn('condition = $mod_visible == 1', lines)
        self.assertNotIn('condition = $active0 == 1', lines)

    def test_visibility_flag_is_declared_and_cleared_every_frame(self):
        lines = self.render_key_lines(DRAW_IB)
        self.assertIn('global $mod_visible = 0', lines)
        self.assertIn('post $mod_visible = 0', lines)
        # The per range flags stay, they are still the source of the reset.
        self.assertIn('global $active0', lines)
        self.assertIn('post $active0 = 0', lines)

    def test_every_preset_range_marks_the_mod_visible(self):
        """The flag is only useful when the range sections set it."""
        import re
        preset_files = (
            'games/base/sections.py',
            'games/yysls.py',
            'games/zzmi.py',
            'games/zzmidx12.py',
            'games/efmi.py',
            'games/identityv.py',
            'games/srmi.py',
            'games/naraka/exporter.py',
            'games/ntemi/sections.py',
            'games/wwmi/exporter.py',
        )
        for relative_path in preset_files:
            text = (ROOT / relative_path).read_text(encoding='utf-8')
            active_count = len(re.findall(r'\$active(?:\" \+ str\(|\{)', text))
            visible_count = text.count('$mod_visible = 1')
            self.assertEqual(
                active_count, visible_count,
                relative_path + ": every range activation must also set $mod_visible ("
                + str(active_count) + " active vs " + str(visible_count) + " visible)",
            )


if __name__ == '__main__':
    try:
        suite = unittest.TestSuite()
        suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(WWMIComponentTests))
        suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(WWMISkeletonMergeGuardTests))
        suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(WWMINamingTests))
        suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(WWMIHotkeyVisibilityTests))
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    finally:
        addon.unregister()
    if not result.wasSuccessful():
        raise AssertionError('WWMI component tests failed')
