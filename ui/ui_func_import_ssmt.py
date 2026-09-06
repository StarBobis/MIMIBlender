
'''
Import model configuration panel
'''
import os
import shutil
import bpy
import re

# Workaround for AttributeError: 'IMPORT_MESH_OT_migoto_raw_buffers_mmt' object has no attribute 'filepath'
from bpy_extras.io_utils import ImportHelper

from ..utils.json_utils import JsonUtils
from ..utils.collection_utils import CollectionUtils, CollectionColor
from ..utils.timer_utils import TimerUtils

from ..common.global_config import GlobalConfig
from ..common.m_texture_helper import M_TextureHelper
from ..common.texture_naming import normalize_texture_filename, normalize_texture_resource_name
from ..common.ssmt_import_helper import SSMTImportHelper
from ..common.gimi_high_fidelity_material import GIMIHighFidelityMaterial
from ..workspace.ssmt_workspace import SSMTWorkSpace, WorkSpaceModel
from ..blueprint.blueprint_export_helper import BlueprintExportHelper
from ..blueprint.blueprint_node_texture import SSMTNode_Texture
import json
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


def _parse_mark_slot_index(mark_slot: str) -> int:
    """Parse the slot index from a mark-slot string such as 'ps-t3'; return 0 on failure."""
    match = re.search(r"t(\d+)\s*$", str(mark_slot or "").strip().lower())
    return int(match.group(1)) if match else 0


def _parse_format_from_deduped_filename(deduped_filename: str) -> str:
    """Extract 'BC7_UNORM' from a deduplicated filename like '3a482e27_3a482e27-BC7_UNORM.dds'."""
    base_name = os.path.splitext(str(deduped_filename or ""))[0]
    if "-" not in base_name:
        return ""
    format_str = base_name.rsplit("-", 1)[-1].strip()
    # Some workspaces write formats as DXGI_FORMAT_BC7_UNORM_SRGB; strip the prefix
    if format_str.upper().startswith("DXGI_FORMAT_"):
        format_str = format_str[len("DXGI_FORMAT_"):]
    return format_str


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


def _get_known_texture_formats() -> set:
    """Read the known DXGI format identifiers from the Texture node format enum."""
    try:
        enum_items = SSMTNode_Texture.bl_rna.properties['texture_format'].enum_items
        return {item.identifier for item in enum_items} - {'AUTO', 'CUSTOM'}
    except Exception:
        return set()


def _apply_texture_format(tex_node, format_str: str):
    """Fill the node target format only when it is a valid enum item; unknown formats use CUSTOM."""
    format_str = (format_str or "").strip()
    if not format_str:
        return
    if format_str in _get_known_texture_formats():
        tex_node.texture_format = format_str
    else:
        tex_node.texture_format = 'CUSTOM'
        tex_node.texture_format_custom = format_str


def _node_world_location(node):
    """Return the absolute node coordinates in the editor.

    Once a node is parented to a Frame its location becomes relative to the
    parent, so the parent Frame chain must be summed to restore the
    absolute coordinates.
    """
    x, y = node.location.x, node.location.y
    parent = node.parent
    while parent is not None:
        x += parent.location.x
        y += parent.location.y
        parent = parent.parent
    return x, y


