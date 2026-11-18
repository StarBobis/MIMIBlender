"""Resolve Naraka clothing opacity slots and generate constant-alpha DDS files."""

import re
import struct

# Both hashes select the gray alpha texture in the sample. A new outfit
# can opt in with an explicit MMT mark without borrowing these hashes.
_SAMPLE_HASHES = {"174bcdb1", "1e3349c0"}
_PS_SLOT = re.compile(r"ps-t[0-9]{1,3}")


def _ps_slot(value):
    slot = str(value or "").strip().lower()
    if not _PS_SLOT.fullmatch(slot):
        return ""
    index = int(slot[4:])
    return f"ps-t{index}" if index <= 127 else ""


def resolve_slot(binding, marks, draw):
    from ...i18n.i18n import tr

    # A Cross-IB guest is drawn using the host PS and its texture layout.
    # Guest capture metadata cannot identify the host's material slot.
    if binding["slot_mode"] == "MANUAL":
        slot = _ps_slot(binding["slot"])
        if not slot:
            raise ValueError(tr("Use a PS texture slot from ps-t0 to ps-t127."))
        return slot
    if draw.cross_render_at_submesh:
        raise ValueError(tr("For Cross-IB draws, use the manual slot of the host material."))

    name = binding["mark_name"].strip().casefold()
    matching = [mark for mark in marks if str(mark.mark_name or "").strip().casefold() == (name or "opacity")]
    if not matching and not name:
        matching = [mark for mark in marks if str(mark.mark_hash or "").strip().lower() in _SAMPLE_HASHES]
    slots = {_ps_slot(mark.mark_slot) for mark in matching}
    if len(slots - {""}) > 1:
        raise ValueError(tr("Several opacity slots match. Enter a unique mark name or use Manual Slot."))
    if not slots or "" in slots:
        raise ValueError(tr("Mark one clothing opacity slot in MMT, or enter the slot manually."))
    return slots.pop()


def solid_alpha_dds(rgba):
    # An uncompressed 4x4 R8G8B8A8_UNORM DDS reads the specified alpha
    # without BC7 quantization or a converter dependency. Every texel is
    # identical, so UVs, filtering and missing mip levels cannot change it.
    header = struct.pack(
        "<31I",
        124, 0x100F, 4, 4, 16, 0, 0,
        *([0] * 11),
        32, 0x4, int.from_bytes(b"DX10", "little"), 0, 0, 0, 0, 0,
        0x1000, 0, 0, 0, 0,
    )
    dx10 = struct.pack("<5I", 28, 3, 0, 1, 1)
    return b"DDS " + header + dx10 + bytes(rgba) * 16
