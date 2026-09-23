"""WWMI component section tests: unassigned Submeshes keep their section.

Run with blender -b --factory-startup --python-exit-code 1 --python this_file.

The blueprint may assign objects to only some Submeshes of a DrawIB. Every
Submesh still needs its [TextureOverrideComponentN] section with its own
match / vertex group metadata, so the component numbering cannot drift; the
unassigned Submesh merely gets no drawindexed line.
"""
import importlib
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
from MIMIBlender.games.wwmi import blend_remap, exporter as wwmi_exporter
from MIMIBlender.model.draw_call_model import DrawCallModel
from MIMIBlender.workspace.wwmi_info import WWMIInfoComponent


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


def make_model(with_key=False):
    """DrawIB stand-in: component 1 has no object in the blueprint."""
    components = [
        make_component(index_offset=0, index_count=111, vg_offset=0, vg_count=11),
        make_component(index_offset=111, index_count=222, vg_offset=11, vg_count=22),
        make_component(index_offset=333, index_count=444, vg_offset=33, vg_count=44),
    ]
    keyname_mkey_dict = {'$swapkey0': object()} if with_key else {}
    return SimpleNamespace(
        wwmi_info=SimpleNamespace(vb0_hash='82aa82e1', components=components),
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
        d3d11_game_type=SimpleNamespace(get_blendindices_count_wwmi=lambda: 4),
        blueprint_model=SimpleNamespace(keyname_mkey_dict=keyname_mkey_dict),
    )


def render_component_sections(model, vgmap_mode):
    """Run the real exporter method and return its INI lines."""
    exporter = wwmi_exporter.Exporter.__new__(wwmi_exporter.Exporter)
    exporter.blueprint_model = model.blueprint_model
    ini_builder = M_IniBuilder()
    with patch.object(wwmi_exporter.MIMIGlobalProperties, 'import_merged_vgmap', return_value=vgmap_mode):
        exporter.add_texture_override_component(ini_builder=ini_builder, draw_ib_model=model)
    return [line for section in ini_builder.ini_section_list for line in section.SectionLineList]


def split_sections(lines):
    """Group INI lines per [TextureOverrideComponentN] section."""
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
            ['[TextureOverrideComponent0]', '[TextureOverrideComponent1]', '[TextureOverrideComponent2]'],
        )
        self.assertIn('match_first_index = 0', sections['[TextureOverrideComponent0]'])
        self.assertIn('match_index_count = 111', sections['[TextureOverrideComponent0]'])
        self.assertIn('$object_detected = 1', sections['[TextureOverrideComponent0]'])

        # The empty component keeps its own match range and vertex groups.
        empty_section = sections['[TextureOverrideComponent1]']
        self.assertIn('match_first_index = 111', empty_section)
        self.assertIn('match_index_count = 222', empty_section)
        self.assertIn('$object_detected = 1', empty_section)
        self.assertIn('$\\WWMIv1\\vg_offset = 11', empty_section)
        self.assertIn('$\\WWMIv1\\vg_count = 22', empty_section)

        # The following component is not shifted onto the empty one's data.
        third_section = sections['[TextureOverrideComponent2]']
        self.assertIn('match_first_index = 333', third_section)
        self.assertIn('match_index_count = 444', third_section)
        self.assertIn('$\\WWMIv1\\vg_offset = 33', third_section)
        self.assertIn('$\\WWMIv1\\vg_count = 44', third_section)

        # Draws only where the blueprint assigned objects; the unassigned
        # Submesh is skipped instead of drawn from the mod's buffer.
        self.assertTrue(any(line.startswith('drawindexed = 111,0,0') for line in sections['[TextureOverrideComponent0]']))
        self.assertTrue(any(line.startswith('drawindexed = 444,333,0') for line in sections['[TextureOverrideComponent2]']))
        self.assertFalse(any('drawindexed' in line for line in empty_section))
        self.assertIn('handling = skip', empty_section)
        self.assertIn('; Draw Component 1 (no object assigned to this Submesh)', empty_section)

        # No empty if-block is left behind anywhere.
        for name, section in sections.items():
            for index, line in enumerate(section):
                if line.startswith('if ') and index + 1 < len(section):
                    self.assertFalse(section[index + 1].startswith('endif'), name)

    def test_per_component_mode_uses_the_same_numbering(self):
        # The non merged vgmap mode shares the component enumeration.
        sections = split_sections(render_component_sections(make_model(), 'PER_COMPONENT'))
        self.assertEqual(len(sections), 3)
        self.assertIn('handling = skip', sections['[TextureOverrideComponent1]'])
        self.assertFalse(any('drawindexed' in line for line in sections['[TextureOverrideComponent1]']))
        self.assertTrue(any('drawindexed = 444,333,0' in line for line in sections['[TextureOverrideComponent2]']))

    def test_active_flag_and_blend_remap_reference_real_index(self):
        sections = split_sections(render_component_sections(make_model(with_key=True), 'MERGED'))
        # The mod-active flag is written for every component, assigned or not.
        for section in sections.values():
            self.assertTrue(any(line.startswith('$active') for line in section), section)

        # A remapped component is referenced by its real index, so the
        # reference matches the resource that blend_remap declares.
        third_section = sections['[TextureOverrideComponent2]']
        self.assertIn('ResourceBlendBufferOverride = ref ResourceRemappedBlendBufferComponent2', third_section)
        self.assertIn('ResourceMergedSkeletonOverride = ref ResourceRemappedSkeletonComponent2', third_section)
        # The empty component is not remapped and must not reference anything.
        self.assertFalse(any('Remapped' in line for line in sections['[TextureOverrideComponent1]']))

    def test_blend_remap_resources_follow_real_index(self):
        model = make_model()
        ini_builder = M_IniBuilder()
        with patch.object(blend_remap.MIMIGlobalProperties, 'import_merged_vgmap', return_value='MERGED'):
            blend_remap.add_blend_remap_sections(ini_builder=ini_builder, draw_ib_model=model)
        text = '\n'.join(line for section in ini_builder.ini_section_list for line in section.SectionLineList)

        self.assertIn('[ResourceRemappedBlendBufferComponent2]', text)
        self.assertIn('[ResourceRemappedSkeletonComponent2]', text)
        self.assertNotIn('Component0]', text)
        self.assertNotIn('Component1]', text)
        # vg_count is looked up by the real index (7), not by a compacted one.
        self.assertIn('$\\WWMIv1\\vg_count = 7', text)
        # blend_remap_id stays compact: the remap buffers are packed in order.
        self.assertIn('$\\WWMIv1\\blend_remap_id = 0', text)
        self.assertNotIn('$\\WWMIv1\\blend_remap_id = 2', text)


if __name__ == '__main__':
    try:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(WWMIComponentTests)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    finally:
        addon.unregister()
    if not result.wasSuccessful():
        raise AssertionError('WWMI component tests failed')
