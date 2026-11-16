"""Blender coverage for one atlas region per source texture file.

The texture combiner groups materials by a cached source identity. That
identity must survive the real import path: one model, several SubMeshes and
one texture file must produce one Image datablock, one visible row and one
atlas region. The same test also proves that a replaced file or a different
tint still stays a separate output.

Run with a factory-startup background Blender and --python-exit-code 1.
The scene, images and output files are synthetic and live in a temp folder.
No user blend file, texture or preference is read or overwritten.

Coverage matrix:
- Import helper: one datablock per normalized path, one per color space, a
  visible error for an empty path, and the real apply_diffuse_texture wiring.
- Merge family: two datablocks of one file plus a third peer that already
  shares a datablock produce one row, three members, one atlas rectangle and
  equal UVs because this fixture uses equal UV coverage.
- UV islands: the same source with different coverage keeps one sampling
  window and one rectangle while each island keeps its own coordinates.
- Tint: a visible tint keeps two outputs even when they share one file.
- Replaced file: the same path with different packed bytes stays two rows.
- Alpha and PBR: two datablocks of one extra file merge; two different extra
  files stay apart.
- Stale plan: replacing the packed bytes after planning must cancel the
  merge instead of pasting two pictures into the approved rectangle.
"""

import json
import os
import sys
import tempfile

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(ROOT))


def clear_scene():
    """Remove objects and images created by an earlier case in this run."""
    # Object removal also detaches meshes and materials from the scene; the
    # follow-up loops then free only datablocks nobody references anymore.
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for mesh in list(bpy.data.meshes):
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)
    for material in list(bpy.data.materials):
        if material.users == 0:
            bpy.data.materials.remove(material)
    for image in list(bpy.data.images):
        # The render result and viewer are owned by Blender, not this test.
        if image.users == 0 and image.name not in {"Render Result", "Viewer Node"}:
            bpy.data.images.remove(image)


def write_png(directory, name, color):
    """Write one small PNG and return its absolute path.

    The file is the only shared input: several datablocks will load it to
    model one model whose SubMeshes reuse the same diffuse texture.
    """
    path = os.path.join(directory, name)
    # A generated image is saved once, then removed: the test must load the
    # file from disk to create datablocks the way the importer does.
    image = bpy.data.images.new("file_source_" + name, 64, 64, alpha=True)
    # A flat color keeps the bytes small; identity only needs a stable digest.
    image.pixels = list(color) * (64 * 64)
    image.filepath_raw = path
    image.file_format = "PNG"
    image.save()
    bpy.data.images.remove(image)
    return path


def make_material(name, image, color=None):
    """Create a Principled material whose Base Color uses one image."""
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    shader = principled(material)
    texture = material.node_tree.nodes.new("ShaderNodeTexImage")
    texture.image = image
    material.node_tree.links.new(texture.outputs["Color"], shader.inputs["Base Color"])
    if color is not None:
        # An explicit tint makes this output visually different from peers.
        material.mimi_smc_diffuse = True
        shader.inputs["Base Color"].default_value = color
    return material


def principled(material):
    """Return the Principled BSDF node of a node material."""
    return next(node for node in material.node_tree.nodes
                if node.type == "BSDF_PRINCIPLED")


def make_quad(name, material, uv_scale=1.0):
    """Create one quad object using the material and a plain 0-1 UV layer."""
    mesh = bpy.data.meshes.new(name + "_mesh")
    mesh.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [], [(0, 1, 2, 3)])
    mesh.materials.append(material)
    layer = mesh.uv_layers.new(name="uvmap")
    corners = [(0, 0), (uv_scale, 0), (uv_scale, uv_scale), (0, uv_scale)]
    for loop, uv in zip(layer.data, corners):
        loop.uv = uv
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def select(objects):
    """Select exactly the objects a planning run should inspect."""
    for obj in bpy.context.scene.objects:
        obj.select_set(obj in objects)
    bpy.context.view_layer.objects.active = objects[0]


def uv_snapshot(objects):
    """Copy live UV vectors into plain tuples for later comparison."""
    return [[tuple(loop.uv) for loop in obj.data.uv_layers.active.data]
            for obj in objects]


