from ..common.global_config import GlobalConfig

from ..utils.json_utils import JsonUtils
from ..utils.collection_utils import CollectionUtils, CollectionColor
from ..utils.ssmt_error_utils import SSMTErrorUtils
import os
import bpy
from typing import List, Dict, Union
from dataclasses import dataclass, field, asdict

@dataclass
class DedupedTextureInfo:
    original_hash:str = field(default="",init=False)
    render_hash:str = field(default="",init=False)
    format:str = field(default="",init=False)
    componet_count_list_str:str = field(default="",init=False)


@dataclass
class WorkSpaceModel:
    '''
    工作空间数据模型 —— 从磁盘目录结构统一解析所有 LOD、DrawIB、Submesh 的映射关系。

    扫描工作空间目录后构建以下映射:
    - lod_components[lod_name][draw_ib][component_index] = old_folder_name
      例: {"LOD0": {"94517393": {0: "94517393-16884-0", 1: "94517393-25830-16884"}}}
    - lod_reverse[lod_name][draw_ib][old_folder_name] = component_index
    - lod_component_info[lod_name][draw_ib][component_index] = (index_count, first_index)
      从旧格式文件夹名中解析的数值，供游戏导出器使用

    命名规则:
    - 新格式（短名）: {DrawIB}-{ComponentIndex}  例: 94517393-0
    - 旧格式（长名）: {DrawIB}-{IndexCount}-{FirstIndex}  例: 94517393-16884-0
    - 带 LOD 前缀的新名: LOD0.94517393-0
    - 带 LOD 前缀的旧名: LOD0.94517393-16884-0
    '''

    workspace_path: str = field(default="")

    # 三层映射: lod -> drawib -> component_index -> old_folder_name
    lod_components: Dict[str, Dict[str, Dict[int, str]]] = field(default_factory=dict)

    # 反向映射: lod -> drawib -> old_folder_name -> component_index
    lod_reverse: Dict[str, Dict[str, Dict[str, int]]] = field(default_factory=dict)

    # 数值信息: lod -> drawib -> component_index -> (index_count, first_index)
    lod_component_info: Dict[str, Dict[str, Dict[int, tuple]]] = field(default_factory=dict)

    # DrawIB 别名: draw_ib -> alias_name (从各 LOD 的 Config.json 读取)
    drawib_aliases: Dict[str, str] = field(default_factory=dict)

    # 所有 submesh 的显示名称列表（新格式，带 LOD 前缀和别名），供蓝图下拉列表使用
    all_display_names: List[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.workspace_path:
            self.workspace_path = GlobalConfig.path_workspace_folder()
        self._scan()

    def _parse_old_folder_name(self, folder_name: str):
        '''
        从旧格式文件夹名中解析 (draw_ib, index_count, first_index)。
        "94517393-16884-0" -> ("94517393", 16884, 0)
        不符合旧格式（< 3 段）返回 None。
        '''
        parts = folder_name.split("-")
        if len(parts) < 3:
            return None
        try:
            draw_ib = parts[0]
            index_count = int(parts[1])
            first_index = int(parts[2])
            return draw_ib, index_count, first_index
        except ValueError:
            return None

    def _read_config_json(self, folder_path: str) -> Dict[str, str]:
        '''读取某个目录下的别名映射，返回 {draw_ib: alias_name} 字典。
        优先读取 Config.json（旧格式），若不存在则尝试 Config\Tabs\*.json（新格式）。'''
        result = {}
        config_path = os.path.join(folder_path, "Config.json")
        if os.path.exists(config_path):
            try:
                config_json = JsonUtils.LoadFromFile(config_path)
                if isinstance(config_json, list):
                    for item in config_json:
                        if not isinstance(item, dict):
                            continue
                        draw_ib = str(item.get("DrawIB", "")).strip()
                        alias = str(item.get("Alias", "")).strip()
                        if draw_ib:
                            result[draw_ib] = alias
            except Exception:
                pass
            return result

        # 新格式: Config\Tabs\*.json -> modelRows[].aliasName
        tabs_dir = os.path.join(folder_path, "Config", "Tabs")
        if os.path.isdir(tabs_dir):
            for filename in os.listdir(tabs_dir):
                if not filename.endswith(".json"):
                    continue
                try:
                    tab_data = JsonUtils.LoadFromFile(os.path.join(tabs_dir, filename))
                except Exception:
                    continue
                if not isinstance(tab_data, dict):
                    continue
                for row in tab_data.get("modelRows", []):
                    if not isinstance(row, dict):
                        continue
                    draw_ib = str(row.get("drawIB", "")).strip()
                    alias = str(row.get("aliasName", "")).strip()
                    if draw_ib and alias:
                        result[draw_ib] = alias

        return result

    def _scan(self):
        '''扫描工作空间目录，构建所有映射。'''
        self.lod_components.clear()
        self.lod_reverse.clear()
        self.lod_component_info.clear()
        self.drawib_aliases.clear()
        self.all_display_names.clear()

        if not self.workspace_path or not os.path.isdir(self.workspace_path):
            return

        # 收集 LOD 文件夹
        lod_folders: List[tuple[str, str]] = []  # [(lod_name, lod_path)]
        for entry in os.scandir(self.workspace_path):
            if not entry.is_dir():
                continue
            name = entry.name
            if name.upper().startswith("LOD") and name[3:].isdigit():
                lod_folders.append((name, entry.path))
        lod_folders.sort(key=lambda x: int(x[0][3:]))

        if not lod_folders:
            # 兼容旧版无 LOD 结构
            lod_folders = [("", self.workspace_path)]

        for lod_name, lod_path in lod_folders:
            # 读取该 LOD 的 Config.json
            if lod_name:
                self.drawib_aliases.update(self._read_config_json(lod_path))

            # 收集该 LOD 下所有旧格式子文件夹
            raw_entries: Dict[str, list] = {}  # drawib -> [(folder_name, first_index)]
            for entry in os.scandir(lod_path):
                if not entry.is_dir():
                    continue
                parsed = self._parse_old_folder_name(entry.name)
                if parsed is None:
                    continue
                draw_ib, _, first_index = parsed
                if draw_ib not in raw_entries:
                    raw_entries[draw_ib] = []
                raw_entries[draw_ib].append((entry.name, first_index))

            # 按 FirstIndex 排序并分配 Component 序号
            self.lod_components[lod_name] = {}
            self.lod_reverse[lod_name] = {}
            self.lod_component_info[lod_name] = {}

            for draw_ib, entries in raw_entries.items():
                entries.sort(key=lambda x: x[1])  # 按 FirstIndex 升序

                comp_map: Dict[int, str] = {}
                reverse_map: Dict[str, int] = {}
                info_map: Dict[int, tuple] = {}

                for comp_index, (folder_name, _) in enumerate(entries):
                    comp_map[comp_index] = folder_name
                    reverse_map[folder_name] = comp_index
                    # 重新解析以获取 index_count
                    parsed = self._parse_old_folder_name(folder_name)
                    if parsed:
                        info_map[comp_index] = (parsed[1], parsed[2])

                self.lod_components[lod_name][draw_ib] = comp_map
                self.lod_reverse[lod_name][draw_ib] = reverse_map
                self.lod_component_info[lod_name][draw_ib] = info_map

            # 构建该 LOD 的显示名称列表
            for draw_ib in sorted(self.lod_components[lod_name].keys()):
                alias = self.drawib_aliases.get(draw_ib, "")
                for comp in sorted(self.lod_components[lod_name][draw_ib].keys()):
                    short_name = f"{draw_ib}-{comp}"
                    if lod_name:
                        full_name = f"{lod_name}.{short_name}"
                    else:
                        full_name = short_name
                    if alias:
                        full_name += f".{alias}"
                    self.all_display_names.append(full_name)

        # 读取根目录 Config.json（兼容旧版无 LOD 结构时的别名）
        root_aliases = self._read_config_json(self.workspace_path)
        for k, v in root_aliases.items():
            if k not in self.drawib_aliases:
                self.drawib_aliases[k] = v

    # ---- 查询方法 ----

    def has_lod(self, lod_name: str) -> bool:
        return lod_name in self.lod_components

    def has_drawib(self, lod_name: str, draw_ib: str) -> bool:
        return self.has_lod(lod_name) and draw_ib in self.lod_components[lod_name]

    def has_component(self, lod_name: str, draw_ib: str, component: int) -> bool:
        return self.has_drawib(lod_name, draw_ib) and component in self.lod_components[lod_name][draw_ib]

    def get_old_folder_name(self, lod_name: str, draw_ib: str, component: int) -> str:
        '''返回旧格式文件夹名: "94517393-16884-0"'''
        return self.lod_components.get(lod_name, {}).get(draw_ib, {}).get(component, "")

    def get_component_index(self, lod_name: str, draw_ib: str, old_folder_name: str) -> int:
        '''从旧格式文件夹名反向查 Component 序号。'''
        return self.lod_reverse.get(lod_name, {}).get(draw_ib, {}).get(old_folder_name, -1)

    def get_index_count(self, lod_name: str, draw_ib: str, component: int) -> int:
        info = self.lod_component_info.get(lod_name, {}).get(draw_ib, {}).get(component)
        return info[0] if info else 0

    def get_first_index(self, lod_name: str, draw_ib: str, component: int) -> int:
        info = self.lod_component_info.get(lod_name, {}).get(draw_ib, {}).get(component)
        return info[1] if info else 0

    def get_index_count_first_index(self, lod_name: str, draw_ib: str, component: int) -> tuple:
        '''返回 (index_count, first_index) 元组。'''
        info = self.lod_component_info.get(lod_name, {}).get(draw_ib, {}).get(component)
        return info if info else (0, 0)

    def resolve_component_info(self, lod_name: str, draw_ib: str, component: int):
        '''返回 (old_folder_name, index_count, first_index) 三元组。'''
        old_name = self.get_old_folder_name(lod_name, draw_ib, component)
        if not old_name:
            return "", 0, 0
        ic, fi = self.get_index_count_first_index(lod_name, draw_ib, component)
        return old_name, ic, fi

    def get_new_submesh_name(self, lod_name: str, draw_ib: str, component: int) -> str:
        '''返回新格式 submesh 名（带 LOD 前缀）: "LOD0.94517393-0"'''
        short = f"{draw_ib}-{component}"
        return f"{lod_name}.{short}" if lod_name else short

    def get_old_lod_submesh_name(self, lod_name: str, draw_ib: str, component: int) -> str:
        '''返回旧格式 submesh 名（带 LOD 前缀）: "LOD0.94517393-16884-0"'''
        old_folder = self.get_old_folder_name(lod_name, draw_ib, component)
        if not old_folder:
            return ""
        return f"{lod_name}.{old_folder}" if lod_name else old_folder

    def get_display_name(self, lod_name: str, draw_ib: str, component: int) -> str:
        '''返回用于物体命名的显示名称，如果有别名则附上。'''
        new_name = self.get_new_submesh_name(lod_name, draw_ib, component)
        alias = self.drawib_aliases.get(draw_ib, "")
        if alias:
            return f"{new_name}.{alias}"
        return new_name

    def get_folder_path(self, lod_name: str, draw_ib: str, component: int) -> str:
        '''返回实际子文件夹的完整路径。'''
        old_folder = self.get_old_folder_name(lod_name, draw_ib, component)
        if not old_folder:
            return ""
        if lod_name:
            return os.path.join(self.workspace_path, lod_name, old_folder)
        return os.path.join(self.workspace_path, old_folder)

    def get_submesh_folder_path_for_name(self, submesh_name: str) -> str:
        '''
        根据 submesh_name（新格式或旧格式）返回实际文件夹路径。
        新格式: "LOD0.94517393-0" 或 "94517393-0"
        旧格式: "LOD0.94517393-16884-0" 或 "94517393-16884-0"
        '''
        parsed = self.parse_new_format_name(submesh_name)
        if parsed is not None:
            return self.get_folder_path(parsed["lod"], parsed["draw_ib"], parsed["component"])

        # 回退: 当作旧格式处理，直接拼接路径
        lod_name, bare_name = SSMTWorkSpace.parse_lod_submesh_name(submesh_name)
        if lod_name:
            return os.path.join(self.workspace_path, lod_name, bare_name)
        return os.path.join(self.workspace_path, bare_name)

    def parse_new_format_name(self, name: str):
        '''
        尝试按新格式解析名称字符串。
        新格式: [LOD前缀.]DrawIB-ComponentIndex[.别名]
        例: "LOD0.94517393-0.身体" -> {"lod": "LOD0", "draw_ib": "94517393", "component": 0, "alias": "身体"}
        例: "94517393-1" -> {"lod": "", "draw_ib": "94517393", "component": 1, "alias": ""}
        无法识别为新格式时返回 None。
        '''
        if not name:
            return None

        lod_name = ""
        bare = name

        # 剥离 LOD 前缀
        if name.upper().startswith("LOD") and "." in name:
            dot_idx = name.index(".")
            potential_lod = name[:dot_idx]
            lod_suffix = potential_lod[3:]
            if lod_suffix.isdigit():
                lod_name = potential_lod
                bare = name[dot_idx + 1:]

        # 分离别名
        alias = ""
        if "." in bare:
            name_part, _, alias = bare.partition(".")
        else:
            name_part = bare

        # 新格式: DrawIB-ComponentIndex（恰好 2 段，第二段是纯数字）
        parts = name_part.split("-")
        if len(parts) == 2:
            try:
                component = int(parts[1])
            except ValueError:
                return None
            return {
                "lod": lod_name,
                "draw_ib": parts[0],
                "component": component,
                "alias": alias.strip(),
            }

        return None

    def parse_any_format_name(self, name: str):
        '''
        尝试解析任意格式的名称（新格式或旧格式）。
        优先按新格式解析，失败则回退到旧格式并查表转换为新格式信息。
        始终返回标准化结果: {"lod", "draw_ib", "component", "alias", "old_folder_name"}
        识别不了时返回 None。
        '''
        if not name:
            return None

        # 先试新格式
        result = self.parse_new_format_name(name)
        if result is not None:
            old_folder = self.get_old_folder_name(result["lod"], result["draw_ib"], result["component"])
            result["old_folder_name"] = old_folder
            return result

        # 回退旧格式: 通过 parse_object_name_to_folder_info 解析后查表
        lod, folder_name, draw_ib = SSMTWorkSpace.parse_object_name_to_folder_info(name)
        if not draw_ib:
            return None

        # 分离别名
        alias = ""
        if "." in name:
            _, _, alias = name.partition(".")
        if "." in alias:
            # 去掉 LOD 前缀后取别名
            parts = alias.split(".")
            alias = parts[-1] if len(parts) > 1 else alias

        comp = self.get_component_index(lod, draw_ib, folder_name)
        if comp < 0:
            # 查表失败，尝试从旧文件夹名解析 component
            # 如果新格式名不存在，可能还没有 component 映射
            return None

        return {
            "lod": lod,
            "draw_ib": draw_ib,
            "component": comp,
            "alias": alias.strip(),
            "old_folder_name": folder_name,
        }

    def get_all_new_format_names(self) -> List[str]:
        '''返回所有新格式 submesh 名称（带 LOD 前缀，不含别名）。'''
        names = []
        for lod_name in sorted(self.lod_components.keys()):
            for draw_ib in sorted(self.lod_components[lod_name].keys()):
                for comp in sorted(self.lod_components[lod_name][draw_ib].keys()):
                    names.append(self.get_new_submesh_name(lod_name, draw_ib, comp))
        return names

    def get_all_display_names(self) -> List[str]:
        '''返回所有带别名的显示名称列表。'''
        return list(self.all_display_names)

    def get_ordered_submesh_name_list_by_drawib(self, draw_ib: str) -> List[str]:
        '''
        返回某个 DrawIB 下所有 Component 的新格式 submesh_name 列表，
        按 Component 序号升序排列，带 LOD 前缀。
        '''
        result = []
        for lod_name in sorted(self.lod_components.keys()):
            if draw_ib not in self.lod_components[lod_name]:
                continue
            comp_map = self.lod_components[lod_name][draw_ib]
            for comp in sorted(comp_map.keys()):
                result.append(self.get_new_submesh_name(lod_name, draw_ib, comp))
        return result


class SSMTWorkSpace:

    @staticmethod
    def get_object_display_name(submesh_folder_name: str, drawib_aliasname_dict: Dict[str, str] | None = None) -> str:
        normalized_folder_name = str(submesh_folder_name or "").strip()
        if not normalized_folder_name:
            return ""

        drawib_aliasname_dict = drawib_aliasname_dict or SSMTWorkSpace.get_drawib_aliasname_dict()
        folder_prefix, _, folder_alias = normalized_folder_name.partition(".")
        draw_ib = folder_prefix.split("-")[0]

        # 优先使用 Config.json 里显式配置的别名。
        configured_alias = str(drawib_aliasname_dict.get(draw_ib, "")).strip()
        if configured_alias:
            return configured_alias

        # 如果名称里已经带了别名后缀，则沿用它。
        if folder_alias.strip():
            return folder_alias.strip()

        # 无别名时回退为原始对象名称，避免写入“自定义名称”。
        return folder_prefix

    @staticmethod
    def get_display_submesh_name(submesh_folder_name: str, drawib_aliasname_dict: Dict[str, str] | None = None) -> str:
        normalized_folder_name = str(submesh_folder_name or "").strip()
        if not normalized_folder_name:
            return ""

        alias_name = SSMTWorkSpace.get_object_display_name(
            normalized_folder_name,
            drawib_aliasname_dict=drawib_aliasname_dict,
        )
        if not alias_name or alias_name == normalized_folder_name:
            return normalized_folder_name

        name_prefix, _, _ = normalized_folder_name.partition(".")
        return name_prefix + "." + alias_name

    @staticmethod
    def get_ordered_gpu_cpu_import_folderpath_list(submesh_folderpath:str)-> List[str]:
        # 导入时，要按照先GPU类型，再CPU类型进行排序
        gpu_import_folder_path_list = []
        cpu_import_folder_path_list = []

        dirs = os.listdir(submesh_folderpath)
        for dirname in dirs:
            if not dirname.startswith("TYPE_"):
                continue
            final_import_folder_path = os.path.join(submesh_folderpath,dirname)
            if dirname.startswith("TYPE_GPU"):
                gpu_import_folder_path_list.append(final_import_folder_path)
            elif dirname.startswith("TYPE_CPU"):
                cpu_import_folder_path_list.append(final_import_folder_path)

        final_import_folder_path_list = []
        for gpu_path in gpu_import_folder_path_list:
            final_import_folder_path_list.append(gpu_path)
        for cpu_path in cpu_import_folder_path_list:
            final_import_folder_path_list.append(cpu_path)

        return final_import_folder_path_list

    @staticmethod
    def parse_lod_submesh_name(submesh_name: str):
        '''
        解析 submesh_name，返回 (lod_name, bare_name)。
        如果有 LOD 前缀（如 "LOD0.67f829fc-2653-0"），返回 ("LOD0", "67f829fc-2653-0")；
        否则返回 ("", submesh_name)。
        '''
        if submesh_name and submesh_name.upper().startswith("LOD") and "." in submesh_name:
            dot_idx = submesh_name.index(".")
            potential_lod = submesh_name[:dot_idx]
            lod_suffix = potential_lod[3:]
            if lod_suffix.isdigit():
                return potential_lod, submesh_name[dot_idx + 1:]
        return "", submesh_name

    @staticmethod
    def parse_object_name_to_folder_info(object_name: str):
        '''
        解析导入后的物体名称，返回 (lod_name, submesh_folder_name, draw_ib)。
        物体格式: LOD0.{submesh_folder_name}[.{alias}]
        例如: "LOD0.3ed2b2ba-2592-76086.身体"
          → ("LOD0", "3ed2b2ba-2592-76086", "3ed2b2ba")
        submesh_folder_name 的特征是包含至少 2 个 '-'（即 split('-') 长度 >= 3）。
        '''
        lod_name = ""
        bare_name = ""

        # 1. 去掉 LOD 前缀
        if object_name and object_name.upper().startswith("LOD") and "." in object_name:
            dot_idx = object_name.index(".")
            potential_lod = object_name[:dot_idx]
            lod_suffix = potential_lod[3:]
            if lod_suffix.isdigit():
                lod_name = potential_lod
                bare_name = object_name[dot_idx + 1:]
            else:
                # 没有 LOD 前缀，整体当作 bare_name
                bare_name = object_name
        else:
            bare_name = object_name

        # 2. 从 bare_name 中分离 submesh_folder_name
        #    bare_name 可能是 "3ed2b2ba-2592-76086.身体" 或 "3ed2b2ba-2592-76086"
        #    submesh_folder_name 的特征是包含 >= 2 个 '-'
        parts = bare_name.split(".")
        submesh_folder_name = ""
        for i, part in enumerate(parts):
            if part.count("-") >= 2:
                submesh_folder_name = part
                break

        if not submesh_folder_name:
            # fallback: 如果找不到符合特征的段，说明要么 bare_name 本身既是 folder name
            # 要么解析失败；直接整体返回，由调用方判断
            submesh_folder_name = bare_name

        # 3. 提取 DrawIB（第一个 '-' 之前的部分）
        draw_ib = submesh_folder_name.split("-")[0] if submesh_folder_name else ""

        return lod_name, submesh_folder_name, draw_ib

    @staticmethod
    def get_submesh_folder_path(submesh_name: str) -> str:
        '''
        根据 submesh_name（可带 LOD 前缀）返回工作空间内实际的 submesh 文件夹路径。
        支持新格式: LOD0.94517393-0  → workspace/LOD0/94517393-16884-0/
        支持旧格式: LOD0.67f829fc-2653-0 → workspace/LOD0/67f829fc-2653-0/
        '''
        workspace_folder = GlobalConfig.path_workspace_folder()

        # 先尝试新格式解析
        ws_model = WorkSpaceModel(workspace_path=workspace_folder)
        parsed = ws_model.parse_new_format_name(submesh_name)
        if parsed is not None and parsed["draw_ib"] and parsed["lod"]:
            folder_path = ws_model.get_folder_path(parsed["lod"], parsed["draw_ib"], parsed["component"])
            if folder_path and os.path.isdir(folder_path):
                return folder_path

        # 回退旧格式
        lod_name, bare_name = SSMTWorkSpace.parse_lod_submesh_name(submesh_name)
        if lod_name:
            return os.path.join(workspace_folder, lod_name, bare_name)
        return os.path.join(workspace_folder, bare_name)

    @staticmethod
    def create_and_get_workspace_collection() -> bpy.types.Collection:
        # 这里先创建以当前工作空间为名称的集合，并且链接到scene，确保它存在
        workspace_collection = CollectionUtils.create_new_collection(collection_name=GlobalConfig.get_workspace_name(),color_tag=CollectionColor.Red)
        bpy.context.scene.collection.children.link(workspace_collection)
        return workspace_collection

    @staticmethod
    def _get_submesh_folderpath_list_from(base_folder: str) -> List[str]:
        '''
        从指定目录中获取所有 SubMesh 文件夹（名字包含至少两个 '-' 的目录）。
        '''
        result = []
        if not os.path.isdir(base_folder):
            return result
        for f in os.scandir(base_folder):
            if not f.is_dir():
                continue
            if len(f.name.split('-')) >= 3:
                result.append(f.path)
        return result

    @staticmethod
    def get_lod_folderpath_list() -> List[str]:
        '''
        获取当前工作空间目录下所有以 "LOD" 开头（后接数字）的目录，按名称排序。
        '''
        lod_folders = []
        workspace_folder = GlobalConfig.path_workspace_folder()
        if not os.path.isdir(workspace_folder):
            return lod_folders
        for f in os.scandir(workspace_folder):
            if not f.is_dir():
                continue
            name = f.name
            if name.upper().startswith("LOD") and name[3:].isdigit():
                lod_folders.append(f.path)
        lod_folders.sort(key=lambda p: int(os.path.basename(p)[3:]))
        return lod_folders

    @staticmethod
    def get_lod_submesh_folderpath_dict() -> Dict[str, List[str]]:
        '''
        返回 {lod_name: [submesh_folder_path, ...]} 字典，按 LOD 排序。
        '''
        result: Dict[str, List[str]] = {}
        for lod_folder_path in SSMTWorkSpace.get_lod_folderpath_list():
            lod_name = os.path.basename(lod_folder_path)
            result[lod_name] = SSMTWorkSpace._get_submesh_folderpath_list_from(lod_folder_path)
        return result

    @staticmethod
    def get_submesh_folderpath_list() -> List[str]:
        '''
        获取当前工作空间文件夹下面的所有SubMesh文件夹（兼容旧版无LOD结构）。
        新版工作空间请使用 get_lod_submesh_folderpath_dict()。
        '''
        submesh_folderpath_list = []
        for f in os.scandir(GlobalConfig.path_workspace_folder()):
            if not f.is_dir():
                continue
            name_splits = f.name.split('-')
            if len(name_splits) >= 3:
                submesh_folderpath_list.append(f.path)
            
        return submesh_folderpath_list

    @staticmethod
    def get_drawib_aliasname_dict_for_path(folder_path: str) -> Dict[str, str]:
        '''
        从指定目录下读取 DrawIB 和别名的对应关系。
        优先读取 Config.json（旧格式），若不存在则尝试 Config\Tabs\*.json（新格式）。
        '''
        drawib_aliasname_dict = {}

        # 策略1: 读取 Config.json（旧格式）
        config_json_path = os.path.join(folder_path, "Config.json")
        if os.path.exists(config_json_path):
            config_json = JsonUtils.LoadFromFile(config_json_path)
            if isinstance(config_json, list):
                for item in config_json:
                    if not isinstance(item, dict):
                        continue
                    draw_ib = str(item.get("DrawIB", "")).strip()
                    alias_name = str(item.get("Alias", "")).strip()
                    if draw_ib:
                        drawib_aliasname_dict[draw_ib] = alias_name
            return drawib_aliasname_dict

        # 策略2: 从 Config\Tabs\*.json 中读取（新格式）
        tabs_dir = os.path.join(folder_path, "Config", "Tabs")
        if os.path.isdir(tabs_dir):
            for filename in os.listdir(tabs_dir):
                if not filename.endswith(".json"):
                    continue
                tab_json_path = os.path.join(tabs_dir, filename)
                try:
                    tab_data = JsonUtils.LoadFromFile(tab_json_path)
                except Exception:
                    continue
                if not isinstance(tab_data, dict):
                    continue
                for row in tab_data.get("modelRows", []):
                    if not isinstance(row, dict):
                        continue
                    draw_ib = str(row.get("drawIB", "")).strip()
                    alias_name = str(row.get("aliasName", "")).strip()
                    if draw_ib and alias_name:
                        drawib_aliasname_dict[draw_ib] = alias_name

        return drawib_aliasname_dict

    @staticmethod
    def get_drawib_aliasname_dict() -> Dict[str,str]:
        '''
        从当前工作空间目录下读取DrawIB和别名的对应关系。
        按优先级: Config.json > Config\\Tabs\\*.json > LOD子目录的Config.json
        '''
        drawib_aliasname_dict = {}

        workspace_folder = GlobalConfig.path_workspace_folder()

        # 策略1: 读取工作空间根目录的 Config.json（旧格式）
        config_json_path = os.path.join(workspace_folder, "Config.json")
        if os.path.exists(config_json_path):
            config_json = JsonUtils.LoadFromFile(config_json_path)
            if isinstance(config_json, list):
                for item in config_json:
                    if not isinstance(item, dict):
                        continue
                    draw_ib = str(item.get("DrawIB", "")).strip()
                    alias_name = str(item.get("Alias", "")).strip()
                    if draw_ib:
                        drawib_aliasname_dict[draw_ib] = alias_name
            if drawib_aliasname_dict:
                return drawib_aliasname_dict

        # 策略2: 从 Config\\Tabs\\*.json 中读取（SSMT4 新格式）
        tabs_dir = os.path.join(workspace_folder, "Config", "Tabs")
        if os.path.isdir(tabs_dir):
            for filename in os.listdir(tabs_dir):
                if not filename.endswith(".json"):
                    continue
                tab_json_path = os.path.join(tabs_dir, filename)
                try:
                    tab_data = JsonUtils.LoadFromFile(tab_json_path)
                except Exception:
                    continue
                if not isinstance(tab_data, dict):
                    continue
                for row in tab_data.get("modelRows", []):
                    if not isinstance(row, dict):
                        continue
                    draw_ib = str(row.get("drawIB", "")).strip()
                    alias_name = str(row.get("aliasName", "")).strip()
                    if draw_ib and alias_name:
                        drawib_aliasname_dict[draw_ib] = alias_name
            if drawib_aliasname_dict:
                return drawib_aliasname_dict

        # 策略3: 扫描 LOD 子目录的 Config.json
        for entry in os.scandir(workspace_folder):
            if not entry.is_dir():
                continue
            lod_config_path = os.path.join(entry.path, "Config.json")
            if not os.path.exists(lod_config_path):
                continue
            try:
                config_json = JsonUtils.LoadFromFile(lod_config_path)
            except Exception:
                continue
            if isinstance(config_json, list):
                for item in config_json:
                    if not isinstance(item, dict):
                        continue
                    draw_ib = str(item.get("DrawIB", "")).strip()
                    alias_name = str(item.get("Alias", "")).strip()
                    if draw_ib:
                        drawib_aliasname_dict[draw_ib] = alias_name

        return drawib_aliasname_dict
    

    @staticmethod
    def check_and_get_submesh_json_path(submesh_name: str) -> str:
        """
        根据 submesh_name 查找对应的 SubmeshJson 文件路径。
        支持新格式（DrawIB-ComponentIndex）和旧格式（DrawIB-IndexCount-FirstIndex）。
        找到返回路径，找不到抛出 SSMTErrorUtils 错误。
        """
        workspace_folder = GlobalConfig.path_workspace_folder()

        # 尝试新格式解析，获取实际文件夹路径和 bare_name
        ws_model = WorkSpaceModel(workspace_path=workspace_folder)
        parsed = ws_model.parse_new_format_name(submesh_name)
        if parsed is not None and parsed["draw_ib"]:
            lod_name = parsed["lod"]
            old_folder_name = ws_model.get_old_folder_name(lod_name, parsed["draw_ib"], parsed["component"])
            if old_folder_name:
                submesh_folder = ws_model.get_folder_path(lod_name, parsed["draw_ib"], parsed["component"])
                bare_name = old_folder_name
            else:
                # 新格式解析成功但查表失败，回退旧逻辑
                lod_name, bare_name = SSMTWorkSpace.parse_lod_submesh_name(submesh_name)
                submesh_folder = SSMTWorkSpace.get_submesh_folder_path(submesh_name)
        else:
            # 旧格式
            lod_name, bare_name = SSMTWorkSpace.parse_lod_submesh_name(submesh_name)
            submesh_folder = SSMTWorkSpace.get_submesh_folder_path(submesh_name)

        if not os.path.exists(submesh_folder):
            SSMTErrorUtils.raise_fatal(
                f"submesh_name '{submesh_name}' 没有找到对应的提取数据。\n"
                + "请确保已从游戏中提取模型并执行「一键导入当前工作空间内容」操作。"
            )

        workspace_import_json_path = os.path.join(workspace_folder, "Import.json")
        workspace_import_json = JsonUtils.LoadFromFile(workspace_import_json_path) if os.path.exists(workspace_import_json_path) else {}
        # Import.json 的 key 可能是新格式或旧格式，两种都试试
        gametype_name = workspace_import_json.get(submesh_name, "")
        if not gametype_name and parsed is not None and old_folder_name:
            # 用旧格式 key 再试一次
            old_full = f"{lod_name}.{old_folder_name}" if lod_name else old_folder_name
            gametype_name = workspace_import_json.get(old_full, "")

        if gametype_name:
            submesh_json_path = os.path.join(submesh_folder, "TYPE_" + gametype_name, bare_name + ".json")
            if os.path.exists(submesh_json_path):
                return submesh_json_path

        found_type_paths = []
        found_types = []
        for dirname in os.listdir(submesh_folder):
            if not dirname.startswith("TYPE_"):
                continue

            submesh_json_path = os.path.join(submesh_folder, dirname, bare_name + ".json")
            if os.path.exists(submesh_json_path):
                found_type_paths.append(submesh_json_path)
                found_types.append(dirname.replace("TYPE_", ""))

        if len(found_type_paths) == 1:
            return found_type_paths[0]

        if len(found_type_paths) > 1:
            SSMTErrorUtils.raise_fatal(
                f"submesh_name '{submesh_name}' 找到以下数据类型但没有在 Import.json 中记录: {', '.join(found_types)}\n"
                + "请尝试重新执行「一键导入当前工作空间内容」操作。"
            )

        SSMTErrorUtils.raise_fatal(
            f"submesh_name '{submesh_name}' 没有找到对应的 SubmeshJson。\n"
            + "请确保已从游戏中提取模型并执行「一键导入当前工作空间内容」操作。"
        )

    @staticmethod
    def get_ordered_submesh_name_list_by_drawib(draw_ib: str) -> list[str]:
        """
        根据 DrawIB 在工作空间中查找对应的 Submesh 文件夹，
        按 FirstIndex 升序排序后返回 submesh_name 列表（新格式）。
        新格式: LOD0.94517393-0, LOD0.94517393-1, ...
        """
        ws_model = WorkSpaceModel()
        return ws_model.get_ordered_submesh_name_list_by_drawib(draw_ib)

    @staticmethod
    def get_hash_deduped_texture_info_dict(submesh_folder_name:str) -> Dict[str,DedupedTextureInfo]:

        draw_ib_folder_path = os.path.dirname(SSMTWorkSpace.get_submesh_folder_path(submesh_folder_name)) + "\\"
        # 接下来计算ComponentList，也就是当前DrawIB使用到这个贴图的所有Component的Count，从1开始
        component_name__drawcall_indexlist_json_path = os.path.join(draw_ib_folder_path,"ComponentName_DrawCallIndexList.json")
        trianglelist_deduped_filename_json_path = os.path.join(draw_ib_folder_path,"TrianglelistDedupedFileName.json")

        component_name__drawcall_indexlist_json_dict = JsonUtils.LoadFromFile(component_name__drawcall_indexlist_json_path)

        drawcall_component_count_dict = {}
        for component_index, (_, drawcall_indexlist) in enumerate(component_name__drawcall_indexlist_json_dict.items(), start=1):
            for drawcall_index in drawcall_indexlist:
                drawcall_component_count_dict[drawcall_index] = str(component_index)

        trianglelist_deduped_filename_json_dict = JsonUtils.LoadFromFile(trianglelist_deduped_filename_json_path)


        deduped_filename_drawcall_index_list_dict = {}
        for trianglelist_deduped_filename,deduped_kv_dict in trianglelist_deduped_filename_json_dict.items():
            deduped_filename:str = deduped_kv_dict.get("FALogDedupedFileName", "")
            json_format:str = deduped_kv_dict.get("Format", "")
            draw_call_index:str = trianglelist_deduped_filename[0:6]

            drawcall_index_list = deduped_filename_drawcall_index_list_dict.get(deduped_filename,[])
            if draw_call_index not in drawcall_index_list:
                drawcall_index_list.append(draw_call_index)

            deduped_filename_drawcall_index_list_dict[deduped_filename] = drawcall_index_list

        hash_deduped_texture_info_dict = {}

        for deduped_filename, drawcall_index_list in deduped_filename_drawcall_index_list_dict.items():
            used_component_count_list = []

            filename_parts = deduped_filename.split("_")
            original_hash = filename_parts[0] if len(filename_parts) > 0 else ""
            render_hash = filename_parts[1].split("-")[0] if len(filename_parts) > 1 else ""

            # 从类似于 "b7ff7a6e_03d46264-R8G8B8A8_UNORM_SRGB.dds" 的文件名中
            # 提取出 "R8G8B8A8_UNORM_SRGB" 部分：
            # - 去掉扩展名
            # - 找到第一个下划线 `_` 的位置
            # - 从该下划线之后查找第一个连字符 `-`，并取其后到文件名末尾的子串
            # - 如果找不到上述模式，则退回到以最后一个 `-` 分割并取最后一段的策略
            base_name = os.path.splitext(deduped_filename)[0]
            fmt = ""
            try:
                first_underscore = base_name.find("_")
                if first_underscore != -1:
                    dash_after_underscore = base_name.find("-", first_underscore + 1)
                    if dash_after_underscore != -1:
                        fmt = base_name[dash_after_underscore + 1:]
                # fallback: use last '-' part
                if not fmt:
                    if "-" in base_name:
                        fmt = base_name.rsplit("-", 1)[-1]
                    else:
                        # as ultimate fallback, if there is an underscore then maybe format is after the second underscore
                        parts = base_name.split("_")
                        if len(parts) > 2:
                            fmt = parts[-1]
                        else:
                            fmt = ""
                # strip any stray whitespace
                fmt = fmt.strip()
            except Exception:
                fmt = ""

            format = json_format if json_format else fmt

            for draw_call_index in drawcall_index_list:
                matched_component_count = drawcall_component_count_dict.get(draw_call_index,"")
                if matched_component_count != "":
                    if matched_component_count not in used_component_count_list:
                        used_component_count_list.append(matched_component_count)

            used_component_count_list.sort()
            # print(used_component_count_list)

            

            componet_count_list_str = ""
            for unique_component_count_str in used_component_count_list:
                componet_count_list_str = componet_count_list_str + unique_component_count_str + "."

            deduped_texture_info = DedupedTextureInfo()
            deduped_texture_info.original_hash = original_hash
            deduped_texture_info.render_hash = render_hash
            deduped_texture_info.format = format
            deduped_texture_info.componet_count_list_str = componet_count_list_str

            hash_deduped_texture_info_dict[original_hash] = deduped_texture_info
    
        return hash_deduped_texture_info_dict