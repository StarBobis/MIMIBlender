"""Read extraction-owned native CS evidence without depending on Blender.

The runtime still consumes game-owned dynamic transforms. These files establish
the static source topology and bindings used by the export-side generator.
Only the measured 40-byte output recipe is accepted by this first revision.
"""
from pathlib import Path
import hashlib
import re
import numpy as np


class NativePostSkinError(ValueError):
    """An explicit unsupported or damaged native-input contract."""


def _read(root, description):
    """Resolve one copied evidence file and verify its retained digest.

    Metadata must never redirect export to an arbitrary installation or desktop
    path. Hashes are checked again when exporting, not only when importing.
    """
    if not isinstance(description, dict):
        raise NativePostSkinError("Native input description must be an object")
    name = description.get("FileName", "")
    if not isinstance(name, str) or not name:
        raise NativePostSkinError("Native input is missing its file name")
    path = (root / name.replace("\\", "/")).resolve()
    if not path.is_relative_to(root) or path == root:
        raise NativePostSkinError("Native input path escapes its workspace")
    size = description.get("ByteLength")
    digest = description.get("Sha256", "")
    if type(size) is not int or size < 1 or size > 64 * 1024 * 1024:
        raise NativePostSkinError("Native input length is unsupported")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise NativePostSkinError("Native input SHA256 is missing or malformed")
    try:
        if path.stat().st_size != size:
            raise NativePostSkinError("Native input length changed: " + name)
        data = path.read_bytes()
    except OSError as error:
        raise NativePostSkinError("Cannot read native input: " + name) from error
    if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
        raise NativePostSkinError("Native input checksum changed: " + name)
    return data


def _stage(root, stage, expected_hash, slots):
    """Accept the known instruction family and its complete required input set.

    Role labels alone are not enough to select a shader recipe. Unknown hashes
    remain extraction evidence until they have a separately validated recipe.
    """
    if not isinstance(stage, dict) or stage.get("ShaderHash") != expected_hash:
        raise NativePostSkinError("Unsupported native compute shader recipe")
    inputs = stage.get("Inputs")
    if not isinstance(inputs, dict):
        raise NativePostSkinError("Native compute inputs are missing")
    return {slot: _read(root, inputs.get(slot)) for slot in slots}


def _array(data, dtype, width, label, finite=True):
    """Require exact records before exposing a typed view to the generator."""
    dtype = np.dtype(dtype)
    if len(data) % (dtype.itemsize * width):
        raise NativePostSkinError("Misaligned native records: " + label)
    values = np.frombuffer(data, dtype=dtype).reshape(-1, width)
    if finite and dtype.kind == "f" and not np.isfinite(values).all():
        raise NativePostSkinError("Non-finite native records: " + label)
    return values