def check_import_loading(directory):
    """The import helper must return one datablock for one file path.

    The first half proves the failure mode still exists in plain Blender, so
    a future reader can see why the helper is needed. The second half checks
    the helper itself: path spelling, color space, empty input and the real
    apply_diffuse_texture call used by the model importer.
    """
    path = write_png(directory, "shared_diffuse.png", (0.2, 0.4, 0.6, 1.0))
    # Prove the trap first: plain loading creates two datablocks for one file.
    # This is the exact image state the importer used to create per SubMesh.
    first_raw = bpy.data.images.load(path, check_existing=False)
    second_raw = bpy.data.images.load(path, check_existing=False)
    assert first_raw != second_raw
    bpy.data.images.remove(first_raw)
    bpy.data.images.remove(second_raw)
    from MIMIBlender.utils.image_loading import find_loaded_image, load_shared_image
    # The helper must return the same datablock for the second request.
    first = load_shared_image(path, "sRGB")
    second = load_shared_image(path, "sRGB")
    assert first == second
    assert first.as_pointer() == second.as_pointer()
    # A differently cased spelling still names the same file on Windows.
    assert find_loaded_image(path.upper()) == first
    # Color space is part of the reuse key: a raw-data use must not repaint
    # the color texture that other materials already share.
    non_color = load_shared_image(path, "Non-Color")
    assert non_color != first
    assert load_shared_image(path, "sRGB") == first
    # An empty path must keep Blender's error instead of a silent None.
    try:
        load_shared_image("")
    except RuntimeError:
        pass
    else:
        raise AssertionError("Empty image path was accepted")
    # A second, genuinely different file must stay a different datablock.
    other_path = write_png(directory, "other_diffuse.png", (0.8, 0.1, 0.1, 1.0))
    assert load_shared_image(other_path, "sRGB") != first
    # The real import wiring goes through the same helper.
    from MIMIBlender.common.mesh_create_helper import MeshCreateHelper
    material = bpy.data.materials.new("import_probe")
    material.use_nodes = True
    shader = next(node for node in material.node_tree.nodes
                  if node.type == "BSDF_PRINCIPLED")
    # Two SubMesh-style materials calling the importer must end on one Image.
    MeshCreateHelper.apply_diffuse_texture(material.node_tree, shader, path)
    MeshCreateHelper.apply_diffuse_texture(material.node_tree, shader, path)
    textures = [node.image for node in material.node_tree.nodes
                if node.type == "TEX_IMAGE"]
    assert len(textures) == 2
    assert textures[0] == textures[1]
    print("IMPORT_LOADING_PASS " + json.dumps({"datablocks": 1, "path": path}))
    clear_scene()


def check_merge_family(directory, scene):
    """Two datablocks from one file plus a third peer must share one region.

    This is the user-visible symptom from the report: the file exists once,
    but the atlas used to contain it four times. The third material already
    points at the first datablock, which proves the test needs the path
    identity and not only datablock sharing to reach one row.
    """
    from MIMIBlender.texcomb.operators.combiner import size_distribution as planner
    path = write_png(directory, "family_diffuse.png", (0.3, 0.5, 0.7, 1.0))
    # The exact import failure: two separate datablocks for one file.
    # The third material reuses the first datablock to mix both situations.
    image_one = bpy.data.images.load(path, check_existing=False)
    image_two = bpy.data.images.load(path, check_existing=False)
    assert image_one != image_two
    material_a = make_material("family_material_a", image_one)
    material_b = make_material("family_material_b", image_two)
    material_c = make_material("family_material_c", image_one)
    objects = [make_quad("family_object_a", material_a),
               make_quad("family_object_b", material_b),
               make_quad("family_object_c", material_c)]
    select(objects)
    scene.mimi_smc_image_format = "PNG"
    scene.mimi_smc_uniform_size_value = 64
    # One planning pass must already show the single row users see.
    assert bpy.ops.mimi.generate_size_distribution() == {"FINISHED"}
    # One source file, one visible row, every material listed as a member.
    assert len(scene.mimi_smc_distribution) == 1, len(scene.mimi_smc_distribution)
    rows = planner.distribution_entries(scene)
    assert rows[material_a] == rows[material_b] == rows[material_c]
    assert len(rows[material_a].members) == 3
    # The real merge must map every peer to the same atlas rectangle.
    # Equal source UV coverage in this fixture makes the mapped UVs equal too.
    output = os.path.join(directory, "atlas_family")
    os.makedirs(output, exist_ok=True)
    assert bpy.ops.mimi.combiner(directory=output) == {"FINISHED"}
    snapshots = uv_snapshot(objects)
    assert snapshots[0] == snapshots[1] == snapshots[2]
    from PIL import Image
    atlas_path = next(os.path.join(output, name) for name in os.listdir(output)
                      if name.endswith(".png"))
    with Image.open(atlas_path) as atlas:
        assert atlas.size == (scene.mimi_smc_distribution_width,
                              scene.mimi_smc_distribution_height)
    print("MERGE_FAMILY_PASS " + json.dumps({"rows": 1, "members": 3,
                                             "canvas": list(atlas.size)}))
    clear_scene()


