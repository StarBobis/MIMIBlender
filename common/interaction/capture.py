"""Find an unambiguous single-target HDR draw in a DX11 frame capture.

This is evidence selection, not a claim that every game pass is supported.
The exported picker still checks live shader identities, depth and stages.
"""
from pathlib import Path
import re
import struct


def find_picker_shaders(directory, drawib):
    """Require one shader pair with a float HDR output and bound scene depth.

    Shadow draws have no color target, and G-buffer draws have several.
    Ambiguous captures fail explicitly instead of guessing a shader hash.
    Read only filenames, DDS headers and the render-target state in the log.
    """
    directory = Path(directory)
    names = [p.name for p in directory.iterdir() if p.is_file()]
    pattern = re.compile(r'^(\d+)-ib=' + re.escape(drawib) + r'-vs=([0-9a-f]{16})-ps=([0-9a-f]{16})\.txt$', re.I)
    draws = {int(m[1]): (m[2], m[3]) for name in names if (m := pattern.match(name))}
    if not draws:
        raise ValueError('The capture contains no draws for this mesh IB')
    depth_by_draw = {}
    depth = False
    with (directory / 'log.txt').open(encoding='utf-8', errors='replace') as stream:
        for line in stream:
            match = re.match(r'(\d+) ', line)
            if not match:
                continue
            if 'OMSetRenderTargets(' in line:
                pointer = re.search(r'pDepthStencilView:(0x[0-9a-fA-F]+)', line)
                depth = bool(pointer and int(pointer[1],16))
            if ' DrawIndexed(' in line and int(match[1]) in draws:
                depth_by_draw[int(match[1])] = depth
    candidates = set()
    for number, pair in draws.items():
        prefix = f'{number:06d}-'
        outputs = [name for name in names if re.match(re.escape(prefix) + r'o\d+=', name)]
        if len(outputs) != 1 or not outputs[0].startswith(prefix+'o0=') or not depth_by_draw.get(number):
            continue
        with (directory / outputs[0]).open('rb') as stream:
            header = stream.read(148)
        # DXGI_FORMAT_R16G16B16A16_FLOAT is the reference main-pass target.
        if len(header) >= 128 and header[:4] == b'DDS ' and (
                (header[84:88] == b'DX10' and len(header)==148 and struct.unpack_from('<I',header,128)[0]==10)
                or struct.unpack_from('<I',header,84)[0]==113):
            candidates.add(pair)
    if len(candidates) != 1:
        raise ValueError('The capture has no unique single-target HDR main pass; choose another capture or configure VS/PS manually')
    return next(iter(candidates))
