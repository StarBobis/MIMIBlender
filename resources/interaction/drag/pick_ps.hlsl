#define MIMI_DRAG_REVERSED_Z 1
#ifndef MIMI_DRAG_REVERSED_Z
#define MIMI_DRAG_REVERSED_Z 1
#endif
Texture2D<float> SceneDepth : register(t103);
struct Input
{
    float4 position : SV_Position;
    float2 weights : TEXCOORD0;
    nointerpolation float3 rest : TEXCOORD1;
    nointerpolation float3 jacobianX : TEXCOORD2;
    nointerpolation float3 jacobianY : TEXCOORD3;
    nointerpolation float2 sampleUV : TEXCOORD4;
};
struct Output
{
    float4 hit : SV_Target0;
    float4 jacobianX : SV_Target1;
    float4 jacobianY : SV_Target2;
};
Output main(Input input)
{
    uint width,height;
    SceneDepth.GetDimensions(width,height);
    if (width == 0 || height == 0 || max(input.weights.x,input.weights.y) < 0.05) discard;
    uint2 pixel = min(uint2(input.sampleUV * float2(width,height)),uint2(width-1,height-1));
    float sceneZ = SceneDepth.Load(int3(pixel,0));
    float z = input.position.z;
    if (!isfinite(z) || !isfinite(sceneZ)) discard;
    // Two units of float-depth tolerance avoid rejecting an equal-depth copy.
    // This does not intentionally allow grabbing through foreground geometry.
    float tolerance = 2e-7;
    bool reversed = MIMI_DRAG_REVERSED_Z != 0;
    if (reversed ? z+tolerance < sceneZ : z-tolerance > sceneZ) discard;
    Output output;
    output.hit = float4(input.rest, input.weights.x >= input.weights.y ? 1 : 2);
    output.jacobianX = float4(input.jacobianX,input.sampleUV.x);
    output.jacobianY = float4(input.jacobianY,input.sampleUV.y);
    return output;
}