def check_tint_stays_separate(directory, scene):
    """One file with a different tint must still produce two regions.

    Merging identical sources is only safe while the baked pixels stay equal.
    A visible tint changes those pixels, so the key must keep the two output
    groups apart even though the source identity is shared.
    """
    from MIMIBlender.texcomb.operators.combiner import size_distribution as planner
    path = write_png(directory, "tint_diffuse.png", (0.4, 0.6, 0.8, 1.0))
    # Both materials read one file, but only the second enables a tint.
    image_one = bpy.data.images.load(path, check_existing=False)
    image_two = bpy.data.images.load(path, check_existing=False)
    material_a = make_material("tint_material_a", image_one)
    material_b = make_material("tint_material_b", image_two,
                               color=(0.2, 0.5, 0.9, 1.0))
    objects = [make_quad("tint_object_a", material_a),
               make_quad("tint_object_b", material_b)]
    select(objects)
    scene.mimi_smc_image_format = "PNG"
    # The same source family must not collapse two different baked colors.
    assert bpy.ops.mimi.generate_size_distribution() == {"FINISHED"}
    # Same source family, different baked color: two rows are still required.
    assert len(scene.mimi_smc_distribution) == 2, len(scene.mimi_smc_distribution)
    rows = planner.distribution_entries(scene)
    assert rows[material_a] != rows[material_b]
    print("TINT_SPLIT_PASS " + json.dumps({"rows": 2}))
    clear_scene()


def check_replaced_file_stays_separate(directory, scene):
    """Equal file paths with different bytes must never share one region.

    This is the reverse guard of the merge case: identity uses the path, but
    the content hash keeps two different pictures from being treated as one
    source just because they claim the same file name.
    """
    from MIMIBlender.texcomb.operators.combiner import size_distribution as planner
    path = os.path.join(directory, "replaced_diffuse.png")
    # Two generated images claim the same path but carry different pixels.
    image_one = bpy.data.images.new("replaced_one", 64, 64, alpha=True)
    image_one.pixels = list((0.9, 0.1, 0.1, 1.0)) * (64 * 64)
    image_one.filepath_raw = path
    image_one.pack()
    image_two = bpy.data.images.new("replaced_two", 64, 64, alpha=True)
    image_two.pixels = list((0.1, 0.1, 0.9, 1.0)) * (64 * 64)
    image_two.filepath_raw = path
    image_two.pack()
    material_a = make_material("replaced_material_a", image_one)
    material_b = make_material("replaced_material_b", image_two)
    objects = [make_quad("replaced_object_a", material_a),
               make_quad("replaced_object_b", material_b)]
    select(objects)
    scene.mimi_smc_image_format = "PNG"
    # Both images claim one path, so only the digest can keep them apart.
    assert bpy.ops.mimi.generate_size_distribution() == {"FINISHED"}
    # The digest guard keeps a replaced file from merging with the old one.
    assert len(scene.mimi_smc_distribution) == 2, len(scene.mimi_smc_distribution)
    rows = planner.distribution_entries(scene)
    assert rows[material_a] != rows[material_b]
    print("REPLACED_SPLIT_PASS " + json.dumps({"rows": 2}))
    clear_scene()


