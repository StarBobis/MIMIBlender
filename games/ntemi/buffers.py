"""
NTMIv1 buffer file generation.

Writes every part's NTMIv1-format buffer files (position / blend / normal /
texcoord / outline / index / bone palette).  The category buffers of a
SubMeshModel are flat uint8 arrays (raw bytes per category); they are
reinterpreted here using the D3D11Element layout of the game type.
"""

import os

import numpy

from ...common.global_config import GlobalConfig
from ...utils.format_utils import FormatUtils
from .parts import part_name


def generate_buffer_files(drawib_model_list):
    """Write all NTMIv1 buffer files of every part of every DrawIB."""
    buf_output_folder = GlobalConfig.path_generatemod_buffer_folder()

    for drawib_model in drawib_model_list:
        for part_index, submesh_model in enumerate(drawib_model.submesh_model_list):
            name = part_name(drawib_model, part_index, submesh_model)
            write_ntmi_buffers(submesh_model, name, buf_output_folder)


def write_ntmi_buffers(submesh_model, part_name_str: str, buf_folder: str):
    """Write all NTMIv1-format buffer files for one part.

    category_buffer_dict values are flat uint8 arrays (raw bytes per category).
    We reinterpret them using the D3D11Element layout from the game type.
    """
    category_bufs = submesh_model.category_buffer_dict
    game_type = submesh_model.d3d11_game_type
    stride_dict = game_type.CategoryStrideDict if game_type else {}
    # Build per-category element layouts: category -> [(element_name, byte_offset, byte_width, format), ...]
    cat_layouts = build_category_layouts(game_type) if game_type else {}

    # --- Position buffer (R32_FLOAT) ---
    pos_bytes = category_bufs.get("Position")
    if pos_bytes is not None and "Position" in stride_dict:
        write_position_buffer(pos_bytes, stride_dict["Position"],
                              os.path.join(buf_folder, f"{part_name_str}-position.buf"))

    # --- Blend buffer (R32_UINT pairs) ---
    blend_bytes = category_bufs.get("Blend")
    if blend_bytes is not None and "Blend" in cat_layouts:
        write_blend_buffer(blend_bytes, stride_dict["Blend"], cat_layouts["Blend"],
                           os.path.join(buf_folder, f"{part_name_str}-blend.buf"))

    # --- Normal buffer (R8G8B8A8_SNORM alternating TANGENT, NORMAL) ---
    normal_bytes = category_bufs.get("Normal")
    if normal_bytes is not None and "Normal" in cat_layouts:
        write_normal_buffer(normal_bytes, stride_dict["Normal"], cat_layouts["Normal"],
                            os.path.join(buf_folder, f"{part_name_str}-normal.buf"))

    # --- Texcoord buffer (R16G16_FLOAT) ---
    tex_bytes = category_bufs.get("Texcoord")
    if tex_bytes is not None and "Texcoord" in cat_layouts:
        write_texcoord_buffer(tex_bytes, stride_dict["Texcoord"], cat_layouts["Texcoord"],
                              os.path.join(buf_folder, f"{part_name_str}-texcoord.buf"))

    # --- Outline buffer (R8G8B8A8_UNORM from COLOR) ---
    color_bytes = category_bufs.get("Color")
    if color_bytes is not None:
        stride = stride_dict.get("Color", 4)
        n_verts = len(color_bytes) // stride if stride > 0 else 0
        if n_verts > 0:
            color_u8 = color_bytes[:n_verts * stride].reshape(n_verts, stride)
            write_buf(os.path.join(buf_folder, f"{part_name_str}-outline.buf"), color_u8.reshape(-1))

    # --- Index buffer (auto R16_UINT or R32_UINT) ---
    ib = submesh_model.ib
    if ib:
        max_index = max(ib)
        if max_index <= 65535:
            ib_arr = numpy.asarray(ib, dtype=numpy.uint16)
        else:
            ib_arr = numpy.asarray(ib, dtype=numpy.uint32)
        write_buf(os.path.join(buf_folder, f"{part_name_str}-ib.buf"), ib_arr)

    # --- Bone palette buffer (R32_UINT) ---
    palette = getattr(submesh_model, 'ntemi_bone_palette', None) or []
    if palette:
        pal_arr = numpy.asarray(palette, dtype=numpy.uint32)
        draw_ib = submesh_model.match_draw_ib
        index_count = submesh_model.match_index_count
        chunk_index = submesh_model.match_first_index
        palette_filename = f"{draw_ib}-{index_count}-{chunk_index}-Palette.buf"
        write_buf(os.path.join(buf_folder, palette_filename), pal_arr)


def build_category_layouts(game_type) -> dict:
    """Build per-category element layouts from D3D11GameType.

    AlignedByteOffset is global across all elements. Category buffers only
    contain the bytes for their own elements, so we subtract the first
    element's offset to make them category-local.

    Returns: {category_name: [(element_name, local_byte_offset, byte_width, format), ...]}
    """
    layouts: dict[str, list] = {}
    for elem in game_type.D3D11ElementList:
        cat = elem.Category
        if cat not in layouts:
            layouts[cat] = []
        byte_width = elem.ByteWidth if elem.ByteWidth > 0 else FormatUtils.format_size(elem.Format)
        layouts[cat].append((elem.ElementName, elem.AlignedByteOffset, byte_width, elem.Format))
    # Make offsets category-local
    for cat, elems in layouts.items():
        base = elems[0][1]  # first element's global offset
        layouts[cat] = [(name, off - base, width, fmt) for name, off, width, fmt in elems]
    return layouts


