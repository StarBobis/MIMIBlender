// =========================================================
// record_bones_cs.hlsl (data storage)
// =========================================================
StructuredBuffer<uint4> OriginalT0 : register(t0);
StructuredBuffer<uint4> DumpedCB1  : register(t1);
// Change 1: switched uint to float so it can receive data = xxx.0 defined in the INI
Buffer<float> MyPartID             : register(t2); 

RWStructuredBuffer<uint4> FakeT0_UAV : register(u1);

[numthreads(64, 1, 1)] 
void main(uint3 tid : SV_DispatchThreadID) {
    uint id = tid.x;
    if (id >= 768) return; 

    // Change 2: removed GetDimensions, read element 0 directly and cast it to uint
    uint my_offset = (uint)MyPartID[0]; 
    
    uint offset_current = DumpedCB1[5].x;
    uint offset_prev    = DumpedCB1[5].y;
    
    uint cur_idx  = (offset_current + id) % 600000;
    uint prev_idx = (offset_prev + id) % 600000;
    
    FakeT0_UAV[my_offset + id]          = OriginalT0[cur_idx];
    FakeT0_UAV[my_offset + 100000 + id] = OriginalT0[prev_idx]; 
}