
'''
Import model configuration panel
'''
import os
import shutil
import bpy

# Workaround for the AttributeError raised when a file-picker operator does not inherit
# ImportHelper: the 'filepath' attribute would be missing.
from bpy_extras.io_utils import ImportHelper

from ..utils.json_utils import JsonUtils
from ..utils.collection_utils import CollectionUtils, CollectionColor
from ..utils.timer_utils import TimerUtils

from ..common.global_config import GlobalConfig
from ..common.ssmt_import_helper import SSMTImportHelper
from ..common.gimi_high_fidelity_material import GIMIHighFidelityMaterial
from ..workspace.ssmt_workspace import SSMTWorkSpace, WorkSpaceModel
from ..blueprint.blueprint_export_helper import BlueprintExportHelper
from ..i18n.i18n import I18nOperator, tr
from math import pi
from mathutils import Quaternion, Vector


_SUBMESH_ROLES = {"Face", "Neck", "Eye"}
_SUBMESH_ROLE_PROPERTY = "SSMT:SubMeshRole"
_FACE_NECK_PLANE_TOLERANCE = 0.001
_FACE_CHIN_HEIGHT_TOLERANCE = 0.004
_NECK_ANCHOR_SEARCH_RADIUS = 0.06


def _read_submesh_role(json_path: str) -> str:
    """Read the SSMT role contract; absent/unknown values are unmarked."""
    try:
        data = JsonUtils.LoadFromFile(json_path)
    except Exception:
        return ""
    role = data.get("SubMeshRole", "") if isinstance(data, dict) else ""
    return role if role in _SUBMESH_ROLES else ""


def _get_eye_diffuse_paths(json_path: str) -> list[str]:
    """Read the ordered, Blender-facing ``DiffuseMap`` metadata field."""
    try:
        data = JsonUtils.LoadFromFile(json_path)
    except Exception:
        return []
    filenames = data.get("DiffuseMap", []) if isinstance(data, dict) else []
    if not isinstance(filenames, list):
        return []
    directory = os.path.dirname(json_path)
    paths = []
    for filename in filenames:
        if not isinstance(filename, str) or not filename:
            continue
        # The interface defines these as filenames relative to the JSON file.
        path = os.path.join(directory, os.path.basename(filename))
        if os.path.isfile(path):
            paths.append(path)
    return paths


def _get_face_shader_metadata(json_path: str) -> tuple[list[str], str, str, str | None]:
    """Read SSMT4's face texture roles from the target JSON metadata."""
    diffuse_paths = _get_eye_diffuse_paths(json_path)
    try:
        data = JsonUtils.LoadFromFile(json_path)
    except Exception:
        return diffuse_paths, '', 'R', None
    directory = os.path.dirname(json_path)
    sdf_path, sdf_channel, shadow_path = '', 'R', None
    marks = data.get('TextureMarkUpInfoList', []) if isinstance(data, dict) else []
    for mark in marks if isinstance(marks, list) else []:
        if not isinstance(mark, dict):
            continue
        name = str(mark.get('MarkName', '') or '').casefold()
        filename = str(mark.get('MarkFileName', '') or '')
        path = os.path.join(directory, os.path.basename(filename))
        if not os.path.isfile(path):
            continue
        if name == 'facesdfmap' and not sdf_path:
            sdf_path = path
            channel = str(mark.get('FaceSDFChannel', 'R') or 'R').upper()
            sdf_channel = channel if channel in {'R', 'G', 'B', 'A'} else 'R'
        elif name in {'faceshadow', 'lightmap'} and shadow_path is None:
            shadow_path = path
    return diffuse_paths, sdf_path, sdf_channel, shadow_path


def _apply_submesh_role_rendering(obj, role: str, json_path: str) -> None:
    if role not in {"Face", "Eye"}:
        return
    diffuse_paths = _get_eye_diffuse_paths(json_path)
    if not diffuse_paths:
        print(f"[GIMI {role}] {json_path} has no valid DiffuseMap shortcut metadata; skipping material build.")
        return
    face_metadata = _get_face_shader_metadata(json_path) if role == 'Face' else None
    for slot in getattr(obj, "material_slots", ()):
        if role == 'Eye':
            GIMIHighFidelityMaterial.configure_eye_alpha_emission(slot.material, diffuse_paths)
        else:
            _, sdf_path, sdf_channel, shadow_path = face_metadata
            if not GIMIHighFidelityMaterial.configure_face_sdf_material(
                slot.material, diffuse_paths, sdf_path, sdf_channel, shadow_path,
            ):
                print(f"[GIMI Face] {json_path} lacks FaceSDFMap; keeping the regular material.")


def _yoz_vertices(obj, rotation, referenced_only=False):
    mesh = obj.data
    referenced = None
    if referenced_only:
        referenced = {index for polygon in mesh.polygons for index in polygon.vertices}
    vertices = [
        rotation @ vertex.co
        for vertex in mesh.vertices
        if referenced is None or vertex.index in referenced
    ]
    if not vertices:
        return []
    nearest = min(abs(vertex.x) for vertex in vertices)
    return [vertex for vertex in vertices if abs(vertex.x) <= nearest + _FACE_NECK_PLANE_TOLERANCE]


def _find_face_anchor(face_objects, rotation):
    vertices = [vertex for obj in face_objects for vertex in _yoz_vertices(obj, rotation)]
    if not vertices:
        return None
    lowest_z = min(vertex.z for vertex in vertices)
    candidates = [vertex for vertex in vertices if vertex.z <= lowest_z + _FACE_CHIN_HEIGHT_TOLERANCE]
    return max(candidates, key=lambda vertex: vertex.y).copy()


def _find_neck_anchor(neck_obj):
    vertices = _yoz_vertices(neck_obj, Quaternion(), referenced_only=True)
    if not vertices:
        return None
    highest = max(vertices, key=lambda vertex: (vertex.z, vertex.y))
    expected = highest + Vector((0.0, -0.024, -0.18))
    nearby = [vertex for vertex in vertices if (vertex - expected).length <= _NECK_ANCHOR_SEARCH_RADIUS]
    candidates = nearby or vertices
    return min(candidates, key=lambda vertex: (vertex.y, (vertex - expected).length_squared)).copy()


