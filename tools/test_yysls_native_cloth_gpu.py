"""Compile native cloth VS assets and test their packed decode on D3D11 WARP.

The shader helpers are extracted from the shipped assets. CPU expectations use
struct's signed-word decoding and Python double precision, independently of HLSL.
No game modules or injected loader are loaded by this regression.
"""
import math
from pathlib import Path
import struct
from test_naraka_shapekey_gpu import run
from test_yysls_cloth_shader import compile_shader, dxbc_chunks, signature_elements

ROOT = Path(__file__).resolve().parents[1]


def normalized(values, fallback):
    length = math.sqrt(sum(x*x for x in values))
    return fallback if length < 1e-5 else tuple(x/length for x in values)


def main():
    helpers = []
    for name in ("yysls_cloth_21bcfc.hlsl", "yysls_cloth_shadow.hlsl"):
        path = ROOT / "resources" / name
        code = compile_shader(path)
        assert b"tPositionDeformTex" in code and b"MIMIClothSource" in code
        source = path.read_text(encoding="utf-8")
        helpers.append(source[source.index("float3 MIMINormalize"):source.index("void main(")])
        print("PASS: native cloth VS compiles with simulation and source map:", name)
    assert helpers[0] == helpers[1], "Main and shadow must decode the same normal bits"

    # Both Qinghe variants shift the original input slots after COLOR0.
    # The main shader forwards COLOR0, while shadow keeps its two-component UV.
    for name, main_pass in (("873adf", True), ("f58ef6", False)):
        shader = ROOT / "resources" / f"yysls_cloth_{name}.hlsl"
        code = compile_shader(shader)
        assert b"tPositionDeformTex" in code and b"MIMIClothSource" in code
        signatures = dxbc_chunks(code)
        inputs = signature_elements(signatures[b"ISGN"])
        outputs = signature_elements(signatures[b"OSGN"])
        assert [(e[0], e[4]) for e in inputs] == list(zip((
            "SV_InstanceID", "POSITION", "COLOR", "NORMAL", "TEXCOORD",
            "TANGENT", "BINORMAL", "BLENDWEIGHT", "BLENDINDICES", "SV_VertexID",
        ), range(10)))
        if main_pass:
            assert any(e[0] == "COLOR" and e[4:] == (6, 15) for e in outputs)
        else:
            assert [(e[0], e[1], e[4], e[5]) for e in outputs] == [
                ("SV_Position", 0, 0, 15), ("TEXCOORD", 0, 1, 3), ("TEXCOORD", 1, 2, 15),
            ]
        print("PASS: Qinghe cloth signature and resource bindings:", name)
    # The first normal word is from the supplied capture. Interpreting that word
    # as float produces 1.45e-38, whose numeric integer conversion is zero.
    normal_words = (0x009e3fe9, 0x00ee7cbe, 0x00a9adee, 0x00808080, 0)
    frames = ((32767, 0, 0, 0, 32767, 0), (-32768, 32767, -1, 1, -32768, 0), (0,0,0,0,0,0))
    records=[]
    expected=[]
    for i in range(65):
        bits=normal_words[i % len(normal_words)]
        # Repack in the native layout: T.xy in word x, T.z in y,
        # B.xy in word z and B.z in word w.
        t=frames[i % len(frames)][:3]
        b=frames[i % len(frames)][3:]
        words=struct.pack("<8h",t[0],t[1],t[2],0,b[0],b[1],b[2],0)
        records.append(struct.pack("<4I",bits,0,0,0)+words+bytes(16))
        normal=normalized([((bits >> shift) & 255)-128 for shift in (0,8,16)],(0,1,0))
        tangent=normalized([x/32767 for x in t],(1,0,0))
        binormal=normalized([x/32767 for x in b],(0,0,1))
        expected.extend((*normal,0,*tangent,0,*binormal,0))
    shader=(helpers[0]+"""
struct Record { float4 normal; float4 frame; float4 unused; };
StructuredBuffer<Record> input : register(t50);
RWStructuredBuffer<Record> output : register(u5);
[numthreads(64,1,1)]
void main(uint3 tid : SV_DispatchThreadID) {
  uint count, stride;
  input.GetDimensions(count, stride);
  if (tid.x >= count) return;
  uint4 bits = asuint(input[tid.x].frame);
  Record result;
  result.normal = float4(MIMIDecodeNormal(asuint(input[tid.x].normal.x)), 0);
  result.frame = float4(MIMINormalize(MIMIDecodeSigned16(uint3(bits.x,bits.x >> 16,bits.y)),float3(1,0,0)),0);
  result.unused = float4(MIMINormalize(MIMIDecodeSigned16(uint3(bits.z,bits.z >> 16,bits.w)),float3(0,0,1)),0);
  output[tid.x] = result;
}
""").encode()
    def check(base,shape,seed,result,weights):
        actual=struct.unpack("<"+"f"*len(expected),result)
        assert all(math.isclose(a,b,abs_tol=2e-6) for a,b in zip(actual,expected)), "Packed native frame differs from signed-word oracle"
    data=b"".join(records)
    run(data,data,stride=48,shader_source=shader,result_checker=check)
    print("PASS: GPU packed normal/tangent/binormal, signed boundaries, zero guards and tail vertex")


if __name__ == "__main__":
    main()
