"""Pure-python core of the texture combiner pipeline.

This package holds the image math of the atlas builder: decoding, channel
merging, resizing, and composition. It deliberately has NO bpy imports, so
it can be unit-tested with plain pytest outside Blender and reused later by
thin bpy adapters.

Design rules (keep these invariants, they are what makes the result precise):
- All pixel data is float32 numpy arrays of shape (height, width, 4).
- All colors are linear (not sRGB) unless a function name says otherwise.
- The alpha channel is data: it is never run through colorspace conversion.
- Slow and obviously-correct beats fast and clever.
"""
