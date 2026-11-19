// Native cloth source remapping. Reserved draw-local SRV: t118.
// Each output point stores original XYZ bits and its original simulation ID.
// Keep the game simulation and both skeleton paths; do not copy ranged CBs.
// Position edits are a reference-space offset transported by the game's skinning.
// This preserves existing simulation topology, not a new collision/cloth solver.
// Imported simulation normals remain authoritative for deformed cloth.
Buffer<uint> MIMIClothSource : register(t118);

// ---- Created with 3Dmigoto v1.2.3.0 on Wed Nov 11 12:33:06 2026

cbuffer Global : register(b2)
{
  float4x4 ViewProj : packoffset(c0);
  float4x4 ShadowViewProjTexs0 : packoffset(c4);
  float4x4 ShadowViewProjTexs1 : packoffset(c8);
  float4x4 ShadowViewProjTexs2 : packoffset(c12);
  float4 CSMShadowBiases : packoffset(c16);
  float4 DiyLightingInfo : packoffset(c17);
  float4 CameraPos : packoffset(c18);
  float4 CameraInfo : packoffset(c19);
  float4 ScreenInfo : packoffset(c20);
  float4 ScreenColor : packoffset(c21);
  float4 FogInfo : packoffset(c22);
  float4 FogColor : packoffset(c23);
  float4 EnvInfo : packoffset(c24);
  float4 SunDirection : packoffset(c25);
  float4 SunColor : packoffset(c26);
  float4 AmbientColor : packoffset(c27);
  float4 ShadowColor : packoffset(c28);
  float4 ReflectionProbeBBMin : packoffset(c29);
  float4 ReflectionProbeBBMax : packoffset(c30);
  float4 Misc : packoffset(c31);
  float4 Misc2 : packoffset(c32);
  float4 Misc3 : packoffset(c33);
  float4 VolumetricFogParam : packoffset(c34);
  float4 VolumetricFogParam2 : packoffset(c35);
  float4x4 ShadowViewProjTexs3 : packoffset(c36);
  float4 VTParam0 : packoffset(c40);
  float4 VTParam1 : packoffset(c41);
  float4 VTParam2 : packoffset(c42);
  float4 VTViewpoint : packoffset(c43);
  float4 VTIndMapUVTransform : packoffset(c44);
  float4 SunFogColor : packoffset(c45);
  float4 WindParam : packoffset(c46);
  float4 LastWindParam : packoffset(c47);
  float4 ScreenMotionGray : packoffset(c48);
  float4 GIInfo : packoffset(c49);
  float4 SSRParam[4] : packoffset(c50);
  float4x4 LastViewProjTex : packoffset(c54);
  float4 GlobalBurnParam : packoffset(c58);
  float4 CSMCacheIndexs : packoffset(c59);
  float4 AerialPerspectiveExt : packoffset(c60);
  float4 AerialPerspectiveMie : packoffset(c61);
  float4 AerialPerspectiveRay : packoffset(c62);
  float4 LastCameraPos : packoffset(c63);
  float4 SHAOParam : packoffset(c64);
  float4 SHSBParam : packoffset(c65);
  float4 SHSBParam2 : packoffset(c66);
  float4 SHGIParam : packoffset(c67);
  float4 SHGIParam2 : packoffset(c68);
  float4 TimeOfDayInfos : packoffset(c69);
  float4 UserData[4] : packoffset(c70);
  float4x4 ViewRotationProj : packoffset(c74);
  float4 WorldProbeInfo : packoffset(c78);
  float4 LastPlayerPos : packoffset(c79);
  float4 HexEnvData[4] : packoffset(c80);
  float4 HexRenderOptionData[4] : packoffset(c84);
  float4 OriginSunDir : packoffset(c88);
}

cbuffer Skeleton : register(b3)
{
  float4 SkeletonData[768] : packoffset(c0);
}