def load_native_postskin(json_path, metadata):
    """Return verified static arrays, or None for a legacy workspace.

    Shader text is optional here because the supported recipe is keyed by its
    exact recorded hash. If a captured artifact exists, its digest is checked as
    well; missing code is not represented as recovered source.
    """
    if not metadata:
        return None
    if not isinstance(metadata, dict) or metadata.get("SchemaVersion") != 1:
        raise NativePostSkinError("Unsupported NarakaPostSkin schema version")
    root = Path(json_path).resolve().parent
    stages = metadata.get("Stages", [])
    if not isinstance(stages, list) or len(stages) != 2:
        raise NativePostSkinError("Expected exactly two supported post-skin stages")
    position_stage, normal_stage = stages
    skin = _stage(root, metadata.get("Skinning"), "09d91b2eee7e232f", ["cs-t0", "cs-t1", "cs-t2"])
    position = _stage(root, position_stage, "ade59729c33f1db5", ["cs-cb0"] + ["cs-t" + str(i) for i in range(7)])
    normal = _stage(root, normal_stage, "3e301419231eeeff", ["cs-cb0"] + ["cs-t" + str(i) for i in range(6)])
    for stage in [metadata["Skinning"], position_stage, normal_stage]:
        artifact = stage.get("ShaderArtifact", {})
        if artifact.get("Status") == "CapturedArtifact":
            _read(root, artifact)
    result = {
        "source_vertices": _array(skin["cs-t0"], "<f4", 10, "skin position"),
        "source_blend_bytes": skin["cs-t1"],
        "bone_count": len(_array(skin["cs-t2"], "<f4", 16, "bones")),
        # Integer sentinel/padding bits may look like float NaNs. Validate only
        # fields that the native shader actually interprets as floating point.
        "position_records": _array(position["cs-t2"], "<f4", 8, "mapping", False),
        "position_influences": _array(position["cs-t3"], "<f4", 8, "influences", False),
        "frame_count": len(_array(position["cs-t4"], "<f4", 20, "frames", False)),
        "members": _array(position["cs-t5"], "<u4", 1, "members").ravel(),
        "offsets": _array(position["cs-t6"], "<u4", 1, "offsets").ravel(),
        "normal_targets": _array(normal["cs-t1"], "<u4", 1, "normal targets").ravel(),
        "position_inputs": position,
        "normal_inputs": normal,
        "metadata": metadata,
    }
    count = len(result["source_vertices"])
    if not np.isfinite(result["position_records"][:, 4]).all() or not np.isfinite(result["position_influences"][:, :4]).all():
        raise NativePostSkinError("Non-finite native deformation coefficients")
    if len(result["source_blend_bytes"]) != count * 32:
        raise NativePostSkinError("Native position/blend vertex counts differ")
    members, offsets = result["members"], result["offsets"]
    if len(offsets) < 2 or offsets[0] != 0 or offsets[-1] != len(members):
        raise NativePostSkinError("Invalid native group offset endpoints")
    if np.any(offsets[1:] <= offsets[:-1]) or not np.array_equal(np.sort(members), np.arange(count)):
        raise NativePostSkinError("Native groups do not partition source vertices")
    # Both original passes must agree on which render vertices each group owns.
    if normal["cs-t2"] != position["cs-t5"] or normal["cs-t3"] != position["cs-t6"]:
        raise NativePostSkinError("Native stages disagree on vertex groups")
    group_count = len(offsets) - 1
    mapping = result["position_records"].view("<u4")
    influence_count = len(result["position_influences"])
    if np.any(mapping[:, 0] >= group_count) or len(np.unique(mapping[:, 0])) != len(mapping):
        raise NativePostSkinError("Invalid or repeated deformation target groups")
    if np.any(mapping[:, 1] >= mapping[:, 2]) or np.any(mapping[:, 2] > influence_count):
        raise NativePostSkinError("Deformation influence ranges exceed their buffer")
    frame_indices = result["position_influences"].view("<u4")[:, 4]
    if np.any(frame_indices >= result["frame_count"]):
        raise NativePostSkinError("Deformation frame index exceeds its buffer")
    triangles = _array(normal["cs-t0"], "<u4", 3, "native triangles")
    adjacency = _array(normal["cs-t4"], "<u4", 1, "adjacency").ravel()
    adj_offsets = _array(normal["cs-t5"], "<u4", 1, "adjacency offsets").ravel()
    if triangles.max(initial=0) >= group_count or result["normal_targets"].max(initial=0) >= group_count:
        raise NativePostSkinError("Native normal group index exceeds its table")
    if len(adj_offsets) != group_count + 1 or adj_offsets[0] != 0 or adj_offsets[-1] != len(adjacency):
        raise NativePostSkinError("Invalid normal adjacency endpoints")
    if np.any(adj_offsets[1:] < adj_offsets[:-1]) or not np.array_equal(np.sort(adjacency), np.arange(triangles.size)):
        raise NativePostSkinError("Native adjacency does not cover triangle corners")
    # The CSR lists corner ownership, not arbitrary neighboring triangle IDs.
    # This distinction matters because the native shader uses corner modulo 3.
    corner_groups = triangles.ravel()[adjacency]
    expected_groups = np.repeat(np.arange(group_count), np.diff(adj_offsets.astype(np.int64)))
    if not np.array_equal(corner_groups, expected_groups):
        raise NativePostSkinError("Native adjacency corner ownership differs")
    result["source_group_triangles"] = triangles
    draw = metadata.get("DrawInputs", {})
    if not isinstance(draw, dict) or "vb1" not in draw or "ib" not in draw:
        raise NativePostSkinError("Source UV/index evidence is missing; extract the workspace again")
    # Index width and vertex stride are witnessed in hashed dump headers.
    # Never infer an index format merely because a file length is divisible.
    def header(item):
        try:
            text = _read(root, item.get("Header")).decode("utf-8-sig")
            return dict(line.split(": ", 1) for line in text.split("vertex-data:", 1)[0].splitlines() if ": " in line)
        except (UnicodeError, AttributeError) as error:
            raise NativePostSkinError("Native source header is invalid") from error
    vertex_header = header(draw["vb1"])
    if vertex_header.get("stride") != "8" or vertex_header.get("first vertex") != "0":
        raise NativePostSkinError("Unsupported native source UV layout")
    source_uv = _array(_read(root, draw["vb1"]), "<f4", 2, "source UV")
    if len(source_uv) != count or int(vertex_header.get("vertex count", -1)) != count:
        raise NativePostSkinError("Source UV and skinning vertex counts differ")
    index_header = header(draw["ib"])
    dtype = {"DXGI_FORMAT_R16_UINT": "<u2", "DXGI_FORMAT_R32_UINT": "<u4"}.get(index_header.get("format"))
    if dtype is None or index_header.get("topology") != "trianglelist":
        raise NativePostSkinError("Unsupported native source index layout")
    raw_indices = _array(_read(root, draw["ib"]), dtype, 1, "source indices").ravel()
    offset = int(index_header.get("byte offset", -1))
    first = int(index_header.get("first index", -1))
    number = int(index_header.get("index count", -1))
    width = np.dtype(dtype).itemsize
    if offset < 0 or offset % width or first < 0 or number < 1 or number % 3:
        raise NativePostSkinError("Invalid source triangle range")
    start = offset // width + first
    if start + number > len(raw_indices):
        raise NativePostSkinError("Source triangle range exceeds its buffer")
    source_triangles = raw_indices[start:start + number].astype("<u4").reshape(-1, 3)
    if source_triangles.max(initial=0) >= count:
        raise NativePostSkinError("Source triangle vertex exceeds skinning count")
    result["source_uv"] = source_uv
    result["source_triangles"] = source_triangles
    return result
