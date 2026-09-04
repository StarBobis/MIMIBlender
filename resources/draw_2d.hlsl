// **** RESPONSIVE UI SHADER ****
// Contributors: SinsOfSeven
// Ispired by VV_Mod_Maker

Texture1D<float4> IniParams : register(t120);

#define SIZE IniParams[87].xy
#define OFFSET IniParams[87].zw
#define UI_STYLE IniParams[88].x
#define UI_PHASE IniParams[88].y
#define UI_INTENSITY IniParams[89].x

struct vs2ps {
	float4 pos : SV_Position0;
	float2 uv : TEXCOORD1;
};

static const float UI_STYLE_NONE = 0.0;
static const float UI_STYLE_BORDER = 5.0;

#ifdef VERTEX_SHADER
void main(
		out vs2ps output,
		uint vertex : SV_VertexID)
{
	float2 BaseCoord,Offset;
	Offset.x = OFFSET.x*2-1;
	Offset.y = (1-OFFSET.y)*2-1;
	BaseCoord.xy = float2((2*SIZE.x),(2*(-SIZE.y)));
	// Not using vertex buffers so manufacture our own coordinates.
	switch(vertex) {
		case 0:
			output.pos.xy = float2(BaseCoord.x+Offset.x, BaseCoord.y+Offset.y);
			output.uv = float2(1,0);
			break;
		case 1:
			output.pos.xy = float2(BaseCoord.x+Offset.x, 0+Offset.y);
			output.uv = float2(1,1);
			break;
		case 2:
			output.pos.xy = float2(0+Offset.x, BaseCoord.y+Offset.y);
			output.uv = float2(0,0);
			break;
		case 3:
			output.pos.xy = float2(0+Offset.x, 0+Offset.y);
			output.uv = float2(0,1);
			break;
		default:
			output.pos.xy = 0;
			output.uv = float2(0,0);
			break;
	};
	output.pos.zw = float2(0, 1);
}
#endif

#ifdef PIXEL_SHADER
Texture2D<float4> tex : register(t100);

float3 neon_palette(float t)
{
	return 0.55 + 0.45 * cos(6.2831853 * (frac(t) + float3(0.00, 0.18, 0.36)));
}

float get_border_mask(float2 safe_size)
{
	float aspect_ratio = min(safe_size.x, safe_size.y) / max(safe_size.x, safe_size.y);
	return saturate((0.08 - aspect_ratio) / 0.08);
}

float3 apply_neon_border(float3 base_rgb, float2 uv, float2 safe_size, float phase, float intensity)
{
	if (intensity <= 0.001)
	{
		return base_rgb;
	}

	float is_horizontal = step(safe_size.y, safe_size.x);
	float long_axis = lerp(uv.y, uv.x, is_horizontal);
	float thin_axis_dist = lerp(abs(uv.x * 2 - 1), abs(uv.y * 2 - 1), is_horizontal);
	float flow = long_axis * 0.92 - phase * 0.16;
	float wave_a = 0.5 + 0.5 * cos(6.2831853 * (flow * 1.10 + 0.08));
	float wave_b = 0.5 + 0.5 * cos(6.2831853 * (flow * 1.85 - 0.27));
	float wave_c = 0.5 + 0.5 * cos(6.2831853 * (flow * 2.90 + thin_axis_dist * 0.22 + 0.41));
	float ribbon = pow(saturate(wave_a * 0.50 + wave_b * 0.35 + wave_c * 0.15), 1.65);
	float shimmer = pow(saturate(wave_b * 0.55 + wave_c * 0.45), 2.4);

	float3 neon_ramp = neon_palette(flow * 0.42 + wave_b * 0.12);
	float3 neon_ramp_alt = neon_palette(flow * 0.42 + 0.18 + wave_c * 0.10);
	float3 sweep_color = lerp(neon_ramp, neon_ramp_alt, 0.5 + 0.5 * wave_a);
	float edge_glow = pow(saturate(1.0 - thin_axis_dist), 1.9);
	float glow_strength = lerp(0.75, 1.25, saturate(intensity));

	float3 neon_border = lerp(base_rgb * 0.18 + float3(0.05, 0.06, 0.08), neon_ramp, 0.82 + 0.08 * ribbon);
	neon_border += neon_ramp * edge_glow * (0.28 + 0.18 * ribbon) * glow_strength;
	neon_border += sweep_color * edge_glow * shimmer * 0.26;
	neon_border += neon_ramp_alt * edge_glow * ribbon * 0.18;
	return saturate(neon_border);
}

void main(vs2ps input, out float4 result : SV_Target0)
{
	float2 dims;
	tex.GetDimensions(dims.x, dims.y);
	if (dims.x <= 0.0 || dims.y <= 0.0) discard;
	input.uv.y = 1 - input.uv.y;

	float2 uv = saturate(input.uv);
	int2 texel = min(int2(uv * dims), int2(dims - 1.0));
	float4 base = tex.Load(int3(texel, 0));
	float resolved_alpha = saturate(base.a);
	if (UI_STYLE < UI_STYLE_BORDER - 0.5)
	{
		result = float4(base.rgb, resolved_alpha);
		return;
	}

	float2 safe_size = max(SIZE, float2(0.0001, 0.0001));
	float blend_mask = saturate(get_border_mask(safe_size) * resolved_alpha * 1.25);
	float effect_enabled = step(0.001, UI_INTENSITY);
	float3 final_rgb = lerp(base.rgb, apply_neon_border(base.rgb, uv, safe_size, UI_PHASE, UI_INTENSITY), blend_mask * effect_enabled);
	result = float4(final_rgb, resolved_alpha);
}
#endif