def check_alpha_source_shared(directory, scene):
    """Alpha masks loaded twice from one file must share one output region.

    The alpha channel is a second texture identity in the same output key.
    If it kept datablock pointers, the merge fix would only work for models
    without alpha and the same bug would return through the back door.
    """
    from MIMIBlender.texcomb.operators.combiner import size_distribution as planner
    diffuse_path = write_png(directory, "alpha_diffuse.png", (0.5, 0.5, 0.5, 1.0))
    alpha_path = write_png(directory, "alpha_mask.png", (0.9, 0.9, 0.9, 1.0))
    # Both the diffuse and the alpha file are loaded twice on purpose.
    # The shader Alpha input is the AUTO source this case exercises.
    diffuse_one = bpy.data.images.load(diffuse_path, check_existing=False)
    diffuse_two = bpy.data.images.load(diffuse_path, check_existing=False)
    alpha_one = bpy.data.images.load(alpha_path, check_existing=False)
    alpha_two = bpy.data.images.load(alpha_path, check_existing=False)
    material_a = make_material("alpha_material_a", diffuse_one)
    material_b = make_material("alpha_material_b", diffuse_two)
    for material, alpha_image in ((material_a, alpha_one), (material_b, alpha_two)):
        material.mimi_smc_alpha_mode = "AUTO"
        shader = principled(material)
        alpha_texture = material.node_tree.nodes.new("ShaderNodeTexImage")
        alpha_texture.image = alpha_image
        material.node_tree.links.new(alpha_texture.outputs["Alpha"], shader.inputs["Alpha"])
    objects = [make_quad("alpha_object_a", material_a),
               make_quad("alpha_object_b", material_b)]
    select(objects)
    scene.mimi_smc_image_format = "PNG"
    # Both diffuse and alpha files are read twice; one plan must show one row.
    assert bpy.ops.mimi.generate_size_distribution() == {"FINISHED"}
    # Both diffuse and alpha files are read twice; both identities still agree.
    assert len(scene.mimi_smc_distribution) == 1, len(scene.mimi_smc_distribution)
    rows = planner.distribution_entries(scene)
    assert rows[material_a] == rows[material_b]
    print("ALPHA_SOURCE_PASS " + json.dumps({"rows": 1}))
    clear_scene()


def check_extra_map_source_shared(directory, scene):
    """Normal maps loaded twice from one file must share one output region.

    Extra PBR maps are read on demand rather than stored in the material
    structure, so this case checks that the batch identity cache and the
    on-demand path agree on the same source.
    """
    from MIMIBlender.texcomb.operators.combiner import size_distribution as planner
    diffuse_path = write_png(directory, "normal_diffuse.png", (0.6, 0.4, 0.2, 1.0))
    normal_path = write_png(directory, "normal_map.png", (0.5, 0.5, 1.0, 1.0))
    # The normal map is loaded twice; the shader Normal input is the extra
    # map source this case exercises through get_gfx_texture_images().
    diffuse_one = bpy.data.images.load(diffuse_path, check_existing=False)
    diffuse_two = bpy.data.images.load(diffuse_path, check_existing=False)
    normal_one = bpy.data.images.load(normal_path, check_existing=False)
    normal_two = bpy.data.images.load(normal_path, check_existing=False)
    material_a = make_material("normal_material_a", diffuse_one)
    material_b = make_material("normal_material_b", diffuse_two)
    for material, normal_image in ((material_a, normal_one), (material_b, normal_two)):
        shader = principled(material)
        normal_texture = material.node_tree.nodes.new("ShaderNodeTexImage")
        normal_texture.image = normal_image
        normal_map = material.node_tree.nodes.new("ShaderNodeNormalMap")
        material.node_tree.links.new(normal_texture.outputs["Color"],
                                     normal_map.inputs["Color"])
        material.node_tree.links.new(normal_map.outputs["Normal"],
                                     shader.inputs["Normal"])
    objects = [make_quad("normal_object_a", material_a),
               make_quad("normal_object_b", material_b)]
    select(objects)
    scene.mimi_smc_image_format = "PNG"
    scene.mimi_smc_include_extra_textures = True
    try:
        # The extra map is part of the output key; one file must mean one row.
        assert bpy.ops.mimi.generate_size_distribution() == {"FINISHED"}
        # The extra map is read twice from one file; its identity must agree.
        assert len(scene.mimi_smc_distribution) == 1, len(scene.mimi_smc_distribution)
        rows = planner.distribution_entries(scene)
        assert rows[material_a] == rows[material_b]
    finally:
        # The setting is scene-wide; leaving it on would change later cases.
        scene.mimi_smc_include_extra_textures = False
    print("EXTRA_MAP_SOURCE_PASS " + json.dumps({"rows": 1}))
    clear_scene()


