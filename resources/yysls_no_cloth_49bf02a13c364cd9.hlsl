// YYSLS local no-cloth vertex shader for hash 49bf02a13c364cd9 only.
// This variant matches the second UV-bearing vertex input layout found in
// the supplied ShaderFixes replacement. It is not a global hash replacement.
// The exporter checks the original VS before binding any mod resources.
// CustomShader installs this VS before the shared resource and draw list.
// The original VS is restored after the complete submesh list returns.
// Other vertex shaders must not use this implementation.
//
// The source keeps the game's decompression, skeleton skinning, historical
// skeleton sampling, motion output, and material output contracts. Only the
// position-deformation texture path is bypassed, so mod vertex data supplies
// the current and historical positions. The second TEXCOORD input remains
// active because this shader's pixel shader family consumes both UV channels.
//
// No t11 deformation texture is read. This bypasses consumption of the cloth
// result, not the upstream simulation itself. Normal skeletal animation stays
// enabled, and no new resource, sampler, or constant-buffer binding is used.
//
// This file intentionally has a separate ABI from yysls_no_cloth.hlsl. The
// target shader declares TEXCOORD1 between TEXCOORD0 and TANGENT0, while the
// original supported shader has no TEXCOORD1 input. Matching only the hash or
// only the index buffer would therefore be unsafe.

cbuffer Global : register(b2)
{
  // CameraInfo is stored at the original c19 register in the global buffer.
  float4 CameraInfo : packoffset(c19);
}

cbuffer Skeleton : register(b3)
{
  // Each bone occupies three affine rows in the original palette.
  float4 SkeletonData[768] : packoffset(c0);
}

cbuffer Shader : register(b1)
{
  // Preserve the material local-position control at its original offset.
  float eInGraphLocalPosition : packoffset(c31.y);
}

cbuffer Batch : register(b0)
{
  // Current object transform and skeleton-map addressing parameters.
  float4x3 World : packoffset(c0);
  float4 VBufferParam : packoffset(c17);

  // These values decode the position and the two UV channels when needed.
  float4 LocalBoundingBoxMin : packoffset(c18);
  float4 LocalBoundingBoxMax : packoffset(c19);
  float4 VertexCompressionParams : packoffset(c20);

  // Per-instance projection matrices are supplied by the game draw.
  float4x4 WorldViewProj : packoffset(c29);
  float4x4 LastWorldViewProjTex : packoffset(c33);
}

// The skeleton map is historical animation data, not cloth-result data.
// Keep the original resource and sampler slots for the motion path.
SamplerState sSkeletonSampler_s : register(s14);
Texture2D<float4> tSkeletonMap : register(t14);

// Preserve the comparison convention used by the decompiled source.
#define cmp -

