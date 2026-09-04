import numpy


# Generic point attributes survive object copies, triangulation, and joins. They
# retain import-only vertex payload that Blender has no native representation for.
RAW_TANGENT_ATTRIBUTE_PREFIX = "3DMigoto:RawTANGENT"
RAW_NORMAL_W_ATTRIBUTE_PREFIX = "3DMigoto:RawNORMALW"
RAW_COLOR_ALPHA_ATTRIBUTE_PREFIX = "3DMigoto:RawCOLORA"


def _attribute_name(prefix: str, word_index: int) -> str:
    return f"{prefix}:{word_index}"


def store_raw_bytes(mesh, prefix: str, data: numpy.ndarray, byte_width: int) -> None:
    """Store one element per mesh vertex as little-endian 32-bit words."""
    if byte_width <= 0 or len(data) != len(mesh.vertices):
        return

    raw = numpy.ascontiguousarray(data).view(numpy.uint8).reshape(len(data), -1)
    if raw.shape[1] < byte_width:
        return
    raw = raw[:, :byte_width]
    word_count = (byte_width + 3) // 4
    padded = numpy.zeros((len(data), word_count * 4), dtype=numpy.uint8)
    padded[:, :byte_width] = raw
    words = padded.view(numpy.uint32).reshape(len(data), word_count)

    for word_index in range(word_count):
        name = _attribute_name(prefix, word_index)
        attribute = mesh.attributes.get(name)
        if attribute is None:
            attribute = mesh.attributes.new(name=name, type='INT', domain='POINT')
        attribute.data.foreach_set('value', words[:, word_index].view(numpy.int32))


def load_raw_bytes(mesh, prefix: str, byte_width: int):
    """Return raw bytes stored by ``store_raw_bytes``, or ``None`` if absent."""
    if byte_width <= 0:
        return None

    vertex_count = len(mesh.vertices)
    word_count = (byte_width + 3) // 4
    words = numpy.empty((vertex_count, word_count), dtype=numpy.uint32)
    for word_index in range(word_count):
        attribute = mesh.attributes.get(_attribute_name(prefix, word_index))
        if attribute is None or attribute.domain != 'POINT' or len(attribute.data) != vertex_count:
            return None
        values = numpy.empty(vertex_count, dtype=numpy.int32)
        attribute.data.foreach_get('value', values)
        words[:, word_index] = values.view(numpy.uint32)

    return words.view(numpy.uint8).reshape(vertex_count, word_count * 4)[:, :byte_width].copy()