def _apply_face_neck_object_alignment(imported_objects: dict) -> bool:
    """Port of FaceNeckObjectAlignment.ts; mesh coordinates remain untouched."""
    faces = [obj for obj, _ in imported_objects.values() if obj.get(_SUBMESH_ROLE_PROPERTY, "") == "Face"]
    necks = [obj for obj, _ in imported_objects.values() if obj.get(_SUBMESH_ROLE_PROPERTY, "") == "Neck"]
    if not faces or not necks:
        return False

    rotation = Quaternion((1.0, 0.0, 0.0), pi / 2) @ Quaternion((0.0, 0.0, 1.0), -pi / 2)
    for obj in faces:
        obj.location = (0.0, 0.0, 0.0)
        obj.rotation_mode = 'QUATERNION'
        obj.rotation_quaternion = rotation

    face_anchor = _find_face_anchor(faces, rotation)
    neck_anchor = _find_neck_anchor(necks[0])
    if face_anchor is None or neck_anchor is None:
        return False
    translation = neck_anchor - face_anchor
    translation.x = 0.0
    for obj in faces:
        obj.location = translation
    return True


# Full import logic


def _extract_texture_marks(submesh_json: dict) -> list:
    """Extract the texture mark list from a Submesh JSON.

    SSMT4 uses the flat TextureMarkUpInfoList;
    some older data only has the per-component ComponentTextureMarkUpInfoListDict,
    in which case the marks of every component are flattened and returned
    (identical hashes are deduplicated later).
    """
    if not isinstance(submesh_json, dict):
        return []
    mark_list = submesh_json.get("TextureMarkUpInfoList")
    if isinstance(mark_list, list) and mark_list:
        return mark_list
    component_dict = submesh_json.get("ComponentTextureMarkUpInfoListDict")
    if isinstance(component_dict, dict):
        flattened = []
        for component_key in sorted(component_dict.keys()):
            component_marks = component_dict.get(component_key)
            if isinstance(component_marks, list):
                flattened.extend(component_marks)
        return flattened
    return mark_list if isinstance(mark_list, list) else []


def _link_group_to_output(tree, group_node, output_node):
    """Link the group node to the next free input of Result_Output; add one when none is free."""
    if group_node is None or len(group_node.outputs) == 0:
        return
    if len(output_node.inputs) == 0 or output_node.inputs[-1].is_linked:
        output_node.inputs.new('MIMISocketObject', "Group {count}".format(count=len(output_node.inputs) + 1))
    tree.links.new(group_node.outputs[0], output_node.inputs[-1])


def _get_marked_diffuse_hash(json_path: str) -> str:
    """Return the first explicitly marked DiffuseMap hash for a Face SubMesh."""
    try:
        data = JsonUtils.LoadFromFile(json_path)
    except Exception:
        return ""
    for mark in _extract_texture_marks(data):
        if not isinstance(mark, dict):
            continue
        if str(mark.get("MarkName", "") or "").strip().casefold() != "diffusemap":
            continue
        hash_value = str(mark.get("MarkHash", "") or "").strip()
        if hash_value:
            return hash_value
    return ""


def _create_face_mod_export_node(tree, oldfoldername_node_dict, oldfoldername_jsonpath_dict, location):
    """Create and wire the face exporter when at least one imported SubMesh is marked Face."""
    face_nodes = []
    diffuse_hash = ""
    for old_folder_name, object_node in oldfoldername_node_dict.items():
        json_path = oldfoldername_jsonpath_dict.get(old_folder_name, "")
        if json_path and _read_submesh_role(json_path) == "Face":
            face_nodes.append(object_node)
            if not diffuse_hash:
                diffuse_hash = _get_marked_diffuse_hash(json_path)
    if not face_nodes:
        return None

    export_node = tree.nodes.new('MIMINode_Face_Mod_Export')
    export_node.location = location
    export_node.label = "Export Face Mod"
    export_node.diffuse_hash = diffuse_hash
    export_node.output_folder = os.path.join(GlobalConfig.path_generate_mod_folder(), "Face")
    for object_node in face_nodes:
        if export_node.inputs[-1].is_linked:
            export_node.inputs.new('MIMISocketObject', f"Face Group {len(export_node.inputs) + 1}")
        tree.links.new(object_node.outputs[0], export_node.inputs[-1])
    return export_node


def _exclude_marked_face_objects_from_regular_group(
    tree, group_node, oldfoldername_node_dict, oldfoldername_jsonpath_dict,
):
    """Disconnect only JSON-marked Face objects from the normal mesh group."""
    if group_node is None:
        return
    face_nodes = {
        object_node.name
        for old_folder_name, object_node in oldfoldername_node_dict.items()
        if _read_submesh_role(oldfoldername_jsonpath_dict.get(old_folder_name, "")) == "Face"
    }
    for link in list(tree.links):
        # Blender may hand out distinct Python RNA wrappers for the same node;
        # compare stable node names instead of object identity (``is``).
        if link.from_node.name in face_nodes and link.to_node.name == group_node.name:
            tree.links.remove(link)

