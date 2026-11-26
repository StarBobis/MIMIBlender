// Rebuild DrawIndexedInstancedIndirect arguments for the edited geometry.
// The renderer owns instance visibility and the first instance on every frame.
Buffer<uint> OriginalArgs : register(t0);
RWBuffer<uint> ModArgs : register(u0);
cbuffer DrawRange : register(b0) { uint SourceWord, IndexCount, FirstIndex, Padding; }

[numthreads(1, 1, 1)]
void main()
{
    ModArgs[0] = IndexCount;
    ModArgs[1] = OriginalArgs[SourceWord + 1];
    ModArgs[2] = FirstIndex;
    ModArgs[3] = 0;
    ModArgs[4] = OriginalArgs[SourceWord + 4];
}
