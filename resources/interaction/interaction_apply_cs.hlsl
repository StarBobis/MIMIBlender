// Generic interaction deformation for 3Dmigoto.
//
// The shader pulls named regions of a mesh along a direction and keeps the
// lighting correct while it does so.
//
// Input slots:
//   t40  the immutable bind pose, read as raw bytes
//   t41  the per-vertex control data, one structured record per vertex
//   t42  the runtime state, one float4 per slot
//   u5   the deformed vertex buffer, written as raw bytes
//
// The control record of a vertex holds the weight of the vertex in each
// region and the spatial gradient of that weight.  The gradient is what
// turns a rigid translation into a smooth stretch: the shader builds the
// Jacobian of the deformation from it and re-derives the normal and the
// tangent from that Jacobian, so the surface keeps shading correctly.
//
// The bind pose is never modified, so the deformation cannot accumulate
// across frames: every dispatch starts from the same input.

ByteAddressBuffer Rest : register(t40);

struct ControlData
{
    float2 weight;
    float3 gradient0;
    float3 gradient1;
};

StructuredBuffer<ControlData> Controls : register(t41);
StructuredBuffer<float4> State : register(t42);
RWByteAddressBuffer Result : register(u5);

// The byte size of one vertex: three float3 plus one float4.
static const uint VERTEX_STRIDE = 40;

// Return the normalized value, or the fallback when it cannot be trusted.
float3 SafeUnit(float3 value, float3 fallback)
{
    float magnitude = dot(value, value);
    bool usable = magnitude > 1e-20 && all(isfinite(value));
    return usable ? value * rsqrt(magnitude) : fallback;
}

[numthreads(64, 1, 1)]
void main(uint3 id : SV_DispatchThreadID)
{
    uint controlCount, controlStride;
    Controls.GetDimensions(controlCount, controlStride);

    uint vertex = id.x;
    if (vertex >= controlCount)
    {
        return;
    }

    uint address = vertex * VERTEX_STRIDE;
    float3 position = asfloat(Rest.Load3(address));
    float3 normal = asfloat(Rest.Load3(address + 12));
    float4 tangent = asfloat(Rest.Load4(address + 24));

    ControlData control = Controls[vertex];

    // The first region owns the first state slot, the second region the
    // third one.  Each slot holds the current pull of that region.
    float3 pull0 = State[0].xyz;
    float3 pull1 = State[2].xyz;

    bool noPull = (all(pull0 == 0) && all(pull1 == 0));
    bool noControl = (all(control.weight == 0)
                      && all(control.gradient0 == 0)
                      && all(control.gradient1 == 0));
    if (noPull || noControl)
    {
        // Nothing moves, so the bind pose is copied through unchanged.
        Result.Store4(address, Rest.Load4(address));
        Result.Store4(address + 16, Rest.Load4(address + 16));
        Result.Store2(address + 32, Rest.Load2(address + 32));
        return;
    }

    // The columns of the Jacobian of the deformation.  A pull along a
    // direction stretches the surface where the weight changes fastest.
    float3 columnX = float3(1, 0, 0) + pull0 * control.gradient0.x + pull1 * control.gradient1.x;
    float3 columnY = float3(0, 1, 0) + pull0 * control.gradient0.y + pull1 * control.gradient1.y;
    float3 columnZ = float3(0, 0, 1) + pull0 * control.gradient0.z + pull1 * control.gradient1.z;

    // The cofactor matrix is the transpose of the inverse, so it turns
    // the normal correctly without needing the inverse itself.
    float3 cofactorX = cross(columnY, columnZ);
    float3 cofactorY = cross(columnZ, columnX);
    float3 cofactorZ = cross(columnX, columnY);
    float determinant = dot(columnX, cofactorX);

    float3 transformedNormal = cofactorX * normal.x + cofactorY * normal.y + cofactorZ * normal.z;
    if (determinant < 0)
    {
        transformedNormal = -transformedNormal;
    }
    float3 unitNormal = SafeUnit(transformedNormal, SafeUnit(normal, float3(0, 0, 1)));

    float3 transformedTangent = columnX * tangent.x + columnY * tangent.y + columnZ * tangent.z;
    transformedTangent -= unitNormal * dot(unitNormal, transformedTangent);
    float3 unitTangent = SafeUnit(transformedTangent, SafeUnit(tangent.xyz, float3(1, 0, 0)));

    // The vertex moves along the pull, scaled by its own weight.
    float3 moved = position + pull0 * control.weight.x + pull1 * control.weight.y;

    Result.Store3(address, asuint(moved));
    Result.Store3(address + 12, asuint(unitNormal * length(normal)));
    Result.Store4(address + 24, asuint(float4(unitTangent * length(tangent.xyz), tangent.w)));
}
