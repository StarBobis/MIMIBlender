"""Small, self-contained writer for GIMI compute-shader face mods.

The format is intentionally compatible with the buffers produced by
``gdsfdg/facemodtools``: 40 bytes per vertex containing position, normal and
tangent.  The shader only reads the position field, but keeping the original
layout lets it bind against GIMI's face ``vb0`` without a format override.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
import re
from typing import Iterable

import numpy


FACE_VERTEX_STRIDE = 40

FACE_HLSL = """struct vb0 {
    float3 position;
    float3 normal;
    float4 tangent;
};

RWStructuredBuffer<vb0> rw_buffer : register(u1);
StructuredBuffer<vb0> base : register(t0);
StructuredBuffer<vb0> key : register(t1);

[numthreads(1, 1, 1)]
void main(uint3 DTid : SV_DispatchThreadID)
{
    rw_buffer[DTid.x].position += key[DTid.x].position - base[DTid.x].position;
}
"""


@dataclass(frozen=True)
class FaceModPart:
    """One face payload, triggered by stable index-buffer hashes."""

    name: str
    base_bytes: bytes
    key_bytes: bytes
    index_hashes: tuple[str, ...]

    @property
    def vertex_count(self) -> int:
        return len(self.base_bytes) // FACE_VERTEX_STRIDE


def gimi_face_local_to_game_positions(positions: numpy.ndarray) -> numpy.ndarray:
    """Undo SSMT's applied GIMI import rotation for face-buffer positions.

    GIMI meshes are displayed in Blender after an X-axis +90 degree rotation
    has been applied to their mesh-local coordinates.  The game Position VB
    uses the inverse basis.  This conversion deliberately does not inspect an
    object's transform; it operates only on the mesh-local coordinates.
    """
    values = numpy.asarray(positions, dtype=numpy.float32)
    if values.ndim != 2 or values.shape[1] != 3:
        raise ValueError("Face key positions must be an Nx3 array.")

    result = values.copy()
    result[:, 1] = values[:, 2]
    result[:, 2] = -values[:, 1]
    return result


def build_key_bytes(positions: numpy.ndarray) -> bytes:
    """Pack Blender mesh coordinates into the face-mod's 40-byte layout."""
    values = numpy.asarray(positions, dtype=numpy.float32)
    if values.ndim != 2 or values.shape[1] != 3:
        raise ValueError("Face key positions must be an Nx3 array.")

    packed = numpy.zeros((len(values), 10), dtype=numpy.float32)
    packed[:, :3] = values
    return packed.tobytes()


def slice_face_base_buffer(
    source_path: str,
    vertex_offset: int = 0,
    vertex_count: int = -1,
) -> bytes:
    """Read the requested 40-byte vertex slice from an extracted Position VB."""
    file_size = os.path.getsize(source_path)
    if file_size % FACE_VERTEX_STRIDE:
        raise ValueError(
            "The source Position buffer is not aligned to the 40-byte GIMI face layout."
        )

    available_count = file_size // FACE_VERTEX_STRIDE
    offset = max(int(vertex_offset), 0)
    count = available_count - offset if int(vertex_count) <= 0 else int(vertex_count)
    if count <= 0 or offset + count > available_count:
        raise ValueError("The requested face vertex slice is outside the source Position buffer.")

    with open(source_path, "rb") as source_file:
        source_file.seek(offset * FACE_VERTEX_STRIDE)
        result = source_file.read(count * FACE_VERTEX_STRIDE)

    if len(result) != count * FACE_VERTEX_STRIDE:
        raise ValueError("Could not read the complete face Position buffer slice.")
    return result


def _identifier(value: str, fallback: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_]", "_", str(value or "")).strip("_")
    if not value:
        value = fallback
    if value[0].isdigit():
        value = "Part_" + value
    return value


def _unique_part_names(parts: Iterable[FaceModPart]) -> list[tuple[FaceModPart, str]]:
    result = []
    used_names: set[str] = set()
    for index, part in enumerate(parts):
        base_name = _identifier(part.name, f"Face{index + 1}")
        candidate = base_name
        suffix = 2
        while candidate.lower() in used_names:
            candidate = f"{base_name}_{suffix}"
            suffix += 1
        used_names.add(candidate.lower())
        result.append((part, candidate))
    return result