def check_uv_islands_shared(directory, scene):
    """Same source file with different UV coverage keeps one window and region.

    Two SubMeshes often use different islands of one texture. They must share
    the sampling window (so the planner does not bake two different grids) and
    then share one atlas rectangle, while each keeps its own island
    coordinates. Identical UVs are not expected here; the shared region is.
    """
    from MIMIBlender.texcomb.operators.combiner import size_distribution as planner
    path = write_png(directory, "islands_diffuse.png", (0.2, 0.5, 0.8, 1.0))
    # Two datablocks of one file stand in for two SubMeshes sharing a texture.
    # Their UV coverage differs, which is the normal case in a real model.
    image_one = bpy.data.images.load(path, check_existing=False)
    image_two = bpy.data.images.load(path, check_existing=False)
    material_a = make_material("islands_material_a", image_one)
    material_b = make_material("islands_material_b", image_two)
    objects = [make_quad("islands_object_a", material_a, uv_scale=1.0),
               make_quad("islands_object_b", material_b, uv_scale=0.5)]
    select(objects)
    scene.mimi_smc_image_format = "PNG"
    # Generation refreshes the object data list; prepare_sources alone would
    # read the previous case's stale RNA rows.
    assert bpy.ops.mimi.generate_size_distribution() == {"FINISHED"}
    _, _, structure = planner.prepare_sources(scene)
    # The two datablocks must agree on the sampling window before packing.
    # Without the shared window each family would bake a different grid.
    assert structure[material_a]["gfx"]["uv_size"] == \
        structure[material_b]["gfx"]["uv_size"]
    assert len(scene.mimi_smc_distribution) == 1, len(scene.mimi_smc_distribution)
    rows = planner.distribution_entries(scene)
    assert rows[material_a] == rows[material_b]
    output = os.path.join(directory, "atlas_islands")
    os.makedirs(output, exist_ok=True)
    assert bpy.ops.mimi.combiner(directory=output) == {"FINISHED"}
    after = uv_snapshot(objects)
    # Different islands remain different, but both stay in the shared region.
    # Equality would mean the merge copied one layout over the other, which
    # would quietly move one SubMesh onto the wrong texels.
    assert after[0] != after[1]
    for snapshot in after:
        for u, v in snapshot:
            assert 0.0 <= u <= 1.0 and 0.0 <= v <= 1.0
    print("UV_ISLANDS_PASS " + json.dumps({"rows": 1, "uv_equal": False}))
    clear_scene()


def check_alpha_split_different_file(directory, scene):
    """Different alpha files must still produce different rectangles.

    This is the negative control for the alpha identity change: a fix that
    simply drops alpha from the output key would merge these two materials
    and pass the shared-alpha case while baking the wrong mask.
    """
    from MIMIBlender.texcomb.operators.combiner import size_distribution as planner
    diffuse_path = write_png(directory, "alpha_split_diffuse.png", (0.5, 0.5, 0.5, 1.0))
    alpha_one_path = write_png(directory, "alpha_split_one.png", (0.9, 0.9, 0.9, 1.0))
    alpha_two_path = write_png(directory, "alpha_split_two.png", (0.2, 0.2, 0.2, 1.0))
    diffuse = bpy.data.images.load(diffuse_path, check_existing=False)
    alpha_one = bpy.data.images.load(alpha_one_path, check_existing=False)
    alpha_two = bpy.data.images.load(alpha_two_path, check_existing=False)
    material_a = make_material("alpha_split_a", diffuse)
    material_b = make_material("alpha_split_b", diffuse)
    for material, alpha_image in ((material_a, alpha_one), (material_b, alpha_two)):
        material.mimi_smc_alpha_mode = "SEPARATE"
        material.mimi_smc_alpha_image = alpha_image
    objects = [make_quad("alpha_split_object_a", material_a),
               make_quad("alpha_split_object_b", material_b)]
    select(objects)
    scene.mimi_smc_image_format = "PNG"
    # Two different alpha files must survive as two approved rows.
    assert bpy.ops.mimi.generate_size_distribution() == {"FINISHED"}
    # A different alpha file is a different baked output.
    assert len(scene.mimi_smc_distribution) == 2, len(scene.mimi_smc_distribution)
    print("ALPHA_SPLIT_PASS " + json.dumps({"rows": 2}))
    clear_scene()


