
'''
导入模型配置面板
'''
import os
import shutil
import bpy
import re

# 用于解决 AttributeError: 'IMPORT_MESH_OT_migoto_raw_buffers_mmt' object has no attribute 'filepath'
from bpy_extras.io_utils import ImportHelper

from ..utils.json_utils import JsonUtils
from ..utils.collection_utils import CollectionUtils, CollectionColor
from ..utils.timer_utils import TimerUtils
from ..utils.translate_utils import iface_, rpt_

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
        print(f"[GIMI {role}] {json_path} 没有有效的 DiffuseMap 快捷元信息，跳过材质构建。")
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
                print(f"[GIMI Face] {json_path} 缺少 FaceSDFMap，保留常规材质。")


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


# 全量导入逻辑


def _parse_mark_slot_index(mark_slot: str) -> int:
    """从 'ps-t3' 这类标记槽位字符串中解析 slot 索引，失败返回 0。"""
    match = re.search(r"t(\d+)\s*$", str(mark_slot or "").strip().lower())
    return int(match.group(1)) if match else 0


def _parse_format_from_deduped_filename(deduped_filename: str) -> str:
    """从 '3a482e27_3a482e27-BC7_UNORM.dds' 中提取 'BC7_UNORM'。"""
    base_name = os.path.splitext(str(deduped_filename or ""))[0]
    if "-" not in base_name:
        return ""
    format_str = base_name.rsplit("-", 1)[-1].strip()
    # 部分工作空间写成 DXGI_FORMAT_BC7_UNORM_SRGB 形式，去掉前缀
    if format_str.upper().startswith("DXGI_FORMAT_"):
        format_str = format_str[len("DXGI_FORMAT_"):]
    return format_str


