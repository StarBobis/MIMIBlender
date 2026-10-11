// **** SHAPEKEYS SHADER ****
// By: Cybertron, SinsOfSeven

struct VertexAttributes {
    float3 position;
    float3 normal;
    float4 tangent;
};

RWStructuredBuffer<VertexAttributes> rw_buffer : register(u5);
StructuredBuffer<VertexAttributes> base : register(t50);
StructuredBuffer<VertexAttributes> shapekey : register(t51);

Texture1D<float4> IniParams : register(t120);
#define key IniParams[88].x

// Use practical work groups instead of one group per vertex. D3D11 limits
// Dispatch.x to 65535 groups, so the old layout failed on large meshes.
// The host dispatches ceil(vertex_count / 64) and guards the tail below.
[numthreads(64, 1, 1)]
void main(uint3 threadID : SV_DispatchThreadID)
{
    uint i = threadID.x;
    // Query the actual output length so the final partial group is safe.
    // Shape and reference lengths are validated by the export pipeline.
    uint count, stride;
    rw_buffer.GetDimensions(count, stride);
    if (i >= count)
        return;
    // Keep base immutable: an animated seed belongs only in rw_buffer.
    // Otherwise weight=1 would cancel the position-frame deformation.
    VertexAttributes diff;
    diff.position = shapekey[i].position - base[i].position;
    diff.normal = shapekey[i].normal - base[i].normal;
    diff.tangent = shapekey[i].tangent - base[i].tangent;
    rw_buffer[i].position += diff.position*key;
    rw_buffer[i].normal += diff.normal*key;
    rw_buffer[i].tangent += diff.tangent*key;
}