void main(
  uint v0 : SV_InstanceID0,
  float4 v1 : POSITION0,
  float4 v2 : NORMAL0,
  float4 v3 : TEXCOORD0,
  float2 v4 : TEXCOORD1,
  float4 v5 : TANGENT0,
  float4 v6 : BINORMAL0,
  float4 v7 : BLENDWEIGHT0,
  uint4 v8 : BLENDINDICES0,
  uint v9 : SV_VertexID0,
  out float4 o0 : SV_Position0,
  out float4 o1 : TEXCOORD0,
  out float4 o2 : TEXCOORD1,
  out float4 o3 : TEXCOORD2,
  out float4 o4 : TEXCOORD3,
  out float4 o5 : TEXCOORD4,
  out float4 o6 : COLOR0,
  out float o7 : TEXCOORD5,
  out float3 p7 : TEXCOORD7,
  out float4 o8 : TEXCOORD6,
  out float4 o9 : TEXCOORD8)
{
  // Retain the register-oriented arithmetic used by the verified shader.
  // Keeping this order also avoids changing compressed-position rounding.
  float4 r0,r1,r2,r3,r4,r5,r6,r7,r8,r9,r10,r11,r12,r13,r14,r15,r16,r17,r18,r19;
  uint4 bitmask;
  float2 uv1;

  // Decode position and the first UV exactly as in the supplied shader.
  // POSITION.w near 255 marks a previously decompressed position.
  // Other modes select UNORM, packed, or unchanged vertex data.
  r0.x = cmp(254.998993 < v1.w);
  r0.y = cmp(v1.w < 255.001007);
  r0.x = r0.y ? r0.x : 0;
  if (r0.x == 0)
  {
    r0.xy = float2(0.00999999978,0.00999999978) + VertexCompressionParams.xy;
    r0.x = (uint)r0.x;
    r1.xyz = LocalBoundingBoxMax.xyz + -LocalBoundingBoxMin.xyz;
    r2.xyz = v1.xyz * r1.xyz + LocalBoundingBoxMin.xyz;
    r0.y = (int)r0.y;
    r0.y = cmp((int)r0.y >= 1);
    r0.zw = v3.xy * float2(2,2) + float2(-0.5,-0.5);
    r0.yz = r0.yy ? r0.zw : v3.xy;
    r0.xw = cmp((int2)r0.xx == int2(1,2));
    r3.xyzw = v1.zyxw * float4(255,255,255,255) + float4(0.00999999978,0.00999999978,0.00999999978,0.00999999978);
    r3.xyzw = (uint4)r3.xyzw;
    if (3 == 0) r4.x = 0; else if (3+5 < 32) { r4.x = (uint)r3.w << (32-(3 + 5)); r4.x = (uint)r4.x >> (32-3); } else r4.x = (uint)r3.w >> 5;
    if (5 == 0) r4.y = 0; else if (5+3 < 32) { r4.y = (uint)r3.w << (32-(5 + 3)); r4.y = (uint)r4.y >> (32-5); } else r4.y = (uint)r3.w >> 3;
    bitmask.w = ((~(-1 << 24)) << 8) & 0xffffffff; r1.w = (((uint)r4.x << 8) & bitmask.w) | ((uint)r3.x & ~bitmask.w);
    bitmask.x = ((~(-1 << 2)) << 8) & 0xffffffff; r3.x = (((uint)r4.y << 8) & bitmask.x) | ((uint)0 & ~bitmask.x);
    bitmask.x = ((~(-1 << 8)) << 0) & 0xffffffff; r3.x = (((uint)r3.y << 0) & bitmask.x) | ((uint)r3.x & ~bitmask.x);
    bitmask.y = ((~(-1 << 3)) << 8) & 0xffffffff; r3.y = (((uint)r3.w << 8) & bitmask.y) | ((uint)0 & ~bitmask.y);
    bitmask.y = ((~(-1 << 8)) << 0) & 0xffffffff; r3.y = (((uint)r3.z << 0) & bitmask.y) | ((uint)r3.y & ~bitmask.y);
    r4.x = (uint)r1.w;
    r4.yz = (uint2)r3.xy;
    r1.xyz = r4.xyz * r1.xyz;
    r1.xyz = r1.xyz * float3(0.000488519785,0.000977517106,0.000488519785) + LocalBoundingBoxMin.xyz;
    r1.w = 255;
    r1.xyzw = r0.wwww ? r1.xyzw : v1.xyzw;
    r2.w = 255;
    r1.xyzw = r0.xxxx ? r2.xyzw : r1.xyzw;
    r0.x = (int)r0.x | (int)r0.w;
    r0.xy = r0.xx ? r0.yz : v3.xy;
    uv1 = v4.xy;
    int compression_mode = (int)(VertexCompressionParams.x + 0.00999999978);
    if ((compression_mode == 1 || compression_mode == 2) && VertexCompressionParams.y >= 1)
    {
      uv1 = v4.xy * float2(2,2) + float2(-0.5,-0.5);
    }
  }
  else
  {
    r1.xyzw = v1.xyzw;
    r0.xy = v3.xy;
    uv1 = v4.xy;
  }

  // Decode the normal from the original UNORM representation.
  // Cloth meshes carry zero tangent data because cloth normally supplies a
  // simulated tangent frame through the removed deformation texture.
  // Construct an orthogonal frame instead of normalizing zero vectors.
  r2.xyz = v2.xyz * float3(2,2,2) + float3(-1,-1,-1);
  r0.z = dot(v5.xyz, v5.xyz);
  r0.w = cmp(r0.z < 9.99999975e-06);
  r0.z = rsqrt(max(r0.z, 9.99999975e-06));
  r3.xyz = v5.xyz * r0.zzz;
  if (r0.w != 0)
  {
    r3.xyz = abs(r2.y) < 0.999 ? cross(r2.xyz, float3(0,1,0)) : cross(r2.xyz, float3(1,0,0));
    r3.xyz = normalize(r3.xyz);
  }
  r0.z = dot(v6.xyz, v6.xyz);
  r0.w = cmp(r0.z < 9.99999975e-06);
  r0.z = rsqrt(max(r0.z, 9.99999975e-06));
  r4.xyz = v6.xyz * r0.zzz;
  if (r0.w != 0)
  {
    r4.xyz = cross(r2.xyz, r3.xyz);
  }

  // The cloth-result path is intentionally absent from this local shader.
  // Current position and the current tangent frame come from mod buffers.
  // No vertex ID or t11 lookup may influence the replacement draw.
  r7.xyz = r1.xyz;
  r0.w = 0;

  // Reconstruct the fourth weight using the original arithmetic order.
  // Blend indices address the skeleton palette, not a deformation texture.
  r2.w = 1 + -v7.x;
  r2.w = -v7.y + r2.w;
  r2.w = -v7.z + r2.w;
  r5.xyzw = (int4)v8.xyzw * int4(3,3,3,3);
  r6.xyzw = mad(int4(3,3,3,3), (int4)v8.xxyy, int4(1,2,1,2));
  r8.xyzw = mad(int4(3,3,3,3), (int4)v8.zzww, int4(1,2,1,2));
  r9.xyzw = SkeletonData[r5.x].xyzw * v7.xxxx;
  r10.xyzw = SkeletonData[r5.y].xyzw * v7.yyyy;
  r9.xyzw = r10.xyzw + r9.xyzw;
  r10.xyzw = SkeletonData[r5.z].xyzw * v7.zzzz;
  r9.xyzw = r10.xyzw + r9.xyzw;
  r10.xyzw = SkeletonData[r5.w].xyzw * r2.wwww;
  r9.xyzw = r10.xyzw + r9.xyzw;
  r10.xyzw = SkeletonData[r6.x].xyzw * v7.xxxx;
  r11.xyzw = SkeletonData[r6.z].xyzw * v7.yyyy;
  r10.xyzw = r11.xyzw + r10.xyzw;
  r11.xyzw = SkeletonData[r8.x].xyzw * v7.zzzz;
  r10.xyzw = r11.xyzw + r10.xyzw;
  r11.xyzw = SkeletonData[r8.z].xyzw * r2.wwww;
  r10.xyzw = r11.xyzw + r10.xyzw;
  r11.xyzw = SkeletonData[r6.y].xyzw * v7.xxxx;
  r6.xyzw = SkeletonData[r6.w].xyzw * v7.yyyy;
  r6.xyzw = r11.xyzw + r6.xyzw;
  r11.xyzw = SkeletonData[r8.y].xyzw * v7.zzzz;
  r6.xyzw = r11.xyzw + r6.xyzw;
  r8.xyzw = SkeletonData[r8.w].xyzw * r2.wwww;
  r6.xyzw = r8.xyzw + r6.xyzw;

  // Skin position with translation and directions without translation.
  // Keep normal, tangent, and binormal as separate material varyings.
  r3.w = dot(r9.xyz, r7.xyz);
  r8.x = r3.w + r9.w;
  r3.w = dot(r10.xyz, r7.xyz);
  r8.y = r3.w + r10.w;
  r3.w = dot(r6.xyz, r7.xyz);
  r8.z = r3.w + r6.w;
  r7.x = dot(r9.xyz, r2.xyz);
  r7.y = dot(r10.xyz, r2.xyz);
  r7.z = dot(r6.xyz, r2.xyz);
  r2.x = dot(r9.xyz, r3.xyz);
  r2.y = dot(r10.xyz, r3.xyz);
  r2.z = dot(r6.xyz, r3.xyz);
  r3.x = dot(r9.xyz, r4.xyz);
  r3.y = dot(r10.xyz, r4.xyz);
  r3.z = dot(r6.xyz, r4.xyz);

  // Preserve the second position decode used by local-position effects.
  // This path still reads only vertex data and never a cloth-result texture.
  r3.w = cmp(254.998993 < r1.w);
  r4.x = cmp(r1.w < 255.001007);
  r3.w = r3.w ? r4.x : 0;
  if (r3.w == 0)
  {
    r3.w = 0.00999999978 + VertexCompressionParams.x;
    r3.w = (uint)r3.w;
    r4.xyz = LocalBoundingBoxMax.xyz + -LocalBoundingBoxMin.xyz;
    r6.xyz = r1.xyz * r4.xyz + LocalBoundingBoxMin.xyz;
    r9.xy = cmp((int2)r3.ww == int2(1,2));
    r10.xyzw = r1.zyxw * float4(255,255,255,255) + float4(0.00999999978,0.00999999978,0.00999999978,0.00999999978);
    r10.xyzw = (uint4)r10.xyzw;
    if (3 == 0) r9.z = 0; else if (3+5 < 32) { r9.z = (uint)r10.w << (32-(3 + 5)); r9.z = (uint)r9.z >> (32-3); } else r9.z = (uint)r10.w >> 5;
    if (5 == 0) r9.w = 0; else if (5+3 < 32) { r9.w = (uint)r10.w << (32-(5 + 3)); r9.w = (uint)r9.w >> (32-5); } else r9.w = (uint)r10.w >> 3;
    bitmask.w = ((~(-1 << 24)) << 8) & 0xffffffff; r1.w = (((uint)r9.z << 8) & bitmask.w) | ((uint)r10.x & ~bitmask.w);
    bitmask.w = ((~(-1 << 2)) << 8) & 0xffffffff; r3.w = (((uint)r9.w << 8) & bitmask.w) | ((uint)0 & ~bitmask.w);
    bitmask.w = ((~(-1 << 8)) << 0) & 0xffffffff; r3.w = (((uint)r10.y << 0) & bitmask.w) | ((uint)r3.w & ~bitmask.w);
    bitmask.w = ((~(-1 << 3)) << 8) & 0xffffffff; r4.w = (((uint)r10.w << 8) & bitmask.w) | ((uint)0 & ~bitmask.w);
    bitmask.w = ((~(-1 << 8)) << 0) & 0xffffffff; r4.w = (((uint)r10.z << 0) & bitmask.w) | ((uint)r4.w & ~bitmask.w);
    r10.x = (uint)r1.w;
    r10.y = (uint)r3.w;
    r10.z = (uint)r4.w;
    r4.xyz = r10.xyz * r4.xyz;
    r4.xyz = r4.xyz * float3(0.000488519785,0.000977517106,0.000488519785) + LocalBoundingBoxMin.xyz;
    r4.xyz = r9.yyy ? r4.xyz : r1.xyz;
    r1.xyz = r9.xxx ? r6.xyz : r4.xyz;
  }

  // Historical position also starts from mod geometry in this variant.
  // The following skeleton-map path remains the original historical animation.
  r4.xyz = r1.xyz;
  r6.xy = cmp(float2(9.99999975e-06,-0.00100000005) < VBufferParam.yw);
  r0.z = cmp(VBufferParam.y < 1);
  r0.z = r0.z ? r6.x : 0;
  if (r0.z != 0)
  {
    // Reconstruct the four original bone rows from the skeleton atlas.
    r5.xyzw = (uint4)r5.xyzw;
    r9.xyzw = float4(0.5,1.5,2.5,0.5) + r5.xxxy;
    r9.xyzw = VBufferParam.zzzz * r9.zxwy;
    r10.xz = r9.yw;
    r10.yw = float2(0,0);
    r10.xyzw = VBufferParam.xyxy + r10.xyzw;
    r11.xyzw = tSkeletonMap.SampleLevel(sSkeletonSampler_s, r10.xy, 0).xyzw;
    r10.xyzw = tSkeletonMap.SampleLevel(sSkeletonSampler_s, r10.zw, 0).xyzw;
    r9.yw = float2(0,0);
    r9.xyzw = VBufferParam.xyxy + r9.xyzw;
    r12.xyzw = tSkeletonMap.SampleLevel(sSkeletonSampler_s, r9.xy, 0).xyzw;
    r9.xyzw = tSkeletonMap.SampleLevel(sSkeletonSampler_s, r9.zw, 0).xyzw;
    r13.xyzw = float4(1.5,2.5,0.5,1.5) + r5.yyzz;
    r13.xyzw = VBufferParam.zzzz * r13.zxwy;
    r14.xz = r13.yw;
    r14.yw = float2(0,0);
    r14.xyzw = VBufferParam.xyxy + r14.xyzw;
    r15.xyzw = tSkeletonMap.SampleLevel(sSkeletonSampler_s, r14.xy, 0).xyzw;
    r14.xyzw = tSkeletonMap.SampleLevel(sSkeletonSampler_s, r14.zw, 0).xyzw;
    r13.yw = float2(0,0);
    r13.xyzw = VBufferParam.xyxy + r13.xyzw;
    r16.xyzw = tSkeletonMap.SampleLevel(sSkeletonSampler_s, r13.xy, 0).xyzw;
    r13.xyzw = tSkeletonMap.SampleLevel(sSkeletonSampler_s, r13.zw, 0).xyzw;
    r5.xyzw = float4(2.5,0.5,1.5,2.5) + r5.zwww;
    r5.xyzw = VBufferParam.zzzz * r5.zxwy;
    r17.xz = r5.yw;
    r17.yw = float2(0,0);
    r17.xyzw = VBufferParam.xyxy + r17.xyzw;
    r18.xyzw = tSkeletonMap.SampleLevel(sSkeletonSampler_s, r17.xy, 0).xyzw;
    r17.xyzw = tSkeletonMap.SampleLevel(sSkeletonSampler_s, r17.zw, 0).xyzw;
    r5.yw = float2(0,0);
    r5.xyzw = VBufferParam.xyxy + r5.xyzw;
    r19.xyzw = tSkeletonMap.SampleLevel(sSkeletonSampler_s, r5.xy, 0).xyzw;
    r5.xyzw = tSkeletonMap.SampleLevel(sSkeletonSampler_s, r5.zw, 0).xyzw;

    // Blend the sampled rows with the same weights as current skinning.
    r9.xyzw = v7.yyyy * r9.xyzw;
    r9.xyzw = v7.xxxx * r11.xyzw + r9.xyzw;
    r9.xyzw = v7.zzzz * r16.xyzw + r9.xyzw;
    r9.xyzw = r2.wwww * r17.xyzw + r9.xyzw;
    r11.xyzw = v7.yyyy * r15.xyzw;
    r10.xyzw = v7.xxxx * r10.xyzw + r11.xyzw;
    r10.xyzw = v7.zzzz * r13.xyzw + r10.xyzw;
    r10.xyzw = r2.wwww * r19.xyzw + r10.xyzw;
    r11.xyzw = v7.yyyy * r14.xyzw;
    r11.xyzw = v7.xxxx * r12.xyzw + r11.xyzw;
    r11.xyzw = v7.zzzz * r18.xyzw + r11.xyzw;
    r5.xyzw = r2.wwww * r5.xyzw + r11.xyzw;
    r0.z = dot(r9.xyz, r4.xyz);
    r9.x = r0.z + r9.w;
    r0.z = dot(r10.xyz, r4.xyz);
    r9.y = r0.z + r10.w;
    r0.z = dot(r5.xyz, r4.xyz);
    r9.z = r0.z + r5.w;
    r4.xyz = r9.xyz;
  }

  // Emit the same world-position and tangent-frame varyings as the source.
  r8.w = 1;
  o2.x = dot(r8.xyzw, World._m00_m10_m20_m30);
  o2.y = dot(r8.xyzw, World._m01_m11_m21_m31);
  o2.z = dot(r8.xyzw, World._m02_m12_m22_m32);
  r5.x = dot(r7.xyz, World._m00_m10_m20);
  r5.y = dot(r7.xyz, World._m01_m11_m21);
  r5.z = dot(r7.xyz, World._m02_m12_m22);
  r0.z = dot(r5.xyz, r5.xyz);
  r0.z = rsqrt(r0.z);
  o3.xyz = r5.xyz * r0.zzz;
  r5.x = dot(r2.xyz, World._m00_m10_m20);
  r5.y = dot(r2.xyz, World._m01_m11_m21);
  r5.z = dot(r2.xyz, World._m02_m12_m22);
  r0.z = dot(r5.xyz, r5.xyz);
  r0.z = rsqrt(r0.z);
  o4.xyz = r5.xyz * r0.zzz;
  r2.x = dot(r3.xyz, World._m00_m10_m20);
  r2.y = dot(r3.xyz, World._m01_m11_m21);
  r2.z = dot(r3.xyz, World._m02_m12_m22);
  r0.z = dot(r2.xyz, r2.xyz);
  r0.z = rsqrt(r0.z);
  o5.xyz = r2.xyz * r0.zzz;

  // Preserve the source's skinning flag without a cloth-result flag.
  r0.z = cmp(v7.x == 1.000000);
  r1.w = cmp((int)v8.y != (int)v8.x);
  r0.z = r0.z ? r1.w : 0;
  r0.z = r0.z ? 0 : 1;
  o9.w = max(r0.z, r0.w);

  // Current clip position uses the per-instance projection matrix.
  // Historical clip coordinates retain the original validity calculation.
  o0.x = dot(r8.xyzw, WorldViewProj._m00_m10_m20_m30);
  o0.y = dot(r8.xyzw, WorldViewProj._m01_m11_m21_m31);
  o0.z = dot(r8.xyzw, WorldViewProj._m02_m12_m22_m32);
  r0.z = dot(r8.xyzw, WorldViewProj._m03_m13_m23_m33);
  r4.w = 1;
  r2.x = dot(r4.xyzw, LastWorldViewProjTex._m00_m10_m20_m30);
  r2.y = dot(r4.xyzw, LastWorldViewProjTex._m01_m11_m21_m31);
  r2.z = dot(r4.xyzw, LastWorldViewProjTex._m03_m13_m23_m33);
  r2.xyz = float3(0.00100000005,0.00100000005,0.00100000005) * r2.xyz;
  o8.xyz = r6.yyy ? r2.xyz : float3(10,10,1);
  o8.w = 1;
  o7.x = CameraInfo.z * r0.z;

  // Preserve both UV channels, local-position effects, and initialized flags.
  r2.xyz = r8.xyz + -r1.xyz;
  p7.xyz = eInGraphLocalPosition * r2.xyz + r1.xyz;
  o0.w = r0.z;
  o1.xy = r0.xy;
  o1.zw = uv1;
  o2.w = r8.y;
  o3.w = 0;
  o4.w = 0;
  o5.w = 0;
  o6.xyzw = float4(1,1,1,0.5);
  o9.xyz = v2.xyz * float3(2,2,2) + float3(-1,-1,-1);

  // Keep SV_VertexID in the input signature without addressing simulation data.
  // The sentinel cannot be produced by a normal draw, so this has no visible
  // effect while preserving compatibility with the original shader contract.
  if (v9 == 0xffffffff)
  {
    o9.w = 1;
  }
  return;
}
