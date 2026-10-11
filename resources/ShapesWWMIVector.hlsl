// WWMI Vector ShapeKey compute shader.
// Interpolates packed R8G8B8A8_SNORM tangent/normal bytes and writes a dynamic Vector buffer.

Texture1D<float4> IniParams : register(t120);

#define ShapeKeyWeight IniParams[88].x
#define Vector4Count IniParams[89].x

Buffer<int> BaseVector : register(t50);
Buffer<int> ShapeKeyVector : register(t51);
RWBuffer<int> OutputVector : register(u5);

float decode_snorm8(int value)
{
    return max(float(value) / 127.0, -1.0);
}

int encode_snorm8(float value)
{
    return int(round(clamp(value, -1.0, 1.0) * 127.0));
}

float3 safe_normalize(float3 value)
{
    float length_sq = dot(value, value);
    if (length_sq < 1e-8) {
        return float3(0.0, 0.0, 1.0);
    }
    return value * rsqrt(length_sq);
}

#ifdef COMPUTE_SHADER

[numthreads(64, 1, 1)]
void main(uint3 thread_id : SV_DispatchThreadID)
{
    uint row = thread_id.x;
    if (row >= uint(Vector4Count)) {
        return;
    }

    uint base_index = row * 4;
    float4 base_value = float4(
        decode_snorm8(BaseVector[base_index + 0]),
        decode_snorm8(BaseVector[base_index + 1]),
        decode_snorm8(BaseVector[base_index + 2]),
        decode_snorm8(BaseVector[base_index + 3])
    );
    float4 target_value = float4(
        decode_snorm8(ShapeKeyVector[base_index + 0]),
        decode_snorm8(ShapeKeyVector[base_index + 1]),
        decode_snorm8(ShapeKeyVector[base_index + 2]),
        decode_snorm8(ShapeKeyVector[base_index + 3])
    );

    float4 output_value = lerp(base_value, target_value, ShapeKeyWeight);
    output_value.xyz = safe_normalize(output_value.xyz);
    output_value.w = ShapeKeyWeight >= 0.5 ? target_value.w : base_value.w;

    OutputVector[base_index + 0] = encode_snorm8(output_value.x);
    OutputVector[base_index + 1] = encode_snorm8(output_value.y);
    OutputVector[base_index + 2] = encode_snorm8(output_value.z);
    OutputVector[base_index + 3] = encode_snorm8(output_value.w);
}

#endif
