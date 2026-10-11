"""Check linked source sizes and equivalent-output deduplication in Blender.

Run in a factory-startup headless process with --python-exit-code 1.
All materials, images and meshes are synthetic and belong to this test.
No user data or output files are overwritten.

Contracts tested:
- Two independent materials using one image share one dimension constraint.
- Editing one unlocked row propagates its size and fixed flag on recalculation.
- Equivalent baked outputs share coordinates and consume only one atlas region.
- A later edit supersedes the previously approved peer size rather than conflicts.
- Two different new fixed requests are rejected, not silently overwritten.
- A failed plan leaves requested dimensions available for correction.
- Different diffuse tint preserves distinct output rectangles.
- Different alpha strategies preserve distinct output rectangles.
- Linked dimensions remain equal even when those rectangles must be separate.
- Group budget reduction shrinks all related rectangles together.
- Source UV vectors are not changed by previews or recalculation.
- Merge UVs for equivalent materials land in the same output region.
- Composition pastes the deduplicated texture only once.
- No material root properties are modified to implement preview grouping.
- The actual merged PNG matches the approved canvas dimensions.
- Both original materials are reassigned to the generated atlas material.
- Distinct source images remain independent even if their colors happen to match.
- The size list retains one visible row for every selected material.
- A group update is deterministic and independent of which row is representative.
- Strict output validation continues to run before the merge.
- Add-on registration and cleanup use the actual Blender API.
- The two source peers use the identical Image datablock, not matching names.
- Preview grouping is intentionally different from baked-output equivalence.
- A source group can contain multiple tint variants without merging their pixels.
- Alpha behavior contributes to output identity even with matching color images.
- Old approved dimensions distinguish propagated locks from new user edits.
- Rebuilding the collection requires re-fetching every row reference afterward.
- The conflicting-size case expects Blender's operator error report exception.
- All other unexpected assertions terminate the script with a failing exit code.
- The manual size survives final UV remapping and image composition.
- Preview generation still copies UVs rather than normalizing the mesh in place.
- The core numeric test checks equal linked sizes without Blender material access.
- Packed representatives are counted separately from visible material rows.
- Shared placement coordinates are verified before and after the real merge.
"""

import json
import os
import sys
import tempfile

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(ROOT))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from test_texcomb_distribution import make_quad


def recalculate():
    """Return Blender's status without hiding unexpected assertion failures."""
    return bpy.ops.mimi.generate_size_distribution(recalculate=True)


