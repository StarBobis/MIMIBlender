"""Find an unambiguous single-target HDR draw in a DX11 frame capture.

This is evidence selection, not a claim that every game pass is supported.
The exported picker still checks live shader identities, depth and stages.
"""
from pathlib import Path
import re
import struct


def find_picker_shaders(directory, drawib, first_index=None, index_count=None):
    """Require one shader pair with a float HDR output and bound scene depth.

    Shadow draws have no color target, and G-buffer draws have several.
    Ambiguous captures fail explicitly instead of guessing a shader hash.
    Read only filenames, DDS headers and the render-target state in the log.
    """
    directory = Path(directory)
    names = [p.name for p in directory.iterdir() if p.is_file()]
    pattern = re.compile(r'^(\d+)-ib=' + re.escape(drawib) + r'-vs=([0-9a-f]{16})-ps=([0-9a-f]{16})\.txt$', re.I)
    draws = {int(m[1]): (m[2], m[3]) for name in names if (m := pattern.match(name))}
    target_draws=set(draws)
    any_ib=re.compile(r'^(\d+)-ib(?:=[0-9a-f]{8})?-vs=([0-9a-f]{16})-ps=([0-9a-f]{16})\.txt$',re.I)
    draws.update({int(m[1]):(m[2],m[3]) for name in names if (m:=any_ib.match(name))})
    depth_by_draw = {}
    ranges={}
    deduped={}
    depth = False
    active_ib=''
    with (directory / 'log.txt').open(encoding='utf-8', errors='replace') as stream:
        for line in stream:
            dumped=re.search(r'Dumping Texture2D (.*?) -> (.*)',line)
            if dumped:
                name=dumped[1].replace('\\','/').split('/')[-1]
                destination=dumped[2].strip().replace('\\','/').split('/')[-1]
                deduped[name]=directory/'deduped'/destination
            match = re.match(r'(\d+) ', line)
            if not match:
                continue
            if ' IASetIndexBuffer(' in line:
                ib=re.search(r'hash=([0-9a-fA-F]{8})',line)
                active_ib=ib[1].lower() if ib else ''
            # An active Mod may replace the IB before dumping. Attribute
            # its capture to the original game binding in the API log.
            if ' DrawIndexed(' in line and active_ib==drawib.lower():
                target_draws.add(int(match[1]))
            if 'OMSetRenderTargets(' in line:
                pointer = re.search(r'pDepthStencilView:(0x[0-9a-fA-F]+)', line)
                depth = bool(pointer and int(pointer[1],16))
            if ' DrawIndexed(' in line and int(match[1]) in draws:
                depth_by_draw[int(match[1])] = depth
                values=re.search(r'IndexCount:(\d+), StartIndexLocation:(\d+)',line)
                if values:
                    ranges[int(match[1])]=(int(values[1]),int(values[2]))
    candidates = set()
    if not target_draws:
        raise ValueError('The capture contains no draws for this mesh IB')
    for number, pair in draws.items():
        if number not in target_draws:
            continue
        if first_index is not None and ranges.get(number,(None,None))[1]!=first_index:
            continue
        if index_count is not None and ranges.get(number,(None,None))[0]!=index_count:
            continue
        prefix = f'{number:06d}-'
        outputs = [name for name in names if re.match(re.escape(prefix) + r'o\d+=', name)]
        if len(outputs) != 1 or not outputs[0].startswith(prefix+'o0=') or not depth_by_draw.get(number):
            continue
        path=directory/outputs[0]
        if path.stat().st_size<128:
            path=deduped.get(outputs[0],path)
        with path.open('rb') as stream:
            header = stream.read(148)
        # DXGI_FORMAT_R16G16B16A16_FLOAT is the reference main-pass target.
        if len(header) >= 128 and header[:4] == b'DDS ' and (
                (header[84:88] == b'DX10' and len(header)==148 and struct.unpack_from('<I',header,128)[0]==10)
                or struct.unpack_from('<I',header,84)[0]==113):
            candidates.add(pair)
    if len(candidates) != 1:
        raise ValueError('The capture has no unique single-target HDR main pass; choose another capture or configure VS/PS manually')
    return next(iter(candidates))


def validate_texture_slots(directory, drawib, vs, ps, marks):
    """Reject texture marks that would overwrite a witnessed buffer binding.

    Capture slot numbers belong to a shader pass. A diffuse texture found
    in another slot must never replace that pass's structured-buffer input.
    Check only the selected IB and shader pair, and only explicit evidence.
    """
    names = [p.name for p in Path(directory).iterdir() if p.is_file()]
    suffix = '-vs=' + vs + '-ps=' + ps
    draws = {name.split('-',1)[0] for name in names
             if '-ib=' + drawib + suffix + '.txt' in name}
    active_ib=''
    with (Path(directory)/'log.txt').open(encoding='utf-8',errors='replace') as stream:
        for line in stream:
            if ' IASetIndexBuffer(' in line:
                match=re.search(r'hash=([0-9a-fA-F]{8})',line)
                active_ib=match[1].lower() if match else ''
            if active_ib==drawib.lower() and ' DrawIndexed(' in line:
                match=re.match(r'(\d+) ',line)
                if match:
                    draws.add(match[1])
    buffers = set()
    for name in names:
        if name.split('-',1)[0] not in draws or suffix + '.buf' not in name:
            continue
        match = re.match(r'\d+-(ps-t\d+)=',name)
        if match:
            buffers.add(match[1])
    for mark in marks:
        if mark.mark_type in ('Slot','SharedSlot') and mark.mark_slot in buffers:
            raise ValueError('Texture mark ' + mark.mark_name + ' targets ' + mark.mark_slot
                             + ', but the selected render pass binds a buffer there; '
                             + 'correct the texture mark or use Hash replacement before exporting')
