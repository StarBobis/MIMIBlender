// YYSLS main cloth variant 873adf1f14b3109d. Preserve the game's COLOR0
// input and output and the original current, historical and tangent branches.
Buffer<uint> MIMIClothSource : register(t118);

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
  float4 cDetailUV : packoffset(c15);
  float4 cDetailAlphaWeight : packoffset(c16);
  float4 cDetailBaseMaskLev1 : packoffset(c17);
  float4 cDetailBaseMaskLev2 : packoffset(c18);
  float4 cDetailBaseMaskLev3 : packoffset(c19);
  float4 cDetailBaseMaskLev4 : packoffset(c20);
  float4 cDetailNormalIndex : packoffset(c21);
  float4 cDetailNormalUV : packoffset(c22);
  float4 cDetailBlendMode : packoffset(c23);
  float4 cDetailRoughOffset : packoffset(c24);
  float4 cDetailMetalOffset : packoffset(c25);
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
  float3 cSparkleLayer1Color : packoffset(c60);
  float cSparkleLayer1Density : packoffset(c60.w);
  float3 cSparkleLayer2Color : packoffset(c61);
  float cSparkleLayer2Density : packoffset(c61.w);
  float cSparkleLayer1Intensity : packoffset(c62);
  float cSparkleLayer2Intensity : packoffset(c62.y);
  float cSparkleLayerLev1Size : packoffset(c62.z);
  float cSparkleLayerLev2Size : packoffset(c62.w);
  float2 cSparkleSizeRange : packoffset(c63);
  float2 cSparkleDensityRange : packoffset(c63.z);
  float cSparkleLayerSizeMobile : packoffset(c64);
  float cDeEyeAdaptionSparkleMobile : packoffset(c64.y);
  float cSparkleFrequency : packoffset(c64.z);
  float cBiasFarAwayShadow : packoffset(c64.w);
  float cLocalVirtualLitEAD : packoffset(c65);
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
  float4 v2 : COLOR0,
  float4 v3 : NORMAL0,
  float2 v4 : TEXCOORD0,
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
  float4 r0,r1,r2,r3,r4,r5,r6,r7,r8,r9,r10,r11,r12,r13,r14,r15,r16,r17,r18;
  uint4 bitmask, uiDest;
  float4 fDest;

  r0.x = cmp(254.998993 < v1.w);
  r0.y = cmp(v1.w < 255.001007);
  r0.x = r0.y ? r0.x : 0;
  r0.yz = float2(0.00999999978,0.00999999978) + VertexCompressionParams.xy;
  r0.y = (uint)r0.y;
  r1.xyz = LocalBoundingBoxMax.xyz + -LocalBoundingBoxMin.xyz;
  r2.xyz = v1.zyx * r1.zyx + LocalBoundingBoxMin.zyx;
  r0.z = (int)r0.z;
  r0.z = cmp((int)r0.z >= 1);
  r3.xyzw = v4.xyxy * float4(2,2,2,2) + float4(-0.5,-0.5,-0.5,-0.5);
  r3.xyzw = r0.zzzz ? r3.xyzw : v4.xyxy;
  r0.yz = cmp((int2)r0.yy == int2(1,2));
  r4.xyzw = v1.zyxw * float4(255,255,255,255) + float4(0.00999999978,0.00999999978,0.00999999978,0.00999999978);
  r4.xyzw = (uint4)r4.xyzw;
  bitmask.x = ((~(-1 << 8)) << 3) & 0xffffffff;  r5.x = (((uint)r4.w << 3) & bitmask.x) | ((uint)0 & ~bitmask.x);
  bitmask.y = ((~(-1 << 8)) << 5) & 0xffffffff;  r5.y = (((uint)r4.w << 5) & bitmask.y) | ((uint)0 & ~bitmask.y);
  bitmask.z = ((~(-1 << 3)) << 8) & 0xffffffff;  r5.z = (((uint)r4.w << 8) & bitmask.z) | ((uint)0 & ~bitmask.z);
  r0.w = (int)r5.y & 768;
  bitmask.w = ((~(-1 << 8)) << 0) & 0xffffffff;  r0.w = (((uint)r4.y << 0) & bitmask.w) | ((uint)r0.w & ~bitmask.w);
  bitmask.x = ((~(-1 << 8)) << 0) & 0xffffffff;  r4.x = (((uint)r4.z << 0) & bitmask.x) | ((uint)r5.z & ~bitmask.x);
  bitmask.y = ((~(-1 << 8)) << 0) & 0xffffffff;  r4.y = (((uint)r4.x << 0) & bitmask.y) | ((uint)r5.x & ~bitmask.y);
  r4.xz = (uint2)r4.xy;
  r4.y = (uint)r0.w;
  r4.xyz = r4.xyz * r1.zyx;
  r4.xyz = r4.xyz * float3(0.000488519785,0.000977517106,0.000488519785) + LocalBoundingBoxMin.zyx;
  r4.w = 255;
  r4.xyzw = r0.zzzz ? r4.xyzw : v1.zyxw;
  r2.w = 255;
  r2.xyzw = r0.yyyy ? r2.xyzw : r4.xyzw;
  r0.w = (int)r0.y | (int)r0.z;
  r3.xyzw = r0.wwww ? r3.xyzw : v4.xyxy;
  r2.xyzw = r0.xxxx ? v1.zyxw : r2.xyzw;
  o1.xyzw = r0.xxxx ? v4.xyxy : r3.xyzw;
  r3.xyz = v3.xyz * float3(2,2,2) + float3(-1,-1,-1);
  r0.x = dot(v5.xyz, v5.xyz);
  r0.x = rsqrt(r0.x);
  r4.xyz = v5.xyz * r0.xxx;
  r0.x = dot(v6.xyz, v6.xyz);
  r0.x = rsqrt(r0.x);
  r5.xyz = v6.xyz * r0.xxx;
  // The game expects positions for the original simulation ID. Apply the
  // vertex edit to position layers only; packed frames must remain untouched.
  uint mapBase = v9 * 4;
  uint sourceVertex = MIMIClothSource[mapBase + 3];
  bool useNativeCloth = cVertexDeformType == 1 && sourceVertex != 0xffffffffu;
  uint packedLayers = asuint(cDeformationMisc);
  uint layerCount = (packedLayers >> 24) & 255;
  int2 sourcePixel = int2(sourceVertex & 255, sourceVertex >> 8);
  float3 editOffset = 0;
  r8.xyz = r2.zyx;
  r0.w = 0;
  if (useNativeCloth) {
    float3 referencePosition = asfloat(uint3(MIMIClothSource[mapBase],
      MIMIClothSource[mapBase + 1], MIMIClothSource[mapBase + 2]));
    editOffset = r8.xyz - referencePosition;
    uint currentLayer = packedLayers & 255;
    uint tangentLayer = (packedLayers >> 16) & 255;
    if (currentLayer < layerCount) {
      float4 cloth = tPositionDeformTex.Load(int4(sourcePixel, currentLayer, 0));
      r8.xyz = cloth.xyz + editOffset;
      r3.xyz = MIMIDecodeNormal(asuint(cloth.w));
      r0.w = 1;
    }
    if (layerCount > 0 && tangentLayer == layerCount - 1) {
      uint4 frame = asuint(tPositionDeformTex.Load(int4(sourcePixel, tangentLayer, 0)));
      r4.xyz = MIMINormalize(MIMIDecodeSigned16(uint3(frame.x, frame.x >> 16, frame.y)), float3(1, 0, 0));
      r5.xyz = MIMINormalize(MIMIDecodeSigned16(uint3(frame.z, frame.z >> 16, frame.w)), float3(0, 0, 1));
    }
  }
  r1.w = 1 + -v7.x;
  r1.w = -v7.y + r1.w;
  r1.w = -v7.z + r1.w;
  r6.xyzw = (int4)v8.xyzw * int4(3,3,3,3);
  r7.xyzw = mad(int4(3,3,3,3), (int4)v8.xxyy, int4(1,2,1,2));
  r9.xyzw = mad(int4(3,3,3,3), (int4)v8.zzww, int4(1,2,1,2));
  r10.xyzw = SkeletonData[r6.x].xyzw * v7.xxxx;
  r11.xyzw = SkeletonData[r6.y].xyzw * v7.yyyy;
  r10.xyzw = r11.xyzw + r10.xyzw;
  r11.xyzw = SkeletonData[r6.z].xyzw * v7.zzzz;
  r10.xyzw = r11.xyzw + r10.xyzw;
  r11.xyzw = SkeletonData[r6.w].xyzw * r1.wwww;
  r10.xyzw = r11.xyzw + r10.xyzw;
  r11.xyzw = SkeletonData[r7.x].xyzw * v7.xxxx;
  r12.xyzw = SkeletonData[r7.z].xyzw * v7.yyyy;
  r11.xyzw = r12.xyzw + r11.xyzw;
  r12.xyzw = SkeletonData[r9.x].xyzw * v7.zzzz;
  r11.xyzw = r12.xyzw + r11.xyzw;
  r12.xyzw = SkeletonData[r9.z].xyzw * r1.wwww;
  r11.xyzw = r12.xyzw + r11.xyzw;
  r12.xyzw = SkeletonData[r7.y].xyzw * v7.xxxx;
  r7.xyzw = SkeletonData[r7.w].xyzw * v7.yyyy;
  r7.xyzw = r12.xyzw + r7.xyzw;
  r12.xyzw = SkeletonData[r9.y].xyzw * v7.zzzz;
  r7.xyzw = r12.xyzw + r7.xyzw;
  r9.xyzw = SkeletonData[r9.w].xyzw * r1.wwww;
  r7.xyzw = r9.xyzw + r7.xyzw;
  r3.w = dot(r10.xyz, r8.xyz);
  r9.x = r3.w + r10.w;
  r3.w = dot(r11.xyz, r8.xyz);
  r9.y = r3.w + r11.w;
  r3.w = dot(r7.xyz, r8.xyz);
  r9.z = r3.w + r7.w;
  r8.x = dot(r10.xyz, r3.xyz);
  r8.y = dot(r11.xyz, r3.xyz);
  r8.z = dot(r7.xyz, r3.xyz);
  r3.x = dot(r10.xyz, r4.xyz);
  r3.y = dot(r11.xyz, r4.xyz);
  r3.z = dot(r7.xyz, r4.xyz);
  r4.x = dot(r10.xyz, r5.xyz);
  r4.y = dot(r11.xyz, r5.xyz);
  r4.z = dot(r7.xyz, r5.xyz);
  r3.w = cmp(254.998993 < r2.w);
  r4.w = cmp(r2.w < 255.001007);
  r3.w = r3.w ? r4.w : 0;
  r5.xyz = r2.zyx * r1.xyz + LocalBoundingBoxMin.xyz;
  r7.xyzw = r2.xyzw * float4(255,255,255,255) + float4(0.00999999978,0.00999999978,0.00999999978,0.00999999978);
  r7.xyzw = (uint4)r7.xyzw;
  bitmask.x = ((~(-1 << 8)) << 3) & 0xffffffff;  r10.x = (((uint)r7.w << 3) & bitmask.x) | ((uint)0 & ~bitmask.x);
  bitmask.y = ((~(-1 << 8)) << 5) & 0xffffffff;  r10.y = (((uint)r7.w << 5) & bitmask.y) | ((uint)0 & ~bitmask.y);
  bitmask.z = ((~(-1 << 3)) << 8) & 0xffffffff;  r10.z = (((uint)r7.w << 8) & bitmask.z) | ((uint)0 & ~bitmask.z);
  r2.w = (int)r10.y & 768;
  bitmask.w = ((~(-1 << 8)) << 0) & 0xffffffff;  r2.w = (((uint)r7.y << 0) & bitmask.w) | ((uint)r2.w & ~bitmask.w);
  bitmask.x = ((~(-1 << 8)) << 0) & 0xffffffff;  r7.x = (((uint)r7.x << 0) & bitmask.x) | ((uint)r10.x & ~bitmask.x);
  bitmask.y = ((~(-1 << 8)) << 0) & 0xffffffff;  r7.y = (((uint)r7.z << 0) & bitmask.y) | ((uint)r10.z & ~bitmask.y);
  r7.yw = (uint2)r7.xy;
  r7.z = (uint)r2.w;
  r1.xyz = r7.yzw * r1.xyz;
  r1.xyz = r1.xyz * float3(0.000488519785,0.000977517106,0.000488519785) + LocalBoundingBoxMin.xyz;
  r1.xyz = r0.zzz ? r1.xyz : r2.zyx;
  r1.xyz = r0.yyy ? r5.xyz : r1.xyz;
  r1.xyz = r3.www ? r2.zyx : r1.xyz;
  // Missing map entries and unavailable history keep the regular position.
  uint historyLayer = (packedLayers >> 8) & 255;
  r2.xyz = r1.xyz;
  if (useNativeCloth && historyLayer < layerCount)
    r2.xyz = tPositionDeformTex.Load(int4(sourcePixel, historyLayer, 0)).xyz + editOffset;
  r0.xy = cmp(float2(9.99999975e-06,-0.00100000005) < VBufferParam.yw);
  r0.z = cmp(VBufferParam.y < 1);
  r0.x = r0.z ? r0.x : 0;
  if (r0.x != 0) {
    r5.xyzw = (uint4)r6.xyzw;
    r6.xyzw = float4(0.5,1.5,2.5,0.5) + r5.xxxy;
    r6.xyzw = VBufferParam.zzzz * r6.zxwy;
    r7.xz = r6.yw;
    r7.yw = float2(0,0);
    r7.xyzw = VBufferParam.xyxy + r7.xyzw;
    r10.xyzw = tSkeletonMap.SampleLevel(sSkeletonSampler_s, r7.xy, 0).xyzw;
    r7.xyzw = tSkeletonMap.SampleLevel(sSkeletonSampler_s, r7.zw, 0).xyzw;
    r6.yw = float2(0,0);
    r6.xyzw = VBufferParam.xyxy + r6.xyzw;
    r11.xyzw = tSkeletonMap.SampleLevel(sSkeletonSampler_s, r6.xy, 0).xyzw;
    r6.xyzw = tSkeletonMap.SampleLevel(sSkeletonSampler_s, r6.zw, 0).xyzw;
    r12.xyzw = float4(1.5,2.5,0.5,1.5) + r5.yyzz;
    r12.xyzw = VBufferParam.zzzz * r12.zxwy;
    r13.xz = r12.yw;
    r13.yw = float2(0,0);
    r13.xyzw = VBufferParam.xyxy + r13.xyzw;
    r14.xyzw = tSkeletonMap.SampleLevel(sSkeletonSampler_s, r13.xy, 0).xyzw;
    r13.xyzw = tSkeletonMap.SampleLevel(sSkeletonSampler_s, r13.zw, 0).xyzw;
    r12.yw = float2(0,0);
    r12.xyzw = VBufferParam.xyxy + r12.xyzw;
    r15.xyzw = tSkeletonMap.SampleLevel(sSkeletonSampler_s, r12.xy, 0).xyzw;
    r12.xyzw = tSkeletonMap.SampleLevel(sSkeletonSampler_s, r12.zw, 0).xyzw;
    r5.xyzw = float4(2.5,0.5,1.5,2.5) + r5.zwww;
    r5.xyzw = VBufferParam.zzzz * r5.zxwy;
    r16.xz = r5.yw;
    r16.yw = float2(0,0);
    r16.xyzw = VBufferParam.xyxy + r16.xyzw;
    r17.xyzw = tSkeletonMap.SampleLevel(sSkeletonSampler_s, r16.xy, 0).xyzw;
    r16.xyzw = tSkeletonMap.SampleLevel(sSkeletonSampler_s, r16.zw, 0).xyzw;
    r5.yw = float2(0,0);
    r5.xyzw = VBufferParam.xyxy + r5.xyzw;
    r18.xyzw = tSkeletonMap.SampleLevel(sSkeletonSampler_s, r5.xy, 0).xyzw;
    r5.xyzw = tSkeletonMap.SampleLevel(sSkeletonSampler_s, r5.zw, 0).xyzw;
    r6.xyzw = v7.yyyy * r6.xyzw;
    r6.xyzw = v7.xxxx * r10.xyzw + r6.xyzw;
    r6.xyzw = v7.zzzz * r15.xyzw + r6.xyzw;
    r6.xyzw = r1.wwww * r16.xyzw + r6.xyzw;
    r10.xyzw = v7.yyyy * r14.xyzw;
    r7.xyzw = v7.xxxx * r7.xyzw + r10.xyzw;
    r7.xyzw = v7.zzzz * r12.xyzw + r7.xyzw;
    r7.xyzw = r1.wwww * r18.xyzw + r7.xyzw;
    r10.xyzw = v7.yyyy * r13.xyzw;
    r10.xyzw = v7.xxxx * r11.xyzw + r10.xyzw;
    r10.xyzw = v7.zzzz * r17.xyzw + r10.xyzw;
    r5.xyzw = r1.wwww * r5.xyzw + r10.xyzw;
    r0.x = dot(r6.xyz, r2.xyz);
    r6.x = r0.x + r6.w;
    r0.x = dot(r7.xyz, r2.xyz);
    r6.y = r0.x + r7.w;
    r0.x = dot(r5.xyz, r2.xyz);
    r6.z = r0.x + r5.w;
    r2.xyz = r6.xyz;
  }
  r9.w = 1;
  o2.x = dot(r9.xyzw, World._m00_m10_m20_m30);
  o2.y = dot(r9.xyzw, World._m01_m11_m21_m31);
  o2.z = dot(r9.xyzw, World._m02_m12_m22_m32);
  r5.x = dot(r8.xyz, World._m00_m10_m20);
  r5.y = dot(r8.xyz, World._m01_m11_m21);
  r5.z = dot(r8.xyz, World._m02_m12_m22);
  r0.x = dot(r5.xyz, r5.xyz);
  r0.x = rsqrt(r0.x);
  o3.xyz = r5.xyz * r0.xxx;
  r5.x = dot(r3.xyz, World._m00_m10_m20);
  r5.y = dot(r3.xyz, World._m01_m11_m21);
  r5.z = dot(r3.xyz, World._m02_m12_m22);
  r0.x = dot(r5.xyz, r5.xyz);
  r0.x = rsqrt(r0.x);
  o4.xyz = r5.xyz * r0.xxx;
  r3.x = dot(r4.xyz, World._m00_m10_m20);
  r3.y = dot(r4.xyz, World._m01_m11_m21);
  r3.z = dot(r4.xyz, World._m02_m12_m22);
  r0.x = dot(r3.xyz, r3.xyz);
  r0.x = rsqrt(r0.x);
  o5.xyz = r3.xyz * r0.xxx;
  r0.x = cmp(v7.x == 1.000000);
  r0.z = cmp((int)v8.y != (int)v8.x);
  r0.x = r0.z ? r0.x : 0;
  r0.x = r0.x ? 0 : 1;
  o9.w = max(r0.x, r0.w);
  o0.x = dot(r9.xyzw, WorldViewProj._m00_m10_m20_m30);
  o0.y = dot(r9.xyzw, WorldViewProj._m01_m11_m21_m31);
  o0.z = dot(r9.xyzw, WorldViewProj._m02_m12_m22_m32);
  r0.x = dot(r9.xyzw, WorldViewProj._m03_m13_m23_m33);
  r2.w = 1;
  r3.x = dot(r2.xyzw, LastWorldViewProjTex._m00_m10_m20_m30);
  r3.y = dot(r2.xyzw, LastWorldViewProjTex._m01_m11_m21_m31);
  r3.z = dot(r2.xyzw, LastWorldViewProjTex._m03_m13_m23_m33);
  r2.xyz = float3(0.00100000005,0.00100000005,0.00100000005) * r3.xyz;
  r2.w = 1;
  o8.xyzw = r0.yyyy ? r2.xyzw : float4(10,10,1,0);
  o7.x = CameraInfo.z * r0.x;
  r0.yzw = r9.xyz + -r1.xyz;
  p7.xyz = eInGraphLocalPosition * r0.yzw + r1.xyz;
  o0.w = r0.x;
  o2.w = r9.y;
  o3.w = 0;
  o4.w = 0;
  o5.w = 0;
  o6.xyzw = v2.xyzw;
  o9.xyz = v3.xyz * float3(2,2,2) + float3(-1,-1,-1);
  return;
}
