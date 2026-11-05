"""Real Blender coverage for automatic merging and blueprint result selection.

Use --factory-startup --python-exit-code 1. Set BLENDER_USER_CONFIG to an
isolated tmp/ directory first: this suite deliberately saves preferences.
Run again with -- --reopen <output directory> to prove restart persistence.
"""
import json
import os
import sys
from types import SimpleNamespace
from unittest.mock import patch

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(ROOT))


def make_pair(prefix):
    """Build two small solid-color meshes with independent source materials."""
    # Hide other meshes so scans remain scoped; never delete scene assets.
    for obj in bpy.context.scene.objects:
        obj.hide_set(True)
    objects = []
    for index in range(2):
        mesh = bpy.data.meshes.new(prefix + "_mesh_" + str(index))
        mesh.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [], [(0, 1, 2, 3)])
        uv = mesh.uv_layers.new(name="uvmap")
        for loop, value in zip(uv.data, [(0, 0), (1, 0), (1, 1), (0, 1)]):
            loop.uv = value
        mat = bpy.data.materials.new(prefix + "_material_" + str(index))
        mat.use_nodes = True
        shader = next(node for node in mat.node_tree.nodes if node.type == "BSDF_PRINCIPLED")
        shader.inputs["Base Color"].default_value = (0.2 + index * 0.6, 0.4, 0.6, 1)
        mesh.materials.append(mat)
        obj = bpy.data.objects.new(prefix + "_object_" + str(index), mesh)
        bpy.context.scene.collection.objects.link(obj)
        obj.select_set(True)
        objects.append(obj)
    bpy.context.view_layer.objects.active = objects[0]
    scene = bpy.context.scene
    scene.mimi_smc_image_format = "PNG"
    scene.mimi_smc_uniform_size = True
    scene.mimi_smc_uniform_size_value = 64
    # A fresh source selection may inherit an old distribution from the scene.
    # Clear explicitly only in this fixture; product recalculation keeps locks.
    scene.mimi_smc_distribution.clear()
    bpy.ops.mimi.refresh_ob_data()
    return objects


def snapshot(objects):
    """Compare copied UV tuples before intentionally rejected operations."""
    return [[tuple(loop.uv) for loop in obj.data.uv_layers.active.data] for obj in objects]


def expect_cancelled(call):
    """Blender surfaces operator ERROR reports as RuntimeError in scripts."""
    try:
        assert call() == {"CANCELLED"}
    except RuntimeError:
        pass


def check_reopen(directory):
    """Read isolated saved preferences and a delivered blend in a new process."""
    from MIMIBlender.texcomb.output_settings import default_output_directory
    from MIMIBlender.common.merged_texture_results import diffuse_results
    # Factory startup intentionally skips user preferences; load them explicitly.
    bpy.ops.wm.read_userpref()
    assert default_output_directory(bpy.context) == directory
    bpy.ops.wm.open_mainfile(filepath=os.path.join(directory, "workflow.blend"))
    assert len(diffuse_results()) == 2
    # RNA replacement paths must survive saving, not just Python operator state.
    tree = bpy.data.node_groups.get("workflow_blueprint")
    assert tree and tree.nodes.get("targeted_slot").texture_slot_items[0].file_path
    print("WORKFLOW_REOPEN_PASS " + json.dumps({"directory": directory, "results": 2}))