def _create_and_layout_obj_info_nodes(tree, group_node, foldername_imported_obj_dict, ws_model):
    """Create Object Info nodes, connect them to the Group and lay them out.

    All Object Info nodes are stacked in a single vertical column from top to
    bottom. The column and the Group node are wrapped in one big NodeFrame
    named after the workspace.

    Returns (oldfoldername_node_dict, oldfoldername_group_dict, max_node_right).
    """
    # old_folder_name -> Object Info node
    oldfoldername_node_dict: dict[str, bpy.types.Node] = {}
    # old_folder_name -> group key (new-format submesh name)
    oldfoldername_group_dict: dict[str, str] = {}
    # Every created Object Info node, in import order
    object_nodes: list[bpy.types.Node] = []

    for new_submesh_name, (imported_obj, display_name) in foldername_imported_obj_dict.items():
        if imported_obj.type != 'MESH':
            continue

        # Resolve the new-format name via WorkSpaceModel to get the component number
        parsed = ws_model.parse_new_format_name(new_submesh_name)
        component_str = str(parsed["component"]) if parsed else "0"

        # Create the node
        node = tree.nodes.new('MIMINode_Object_Info')

        # Fill in the properties
        node.object_name = imported_obj.name
        node.original_object_name = imported_obj.name
        node.component = component_str
        node.submesh_name = display_name
        node.label = imported_obj.name

        old_folder_name = ""
        if parsed:
            old_folder_name = ws_model.get_old_folder_name(
                parsed.get("lod", ""),
                parsed.get("draw_ib", ""),
                parsed.get("component", 0),
            )
        if old_folder_name:
            oldfoldername_node_dict[old_folder_name] = node
            oldfoldername_group_dict[old_folder_name] = new_submesh_name

        object_nodes.append(node)

        # Add a socket manually when the Group's last socket is already occupied
        if group_node.inputs[-1].is_linked:
            group_node.inputs.new('MIMISocketObject', f"Input {len(group_node.inputs) + 1}")
        tree.links.new(node.outputs[0], group_node.inputs[-1])

    # Stack all Object Info nodes into one vertical column, top to bottom.
    NODE_X = 40.0
    # Estimated height of a single Object Info node
    NODE_Y_GAP = 260.0
    y = 0.0
    for node in object_nodes:
        node.location = (NODE_X, y)
        y -= NODE_Y_GAP

    # Place the Group node to the right of the column; it is included in the
    # Frame below, so the Frame wraps the whole import result and the imported
    # content is easy to tell apart at a glance.
    GROUP_X_GAP = 560.0
    group_node.location = (NODE_X + GROUP_X_GAP, -200.0)
    max_node_right = NODE_X + GROUP_X_GAP

    # Wrap the whole column and the Group node in one big Frame named after
    # the workspace. Blender fits the Frame size to its children; only a
    # rough top-left position is given here.
    FRAME_PAD = 40.0
    if object_nodes:
        workspace_name = GlobalConfig.get_workspace_name() or "Workspace"
        frame = tree.nodes.new('NodeFrame')
        frame.label = workspace_name
        frame.name = "Frame_" + workspace_name.replace(" ", "_")
        frame.location = (NODE_X - FRAME_PAD, FRAME_PAD)
        for node in object_nodes:
            abs_x, abs_y = node.location.x, node.location.y
            node.parent = frame
            node.location = (abs_x - frame.location.x, abs_y - frame.location.y)
        abs_x, abs_y = group_node.location.x, group_node.location.y
        group_node.parent = frame
        group_node.location = (abs_x - frame.location.x, abs_y - frame.location.y)

    return (oldfoldername_node_dict, oldfoldername_group_dict, max_node_right)



def _clear_blueprint_node_selection(tree):
    """Leave generated blueprints ready for inspection, without a selected graph."""
    for node in tree.nodes:
        node.select = False
    tree.nodes.active = None


def _deselect_imported_objects(imported_objects):
    """Clear the importer-created selection while preserving prior scene selection."""
    objects = tuple(obj for obj, _ in imported_objects.values())
    for obj in objects:
        obj.select_set(False)

    active_object = bpy.context.view_layer.objects.active
    if active_object in objects:
        bpy.context.view_layer.objects.active = None


def _deselect_imported_shader_nodes(imported_objects):
    """Clear selections left on all shader trees created during model import.

    High-fidelity materials build reusable shader groups in ``bpy.data``;
    some of those trees are not reachable through an imported object's
    material slot, so walking only the material graph leaves nodes selected.
    """
    visited_trees = set()

    def clear_tree(node_tree):
        if node_tree is None:
            return
        pointer = node_tree.as_pointer()
        if pointer in visited_trees:
            return
        visited_trees.add(pointer)
        for node in node_tree.nodes:
            node.select = False
            group_tree = getattr(node, "node_tree", None)
            if getattr(group_tree, "bl_idname", "") == "ShaderNodeTree":
                clear_tree(group_tree)
        node_tree.nodes.active = None

    # Include every registered ShaderNodeTree. This also covers reusable
    # groups created during import that are temporarily unattached.
    for node_tree in bpy.data.node_groups:
        if getattr(node_tree, "bl_idname", "") == "ShaderNodeTree":
            clear_tree(node_tree)

    # Keep the material-slot walk for Blender versions where a material node
    # tree is not exposed in bpy.data.node_groups during the import callback.
    for obj, _ in imported_objects.values():
        for material_slot in getattr(obj, "material_slots", ()):
            material = material_slot.material
            if material is not None:
                clear_tree(material.node_tree)