def _build_texture_nodes(
    tree,
    oldfoldername_node_dict: dict,
    oldfoldername_jsonpath_dict: dict,
    oldfoldername_group_dict: dict,
    group_tex_cursors: dict,
    tex_y_gap: float,
    group_frame_dict: dict = None,
    tex_home_group: dict = None,
):
    """Build Texture nodes from the TextureMarkUpInfoList of each Submesh JSON.

    Only textures explicitly marked by the user in SSMT generate nodes;
    the style (Hash / Slot) is decided entirely by each mark's own MarkType;
    textures sharing one hash reuse the same node.
    A texture node belongs to the group Frame of the submesh that "first
    uses it" (its first Slot mark); a pure Hash texture without any Slot
    mark belongs to the group Frame where it first appears.

    Hash-style textures are wired to a standalone Hash texture group node
    (placed beside the object groups).

    Returns (texture node list, hash texture group node);
    the hash group node is lazily created as needed and is None when there
    is no hash texture.
    """
    if group_frame_dict is None:
        group_frame_dict = {}
    if tex_home_group is None:
        tex_home_group = {}
    hash_group_node = None
    texture_node_by_hash: dict[str, bpy.types.Node] = {}
    hash_linked_node_names: set[str] = set()
    slot_link_done: set[tuple] = set()

    for old_folder_name, json_path in oldfoldername_jsonpath_dict.items():
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                submesh_json = json.load(f)
        except Exception as e:
            print(f"[ImportTexture] Failed to read Submesh JSON: {json_path}, {e}")
            continue

        mark_list = _extract_texture_marks(submesh_json)
        if not mark_list:
            continue

        for mark in mark_list:
            if not isinstance(mark, dict):
                continue
            mark_hash = str(mark.get("MarkHash", "") or "").strip()
            if not mark_hash:
                continue
            mark_name = str(mark.get("MarkName", "") or "").strip()
            mark_type = str(mark.get("MarkType", "") or "").strip()
            mark_slot = str(mark.get("MarkSlot", "") or "").strip()
            mark_filename = str(mark.get("MarkFileName", "") or "").strip()
            resource_name = str(mark.get("ResourceName", mark.get("resource_name", "")) or "").strip()
            mark_deduped_filename = str(mark.get("MarkDedupedFileName", "") or "").strip()

            tex_node = texture_node_by_hash.get(mark_hash)
            if tex_node is None:
                tex_node = tree.nodes.new('SSMTNode_Texture')
                # Ownership: prefer the group of the submesh that "first uses
                # it" (its first Slot mark), otherwise the group where it first appears.
                group_key = tex_home_group.get(mark_hash) or oldfoldername_group_dict.get(old_folder_name, ("", ""))
                cursor = group_tex_cursors.setdefault(group_key, [0.0, 0.0])
                tex_node.location = (cursor[0], cursor[1])
                cursor[1] -= tex_y_gap
                # Parent it into the owning group's Frame
                frame = group_frame_dict.get(group_key)
                if frame is not None:
                    abs_x, abs_y = tex_node.location.x, tex_node.location.y
                    # The Frame may have been merged into a DrawIB second-level Frame,
                    # making frame.location relative to it; convert back to absolute coordinates.
                    frame_abs_x, frame_abs_y = _node_world_location(frame)
                    tex_node.parent = frame
                    tex_node.location = (abs_x - frame_abs_x, abs_y - frame_abs_y)
                tex_node.texture_hash = mark_hash
                tex_node.mark_name = mark_name
                if resource_name:
                    tex_node.resource_name = normalize_texture_resource_name(resource_name)
                if mark_filename:
                    # Generated texture assets are always DDS, even when older
                    # metadata omitted the extension.
                    tex_node.texture_filename = normalize_texture_filename(mark_filename)
                    candidate_path = os.path.join(os.path.dirname(json_path), tex_node.texture_filename)
                    if not os.path.isfile(candidate_path):
                        # Preserve compatibility with metadata that points to a
                        # real non-DDS source while exporting it as DDS.
                        candidate_path = os.path.join(os.path.dirname(json_path), mark_filename)
                    if os.path.isfile(candidate_path):
                        tex_node.texture_filepath = candidate_path

                # Prefer the format from the SSMT metadata; otherwise fall back to parsing the source DDS header
                format_str = _parse_format_from_deduped_filename(mark_deduped_filename)
                if not format_str and tex_node.texture_filepath:
                    format_str = M_TextureHelper.detect_dds_format(tex_node.texture_filepath)
                _apply_texture_format(tex_node, format_str)

                texture_node_by_hash[mark_hash] = tex_node

            if mark_type == 'Hash':
                # Hash style: connect the Hash output to the standalone Hash texture group node, producing a dedicated [TextureOverride_<hash>] section
                if tex_node.name in hash_linked_node_names:
                    continue
                if hash_group_node is None:
                    hash_group_node = tree.nodes.new('SSMTNode_Object_Group')
                    hash_group_node.label = "Hash Texture Group"
                if hash_group_node.inputs[-1].is_linked:
                    hash_group_node.inputs.new('SSMTSocketObject', "Input {count}".format(count=len(hash_group_node.inputs) + 1))
                tree.links.new(tex_node.outputs["Hash"], hash_group_node.inputs[-1])
                hash_linked_node_names.add(tex_node.name)
            else:
                # Slot / SharedSlot style: connect the Slot output to the corresponding Object Info node socket
                obj_info_node = oldfoldername_node_dict.get(old_folder_name)
                if obj_info_node is None:
                    continue
                link_key = (old_folder_name, mark_hash, mark_slot)
                if link_key in slot_link_done:
                    continue
                slot_link_done.add(link_key)
                obj_info_node.link_texture_node(tex_node, _parse_mark_slot_index(mark_slot))

    return list(texture_node_by_hash.values()), hash_group_node


def _link_group_to_output(tree, group_node, output_node):
    """Link the group node to the next free input of Result_Output; add one when none is free."""
    if group_node is None or len(group_node.outputs) == 0:
        return
    if len(output_node.inputs) == 0 or output_node.inputs[-1].is_linked:
        output_node.inputs.new('SSMTSocketObject', "Group {count}".format(count=len(output_node.inputs) + 1))
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

    export_node = tree.nodes.new('SSMTNode_Face_Mod_Export')
    export_node.location = location
    export_node.label = "Export Face Mod"
    export_node.diffuse_hash = diffuse_hash
    export_node.output_folder = os.path.join(GlobalConfig.path_generate_mod_folder(), "Face")
    for object_node in face_nodes:
        if export_node.inputs[-1].is_linked:
            export_node.inputs.new('SSMTSocketObject', f"Face Group {len(export_node.inputs) + 1}")
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

