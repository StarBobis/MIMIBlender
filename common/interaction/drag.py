"""Export the reference mouse picker and spring controller for Naraka.

The retained template contains the full reference state and binding guards.
Only authored geometry, shader identities and controller settings are replaced.
No reference mesh buffers or texture replacements are distributed.
"""

from pathlib import Path
import hashlib
import re

import numpy as np

from ..m_ini_builder import M_IniSection, M_SectionType


def marker(stage, shader):
    """Keep marker values exactly representable in the INI float channel."""
    return int(hashlib.sha256((stage + shader).encode()).hexdigest()[:6], 16) or 1


def prepare(data, model, node):
    """Validate the picker inputs before the exporter writes any files.

    Shader hashes are explicit evidence from a capture. Reusing the sample
    character's hashes on another model would silently produce no interaction.
    Multiple ranges retain their original visibility conditions in the IB hook.
    """
    vs, ps = node.pick_vs.strip().lower(), node.pick_ps.strip().lower()
    if not re.fullmatch('[0-9a-f]{16}', vs) or not re.fullmatch('[0-9a-f]{16}', ps):
        raise ValueError('Mouse drag: choose the main-pass VS and PS hashes from a FrameAnalysis capture in the interaction node')
    if getattr(node, 'capture_directory', ''):
        from .capture import validate_texture_slots
        validate_texture_slots(node.capture_directory, model.draw_ib, vs, ps,
                               [mark for submesh in model.submesh_model_list
                                for mark in model.get_submesh_texture_markup_info_list(submesh)])
    if data['position_stride'] != 40:
        raise ValueError('Mouse drag currently requires the reference 40-byte Position layout')
    if any(c.cross_render_at_submesh for s in model.submesh_model_list for c in s.drawcall_model_list):
        raise ValueError('Mouse drag: cross-IB regions require a receiver-specific picker; export this interaction separately')
    distances = [v for v in data['region_safe_distance_list'] if v > 0]
    if not distances:
        raise ValueError('Mouse drag: paint control weights with a smooth falloff first')
    # Both displacement fields contribute to the same Jacobian. Share the
    # bound across the two springs so simultaneous motion stays within it.
    bound = sum(data['region_gradient_bound_list'])
    distance = min(min(distances), 0.45 / max(bound, 1e-12)) * node.drag_strength
    data['drag'] = dict(vs=vs, ps=ps, distance=distance,
                        frequency=node.spring_frequency, damping=node.damping_ratio,
                        sensitivity=node.drag_sensitivity, flip_y=node.flip_y,
                        reversed_z=node.reversed_z, ranges={})
    # A grab starts at the rest pose; the old fixed offset has no meaning.
    data['state_record'][:] = 0
    data['drag_positions'] = np.concatenate([
        np.asarray(s.category_buffer_dict['Position'], dtype=np.uint8).reshape(-1)
        for s in model.submesh_model_list])
    from ..m_ini_helper import M_IniHelper
    for submesh in model.submesh_model_list:
        for line in M_IniHelper.get_drawindexed_str_list(
                submesh.drawcall_model_list, obj_name_draw_offset_dict=model.obj_name_draw_offset):
            hook(data, model, submesh, line)
    if not data['drag']['ranges']:
        raise ValueError('Mouse drag: no visible triangle draw ranges were found')
    data['drag_indices'] = model.submesh_ib_dict


def hook(data, model, submesh, line):
    """Return the exact-range picker call, to place after the visible draw.

    Called while the same IB and vertex resources are still bound. Keeping
    it inside the existing condition prevents hidden costume ranges picking.
    Instanced draws need a separate derivative recipe and are rejected.
    """
    if 'drag' not in data or not line.strip().startswith('drawindexed'):
        return None
    match = re.fullmatch(r'\s*drawindexed\s*=\s*(\d+)\s*,\s*(\d+)\s*,\s*(-?\d+)\s*', line)
    if match is None:
        raise ValueError('Mouse drag does not support instanced draw ranges')
    count, first, base = map(int, match.groups())
    slug = hashlib.sha256((submesh.submesh_name + line.strip()).encode()).hexdigest()[:12]
    data['drag']['ranges'][slug] = (count, first, base, submesh)
    return 'run = CommandListMimiDragPick_' + model.draw_ib + '_Draw_' + slug


