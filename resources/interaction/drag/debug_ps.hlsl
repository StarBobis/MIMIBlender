Texture1D<float4> IniParams : register(t120);
Texture2D<float4> Hit : register(t45);
StructuredBuffer<float4> State : register(t42);

// Prebaked labels: key, deformation, draw, pass, position, picking,
// drag mode, actual marker, expected marker and position output slot.
// BEGIN HUD GLYPHS
static const uint GlyphRows[160] = {
    // key
    0x20402010u,0x20202010u,0x27fe677eu,0xfc027912u,0x2442c2ffu,0x20c0fc12u,0x2080277eu,0x37fe2112u,0xe108f9feu,0x23082510u,0x239027feu,0x20f02a10u,0x20703390u,0x238c64ffu,0xec020800u,0x00000000u,
    // deform
    0x00020180u,0x3f8400c0u,0x1118ffffu,0x11300220u,0x11611228u,0x11022224u,0x7fec4222u,0x11188001u,0x11313ff8u,0x11020810u,0x11040660u,0x21180380u,0x21300ef0u,0x4160f00fu,0x00000000u,0x00000000u,
    // draw
    0x40400000u,0xc0c04804u,0x81a0ffa4u,0x91308824u,0x22190824u,0xe40dffa4u,0x49fe0824u,0xc0000824u,0x8000ff24u,0xf7fc8924u,0x00808924u,0x01208904u,0x72108f04u,0x8408083cu,0x0ff80000u,0x00040000u,
    // pass
    0x40004108u,0x27fc2090u,0x301837feu,0x13301040u,0x01c00040u,0x07fc03fcu,0xe4446204u,0x27fc23fcu,0x24442204u,0x27fc23fcu,0x24442204u,0x244423fcu,0x247c2204u,0x50005000u,0x8ffe8ffeu,0x00000000u,
    // position
    0x08400000u,0x10203ffcu,0x10102224u,0x27ff3ffcu,0x20000080u,0x22027ffeu,0x62060080u,0xe1041ffcu,0xa1041004u,0x21081ffcu,0x20881004u,0x20901ffcu,0x20101004u,0x2fff7ffeu,0x20000000u,0x00000000u,
    // pick
    0x40400000u,0x40e0fffcu,0x41b04484u,0xf3104484u,0x4c0c7c84u,0x58064448u,0x47f84448u,0x50007c48u,0x60004470u,0xc7f84430u,0x44085f30u,0x4408e4d8u,0x4408058cu,0x47f80706u,0xc4080000u,0x00000000u,
    // drag
    0x20802040u,0x21002040u,0x21fe23feu,0xfa00fe42u,0x24202242u,0x222e23feu,0x3bf23a42u,0x66226242u,0xa222a3feu,0x223e2240u,0x2221204eu,0x22212030u,0x220321f1u,0xe3feee0eu,0x00000000u,0x00000000u,
    // actual
    0x01000000u,0x01807bfeu,0x7ffe4800u,0x40024800u,0x50825000u,0x0c8057ffu,0x02805020u,0x20804820u,0x188048a4u,0x04804926u,0x7ffe4b22u,0x01807a23u,0x03e04421u,0x1c184020u,0xe00641e0u,0x00000000u,
    // expected
    0xfdff223eu,0x0c207fa2u,0x58202222u,0x31fe3e22u,0x1102223eu,0xfd122222u,0x15123e22u,0x15122222u,0x1512223eu,0x1112ffa2u,0x11321662u,0x104c6342u,0x1186c08eu,0xf6030000u,0x00000000u,0x00000000u,
    // slot
    0x20900840u,0x2fff1020u,0x20901010u,0xfffe27ffu,0x24922000u,0x27fe2202u,0x74926206u,0x6ffee104u,0xa000a104u,0xa3fc2108u,0xa2042088u,0x23fc2090u,0x22042010u,0x23fc2fffu,0x22042000u,0x00000000u,
};
// END HUD GLYPHS
static const uint DigitRows[55] = {
    14,17,17,17,14, 4,12,4,4,14, 14,1,14,16,31,
    30,1,14,1,30, 18,18,31,2,2, 31,16,30,1,30,
    14,16,30,17,14, 31,1,2,4,4, 14,17,14,17,14,
    14,17,15,1,14, 0,0,14,0,0
};
static const uint DecimalPowers[8] = {1,10,100,1000,10000,100000,1000000,10000000};
bool Glyph(uint glyph, float2 pixel)
{
    int2 cell = int2(floor(pixel));
    if (cell.x < 0 || cell.x >= 32 || cell.y < 0 || cell.y >= 16) return false;
    return (GlyphRows[glyph*16+(uint)cell.y] & (1u << (31-cell.x))) != 0;
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
        float2 diagnostic = p-float2(-70,34);
        if (all(diagnostic >= float2(-2,-1)) && all(diagnostic <= float2(140,56)))
        {
            uint row = (uint)clamp(floor(diagnostic.y/20),0,2);
            float2 local = diagnostic-float2(0,row*20);
            float4 values = IniParams[252];
            uint label = row == 0 ? 7u : row == 1 ? 8u : 9u;
            float value = row == 0 ? values.x : row == 1 ? values.y : values.z;
            if (Glyph(label,local) || Number(value,local-float2(40,3),row == 2 ? 2u : 8u))
                return float4(1,.85,.4,.98);
            return float4(.02,.02,.02,.75);
        }
    }
    float2 status = p-float2(-111,-30);
    if (all(status >= float2(-2,-2)) && all(status <= float2(224,17)))
    {
        uint column = (uint)clamp(floor(status.x/38),0,5);
        bool on = column == 0 ? core.z > .5 : column == 1 ? core.y > .5 :
                  column == 2 ? stages.x > .5 : column == 3 ? stages.y > .5 :
                  column == 4 ? stages.z > .5 : stages.w > .5;
        if (Glyph(column, status-float2(column*38,0)))
            return float4(on ? float3(.2,1,.45) : float3(.55,.55,.55),.95);
        return float4(.02,.02,.02,.65);
    }
    float2 modeLabel = p-float2(-16,13);
    if (Glyph(6u,modeLabel))
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