def _create_and_layout_obj_info_nodes(tree, group_node, foldername_imported_obj_dict, ws_model, oldfoldername_jsonpath_hint=None):
    """Create Object Info nodes, connect them to the Group and lay them out per Submesh group.

    Each Submesh (imported mesh) owns one group: one column pair, with the
    texture column on the left (reserving preview space) and one Mesh Info
    node on the right; column pairs run horizontally and wrap after at most
    MAX_GROUP_COLS_PER_ROW groups per row.

    Mesh Info nodes grow taller as texture slots are linked, so wrapping
    advances by the estimated actual height to avoid overlapping the nodes
    of the next row.

    Each group also gets a NodeFrame that frames that Submesh's Mesh Info
    node together with its texture nodes for easier inspection; texture
    nodes are parented into the Frame by _build_texture_nodes.
    Submesh Frames sharing one IB hash are merged into a DrawIB-level
    second Frame.

    Returns (oldfoldername_node_dict, oldfoldername_group_dict, group_tex_cursors,
          max_node_right, tex_y_gap, group_frame_dict, tex_home_group).
    """
    if oldfoldername_jsonpath_hint is None:
        oldfoldername_jsonpath_hint = {}
    # old_folder_name -> Object Info node (Slot link target of texture marks)
    oldfoldername_node_dict: dict[str, bpy.types.Node] = {}
    # old_folder_name -> group key (new-format submesh name)
    oldfoldername_group_dict: dict[str, str] = {}
    group_order: list[str] = []
    group_nodes: dict[str, list] = {}
    # group key -> NodeFrame label (mesh name + DrawIB alias)
    group_frame_labels: dict[str, str] = {}
    # DrawIB second-level grouping: (lod, draw_ib) -> submesh group keys under that IB hash
    outer_order: list[tuple] = []
    outer_groups: dict[tuple, list] = {}

    for new_submesh_name, (imported_obj, display_name) in foldername_imported_obj_dict.items():
        if imported_obj.type != 'MESH':
            continue

        # Resolve the new-format name via WorkSpaceModel to get the component number
        parsed = ws_model.parse_new_format_name(new_submesh_name)
        component_str = str(parsed["component"]) if parsed else "0"

        # Create the node
        node = tree.nodes.new('SSMTNode_Object_Info')

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

        # Group granularity is the Submesh: one group / Frame per mesh
        group_key = new_submesh_name
        if group_key not in group_nodes:
            group_nodes[group_key] = []
            group_order.append(group_key)
        group_nodes[group_key].append(node)
        if old_folder_name:
            oldfoldername_group_dict[old_folder_name] = group_key

        group_frame_labels[group_key] = imported_obj.name or new_submesh_name

        outer_key = (parsed.get("lod", ""), parsed.get("draw_ib", "")) if parsed else ("", "")
        if outer_key not in outer_groups:
            outer_groups[outer_key] = []
            outer_order.append(outer_key)
        outer_groups[outer_key].append(group_key)

        # Add a socket manually when the Group's last socket is already occupied
        if group_node.inputs[-1].is_linked:
            group_node.inputs.new('SSMTSocketObject', f"Input {len(group_node.inputs) + 1}")
        tree.links.new(node.outputs[0], group_node.inputs[-1])

    # Group layout
    OBJ_X_OFFSET = 560.0
    TEX_Y_GAP = 460.0
    GROUP_X_GAP = 1120.0
    ROW_Y_GAP = 320.0
    MAX_GROUP_COLS_PER_ROW = 3
    # Mesh Info node height estimate: base height plus growth per linked texture slot.
    # The node UI is made of socket rows (about 22px per row) and draw_buttons
    # rows (about 20px per row); each linked slot adds about 1 socket row plus
    # 3 slot-configuration button rows.
    OBJ_BASE_HEIGHT = 220.0
    OBJ_SLOT_LINK_HEIGHT = 100.0

    # Pre-count the texture nodes per group to estimate the row height (texture columns need preview space)
    group_tex_counts: dict[str, int] = {}
    # Pre-count the linked texture slots per Mesh Info node group (marks whose
    # MarkType is not Hash, deduplicated like the slot_link_done logic of _build_texture_nodes)
    group_slot_link_counts: dict[str, int] = {}
    seen_mark_hashes: set[str] = set()
    seen_slot_links: set[tuple] = set()
    # For each texture hash: the group where it first appears and the group of
    # its first Slot mark (the submesh that "first uses it"), used to decide
    # which group's Frame owns the texture node
    tex_first_group: dict[str, str] = {}
    tex_first_slot_group: dict[str, str] = {}
    for old_folder_name, json_path in oldfoldername_jsonpath_hint.items():
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                submesh_json = json.load(f)
        except Exception:
            continue
        mark_list = _extract_texture_marks(submesh_json)
        group_key = oldfoldername_group_dict.get(old_folder_name, ("", ""))
        for mark in mark_list:
            if not isinstance(mark, dict):
                continue
            mark_hash = str(mark.get("MarkHash", "") or "").strip()
            if not mark_hash:
                continue
            if mark_hash not in tex_first_group:
                tex_first_group[mark_hash] = group_key
            if mark_hash not in seen_mark_hashes:
                seen_mark_hashes.add(mark_hash)
                group_tex_counts[group_key] = group_tex_counts.get(group_key, 0) + 1
            mark_type = str(mark.get("MarkType", "") or "").strip()
            if mark_type != 'Hash':
                mark_slot = str(mark.get("MarkSlot", "") or "").strip()
                link_key = (old_folder_name, mark_hash, mark_slot)
                if link_key not in seen_slot_links:
                    seen_slot_links.add(link_key)
                    group_slot_link_counts[group_key] = group_slot_link_counts.get(group_key, 0) + 1
                if mark_hash not in tex_first_slot_group:
                    tex_first_slot_group[mark_hash] = group_key

    # Texture ownership strictly follows the submesh of the "first use"
    # (the first Slot mark); pure Hash textures without Slot marks follow
    # the group where they first appear
    tex_home_group = {
        h: tex_first_slot_group.get(h) or first_group
        for h, first_group in tex_first_group.items()
    }

    group_tex_cursors: dict[str, list] = {}
    group_top_y: dict[str, float] = {}
    max_node_right = 0.0
    row_start_y = 0.0
    row_max_height = 0.0
    col_in_row = 0

    for outer_key in outer_order:
        submesh_keys = outer_groups[outer_key]
        # Submeshes of one DrawIB line up consecutively in a row so that the
        # second-level Frame does not cover other groups: wrap first when the
        # remaining columns of the current row cannot fit the whole group
        if 0 < col_in_row and len(submesh_keys) > MAX_GROUP_COLS_PER_ROW - col_in_row:
            col_in_row = 0
            row_start_y -= (row_max_height + ROW_Y_GAP)
            row_max_height = 0.0
        spanned_multiple_rows = False
        for group_key in submesh_keys:
            if col_in_row >= MAX_GROUP_COLS_PER_ROW:
                col_in_row = 0
                row_start_y -= (row_max_height + ROW_Y_GAP)
                row_max_height = 0.0
                spanned_multiple_rows = True
            base_x = col_in_row * GROUP_X_GAP
            col_in_row += 1

            y = row_start_y
            for node in group_nodes[group_key]:
                node.location = (base_x + OBJ_X_OFFSET, y)
                slot_link_count = group_slot_link_counts.get(group_key, 0)
                y -= OBJ_BASE_HEIGHT + slot_link_count * OBJ_SLOT_LINK_HEIGHT

            # Mesh Info nodes grow with linked texture slots; count the estimated height into the row height to avoid overlapping the next row
            obj_height = row_start_y - y
            tex_height = group_tex_counts.get(group_key, 0) * TEX_Y_GAP
            row_max_height = max(row_max_height, obj_height, tex_height)
            max_node_right = max(max_node_right, base_x + OBJ_X_OFFSET)

            group_tex_cursors[group_key] = [base_x, row_start_y]
            group_top_y[group_key] = row_start_y
        # A group spanning several rows has a second-level Frame whose rectangle
        # covers those rows, so no other group may use the leftover columns
        if spanned_multiple_rows:
            col_in_row = MAX_GROUP_COLS_PER_ROW

    # Create a Frame per group and parent the group's Mesh Info nodes into it
    FRAME_PAD = 40.0
    group_frame_dict: dict[str, bpy.types.Node] = {}
    for group_key in group_order:
        frame = tree.nodes.new('NodeFrame')
        frame_label = group_frame_labels.get(group_key, "") or str(group_key) or "Ungrouped"
        frame.label = frame_label
        frame.name = "Frame_" + (frame_label.replace(" ", "_") or "Ungrouped")
        frame.location = (group_tex_cursors[group_key][0] - FRAME_PAD,
                          group_top_y[group_key] + FRAME_PAD)
        group_frame_dict[group_key] = frame

        for node in group_nodes[group_key]:
            abs_x, abs_y = node.location.x, node.location.y
            node.parent = frame
            node.location = (abs_x - frame.location.x, abs_y - frame.location.y)

    # Create a second-level Frame per DrawIB and merge the Submesh Frames of
    # the same IB hash into it. The layout stage already keeps the submeshes
    # of one group consecutive, with multi-row groups owning all of their rows,
    # so the second-level Frame rectangle never covers other groups.
    # Blender fits the Frame size to its children; only a rough top-left
    # position is given here.
    OUTER_FRAME_PAD = 40.0
    for outer_key in outer_order:
        lod_name, draw_ib = outer_key
        label_parts = [part for part in (lod_name, draw_ib) if part]
        outer_label = ".".join(label_parts) if label_parts else "Ungrouped"
        alias = getattr(ws_model, "drawib_aliases", {}).get(draw_ib, "")
        if alias:
            outer_label += f" ({alias})"
        outer_frame = tree.nodes.new('NodeFrame')
        outer_frame.label = outer_label
        outer_frame.name = "Frame_" + (outer_label.replace(" ", "_") or "Ungrouped")
        first_key = outer_groups[outer_key][0]
        outer_frame.location = (group_tex_cursors[first_key][0] - FRAME_PAD - OUTER_FRAME_PAD,
                                group_top_y[first_key] + FRAME_PAD + OUTER_FRAME_PAD)
        for group_key in outer_groups[outer_key]:
            inner_frame = group_frame_dict[group_key]
            abs_x, abs_y = inner_frame.location.x, inner_frame.location.y
            inner_frame.parent = outer_frame
            inner_frame.location = (abs_x - outer_frame.location.x, abs_y - outer_frame.location.y)

    return (oldfoldername_node_dict, oldfoldername_group_dict, group_tex_cursors,
            max_node_right, TEX_Y_GAP, group_frame_dict, tex_home_group)


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
        self.report({'ERROR'}, "No LOD directories (LOD0, LOD1, ...) were found in the current workspace. Please check the workspace structure.")
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
                        self.report({'INFO'}, "Successfully imported " + new_submesh_name + " data type: " + gametype_name)
                    except Exception as e:
                        print(f"Failed to import from {import_folder_path}: {e}")
                        continue
                    # Break after the first successful import
                    break

    if successful_import_count == 0:
        self.report({'ERROR'}, "No models were successfully imported from the current workspace; blueprint generation was skipped.")
        return

    # Save the workspace-level Import.json selection record (using new-format keys)
    save_import_json_path = os.path.join(GlobalConfig.path_workspace_folder(), "Import.json")
    JsonUtils.SaveToFile(json_dict=foldername_gametypename_dict, filepath=save_import_json_path)
    
    if getattr(context.scene.global_properties, "align_face_on_import", False):
        if not _apply_face_neck_object_alignment(foldername_imported_obj_dict):
            self.report({'WARNING'}, "Face alignment requires at least one valid Face mark and one Neck mark.")

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
            tree = bpy.data.node_groups.new(name=tree_name, type='SSMTBlueprintTreeType')
        except Exception as e:
            print(f"Failed to create new node tree: {e}. Check if SSMTBlueprintTreeType is registered.")
            return
        tree.use_fake_user = True
        BlueprintExportHelper.set_tree_submesh_names(all_submesh_display_names, tree=tree)
        
        # Create the Group node (and link to it in the loop)
        group_node = tree.nodes.new('SSMTNode_Object_Group')
        group_node.label = "Default Group"
        
        # 3. Create Object Info nodes laid out per Submesh group (same IB hash merged into a second-level Frame)
        (oldfoldername_node_dict, oldfoldername_group_dict,
         group_tex_cursors, max_node_right, TEX_Y_GAP,
         group_frame_dict, tex_home_group) = _create_and_layout_obj_info_nodes(
            tree, group_node, foldername_imported_obj_dict, ws_model,
            oldfoldername_jsonpath_hint=oldfoldername_jsonpath_dict)

        # 3.5 Auto-create and connect Texture nodes from each Submesh's texture-mark metadata
        # Only textures explicitly marked by the user in SSMT are imported; the style is decided by each mark's MarkType
        _, hash_group_node = _build_texture_nodes(
            tree=tree,
            oldfoldername_node_dict=oldfoldername_node_dict,
            oldfoldername_jsonpath_dict=oldfoldername_jsonpath_dict,
            oldfoldername_group_dict=oldfoldername_group_dict,
            group_tex_cursors=group_tex_cursors,
            tex_y_gap=TEX_Y_GAP,
            group_frame_dict=group_frame_dict,
            tex_home_group=tex_home_group,
        )

        # 4. Place the Group and Output nodes (the Hash texture group sits beside the object group)
        group_node.location = (max_node_right + 560.0, -200.0)
        group_node.label = "Master Mesh Group"
        if hash_group_node is not None:
            hash_group_node.location = (max_node_right + 560.0, -1000.0)
            hash_group_node.label = "Master Hash Texture Group"

        output_node = tree.nodes.new('SSMTNode_Result_Output')
        output_node.location = (max_node_right + 1040.0, -200.0)
        output_node.label = "Generate Mod"

        face_export_node = _create_face_mod_export_node(
            tree, oldfoldername_node_dict, oldfoldername_jsonpath_dict,
            (max_node_right + 1040.0, -760.0),
        )
        
        # Link the side-by-side group nodes directly to the Output
        _link_group_to_output(tree, face_export_node, output_node)
        _link_group_to_output(tree, group_node, output_node)
        _link_group_to_output(tree, hash_group_node, output_node)

        if hasattr(group_node, "update"):
            group_node.update()
        if hash_group_node is not None and hasattr(hash_group_node, "update"):
            hash_group_node.update()
        _exclude_marked_face_objects_from_regular_group(
            tree, group_node, oldfoldername_node_dict, oldfoldername_jsonpath_dict,
        )

        BlueprintExportHelper.set_runtime_blueprint_tree(tree)

        global_properties = getattr(getattr(context, "scene", None), "global_properties", None)
        if global_properties:
            global_properties.selected_blueprint_name = tree.name

        BlueprintExportHelper.reveal_tree_in_node_editors(context, tree)
        _clear_blueprint_node_selection(tree)

        print(f"Blueprint {tree_name} updated with imported objects.")
        
    except Exception as e:
        print(f"Error generating blueprint nodes: {e}")
        import traceback
        traceback.print_exc()
    