def main():
    # Saving real user settings is forbidden: require an isolated tmp config.
    config = os.environ.get("BLENDER_USER_CONFIG", "")
    assert config and os.path.commonpath([os.path.abspath(config), os.path.join(ROOT, "tmp")]) == os.path.join(ROOT, "tmp")
    bpy.ops.preferences.addon_enable(module="MIMIBlender")
    if "--reopen" in sys.argv:
        check_reopen(sys.argv[sys.argv.index("--reopen") + 1])
        return
    from MIMIBlender.texcomb import output_settings
    from MIMIBlender.common import merged_texture_results as results
    from MIMIBlender.texcomb.operators.combiner.combiner import Combiner
    from MIMIBlender.blueprint import texture_row_ui
    from MIMIBlender.model.blueprint_model import BluePrintModel

    directory = os.path.join(config, "atlases")
    os.makedirs(directory, exist_ok=True)
    prefs = output_settings.addon_preferences(bpy.context)
    # Explicitly disable Blender auto-save to prove the chooser saves itself.
    bpy.context.preferences.use_preferences_save = False
    assert bpy.ops.mimi.choose_atlas_output_directory(directory=directory) == {"FINISHED"}
    assert output_settings.default_output_directory(bpy.context) == directory
    assert os.path.isfile(os.path.join(config, "userpref.blend"))
    # A failed persistence write rolls back the in-memory preference.
    another = os.path.join(config, "another")
    os.makedirs(another, exist_ok=True)
    # bpy.ops namespace proxies are recreated on lookup; patch the module boundary.
    fake_bpy = SimpleNamespace(path=bpy.path, ops=SimpleNamespace(
        wm=SimpleNamespace(save_userpref=lambda: {"CANCELLED"})))
    with patch.object(output_settings, "bpy", fake_bpy):
        try:
            output_settings.remember_output_directory(bpy.context, another)
        except RuntimeError:
            pass
        else:
            raise AssertionError("Failed preference save was accepted")
    assert prefs.atlas_output_directory == directory

    objects = make_pair("fresh")
    assert not bpy.context.scene.mimi_smc_distribution
    # Direct execute automatically plans; an explicit destination must not
    # overwrite a different remembered folder. Restore the real default after.
    prefs.atlas_output_directory = another
    assert bpy.ops.mimi.combiner(directory=directory) == {"FINISHED"}
    assert output_settings.default_output_directory(bpy.context) == another
    prefs.atlas_output_directory = directory
    first_results = results.diffuse_results()
    assert len(first_results) == 1 and os.path.isfile(first_results[0][1])
    assert len(objects[0].data.materials) == 1
    first_name, first_path = first_results[0]
    first_bytes = open(first_path, "rb").read()

    # A second source merges through invoke without opening a file browser.
    objects = make_pair("second")
    # Switching formats in the same directory must still reserve previous IDs.
    bpy.context.scene.mimi_smc_image_format = "DDS"
    assert bpy.ops.mimi.generate_size_distribution() == {"FINISHED"}
    # Feasible manual edits must trigger automatic recalculation inside invoke.
    locked = bpy.context.scene.mimi_smc_distribution[0]
    locked.width = locked.height = 64
    assert locked.locked and not bpy.context.scene.mimi_smc_distribution_valid
    op = SimpleNamespace(directory="", report=lambda *args: None)
    op._ensure_distribution = lambda context: Combiner._ensure_distribution(op, context)
    op._return_with_message = lambda kind, text: {"CANCELLED"}
    op.execute = lambda context: bpy.ops.mimi.combiner(directory=op.directory)
    assert Combiner.invoke(op, bpy.context, None) == {"FINISHED"}
    assert len(results.diffuse_results()) == 2
    assert open(first_path, "rb").read() == first_bytes
    # Direct exports to a different folder must not rewrite the user's default.
    assert prefs.atlas_output_directory == directory

    # A misleading filename and non-albedo role never become diffuse results.
    fake = bpy.data.images.new("atlas_normal_looks_diffuse", 1, 1)
    fake.filepath = first_path
    results.mark_atlas_image(fake, "normal", "test")
    assert len(results.diffuse_results()) == 2
    assert not results.result_path(fake.name)

    tree = bpy.data.node_groups.new("workflow_blueprint", "MIMIBlueprintTreeType")
    # Standalone synthetic blueprints need a user to survive Blender saving.
    tree.use_fake_user = True
    # All four texture replacement node types must use the generated result.
    for node_type in ("MIMINode_Texture_Bind", "MIMINode_Hash_Texture_Bind",
                      "MIMINode_Hash_Texture_Global", "MIMINode_Texture_Global"):
        node = tree.nodes.new(node_type)
        profile = texture_row_ui.profile_for(node)
        if profile:
            row = getattr(node, profile.rows_prop).add()
            if hasattr(row, "texture_hash"):
                row.texture_hash = "abcdef12"
                row.mark_source_name = "DiffuseMap"
            else:
                row.identity = "LOD0|94517393-0|ps-t0|DiffuseMap"
                row.mark_name = "DiffuseMap"
            key = str(profile.key(row))
        else:
            node.name = "targeted_slot"
            row = node.texture_slot_items.add()
            row.source_type = "FILE"
            row.slot = "ps-t0"
            key = str(row.as_pointer())
        assert bpy.ops.mimi.texture_row_select_merged(
            tree_name=tree.name, node_name=node.name, row_index=0,
            row_key=key, result_image=first_name) == {"FINISHED"}
        assert row.file_path == first_path
        # Hash assignment must become a FILE source via its existing callback.
        if hasattr(row, "source_type"):
            assert row.source_type == "FILE"
        if node_type == "MIMINode_Texture_Bind":
            binding = BluePrintModel._collect_texture_bindings(node)[0]
            assert binding["file_path"] == first_path and binding["source_type"] == "FILE"

    # A MARK source keeps semantic capture lookup rather than forcing a raw slot.
    slot_node = tree.nodes.get("targeted_slot")
    slot_row = slot_node.texture_slot_items.add()
    slot_row.source_type = "MARK"
    slot_row.mark_name_value = "DiffuseMap"
    assert bpy.ops.mimi.texture_row_select_merged(
        tree_name=tree.name, node_name=slot_node.name, row_index=1,
        row_key=str(slot_row.as_pointer()), result_image=first_name) == {"FINISHED"}
    assert slot_row.source_type == "MARK" and slot_row.mark_file_path == first_path
    # Removed or moved files are excluded again at execution, with no row mutation.
    image = bpy.data.images.get(first_name)
    enum_numbers = {item[0]: item[4] for item in texture_row_ui._merged_result_items(None, bpy.context)}
    image.filepath = os.path.join(directory, "missing.png")
    assert not results.result_path(first_name)
    # Removing an earlier result must not reindex the remaining choices.
    for item in texture_row_ui._merged_result_items(None, bpy.context):
        assert item[4] == enum_numbers[item[0]]
    # Execute rechecks the file and the row, not only the popup's earlier list.
    selection = SimpleNamespace(result_image=first_name, tree_name=tree.name,
        node_name=slot_node.name, row_index=1, row_key=str(slot_row.as_pointer()),
        report=lambda *args: None)
    assert texture_row_ui.MIMI_OT_TextureRowSelectMerged.execute(selection, bpy.context) == {"CANCELLED"}
    assert slot_row.mark_file_path == first_path
    image.filepath = first_path
    assert results.result_path(first_name) == first_path
    selection.row_key = "removed_row"
    assert texture_row_ui.MIMI_OT_TextureRowSelectMerged.execute(selection, bpy.context) == {"CANCELLED"}
    assert slot_row.mark_file_path == first_path
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(directory, "workflow.blend"))

    # Failed constraints and invalid folders must preserve live UVs and files.
    objects = make_pair("impossible")
    scene = bpy.context.scene
    scene.mimi_smc_total_size = True
    scene.mimi_smc_total_width = scene.mimi_smc_total_height = 64
    bpy.ops.mimi.generate_size_distribution()
    for entry in scene.mimi_smc_distribution:
        entry.width = entry.height = 64
    before = snapshot(objects)
    expect_cancelled(lambda: bpy.ops.mimi.combiner())
    assert snapshot(objects) == before
    assert all(entry.locked and entry.width == 64 for entry in scene.mimi_smc_distribution)
    expect_cancelled(lambda: bpy.ops.mimi.combiner(directory=os.path.join(directory, "missing")))
    assert snapshot(objects) == before
    assert len(results.diffuse_results()) == 2
    print("WORKFLOW_PASS " + json.dumps({"directory": directory, "results": 2, "nodes": 4}))


if __name__ == "__main__":
    main()