cbuffer Batch : register(b0)
{
  float4x3 World : packoffset(c0);
  float4 cTintColor1 : packoffset(c3);
  float4 cTintColor2 : packoffset(c4);
  float4 cTintColor3 : packoffset(c5);
  float4 cShadowBias : packoffset(c6);
  float4 cSHCoefficients[7] : packoffset(c7);
  float4 cParameter : packoffset(c14);
  float4 cParameter2 : packoffset(c15);
  float4 cParameter3 : packoffset(c16);
  float4 VBufferParam : packoffset(c17);
  float4 LocalBoundingBoxMin : packoffset(c18);
  float4 LocalBoundingBoxMax : packoffset(c19);
  float4 VertexCompressionParams : packoffset(c20);
  float4 cMinBB : packoffset(c21);
  float4 cMaxBB : packoffset(c22);
  float4 cVirtualLitDir : packoffset(c23);
  float4 cVirtualLitColor : packoffset(c24);
  float4 cVirtualLitColor2 : packoffset(c25);
  float4 cVirtualLitParam : packoffset(c26);
  float4 cHeightmapMinPos : packoffset(c27);
  float4 cHeightmapMaxPos : packoffset(c28);
  float4x4 WorldViewProj : packoffset(c29);
  float4x4 LastWorldViewProjTex : packoffset(c33);
  float4x3 LastWorld : packoffset(c37);
  float4x4 ViewRotationProjTex : packoffset(c40);
  float4x4 LastViewRotationProjTex : packoffset(c44);
  float4 PlayerPos : packoffset(c48);
  float4 FoliageCenter : packoffset(c49);
  float4 LastFoliageCenter : packoffset(c50);
  float4 FoliageMapParam : packoffset(c51);
  float4 SheltermapMinPos : packoffset(c52);
  float4 SheltermapMaxPos : packoffset(c53);
  float4x4 NormalWorld : packoffset(c54);
  float4 cWBasisX : packoffset(c58);
  float4 cWBasisY : packoffset(c59);
  float4 cWBasisZ : packoffset(c60);
  float4 cVisibilitySH[2] : packoffset(c61);
  float4x3 Local : packoffset(c63);
  float4x3 View : packoffset(c66);
  float4x3 InvView : packoffset(c69);
  uint4 DynamicShaderProfile : packoffset(c72);
  float4 HexGpuDrivenParams : packoffset(c73);
  int cVertexDeformType : packoffset(c74);
  int cPositionDeformTexHeight : packoffset(c74.y);
  int cPositionDeformLastTexHeight : packoffset(c74.z);
  int cDeformationMisc : packoffset(c74.w);
  float4 cHDRParam : packoffset(c75);
  uint4 RTGeometryInfo : packoffset(c76);
}

Texture2DArray<float4> tPositionDeformTex : register(t11);


// 3Dmigoto declarations
#define cmp -
Texture1D<float4> IniParams : register(t120);


// t11.w and tangent-plane texels carry integer bit patterns in float slots.
// Numeric float-to-int conversion destroys these bits; reinterpret first.
float3 MIMINormalize(float3 value, float3 fallback)
{
  float magnitude = length(value);
  return magnitude < 0.00001 ? fallback : value / magnitude;
}

float3 MIMIDecodeNormal(uint bits)
{
  float3 value = float3(bits & 255, (bits >> 8) & 255, (bits >> 16) & 255);
  value = (value - 128.0) * (1.0 / 127.5);
  return MIMINormalize(value, float3(0, 1, 0));
}

float3 MIMIDecodeSigned16(uint3 bits)
{
  // Sign extend each low word before converting its signed value to float.
  int3 words = int3(bits & 65535);
  words = (words ^ 32768) - 32768;
  return float3(words) * (1.0 / 32767.0);
}