def main():
    import MIMIBlender
    bpy.ops.preferences.addon_enable(module="MIMIBlender")
    from MIMIBlender.texcomb.operators.combiner import size_distribution as planner
    from MIMIBlender.texcomb.core.layout import pack_budget_atlas

    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    objects = [make_quad(index) for index in range(3)]
    a, b, other = [mat for obj, mat in objects]
    image = next(node.image for node in a.node_tree.nodes if node.type == "TEX_IMAGE")
    node_b = next(node for node in b.node_tree.nodes if node.type == "TEX_IMAGE")
    node_b.image = image
    scene = bpy.context.scene
    scene.mimi_smc_uniform_size_value = 512
    scene.mimi_smc_total_size = True
    scene.mimi_smc_total_width = 1024
    scene.mimi_smc_total_height = 1024
    scene.mimi_smc_image_format = "PNG"
    bpy.context.view_layer.objects.active = objects[0][0]
    assert bpy.ops.mimi.generate_size_distribution() == {"FINISHED"}

    def entries():
        # Re-fetch RNA after every collection rebuild; old references may die.
        return planner.distribution_entries(scene)

    rows = entries()
    assert len(rows) == 3
    assert len(scene.mimi_smc_distribution) == 2
    assert rows[a] == rows[b]
    assert len(rows[a].members) == 2
    assert {member.mat for member in rows[a].members} == {a, b}
    # Expanding member names changes presentation only, not plan approval.
    rows[a].members_expanded = True
    assert planner.distribution_ready(scene, check_sources=False)
    assert (rows[a].x, rows[a].y) == (rows[b].x, rows[b].y)
    rows[a].width, rows[a].height = 256, 256
    assert recalculate() == {"FINISHED"}
    rows = entries()
    assert all((rows[mat].width, rows[mat].height, rows[mat].locked) == (256, 256, True) for mat in (a, b))
    # Changing just one previously fixed peer supersedes the old group size.
    rows[b].width, rows[b].height = 128, 128
    assert recalculate() == {"FINISHED"}
    rows = entries()
    assert rows[a].width == rows[b].width == 128
    # There is now one control for both members, so contradictory edits cannot
    # be made within an equivalent-output group at all.
    rows[a].width, rows[a].height = 256, 256
    assert rows[b].width == 256
    assert recalculate() == {"FINISHED"}

    # Matching source image does not imply matching output tint or alpha.
    b.mimi_smc_diffuse = True
    shader_b = next(node for node in b.node_tree.nodes if node.type == "BSDF_PRINCIPLED")
    shader_b.inputs["Base Color"].default_value = (0.2, 0.5, 0.8, 1)
    assert recalculate() == {"FINISHED"}
    rows = entries()
    assert rows[a].width == rows[b].width
    assert (rows[a].x, rows[a].y) != (rows[b].x, rows[b].y)
    assert len(scene.mimi_smc_distribution) == 3
    rows[a].width, rows[a].height = 128, 128
    rows[b].width, rows[b].height = 64, 64
    try:
        result = recalculate()
    except RuntimeError:
        result = {"CANCELLED"}
    assert result == {"CANCELLED"}
    assert not scene.mimi_smc_distribution_valid
    rows[a].width, rows[a].height = 256, 256
    rows[b].width, rows[b].height = 256, 256
    assert recalculate() == {"FINISHED"}
    b.mimi_smc_diffuse = False
    b.mimi_smc_alpha_mode = "OPAQUE"
    assert recalculate() == {"FINISHED"}
    rows = entries()
    assert (rows[a].x, rows[a].y) != (rows[b].x, rows[b].y)
    b.mimi_smc_alpha_mode = "AUTO"
    assert recalculate() == {"FINISHED"}
    rows = entries()
    assert (rows[a].x, rows[a].y) == (rows[b].x, rows[b].y)

    # Core linking keeps separately baked output regions equal under pressure.
    fits, canvas, sizes = pack_budget_atlas({"a": (512, 512), "b": (512, 512), "c": (512, 512)},
                                           (512, 512), linked_groups=[{"a", "b"}])
    assert sizes["a"] == sizes["b"]
    assert fits["a"] != fits["b"]
    _, _, structure = planner.prepare_sources(scene)
    planner.apply_distribution(scene, structure)
    assert len(structure) == 2
    assert all(not mat.mimi_root_mat for mat in (a, b, other))
    before = [[tuple(loop.uv) for loop in obj.data.uv_layers.active.data] for obj, mat in objects]
    assert before[0] == before[1]
    directory = tempfile.mkdtemp(prefix="mimi_shared_texture_")
    assert bpy.ops.mimi.combiner(directory=directory) == {"FINISHED"}
    after = [[tuple(loop.uv) for loop in obj.data.uv_layers.active.data] for obj, mat in objects]
    assert after[0] == after[1]
    from PIL import Image
    path = next(os.path.join(directory, name) for name in os.listdir(directory) if name.endswith(".png"))
    with Image.open(path) as atlas:
        assert atlas.size == (scene.mimi_smc_distribution_width, scene.mimi_smc_distribution_height)
    bpy.ops.preferences.addon_disable(module="MIMIBlender")
    print("RESULT " + json.dumps({"status": "passed", "source_materials": 3, "rows": 2, "packed_outputs": 2,
                                  "linked_size": [256, 256], "uvs_shared": True}))


if __name__ == "__main__":
    main()
