"""Bake Chinese HUD labels as shader bitmasks, without a runtime font API.

Run on Windows with Pillow installed. The generated rows are committed, so
Blender and exported mods need neither Pillow nor the font at runtime.
The preview is always placed under tmp, never beside repository sources.
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
LABELS = ['按键', '形变', '绘制', '通道', '位置', '拾取', '拖拽', '实际', '预期', '槽位']
NAMES = ['key', 'deform', 'draw', 'pass', 'position', 'pick', 'drag', 'actual', 'expected', 'slot']


def main():
    """Rasterize each two-character label into a 32 by 16 pixel cell."""
    font = ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',16)
    rows = []
    preview = Image.new('RGB',(6*76,64),(12,16,20))
    for index,label in enumerate(LABELS):
        glyph = Image.new('1',(32,16))
        top = font.getbbox(label)[1]
        ImageDraw.Draw(glyph).text((0,-top),label,font=font,fill=1)
        values = [sum(int(bool(glyph.getpixel((x,y)))) << (31-x) for x in range(32)) for y in range(16)]
        rows.append('    // ' + NAMES[index] + '\n    ' + ','.join(f'0x{v:08x}u' for v in values) + ',')
        # Preview the exact binary rows sampled by the shader, at 2x scale.
        mask = glyph.convert('L').resize((64,32),Image.Resampling.NEAREST)
        preview.paste((51,255,115),((index%6)*76,(index//6)*32),mask)
    block = '// BEGIN HUD GLYPHS\nstatic const uint GlyphRows[160] = {\n' + '\n'.join(rows) + '\n};\n// END HUD GLYPHS'
    shader = ROOT/'resources/interaction/drag/debug_ps.hlsl'
    source = shader.read_text(encoding='utf-8')
    start,end = source.index('// BEGIN HUD GLYPHS'),source.index('// END HUD GLYPHS')+len('// END HUD GLYPHS')
    shader.write_text(source[:start]+block+source[end:],encoding='utf-8')
    (ROOT/'tmp').mkdir(exist_ok=True)
    preview.save(ROOT/'tmp/interaction_hud_labels.png')


if __name__=='__main__':
    main()
