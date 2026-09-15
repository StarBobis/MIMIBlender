"""End-to-end functional test for the texcomb combiner, run inside Blender.

Run with Blender 5.2:
    "C:\\Program Files\\Blender Foundation\\Blender 5.2\\blender.exe" ^
        -b --factory-startup --python tools/texcomb_e2e_test.py

The test builds a small scene with three materials:
  A: red base texture with embedded alpha 0.5
  B: green base texture + a SEPARATE alpha texture (gray 0.7) linked to the
     Principled BSDF Alpha input
  C: solid blue, no texture (solid-color fallback path)

Then it runs bpy.ops.mimi.combiner and verifies the generated atlas:
  - the atlas file exists on disk;
  - the atlas contains red, green and blue regions;
  - the alpha channel carries ~0.5 for A (embedded), ~0.7 for B (from the
    separate alpha texture, NOT from B's opaque base), and 1.0 for C;
  - the object was rebound to the generated atlas material.

Exits with code 0 on success and 1 on the first failed assertion.
"""

import os
import sys
import tempfile

# Make the addon package importable: the repo root is the package itself, so
# its parent directory must be on sys.path (same as Blender's addon folder).
_REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PARENT_DIR = os.path.dirname(_REPO_DIR)
for _path in (_PARENT_DIR, os.path.join(_REPO_DIR, "texcomb", "libs")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import bpy  # noqa: E402
from PIL import Image  # noqa: E402  (vendored Pillow from texcomb/libs)

_FAILURES = []


def check(label, condition):
    """Record one assertion result and print it immediately."""
    status = "PASS" if condition else "FAIL"
    print("[E2E {}] {}".format(status, label))
    if not condition:
        _FAILURES.append(label)


def _write_png(path, rgba):
    """Write a solid-color 4x4 RGBA PNG with vendored Pillow."""
    Image.new("RGBA", (4, 4), rgba).save(path)


def _make_textured_material(name, base_path, alpha_path=None):
    """Create a Principled material with a base image and optional alpha."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    node_tree = mat.node_tree
    bsdf = next(n for n in node_tree.nodes if n.type == "BSDF_PRINCIPLED")

    base_node = node_tree.nodes.new(type="ShaderNodeTexImage")
    base_node.image = bpy.data.images.load(base_path)
    node_tree.links.new(base_node.outputs["Color"], bsdf.inputs["Base Color"])

    if alpha_path is not None:
        # Separate alpha texture: drives the BSDF Alpha input from the
        # image's own Alpha output socket.
        alpha_node = node_tree.nodes.new(type="ShaderNodeTexImage")
        alpha_node.image = bpy.data.images.load(alpha_path)
        node_tree.links.new(alpha_node.outputs["Alpha"], bsdf.inputs["Alpha"])
    return mat


def _make_solid_material(name, color):
    """Create a Principled material with a flat base color, no texture."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Base Color"].default_value = color
    return mat


def main():
    workdir = tempfile.mkdtemp(prefix="texcomb_e2e_")
    base_a = os.path.join(workdir, "base_a.png")
    base_b = os.path.join(workdir, "base_b.png")
    alpha_b = os.path.join(workdir, "alpha_b.png")
    _write_png(base_a, (255, 0, 0, 128))    # red, embedded alpha ~0.5
    _write_png(base_b, (0, 255, 0, 255))    # opaque green
    _write_png(alpha_b, (255, 255, 255, 179))  # white, alpha ~0.7

    # Enable the addon through Blender's addon system.
    bpy.ops.preferences.addon_enable(module="MIMIBlender")

    # Clean scene, then add a 2x2-face grid (it comes with a UV map).
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=3, y_subdivisions=3)
    obj = bpy.context.active_object

    mat_a = _make_textured_material("mat_a", base_a)
    mat_b = _make_textured_material("mat_b", base_b, alpha_b)
    mat_c = _make_solid_material("mat_c", (0.05, 0.1, 0.8, 1.0))
    for mat in (mat_a, mat_b, mat_c):
        obj.data.materials.append(mat)
    # Faces 0,1 -> mat_a; face 2 -> mat_b; face 3 -> mat_c.
    obj.data.polygons[0].material_index = 0
    obj.data.polygons[1].material_index = 0
    obj.data.polygons[2].material_index = 1
    obj.data.polygons[3].material_index = 2

    # Run the combiner. Uniform size keeps the atlas small for the test.
    scene = bpy.context.scene
    scene.mimi_smc_uniform_size_value = 64
    scene.mimi_smc_include_extra_textures = False
    bpy.ops.mimi.combiner(directory=workdir)

    # --- Verify the atlas file on disk ------------------------------------
    atlases = [f for f in os.listdir(workdir) if f.startswith("Atlas_")]
    check("atlas file written", len(atlases) == 1)
    if not atlases:
        print("[E2E] no atlas produced, aborting checks")
        sys.exit(1)

    atlas_path = os.path.join(workdir, atlases[0])
    with Image.open(atlas_path) as opened:
        atlas = opened.convert("RGBA")
        pixels = list(atlas.getdata())
    reds = [p for p in pixels if p[0] > 150 and p[1] < 100]
    greens = [p for p in pixels if p[1] > 150 and p[0] < 150]
    blues = [p for p in pixels if p[2] > 150 and p[0] < 100]
    check("atlas contains the red region (mat A)", len(reds) > 100)
    check("atlas contains the green region (mat B)", len(greens) > 100)
    check("atlas contains the blue region (mat C)", len(blues) > 100)

    # --- Verify the alpha channel semantics -------------------------------
    check(
        "mat A alpha ~128 embedded from its base texture",
        any(abs(p[3] - 128) <= 4 for p in reds),
    )
    # mat B's own base texture is opaque (255): a value near 179 proves the
    # alpha came from the SEPARATE alpha texture.
    check(
        "mat B alpha ~179 from the separate alpha texture",
        any(abs(p[3] - 179) <= 4 for p in greens),
    )
    check("mat C alpha fully opaque", all(p[3] == 255 for p in blues))

    # --- Verify the object got the combined material ----------------------
    slot_names = [s.material.name for s in obj.material_slots if s.material]
    check(
        "object rebound to atlas material",
        any(name.startswith("material_atlas_") for name in slot_names),
    )
    check(
        "original materials removed from the object",
        not any(name in slot_names for name in ("mat_a", "mat_b", "mat_c")),
    )

    bpy.ops.preferences.addon_disable(module="MIMIBlender")

    if _FAILURES:
        print("[E2E] {} check(s) FAILED".format(len(_FAILURES)))
        sys.exit(1)
    print("[E2E] all checks passed")
    sys.exit(0)


main()
