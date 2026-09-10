"""Regression tests for the language-independent texture apply helper.

The "Apply Texture to Selected Objects" operator used to look nodes up by
their localised names (nodes.get("Principled BSDF")). In a Chinese
interface that name becomes "原理化 BSDF", so the lookup returned None and
the operator created a brand new node that was never connected to the
material output: the texture could not show up.

These tests reproduce that exact situation by renaming the BSDF / Output
nodes to their Chinese names and verifying that:
    - the existing Principled BSDF is reused (no extra node is created),
    - the image texture is wired into that node,
    - the node chain stays connected to the material output.

Run from the repository root with a headless Blender, for example:
    blender -b --python tools/test_material_texture_apply.py
"""
import os
import sys
import tempfile
import types
from types import SimpleNamespace

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# Import the add-on modules as the "MIMIBlender" package without executing
# the add-on's own __init__.py (which would register everything else).
PKG = types.ModuleType("MIMIBlender")
PKG.__path__ = [REPO_ROOT]
sys.modules["MIMIBlender"] = PKG

import bpy  # noqa: E402
import MIMIBlender.utils.material_texture_utils as mtu  # noqa: E402
import MIMIBlender.ui.ui_panel_fast_texture as ft  # noqa: E402

PASSED = []
FAILED = []


def check(name, condition, detail=""):
    if condition:
        PASSED.append(name)
        print("[TEST] PASS |", name)
    else:
        FAILED.append(name)
        print("[TEST] FAIL |", name, "|", detail)


def wipe_scene():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for mesh in list(bpy.data.meshes):
        bpy.data.meshes.remove(mesh)
    for mat in list(bpy.data.materials):
        bpy.data.materials.remove(mat)
    for img in list(bpy.data.images):
        if img.users == 0:
            bpy.data.images.remove(img)


def count_nodes(material, bl_idname):
    return sum(
        1 for node in material.node_tree.nodes
        if node.bl_idname == bl_idname
    )


def count_bsdf(material):
    return count_nodes(material, "ShaderNodeBsdfPrincipled")


def make_material_with_chinese_nodes():
    """A material whose BSDF / Output nodes carry Chinese names.

    This mirrors the state of a material created while Blender is running
    in a Chinese interface ("new data names are translated").
    """
    mat = bpy.data.materials.new("ProbeMat")
    mat.use_nodes = True
    for node in mat.node_tree.nodes:
        if node.bl_idname == "ShaderNodeBsdfPrincipled":
            node.name = "原理化 BSDF"
        elif node.bl_idname == "ShaderNodeOutputMaterial":
            node.name = "材质输出"
    return mat


def find_bsdf(material):
    return mtu.find_node(material.node_tree.nodes, "ShaderNodeBsdfPrincipled")


def find_image_link_to_bsdf(material):
    """Return the image node linked to the BSDF Base Color, or None.

    bpy node references are not guaranteed to be the same Python object
    across separate lookups, so the search matches by node type and socket
    name instead of by identity.
    """
    for node in material.node_tree.nodes:
        for link in material.node_tree.links:
            if link.to_node.bl_idname == "ShaderNodeBsdfPrincipled" \
                    and link.to_socket.name == "Base Color" \
                    and link.from_node.bl_idname == "ShaderNodeTexImage":
                if link.from_node.image is not None:
                    return link.from_node
    return None


def output_surface_is_linked(material):
    """True when the material output Surface input has an incoming link."""
    for link in material.node_tree.links:
        if link.to_node.bl_idname == "ShaderNodeOutputMaterial" \
                and link.to_socket.name == "Surface":
            return True
    return False


def make_image():
    return bpy.data.images.new("ProbeImage", width=4, height=4, alpha=True)


def test_helper_reuses_chinese_named_nodes():
    """A BSDF named in Chinese must be reused, not duplicated."""
    mat = make_material_with_chinese_nodes()
    bsdf_before = count_bsdf(mat)
    image = make_image()

    # Existence of the localised name proves the old lookup would fail.
    check("helper: nodes.get(english) fails here",
          mat.node_tree.nodes.get("Principled BSDF") is None)
    check("helper: find_node still finds the chinese BSDF",
          find_bsdf(mat) is not None)

    mtu.apply_image_texture_to_material(mat, image)
    check("helper: no extra BSDF created",
          count_bsdf(mat) == bsdf_before,
          f"{bsdf_before} -> {count_bsdf(mat)}")
    img_node = find_image_link_to_bsdf(mat)
    check("helper: image wired into the reused BSDF",
          img_node is not None and img_node.image is image)
    check("helper: output chain intact", output_surface_is_linked(mat))
    check("helper: image alpha linked",
          any(link.to_node.bl_idname == "ShaderNodeBsdfPrincipled"
              and link.to_socket.name == "Alpha"
              and link.from_node.bl_idname == "ShaderNodeTexImage"
              for link in mat.node_tree.links))


