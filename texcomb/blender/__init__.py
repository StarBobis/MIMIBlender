"""Blender-side adapters for the texture combiner.

Modules in this package may import bpy and the bpy-dependent texcomb.utils.
They translate Blender state (materials, packed files, scene settings) into
the plain data the bpy-free texcomb.core pipeline works with, and translate
the results back. Nothing here does image math itself; that all lives in
texcomb.core.
"""