def _extract_texture_marks(submesh_json: dict) -> list:
    """从 Submesh JSON 中提取贴图标记列表。

    SSMT4 使用扁平的 TextureMarkUpInfoList；
    部分旧数据只有按组件分组的 ComponentTextureMarkUpInfoListDict，
    此时把所有组件的标记拍平返回（同 Hash 会在后续去重）。
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
    """读取 Texture 节点格式枚举中的已知 DXGI 格式标识符。"""
    try:
        enum_items = SSMTNode_Texture.bl_rna.properties['texture_format'].enum_items
        return {item.identifier for item in enum_items} - {'AUTO', 'CUSTOM'}
    except Exception:
        return set()


def _apply_texture_format(tex_node, format_str: str):
    """按枚举合法性填充节点目标格式，未知格式走 CUSTOM。"""
    format_str = (format_str or "").strip()
    if not format_str:
        return
    if format_str in _get_known_texture_formats():
        tex_node.texture_format = format_str
    else:
        tex_node.texture_format = 'CUSTOM'
        tex_node.texture_format_custom = format_str


def _node_world_location(node):
    """返回节点在编辑器中的绝对坐标。

    节点 parent 到 Frame 后 location 变为相对父级的值，
    需要沿父 Frame 链累加才能还原绝对坐标。
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
    """根据各 Submesh JSON 中的 TextureMarkUpInfoList 构建 Texture 节点。

    只有被用户在 SSMT 中明确标记过的贴图才会生成节点；
    风格（Hash / Slot）完全由每条标记自身的 MarkType 决定；
    同一 Hash 的贴图对象复用同一个节点。
    贴图节点归属于"第一次使用它"（首个 Slot 标记）的 submesh 所在的分组 Frame；
    没有 Slot 标记的纯 Hash 贴图则归属于它第一个出现的分组 Frame。

    Hash 风格的贴图会连到一个独立的 Hash 贴图分组节点（与物体分组并列）。

    返回 (贴图节点列表, Hash 贴图分组节点)；
    Hash 贴图分组节点按需懒创建，没有 Hash 贴图时为 None。
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
            print(f"[ImportTexture] 读取 Submesh JSON 失败: {json_path}, {e}")
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
                # 归属分组：优先"第一次使用它"（首个 Slot 标记）的 submesh 分组，
                # 否则取它第一个出现的分组
                group_key = tex_home_group.get(mark_hash) or oldfoldername_group_dict.get(old_folder_name, ("", ""))
                cursor = group_tex_cursors.setdefault(group_key, [0.0, 0.0])
                tex_node.location = (cursor[0], cursor[1])
                cursor[1] -= tex_y_gap
                # 挂到归属分组的 Frame 里
                frame = group_frame_dict.get(group_key)
                if frame is not None:
                    abs_x, abs_y = tex_node.location.x, tex_node.location.y
                    # Frame 可能已并入 DrawIB 二级 Frame，此时 frame.location
                    # 是相对二级 Frame 的值，必须换算回绝对坐标再计算相对位置
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

                # 优先使用 SSMT 元数据里的格式，其次回退到解析源 DDS 文件头
                format_str = _parse_format_from_deduped_filename(mark_deduped_filename)
                if not format_str and tex_node.texture_filepath:
                    format_str = M_TextureHelper.detect_dds_format(tex_node.texture_filepath)
                _apply_texture_format(tex_node, format_str)

                texture_node_by_hash[mark_hash] = tex_node

            if mark_type == 'Hash':
                # Hash 风格：连接 Hash 出口到独立的 Hash 贴图分组节点，生成独立 [TextureOverride_<hash>] 段
                if tex_node.name in hash_linked_node_names:
                    continue
                if hash_group_node is None:
                    hash_group_node = tree.nodes.new('SSMTNode_Object_Group')
                    hash_group_node.label = "Hash Texture Group"
                if hash_group_node.inputs[-1].is_linked:
                    hash_group_node.inputs.new('SSMTSocketObject', iface_("输入 {count}").format(count=len(hash_group_node.inputs) + 1))
                tree.links.new(tex_node.outputs["Hash"], hash_group_node.inputs[-1])
                hash_linked_node_names.add(tex_node.name)
            else:
                # Slot / SharedSlot 风格：连接 Slot 出口到对应 Object Info 节点的槽位
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
    """把分组节点连到 Result_Output 的下一个空闲输入口，没有空闲口时先补充。"""
    if group_node is None or len(group_node.outputs) == 0:
        return
    if len(output_node.inputs) == 0 or output_node.inputs[-1].is_linked:
        output_node.inputs.new('SSMTSocketObject', iface_("组 {count}").format(count=len(output_node.inputs) + 1))
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
    export_node.label = "导出面部 Mod"
    export_node.diffuse_hash = diffuse_hash
    export_node.output_folder = os.path.join(GlobalConfig.path_generate_mod_folder(), "Face")
    for object_node in face_nodes:
        if export_node.inputs[-1].is_linked:
            export_node.inputs.new('SSMTSocketObject', f"面部组 {len(export_node.inputs) + 1}")
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
    """创建 Object Info 节点、连接到 Group，并按 Submesh 分组布局。

    每个 Submesh（导入的 mesh）独占一个分组：占一列对，左侧贴图列
    （留出预览空间），右侧一个 Mesh Info 节点；列对横向排列，
    每行最多 MAX_GROUP_COLS_PER_ROW 组后换行。

    Mesh Info 节点会随贴图槽位连接数量被撑高，因此换行时按预估的
    实际高度推进，避免与下一行的节点叠在一起。

    每个分组同时创建一个 NodeFrame，把该 Submesh 的 Mesh Info 节点与
    贴图节点框在一起，便于观察；贴图节点由 _build_texture_nodes 负责挂进 Frame。
    归属于同一 IB hash 的 Submesh Frame 会再并入一个 DrawIB 级的二级 Frame。

    返回 (oldfoldername_node_dict, oldfoldername_group_dict, group_tex_cursors,
          max_node_right, tex_y_gap, group_frame_dict, tex_home_group)。
    """
    if oldfoldername_jsonpath_hint is None:
        oldfoldername_jsonpath_hint = {}
    # old_folder_name -> Object Info 节点（贴图标记的 Slot 连接目标）
    oldfoldername_node_dict: dict[str, bpy.types.Node] = {}
    # old_folder_name -> 分组 key（新格式 submesh 名称）
    oldfoldername_group_dict: dict[str, str] = {}
    group_order: list[str] = []
    group_nodes: dict[str, list] = {}
    # 分组 key -> NodeFrame 标签（mesh 名 + DrawIB 别名）
    group_frame_labels: dict[str, str] = {}
    # DrawIB 二级分组：(lod, draw_ib) -> 该 IB hash 下的 submesh 分组 key 列表
    outer_order: list[tuple] = []
    outer_groups: dict[tuple, list] = {}

    for new_submesh_name, (imported_obj, display_name) in foldername_imported_obj_dict.items():
        if imported_obj.type != 'MESH':
            continue

        # 通过 WorkSpaceModel 解析新格式名称获取 component 编号
        parsed = ws_model.parse_new_format_name(new_submesh_name)
        component_str = str(parsed["component"]) if parsed else "0"

        # 创建节点
        node = tree.nodes.new('SSMTNode_Object_Info')

        # 填充属性
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

        # 分组粒度为 Submesh：每个 mesh 一个分组 / 一个 Frame
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

        # 如果 Group 最后一个插槽已被占用，手动扩展一个
        if group_node.inputs[-1].is_linked:
            group_node.inputs.new('SSMTSocketObject', f"Input {len(group_node.inputs) + 1}")
        tree.links.new(node.outputs[0], group_node.inputs[-1])

    # 分组布局
    OBJ_X_OFFSET = 560.0
    TEX_Y_GAP = 460.0
    GROUP_X_GAP = 1120.0
    ROW_Y_GAP = 320.0
    MAX_GROUP_COLS_PER_ROW = 3
    # Mesh Info 节点高度预估：基础高度 + 每个贴图槽位连接的撑高。
    # 节点 UI 由 socket 行（约 22px/行）与 draw_buttons 行（约 20px/行）构成，
    # 每个已连接槽位约增加 1 行 socket + 3 行槽位配置按钮。
    OBJ_BASE_HEIGHT = 220.0
    OBJ_SLOT_LINK_HEIGHT = 100.0

    # 预统计每组贴图节点数量，用于估算行高（贴图列需要预览空间）
    group_tex_counts: dict[str, int] = {}
    # 预统计每组 Mesh Info 节点的贴图槽位连接数（MarkType 非 Hash 的标记，
    # 去重规则与 _build_texture_nodes 的 slot_link_done 一致），用于估算节点撑高
    group_slot_link_counts: dict[str, int] = {}
    seen_mark_hashes: set[str] = set()
    seen_slot_links: set[tuple] = set()
    # 每个贴图 hash 的首个出现分组与首个 Slot 标记分组（"第一次使用它"的 submesh），
    # 用于决定贴图节点归属哪个分组的 Frame
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

    # 贴图归属分组：严格跟随"第一次使用它"（首个 Slot 标记）的 submesh；
    # 没有 Slot 标记的纯 Hash 贴图跟随第一个出现的分组
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
        # 同一 DrawIB 的 submesh 在一行内连续排列，二级 Frame 才不会罩住别组：
        # 当前行剩余列放不下整组时先换行
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

            # Mesh Info 节点会被贴图槽位连接撑高，按预估实际高度计入行高，避免与下一行重叠
            obj_height = row_start_y - y
            tex_height = group_tex_counts.get(group_key, 0) * TEX_Y_GAP
            row_max_height = max(row_max_height, obj_height, tex_height)
            max_node_right = max(max_node_right, base_x + OBJ_X_OFFSET)

            group_tex_cursors[group_key] = [base_x, row_start_y]
            group_top_y[group_key] = row_start_y
        # 跨行大组（超过一行宽）的二级 Frame 是覆盖多行的矩形，
        # 其最后一行的剩余列不能再放别组，否则会被框住
        if spanned_multiple_rows:
            col_in_row = MAX_GROUP_COLS_PER_ROW

    # 为每个分组创建 Frame，并把组内 Mesh Info 节点挂进去
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

    # 为每个 DrawIB 创建二级 Frame，把同 IB hash 的 Submesh Frame 并进去。
    # 布局阶段已保证同组 submesh 连续排列且跨行大组独占其所有行，
    # 因此二级 Frame 的矩形范围不会罩住其他分组。
    # Frame 尺寸由 Blender 按子节点自动贴合，这里只需给出大致的左上角位置。
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
    
    # 创建 WorkSpaceModel 统一管理所有映射
    ws_model = WorkSpaceModel()

    # 这里先创建以当前工作空间为名称的集合，并且链接到scene，确保它存在
    workspace_collection = SSMTWorkSpace.create_and_get_workspace_collection()

    if not ws_model.lod_components:
        self.report({'ERROR'}, "当前工作空间未找到任何 LOD 目录（LOD0、LOD1…），请检查工作空间结构。")
        return

    # key: 新格式 submesh_name（如 "LOD0.94517393-0"）, value: gametype_name
    foldername_gametypename_dict = {}
    foldername_imported_obj_dict = {}
    # old_folder_name -> 实际用于导入的 Submesh JSON 路径（贴图标记元数据来源）
    oldfoldername_jsonpath_dict = {}
    all_submesh_display_names = []
    successful_import_count = 0

    for lod_name in sorted(ws_model.lod_components.keys()):
        # 为每个 LOD 创建蓝色子集合，挂在工作空间集合下面
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

                # 获取导入的数据类型文件夹路径列表
                final_import_folder_path_list = SSMTWorkSpace.get_ordered_gpu_cpu_import_folderpath_list(folder_path)
                print("Final Import Folder Path List: " + str(final_import_folder_path_list))

                # 接下来开始导入，尝试对当前DrawIB的每个数据类型都进行导入
                for import_folder_path in final_import_folder_path_list:
                    gametype_name = import_folder_path.split("TYPE_")[1]

                    try:
                        print("尝试导入路径: " + import_folder_path)

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
                        self.report({'INFO'}, "成功导入 " + new_submesh_name + " 的数据类型: " + gametype_name)
                    except Exception as e:
                        print(f"Failed to import from {import_folder_path}: {e}")
                        continue
                    # 直到第一个导入成功就 Break
                    break

    if successful_import_count == 0:
        self.report({'ERROR'}, "当前工作空间没有成功导入任何模型，已跳过蓝图生成。")
        return

    # 保存工作空间级 Import.json 选择记录（使用新格式 key）
    save_import_json_path = os.path.join(GlobalConfig.path_workspace_folder(), "Import.json")
    JsonUtils.SaveToFile(json_dict=foldername_gametypename_dict, filepath=save_import_json_path)
    
    if getattr(context.scene.global_properties, "align_face_on_import", False):
        if not _apply_face_neck_object_alignment(foldername_imported_obj_dict):
            self.report({'WARNING'}, "矫正面部需要至少一个有效的 Face 和 Neck 标记。")

    _deselect_imported_objects(foldername_imported_obj_dict)
    _deselect_imported_shader_nodes(foldername_imported_obj_dict)

    # ==========================
    # 自动生成蓝图节点逻辑
    # ==========================
    try:
        # 创建蓝图，名称为当前工作空间名称
        tree_name = GlobalConfig.get_workspace_name()
        
        # Nico: 为了防止覆盖用户修改过的蓝图，始终创建新蓝图
        # 如果已存在同名蓝图，Blender会自动添加.001等后缀，从而保留旧蓝图
        try:
            tree = bpy.data.node_groups.new(name=tree_name, type='SSMTBlueprintTreeType')
        except Exception as e:
            print(f"Failed to create new node tree: {e}. Check if SSMTBlueprintTreeType is registered.")
            return
        tree.use_fake_user = True
        BlueprintExportHelper.set_tree_submesh_names(all_submesh_display_names, tree=tree)
        
        # 创建 Group 节点 (并在循环中连接)
        group_node = tree.nodes.new('SSMTNode_Object_Group')
        group_node.label = "Default Group"
        
        # 3. 创建 Object Info 节点并按 Submesh 分组布局（同 IB hash 并入二级 Frame）
        (oldfoldername_node_dict, oldfoldername_group_dict,
         group_tex_cursors, max_node_right, TEX_Y_GAP,
         group_frame_dict, tex_home_group) = _create_and_layout_obj_info_nodes(
            tree, group_node, foldername_imported_obj_dict, ws_model,
            oldfoldername_jsonpath_hint=oldfoldername_jsonpath_dict)

        # 3.5 根据各 Submesh 的贴图标记元数据自动创建并连接 Texture 节点
        # 只导入用户在 SSMT 中明确标记的贴图；风格由每条标记的 MarkType 决定
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

        # 4. 放置 Group 和 Output 节点（Hash 贴图分组与物体分组并列排放）
        group_node.location = (max_node_right + 560.0, -200.0)
        group_node.label = "网格体总组"
        if hash_group_node is not None:
            hash_group_node.location = (max_node_right + 560.0, -1000.0)
            hash_group_node.label = "Hash 风格贴图总组"

        output_node = tree.nodes.new('SSMTNode_Result_Output')
        output_node.location = (max_node_right + 1040.0, -200.0)
        output_node.label = "Generate Mod"

        face_export_node = _create_face_mod_export_node(
            tree, oldfoldername_node_dict, oldfoldername_jsonpath_dict,
            (max_node_right + 1040.0, -760.0),
        )
        
        # 两个并列的分组节点分别直接连到 Output
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
    bl_label = "一键导入SSMT工作空间内容"
    bl_description = "一键导入当前工作空间文件夹下所有的内容"
    bl_options = {'REGISTER','UNDO'}

    def execute(self, context):
        # print("Current WorkSpace: " + GlobalConfig.get_workspace_name())
        # print("Current Game: " + GlobalConfig.gamename)
        if GlobalConfig.get_workspace_name() == "":
            self.report({"ERROR"}, rpt_("请先在SSMT中选择当前工作空间后再导入。"))
        elif not os.path.exists(GlobalConfig.path_workspace_folder()):
            self.report({"ERROR"}, rpt_("工作空间文件夹不存在，请先在SSMT中创建工作空间: {path}").format(path=GlobalConfig.path_workspace_folder()))
        else:
            TimerUtils.Start("ImportFromWorkSpaceBlueprint")
            ImprotFromWorkSpaceFull(self, context)
            TimerUtils.End("ImportFromWorkSpaceBlueprint")
        
        return {'FINISHED'}
    

class SSMT4ImportRaw(bpy.types.Operator, ImportHelper):
    bl_idname = "ssmt4.import_raw"
    bl_label = "导入SSMT格式模型"
    bl_description = "导入SSMT格式的模型文件, 只需选择.json文件即可"
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
        # 我们需要添加到一个新建的集合里，方便后续操作
        # 这里集合的名称需要为当前文件夹的名称
        dirname = os.path.dirname(self.filepath)

        collection_name = os.path.basename(dirname)
        collection = bpy.data.collections.new(collection_name)
        bpy.context.scene.collection.children.link(collection)

        # 如果用户不选择任何json文件，则默认返回读取所有的json文件。
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

        # 逐个json文件导入
        for json_file_name in import_filename_list:
            if os.path.isabs(json_file_name):
                json_file_path = json_file_name
            else:
                json_file_path = os.path.join(dirname, json_file_name)
            SSMTImportHelper.create_mesh_from_json(json_file_path=json_file_path, import_collection=collection)

        CollectionUtils.deselect_collection_objects(collection)

        return {'FINISHED'}

# =============================================================================
# 筛选导入逻辑 — 只导入指定的 submesh 文件夹列表
# =============================================================================
def _get_or_create_lod_collection(workspace_collection, lod_name):
    '''查找或创建 LOD 子集合（重用已有集合，避免重复创建）。'''
    if lod_name in workspace_collection.children:
        return workspace_collection.children[lod_name]
    # 检查 bpy.data.collections 中是否已存在
    if lod_name in bpy.data.collections:
        existing = bpy.data.collections[lod_name]
        # 如果已存在但尚未挂到 workspace 下，则链接
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
    '''查找或创建工作空间集合（重用已有集合，避免重复创建）。'''
    workspace_name = GlobalConfig.get_workspace_name()
    if workspace_name in bpy.data.collections:
        ws_coll = bpy.data.collections[workspace_name]
        # 确保链接到 scene
        if ws_coll.name not in bpy.context.scene.collection.children:
            bpy.context.scene.collection.children.link(ws_coll)
        return ws_coll
    return SSMTWorkSpace.create_and_get_workspace_collection()


def ImprotFromWorkSpaceSelected(self, context, submesh_lod_info_list, force_gametype_name=None):
    '''
    仅导入指定的 submesh 列表。
    submesh_lod_info_list: [(lod_name, submesh_folder_path), ...]
    例如: [("LOD0", r"D:\SSMTCacheFolder\WorkSpace\GF2\Default\LOD0\3ed2b2ba-2592-76086"), ...]
    force_gametype_name: 如果指定（如 "CPU_P12_N12_TA16_C16_T4_"），
      则强制所有 submesh 只尝试该数据类型（用于 DrawIB 统一类型场景）。
      传入 "__AUTO__" 表示：第一个 submesh 正常尝试所有类型，
      确定哪个类型可用，后续 submesh 全部使用同一类型。
    '''
    ws_model = WorkSpaceModel()
    workspace_collection = _get_or_create_workspace_collection()

    foldername_gametypename_dict = {}
    foldername_imported_obj_dict = {}
    # old_folder_name -> 实际用于导入的 Submesh JSON 路径（贴图标记元数据来源）
    oldfoldername_jsonpath_dict = {}
    all_submesh_display_names = []
    successful_import_count = 0

    # 当 force_gametype_name == "__AUTO__" 时，第一个成功后锁定该类型
    locked_gametype = None

    # 按 LOD 分组
    lod_submesh_map: dict[str, list[str]] = {}
    for lod_name, submesh_folder_path in submesh_lod_info_list:
        if lod_name not in lod_submesh_map:
            lod_submesh_map[lod_name] = []
        lod_submesh_map[lod_name].append(submesh_folder_path)

    for lod_name, submesh_folder_paths in lod_submesh_map.items():
        # 查找或创建 LOD 子集合（复用已有的）
        lod_collection = _get_or_create_lod_collection(workspace_collection, lod_name)

        for submesh_folder_path in submesh_folder_paths:
            submesh_folder_name = os.path.basename(submesh_folder_path)
            print("Re-Import FolderName: " + submesh_folder_name)

            # 通过 WorkSpaceModel 获取 Component 序号和新格式名称
            old_folder_draw_ib = submesh_folder_name.split("-")[0]
            comp_index = ws_model.get_component_index(lod_name, old_folder_draw_ib, submesh_folder_name)
            if comp_index < 0:
                comp_index = 0

            new_submesh_name = ws_model.get_new_submesh_name(lod_name, old_folder_draw_ib, comp_index)
            display_name = ws_model.get_display_name(lod_name, old_folder_draw_ib, comp_index)

            # 确定要尝试的数据类型文件夹列表
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
                    print(f"数据类型文件夹不存在，跳过: {import_folder_path}")
                    continue
                gametype_name = import_folder_path.split("TYPE_")[1]

                try:
                    print("尝试导入路径: " + import_folder_path)

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
                    self.report({'INFO'}, "成功导入 " + new_submesh_name + " 的数据类型: " + gametype_name)

                    # 如果是 __AUTO__ 模式且第一次成功，锁定该类型供后续使用
                    if locked_gametype is None and force_gametype_name == "__AUTO__":
                        locked_gametype = gametype_name
                        self.report({'INFO'}, f"DrawIB 统一类型锁定为: {locked_gametype}，后续 submesh 全部使用此类型")
                except Exception as e:
                    print(f"Failed to re-import from {import_folder_path}: {e}")
                    continue
                break

    if successful_import_count == 0:
        self.report({'ERROR'}, "所选 submesh 没有成功导入任何模型。")
        return

    # 更新 Import.json（保留已有记录，覆盖本次导入的）
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
            self.report({'WARNING'}, "矫正面部需要至少一个有效的 Face 和 Neck 标记。")

    _deselect_imported_objects(foldername_imported_obj_dict)
    _deselect_imported_shader_nodes(foldername_imported_obj_dict)

    # 生成蓝图
    _generate_blueprint_for_imported_objects(context, foldername_imported_obj_dict, all_submesh_display_names, oldfoldername_jsonpath_dict)


def _generate_blueprint_for_imported_objects(context, foldername_imported_obj_dict, all_submesh_display_names, oldfoldername_jsonpath_dict=None):
    '''更新已存在的蓝图节点（不新建），若没有已有蓝图则跳过。'''
    tree_name = GlobalConfig.get_workspace_name()
    if not tree_name:
        return

    # 查找已有蓝图，不存在则跳过
    tree = bpy.data.node_groups.get(tree_name)
    if not tree:
        print(f"未找到已有蓝图 '{tree_name}'，跳过蓝图更新")
        return
    if not BlueprintExportHelper._is_valid_blueprint_tree(tree):
        print(f"已有节点组 '{tree_name}' 不是有效的 SSMT 蓝图，跳过")
        return

    try:
        # 清空所有节点和连接
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

        # Hash 贴图分组与物体分组并列排放
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
# 工具函数 — 删除物体
# =============================================================================
def _delete_objects(obj_names_to_delete: list[str]):
    '''删除 Blender 场景中指定名称列表的所有物体。'''
    for obj_name in obj_names_to_delete:
        if obj_name in bpy.data.objects:
            obj = bpy.data.objects[obj_name]
            # 从所有集合中移除
            for coll in list(obj.users_collection):
                coll.objects.unlink(obj)
            bpy.data.objects.remove(obj, do_unlink=True)


def _count_type_folders(submesh_folder_path: str) -> int:
    '''统计 submesh 文件夹下 TYPE_ 开头的文件夹数量。'''
    count = 0
    if not os.path.isdir(submesh_folder_path):
        return 0
    for entry in os.scandir(submesh_folder_path):
        if entry.is_dir() and entry.name.startswith("TYPE_"):
            count += 1
    return count


def _show_last_type_warning(submesh_folder_name: str):
    '''弹出警告对话框：该 submesh 只剩下最后一个数据类型，无法删除。'''
    def draw_popup(self, context):
        self.layout.label(
            text=f"Submesh '{submesh_folder_name}' 只剩下最后一个数据类型文件夹，"
        )
        self.layout.label(
            text="无法删除该类型。如果没有正确数据类型，请联系SSMT开发者添加。"
        )
    bpy.context.window_manager.popup_menu(draw_popup, title="警告", icon='ERROR')


# =============================================================================
# Operator — 该DrawIB数据类型不正确
# =============================================================================
class SSMT4FixDrawIBDataType(bpy.types.Operator):
    bl_idname = "ssmt4.fix_drawib_datatype"
    bl_label = "修复DrawIB数据类型"
    bl_description = "该DrawIB数据类型不正确：删除该DrawIB下所有对应数据类型的文件夹，删除相关Mesh，并重新导入"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        selected_objects = context.selected_objects
        if not selected_objects:
            self.report({'ERROR'}, "请先选中一个或多个物体")
            return {'CANCELLED'}

        from ..workspace.ssmt_workspace import SSMTWorkSpace

        workspace_folder = GlobalConfig.path_workspace_folder()
        if not workspace_folder or not os.path.exists(workspace_folder):
            self.report({'ERROR'}, "工作空间文件夹不存在，请先设置工作空间")
            return {'CANCELLED'}

        ws_model = WorkSpaceModel()

        # 1. 解析每个选中物体，收集 {lod_name: set_of_drawib}
        lod_drawib_set: dict[str, set[str]] = {}
        # 同时记录要删除的物体名称
        all_obj_info = []  # [(obj_name, lod_name, submesh_folder_name, draw_ib, gametypename)]
        for obj in selected_objects:
            gametypename = obj.get("3DMigoto:GameTypeName", "")
            if not gametypename:
                self.report({'WARNING'}, f"物体 '{obj.name}' 没有数据类型属性，已跳过")
                continue

            parsed = ws_model.parse_any_format_name(obj.name)
            if not parsed or not parsed["lod"] or not parsed["draw_ib"]:
                self.report({'WARNING'}, f"无法解析物体 '{obj.name}' 的名称，已跳过")
                continue

            submesh_folder_path = ws_model.get_folder_path(parsed["lod"], parsed["draw_ib"], parsed["component"])
            submesh_folder_name = os.path.basename(submesh_folder_path) if submesh_folder_path else ""

            all_obj_info.append((obj.name, parsed["lod"], submesh_folder_name, parsed["draw_ib"], gametypename))
            if parsed["lod"] not in lod_drawib_set:
                lod_drawib_set[parsed["lod"]] = set()
            lod_drawib_set[parsed["lod"]].add(parsed["draw_ib"])

        if not all_obj_info:
            self.report({'ERROR'}, "未能从选中物体中解析出任何有效信息")
            return {'CANCELLED'}

        # 2. 预检：收集该 DrawIB 下所有 submesh 文件夹
        all_submesh_entries: list[tuple[str, str, str]] = []  # [(lod_name, submesh_folder_name, submesh_folder_path)]
        for lod_name, draw_ib_set in lod_drawib_set.items():
            lod_folder_path = os.path.join(workspace_folder, lod_name)
            if not os.path.isdir(lod_folder_path):
                self.report({'WARNING'}, f"LOD 目录不存在: {lod_folder_path}")
                continue
            for entry in os.scandir(lod_folder_path):
                if not entry.is_dir():
                    continue
                folder_draw_ib = entry.name.split("-")[0]
                if folder_draw_ib in draw_ib_set:
                    all_submesh_entries.append((lod_name, entry.name, entry.path))

        if not all_submesh_entries:
            self.report({'ERROR'}, "没有找到对应的 submesh 文件夹")
            return {'CANCELLED'}

        # 3. 预检：检查是否有 submesh 只剩最后一个数据类型
        for lod_name, submesh_folder_name, submesh_folder_path in all_submesh_entries:
            for _, o_lod, o_submesh, o_draw_ib, gametypename in all_obj_info:
                if o_lod != lod_name or o_submesh != submesh_folder_name:
                    continue
                type_folder_path = os.path.join(submesh_folder_path, "TYPE_" + gametypename)
                if os.path.exists(type_folder_path) and _count_type_folders(submesh_folder_path) <= 1:
                    _show_last_type_warning(submesh_folder_name=submesh_folder_name)
                    self.report({'WARNING'}, f"Submesh '{submesh_folder_name}' 只剩下最后一个数据类型，已中止操作")
                    return {'CANCELLED'}

        # 4. 执行删除：删除 TYPE 文件夹
        for lod_name, submesh_folder_name, submesh_folder_path in all_submesh_entries:
            for _, o_lod, o_submesh, o_draw_ib, gametypename in all_obj_info:
                if o_lod != lod_name or o_submesh != submesh_folder_name:
                    continue
                type_folder_path = os.path.join(submesh_folder_path, "TYPE_" + gametypename)
                if os.path.exists(type_folder_path):
                    shutil.rmtree(type_folder_path)
                    self.report({'INFO'}, f"已删除数据类型文件夹: {type_folder_path}")

        # 5. 收集需要删除的物体名称（当前工作空间集合中所有属于该 DrawIB 的物体）
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

        # 去重
        all_obj_to_delete = list(dict.fromkeys(all_obj_to_delete))
        submesh_to_reimport = list(dict.fromkeys(submesh_to_reimport))

        # 6. 删除物体
        if all_obj_to_delete:
            _delete_objects(all_obj_to_delete)
            self.report({'INFO'}, f"已删除 {len(all_obj_to_delete)} 个物体")

        # 5. 重新导入（DrawIB 模式：自动统一类型，所有 submesh 使用同一数据类型）
        if submesh_to_reimport:
            ImprotFromWorkSpaceSelected(self, context, submesh_to_reimport, force_gametype_name="__AUTO__")
            self.report({'INFO'}, f"已重新导入 {len(submesh_to_reimport)} 个 submesh（DrawIB 统一类型）")
        else:
            self.report({'WARNING'}, "没有找到需要重新导入的 submesh")

        return {'FINISHED'}


# =============================================================================
# Operator — 该Submesh数据类型不正确
# =============================================================================
class SSMT4FixSubmeshDataType(bpy.types.Operator):
    bl_idname = "ssmt4.fix_submesh_datatype"
    bl_label = "修复Submesh数据类型"
    bl_description = "该Submesh数据类型不正确：删除对应数据类型的文件夹，删除该Mesh，并重新导入"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        selected_objects = context.selected_objects
        if not selected_objects:
            self.report({'ERROR'}, "请先选中一个或多个物体")
            return {'CANCELLED'}

        from ..workspace.ssmt_workspace import SSMTWorkSpace

        workspace_folder = GlobalConfig.path_workspace_folder()
        if not workspace_folder or not os.path.exists(workspace_folder):
            self.report({'ERROR'}, "工作空间文件夹不存在，请先设置工作空间")
            return {'CANCELLED'}

        ws_model = WorkSpaceModel()

        # 1. 解析每个选中物体，并预检
        submesh_entries: list[tuple[str, str, str, str]] = []  # [(obj_name, lod_name, submesh_folder_path, gametypename)]

        for obj in selected_objects:
            gametypename = obj.get("3DMigoto:GameTypeName", "")
            if not gametypename:
                self.report({'WARNING'}, f"物体 '{obj.name}' 没有数据类型属性，已跳过")
                continue

            parsed = ws_model.parse_any_format_name(obj.name)
            if not parsed or not parsed["lod"] or not parsed["draw_ib"]:
                self.report({'WARNING'}, f"无法解析物体 '{obj.name}' 的名称，已跳过")
                continue

            submesh_folder_path = ws_model.get_folder_path(parsed["lod"], parsed["draw_ib"], parsed["component"])
            if not submesh_folder_path or not os.path.isdir(submesh_folder_path):
                self.report({'WARNING'}, f"找不到物体 '{obj.name}' 对应的 submesh 文件夹，已跳过")
                continue

            submesh_entries.append((obj.name, parsed["lod"], submesh_folder_path, gametypename))

        if not submesh_entries:
            self.report({'ERROR'}, "未能从选中物体中解析出任何有效信息")
            return {'CANCELLED'}

        # 2. 预检：检查是否有 submesh 只剩最后一个数据类型
        for obj_name, lod_name, submesh_folder_path, gametypename in submesh_entries:
            type_folder_path = os.path.join(submesh_folder_path, "TYPE_" + gametypename)
            if os.path.exists(type_folder_path) and _count_type_folders(submesh_folder_path) <= 1:
                submesh_folder_name = os.path.basename(submesh_folder_path)
                _show_last_type_warning(submesh_folder_name=submesh_folder_name)
                self.report({'WARNING'}, f"Submesh '{submesh_folder_name}' 只剩下最后一个数据类型，已中止操作")
                return {'CANCELLED'}

        # 3. 执行删除：删除 TYPE 文件夹
        submesh_to_reimport: list[tuple[str, str]] = []
        obj_names_to_delete: list[str] = []

        for obj_name, lod_name, submesh_folder_path, gametypename in submesh_entries:
            type_folder_path = os.path.join(submesh_folder_path, "TYPE_" + gametypename)
            if os.path.exists(type_folder_path):
                shutil.rmtree(type_folder_path)
                self.report({'INFO'}, f"已删除数据类型文件夹: {type_folder_path}")

            submesh_to_reimport.append((lod_name, submesh_folder_path))
            obj_names_to_delete.append(obj_name)

        if not submesh_to_reimport:
            self.report({'ERROR'}, "没有找到需要处理的 submesh")
            return {'CANCELLED'}

        # 4. 删除物体
        if obj_names_to_delete:
            _delete_objects(obj_names_to_delete)
            self.report({'INFO'}, f"已删除 {len(obj_names_to_delete)} 个物体")

        # 4. 重新导入
        ImprotFromWorkSpaceSelected(self, context, submesh_to_reimport)
        self.report({'INFO'}, f"已重新导入 {len(submesh_to_reimport)} 个 submesh")

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