def test_helper_builds_tree_from_scratch():
    """A material with no nodes gets a full, connected chain."""
    mat = bpy.data.materials.new("EmptyMat")
    mat.use_nodes = True
    mat.node_tree.nodes.clear()
    image = make_image()
    mtu.apply_image_texture_to_material(mat, image)
    check("helper: empty tree creates one BSDF", count_bsdf(mat) == 1)
    check("helper: empty tree creates one output",
          count_nodes(mat, "ShaderNodeOutputMaterial") == 1)
    check("helper: empty tree output connected",
          output_surface_is_linked(mat))
    check("helper: empty tree image connected",
          find_image_link_to_bsdf(mat) is not None)


def test_apply_operator_reuses_original_material():
    """End-to-end: the operator must not create a second material/node."""
    # Build an object with a pre-existing material whose nodes are Chinese.
    wipe_scene()
    mesh = bpy.data.meshes.new("M")
    mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
    obj = bpy.data.objects.new("Obj", mesh)
    bpy.context.scene.collection.objects.link(obj)

    mat = make_material_with_chinese_nodes()
    mat_name_before = mat.name
    obj.data.materials.append(mat)
    bsdf_before = count_bsdf(mat)

    # A real image file to load by path.
    image = bpy.data.images.new("TempImage", width=4, height=4, alpha=True)
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        image.filepath_raw = path
        image.file_format = "PNG"
        image.save()
        image_path = path

        class _Scene:
            def __init__(self, image_path):
                self.mimi_image_list = [SimpleNamespace(filepath=image_path,
                                                  name="temp.png")]
                self.mimi_image_list_index = 0

        fake_context = SimpleNamespace(
            scene=_Scene(image_path),
            selected_objects=[obj],
        )

        # Operator instances cannot be created directly (bpy_struct), but
        # execute() is a plain method that only uses self.report(), so it
        # can be invoked with a lightweight fake "self".
        fake_self = SimpleNamespace(report=lambda *args, **kwargs: None)
        result = ft.SSMT_ImportTexture_WM_OT_ApplyImageToMaterial.execute(
            fake_self, fake_context)

        check("operator: finished",
              isinstance(result, set) and "FINISHED" in result, str(result))
        check("operator: original material reused",
              obj.data.materials[0] is mat and
              obj.data.materials[0].name == mat_name_before)
        check("operator: no extra BSDF created",
              count_bsdf(mat) == bsdf_before,
              f"{bsdf_before} -> {count_bsdf(mat)}")
        img_node = find_image_link_to_bsdf(mat)
        check("operator: image connected into original chain",
              img_node is not None)
        check("operator: output chain intact", output_surface_is_linked(mat))
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def test_apply_operator_creates_material_when_missing():
    """An object without materials still gets a working material."""
    wipe_scene()
    mesh = bpy.data.meshes.new("M2")
    mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
    obj = bpy.data.objects.new("Obj2", mesh)
    bpy.context.scene.collection.objects.link(obj)

    image = bpy.data.images.new("TempImage2", width=4, height=4, alpha=True)
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        image.filepath_raw = path
        image.file_format = "PNG"
        image.save()

        class _Scene:
            def __init__(self, image_path):
                self.mimi_image_list = [SimpleNamespace(filepath=image_path,
                                                  name="temp2.png")]
                self.mimi_image_list_index = 0

        fake_context = SimpleNamespace(
            scene=_Scene(path),
            selected_objects=[obj],
        )

        fake_self = SimpleNamespace(report=lambda *args, **kwargs: None)
        result = ft.SSMT_ImportTexture_WM_OT_ApplyImageToMaterial.execute(
            fake_self, fake_context)

        check("operator: (no material) finished",
              isinstance(result, set) and "FINISHED" in result, str(result))
        check("operator: (no material) material created",
              len(obj.data.materials) == 1 and count_bsdf(
                  obj.data.materials[0]) == 1)
        check("operator: (no material) image connected",
              find_image_link_to_bsdf(obj.data.materials[0]) is not None)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def main():
    tests = [
        test_helper_reuses_chinese_named_nodes,
        test_helper_builds_tree_from_scratch,
        test_apply_operator_reuses_original_material,
        test_apply_operator_creates_material_when_missing,
    ]
    for test in tests:
        try:
            test()
        except Exception:
            import traceback
            FAILED.append(test.__name__)
            print("[TEST] FAIL |", test.__name__, "| exception:")
            traceback.print_exc()
    print(f"[SUMMARY] {len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        print("[SUMMARY] failed:", ", ".join(FAILED))


main()