def parse_face_index_hashes(value: str | Iterable[str] | None) -> tuple[str, ...]:
    """Normalize user-supplied stable Face IB hashes, preserving their order."""
    raw_values = value.split(",") if isinstance(value, str) else (value or ())
    result = []
    seen = set()
    for raw in raw_values:
        hash_value = str(raw or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{8}", hash_value) or hash_value in seen:
            continue
        seen.add(hash_value)
        result.append(hash_value)
    return tuple(result)


def build_face_ini(parts: Iterable[FaceModPart], diffuse_hash: str = "") -> str:
    """Build the complete 3Dmigoto configuration for ``parts``."""
    named_parts = _unique_part_names(parts)
    if not named_parts:
        raise ValueError("At least one face part is required.")

    for part, _ in named_parts:
        if not parse_face_index_hashes(part.index_hashes):
            raise ValueError(f"Face part '{part.name}' has no valid Face index-buffer hash.")
        if len(part.base_bytes) != len(part.key_bytes) or len(part.base_bytes) % FACE_VERTEX_STRIDE:
            raise ValueError(f"Face part '{part.name}' has incompatible base/key buffers.")

    gate_hash = str(diffuse_hash or "").strip()
    gate_variable = "$ssmt_face_mod_active"
    lines: list[str] = ["; Generated by TheHerta4 SSMT face-mod exporter.", ""]

    if gate_hash:
        lines.extend([
            "[Constants]",
            f"global {gate_variable} = 0",
            "",
            "[Present]",
            f"post {gate_variable} = 0",
            "",
            "; Optional character scope. This does not replace the diffuse texture.",
            "[TextureOverrideSSMTFaceDiffuse]",
            f"hash = {gate_hash}",
            "match_priority = 0",
            f"{gate_variable} = 1",
            "",
        ])

    multiple_parts = len(named_parts) > 1
    for part, part_name in named_parts:
        relative_prefix = part_name + "/" if multiple_parts else ""
        # Face vb0 is CPU-generated and its hash changes between scenes.  The
        # index buffer identifies the draw reliably; copy its *current* vb0.
        for index_hash in parse_face_index_hashes(part.index_hashes):
            lines.extend([
                f"[TextureOverrideSSMTFace{part_name}_{index_hash}]",
                f"hash = {index_hash}",
            ])
            if gate_hash:
                lines.extend([f"if {gate_variable}", f"  run = CommandListSSMTFace{part_name}", "endif"])
            else:
                lines.append(f"run = CommandListSSMTFace{part_name}")
            lines.append("")
        lines.extend([
            "",
            f"[CommandListSSMTFace{part_name}]",
            f"ResourceSSMTFace{part_name}Dif = copy vb0",
            f"run = CustomShaderSSMTFace{part_name}",
            f"vb0 = ResourceSSMTFace{part_name}Dif",
            "",
            f"[ResourceSSMTFace{part_name}Dif]",
            "",
            f"[ResourceSSMTFace{part_name}Base]",
            "type = RWBuffer",
            f"stride = {FACE_VERTEX_STRIDE}",
            f"filename = {relative_prefix}base.buf",
            "",
            f"[ResourceSSMTFace{part_name}Key]",
            "type = RWBuffer",
            f"stride = {FACE_VERTEX_STRIDE}",
            f"filename = {relative_prefix}key.buf",
            "",
            f"[CustomShaderSSMTFace{part_name}]",
            "cs = Face.hlsl",
            "",
            f"cs-u1 = copy ResourceSSMTFace{part_name}Dif",
            f"cs-t0 = copy ResourceSSMTFace{part_name}Base",
            f"cs-t1 = copy ResourceSSMTFace{part_name}Key",
            "",
            f"Dispatch = {part.vertex_count}, 1, 1",
            f"ResourceSSMTFace{part_name}Dif = copy cs-u1",
            "post cs-u1 = null",
            "",
        ])

    return "\n".join(lines)


def write_face_mod(output_folder: str, parts: Iterable[FaceModPart], diffuse_hash: str = "") -> str:
    """Write ``Face.ini``, ``Face.hlsl`` and the part buffers to ``output_folder``."""
    named_parts = _unique_part_names(parts)
    if not named_parts:
        raise ValueError("At least one face part is required.")

    output_folder = os.path.abspath(output_folder)
    os.makedirs(output_folder, exist_ok=True)
    ini = build_face_ini([part for part, _ in named_parts], diffuse_hash=diffuse_hash)

    with open(os.path.join(output_folder, "Face.hlsl"), "w", encoding="utf-8", newline="\n") as hlsl_file:
        hlsl_file.write(FACE_HLSL)
    with open(os.path.join(output_folder, "Face.ini"), "w", encoding="utf-8", newline="\n") as ini_file:
        ini_file.write(ini)

    multiple_parts = len(named_parts) > 1
    for part, part_name in named_parts:
        part_folder = os.path.join(output_folder, part_name) if multiple_parts else output_folder
        os.makedirs(part_folder, exist_ok=True)
        with open(os.path.join(part_folder, "base.buf"), "wb") as base_file:
            base_file.write(part.base_bytes)
        with open(os.path.join(part_folder, "key.buf"), "wb") as key_file:
            key_file.write(part.key_bytes)

    return output_folder
