"""Joint packing for YYSLS's two interleaved four-influence bone sets.

WWMI already gathers a bounded number of influences as one wide array. Reuse
that gatherer, normalize and quantize the complete eight-column array once,
then split it for YYSLS's weight0/index0/weight1/index1 physical layout.
Four-influence YYSLS meshes deliberately stay on the historical exporter path.
"""

import numpy

from .format_utils import Fatal, FormatUtils
from .vertexgroup_utils import VertexGroupUtils


def has_extended_blend(game_type):
    """Use explicit bone semantics, never a buffer hash or a color count."""
    elements = game_type.ElementNameD3D11ElementDict
    return "BLENDWEIGHT1" in elements or "BLENDINDICES1" in elements


def pack_extended_blend(mesh, game_type):
    """Return per-semantic-index byte weights and integer bone indices.

    Both sets must be present and use the actual YYSLS packed formats. A
    partial/mislabeled layout must not silently export half a skeleton.
    Limiting to eight influences happens before normalization, matching WWMI.
    Quantizing each four-column half separately would incorrectly produce
    255 + 255 instead of a total weight of 255 for the whole vertex.
    """
    elements = game_type.ElementNameD3D11ElementDict
    for index in range(2):
        suffix = str(index) if index else ""
        for semantic, fmt in (("BLENDWEIGHT", "R8G8B8A8_UNORM"),
                              ("BLENDINDICES", "R8G8B8A8_UINT")):
            element = elements.get(semantic + suffix)
            if element is None or element.Format != fmt or element.ByteWidth != 4:
                raise Fatal("YYSLS EXT8 requires two complete four-influence weight/index sets")

    weights, indices = VertexGroupUtils.get_blendweights_blendindices_v4_fast(
        mesh=mesh, normalize_weights=True, blend_size=8)
    # The shared gatherer can return only four columns when the entire mesh
    # uses at most four influences. The second physical set still needs zeros.
    wide_weights = numpy.zeros((len(mesh.loops), 8), dtype=numpy.float32)
    wide_indices = numpy.zeros((len(mesh.loops), 8), dtype=numpy.uint32)
    width = weights[0].shape[1]
    wide_weights[:, :width] = weights[0]
    wide_indices[:, :width] = indices[0]

    # Keep the established quantizer's rounding policy but call it just once.
    # Empty rows must remain empty rather than gaining a fabricated influence.
    # Do not cast indices to uint8 here: the existing remap stage still needs
    # their full precision and performs range handling before buffer packing.
    packed = FormatUtils.convert_4x_float32_to_r8g8b8a8_unorm_blendweights(wide_weights)
    packed[wide_weights.sum(axis=1) == 0] = 0
    return ({0: packed[:, :4], 1: packed[:, 4:]},
            {0: wide_indices[:, :4], 1: wide_indices[:, 4:]})