def sections(builder, data, model):
    """Instantiate shared state once and the full picker for every draw range."""
    settings = data['drag']
    root = Path(__file__).resolve().parents[2] / 'resources/interaction/drag'
    template = (root / 'runtime.ini').read_text(encoding='utf-8')
    chunks = re.findall(r'(?ms)^\[([^\]]+)\]\n(.*?)(?=^\[|\Z)', template)
    values = {'DRAW': model.draw_ib, 'VS': settings['vs'], 'PS': settings['ps'],
              'VSMARK': marker('vs', settings['vs']), 'PSMARK': marker('ps', settings['ps']),
              'VERTICES': data['vertex_count'], 'BYTES': data['vertex_count'] * 40,
              'GROUPS': (data['vertex_count'] + 63) // 64,
              'DISTANCE': settings['distance'], 'FREQUENCY': settings['frequency'],
              'DAMPING': settings['damping'], 'SENSITIVITY': settings['sensitivity']}
    for name, body in chunks:
        if name == 'ResourceMimiNarakaDragIndices_@DRAW@':
            continue
        if '@RANGE@' in name:
            entries = settings['ranges'].items()
        else:
            entries = [(None, None)]
        for slug, entry in entries:
            local = dict(values)
            if entry:
                count, first, base, submesh = entry
                local.update(RANGE=slug, COUNT=count, FIRST=first, BASE=base)
            content = '[' + name + ']\n' + body
            if name.startswith('ShaderOverride'):
                content = content.replace(']\n', '_' + model.draw_ib + ']\n', 1)
            # Index buffers belong to their live submesh, rather than the
            # concatenated triangle list used to calculate weight gradients.
            if slug:
                content = content.replace('ResourceMimiNarakaDragIndices_@DRAW@',
                                          'ResourceMimiDragIndices_@DRAW@_' + slug)
            for key, value in local.items():
                content = content.replace('@' + key + '@', str(value))
            content = content.replace('z246 = 1', 'z246 = ' + str(int(settings['flip_y'])))
            if not settings['reversed_z']:
                content = content.replace('depth_func = greater_equal', 'depth_func = less_equal')
                content = content.replace('_Depth depth 0', '_Depth depth 1')
            # Each DrawIB gets its own shader names so depth conventions can
            # differ without another export overwriting a shared shader file.
            content = content.replace('Interaction/drag/', 'Interaction/drag/' + model.draw_ib + '-')
            kind = name if name in ('Constants', 'Present') else M_SectionType.CommandList
            section = M_IniSection(kind)
            for line in content.splitlines():
                section.append(line)
            builder.append_section(section)
            if slug and name.startswith('ResourceMimiDragPick'):
                resource = M_IniSection(M_SectionType.ResourceBuffer)
                for line in ('[ResourceMimiDragIndices_' + model.draw_ib + '_' + slug + ']',
                             'type = ByteAddressBuffer', 'misc_flags = buffer_allow_raw_views',
                             'bind_flags = shader_resource', 'stride = 4',
                             'filename = Interaction/' + model.draw_ib + '-' + slug + '-Indices.buf'):
                    resource.append(line)
                builder.append_section(resource)


def write(folder, data, drawib):
    """Write generated buffers and reference shaders with no source writes."""
    folder = Path(folder) / 'Interaction'
    folder.mkdir(parents=True, exist_ok=True)
    source = Path(__file__).resolve().parents[2] / 'resources/interaction/drag'
    shaders = folder / 'drag'
    shaders.mkdir(exist_ok=True)
    for path in source.glob('*.hlsl'):
        text = path.read_text(encoding='utf-8')
        if path.name == 'pick_ps.hlsl':
            text = text.replace('#define MIMI_DRAG_REVERSED_Z 1', '#define MIMI_DRAG_REVERSED_Z ' + str(int(data['drag']['reversed_z'])))
        (shaders / (drawib + '-' + path.name)).write_text(text, encoding='utf-8')
    data['drag_positions'].tofile(folder / (drawib + '-Rest.buf'))
    data['control_record'].astype('<f4').tofile(folder / (drawib + '-Deformation.buf'))
    data['control_record'][:, :2].copy().astype('<f4').tofile(folder / (drawib + '-Weights.buf'))
    data['state_record'].astype('<f4').tofile(folder / (drawib + '-State.buf'))
    for slug, (_, _, _, submesh) in data['drag']['ranges'].items():
        np.asarray(data['drag_indices'][submesh.submesh_name], dtype='<u4').tofile(folder / (drawib + '-' + slug + '-Indices.buf'))
