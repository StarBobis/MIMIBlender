// Procedural rest-space directional morph. Always read immutable Rest, never
// last frame's result. The private/native skinning dispatch consumes Result.
ByteAddressBuffer Rest : register(t40);
struct ControlData { float2 weight; float3 gradient0; float3 gradient1; };
StructuredBuffer<ControlData> Controls : register(t41);
StructuredBuffer<float4> State : register(t42);
RWByteAddressBuffer Result : register(u5);

float3 SafeUnit(float3 value, float3 fallback)
{
    float magnitude = dot(value,value);
    return magnitude > 1e-20 && all(isfinite(value)) ? value*rsqrt(magnitude) : fallback;
}

[numthreads(64,1,1)]
void main(uint3 id : SV_DispatchThreadID)
{
    uint count, stride;
    Controls.GetDimensions(count,stride);
    uint vertex = id.x;
    if (vertex >= count) return;
    uint address = vertex*40;
    float3 position = asfloat(Rest.Load3(address));
    float3 normal = asfloat(Rest.Load3(address+12));
    float4 tangent = asfloat(Rest.Load4(address+24));
    ControlData control = Controls[vertex];
    float3 a = State[0].xyz, b = State[2].xyz;
    if ((all(a == 0) && all(b == 0)) ||
        (all(control.weight == 0) && all(control.gradient0 == 0) && all(control.gradient1 == 0)))
    {
        Result.Store4(address,Rest.Load4(address));
        Result.Store4(address+16,Rest.Load4(address+16));
        Result.Store2(address+32,Rest.Load2(address+32));
        return;
    }
    // Columns of d(P')/d(P), with smooth surface weight gradients.
    float3 jx = float3(1,0,0)+a*control.gradient0.x+b*control.gradient1.x;
    float3 jy = float3(0,1,0)+a*control.gradient0.y+b*control.gradient1.y;
    float3 jz = float3(0,0,1)+a*control.gradient0.z+b*control.gradient1.z;
    float3 cofactorX = cross(jy,jz), cofactorY = cross(jz,jx), cofactorZ = cross(jx,jy);
    float determinant = dot(jx,cofactorX);
    float3 transformedNormal = cofactorX*normal.x + cofactorY*normal.y + cofactorZ*normal.z;
    if (determinant < 0) transformedNormal = -transformedNormal;
    float3 unitNormal = SafeUnit(transformedNormal, SafeUnit(normal,float3(0,0,1)));
    float3 transformedTangent = jx*tangent.x + jy*tangent.y + jz*tangent.z;
    transformedTangent -= unitNormal * dot(unitNormal,transformedTangent);
    float3 unitTangent = SafeUnit(transformedTangent, SafeUnit(tangent.xyz,float3(1,0,0)));
    float3 moved = position + a*control.weight.x + b*control.weight.y;
    Result.Store3(address,asuint(moved));
    Result.Store3(address+12,asuint(unitNormal*length(normal)));
    Result.Store4(address+24,asuint(float4(unitTangent*length(tangent.xyz),tangent.w)));
}
