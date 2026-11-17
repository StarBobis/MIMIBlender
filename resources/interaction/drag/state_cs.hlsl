// Single-thread, once-per-frame controller. Picking arrives from the preceding
// rendered frame. Persistent state remains entirely on the GPU.
Texture2D<float4> Snapshot0 : register(t45);
Texture2D<float4> Snapshot1 : register(t46);
Texture2D<float4> Snapshot2 : register(t47);
Texture1D<float4> IniParams : register(t120);
RWStructuredBuffer<float4> State : register(u6);
// 0/1: region0 offset/velocity; 2/3: region1 offset/velocity
// 4: grabbed region(1/2/0), preceding held, initialized, last time
// 5: cursor origin.xy, pending confirmation attempts, flip at press
// 6/7: rest-space Jacobian X/Y; 8: initial offset

void Spring(inout float3 x, inout float3 velocity, float3 target,
            float dt, float omega, float damping)
{
    float3 displacement = x - target;
    if (damping < .999)
    {
        float frequency = omega * sqrt(1 - damping*damping);
        float angle = frequency * dt;
        float decay = exp(-damping * omega * dt);
        float c = cos(angle), s = sin(angle) / frequency;
        x = target + decay * (displacement*c + (velocity + damping*omega*displacement)*s);
        velocity = decay * (velocity*c - (damping*omega*velocity + omega*omega*displacement)*s);
    }
    else if (damping > 1.001)
    {
        float root = sqrt(damping*damping - 1);
        float r1 = -omega * (damping-root), r2 = -omega * (damping+root);
        float3 a = (velocity-r2*displacement)/(r1-r2), b = displacement-a;
        float e1 = exp(r1*dt), e2 = exp(r2*dt);
        x = target + a*e1 + b*e2;
        velocity = r1*a*e1 + r2*b*e2;
    }
    else
    {
        float decay = exp(-omega*dt);
        float3 c = velocity + omega*displacement;
        x = target + (displacement+c*dt)*decay;
        velocity = (velocity-omega*c*dt)*decay;
    }
}

float3 Limit(float3 value, float maximum)
{
    float magnitude = length(value);
    return value * min(1.0, maximum/max(magnitude, 1e-12));
}

[numthreads(1,1,1)]
void main(uint3 id : SV_DispatchThreadID)
{
    float4 interaction = IniParams[248]; // sensitivity, held, enabled, DRAG=0/HIT=1
    float4 settings = IniParams[247];    // time, max distance, frequency Hz, damping
    float2 cursor = IniParams[246].xy;   // scene UV, same convention as picker
    if (IniParams[246].z > .5) cursor.y = 1-cursor.y;
    bool held = interaction.y > .5;
    float4 control = State[4];
    float elapsed = settings.x - control.w;
    bool reset = control.z < .5 || elapsed < 0 || elapsed > .25 || interaction.z < .5 || interaction.w > .5;
    if (reset)
    {
        [unroll] for (uint i=0; i<9; ++i) State[i] = 0;
        // A disabled/HIT controller never begins a grab on a still-held button.
        State[4] = float4(0, held ? 1 : 0, 1, settings.x);
        return;
    }
    float dt = clamp(elapsed, 0, .05);
    if (!held)
    {
        control.x = 0;
        State[5].z = 0;
    }
    if (held && control.y < .5)
    {
        // The frame containing this press has not reached the picking draw yet.
        // Try the existing hover immediately, then allow the next two frames to
        // return the hit at this exact press location. Do not acquire arbitrary
        // geometry that the user later moves over while continuing to hold.
        control.x = 0;
        State[5] = float4(cursor, 3, IniParams[246].z);
    }
    if (held && control.x < .5 && State[5].z > .5)
    {
        float4 hit = Snapshot0.Load(int3(0,0,0));
        float4 dx = Snapshot1.Load(int3(0,0,0));
        float4 dy = Snapshot2.Load(int3(0,0,0));
        float4 press = State[5];
        float2 pixelTolerance = 2.0 / max(IniParams[249].yz, float2(1,1));
        bool samePress = all(abs(float2(dx.w,dy.w)-press.xy) <= pixelTolerance)
                      && abs(press.w-IniParams[246].z) < .5;
        uint region = (uint)round(hit.w);
        if (region >= 1 && region <= (uint)IniParams[249].x &&
            samePress &&
            all(isfinite(dx)) && all(isfinite(dy)) &&
            dot(dx.xyz,dx.xyz) > 1e-16 && dot(dy.xyz,dy.xyz) > 1e-16)
        {
            control.x = region;
            State[5] = float4(dx.w,dy.w,0,IniParams[246].z);
            State[6] = float4(dx.xyz,0);
            State[7] = float4(dy.xyz,0);
            State[8] = State[(region-1)*2];
        }
        else
        {
            State[5].z = abs(press.w-IniParams[246].z) < .5 ? max(0,press.z-1) : 0;
        }
    }
    [unroll] for (uint regionIndex=0; regionIndex<2; ++regionIndex)
    {
        float3 offset = State[regionIndex*2].xyz;
        float3 velocity = State[regionIndex*2+1].xyz;
        float3 target = 0;
        if ((uint)control.x == regionIndex+1 && held)
        {
            float2 delta = cursor-State[5].xy;
            target = State[8].xyz + interaction.x * (delta.x*State[6].xyz + delta.y*State[7].xyz);
            target = Limit(target, settings.y);
        }
        Spring(offset,velocity,target,dt,6.28318530718*settings.z,settings.w);
        offset = Limit(offset, settings.y);
        if (!all(isfinite(offset)) || !all(isfinite(velocity))) { offset=0; velocity=0; }
        State[regionIndex*2] = float4(offset,0);
        State[regionIndex*2+1] = float4(velocity,0);
    }
    State[4] = float4(control.x, held ? 1 : 0, 1, settings.x);
}