def ImprotFromWorkSpaceFull(self, context):
    
    # Create a WorkSpaceModel to manage all the mappings
    ws_model = WorkSpaceModel()

    # First create the collection named after the current workspace and link it to the scene, ensuring it exists
    workspace_collection = SSMTWorkSpace.create_and_get_workspace_collection()

    if not ws_model.lod_components:
        self.report({'ERROR'}, tr("No LOD directories (LOD0, LOD1, ...) were found in the current workspace. Please check the workspace structure."))
        return

    # key: new-format submesh_name (e.g. "LOD0.94517393-0"), value: gametype_name
    foldername_gametypename_dict = {}
    foldername_imported_obj_dict = {}
    # old_folder_name -> actual Submesh JSON path used for import (source of the texture-mark metadata)
    oldfoldername_jsonpath_dict = {}
    all_submesh_display_names = []
    successful_import_count = 0

    for lod_name in sorted(ws_model.lod_components.keys()):
        # Create a blue sub-collection per LOD, linked under the workspace collection
        lod_collection = CollectionUtils.create_new_collection(
            collection_name=lod_name,
            color_tag=CollectionColor.Blue,
        )
        workspace_collection.children.link(lod_collection)

        drawib_components = ws_model.lod_components[lod_name]

        for draw_ib in sorted(drawib_components.keys()):
            comp_map = drawib_components[draw_ib]

            for comp_index in sorted(comp_map.keys()):
                old_folder_name = comp_map[comp_index]
                new_submesh_name = ws_model.get_new_submesh_name(lod_name, draw_ib, comp_index)
                display_name = ws_model.get_display_name(lod_name, draw_ib, comp_index)
                folder_path = ws_model.get_folder_path(lod_name, draw_ib, comp_index)

                if not folder_path or not os.path.isdir(folder_path):
                    continue

                print("Import FolderName: " + folder_path)

                # Get the ordered data-type folder path list to import from
                final_import_folder_path_list = SSMTWorkSpace.get_ordered_gpu_cpu_import_folderpath_list(folder_path)
                print("Final Import Folder Path List: " + str(final_import_folder_path_list))

                # Now import, trying every data type of the current DrawIB
                for import_folder_path in final_import_folder_path_list:
                    gametype_name = import_folder_path.split("TYPE_")[1]

                    try:
                        print("Attempting import path: " + import_folder_path)

                        json_file_path = os.path.join(import_folder_path, old_folder_name + ".json")
                        imported_obj = SSMTImportHelper.create_mesh_from_json(
                            json_file_path=json_file_path,
                            import_collection=lod_collection,
                        )
                        if imported_obj is not None:
                            imported_obj.name = display_name
                            imported_obj.data.name = imported_obj.name
                            role = _read_submesh_role(json_file_path)
                            imported_obj[_SUBMESH_ROLE_PROPERTY] = role
                            _apply_submesh_role_rendering(imported_obj, role, json_file_path)
                            foldername_imported_obj_dict[new_submesh_name] = (imported_obj, display_name)
                            all_submesh_display_names.append(display_name)
                            successful_import_count += 1

                        foldername_gametypename_dict[new_submesh_name] = gametype_name
                        oldfoldername_jsonpath_dict[old_folder_name] = json_file_path
                        self.report({'INFO'}, tr("Successfully imported ") + new_submesh_name + tr(" data type: ") + gametype_name)
                    except Exception as e:
                        print(f"Failed to import from {import_folder_path}: {e}")
                        continue
                    # Break after the first successful import
                    break

    if successful_import_count == 0:
        self.report({'ERROR'}, tr("No models were successfully imported from the current workspace; blueprint generation was skipped."))
        return

    # Save the workspace-level Import.json selection record (using new-format keys)
    save_import_json_path = os.path.join(GlobalConfig.path_workspace_folder(), "Import.json")
    JsonUtils.SaveToFile(json_dict=foldername_gametypename_dict, filepath=save_import_json_path)
    
    if getattr(context.scene.mimi_global_properties, "align_face_on_import", False):
        if not _apply_face_neck_object_alignment(foldername_imported_obj_dict):
            self.report({'WARNING'}, tr("Face alignment requires at least one valid Face mark and one Neck mark."))

    _deselect_imported_objects(foldername_imported_obj_dict)
    _deselect_imported_shader_nodes(foldername_imported_obj_dict)

    # ==========================
    # Auto-generate blueprint node graph
    # ==========================
    try:
        # Create the blueprint, named after the current workspace
        tree_name = GlobalConfig.get_workspace_name()
        
        # Nico: always create a new blueprint to avoid overwriting user-modified ones
        # If a blueprint with the same name exists, Blender appends a suffix like .001, preserving the old one
        try:
            tree = bpy.data.node_groups.new(name=tree_name, type='MIMIBlueprintTreeType')
        except Exception as e:
            print(f"Failed to create new node tree: {e}. Check if MIMIBlueprintTreeType is registered.")
            return
        tree.use_fake_user = True
        BlueprintExportHelper.set_tree_submesh_names(all_submesh_display_names, tree=tree)
        
        # Create the Group node (and link to it in the loop)
        group_node = tree.nodes.new('MIMINode_Object_Group')
        group_node.label = "Default Group"
        
        # 3. Create Object Info nodes stacked in one vertical column; the column and the Group node share one workspace-named Frame
        (oldfoldername_node_dict, oldfoldername_group_dict, max_node_right) = _create_and_layout_obj_info_nodes(
            tree, group_node, foldername_imported_obj_dict, ws_model)

        # 4. Place the Output nodes (the Group node is already placed inside the Frame)
        group_node.label = "Master Mesh Group"

        output_node = tree.nodes.new('MIMINode_Result_Output')
        output_node.location = (max_node_right + 480.0, -200.0)
        output_node.label = "Generate Mod"

        face_export_node = _create_face_mod_export_node(
            tree, oldfoldername_node_dict, oldfoldername_jsonpath_dict,
            (max_node_right + 480.0, -760.0),
        )
        
        # Link the side-by-side group nodes directly to the Output
        _link_group_to_output(tree, face_export_node, output_node)
        _link_group_to_output(tree, group_node, output_node)

        if hasattr(group_node, "update"):
            group_node.update()
        _exclude_marked_face_objects_from_regular_group(
            tree, group_node, oldfoldername_node_dict, oldfoldername_jsonpath_dict,
        )

        BlueprintExportHelper.set_runtime_blueprint_tree(tree)

        mimi_global_properties = getattr(getattr(context, "scene", None), "mimi_global_properties", None)
        if mimi_global_properties:
            mimi_global_properties.selected_blueprint_name = tree.name

        BlueprintExportHelper.reveal_tree_in_node_editors(context, tree)
        _clear_blueprint_node_selection(tree)

        print(f"Blueprint {tree_name} updated with imported objects.")
        
    except Exception as e:
        print(f"Error generating blueprint nodes: {e}")
        import traceback
        traceback.print_exc()
    


class SSMT4ImportAllFromCurrentWorkSpaceBlueprint(I18nOperator):
    bl_idname = "mimi.import_all_from_workspace"
    bl_label = "Import All From SSMT Workspace"
    bl_description = "Import everything from the current workspace folder with one click."
    bl_options = {'REGISTER','UNDO'}

    def execute(self, context):
        # print("Current WorkSpace: " + GlobalConfig.get_workspace_name())
        # print("Current Game: " + GlobalConfig.gamename)
        if GlobalConfig.get_workspace_name() == "":
            self.report({"ERROR"}, tr("Please select the current workspace in SSMT before importing."))
        elif not os.path.exists(GlobalConfig.path_workspace_folder()):
            self.report({"ERROR"}, tr("Workspace folder does not exist. Please create a workspace in SSMT first: {path}").format(path=GlobalConfig.path_workspace_folder()))
        else:
            TimerUtils.Start("ImportFromWorkSpaceBlueprint")
            ImprotFromWorkSpaceFull(self, context)
            TimerUtils.End("ImportFromWorkSpaceBlueprint")
        
        return {'FINISHED'}
    