class SSMT4ImportAllFromCurrentWorkSpaceBlueprint(bpy.types.Operator):
    bl_idname = "ssmt4.import_all_from_workspace"
    bl_label = "Import All From SSMT Workspace"
    bl_description = "Import everything from the current workspace folder with one click."
    bl_options = {'REGISTER','UNDO'}

    def execute(self, context):
        # print("Current WorkSpace: " + GlobalConfig.get_workspace_name())
        # print("Current Game: " + GlobalConfig.gamename)
        if GlobalConfig.get_workspace_name() == "":
            self.report({"ERROR"}, "Please select the current workspace in SSMT before importing.")
        elif not os.path.exists(GlobalConfig.path_workspace_folder()):
            self.report({"ERROR"}, "Workspace folder does not exist. Please create a workspace in SSMT first: {path}".format(path=GlobalConfig.path_workspace_folder()))
        else:
            TimerUtils.Start("ImportFromWorkSpaceBlueprint")
            ImprotFromWorkSpaceFull(self, context)
            TimerUtils.End("ImportFromWorkSpaceBlueprint")
        
        return {'FINISHED'}
    

class SSMT4ImportRaw(bpy.types.Operator, ImportHelper):
    bl_idname = "ssmt4.import_raw"
    bl_label = "Import SSMT Model"
    bl_description = "Import an SSMT model file. You only need to select the .json file."
    bl_options = {'REGISTER','UNDO'}

    filter_glob: bpy.props.StringProperty(
        default='*.json',
        options={'HIDDEN'},
    ) # type: ignore

    files: bpy.props.CollectionProperty(
        name="File Path",
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
    e.g. [("LOD0", r"D:\SSMTCacheFolder\WorkSpace\GF2\Default\LOD0\3ed2b2ba-2592-76086"), ...]
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
                    self.report({'INFO'}, "Successfully imported " + new_submesh_name + " data type: " + gametype_name)

                    # In __AUTO__ mode, lock the type once the first import succeeds
                    if locked_gametype is None and force_gametype_name == "__AUTO__":
                        locked_gametype = gametype_name
                        self.report({'INFO'}, f"DrawIB unified type locked to: {locked_gametype}; all later submeshes will use this type")
                except Exception as e:
                    print(f"Failed to re-import from {import_folder_path}: {e}")
                    continue
                break

    if successful_import_count == 0:
        self.report({'ERROR'}, "None of the selected submeshes were imported successfully.")
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

    if getattr(context.scene.global_properties, "align_face_on_import", False):
        if not _apply_face_neck_object_alignment(foldername_imported_obj_dict):
            self.report({'WARNING'}, "Face alignment requires at least one valid Face mark and one Neck mark.")

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

        group_node = tree.nodes.new('SSMTNode_Object_Group')
        group_node.label = "Default Group"

        ws_model = WorkSpaceModel()

        (oldfoldername_node_dict, oldfoldername_group_dict,
         group_tex_cursors, max_node_right, TEX_Y_GAP,
         group_frame_dict, tex_home_group) = _create_and_layout_obj_info_nodes(
            tree, group_node, foldername_imported_obj_dict, ws_model,
            oldfoldername_jsonpath_hint=oldfoldername_jsonpath_dict)

        hash_group_node = None
        if oldfoldername_jsonpath_dict:
            _, hash_group_node = _build_texture_nodes(
                tree=tree,
                oldfoldername_node_dict=oldfoldername_node_dict,
                oldfoldername_jsonpath_dict=oldfoldername_jsonpath_dict,
                oldfoldername_group_dict=oldfoldername_group_dict,
                group_tex_cursors=group_tex_cursors,
                tex_y_gap=TEX_Y_GAP,
                group_frame_dict=group_frame_dict,
                tex_home_group=tex_home_group,
            )

        # The Hash texture group sits beside the object group
        group_node.location = (max_node_right + 560.0, -200.0)
        if hash_group_node is not None:
            hash_group_node.location = (max_node_right + 560.0, 60.0)

        output_node = tree.nodes.new('SSMTNode_Result_Output')
        output_node.location = (max_node_right + 1040.0, -200.0)
        output_node.label = "Generate Mod"

        face_export_node = _create_face_mod_export_node(
            tree, oldfoldername_node_dict, oldfoldername_jsonpath_dict or {},
            (max_node_right + 1040.0, -760.0),
        )

        _link_group_to_output(tree, face_export_node, output_node)
        _link_group_to_output(tree, group_node, output_node)
        _link_group_to_output(tree, hash_group_node, output_node)

        if hasattr(group_node, "update"):
            group_node.update()
        if hash_group_node is not None and hasattr(hash_group_node, "update"):
            hash_group_node.update()
        _exclude_marked_face_objects_from_regular_group(
            tree, group_node, oldfoldername_node_dict, oldfoldername_jsonpath_dict or {},
        )

        BlueprintExportHelper.set_runtime_blueprint_tree(tree)

        global_properties = getattr(getattr(context, "scene", None), "global_properties", None)
        if global_properties:
            global_properties.selected_blueprint_name = tree.name

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
            text=f"Submesh '{submesh_folder_name}' is down to its last data-type folder; "
        )
        self.layout.label(
            text="that type cannot be deleted. If no correct data type exists, contact the SSMT developer to add one."
        )
    bpy.context.window_manager.popup_menu(draw_popup, title="Warning", icon='ERROR')


