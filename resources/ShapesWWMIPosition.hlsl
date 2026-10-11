// WWMI position-only ShapeKey compute shader.
// Applies one full target Position buffer to a dynamic Position RWBuffer.

Texture1D<float4> IniParams : register(t120);

#define ShapeKeyWeight IniParams[88].x
#define FloatCount IniParams[89].x

Buffer<float> BasePosition : register(t50);
Buffer<float> ShapeKeyPosition : register(t51);
RWBuffer<float> OutputPosition : register(u5);

#ifdef COMPUTE_SHADER

[numthreads(64, 1, 1)]
void main(uint3 thread_id : SV_DispatchThreadID)
{
    uint index = thread_id.x;
    if (index >= uint(FloatCount)) {
        return;
    }

    float base_value = BasePosition[index];
    float shapekey_value = ShapeKeyPosition[index];
    OutputPosition[index] += (shapekey_value - base_value) * ShapeKeyWeight;
}

#endif
