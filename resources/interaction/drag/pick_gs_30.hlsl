// Keep the game's actual VS and its live object/camera transforms. This GS
// only crops its projected triangles to the mouse pixel and adds authored data.
ByteAddressBuffer Indices : register(t100);
ByteAddressBuffer RestPositions : register(t101);
StructuredBuffer<float2> RegionWeights : register(t102);
Texture2D<float> SceneDepth : register(t103);
Texture1D<float4> IniParams : register(t120);
cbuffer DrawParameters : register(b13)
{
    uint FirstIndex;
    int BaseVertex;
    uint VertexCount;
    uint DrawIndexCount;
};
struct VSOutput
{
    float4 unused0 : TEXCOORD200;
    float4 unused1 : TEXCOORD201;
    float4 unused2 : TEXCOORD202;
    float4 unused3 : TEXCOORD203;
    float4 unused4 : TEXCOORD204;
    float4 unused5 : TEXCOORD205;
    float4 unused6 : TEXCOORD206;
    float4 unused7 : TEXCOORD207;
    float4 unused8 : TEXCOORD208;
    float4 unused9 : TEXCOORD209;
    float4 unused10 : TEXCOORD210;
    float4 unused11 : TEXCOORD211;
    float4 unused12 : TEXCOORD212;
    float4 unused13 : TEXCOORD213;
    float4 unused14 : TEXCOORD214;
    float4 unused15 : TEXCOORD215;
    float4 unused16 : TEXCOORD216;
    float4 unused17 : TEXCOORD217;
    float4 unused18 : TEXCOORD218;
    float4 unused19 : TEXCOORD219;
    float4 unused20 : TEXCOORD220;
    float4 unused21 : TEXCOORD221;
    float4 unused22 : TEXCOORD222;
    float4 unused23 : TEXCOORD223;
    float4 unused24 : TEXCOORD224;
    float4 unused25 : TEXCOORD225;
    float4 unused26 : TEXCOORD226;
    float4 unused27 : TEXCOORD227;
    float4 unused28 : TEXCOORD228;
    float4 unused29 : TEXCOORD229;
    float4 position : SV_Position;
};
struct GSOutput
{
    float4 position : SV_Position;
    float2 weights : TEXCOORD0;
    nointerpolation float3 rest : TEXCOORD1;
    nointerpolation float3 jacobianX : TEXCOORD2;
    nointerpolation float3 jacobianY : TEXCOORD3;
    nointerpolation float2 sampleUV : TEXCOORD4;
};

