Texture1D<float4> IniParams : register(t120);
Texture2D<float4> Hit : register(t45);
StructuredBuffer<float4> State : register(t42);

// Five-by-five diagnostic glyphs: K A H P V G, followed by D / H for mode.
// K = held key; A = deformation applied; H = object draw hook;
// P = expected main PS+VS pair; V = native VS position ABI; G = pick submitted.
static const uint GlyphRows[50] = {
    17,18,28,18,17, 14,17,31,17,17, 17,17,31,17,17,
    30,17,30,16,16, 17,17,17,10,4, 14,16,23,17,14,
    30,17,17,17,30, 31,4,4,4,31,
    31,16,30,16,31, 30,17,30,18,17
};
static const uint DigitRows[55] = {
    14,17,17,17,14, 4,12,4,4,14, 14,1,14,16,31,
    30,1,14,1,30, 18,18,31,2,2, 31,16,30,1,30,
    14,16,30,17,14, 31,1,2,4,4, 14,17,14,17,14,
    14,17,15,1,14, 0,0,14,0,0
};
static const uint DecimalPowers[8] = {1,10,100,1000,10000,100000,1000000,10000000};
bool Glyph(uint glyph, float2 pixel)
{
    int2 cell = int2(floor(pixel*.5));
    if (any(cell < 0) || any(cell >= 5)) return false;
    return (GlyphRows[glyph*5+(uint)cell.y] & (1u << (4-cell.x))) != 0;
}
bool Number(float value, float2 pixel, uint width)
{
    int character = (int)floor(pixel.x/12);
    if (character < 0 || character >= (int)width) return false;
    int2 cell = int2(floor(float2(pixel.x-character*12,pixel.y)*.5));
    if (any(cell < 0) || any(cell >= 5)) return false;
    uint digit = 10;
    // Markers are exact non-negative integer values below 2^24. Invalid
    // values use dashes; the two-character ABI field explicitly supports -1.
    if (width == 2 && value == -1)
        digit = character == 0 ? 10u : 1u;
    else if (isfinite(value) && value >= 0 && value < 100000000)
        digit = ((uint)round(value) / DecimalPowers[width-1-(uint)character]) % 10u;
    return (DigitRows[digit*5+(uint)cell.y] & (1u << (4-cell.x))) != 0;
}

float4 main(float4 position : SV_Position, float2 uv : TEXCOORD0) : SV_Target0
{
    float2 p = (uv-IniParams[246].xy)*IniParams[249].yz;
    float4 core = IniParams[250];
    float4 stages = IniParams[251];
    // Only expand the HUD when the object hook ran but the exact shader pair
    // or VS signature gate failed. Normal interaction keeps the compact strip.
    if (stages.x > .5 && (stages.y < .5 || stages.z < .5))
    {
        float2 diagnostic = p-float2(-57,29);
        if (all(diagnostic >= float2(-2,-1)) && all(diagnostic <= float2(115,40)))
        {
            uint row = (uint)clamp(floor(diagnostic.y/14),0,2);
            float2 local = diagnostic-float2(0,row*14);
            float4 values = IniParams[252];
            uint label = row == 0 ? 4u : row == 1 ? 8u : 9u;
            float value = row == 0 ? values.x : row == 1 ? values.y : values.z;
            if (Glyph(label,local) || Number(value,local-float2(18,0),row == 2 ? 2u : 8u))
                return float4(1,.85,.4,.98);
            return float4(.02,.02,.02,.75);
        }
    }
    float2 status = p-float2(-41,-25);
    if (all(status >= float2(-1,-1)) && all(status <= float2(82,11)))
    {
        uint column = (uint)clamp(floor(status.x/14),0,5);
        bool on = column == 0 ? core.z > .5 : column == 1 ? core.y > .5 :
                  column == 2 ? stages.x > .5 : column == 3 ? stages.y > .5 :
                  column == 4 ? stages.z > .5 : stages.w > .5;
        if (Glyph(column, status-float2(column*14,0)))
            return float4(on ? float3(.2,1,.45) : float3(.55,.55,.55),.95);
        return float4(.02,.02,.02,.65);
    }
    float2 modeLabel = p-float2(-5,13);
    if (Glyph(core.w > .5 ? 2u : 6u,modeLabel))
        return float4(core.w > .5 ? float3(.15,.8,1) : float3(.9,.9,.9),.95);
    float ring = abs(length(p)-7);
    bool mark = ring < 1.25 || (abs(p.x)<.8 && abs(p.y)<3.5) || (abs(p.y)<.8 && abs(p.x)<3.5);
    clip(mark ? 1 : -1);
    float region = Hit.Load(int3(0,0,0)).w;
    float3 color = float3(.8,.8,.8);
    if (region > .5) color = float3(.1,1,.35);
    if (State[5].z > .5 && State[4].x < .5) color = float3(.9,.3,1);
    if (State[4].x > .5) color = float3(1,.65,.05);
    if (IniParams[248].w > .5 && region > .5) color = float3(.15,.8,1);
    return float4(color,.85);
}
