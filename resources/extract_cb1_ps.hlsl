struct V2P {
    float4 pos : SV_Position;
    nointerpolation uint id : TEXCOORD0;
    nointerpolation uint4 raw_bits : TEXCOORD1;
};

RWStructuredBuffer<uint4> DumpedCB1_UAV : register(u7);

float4 main(V2P i) : SV_Target {
    DumpedCB1_UAV[i.id] = i.raw_bits;
    return float4(0, 0, 0, 0); 
}