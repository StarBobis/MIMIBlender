"""Check the exported picker contract independently of the Blender UI.

Run: python tools/test_interaction_drag.py
The test uses two distinct submesh ranges and checks that no sample-character
identities or unresolved placeholders can leak into the generated mod.
"""
import sys
from pathlib import Path
from types import SimpleNamespace
import tempfile
import re

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.interaction import drag
from common.m_ini_builder import M_IniBuilder
from common.interaction.capture import find_picker_shaders, validate_texture_slots
import struct


def main():
    """Verify the complete INI resource graph and generated buffer sizes."""
    submesh = SimpleNamespace(submesh_name='body')
    model = SimpleNamespace(draw_ib='12345678')
    data = {'vertex_count': 4, 'control_record': np.zeros((4, 8)),
            'state_record': np.zeros((9, 4)), 'drag_positions': np.zeros(160, dtype=np.uint8),
            'drag_indices': {'body': [0, 1, 2, 1, 2, 3]},
            'drag': dict(vs='1234567890abcdef', ps='fedcba0987654321', distance=.02,
                         frequency=3.5, damping=.24, sensitivity=2., flip_y=True,
                         reversed_z=True, ranges={'aaa': (3, 0, 0, submesh),
                                                  'bbb': (3, 3, 0, submesh)})}
    builder = M_IniBuilder()
    drag.sections(builder, data, model)
    text = '\n'.join('\n'.join(s.SectionLineList) for s in builder.ini_section_list)
    # Hiding diagnostics must change only the HUD condition. Picking,
    # spring integration and deformation must retain their original paths.
    assert '_input_valid == 1 && 0 == 1' in text
    data['drag']['show_debug'] = True
    debug_builder = M_IniBuilder()
    drag.sections(debug_builder,data,model)
    debug_text = '\n'.join('\n'.join(s.SectionLineList) for s in debug_builder.ini_section_list)
    assert debug_text == text.replace('_input_valid == 1 && 0 == 1','_input_valid == 1 && 1 == 1')
    headers = re.findall(r'^\[([^\]]+)\]', text, re.M)
    assert len(headers) == len(set(headers)), 'Duplicate section names'
    assert '@' not in text and 'd3b27608' not in text
    assert text.count('drawindexed = 3,0,0') == 32
    assert text.count('drawindexed = 3,3,0') == 32
    # Every resource/command target is defined locally; Position belongs
    # to the ordinary exporter and is the only intentional external target.
    definitions = {n.lower() for n in headers}
    references = re.findall(r'\b(?:Resource|CommandList|CustomShader)[\w-]+', text)
    missing = {r for r in references if r.lower() not in definitions and r != 'Resource12345678Position'}
    assert not missing, missing
    root = Path(__file__).resolve().parents[1] / 'tmp'
    root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root) as folder:
        drag.write(folder, data, model.draw_ib)
        base = Path(folder) / 'Interaction'
        assert (base / '12345678-Weights.buf').stat().st_size == 32
        assert (base / '12345678-State.buf').stat().st_size == 144
        assert (base / '12345678-bbb-Indices.buf').stat().st_size == 24
        # Every shader path in the generated INI must actually exist.
        for shader in re.findall(r'= (Interaction/drag/[^\s]+\.hlsl)', text):
            assert (Path(folder) / shader).is_file(), shader
    print('PASS: two picker ranges, 64 GS draws, complete resource graph and shader files')
    print('PASS: debug overlay defaults off and changes no interaction commands')
    with tempfile.TemporaryDirectory(dir=root) as folder:
        folder = Path(folder)
        pair = '-vs=1234567890abcdef-ps=fedcba0987654321'
        (folder / ('000001-ib=12345678'+pair+'.txt')).write_text('fixture')
        (folder / 'log.txt').write_text('000001 OMSetRenderTargets(NumViews:1, pDepthStencilView:0x123)\n000001 DrawIndexed(IndexCount:3)\n')
        output = folder / ('000001-o0=12345678'+pair+'.dds')
        # The same HDR format can use either the legacy D3D9 FourCC or DX10.
        # Both representations occur in actual DX11 FrameAnalysis dumps.
        header = bytearray(148)
        header[:4] = b'DDS '
        struct.pack_into('<I',header,84,113)
        output.write_bytes(header)
        assert find_picker_shaders(folder,'12345678') == ('1234567890abcdef','fedcba0987654321')
        # A live Mod replaces the dumped IB and leaves zero-byte texture
        # placeholders. Original bindings and dedup destinations are in log.
        (folder/('000001-ib=12345678'+pair+'.txt')).rename(folder/('000001-ib'+pair+'.txt'))
        (folder/'deduped').mkdir()
        (folder/'deduped/hdr.dds').write_bytes(header)
        output.write_bytes(b'')
        (folder/'log.txt').write_text(
            '000001 IASetIndexBuffer(pIndexBuffer:0x1) hash=12345678\n'
            '000001 OMSetRenderTargets(NumViews:1, pDepthStencilView:0x123)\n'
            '000001 DrawIndexed(IndexCount:3, StartIndexLocation:0, BaseVertexLocation:0)\n'
            '000001 3DMigoto Dumping Texture2D '+str(output)+' -> '+str(folder/'deduped/hdr.dds')+'\n')
        assert find_picker_shaders(folder,'12345678',first_index=0,index_count=3)==('1234567890abcdef','fedcba0987654321')
        (folder / ('000001-ps-t0=11223344'+pair+'.buf')).write_bytes(b'fixture')
        mark = SimpleNamespace(mark_name='DiffuseMap',mark_type='Slot',mark_slot='ps-t0')
        try:
            validate_texture_slots(folder,'12345678','1234567890abcdef','fedcba0987654321',[mark])
        except ValueError:
            pass
        else:
            raise AssertionError('A texture must not overwrite a captured buffer slot')
        mark.mark_type = 'Hash'
        validate_texture_slots(folder,'12345678','1234567890abcdef','fedcba0987654321',[mark])
        header[84:88] = b'DX10'
        struct.pack_into('<I',header,128,10)
        output.write_bytes(header)
        assert find_picker_shaders(folder,'12345678') == ('1234567890abcdef','fedcba0987654321')
        (folder / ('000001-o1=12345678'+pair+'.dds')).write_bytes(header)
        try:
            find_picker_shaders(folder,'12345678')
        except ValueError:
            pass
        else:
            raise AssertionError('A multiple-render-target pass must not be selected')
    print('PASS: legacy/DX10 HDR capture selection and G-buffer rejection')
    from common.interaction.automatic import latest_host_capture,region_submesh
    with tempfile.TemporaryDirectory(dir=root) as temporary:
        base=Path(temporary)
        config=base/'host'
        (config/'Games/Naraka').mkdir(parents=True)
        install=base/'game'
        import json
        (config/'settings.json').write_text(json.dumps({'CurrentGameName':'Naraka'}))
        (config/'Games/Naraka/Config.json').write_text(json.dumps({'installDir':str(install)}))
        for name in ('FrameAnalysis-2026-11-16','FrameAnalysis-2026-11-17'):
            path=install/name
            path.mkdir(parents=True)
            (path/'log.txt').write_text('fixture')
        assert Path(latest_host_capture(config,base/'workspace')).name=='FrameAnalysis-2026-11-17'
        (config/'settings.json').write_text(json.dumps({'CurrentGameName':'WWMI'}))
        try:
            latest_host_capture(config,base/'workspace')
        except ValueError:
            pass
        else:
            raise AssertionError('Do not borrow another game configuration')
    tree=SimpleNamespace(nodes=[SimpleNamespace(object_items=[SimpleNamespace(object_name='Body',submesh_name='LOD0.12345678-0')])])
    assert region_submesh(tree,SimpleNamespace(object_name='Body'))=='LOD0.12345678-0'
    print('PASS: latest host capture, game isolation and renamed object Submesh mapping')


if __name__ == '__main__':
    main()
