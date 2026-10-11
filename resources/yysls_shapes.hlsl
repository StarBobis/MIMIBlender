// YYSLS packed-vertex shape interpolation, adapted from the supplied mod.
// The exporter prepends validated category-local layout constants.
// Opaque words preserve color, UV, padding, and packed normal/position W.
struct VertexAttributes {
    uint words[VERTEX_WORDS];
};

// Keep deltas in float precision until every shape has contributed.
// This avoids order-dependent normal normalization and UNORM quantization.
struct ShapeAccumulation {
    float4 position;
    float4 normal;
};

RWStructuredBuffer<VertexAttributes> output_vertices : register(u5);
RWStructuredBuffer<ShapeAccumulation> accumulated : register(u6);
StructuredBuffer<VertexAttributes> base_vertices : register(t50);
StructuredBuffer<VertexAttributes> shape_vertices : register(t51);
Texture1D<float4> IniParams : register(t120);

// x is the weight; y/z mark the first/last shape dispatch of this DrawIB.
// These flags are written explicitly on every dispatch, including reloads.
#define weight IniParams[88].x
#define first_shape IniParams[88].y
#define last_shape IniParams[88].z

float3 SafeNormal(float3 value, float3 fallback)
{
    // Opposing normals can cancel exactly. Never normalize a zero vector.
    float length_squared = dot(value, value);
    if (length_squared < 1e-12)
        return fallback;
    return value * rsqrt(length_squared);
}

float3 ReadNormal(VertexAttributes vertex)
{
    // NORMAL is UNORM8 data encoding the signed direction in its low bytes.
    uint packed = vertex.words[NORMAL_WORD];
    float3 bytes = float3(packed & 255, (packed >> 8) & 255, (packed >> 16) & 255);
    return SafeNormal(bytes * (2.0 / 255.0) - 1.0, float3(0, 0, 1));
}

uint WriteNormal(float3 normal, uint original)
{
    // Round only once, and preserve the original high byte exactly.
    uint3 bytes = (uint3)(saturate(normal * 0.5 + 0.5) * 255.0 + 0.5);
    return bytes.x | (bytes.y << 8) | (bytes.z << 16) | (original & 0xff000000);
}

float3 ReadPosition(VertexAttributes vertex)
{
#if POSITION_UNORM16
    // Quantized positions use the original shared bounding-box coordinates.
    // Affine decompression commutes with adding full-weight shape deltas.
    uint xy = vertex.words[POSITION_WORD];
    uint zw = vertex.words[POSITION_WORD + 1];
    return float3(xy & 65535, xy >> 16, zw & 65535) / 65535.0;
#else
    return asfloat(uint3(vertex.words[POSITION_WORD], vertex.words[POSITION_WORD + 1], vertex.words[POSITION_WORD + 2]));
#endif
}

void WritePosition(inout VertexAttributes vertex, float3 position)
{
#if POSITION_UNORM16
    // Saturate at the representable bounding box, matching buffer export.
    // POSITION.w is metadata, not a fourth component to interpolate.
    uint3 values = (uint3)(saturate(position) * 65535.0 + 0.5);
    vertex.words[POSITION_WORD] = values.x | (values.y << 16);
    vertex.words[POSITION_WORD + 1] = values.z | (vertex.words[POSITION_WORD + 1] & 0xffff0000);
#else
    vertex.words[POSITION_WORD] = asuint(position.x);
    vertex.words[POSITION_WORD + 1] = asuint(position.y);
    vertex.words[POSITION_WORD + 2] = asuint(position.z);
#endif
}

// Dispatch ceil(vertex_count / 64), rather than one group per vertex.
// Validate every length as a second defense against edited or stale buffers.
[numthreads(64, 1, 1)]
void main(uint3 thread_id : SV_DispatchThreadID)
{
    uint i = thread_id.x;
    uint count, stride, base_count, shape_count, scratch_count;
    output_vertices.GetDimensions(count, stride);
    base_vertices.GetDimensions(base_count, stride);
    shape_vertices.GetDimensions(shape_count, stride);
    accumulated.GetDimensions(scratch_count, stride);
    if (i >= min(count, min(base_count, shape_count)))
        return;
    // A single shape keeps its deltas in registers, so its scratch can be tiny.
    // Multi-key passes need one scratch record for every output vertex.
    if ((first_shape == 0 || last_shape == 0) && i >= scratch_count)
        return;

    // The first key owns initialization; no stale frame can affect this run.
    // Scratch does not alias either immutable input or the animated seed.
    ShapeAccumulation delta;
    if (first_shape != 0)
    {
        delta.position = 0;
        delta.normal = 0;
    }
    else
        delta = accumulated[i];

    // Zero weights keep the complete seed bit-identical, even for packed data.
    // Track influence separately because different nonzero weights can cancel.
    if (weight != 0)
    {
        VertexAttributes base = base_vertices[i];
        VertexAttributes shape = shape_vertices[i];
        delta.position.xyz += (ReadPosition(shape) - ReadPosition(base)) * weight;
        delta.normal.xyz += (ReadNormal(shape) - ReadNormal(base)) * weight;
        delta.normal.w += abs(weight);
    }

    // Intermediate passes only update scratch, never a quantized vertex.
    // A single final write handles both single-key and multi-key blending.
    if (last_shape == 0)
        accumulated[i] = delta;
    else if (delta.normal.w != 0)
    {
        VertexAttributes vertex = output_vertices[i];
        float3 original_normal = ReadNormal(vertex);
        WritePosition(vertex, ReadPosition(vertex) + delta.position.xyz);
        float3 normal = SafeNormal(original_normal + delta.normal.xyz, original_normal);
        vertex.words[NORMAL_WORD] = WriteNormal(normal, vertex.words[NORMAL_WORD]);
        output_vertices[i] = vertex;
    }
}
