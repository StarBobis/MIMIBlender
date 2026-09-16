// Position-only shape accumulation for an explicit 12-byte layout.
// Inputs contain absolute full-weight shapes. Keep the reference immutable,
// even when the output accumulator starts from a time-switched frame.
RWStructuredBuffer<float3> output_positions : register(u5);
StructuredBuffer<float3> base_positions : register(t50);
StructuredBuffer<float3> shape_positions : register(t51);
Texture1D<float4> IniParams : register(t120);

// One group handles 64 vertices. The host uses ceil(vertex_count / 64),
// so the final partial group must guard every read and write.
// GetDimensions avoids consuming another shared IniParams component.
[numthreads(64, 1, 1)]
void main(uint3 thread_id : SV_DispatchThreadID)
{
    uint count, stride;
    output_positions.GetDimensions(count, stride);
    if (thread_id.x >= count)
        return;
    // Resetting the output from the seed before dispatch prevents temporal
    // accumulation; multiple shape keys may then add their independent deltas.
    uint i = thread_id.x;
    output_positions[i] += (shape_positions[i] - base_positions[i]) * IniParams[88].x;
}