class SSMT4ImportRaw(I18nOperator, ImportHelper):
    bl_idname = "mimi.import_raw"
    bl_label = "Import SSMT Model"
    bl_description = "Import an SSMT model file. You only need to select the .json file."
    bl_options = {'REGISTER','UNDO'}

    filter_glob: bpy.props.StringProperty(
        default='*.json',
        options={'HIDDEN'},
    ) # type: ignore

    files: bpy.props.CollectionProperty(
        name=tr("File Path"),
        type=bpy.types.OperatorFileListElement,
    ) # type: ignore

    def execute(self, context):
        # We need to add to a newly created collection for the later steps
        # The collection must be named after the current folder
        dirname = os.path.dirname(self.filepath)

        collection_name = os.path.basename(dirname)
        collection = bpy.data.collections.new(collection_name)
        bpy.context.scene.collection.children.link(collection)

        # If the user does not select any json file, fall back to importing every json file.
        import_filename_list = []
        if len(self.files) == 1:
            if str(self.filepath).endswith(".json"):
                import_filename_list.append(self.filepath)
            else:
                for filename in os.listdir(self.filepath):
                    if filename.endswith(".json"):
                        import_filename_list.append(filename)
        else:
            for json_file in self.files:
                import_filename_list.append(json_file.name)

        # Import the json files one by one
        for json_file_name in import_filename_list:
            if os.path.isabs(json_file_name):
                json_file_path = json_file_name
            else:
                json_file_path = os.path.join(dirname, json_file_name)
            SSMTImportHelper.create_mesh_from_json(json_file_path=json_file_path, import_collection=collection)

        CollectionUtils.deselect_collection_objects(collection)

        return {'FINISHED'}

# =============================================================================
# Filtered import logic - only the listed submesh folders are imported
# =============================================================================
def _get_or_create_lod_collection(workspace_collection, lod_name):
    '''Find or create the LOD sub-collection (reuse existing collections to avoid duplicates).'''
    if lod_name in workspace_collection.children:
        return workspace_collection.children[lod_name]
    # Check whether it already exists in bpy.data.collections
    if lod_name in bpy.data.collections:
        existing = bpy.data.collections[lod_name]
        # If it exists but is not linked under the workspace yet, link it
        if existing.name not in workspace_collection.children:
            workspace_collection.children.link(existing)
        return existing
    lod_collection = CollectionUtils.create_new_collection(
        collection_name=lod_name,
        color_tag=CollectionColor.Blue,
    )
    workspace_collection.children.link(lod_collection)
    return lod_collection


def _get_or_create_workspace_collection():
    '''Find or create the workspace collection (reuse existing collections to avoid duplicates).'''
    workspace_name = GlobalConfig.get_workspace_name()
    if workspace_name in bpy.data.collections:
        ws_coll = bpy.data.collections[workspace_name]
        # Make sure it is linked to the scene
        if ws_coll.name not in bpy.context.scene.collection.children:
            bpy.context.scene.collection.children.link(ws_coll)
        return ws_coll
    return SSMTWorkSpace.create_and_get_workspace_collection()


