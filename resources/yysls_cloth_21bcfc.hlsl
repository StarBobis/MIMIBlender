// Native cloth source remapping. Reserved draw-local SRV: t118.
// Each output point stores original XYZ bits and its original simulation ID.
// Keep the game simulation and both skeleton paths; do not copy ranged CBs.
// Position edits are a reference-space offset transported by the game's skinning.
// This preserves existing simulation topology, not a new collision/cloth solver.
// Imported simulation normals remain authoritative for deformed cloth.
Buffer<uint> MIMIClothSource : register(t118);

// ---- Created with 3Dmigoto v1.2.3.0 on Sun Nov 15 20:25:47 2026

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

cbuffer Shader : register(b1)
{
  float cMetallicScale : packoffset(c0);
  float cSmoothnessScale : packoffset(c0.y);
  float cSmoothnessOffset : packoffset(c0.z);
  float cMetallicOffset : packoffset(c0.w);
  float cAlpha : packoffset(c1);
  float cSaturation : packoffset(c1.y);
  float cDepthOffset : packoffset(c1.z);
  float cCameraSurfaceIntensity : packoffset(c1.w);
  float4 cDyeingHighlightMask : packoffset(c2);
  float4 cEmissionScale : packoffset(c3);
  float4 cEmissionScrolling : packoffset(c4);
  float4 DyeingMaskIndex : packoffset(c5);
  float3 cPatternHSVOffset : packoffset(c6);
  float cPatternHSVScale : packoffset(c6.w);
  float3 cColorHSVOffset0 : packoffset(c7);
  float cColorHSVScale0 : packoffset(c7.w);
  float3 cColorHSVOffset1 : packoffset(c8);
  float cColorHSVScale1 : packoffset(c8.w);
  float3 cColorHSVOffset2 : packoffset(c9);
  float cColorHSVScale2 : packoffset(c9.w);
  float3 cDetailColorlev1 : packoffset(c10);
  float cDetailAlphaLev1 : packoffset(c10.w);
  float3 cDetailColorlev2 : packoffset(c11);
  float cDetailAlphaLev2 : packoffset(c11.w);
  float3 cDetailColorlev3 : packoffset(c12);
  float cDetailAlphaLev3 : packoffset(c12.w);
  float3 cDetailColorlev4 : packoffset(c13);
  float cDetailAlphaLev4 : packoffset(c13.w);
  float4 cDetailIndex : packoffset(c14);
  float cDetailUVLev1 : packoffset(c15);
  float cDetailUVLev2 : packoffset(c15.y);
  float cDetailUVLev3 : packoffset(c15.z);
  float cDetailUVLev4 : packoffset(c15.w);
  float4 cDetailAlphaWeight : packoffset(c16);
  float4 cDetailBaseMaskLev1 : packoffset(c17);
  float4 cDetailBaseMaskLev2 : packoffset(c18);
  float4 cDetailBaseMaskLev3 : packoffset(c19);
  float4 cDetailBaseMaskLev4 : packoffset(c20);
  float4 cDetailNormalIndex : packoffset(c21);
  float cDetailNormalUVLev1 : packoffset(c22);
  float cDetailNormalUVLev2 : packoffset(c22.y);
  float cDetailNormalUVLev3 : packoffset(c22.z);
  float cDetailNormalUVLev4 : packoffset(c22.w);
  float cDetailBlendModeLev1 : packoffset(c23);
  float cDetailBlendModeLev2 : packoffset(c23.y);
  float cDetailBlendModeLev3 : packoffset(c23.z);
  float cDetailBlendModeLev4 : packoffset(c23.w);
  float cDetailRoughOffsetLev1 : packoffset(c24);
  float cDetailRoughOffsetLev2 : packoffset(c24.y);
  float cDetailRoughOffsetLev3 : packoffset(c24.z);
  float cDetailRoughOffsetLev4 : packoffset(c24.w);
  float cDetailMetalOffsetLev1 : packoffset(c25);
  float cDetailMetalOffsetLev2 : packoffset(c25.y);
  float cDetailMetalOffsetLev3 : packoffset(c25.z);
  float cDetailMetalOffsetLev4 : packoffset(c25.w);
  float3 cVirtualSpec01Color : packoffset(c26);
  float cVirtualroughnessX : packoffset(c26.w);
  float3 cVirtualSpec02Color : packoffset(c27);
  float cVirtualroughnessY : packoffset(c27.w);
  float cSilkVirtualFabric : packoffset(c28);
  float cSilkSpecShift : packoffset(c28.y);
  float croughnessX : packoffset(c28.z);
  float croughnessY : packoffset(c28.w);
  float cFuzzTilling : packoffset(c29);
  float cFuzzSpecIns : packoffset(c29.y);
  float cFuzzRoughness : packoffset(c29.z);
  float cFuzzNormalInt : packoffset(c29.w);
  float cIsChiffon : packoffset(c30);
  float cChiffonPower : packoffset(c30.y);
  float2 LocalDetailCustom : packoffset(c30.z);
  float LocalDetailThreshold : packoffset(c31);
  float eInGraphLocalPosition : packoffset(c31.y);
  float3 eDyingColor : packoffset(c32);
  float eSaturateMinLum : packoffset(c32.w);
  float3 eScanEffectColor : packoffset(c33);
  float eScanEffectWidth : packoffset(c33.w);
  float eScanEffectDistance : packoffset(c34);
  float eScanEffectSpeed : packoffset(c34.y);
  float eScanEffectSlope : packoffset(c34.z);
  float eScanEffectIntensity : packoffset(c34.w);
  float3 eFresnelColor : packoffset(c35);
  float eFresnelPower : packoffset(c35.w);
  float eFresnelBreathFreq : packoffset(c36);
  float eFresnelBreathMinLum : packoffset(c36.y);
  float eFresnelMinIntensity : packoffset(c36.z);
  float eFresnelNoiseStrength : packoffset(c36.w);
  float4 eFresnelUVScrolling : packoffset(c37);
  float4 eFresnelNoiseUVScrolling : packoffset(c38);
  float3 eFresnelFadeCenter : packoffset(c39);
  float eFresnelFadeTargetRadius : packoffset(c39.w);
  float eFresnelFadePower : packoffset(c40);
  float eFresnelFadeRadius : packoffset(c40.y);
  float2 eFresnelProceNoiseInt : packoffset(c40.z);
  float eFresnelIntensity : packoffset(c41);
  float eFresnelAlphaPower : packoffset(c41.y);
  float eFresnelAlphaAdd : packoffset(c41.z);
  float eFresnelFadeUVFlag : packoffset(c41.w);
  float3 eDissipatedEdgeEmissionColor : packoffset(c42);
  float eDissipatedEmissionSoftness : packoffset(c42.w);
  float4 eDissipatedUVScrolling : packoffset(c43);
  float4 eDissipatedEdgeBaseColor : packoffset(c44);
  float4 eDissipatedNoiseUVScrolling : packoffset(c45);
  float4 eStencilOutputColor : packoffset(c46);
  float4 eStencilFlatColor : packoffset(c47);
  float eDissipatedNoiseStrength : packoffset(c48);
  float eDissipatedBaseControl : packoffset(c48.y);
  float eDissipatedEmissionControl : packoffset(c48.z);
  float eDissipatedBaseSoftness : packoffset(c48.w);
  float3 eTriPlanarMask : packoffset(c49);
  float eTriPlanarFlag : packoffset(c49.w);
  float2 eFresnelTexNoiseInt : packoffset(c50);
  float eDissipatedEmissionEdge : packoffset(c50.z);
  float eLocalYPositionFlag : packoffset(c50.w);
  float eMaxHeight : packoffset(c51);
  float eMinHeight : packoffset(c51.y);
  float eUsecEmissionParameters : packoffset(c51.z);
  float eEmissionNoiseStrength : packoffset(c51.w);
  float4 eEmissionNoiseUVScrolling : packoffset(c52);
  float4 eEmissionUVScrolling : packoffset(c53);
  float4 eEmissionMaskUVScrolling : packoffset(c54);
  float4 eEmissionScale : packoffset(c55);
  float eDissipatedBaseEdge : packoffset(c56);
  float eIsPlayerOverride : packoffset(c56.y);
  float eAlpha : packoffset(c56.z);
  float eSaturate : packoffset(c56.w);
  float eEmissionMaskPower : packoffset(c57);
  float eEmissionBaseFactor : packoffset(c57.y);
  float cDetailLocalBias : packoffset(c57.z);
  float IsColorize : packoffset(c57.w);
  float4 cCIFadeTime : packoffset(c58);
  float3 cCIMudBuff : packoffset(c59);
  float cCICheapWet : packoffset(c59.w);
  float cFilmStrength : packoffset(c60);
  float cFakeFilmColorRange : packoffset(c60.y);
  float cFakeFilmColorH : packoffset(c60.z);
  float cFakeFilmColorS : packoffset(c60.w);
  float3 cSparkleLayer1Color : packoffset(c61);
  float cSparkleLayer1Density : packoffset(c61.w);
  float3 cSparkleLayer2Color : packoffset(c62);
  float cSparkleLayer2Density : packoffset(c62.w);
  float cSparkleLayer1Intensity : packoffset(c63);
  float cSparkleLayer2Intensity : packoffset(c63.y);
  float cSparkleLayerLev1Size : packoffset(c63.z);
  float cSparkleLayerLev2Size : packoffset(c63.w);
  float2 cSparkleSizeRange : packoffset(c64);
  float2 cSparkleDensityRange : packoffset(c64.z);
  float cSparkleFrequency : packoffset(c65);
  float cBiasFarAwayShadow : packoffset(c65.y);
  float cLocalVirtualLitEAD : packoffset(c65.z);
  float4 cLocalVirtualLitPos : packoffset(c66);
  float4 cLocalVirtualLitColor : packoffset(c67);
  float4 cLocalVirtualLitCustom : packoffset(c68);
  float3 cDetailAlphaBlend : packoffset(c69);
  float cDeEyeAdaptionWeight : packoffset(c69.w);
  float3 cUnderWaterFactor : packoffset(c70);
  float FabricDiffuseColorWeight : packoffset(c70.w);
  float4 CustomIBLFlag : packoffset(c71);
  float4 cCISnowData : packoffset(c72);
  float4 cCISwitchData : packoffset(c73);
  float eEmissionMaskNoiseStrength : packoffset(c74);
  float LocalDetailInclude : packoffset(c74.y);
  float eDynamicFresnelIntensity : packoffset(c74.z);
  float cDyeingMaskTimeStart : packoffset(c74.w);
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

SamplerState sSkeletonSampler_s : register(s14);
Texture2DArray<float4> tPositionDeformTex : register(t11);
Texture2D<float4> tSkeletonMap : register(t14);


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
// Needs manual fix for instruction:
// unknown dcl_: dcl_input_sgv v8.x, vertex_id
  float4 r0,r1,r2,r3,r4,r5,r6,r7,r8,r9,r10,r11,r12,r13,r14,r15,r16,r17,r18,r19;
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
    bitmask.x = ((~(-1 << 2)) << 8) & 0xffffffff;  r3.x = (((uint)r4.y << 8) & bitmask.x) | ((uint)0 & ~bitmask.x);
    bitmask.x = ((~(-1 << 8)) << 0) & 0xffffffff;  r3.x = (((uint)r3.y << 0) & bitmask.x) | ((uint)r3.x & ~bitmask.x);
    bitmask.y = ((~(-1 << 3)) << 8) & 0xffffffff;  r3.y = (((uint)r3.w << 8) & bitmask.y) | ((uint)0 & ~bitmask.y);
    bitmask.y = ((~(-1 << 8)) << 0) & 0xffffffff;  r3.y = (((uint)r3.z << 0) & bitmask.y) | ((uint)r3.y & ~bitmask.y);
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
  } else {
    r1.xyzw = v1.xyzw;
    r0.xy = v3.xy;
  }
  r2.xyz = v2.xyz * float3(2,2,2) + float3(-1,-1,-1);
  r0.z = dot(v4.xyz, v4.xyz);
  r0.z = rsqrt(r0.z);
  r3.xyz = v4.xyz * r0.zzz;
  r0.z = dot(v5.xyz, v5.xyz);
  r0.z = rsqrt(r0.z);
  r4.xyz = v5.xyz * r0.zzz;
  // r1 is the decoded edited reference position.
  editOffset = r1.xyz - sourcePosition;
  r0.z = cmp(cVertexDeformType == 1);
  r7.xyz = r1.xyz;
  r0.w = 0;
  if (r0.z != 0) {
    uint layerCount = (asuint(cDeformationMisc) >> 24) & 255;
    uint currentLayer = asuint(cDeformationMisc) & 255;
    uint tangentLayer = (asuint(cDeformationMisc) >> 16) & 255;
    int2 sourcePixel = int2(sourceVertex & 255, sourceVertex >> 8);
    if (currentLayer < layerCount) {
      float4 cloth = tPositionDeformTex.Load(int4(sourcePixel, currentLayer, 0));
      r7.xyz = cloth.xyz + editOffset;
      r2.xyz = MIMIDecodeNormal(asuint(cloth.w));
      r0.w = 1;
    }
    if (layerCount > 0 && tangentLayer == layerCount - 1) {
      uint4 frame = asuint(tPositionDeformTex.Load(int4(sourcePixel, tangentLayer, 0)));
      float3 tangent = MIMIDecodeSigned16(uint3(frame.x, frame.x >> 16, frame.y));
      float3 binormal = MIMIDecodeSigned16(uint3(frame.z, frame.z >> 16, frame.w));
      r3.xyz = MIMINormalize(tangent, float3(1, 0, 0));
      r4.xyz = MIMINormalize(binormal, float3(0, 0, 1));
    }
  }
  r2.w = 1 + -v6.x;
  r2.w = -v6.y + r2.w;
  r2.w = -v6.z + r2.w;
  r5.xyzw = (int4)v7.xyzw * int4(3,3,3,3);
  r6.xyzw = mad(int4(3,3,3,3), (int4)v7.xxyy, int4(1,2,1,2));
  r8.xyzw = mad(int4(3,3,3,3), (int4)v7.zzww, int4(1,2,1,2));
  r9.xyzw = SkeletonData[r5.x].xyzw * v6.xxxx;
  r10.xyzw = SkeletonData[r5.y].xyzw * v6.yyyy;
  r9.xyzw = r10.xyzw + r9.xyzw;
  r10.xyzw = SkeletonData[r5.z].xyzw * v6.zzzz;
  r9.xyzw = r10.xyzw + r9.xyzw;
  r10.xyzw = SkeletonData[r5.w].xyzw * r2.wwww;
  r9.xyzw = r10.xyzw + r9.xyzw;
  r10.xyzw = SkeletonData[r6.x].xyzw * v6.xxxx;
  r11.xyzw = SkeletonData[r6.z].xyzw * v6.yyyy;
  r10.xyzw = r11.xyzw + r10.xyzw;
  r11.xyzw = SkeletonData[r8.x].xyzw * v6.zzzz;
  r10.xyzw = r11.xyzw + r10.xyzw;
  r11.xyzw = SkeletonData[r8.z].xyzw * r2.wwww;
  r10.xyzw = r11.xyzw + r10.xyzw;
  r11.xyzw = SkeletonData[r6.y].xyzw * v6.xxxx;
  r6.xyzw = SkeletonData[r6.w].xyzw * v6.yyyy;
  r6.xyzw = r11.xyzw + r6.xyzw;
  r11.xyzw = SkeletonData[r8.y].xyzw * v6.zzzz;
  r6.xyzw = r11.xyzw + r6.xyzw;
  r8.xyzw = SkeletonData[r8.w].xyzw * r2.wwww;
  r6.xyzw = r8.xyzw + r6.xyzw;
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
  r3.w = cmp(254.998993 < r1.w);
  r4.x = cmp(r1.w < 255.001007);
  r3.w = r3.w ? r4.x : 0;
  if (r3.w == 0) {
    r3.w = 0.00999999978 + VertexCompressionParams.x;
    r3.w = (uint)r3.w;
    r4.xyz = LocalBoundingBoxMax.xyz + -LocalBoundingBoxMin.xyz;
    r6.xyz = r1.xyz * r4.xyz + LocalBoundingBoxMin.xyz;
    r9.xy = cmp((int2)r3.ww == int2(1,2));
    r10.xyzw = r1.zyxw * float4(255,255,255,255) + float4(0.00999999978,0.00999999978,0.00999999978,0.00999999978);
    r10.xyzw = (uint4)r10.xyzw;
    if (3 == 0) r9.z = 0; else if (3+5 < 32) {     r9.z = (uint)r10.w << (32-(3 + 5)); r9.z = (uint)r9.z >> (32-3);    } else r9.z = (uint)r10.w >> 5;
    if (5 == 0) r9.w = 0; else if (5+3 < 32) {     r9.w = (uint)r10.w << (32-(5 + 3)); r9.w = (uint)r9.w >> (32-5);    } else r9.w = (uint)r10.w >> 3;
    bitmask.w = ((~(-1 << 24)) << 8) & 0xffffffff;  r1.w = (((uint)r9.z << 8) & bitmask.w) | ((uint)r10.x & ~bitmask.w);
    bitmask.w = ((~(-1 << 2)) << 8) & 0xffffffff;  r3.w = (((uint)r9.w << 8) & bitmask.w) | ((uint)0 & ~bitmask.w);
    bitmask.w = ((~(-1 << 8)) << 0) & 0xffffffff;  r3.w = (((uint)r10.y << 0) & bitmask.w) | ((uint)r3.w & ~bitmask.w);
    bitmask.w = ((~(-1 << 3)) << 8) & 0xffffffff;  r4.w = (((uint)r10.w << 8) & bitmask.w) | ((uint)0 & ~bitmask.w);
    bitmask.w = ((~(-1 << 8)) << 0) & 0xffffffff;  r4.w = (((uint)r10.z << 0) & bitmask.w) | ((uint)r4.w & ~bitmask.w);
    r10.x = (uint)r1.w;
    r10.y = (uint)r3.w;
    r10.z = (uint)r4.w;
    r4.xyz = r10.xyz * r4.xyz;
    r4.xyz = r4.xyz * float3(0.000488519785,0.000977517106,0.000488519785) + LocalBoundingBoxMin.xyz;
    r4.xyz = r9.yyy ? r4.xyz : r1.xyz;
    r1.xyz = r9.xxx ? r6.xyz : r4.xyz;
  }
  if (r0.z != 0) {
    r4.xy = cDeformationMisc >> int2(24,8);
    r4.xz = (int2)r4.xy & int2(255,255);
    r0.z = cmp((int)r4.z < (int)r4.x);
    if (r0.z != 0) {
      r0.z = sourceVertex;
      r1.w = 0.00390625 * r0.z;
      r4.y = (int)r1.w;
      r1.w = (uint)r4.y;
      r0.z = -r1.w * 256 + r0.z;
      r4.x = (int)r0.z;
      r4.w = 0;
      r4.xyz = tPositionDeformTex.Load(r4.xyzw).xyz;
      r4.xyz += editOffset; // Historical deformation needs the same edit.
    } else {
      r4.xyz = r1.xyz;
    }
  } else {
    r4.xyz = r1.xyz;
  }
  r6.xy = cmp(float2(9.99999975e-06,-0.00100000005) < VBufferParam.yw);
  r0.z = cmp(VBufferParam.y < 1);
  r0.z = r0.z ? r6.x : 0;
  if (r0.z != 0) {
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
    r9.xyzw = v6.yyyy * r9.xyzw;
    r9.xyzw = v6.xxxx * r11.xyzw + r9.xyzw;
    r9.xyzw = v6.zzzz * r16.xyzw + r9.xyzw;
    r9.xyzw = r2.wwww * r17.xyzw + r9.xyzw;
    r11.xyzw = v6.yyyy * r15.xyzw;
    r10.xyzw = v6.xxxx * r10.xyzw + r11.xyzw;
    r10.xyzw = v6.zzzz * r13.xyzw + r10.xyzw;
    r10.xyzw = r2.wwww * r19.xyzw + r10.xyzw;
    r11.xyzw = v6.yyyy * r14.xyzw;
    r11.xyzw = v6.xxxx * r12.xyzw + r11.xyzw;
    r11.xyzw = v6.zzzz * r18.xyzw + r11.xyzw;
    r5.xyzw = r2.wwww * r5.xyzw + r11.xyzw;
    r0.z = dot(r9.xyz, r4.xyz);
    r9.x = r0.z + r9.w;
    r0.z = dot(r10.xyz, r4.xyz);
    r9.y = r0.z + r10.w;
    r0.z = dot(r5.xyz, r4.xyz);
    r9.z = r0.z + r5.w;
    r4.xyz = r9.xyz;
  }
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
  r0.z = cmp(v6.x == 1.000000);
  r1.w = cmp((int)v7.y != (int)v7.x);
  r0.z = r0.z ? r1.w : 0;
  r0.z = r0.z ? 0 : 1;
  o9.w = max(r0.z, r0.w);
  o0.x = dot(r8.xyzw, WorldViewProj._m00_m10_m20_m30);
  o0.y = dot(r8.xyzw, WorldViewProj._m01_m11_m21_m31);
  o0.z = dot(r8.xyzw, WorldViewProj._m02_m12_m22_m32);
  r0.z = dot(r8.xyzw, WorldViewProj._m03_m13_m23_m33);
  r4.w = 1;
  r2.x = dot(r4.xyzw, LastWorldViewProjTex._m00_m10_m20_m30);
  r2.y = dot(r4.xyzw, LastWorldViewProjTex._m01_m11_m21_m31);
  r2.z = dot(r4.xyzw, LastWorldViewProjTex._m03_m13_m23_m33);
  r2.xyz = float3(0.00100000005,0.00100000005,0.00100000005) * r2.xyz;
  r2.w = 1;
  o8.xyzw = r6.yyyy ? r2.xyzw : float4(10,10,1,0);
  o7.x = CameraInfo.z * r0.z;
  r2.xyz = r8.xyz + -r1.xyz;
  p7.xyz = eInGraphLocalPosition * r2.xyz + r1.xyz;
  o0.w = r0.z;
  o1.xyzw = r0.xyxy;
  o2.w = r8.y;
  o3.w = 0;
  o4.w = 0;
  o5.w = 0;
  o6.xyzw = float4(1,1,1,0.5);
  o9.xyz = v2.xyz * float3(2,2,2) + float3(-1,-1,-1);
  return;
}