def check_extra_map_split_different_file(directory, scene):
    """Different normal maps must still produce different rectangles.

    The negative control mirrors the alpha case: dropping extra maps from the
    output key would silently bake one normal map on two different materials.
    """
    from MIMIBlender.texcomb.operators.combiner import size_distribution as planner
    diffuse_path = write_png(directory, "normal_split_diffuse.png", (0.6, 0.4, 0.2, 1.0))
    normal_one_path = write_png(directory, "normal_split_one.png", (0.5, 0.5, 1.0, 1.0))
    normal_two_path = write_png(directory, "normal_split_two.png", (1.0, 0.5, 0.5, 1.0))
    diffuse = bpy.data.images.load(diffuse_path, check_existing=False)
    normal_one = bpy.data.images.load(normal_one_path, check_existing=False)
    normal_two = bpy.data.images.load(normal_two_path, check_existing=False)
    material_a = make_material("normal_split_a", diffuse)
    material_b = make_material("normal_split_b", diffuse)
    for material, normal_image in ((material_a, normal_one), (material_b, normal_two)):
        shader = principled(material)
        normal_texture = material.node_tree.nodes.new("ShaderNodeTexImage")
        normal_texture.image = normal_image
        normal_map = material.node_tree.nodes.new("ShaderNodeNormalMap")
        material.node_tree.links.new(normal_texture.outputs["Color"],
                                     normal_map.inputs["Color"])
        material.node_tree.links.new(normal_map.outputs["Normal"],
                                     shader.inputs["Normal"])
    objects = [make_quad("normal_split_object_a", material_a),
               make_quad("normal_split_object_b", material_b)]
    select(objects)
    scene.mimi_smc_image_format = "PNG"
    scene.mimi_smc_include_extra_textures = True
    try:
        # Two different PBR files must survive as two approved rows.
        assert bpy.ops.mimi.generate_size_distribution() == {"FINISHED"}
        # A different PBR file is a different baked output.
        assert len(scene.mimi_smc_distribution) == 2, len(scene.mimi_smc_distribution)
    finally:
        # Leave the scene-wide toggle off for the remaining cases.
        scene.mimi_smc_include_extra_textures = False
    print("EXTRA_MAP_SPLIT_PASS " + json.dumps({"rows": 2}))
    clear_scene()


def check_stale_plan_rejected(directory, scene):
    """A replaced file after planning must cancel, not paste one rectangle.

    Planning approved one row for two datablocks of one path. Replacing the
    packed bytes of one block makes the two outputs different. The merge must
    refuse the stale row instead of writing both pictures into one region.

    The replacement keeps the path and the image size, so only the content
    digest can notice the difference. This is exactly the case an earlier
    plan could otherwise approve and then lose one picture at merge time.

    Both entry paths are checked: the operator (which rebuilds the structure)
    and a direct apply_distribution call that still holds the old structure.
    """
    from MIMIBlender.texcomb.operators.combiner import size_distribution as planner
    path = write_png(directory, "stale_diffuse.png", (0.3, 0.6, 0.9, 1.0))
    other_path = write_png(directory, "stale_other.png", (0.9, 0.1, 0.1, 1.0))
    # Two datablocks of one path are approved as one row by the first plan.
    image_one = bpy.data.images.load(path, check_existing=False)
    image_two = bpy.data.images.load(path, check_existing=False)
    material_a = make_material("stale_material_a", image_one)
    material_b = make_material("stale_material_b", image_two)
    objects = [make_quad("stale_object_a", material_a),
               make_quad("stale_object_b", material_b)]
    select(objects)
    scene.mimi_smc_image_format = "PNG"
    # A normal plan approves the single shared row this test then breaks.
    assert bpy.ops.mimi.generate_size_distribution() == {"FINISHED"}
    assert len(scene.mimi_smc_distribution) == 1, len(scene.mimi_smc_distribution)
    # A direct caller can still hold this structure after the file changes.
    _, _, stale_structure = planner.prepare_sources(scene)
    with open(other_path, "rb") as handle:
        other_bytes = handle.read()
    # Same path, same size, different bytes: the digest must notice.
    # Keep the filepath and the dimensions untouched on purpose.
    image_two.pack(data=other_bytes, data_len=len(other_bytes))
    # apply_distribution must refresh identities instead of trusting the old
    # structure, otherwise it would accept the stale row and lose one picture.
    try:
        planner.apply_distribution(scene, stale_structure)
    except ValueError:
        pass
    else:
        raise AssertionError("A stale structure was accepted by apply_distribution")
    output = os.path.join(directory, "atlas_stale")
    os.makedirs(output, exist_ok=True)
    before = uv_snapshot(objects)
    try:
        # A stale approval must surface as a cancelled operator, not a merge.
        result = bpy.ops.mimi.combiner(directory=output)
    except RuntimeError:
        result = {"CANCELLED"}
    # Blender reports operator errors as RuntimeError in scripts; both forms
    # mean the merge was refused before any UV or image write.
    assert result == {"CANCELLED"}, result
    # The refusal must happen before live UV normalization: a failed merge
    # cannot leave the artist's mesh half-remapped.
    assert uv_snapshot(objects) == before
    print("STALE_PLAN_PASS " + json.dumps({"result": "cancelled"}))
    clear_scene()


