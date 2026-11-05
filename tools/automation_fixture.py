"""Create a tiny native-format fixture for visible automation regression tests.

Only these synthetic source bytes are generated. All model import and graph
creation remain the production add-on code, and generated files stay under tmp.
The fixture contains two triangles with normals, tangents, UVs and skin weights.
"""
# Fixture identity:
# - Each caller provides an exclusive directory under repository tmp.
# - Source metadata follows the shipped SubmeshJson contract.
# - VertexCount zero tests native inference from buffer lengths.
# - IndexCount records the source component's original draw range.
# - Position, Texcoord and Blend category hashes are deterministic test values.
# - Every vertex has one numeric bone influence with unit weight.
# - No game binary, protected process or original capture is loaded.
# - Files are written exclusively, never over existing source assets.
# - The returned workspace path is an explicit absolute path.
# - Tests hash these files before/after actions to detect accidental source writes.
# - The layout exercises ordinary LOD/component/type discovery.
# - A duplicate candidate can be added by a test to verify ambiguity rejection.
# - Broken metadata can be added by a test without changing an original fixture.
# - This helper does not import bpy or create a Blender scene.
import hashlib
import json
from pathlib import Path
import struct


TYPE_NAME = "GPU_P12_N12_TA16_BW16_BI16_T8_"
FOLDER_NAME = "12345678-6-0"


def element(name, fmt, width, category, slot):
    """Build the same element fields that production source JSON declares."""
    return {"SemanticName": name, "SemanticIndex": 0, "Format": fmt, "ByteWidth": width,
            "Category": category, "ExtractSlot": slot, "ExtractTechnique": "pointlist"}


def write_native_workspace(folder):
    """Write one inert synthetic component, using exclusive file creation."""
    root = Path(folder).resolve()
    target = root / "LOD0" / FOLDER_NAME / ("TYPE_" + TYPE_NAME)
    target.mkdir(parents=True, exist_ok=False)
    coordinates = [(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]
    position = b"".join(struct.pack("<10f", *(point + (0, 0, 1, 1, 0, 0, 1))) for point in coordinates)
    texcoord = b"".join(struct.pack("<2f", float(index % 2), float(index // 3)) for index in range(6))
    blend = b"".join(struct.pack("<4f4I", 1, 0, 0, 0, 0, 0, 0, 0) for index in range(6))
    index = struct.pack("<6I", 0, 1, 2, 3, 4, 5)
    buffers = {FOLDER_NAME + "-position.buf": position, FOLDER_NAME + "-texcoord.buf": texcoord,
               FOLDER_NAME + "-blend.buf": blend, FOLDER_NAME + ".ib": index}
    for name, data in buffers.items():
        with (target / name).open("xb") as handle:
            handle.write(data)
    groups = [
        ("position", "Position", [element("POSITION", "R32G32B32_FLOAT", 12, "Position", "cs-t0"),
                                  element("NORMAL", "R32G32B32_FLOAT", 12, "Position", "cs-t0"),
                                  element("TANGENT", "R32G32B32A32_FLOAT", 16, "Position", "cs-t0")]),
        ("texcoord", "Texcoord", [element("TEXCOORD", "R32G32_FLOAT", 8, "Texcoord", "vb1")]),
        ("blend", "Blend", [element("BLENDWEIGHTS", "R32G32B32A32_FLOAT", 16, "Blend", "cs-t1"),
                            element("BLENDINDICES", "R32G32B32A32_UINT", 16, "Blend", "cs-t1")]),
    ]
    metadata = {"GamePreset": "PGR", "WorkGameType": TYPE_NAME, "GPU-PreSkinning": True,
                "VertexLimitVB": "12345678", "VertexCount": 0, "IndexOffset": 0, "IndexCount": 6,
                "CategoryHash": {"Position": "11111111", "Texcoord": "22222222", "Blend": "33333333"},
                "CategoryDrawCategoryMap": {name: name for name in ("Position", "Texcoord", "Blend")},
                "IndexBufferList": [{"FileName": FOLDER_NAME + ".ib", "DXGI_FORMAT": "DXGI_FORMAT_R32_UINT"}],
                "CategoryBufferList": [{"FileName": FOLDER_NAME + "-" + suffix + ".buf", "Type": "Normal",
                                        "D3D11ElementList": elements} for suffix, category, elements in groups]}
    with (target / (FOLDER_NAME + ".json")).open("x", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2)
    return root


def source_hashes(root):
    """Hash all test source files independently of the importer's stat checks."""
    root = Path(root)
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob("*") if path.is_file()}
