"""Generic interaction deformation support.

The interaction feature deforms named regions of a mesh at runtime.  The
maths and the export plumbing live here so every game preset can reuse
them; a preset only has to state whether its meshes can carry the
deformation and how its position buffer is laid out.

The module is split into small pieces:

* weight_field: the surface gradient maths of the control weight field.
* vertex_layout: the position layout the runtime shader can read.
* collector: samples the Blender vertex groups during the export.
* runtime: assembles the buffers and writes the INI sections.
* backend: the per-preset capability declaration.
"""
