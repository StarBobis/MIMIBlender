"""Model-scoped resource and NBPv1 call generation, independent of Blender.

All binary allocations belong to the generated Mod. The installed Package owns
the shared HLSL and execution sequence. No shader is copied into ShaderFixes.
"""
from pathlib import Path
import re
import numpy as np
from .native_postskin_data import NativePostSkinError, load_native_postskin
from .native_postskin_binding import bind_subdivision_sources
from .native_postskin_buffers import build_native_buffers


def prepare_native_export(json_path, metadata, draw_ib, output_hash, categories, index_lists):
    """Validate and compute everything before the shared exporter writes files.

    Legacy workspaces have no evidence and retain their previous export path.
    Evidence-bearing workspaces fail explicitly when a recipe cannot be used.
    This prevents incomplete native resources from silently becoming skip-only
    physics removal or a partially generated replacement configuration.
    """
    if not metadata:
        return None
    if not re.fullmatch(r"[0-9a-fA-F]{8}", draw_ib) or not re.fullmatch(r"[0-9a-fA-F]{8}", output_hash):
        raise NativePostSkinError("Invalid native DrawIB/output hash")
    if metadata.get("OutputHash", "").lower() != output_hash.lower():
        raise NativePostSkinError("Native evidence belongs to a different output buffer")
    evidence = load_native_postskin(json_path, metadata)
    try:
        vertices = np.frombuffer(np.asarray(categories["Position"], dtype=np.uint8).tobytes(), "<f4").reshape(-1, 10)
        uv = np.frombuffer(np.asarray(categories["Texcoord"], dtype=np.uint8).tobytes(), "<f4").reshape(-1, 2)
        triangles = np.concatenate([np.asarray(indices, dtype=np.uint32) for indices in index_lists if len(indices)]).reshape(-1, 3)
    except (KeyError, ValueError) as error:
        raise NativePostSkinError("Unsupported native output category layout") from error
    parents = bind_subdivision_sources(evidence, vertices, uv, triangles)
    generated = build_native_buffers(evidence, parents, triangles)
    generated["draw_ib"] = draw_ib.lower()
    generated["output_hash"] = output_hash.lower()
    generated["shader_hashes"] = [stage["ShaderHash"] for stage in metadata["Stages"]]
    # Markers must be exact float32 integers. The export owner checks collisions
    # across all generated models before accepting this deterministic marker.
    generated["marker"] = 0x800000 + (int(output_hash, 16) & 0x7fffff)
    return generated


def check_package_runtime(migoto_folder):
    """Reject a missing/incompatible Package before changing export output.

    Runtime support is an explicit dependency of this Mod format. Existing
    standalone helpers are not silently embedded as an alternate execution API.
    This checks the installed contract, not the user's current GPU state.
    """
    root = Path(migoto_folder)
    runtime = root / "Core/NBP/NativePostSkin/Runtime.ini"
    try:
        text = runtime.read_text(encoding="utf-8-sig")
        loader = (root / "d3dx.ini").read_text(encoding="utf-8-sig")
    except OSError as error:
        raise NativePostSkinError("Install NBP-Package with native post-skin API revision 1 before exporting") from error
    if not re.search(r"(?im)^\s*global\s+\$native_postskin_api\s*=\s*1\s*$", text):
        raise NativePostSkinError("NBP native post-skin API revision 1 is required")
    normalized = loader.lower().replace("/", "\\")
    if not re.search(r"(?im)^\s*include\s*=\s*core\\nbp\\nativepostskin\\runtime\.ini\s*$", normalized):
        raise NativePostSkinError("NBP native post-skin Runtime is not included by d3dx.ini")


def emit_native_ini(plan):
    """Return scoped INI lines and relative binary payload names.

    Dispatch counts are generated from actual arrays. Resource names contain
    the DrawIB scope; the Package only receives temporary aliases at each call.
    Mutable frame/shadow storage therefore cannot be overwritten by another
    model before its draw merely because the helpers are shared.
    """
    draw = plan["draw_ib"]
    prefix = "ResourceNative_" + draw + "_"
    names = {
        "Frames": ("extended-frames", "StructuredBuffer", 80),
        "Shadow": ("normal-shadow", "ByteAddressBuffer", 40),
        "PositionCB": ("position-cb", "Buffer", 16),
        "PositionBatch": ("position-batch", "StructuredBuffer", 16),
        "PositionMapping": ("position-mapping", "StructuredBuffer", 32),
        "PositionInfluences": ("position-influences", "StructuredBuffer", 32),
        "PositionMembers": ("position-members", "StructuredBuffer", 4),
        "PositionOffsets": ("position-offsets", "StructuredBuffer", 4),
        "LimitsCB": ("limits-cb", "Buffer", 16),
        "NormalCB": ("normal-cb", "Buffer", 16),
        "NormalTriangles": ("normal-triangles", "StructuredBuffer", 4),
        "NormalTargets": ("normal-targets", "StructuredBuffer", 4),
        "NormalMembers": ("normal-members", "StructuredBuffer", 4),
        "NormalOffsets": ("normal-offsets", "StructuredBuffer", 4),
        "NormalAdjacency": ("normal-adjacency", "StructuredBuffer", 4),
        "NormalAdjacencyOffsets": ("normal-adjacency-offsets", "StructuredBuffer", 4),
    }
    lines, files = [], {}
    for name, (array_name, kind, stride) in names.items():
        filename = "native_" + draw + "_" + array_name + ".buf"
        files[filename] = plan["arrays"][array_name].tobytes()
        lines += ["", "[" + prefix + name + "]", "type = " + kind]
        lines += ["format = R32G32B32A32_UINT"] if kind == "Buffer" else ["stride = " + str(stride)]
        lines += ["filename = Buffers\\" + filename]
    capture = "CommandListNative_" + draw + "_CaptureBones"
    lines += ["", "[" + prefix + "Bones]", "", "[" + capture + "]", prefix + "Bones = ref cs-t2"]
    calls = [
        ("DeformNative", ["Bones", "Frames", "PositionCB", "PositionBatch", "PositionMapping", "PositionInfluences", "PositionMembers", "PositionOffsets"], "frame_dispatch"),
        ("RecalculateNormals", ["Shadow", "LimitsCB", "NormalCB", "NormalTriangles", "NormalTargets", "NormalMembers", "NormalOffsets", "NormalAdjacency", "NormalAdjacencyOffsets"], "normal_dispatch"),
    ]
    for index, (command, resources, dispatch) in enumerate(calls):
        lines += ["", "[ShaderOverrideNative_" + draw + "_" + command + "]", "hash = " + plan["shader_hashes"][index], "allow_duplicate_hash = true", "if $costume_mods && cs-u0 == " + str(plan["marker"]), "  if $\\NBPv1\\native_postskin_api == 1"]
        lines += ["    Resource\\NBPv1\\" + name + " = ref " + prefix + name for name in resources]
        lines += ["    $\\NBPv1\\vertex_dispatch = " + str(plan["vertex_dispatch"]), "    $\\NBPv1\\" + dispatch + " = " + str(plan[dispatch]), "    run = CommandList\\NBPv1\\" + command, "  endif", "endif"]
    return lines, files, capture
