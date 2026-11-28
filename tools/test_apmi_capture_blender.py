"""Headless round trip of the APMI 2026-11-26 and 2026-11-28 captures extracted by MMT.

Set APMI_TEST_WORKSPACE to the full Rust extraction. Run Blender with
--background --factory-startup --python-exit-code 1 --python <this file>.
For the 2026-11-28 extraction add -- --posed to select the ten posed snapshots.
For 2026-11-26 set APMI_CAPTURE to replay its captured skin matrices against the UAV.
The generated mod and selection stay in a new directory under the repo's tmp.
"""
import json
import os
from pathlib import Path
import re
import sys
import tempfile

import bpy
import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO.parent))
import MIMIBlender
from MIMIBlender.automation.workspaces import choose_candidates, scan_workspace
from MIMIBlender.blueprint.blueprint_export_helper import BlueprintExportHelper
from MIMIBlender.common.global_config import GlobalConfig
from MIMIBlender.common.mmt_import_helper import MMTImportHelper
from MIMIBlender.ui.ui_func_export import _export_regular_output
from MIMIBlender.ui.ui_func_import_mmt import _create_and_layout_obj_info_nodes, _link_group_to_output


def blend_contributions(path, indices, stride):
    # A rigid record contains the index alone. The other shaders load all the
    # float weights first and then the same number of uint32 bone indices.
    record = np.fromfile(path, "<u4").reshape(-1, stride // 4)[indices]
    width = record.shape[1] // 2
    ids = record[:, width:]
    weights = record[:, :width].copy().view("<f4") if width else np.ones(ids.shape)
    return ids, weights


def verify_skin_dispatches(capture):
    # Validate the interpretation independently of both ends of the round trip.
    # Reproduce each observed dispatch using its own input matrices, then
    # compare every position to the game-produced UAV for the same dispatch.
    widths = {"3b4f1b1749cd3030": 4, "10749e66a6e6de89": 16, "09d91b2eee7e232f": 32}
    counts = []
    for shader, stride in widths.items():
        dispatches = sorted(capture.glob(f"*-cs-t1=*-cs={shader}.buf"))
        counts.append(len(dispatches))
        for blend in dispatches:
            call = blend.name.split("-", 1)[0]

            def slot(name):
                [file] = capture.glob(f"{call}-{name}=*-cs={shader}.buf")
                return np.fromfile(file, "<f4")

            position = slot("cs-t0").reshape(-1, 10)[:, :3]
            ids, weights = blend_contributions(blend, np.arange(len(position)), stride)
            matrices = slot("cs-t2").reshape(-1, 4, 4)
            matrix = np.sum(weights[:, :, None, None] * matrices[ids], axis=1)
            predicted = np.einsum("bi,bij->bj", position, matrix[:, :3, :3]) + matrix[:, 3, :3]
            actual = slot("u0").reshape(-1, 10)[:len(position), :3]
            np.testing.assert_allclose(predicted, actual, atol=1e-6, err_msg=call)
    assert counts == [1, 1, 7], counts


def verify_mesh(record, metadata, output, posed=False):
    source = Path(metadata).parent
    meta = json.loads(Path(metadata).read_text(encoding="utf8"))
    # Compare at referenced triangle corners. Blender can legally split or
    # merge vertices, changing both the IB values and the physical VB order.
    label = record["display_name"]
    gpu = meta["GPU-PreSkinning"]
    prefix = record["draw_ib"] if gpu else label
    index = np.fromfile(source / meta["IndexBufferList"][0]["FileName"], "<u4")
    new_index = np.fromfile(output / (label + "-Index.buf"), "<u4")
    if posed and record["draw_ib"] == "761cc770":
        # Blender validates duplicate faces on import. Compare the retained
        # corners to the source, and pin the exact number of duplicates here.
        tris = index.reshape(-1, 3)
        _, first = np.unique(np.sort(tris, axis=1), axis=0, return_index=True)
        assert len(tris) - len(first) == 40
        index = tris[np.sort(first)].ravel()
    assert len(index) == len(new_index), label

    for buf in meta["CategoryBufferList"]:
        elements = buf["D3D11ElementList"]
        category = elements[0]["Category"]
        stride = sum(int(e["ByteWidth"]) for e in elements)
        old_file = source / buf["FileName"]
        new_file = output / (prefix + "-" + category + ".buf")
        if category == "Blend":
            # Influences may be reordered and a bone may occur in multiple
            # lanes. Compare the effective contribution of every active bone.
            ids, weights = blend_contributions(old_file, index, stride)
            new_ids, new_weights = blend_contributions(new_file, new_index, stride)
            for bones in np.column_stack((ids, new_ids)).T:
                before = np.sum(weights * (ids == bones[:, None]), axis=1)
                after = np.sum(new_weights * (new_ids == bones[:, None]), axis=1)
                np.testing.assert_allclose(before, after, atol=2e-7, err_msg=label)
            continue
        old = np.fromfile(old_file, "u1").reshape(-1, stride)[index]
        new = np.fromfile(new_file, "u1").reshape(-1, stride)[new_index]
        offset = 0
        for element in elements:
            end = offset + int(element["ByteWidth"])
            left = old[:, offset:end].copy()
            right = new[:, offset:end].copy()
            offset = end
            semantic = element["SemanticName"]
            if semantic == "POSITION":
                # Blender applies a pair of Y/Z axis conversions to float32
                # scene coordinates, including the large UI coordinates.
                lhs, rhs = left.view("<f4"), right.view("<f4")
                if posed:
                    # Axis rotations mix coordinates. Bound float32 round-off by
                    # each source position's magnitude, including large UI meshes.
                    scale = np.maximum(np.abs(lhs).max(axis=1, keepdims=True), 1)
                    np.testing.assert_allclose(lhs / scale, rhs / scale, rtol=0, atol=8 * np.finfo("f4").eps, err_msg=label)
                else:
                    np.testing.assert_allclose(lhs, rhs, atol=2e-4, err_msg=label)
            elif category == "Texcoord" and not gpu and element["Format"] in {"R16G16_FLOAT", "R8G8B8A8_UNORM"}:
                np.testing.assert_array_equal(left, right, err_msg=label)
            elif semantic == "TANGENT":
                np.testing.assert_array_equal(left, right, err_msg=label)
            elif semantic == "TEXCOORD" and element["Format"].startswith("R32"):
                np.testing.assert_allclose(left.view("<f4"), right.view("<f4"), atol=1e-5, err_msg=label)
            elif semantic == "NORMAL" and element["Format"] == "R32G32B32_FLOAT":
                # These values are shader payloads that Blender would otherwise normalize.
                payload = ~np.isclose(np.linalg.norm(left.view("<f4"), axis=1), 1.0, atol=0.001)
                np.testing.assert_array_equal(left[payload], right[payload], err_msg=label)


def verify_ini(path, selected, posed):
    contents = path.read_text(encoding="utf-8-sig")
    sections = re.findall(r"^\[([^\]]+)\]", contents, re.M)
    names = {section.lower() for section in sections}
    assert len(sections) == len(names)
    assert sum(name.startswith("commandlistapmidraw_") for name in names) == len(selected)
    assert sum(name.startswith("commandlistapmiskin_") for name in names) == (2 if posed else 9)
    for line in contents.splitlines():
        if "=" in line and not line.lstrip().startswith(";"):
            for resource in re.findall(r"\b(Resource\w+)", line, re.I):
                assert resource.lower() in names, resource
    for ref in re.findall(r"^\s*run = (\w+)", contents, re.M):
        # Hash-textured IBs call the command list supplied by APMI-Package.
        assert ref == "CommandListSkinTexture" or ref in sections, ref
    # This blueprint contains no explicit texture nodes. Verify the call against
    # each component's actual Hash override, including on marked capture copies.
    blocks = {}
    for block in re.split(r"(?=^\[)", contents, flags=re.M):
        header, _, body = block.partition("\n")
        blocks[header] = body.splitlines()
    for record, candidate in selected:
        meta = json.loads(Path(candidate["json"]).read_text(encoding="utf8"))
        marked = any(mark["MarkType"] == "Hash" and "textureoverride_" + mark["MarkHash"].lower() in names
                     for mark in meta.get("TextureMarkUpInfoList", []))
        key = record["submesh"].replace("-", "_")
        lines = blocks["[CommandListAPMIDraw_" + key + "]"]
        if not meta["GPU-PreSkinning"] and "Texcoord" in meta["CategoryHash"]:
            # A split posed mesh has its own local IB and both local vertex streams.
            uv = "Resource_" + key + "_Texcoord"
            assert "vb1 = " + uv in lines and "vb1 = ref ResourceAPMIOldVB1" in lines
            [buffer] = [b for b in meta["CategoryBufferList"] if b["FileName"].endswith("-Texcoord.buf")]
            stride = sum(int(e["ByteWidth"]) for e in buffer["D3D11ElementList"])
            assert "stride = " + str(stride) in blocks["[" + uv + "]"]
        call = "run = CommandListSkinTexture"
        assert lines.count(call) == int(marked), key
        if marked:
            bind = next(i for i, line in enumerate(lines) if line.startswith("ib = Resource"))
            redraw = next(i for i, line in enumerate(lines) if line.strip().startswith("drawindexed"))
            assert bind < lines.index(call) < redraw, key
    for line in contents.splitlines():
        if line.startswith(("filename = ", "cs = ")):
            assert (path.parent / line.split(" = ", 1)[1]).is_file(), line
    # Each live skin shader gets a command-list entry. The indirect UI draw
    # must retain its runtime arguments and use the generated compute shader.
    if posed:
        assert "ShaderOverrideAPMI_09d91b2eee7e232f" in sections
        return
    for shader in ("3b4f1b1749cd3030", "10749e66a6e6de89", "09d91b2eee7e232f"):
        assert "ShaderOverrideAPMI_" + shader in sections
    assert "drawindexedinstancedindirect = ResourceAPMIArgs, 0" in contents
    assert "draw_type == 6 && indirect_offset == 0" in contents


def main():
    posed = "--posed" in sys.argv
    if not posed and os.environ.get("APMI_CAPTURE"):
        verify_skin_dispatches(Path(os.environ["APMI_CAPTURE"]))
    MIMIBlender.register()
    root, model, records, _ = scan_workspace(os.environ["APMI_TEST_WORKSPACE"])
    requested = {}
    if posed:
        # Each repeated component has a posed CPU result and a GPU skin-input result.
        for r in records:
            if len(r["choices"]) > 1:
                [cpu] = [c for c in r["choices"] if c["type"].startswith("CPU_")]
                requested[r["submesh"]] = cpu["type"]
        assert len(requested) == 10
    selected = choose_candidates(root, records, "APMI", requested)
    assert len(selected) == (80 if posed else 199)
    # Use the add-on's normal workspace selection, object nodes and export
    # path. Isolate all test artifacts from both the user's Mods and capture.
    tmp = REPO / "tmp"
    tmp.mkdir(exist_ok=True)
    dest = Path(tempfile.mkdtemp(prefix="apmi-", dir=tmp))
    selection = dest / "selection.json"
    selection.write_text(json.dumps({r["submesh"]: c["type"] for r, c in selected}))
    GlobalConfig._automation_override = {
        "logic": "APMI", "workspace_name": "APMI", "workspace": str(root),
        "output": str(dest), "import_selection": str(selection),
    }
    GlobalConfig.logic_name = GlobalConfig.gamename = GlobalConfig.workspacename = "APMI"

    imported = {}
    for record, candidate in selected:
        obj = MMTImportHelper.create_mesh_from_json(candidate["json"], import_collection=bpy.context.scene.collection)
        assert obj is not None and len(obj.data.polygons), record["submesh"]
        obj.name = record["display_name"]
        imported[record["submesh"]] = (obj, obj.name)

    # Link real object-info nodes so shared IBs go through the same native
    # grouping and buffer concatenation as an interactive Generate Mod action.
    tree = bpy.data.node_groups.new("APMI capture test", "MIMIBlueprintTreeType")
    BlueprintExportHelper.set_tree_submesh_names([v[1] for v in imported.values()], tree=tree)
    group = tree.nodes.new("MIMINode_Object_Group")
    _create_and_layout_obj_info_nodes(tree, group, imported, model)
    output = tree.nodes.new("MIMINode_Result_Output")
    _link_group_to_output(tree, group, output)
    BlueprintExportHelper.set_runtime_blueprint_tree(tree)
    [ini] = _export_regular_output(tree, bpy.context, output, "APMI.ini")
    verify_ini(Path(ini), selected, posed)
    for record, candidate in selected:
        verify_mesh(record, candidate["json"], dest / "Buffers", posed)
    print(f"APMI capture round trip passed for {len(selected)} components. {ini}")


if __name__ == "__main__":
    main()