def write_position_buffer(data: numpy.ndarray, stride: int, filepath: str):
    """Write R32_FLOAT position buffer. data is flat uint8 per-vertex bytes."""
    n_verts = len(data) // stride if stride > 0 else 0
    if n_verts == 0:
        return
    chunk = data[:n_verts * stride]
    # POSITION is R32G32B32_FLOAT: first 12 bytes = 3 float32s
    pos_f32 = chunk.reshape(n_verts, stride)[:, :12].reshape(-1).view(numpy.float32)
    write_buf(filepath, pos_f32)


def write_blend_buffer(data: numpy.ndarray, stride: int, layout: list, filepath: str):
    """Write NTMIv1 blend buffer: interleaved (index_u32, weight_fixed_u32) per influence.

    layout: list of (element_name, byte_offset, byte_width, format)
    """
    n_verts = len(data) // stride if stride > 0 else 0
    if n_verts == 0:
        return

    chunk = data[:n_verts * stride].reshape(n_verts, stride)

    # Find BLENDINDICES and BLENDWEIGHTS elements in layout
    idx_elem = None
    wt_elem = None
    for name, offset, width, fmt in layout:
        if name == "BLENDINDICES":
            idx_elem = (offset, width, fmt)
        elif name == "BLENDWEIGHTS" or name == "BLENDWEIGHT":
            wt_elem = (offset, width, fmt)

    if idx_elem is None or wt_elem is None:
        print(f"WARNING: Blend layout missing BLENDINDICES/BLENDWEIGHTS, skipping blend buffer")
        return

    idx_offset, idx_width, idx_fmt = idx_elem
    wt_offset, wt_width, wt_fmt = wt_elem

    # Extract raw bytes for indices and weights
    raw_indices = chunk[:, idx_offset:idx_offset + idx_width]
    raw_weights = chunk[:, wt_offset:wt_offset + wt_width]

    # Number of influences = byte_width (R8G8B8A8_UINT has 4 bytes = 4 uint8s)
    n_influences = idx_width

    idx_u32 = numpy.asarray(raw_indices, dtype=numpy.uint32)
    wt_u8 = numpy.asarray(raw_weights, dtype=numpy.uint32)
    wt_fixed = wt_u8 * 257  # [0,255] -> [0,65535]

    # Interleave: idx_0, wt_0, idx_1, wt_1, ...
    interleaved = numpy.empty((n_verts, n_influences * 2), dtype=numpy.uint32)
    interleaved[:, 0::2] = idx_u32
    interleaved[:, 1::2] = wt_fixed

    write_buf(filepath, interleaved.reshape(-1))


def write_normal_buffer(data: numpy.ndarray, stride: int, layout: list, filepath: str):
    """Write NTMIv1 normal buffer: alternating TANGENT and NORMAL as R8G8B8A8_SNORM."""
    n_verts = len(data) // stride if stride > 0 else 0
    if n_verts == 0:
        return

    chunk = data[:n_verts * stride].reshape(n_verts, stride)

    tg_elem = None
    nm_elem = None
    for name, offset, width, fmt in layout:
        if name == "TANGENT":
            tg_elem = (offset, width, fmt)
        elif name == "NORMAL":
            nm_elem = (offset, width, fmt)

    if tg_elem is None or nm_elem is None:
        print(f"WARNING: Normal layout missing TANGENT/NORMAL, skipping normal buffer")
        return

    tg_offset, tg_width, _ = tg_elem
    nm_offset, nm_width, _ = nm_elem

    if tg_width == 0 or nm_width == 0:
        print(f"WARNING: Normal element width is 0 (TANGENT={tg_width}, NORMAL={nm_width}), skipping normal buffer")
        return

    tangents = chunk[:, tg_offset:tg_offset + tg_width].astype(numpy.int8)
    normals = chunk[:, nm_offset:nm_offset + nm_width].astype(numpy.int8)

    # Interleave: T0, N0, T1, N1, ...
    interleaved = numpy.empty((n_verts * 2, tg_width), dtype=numpy.int8)
    interleaved[0::2] = tangents
    interleaved[1::2] = normals
    write_buf(filepath, interleaved.reshape(-1))


def write_texcoord_buffer(data: numpy.ndarray, stride: int, layout: list, filepath: str):
    """Write NTMIv1 texcoord buffer: R16G16_FLOAT from R32G32_FLOAT source."""
    n_verts = len(data) // stride if stride > 0 else 0
    if n_verts == 0:
        return

    chunk = data[:n_verts * stride].reshape(n_verts, stride)

    # Find TEXCOORD element
    tc_elem = None
    for name, offset, width, fmt in layout:
        if name.startswith("TEXCOORD"):
            tc_elem = (offset, width, fmt)
            break

    if tc_elem is None:
        print(f"WARNING: Texcoord layout missing TEXCOORD, skipping texcoord buffer")
        return

    tc_offset, tc_width, tc_fmt = tc_elem

    raw_tc = chunk[:, tc_offset:tc_offset + tc_width]
    # Source is R32G32_FLOAT (8 bytes = 2 float32s)
    tc_f32 = raw_tc.view(numpy.float32).reshape(n_verts, -1)[:, :2]
    tc_f16 = tc_f32.astype(numpy.float16)
    write_buf(filepath, tc_f16.reshape(-1))


def write_buf(filepath: str, arr: numpy.ndarray):
    """Write a flat numpy array as a raw .buf file."""
    with open(filepath, 'wb') as f:
        arr.tofile(f)