# =============================================================================
# Operator - the DrawIB data type is incorrect
# =============================================================================
class SSMT4FixDrawIBDataType(bpy.types.Operator):
    bl_idname = "ssmt4.fix_drawib_datatype"
    bl_label = "Fix DrawIB Data Type"
    bl_description = "The DrawIB data type is incorrect: delete all matching data-type folders under this DrawIB, delete the related meshes, and re-import"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        selected_objects = context.selected_objects
        if not selected_objects:
            self.report({'ERROR'}, "Please select one or more objects first")
            return {'CANCELLED'}

        from ..workspace.ssmt_workspace import SSMTWorkSpace

        workspace_folder = GlobalConfig.path_workspace_folder()
        if not workspace_folder or not os.path.exists(workspace_folder):
            self.report({'ERROR'}, "Workspace folder does not exist. Please set the workspace first.")
            return {'CANCELLED'}

        ws_model = WorkSpaceModel()

        # 1. Parse each selected object, collecting {lod_name: set_of_drawib}
        lod_drawib_set: dict[str, set[str]] = {}
        # Also record the names of the objects to delete
        all_obj_info = []  # [(obj_name, lod_name, submesh_folder_name, draw_ib, gametypename)]
        for obj in selected_objects:
            gametypename = obj.get("3DMigoto:GameTypeName", "")
            if not gametypename:
                self.report({'WARNING'}, f"Object '{obj.name}' has no data-type attribute; skipped")
                continue

            parsed = ws_model.parse_any_format_name(obj.name)
            if not parsed or not parsed["lod"] or not parsed["draw_ib"]:
                self.report({'WARNING'}, f"Could not parse the name of object '{obj.name}'; skipped")
                continue

            submesh_folder_path = ws_model.get_folder_path(parsed["lod"], parsed["draw_ib"], parsed["component"])
            submesh_folder_name = os.path.basename(submesh_folder_path) if submesh_folder_path else ""

            all_obj_info.append((obj.name, parsed["lod"], submesh_folder_name, parsed["draw_ib"], gametypename))
            if parsed["lod"] not in lod_drawib_set:
                lod_drawib_set[parsed["lod"]] = set()
            lod_drawib_set[parsed["lod"]].add(parsed["draw_ib"])

        if not all_obj_info:
            self.report({'ERROR'}, "Could not resolve any valid information from the selected objects.")
            return {'CANCELLED'}

        # 2. Pre-check: collect every submesh folder under this DrawIB
        all_submesh_entries: list[tuple[str, str, str]] = []  # [(lod_name, submesh_folder_name, submesh_folder_path)]
        for lod_name, draw_ib_set in lod_drawib_set.items():
            lod_folder_path = os.path.join(workspace_folder, lod_name)
            if not os.path.isdir(lod_folder_path):
                self.report({'WARNING'}, f"LOD directory does not exist: {lod_folder_path}")
                continue
            for entry in os.scandir(lod_folder_path):
                if not entry.is_dir():
                    continue
                folder_draw_ib = entry.name.split("-")[0]
                if folder_draw_ib in draw_ib_set:
                    all_submesh_entries.append((lod_name, entry.name, entry.path))

        if not all_submesh_entries:
            self.report({'ERROR'}, "No matching submesh folders were found.")
            return {'CANCELLED'}

        # 3. Pre-check: see whether any submesh is down to its last data type
        for lod_name, submesh_folder_name, submesh_folder_path in all_submesh_entries:
            for _, o_lod, o_submesh, o_draw_ib, gametypename in all_obj_info:
                if o_lod != lod_name or o_submesh != submesh_folder_name:
                    continue
                type_folder_path = os.path.join(submesh_folder_path, "TYPE_" + gametypename)
                if os.path.exists(type_folder_path) and _count_type_folders(submesh_folder_path) <= 1:
                    _show_last_type_warning(submesh_folder_name=submesh_folder_name)
                    self.report({'WARNING'}, f"Submesh '{submesh_folder_name}' has only its last data type left; operation aborted")
                    return {'CANCELLED'}

        # 4. Delete: remove the TYPE folders
        for lod_name, submesh_folder_name, submesh_folder_path in all_submesh_entries:
            for _, o_lod, o_submesh, o_draw_ib, gametypename in all_obj_info:
                if o_lod != lod_name or o_submesh != submesh_folder_name:
                    continue
                type_folder_path = os.path.join(submesh_folder_path, "TYPE_" + gametypename)
                if os.path.exists(type_folder_path):
                    shutil.rmtree(type_folder_path)
                    self.report({'INFO'}, f"Deleted data-type folder: {type_folder_path}")

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
            self.report({'INFO'}, f"Deleted {len(all_obj_to_delete)} objects")

        # 5. Re-import (DrawIB mode: unify the type automatically; all submeshes use the same data type)
        if submesh_to_reimport:
            ImprotFromWorkSpaceSelected(self, context, submesh_to_reimport, force_gametype_name="__AUTO__")
            self.report({'INFO'}, f"Re-imported {len(submesh_to_reimport)} submeshes (unified DrawIB type)")
        else:
            self.report({'WARNING'}, "No submeshes need to be re-imported.")

        return {'FINISHED'}


