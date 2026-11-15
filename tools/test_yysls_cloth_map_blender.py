"""Native cloth provenance regression in a disposable Blender process.

Run blender --background --factory-startup --python-exit-code 1 --python this_file.
Optional -- --capture <FrameAnalysis root> exercises the user's real mesh.
No live Mod, installed addon, or saved scene is modified by this test.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import sys
from unittest.mock import patch
import bpy
import numpy as np

# Reuse the production import setup without registering the addon UI.
spec = importlib.util.spec_from_file_location("blend_fixture", Path(__file__).with_name("test_yysls_blend.py"))
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)
from yysls_blend_test.common.yysls_cloth_map import store_source, export_map, pack_map, merge_sources, recover_source_ids, TABLE


def expect_failure(action):
    # Unsupported provenance must never fall back to guessed simulation IDs.
    try:
        action()
    except ValueError:
        return
    raise AssertionError("Expected explicit provenance failure")


def synthetic():
    obj = f.triangle()
    store_source(obj, [(0,0,0), (1,0,0), (0,1,0)], 7)
    obj.data.vertices[0].co.x = 0.25
    table = merge_sources([obj])
    assert table["7"] == [0,0,0]
    # Reordered output and UV splits must retain exact reference IDs/positions.
    result = export_map(obj, obj.data, {0:2, 1:0, 2:1, 3:0}).reshape(-1,16).view("<u4")
    assert result[:,3].tolist() == [9,7,8,7]
    assert result[1,:3].view("<f4").tolist() == [0,0,0]
    # Interpolation of an immutable reference is not a supported source point.
    expect_failure(lambda: pack_map([7], [[0.5,0,0]], table, [0]))
    expect_failure(lambda: pack_map([-1], [[0,0,0]], table, [0]))
    expect_failure(lambda: merge_sources([f.triangle()]))
    # A legacy triangle can be recovered without assuming vertex numbering.
    refs = np.array([(0,0,0),(1,0,0),(0,1,0)],dtype=np.float32)
    uvs = np.array([(0,0),(1,0),(0,1)],dtype=np.float32)
    ids = recover_source_ids(refs[[2,0,1]], [[0,2,1]], [uvs[[2,1,0]]], refs, uvs, [[0,1,2]])
    assert ids.tolist() == [2,0,1]
    # Duplicated identical source triangles are ambiguous and must be refused.
    expect_failure(lambda: recover_source_ids(refs, [[2,1,0]], [uvs[[2,1,0]]],
        np.vstack([refs,refs]), np.vstack([uvs,uvs]), [[0,1,2],[3,4,5]]))
    # Actual evaluated modifiers must preserve valid attributes or fail loudly.
    mod = obj.modifiers.new("subdivide", "SUBSURF")
    mod.levels = 1
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).to_mesh()
    expect_failure(lambda: export_map(obj, evaluated, {i:i for i in range(len(evaluated.loops))}))
    print("PASS: edits, reordered/split output, missing IDs and subdivision rejection")


def capture(root):
    # Read exact native records; no geometric matching is used for source IDs.
    ctx = next(root.glob("ctx-*/000039-vb0*.buf")).parent
    raw = lambda slot: next(ctx.glob("000039-vb"+str(slot)+"*.buf")).read_bytes()
    a = np.frombuffer(raw(0), dtype=[("POSITION","<f4",3),("NORMAL","u1",4),("TEXCOORD","<f4",2)])
    t = np.frombuffer(raw(1), dtype=[("TANGENT","<i2",4),("BINORMAL","<i2",4)])
    b = np.frombuffer(raw(2), dtype=[("BLENDWEIGHT","u1",4),("BLENDINDICES","u1",4)])
    indices = np.frombuffer(next(ctx.glob("000039-ib*.buf")).read_bytes(), dtype="<u2").astype(np.int64)
    elements=[]
    for slot, category, fields in [(0,"Position",[("POSITION","R32G32B32_FLOAT",12),("NORMAL","R8G8B8A8_UNORM",4),("TEXCOORD","R32G32_FLOAT",8)]),(1,"Texcoord",[("TANGENT","R16G16B16A16_SNORM",8),("BINORMAL","R16G16B16A16_SNORM",8)]),(2,"Blend",[("BLENDWEIGHT","R8G8B8A8_UNORM",4),("BLENDINDICES","R8G8B8A8_UINT",4)])]:
        for name,fmt,width in fields:
            elements.append(dict(SemanticName=name,SemanticIndex="0",Format=fmt,ByteWidth=str(width),ExtractSlot="vb"+str(slot),Category=category,DrawCategory=category))
    gt=f.D3D11GameType.from_submesh_json_dict({"WorkGameType":"native_cloth_fixture","CategoryBufferList":[{"D3D11ElementList":elements}]})
    data={name:array[name].copy() for array in (a,t,b) for name in array.dtype.names}
    with patch.object(f.MeshCreateHelper,"create_bsdf_with_diffuse_linked",lambda **kw: None):
        obj=f.MeshCreateHelper.create_mesh_object(mesh_name="cloth_capture",source_path=str(root/"fixture.json"),logic_name=f.LogicName.YYSLS,gametypename="native_cloth_fixture",elements=gt.D3D11ElementList,vb_data=data,ib_data=indices,vb_vertex_count=len(a),ib_count=len(indices),ib_polygon_count=len(indices)//3)
    # Preserve topology while editing the reference shape, then use real packing.
    for vertex in obj.data.vertices:
        vertex.co.x += 0.0125
    # Match SubMeshModel's actual Y-up export transform before packing.
    import math
    obj.rotation_euler[0] = -math.pi / 2
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    result=f.ExportUtils.build_unity_obj_buffer_result(obj,gt)
    payload=result.category_buffer_dict["YYSLSClothMap"].reshape(-1,16).view("<u4")
    output=np.frombuffer(result.category_buffer_dict["Position"].tobytes(),dtype=a.dtype)
    assert len(payload)==len(output)
    refs=a["POSITION"][payload[:,3]]
    assert np.array_equal(payload[:,:3].copy().view("<f4"),refs)
    print("edit delta bounds", np.min(output["POSITION"]-refs,axis=0),np.max(output["POSITION"]-refs,axis=0))
    assert np.allclose(output["POSITION"]-refs,[0.0125,0,0],atol=1e-6)
    assert len(result.ib)==len(indices)
    print("PASS: real capture",len(a),"source vertices ->",len(payload),"exported vertices; reference IDs and edit offsets agree")


if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--capture",type=Path)
    args=parser.parse_args(sys.argv[sys.argv.index("--")+1:] if "--" in sys.argv else [])
    bpy.utils.register_class(f.MIMIGlobalProperties)
    bpy.types.Scene.mimi_global_properties=bpy.props.PointerProperty(type=f.MIMIGlobalProperties)
    f.GlobalConfig.logic_name=f.LogicName.YYSLS
    synthetic()
    if args.capture:
        capture(args.capture)
