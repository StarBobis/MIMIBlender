// =========================================================
// record_bones_cs.hlsl (数据存储器)
// =========================================================
StructuredBuffer<uint4> OriginalT0 : register(t0);
StructuredBuffer<uint4> DumpedCB1  : register(t1);
// 💡 修改1：将 uint 改为 float，用于接收 INI 中定义的 data = xxx.0
Buffer<float> MyPartID             : register(t2); 

RWStructuredBuffer<uint4> FakeT0_UAV : register(u1);

[numthreads(64, 1, 1)] 
void main(uint3 tid : SV_DispatchThreadID) {
    uint id = tid.x;
    if (id >= 768) return; 

    // 💡 修改2：删掉 GetDimensions，直接读取第0位数据并强转为 uint
    uint my_offset = (uint)MyPartID[0]; 
    
    uint offset_current = DumpedCB1[5].x;
    uint offset_prev    = DumpedCB1[5].y;
    
    uint cur_idx  = (offset_current + id) % 600000;
    uint prev_idx = (offset_prev + id) % 600000;
    
    FakeT0_UAV[my_offset + id]          = OriginalT0[cur_idx];
    FakeT0_UAV[my_offset + 100000 + id] = OriginalT0[prev_idx]; 
}