def ImprotFromWorkSpaceSelected(self, context, submesh_lod_info_list, force_gametype_name=None):
    '''
    Import only the given list of submeshes.
    submesh_lod_info_list: [(lod_name, submesh_folder_path), ...]
    e.g. [("LOD0", "D:/SSMTCacheFolder/WorkSpace/GF2/Default/LOD0/3ed2b2ba-2592-76086"), ...]
    force_gametype_name: when given (e.g. "CPU_P12_N12_TA16_C16_T4_"),
      forces every submesh to try only that data type (used for the DrawIB
      unified data-type scenario).
      Passing "__AUTO__" makes the first submesh try all types normally,
      then uses whichever type works for every later submesh.
    '''
    ws_model = WorkSpaceModel()
    workspace_collection = _get_or_create_workspace_collection()

    foldername_gametypename_dict = {}
    foldername_imported_obj_dict = {}
    # old_folder_name -> actual Submesh JSON path used for import (source of the texture-mark metadata)
    oldfoldername_jsonpath_dict = {}
    all_submesh_display_names = []
    successful_import_count = 0

    # When force_gametype_name == "__AUTO__", lock the type after the first success
    locked_gametype = None

    # Group by LOD
    lod_submesh_map: dict[str, list[str]] = {}
    for lod_name, submesh_folder_path in submesh_lod_info_list:
        if lod_name not in lod_submesh_map:
            lod_submesh_map[lod_name] = []
        lod_submesh_map[lod_name].append(submesh_folder_path)

    for lod_name, submesh_folder_paths in lod_submesh_map.items():
        # Find or create the LOD sub-collection (reuse existing ones)
        lod_collection = _get_or_create_lod_collection(workspace_collection, lod_name)

        for submesh_folder_path in submesh_folder_paths:
            submesh_folder_name = os.path.basename(submesh_folder_path)
            print("Re-Import FolderName: " + submesh_folder_name)

            # Get the component index and the new-format name from WorkSpaceModel
            old_folder_draw_ib = submesh_folder_name.split("-")[0]
            comp_index = ws_model.get_component_index(lod_name, old_folder_draw_ib, submesh_folder_name)
            if comp_index < 0:
                comp_index = 0

            new_submesh_name = ws_model.get_new_submesh_name(lod_name, old_folder_draw_ib, comp_index)
            display_name = ws_model.get_display_name(lod_name, old_folder_draw_ib, comp_index)

            # Decide the list of data-type folders to try
            if locked_gametype is not None:
                final_import_folder_path_list = [
                    os.path.join(submesh_folder_path, "TYPE_" + locked_gametype)
                ]
            elif force_gametype_name and force_gametype_name != "__AUTO__":
                final_import_folder_path_list = [
                    os.path.join(submesh_folder_path, "TYPE_" + force_gametype_name)
                ]
            else:
                final_import_folder_path_list = SSMTWorkSpace.get_ordered_gpu_cpu_import_folderpath_list(submesh_folder_path)
            print("Re-Import Folder Path List: " + str(final_import_folder_path_list))

            for import_folder_path in final_import_folder_path_list:
                if not os.path.isdir(import_folder_path):
                    print(f"Data-type folder does not exist; skipping: {import_folder_path}")
                    continue
                gametype_name = import_folder_path.split("TYPE_")[1]

                try:
                    print("Attempting import path: " + import_folder_path)

                    json_file_path = os.path.join(import_folder_path, submesh_folder_name + ".json")
                    imported_obj = SSMTImportHelper.create_mesh_from_json(
                        json_file_path=json_file_path,
                        import_collection=lod_collection,
                    )
                    if imported_obj is not None:
                        imported_obj.name = display_name
                        imported_obj.data.name = imported_obj.name
                        role = _read_submesh_role(json_file_path)
                        imported_obj[_SUBMESH_ROLE_PROPERTY] = role
                        _apply_submesh_role_rendering(imported_obj, role, json_file_path)
                        foldername_imported_obj_dict[new_submesh_name] = (imported_obj, display_name)
                        all_submesh_display_names.append(display_name)
                        successful_import_count += 1

                    foldername_gametypename_dict[new_submesh_name] = gametype_name
                    oldfoldername_jsonpath_dict[submesh_folder_name] = json_file_path
                    self.report({'INFO'}, tr("Successfully imported ") + new_submesh_name + tr(" data type: ") + gametype_name)

                    # In __AUTO__ mode, lock the type once the first import succeeds
                    if locked_gametype is None and force_gametype_name == "__AUTO__":
                        locked_gametype = gametype_name
                        self.report({'INFO'}, tr("DrawIB unified type locked to: {name}; all later submeshes will use this type").format(name=locked_gametype))
                except Exception as e:
                    print(f"Failed to re-import from {import_folder_path}: {e}")
                    continue
                break

    if successful_import_count == 0:
        self.report({'ERROR'}, tr("None of the selected submeshes were imported successfully."))
        return

    # Update Import.json (keep existing records, overwrite the ones imported now)
    save_import_json_path = os.path.join(GlobalConfig.path_workspace_folder(), "Import.json")
    existing_import_json = {}
    if os.path.exists(save_import_json_path):
        try:
            existing_import_json = JsonUtils.LoadFromFile(save_import_json_path) or {}
        except Exception:
            existing_import_json = {}
    existing_import_json.update(foldername_gametypename_dict)
    JsonUtils.SaveToFile(json_dict=existing_import_json, filepath=save_import_json_path)

    if getattr(context.scene.mimi_global_properties, "align_face_on_import", False):
        if not _apply_face_neck_object_alignment(foldername_imported_obj_dict):
            self.report({'WARNING'}, tr("Face alignment requires at least one valid Face mark and one Neck mark."))

    _deselect_imported_objects(foldername_imported_obj_dict)
    _deselect_imported_shader_nodes(foldername_imported_obj_dict)

    # Generate the blueprint
    _generate_blueprint_for_imported_objects(context, foldername_imported_obj_dict, all_submesh_display_names, oldfoldername_jsonpath_dict)


def _generate_blueprint_for_imported_objects(context, foldername_imported_obj_dict, all_submesh_display_names, oldfoldername_jsonpath_dict=None):
    '''Update the nodes of an existing blueprint (do not create a new one); skip when no blueprint exists.'''
    tree_name = GlobalConfig.get_workspace_name()
    if not tree_name:
        return

    # Find the existing blueprint; skip if there is none
    tree = bpy.data.node_groups.get(tree_name)
    if not tree:
        print(f"Existing blueprint '{tree_name}' not found; skipping the blueprint update")
        return
    if not BlueprintExportHelper._is_valid_blueprint_tree(tree):
        print(f"Existing node group '{tree_name}' is not a valid SSMT blueprint; skipping")
        return

    try:
        # Clear all nodes and links
        tree.nodes.clear()

        tree.use_fake_user = True
        BlueprintExportHelper.set_tree_submesh_names(all_submesh_display_names, tree=tree)

        group_node = tree.nodes.new('MIMINode_Object_Group')
        group_node.label = "Default Group"

        ws_model = WorkSpaceModel()

        (oldfoldername_node_dict, oldfoldername_group_dict, max_node_right) = _create_and_layout_obj_info_nodes(
            tree, group_node, foldername_imported_obj_dict, ws_model)

        output_node = tree.nodes.new('MIMINode_Result_Output')
        output_node.location = (max_node_right + 480.0, -200.0)
        output_node.label = "Generate Mod"

        face_export_node = _create_face_mod_export_node(
            tree, oldfoldername_node_dict, oldfoldername_jsonpath_dict or {},
            (max_node_right + 480.0, -760.0),
        )

        _link_group_to_output(tree, face_export_node, output_node)
        _link_group_to_output(tree, group_node, output_node)

        if hasattr(group_node, "update"):
            group_node.update()
        _exclude_marked_face_objects_from_regular_group(
            tree, group_node, oldfoldername_node_dict, oldfoldername_jsonpath_dict or {},
        )

        BlueprintExportHelper.set_runtime_blueprint_tree(tree)

        mimi_global_properties = getattr(getattr(context, "scene", None), "mimi_global_properties", None)
        if mimi_global_properties:
            mimi_global_properties.selected_blueprint_name = tree.name

        BlueprintExportHelper.reveal_tree_in_node_editors(context, tree)
        _clear_blueprint_node_selection(tree)

        print(f"Blueprint {tree_name} updated with imported objects.")
    except Exception as e:
        print(f"Error updating blueprint nodes: {e}")
        import traceback
        traceback.print_exc()


# =============================================================================
# Utility functions - deleting objects
# =============================================================================
def _delete_objects(obj_names_to_delete: list[str]):
    '''Delete all objects with the given names from the Blender scene.'''
    for obj_name in obj_names_to_delete:
        if obj_name in bpy.data.objects:
            obj = bpy.data.objects[obj_name]
            # Unlink it from all collections
            for coll in list(obj.users_collection):
                coll.objects.unlink(obj)
            bpy.data.objects.remove(obj, do_unlink=True)