bool BuildTriangle(VSOutput input[3], uint primitive, inout GSOutput vertices[3])
{
    vertices[0] = (GSOutput)0;
    vertices[1] = (GSOutput)0;
    vertices[2] = (GSOutput)0;
    float4 control = IniParams.Load(int2(246, 0));
    if (control.w < 0.5 || !all(isfinite(control)) ||
        any(control.xy < 0) || any(control.xy > 1)) return false;
    uint width, height, indexElements, weightElements, weightStride, restBytes;
    SceneDepth.GetDimensions(width, height);
    Indices.GetDimensions(indexElements);
    indexElements /= 4u;
    RegionWeights.GetDimensions(weightElements, weightStride);
    RestPositions.GetDimensions(restBytes);
    if (width == 0 || height == 0 || primitive >= DrawIndexCount / 3u) return false;
    uint address = FirstIndex + primitive * 3u;
    if (address < FirstIndex || address + 2u >= indexElements) return false;
    float2 sceneUV = float2(control.x, control.z > 0.5 ? 1-control.y : control.y);
    float2 size = float2(width, height);
    float2 samplePixel = min(floor(sceneUV * size), size-1) + 0.5;
    sceneUV = samplePixel / size;
    float2 cursorNDC = float2(sceneUV.x * 2-1, 1-sceneUV.y * 2);
    float3 rest[3] = {float3(0,0,0),float3(0,0,0),float3(0,0,0)};
    float2 weights[3] = {float2(0,0),float2(0,0),float2(0,0)};
    float2 pixel[3] = {float2(0,0),float2(0,0),float2(0,0)};
    float reciprocalW[3] = {0,0,0};
    [unroll] for (uint k=0; k<3; ++k)
    {
        int vertex = (int)Indices.Load((address+k)*4u) + BaseVertex;
        if (vertex < 0 || (uint)vertex >= VertexCount || (uint)vertex >= weightElements ||
            (uint)vertex >= restBytes / 40u || !all(isfinite(input[k].position)) ||
            input[k].position.w <= 1e-7) return false;
        rest[k] = asfloat(RestPositions.Load3((uint)vertex * 40u));
        weights[k] = RegionWeights[vertex];
        if (!all(isfinite(rest[k])) || !all(isfinite(weights[k]))) return false;
        reciprocalW[k] = rcp(input[k].position.w);
        float2 ndc = input[k].position.xy * reciprocalW[k];
        pixel[k] = float2(ndc.x * 0.5+0.5, 0.5-ndc.y * 0.5) * size;
    }
    // Analytical derivative of perspective interpolation q/d at the cursor.
    // No quad derivatives/helper lanes are required on the 1x1 target.
    float2 a = pixel[0]-pixel[2], b = pixel[1]-pixel[2];
    float determinant = a.x*b.y-a.y*b.x;
    if (!isfinite(determinant) || abs(determinant) < 1e-5) return false;
    float2 l0d = float2(b.y,-b.x) / determinant;
    float2 l1d = float2(-a.y,a.x) / determinant;
    float2 relative = samplePixel-pixel[2];
    float3 lambda = float3(dot(l0d,relative), dot(l1d,relative), 0);
    lambda.z = 1-lambda.x-lambda.y;
    float3 dlx = float3(l0d.x,l1d.x,-l0d.x-l1d.x);
    float3 dly = float3(l0d.y,l1d.y,-l0d.y-l1d.y);
    float3 rw = float3(reciprocalW[0],reciprocalW[1],reciprocalW[2]);
    float divisor = dot(lambda,rw);
    if (!isfinite(divisor) || divisor <= 1e-10) return false;
    float3 local = (lambda.x*rw.x*rest[0] + lambda.y*rw.y*rest[1] + lambda.z*rw.z*rest[2]) / divisor;
    float3 qx = dlx.x*rw.x*rest[0] + dlx.y*rw.y*rest[1] + dlx.z*rw.z*rest[2];
    float3 qy = dly.x*rw.x*rest[0] + dly.y*rw.y*rest[1] + dly.z*rw.z*rest[2];
    float3 jacX = (qx-local*dot(dlx,rw)) / divisor * size.x;
    float3 jacY = (qy-local*dot(dly,rw)) / divisor * size.y;
    if (!all(isfinite(local)) || !all(isfinite(jacX)) || !all(isfinite(jacY))) return false;
    [unroll] for (uint corner=0; corner<3; ++corner)
    {
        GSOutput output = (GSOutput)0;
        float4 clipPosition = input[corner].position;
        output.position = float4((clipPosition.xy-cursorNDC*clipPosition.w)*size,
                                 clipPosition.z, clipPosition.w);
        output.weights = saturate(weights[corner]);
        output.rest = local;
        output.jacobianX = jacX;
        output.jacobianY = jacY;
        output.sampleUV = sceneUV;
        vertices[corner] = output;
    }
    return true;
}

[maxvertexcount(3)]
void main(triangle VSOutput input[3], uint primitive : SV_PrimitiveID,
          inout TriangleStream<GSOutput> stream)
{
    GSOutput vertices[3] = {(GSOutput)0,(GSOutput)0,(GSOutput)0};
    if (BuildTriangle(input, primitive, vertices))
    {
        stream.Append(vertices[0]);
        stream.Append(vertices[1]);
        stream.Append(vertices[2]);
        stream.RestartStrip();
    }
}