# =============================================================================
# Operator - the Submesh data type is incorrect
# =============================================================================
class SSMT4FixSubmeshDataType(bpy.types.Operator):
    bl_idname = "ssmt4.fix_submesh_datatype"
    bl_label = "Fix Submesh Data Type"
    bl_description = "The Submesh data type is incorrect: delete the matching data-type folder, delete this mesh, and re-import"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        selected_objects = context.selected_objects
        if not selected_objects:
            self.report({'ERROR'}, "Please select one or more objects first")
            return {'CANCELLED'}

        from ..workspace.ssmt_workspace import SSMTWorkSpace

        workspace_folder = GlobalConfig.path_workspace_folder()
        if not workspace_folder or not os.path.exists(workspace_folder):
            self.report({'ERROR'}, "Workspace folder does not exist. Please set the workspace first.")
            return {'CANCELLED'}

        ws_model = WorkSpaceModel()

        # 1. Parse each selected object and pre-check it
        submesh_entries: list[tuple[str, str, str, str]] = []  # [(obj_name, lod_name, submesh_folder_path, gametypename)]

        for obj in selected_objects:
            gametypename = obj.get("3DMigoto:GameTypeName", "")
            if not gametypename:
                self.report({'WARNING'}, f"Object '{obj.name}' has no data-type attribute; skipped")
                continue

            parsed = ws_model.parse_any_format_name(obj.name)
            if not parsed or not parsed["lod"] or not parsed["draw_ib"]:
                self.report({'WARNING'}, f"Could not parse the name of object '{obj.name}'; skipped")
                continue

            submesh_folder_path = ws_model.get_folder_path(parsed["lod"], parsed["draw_ib"], parsed["component"])
            if not submesh_folder_path or not os.path.isdir(submesh_folder_path):
                self.report({'WARNING'}, f"Could not find the submesh folder for object '{obj.name}'; skipped")
                continue

            submesh_entries.append((obj.name, parsed["lod"], submesh_folder_path, gametypename))

        if not submesh_entries:
            self.report({'ERROR'}, "Could not resolve any valid information from the selected objects.")
            return {'CANCELLED'}

        # 2. Pre-check: see whether any submesh is down to its last data type
        for obj_name, lod_name, submesh_folder_path, gametypename in submesh_entries:
            type_folder_path = os.path.join(submesh_folder_path, "TYPE_" + gametypename)
            if os.path.exists(type_folder_path) and _count_type_folders(submesh_folder_path) <= 1:
                submesh_folder_name = os.path.basename(submesh_folder_path)
                _show_last_type_warning(submesh_folder_name=submesh_folder_name)
                self.report({'WARNING'}, f"Submesh '{submesh_folder_name}' has only its last data type left; operation aborted")
                return {'CANCELLED'}

        # 3. Delete: remove the TYPE folders
        submesh_to_reimport: list[tuple[str, str]] = []
        obj_names_to_delete: list[str] = []

        for obj_name, lod_name, submesh_folder_path, gametypename in submesh_entries:
            type_folder_path = os.path.join(submesh_folder_path, "TYPE_" + gametypename)
            if os.path.exists(type_folder_path):
                shutil.rmtree(type_folder_path)
                self.report({'INFO'}, f"Deleted data-type folder: {type_folder_path}")

            submesh_to_reimport.append((lod_name, submesh_folder_path))
            obj_names_to_delete.append(obj_name)

        if not submesh_to_reimport:
            self.report({'ERROR'}, "No submeshes were found to process.")
            return {'CANCELLED'}

        # 4. Delete the objects
        if obj_names_to_delete:
            _delete_objects(obj_names_to_delete)
            self.report({'INFO'}, f"Deleted {len(obj_names_to_delete)} objects")

        # 4. Re-import
        ImprotFromWorkSpaceSelected(self, context, submesh_to_reimport)
        self.report({'INFO'}, f"Re-imported {len(submesh_to_reimport)} submeshes")

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