def check_stale_alpha_rejected(directory, scene):
    """Clearing an alpha image after planning must cancel a direct merge.

    The alpha key is cached per structure. If a direct caller reuses the old
    structure after the live alpha source changed, the cached key would claim
    the two outputs are equal while the composer bakes different alpha data.
    apply_distribution must refresh the cache and reject that stale row.
    """
    from MIMIBlender.texcomb.operators.combiner import size_distribution as planner
    diffuse_path = write_png(directory, "stale_alpha_diffuse.png", (0.5, 0.5, 0.5, 1.0))
    alpha_path = write_png(directory, "stale_alpha_mask.png", (0.9, 0.9, 0.9, 1.0))
    diffuse_one = bpy.data.images.load(diffuse_path, check_existing=False)
    diffuse_two = bpy.data.images.load(diffuse_path, check_existing=False)
    alpha_one = bpy.data.images.load(alpha_path, check_existing=False)
    alpha_two = bpy.data.images.load(alpha_path, check_existing=False)
    material_a = make_material("stale_alpha_material_a", diffuse_one)
    material_b = make_material("stale_alpha_material_b", diffuse_two)
    for material, alpha_image in ((material_a, alpha_one), (material_b, alpha_two)):
        material.mimi_smc_alpha_mode = "SEPARATE"
        material.mimi_smc_alpha_image = alpha_image
    objects = [make_quad("stale_alpha_object_a", material_a),
               make_quad("stale_alpha_object_b", material_b)]
    select(objects)
    scene.mimi_smc_image_format = "PNG"
    # Both diffuse and alpha files are shared, so planning approves one row.
    assert bpy.ops.mimi.generate_size_distribution() == {"FINISHED"}
    assert len(scene.mimi_smc_distribution) == 1, len(scene.mimi_smc_distribution)
    # Keep the planned structure while the live alpha source changes.
    _, _, stale_structure = planner.prepare_sources(scene)
    material_b.mimi_smc_alpha_image = None
    # apply_distribution refreshes the cached alpha identity before comparing
    # rows, so the now-different live source must cancel the direct call.
    try:
        planner.apply_distribution(scene, stale_structure)
    except ValueError:
        pass
    else:
        raise AssertionError("A stale alpha source was accepted")
    print("STALE_ALPHA_PASS " + json.dumps({"result": "cancelled"}))
    clear_scene()


def main():
    # The add-on must be enabled through its normal registration path so the
    # operators used below are the ones users actually run.
    import MIMIBlender
    bpy.ops.preferences.addon_enable(module="MIMIBlender")
    scene = bpy.context.scene
    directory = tempfile.mkdtemp(prefix="mimi_source_texture_")
    # Each case clears its own datablocks so identities cannot leak between
    # cases; the order is independent and any failure stops the script.
    # A final JSON line makes a passing run easy to identify in a log.
    check_import_loading(directory)
    check_merge_family(directory, scene)
    check_tint_stays_separate(directory, scene)
    check_replaced_file_stays_separate(directory, scene)
    check_alpha_source_shared(directory, scene)
    check_extra_map_source_shared(directory, scene)
    check_uv_islands_shared(directory, scene)
    check_alpha_split_different_file(directory, scene)
    check_extra_map_split_different_file(directory, scene)
    check_stale_plan_rejected(directory, scene)
    check_stale_alpha_rejected(directory, scene)
    bpy.ops.preferences.addon_disable(module="MIMIBlender")
    print("RESULT " + json.dumps({"status": "passed", "directory": directory}))


if __name__ == "__main__":
    main()