def _count_type_folders(submesh_folder_path: str) -> int:
    '''Count the TYPE_-prefixed folders inside the submesh folder.'''
    count = 0
    if not os.path.isdir(submesh_folder_path):
        return 0
    for entry in os.scandir(submesh_folder_path):
        if entry.is_dir() and entry.name.startswith("TYPE_"):
            count += 1
    return count


def _show_last_type_warning(submesh_folder_name: str):
    '''Show a warning popup: this submesh is down to its last data type and cannot be deleted.'''
    def draw_popup(self, context):
        self.layout.label(
            text=tr("Submesh '{name}' is down to its last data-type folder;").format(name=submesh_folder_name)
        )
        self.layout.label(
            text=tr("That type cannot be deleted. If no correct data type exists, contact the SSMT developer to add one.")
        )
    bpy.context.window_manager.popup_menu(draw_popup, title=tr("Warning"), icon='ERROR')


# =============================================================================
# Operator - the DrawIB data type is incorrect
# =============================================================================
class SSMT4FixDrawIBDataType(I18nOperator):
    bl_idname = "mimi.fix_drawib_datatype"
    bl_label = "Fix DrawIB Data Type"
    bl_description = "The DrawIB data type is incorrect: delete all matching data-type folders under this DrawIB, delete the related meshes, and re-import"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        selected_objects = context.selected_objects
        if not selected_objects:
            self.report({'ERROR'}, tr("Please select one or more objects first"))
            return {'CANCELLED'}

        from ..workspace.ssmt_workspace import SSMTWorkSpace

        workspace_folder = GlobalConfig.path_workspace_folder()
        if not workspace_folder or not os.path.exists(workspace_folder):
            self.report({'ERROR'}, tr("Workspace folder does not exist. Please set the workspace first."))
            return {'CANCELLED'}

        ws_model = WorkSpaceModel()

        # 1. Parse each selected object, collecting {lod_name: set_of_drawib}
        lod_drawib_set: dict[str, set[str]] = {}
        # Also record the names of the objects to delete
        all_obj_info = []  # [(obj_name, lod_name, submesh_folder_name, draw_ib, gametypename)]
        for obj in selected_objects:
            gametypename = obj.get("3DMigoto:GameTypeName", "")
            if not gametypename:
                self.report({'WARNING'}, tr("Object '{name}' has no data-type attribute; skipped").format(name=obj.name))
                continue

            parsed = ws_model.parse_any_format_name(obj.name)
            if not parsed or not parsed["lod"] or not parsed["draw_ib"]:
                self.report({'WARNING'}, tr("Could not parse the name of object '{name}'; skipped").format(name=obj.name))
                continue

            submesh_folder_path = ws_model.get_folder_path(parsed["lod"], parsed["draw_ib"], parsed["component"])
            submesh_folder_name = os.path.basename(submesh_folder_path) if submesh_folder_path else ""

            all_obj_info.append((obj.name, parsed["lod"], submesh_folder_name, parsed["draw_ib"], gametypename))
            if parsed["lod"] not in lod_drawib_set:
                lod_drawib_set[parsed["lod"]] = set()
            lod_drawib_set[parsed["lod"]].add(parsed["draw_ib"])

        if not all_obj_info:
            self.report({'ERROR'}, tr("Could not resolve any valid information from the selected objects."))
            return {'CANCELLED'}

        # 2. Pre-check: collect every submesh folder under this DrawIB
        all_submesh_entries: list[tuple[str, str, str]] = []  # [(lod_name, submesh_folder_name, submesh_folder_path)]
        for lod_name, draw_ib_set in lod_drawib_set.items():
            lod_folder_path = os.path.join(workspace_folder, lod_name)
            if not os.path.isdir(lod_folder_path):
                self.report({'WARNING'}, tr("LOD directory does not exist: {path}").format(path=lod_folder_path))
                continue
            for entry in os.scandir(lod_folder_path):
                if not entry.is_dir():
                    continue
                folder_draw_ib = entry.name.split("-")[0]
                if folder_draw_ib in draw_ib_set:
                    all_submesh_entries.append((lod_name, entry.name, entry.path))

        if not all_submesh_entries:
            self.report({'ERROR'}, tr("No matching submesh folders were found."))
            return {'CANCELLED'}

        # 3. Pre-check: see whether any submesh is down to its last data type
        for lod_name, submesh_folder_name, submesh_folder_path in all_submesh_entries:
            for _, o_lod, o_submesh, o_draw_ib, gametypename in all_obj_info:
                if o_lod != lod_name or o_submesh != submesh_folder_name:
                    continue
                type_folder_path = os.path.join(submesh_folder_path, "TYPE_" + gametypename)
                if os.path.exists(type_folder_path) and _count_type_folders(submesh_folder_path) <= 1:
                    _show_last_type_warning(submesh_folder_name=submesh_folder_name)
                    self.report({'WARNING'}, tr("Submesh '{name}' has only its last data type left; operation aborted").format(name=submesh_folder_name))
                    return {'CANCELLED'}

        # 4. Delete: remove the TYPE folders
        for lod_name, submesh_folder_name, submesh_folder_path in all_submesh_entries:
            for _, o_lod, o_submesh, o_draw_ib, gametypename in all_obj_info:
                if o_lod != lod_name or o_submesh != submesh_folder_name:
                    continue
                type_folder_path = os.path.join(submesh_folder_path, "TYPE_" + gametypename)
                if os.path.exists(type_folder_path):
                    shutil.rmtree(type_folder_path)
                    self.report({'INFO'}, tr("Deleted data-type folder: {path}").format(path=type_folder_path))

        # 5. Collect the names of the objects to delete (every object of this DrawIB in the current workspace collection)
        submesh_to_reimport = [(ln, fp) for ln, _, fp in all_submesh_entries]
        all_obj_to_delete: list[str] = []
        workspace_collection_name = GlobalConfig.get_workspace_name()
        if workspace_collection_name in bpy.data.collections:
            ws_coll = bpy.data.collections[workspace_collection_name]
            for obj in ws_coll.all_objects:
                if obj.type != 'MESH':
                    continue
                parsed = ws_model.parse_any_format_name(obj.name)
                if not parsed or not parsed["draw_ib"]:
                    continue
                for _, draw_ib_set in lod_drawib_set.items():
                    if parsed["draw_ib"] in draw_ib_set:
                        all_obj_to_delete.append(obj.name)
                        break

        # Deduplicate
        all_obj_to_delete = list(dict.fromkeys(all_obj_to_delete))
        submesh_to_reimport = list(dict.fromkeys(submesh_to_reimport))

        # 6. Delete the objects
        if all_obj_to_delete:
            _delete_objects(all_obj_to_delete)
            self.report({'INFO'}, tr("Deleted {count} objects").format(count=len(all_obj_to_delete)))

        # 5. Re-import (DrawIB mode: unify the type automatically; all submeshes use the same data type)
        if submesh_to_reimport:
            ImprotFromWorkSpaceSelected(self, context, submesh_to_reimport, force_gametype_name="__AUTO__")
            self.report({'INFO'}, tr("Re-imported {count} submeshes (unified DrawIB type)").format(count=len(submesh_to_reimport)))
        else:
            self.report({'WARNING'}, tr("No submeshes need to be re-imported."))

        return {'FINISHED'}