void main(
  uint v0 : SV_InstanceID0,
  float4 v1 : POSITION0,
  float4 v2 : NORMAL0,
  float2 v3 : TEXCOORD0,
  float4 v4 : TANGENT0,
  float4 v5 : BINORMAL0,
  float4 v6 : BLENDWEIGHT0,
  uint4 v7 : BLENDINDICES0,
  uint v8 : SV_VertexID0,
  out float4 o0 : SV_Position0,
  out float4 o1 : TEXCOORD0,
  out float4 o2 : TEXCOORD1)
{
// Needs manual fix for instruction:
// unknown dcl_: dcl_input_sgv v8.x, vertex_id
  // Only XY carries shadow UVs; define the unused output lanes as well.
  o1.zw = float2(0, 0);
  float4 r0,r1,r2,r3,r4,r5,r6;
  // Read the map with the exported ID before replacing simulation addressing.
  uint mapBase = v8 * 4;
  float3 sourcePosition = asfloat(uint3(MIMIClothSource[mapBase],
    MIMIClothSource[mapBase + 1], MIMIClothSource[mapBase + 2]));
  uint sourceVertex = MIMIClothSource[mapBase + 3];
  float3 editOffset;

  uint4 bitmask, uiDest;
  float4 fDest;

  r0.x = cmp(254.998993 < v1.w);
  r0.y = cmp(v1.w < 255.001007);
  r0.x = r0.y ? r0.x : 0;
  if (r0.x == 0) {
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
    if (3 == 0) r4.x = 0; else if (3+5 < 32) {     r4.x = (uint)r3.w << (32-(3 + 5)); r4.x = (uint)r4.x >> (32-3);    } else r4.x = (uint)r3.w >> 5;
    if (5 == 0) r4.y = 0; else if (5+3 < 32) {     r4.y = (uint)r3.w << (32-(5 + 3)); r4.y = (uint)r4.y >> (32-5);    } else r4.y = (uint)r3.w >> 3;
    bitmask.w = ((~(-1 << 24)) << 8) & 0xffffffff;  r1.w = (((uint)r4.x << 8) & bitmask.w) | ((uint)r3.x & ~bitmask.w);
    bitmask.w = ((~(-1 << 2)) << 8) & 0xffffffff;  r2.w = (((uint)r4.y << 8) & bitmask.w) | ((uint)0 & ~bitmask.w);
    bitmask.w = ((~(-1 << 8)) << 0) & 0xffffffff;  r2.w = (((uint)r3.y << 0) & bitmask.w) | ((uint)r2.w & ~bitmask.w);
    bitmask.x = ((~(-1 << 3)) << 8) & 0xffffffff;  r3.x = (((uint)r3.w << 8) & bitmask.x) | ((uint)0 & ~bitmask.x);
    bitmask.x = ((~(-1 << 8)) << 0) & 0xffffffff;  r3.x = (((uint)r3.z << 0) & bitmask.x) | ((uint)r3.x & ~bitmask.x);
    r4.x = (uint)r1.w;
    r4.y = (uint)r2.w;
    r4.z = (uint)r3.x;
    r1.xyz = r4.xyz * r1.xyz;
    r1.xyz = r1.xyz * float3(0.000488519785,0.000977517106,0.000488519785) + LocalBoundingBoxMin.xyz;
    r1.xyz = r0.www ? r1.xyz : v1.xyz;
    r1.xyz = r0.xxx ? r2.xyz : r1.xyz;
    r0.x = (int)r0.x | (int)r0.w;
    o1.xy = r0.xx ? r0.yz : v3.xy;
  } else {
    r1.xyz = v1.xyz;
    o1.xy = v3.xy;
  }
  r0.xyz = v2.xyz * float3(2,2,2) + float3(-1,-1,-1);
  // Shadow position must follow the same simulated source and edit.
  editOffset = r1.xyz - sourcePosition;
  // Use the same cloth decision as the main pass for replacement draws.
  if (cVertexDeformType == 1 && sourceVertex != 0xffffffffu) {
    r0.w = cDeformationMisc >> 24;
    r0.w = (int)r0.w & 255;
    r2.z = cDeformationMisc & 255;
    r0.w = cmp((int)r2.z < (int)r0.w);
    if (r0.w != 0) {
      r0.w = sourceVertex;
      r3.x = 0.00390625 * r0.w;
      r2.y = (int)r3.x;
      r3.x = (uint)r2.y;
      r3.x = 256 * r3.x;
      r0.w = -r3.x + r0.w;
      r2.x = (int)r0.w;
      r2.w = 0;
      r1.xyzw = tPositionDeformTex.Load(r2.xyzw).xyzw;
      r1.xyz += editOffset; // Keep shadow geometry aligned with the main pass.
      r0.xyz = MIMIDecodeNormal(asuint(r1.w));
    }
  }
  r0.w = 1 + -v6.x;
  r0.w = -v6.y + r0.w;
  r0.w = -v6.z + r0.w;
  r2.xyzw = (int4)v7.xyzw * int4(3,3,3,3);
  r3.xyzw = mad(int4(3,3,3,3), (int4)v7.xxyy, int4(1,2,1,2));
  r4.xyzw = mad(int4(3,3,3,3), (int4)v7.zzww, int4(1,2,1,2));
  r5.xyzw = SkeletonData[r2.x].xyzw * v6.xxxx;
  r6.xyzw = SkeletonData[r2.y].xyzw * v6.yyyy;
  r5.xyzw = r6.xyzw + r5.xyzw;
  r6.xyzw = SkeletonData[r2.z].xyzw * v6.zzzz;
  r5.xyzw = r6.xyzw + r5.xyzw;
  r2.xyzw = SkeletonData[r2.w].xyzw * r0.wwww;
  r2.xyzw = r5.xyzw + r2.xyzw;
  r5.xyzw = SkeletonData[r3.x].xyzw * v6.xxxx;
  r6.xyzw = SkeletonData[r3.z].xyzw * v6.yyyy;
  r5.xyzw = r6.xyzw + r5.xyzw;
  r6.xyzw = SkeletonData[r4.x].xyzw * v6.zzzz;
  r5.xyzw = r6.xyzw + r5.xyzw;
  r6.xyzw = SkeletonData[r4.z].xyzw * r0.wwww;
  r5.xyzw = r6.xyzw + r5.xyzw;
  r6.xyzw = SkeletonData[r3.y].xyzw * v6.xxxx;
  r3.xyzw = SkeletonData[r3.w].xyzw * v6.yyyy;
  r3.xyzw = r6.xyzw + r3.xyzw;
  r6.xyzw = SkeletonData[r4.y].xyzw * v6.zzzz;
  r3.xyzw = r6.xyzw + r3.xyzw;
  r4.xyzw = SkeletonData[r4.w].xyzw * r0.wwww;
  r3.xyzw = r4.xyzw + r3.xyzw;
  r0.w = dot(r2.xyz, r1.xyz);
  r4.x = r0.w + r2.w;
  r0.w = dot(r5.xyz, r1.xyz);
  r4.y = r0.w + r5.w;
  r0.w = dot(r3.xyz, r1.xyz);
  r4.z = r0.w + r3.w;
  r1.x = dot(r2.xyz, r0.xyz);
  r1.y = dot(r5.xyz, r0.xyz);
  r1.z = dot(r3.xyz, r0.xyz);
  r4.w = 1;
  r0.x = dot(r4.xyzw, World._m00_m10_m20_m30);
  r0.y = dot(r4.xyzw, World._m01_m11_m21_m31);
  r0.z = dot(r4.xyzw, World._m02_m12_m22_m32);
  r2.x = dot(r1.xyz, World._m00_m10_m20);
  r2.y = dot(r1.xyz, World._m01_m11_m21);
  r2.z = dot(r1.xyz, World._m02_m12_m22);
  r0.w = dot(r2.xyz, r2.xyz);
  r0.w = rsqrt(r0.w);
  r1.xyz = r2.xyz * r0.www;
  r2.x = dot(r4.xyzw, WorldViewProj._m00_m10_m20_m30);
  r2.y = dot(r4.xyzw, WorldViewProj._m01_m11_m21_m31);
  r0.w = dot(r4.xyzw, WorldViewProj._m02_m12_m22_m32);
  r1.w = dot(r4.xyzw, WorldViewProj._m03_m13_m23_m33);
  r3.y = abs(CameraInfo.w);
  r3.z = cmp(0 >= CameraInfo.w);
  r3.x = dot(r1.xyz, SunDirection.xyz);
  r0.xyz = CameraPos.xyz + -r0.xyz;
  r3.w = dot(r0.xyz, r0.xyz);
  r3.w = rsqrt(r3.w);
  r0.xyz = r3.www * r0.xyz;
  r0.x = dot(r1.xyz, r0.xyz);
  r0.z = 1 + -abs(r0.x);
  r0.z = r1.w * r0.z;
  r0.z = max(1, r0.z);
  r0.z = min(10, r0.z);
  r0.y = r3.y * r0.z;
  r0.xy = r3.zz ? r3.xy : r0.xy;
  r0.x = cmp(0 != r0.x);
  r0.x = r0.x ? r0.y : -r0.y;
  r0.x = r0.w + r0.x;
  r0.y = CameraInfo.y + -CameraInfo.x;
  r0.y = -500 + r0.y;
  r0.y = cmp(0 < r0.y);
  r0.z = 9.99999997e-07 * r1.w;
  r0.z = max(r0.x, r0.z);
  r2.z = r0.y ? r0.z : r0.x;
  r0.x = cmp(CameraPos.w < 0);
  r0.y = dot(r2.xyz, r2.xyz);
  r0.y = sqrt(r0.y);
  r1.z = 0.5 * r0.y;
  r2.w = -r2.x;
  r0.y = dot(abs(r2.ywz), float3(1,1,1));
  r0.y = 1 / r0.y;
  r0.zw = r2.yw * r0.yy;
  r1.x = r2.y * r0.y + -r0.w;
  r1.y = r0.z + r0.w;
  r0.y = abs(r2.y) + abs(r2.w);
  r0.y = max(9.99999997e-07, r0.y);
  r0.y = 1 / r0.y;
  r0.zw = r2.yw * r0.yy;
  r3.x = r2.y * r0.y + -r0.w;
  r3.y = r0.z + r0.w;
  r0.y = cmp(r2.z >= 0);
  r3.z = r1.z;
  r0.yzw = r0.yyy ? r1.xyz : r3.xyz;
  o0.xyz = r0.xxx ? r0.yzw : r2.xyz;
  o0.w = r1.w;
  o2.xyz = float3(0,0,0);
  o2.w = r4.y;
  return;
}