# =============================================================================
# Operator - the Submesh data type is incorrect
# =============================================================================
class SSMT4FixSubmeshDataType(I18nOperator):
    bl_idname = "mimi.fix_submesh_datatype"
    bl_label = "Fix Submesh Data Type"
    bl_description = "The Submesh data type is incorrect: delete the matching data-type folder, delete this mesh, and re-import"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        selected_objects = context.selected_objects
        if not selected_objects:
            self.report({'ERROR'}, tr("Please select one or more objects first"))
            return {'CANCELLED'}

        from ..workspace.ssmt_workspace import SSMTWorkSpace

        workspace_folder = GlobalConfig.path_workspace_folder()
        if not workspace_folder or not os.path.exists(workspace_folder):
            self.report({'ERROR'}, tr("Workspace folder does not exist. Please set the workspace first."))
            return {'CANCELLED'}

        ws_model = WorkSpaceModel()

        # 1. Parse each selected object and pre-check it
        submesh_entries: list[tuple[str, str, str, str]] = []  # [(obj_name, lod_name, submesh_folder_path, gametypename)]

        for obj in selected_objects:
            gametypename = obj.get("3DMigoto:GameTypeName", "")
            if not gametypename:
                self.report({'WARNING'}, tr("Object '{name}' has no data-type attribute; skipped").format(name=obj.name))
                continue

            parsed = ws_model.parse_any_format_name(obj.name)
            if not parsed or not parsed["lod"] or not parsed["draw_ib"]:
                self.report({'WARNING'}, tr("Could not parse the name of object '{name}'; skipped").format(name=obj.name))
                continue

            submesh_folder_path = ws_model.get_folder_path(parsed["lod"], parsed["draw_ib"], parsed["component"])
            if not submesh_folder_path or not os.path.isdir(submesh_folder_path):
                self.report({'WARNING'}, tr("Could not find the submesh folder for object '{name}'; skipped").format(name=obj.name))
                continue

            submesh_entries.append((obj.name, parsed["lod"], submesh_folder_path, gametypename))

        if not submesh_entries:
            self.report({'ERROR'}, tr("Could not resolve any valid information from the selected objects."))
            return {'CANCELLED'}

        # 2. Pre-check: see whether any submesh is down to its last data type
        for obj_name, lod_name, submesh_folder_path, gametypename in submesh_entries:
            type_folder_path = os.path.join(submesh_folder_path, "TYPE_" + gametypename)
            if os.path.exists(type_folder_path) and _count_type_folders(submesh_folder_path) <= 1:
                submesh_folder_name = os.path.basename(submesh_folder_path)
                _show_last_type_warning(submesh_folder_name=submesh_folder_name)
                self.report({'WARNING'}, tr("Submesh '{name}' has only its last data type left; operation aborted").format(name=submesh_folder_name))
                return {'CANCELLED'}

        # 3. Delete: remove the TYPE folders
        submesh_to_reimport: list[tuple[str, str]] = []
        obj_names_to_delete: list[str] = []

        for obj_name, lod_name, submesh_folder_path, gametypename in submesh_entries:
            type_folder_path = os.path.join(submesh_folder_path, "TYPE_" + gametypename)
            if os.path.exists(type_folder_path):
                shutil.rmtree(type_folder_path)
                self.report({'INFO'}, tr("Deleted data-type folder: {path}").format(path=type_folder_path))

            submesh_to_reimport.append((lod_name, submesh_folder_path))
            obj_names_to_delete.append(obj_name)

        if not submesh_to_reimport:
            self.report({'ERROR'}, tr("No submeshes were found to process."))
            return {'CANCELLED'}

        # 4. Delete the objects
        if obj_names_to_delete:
            _delete_objects(obj_names_to_delete)
            self.report({'INFO'}, tr("Deleted {count} objects").format(count=len(obj_names_to_delete)))

        # 4. Re-import
        ImprotFromWorkSpaceSelected(self, context, submesh_to_reimport)
        self.report({'INFO'}, tr("Re-imported {count} submeshes").format(count=len(submesh_to_reimport)))

        return {'FINISHED'}


def register():
    bpy.utils.register_class(SSMT4ImportRaw)
    bpy.utils.register_class(SSMT4ImportAllFromCurrentWorkSpaceBlueprint)
    bpy.utils.register_class(SSMT4FixDrawIBDataType)
    bpy.utils.register_class(SSMT4FixSubmeshDataType)


def unregister():
    bpy.utils.unregister_class(SSMT4ImportRaw)
    bpy.utils.unregister_class(SSMT4ImportAllFromCurrentWorkSpaceBlueprint)
    bpy.utils.unregister_class(SSMT4FixDrawIBDataType)
    bpy.utils.unregister_class(SSMT4FixSubmeshDataType)
