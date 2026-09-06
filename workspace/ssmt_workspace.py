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
    Workspace data model - uniformly resolves the mapping relations of all LOD, DrawIB and Submesh from the on-disk directory structure.

    After scanning the workspace directory, the following mappings are built:
    - lod_components[lod_name][draw_ib][component_index] = old_folder_name
      e.g. {"LOD0": {"94517393": {0: "94517393-16884-0", 1: "94517393-25830-16884"}}}
    - lod_reverse[lod_name][draw_ib][old_folder_name] = component_index
    - lod_component_info[lod_name][draw_ib][component_index] = (index_count, first_index)
      Values parsed from old-format folder names, provided to the game exporter

    Naming rules:
    - New format (short name): {DrawIB}-{ComponentIndex}  e.g. 94517393-0
    - Old format (long name): {DrawIB}-{IndexCount}-{FirstIndex}  e.g. 94517393-16884-0
    - New name with LOD prefix: LOD0.94517393-0
    - Old name with LOD prefix: LOD0.94517393-16884-0
    '''

    workspace_path: str = field(default="")

    # Three-level mapping: lod -> drawib -> component_index -> old_folder_name
    lod_components: Dict[str, Dict[str, Dict[int, str]]] = field(default_factory=dict)

    # Reverse mapping: lod -> drawib -> old_folder_name -> component_index
    lod_reverse: Dict[str, Dict[str, Dict[str, int]]] = field(default_factory=dict)

    # Numeric info: lod -> drawib -> component_index -> (index_count, first_index)
    lod_component_info: Dict[str, Dict[str, Dict[int, tuple]]] = field(default_factory=dict)

    # DrawIB alias: draw_ib -> alias_name (read from each LOD's Config.json)
    drawib_aliases: Dict[str, str] = field(default_factory=dict)

    # Display-name list of all submeshes (new format, with LOD prefix and alias), for Blueprint dropdown lists
    all_display_names: List[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.workspace_path:
            self.workspace_path = GlobalConfig.path_workspace_folder()
        self._scan()

    def _parse_old_folder_name(self, folder_name: str):
        '''
        Parses (draw_ib, index_count, first_index) from an old-format folder name.
        "94517393-16884-0" -> ("94517393", 16884, 0)
        Returns None if the name does not match the old format (fewer than 3 segments).
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
        '''Reads the alias mapping in a given folder, returning a {draw_ib: alias_name} dict.
        Prefers Config.json (old format); if absent, tries Config\Tabs\*.json (new format).'''
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

        # New format: Config\Tabs\*.json -> modelRows[].aliasName
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
        '''Scans the workspace directory and builds all mappings.'''
        self.lod_components.clear()
        self.lod_reverse.clear()
        self.lod_component_info.clear()
        self.drawib_aliases.clear()
        self.all_display_names.clear()

        if not self.workspace_path or not os.path.isdir(self.workspace_path):
            return

        # Collect LOD folders
        lod_folders: List[tuple[str, str]] = []  # [(lod_name, lod_path)]
        for entry in os.scandir(self.workspace_path):
            if not entry.is_dir():
                continue
            name = entry.name
            if name.upper().startswith("LOD") and name[3:].isdigit():
                lod_folders.append((name, entry.path))
        lod_folders.sort(key=lambda x: int(x[0][3:]))

        if not lod_folders:
            # Backward compatibility with the old layout that has no LOD folders
            lod_folders = [("", self.workspace_path)]

        for lod_name, lod_path in lod_folders:
            # Read this LOD's Config.json
            if lod_name:
                self.drawib_aliases.update(self._read_config_json(lod_path))

            # Collect all old-format subfolders under this LOD
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

            # Sort by FirstIndex and assign Component indices
            self.lod_components[lod_name] = {}
            self.lod_reverse[lod_name] = {}
            self.lod_component_info[lod_name] = {}

            for draw_ib, entries in raw_entries.items():
                entries.sort(key=lambda x: x[1])  # ascending by FirstIndex

                comp_map: Dict[int, str] = {}
                reverse_map: Dict[str, int] = {}
                info_map: Dict[int, tuple] = {}

                for comp_index, (folder_name, _) in enumerate(entries):
                    comp_map[comp_index] = folder_name
                    reverse_map[folder_name] = comp_index
                    # Re-parse to obtain index_count
                    parsed = self._parse_old_folder_name(folder_name)
                    if parsed:
                        info_map[comp_index] = (parsed[1], parsed[2])

                self.lod_components[lod_name][draw_ib] = comp_map
                self.lod_reverse[lod_name][draw_ib] = reverse_map
                self.lod_component_info[lod_name][draw_ib] = info_map

            # Build the display-name list for this LOD
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

        # Read the root Config.json (aliases for the old layout without LOD folders)
        root_aliases = self._read_config_json(self.workspace_path)
        for k, v in root_aliases.items():
            if k not in self.drawib_aliases:
                self.drawib_aliases[k] = v

    # ---- Query methods ----

    def has_lod(self, lod_name: str) -> bool:
        return lod_name in self.lod_components

    def has_drawib(self, lod_name: str, draw_ib: str) -> bool:
        return self.has_lod(lod_name) and draw_ib in self.lod_components[lod_name]

    def has_component(self, lod_name: str, draw_ib: str, component: int) -> bool:
        return self.has_drawib(lod_name, draw_ib) and component in self.lod_components[lod_name][draw_ib]

    def get_old_folder_name(self, lod_name: str, draw_ib: str, component: int) -> str:
        '''Returns the old-format folder name: "94517393-16884-0"'''
        return self.lod_components.get(lod_name, {}).get(draw_ib, {}).get(component, "")

    def get_component_index(self, lod_name: str, draw_ib: str, old_folder_name: str) -> int:
        '''Looks up the Component index in reverse from an old-format folder name.'''
        return self.lod_reverse.get(lod_name, {}).get(draw_ib, {}).get(old_folder_name, -1)

    def get_index_count(self, lod_name: str, draw_ib: str, component: int) -> int:
        info = self.lod_component_info.get(lod_name, {}).get(draw_ib, {}).get(component)
        return info[0] if info else 0

    def get_first_index(self, lod_name: str, draw_ib: str, component: int) -> int:
        info = self.lod_component_info.get(lod_name, {}).get(draw_ib, {}).get(component)
        return info[1] if info else 0

    def get_index_count_first_index(self, lod_name: str, draw_ib: str, component: int) -> tuple:
        '''Returns the (index_count, first_index) tuple.'''
        info = self.lod_component_info.get(lod_name, {}).get(draw_ib, {}).get(component)
        return info if info else (0, 0)

    def resolve_component_info(self, lod_name: str, draw_ib: str, component: int):
        '''Returns the (old_folder_name, index_count, first_index) triple.'''
        old_name = self.get_old_folder_name(lod_name, draw_ib, component)
        if not old_name:
            return "", 0, 0
        ic, fi = self.get_index_count_first_index(lod_name, draw_ib, component)
        return old_name, ic, fi

    def get_new_submesh_name(self, lod_name: str, draw_ib: str, component: int) -> str:
        '''Returns the new-format submesh name (with LOD prefix): "LOD0.94517393-0"'''
        short = f"{draw_ib}-{component}"
        return f"{lod_name}.{short}" if lod_name else short

    def get_old_lod_submesh_name(self, lod_name: str, draw_ib: str, component: int) -> str:
        '''Returns the old-format submesh name (with LOD prefix): "LOD0.94517393-16884-0"'''
        old_folder = self.get_old_folder_name(lod_name, draw_ib, component)
        if not old_folder:
            return ""
        return f"{lod_name}.{old_folder}" if lod_name else old_folder

    def get_display_name(self, lod_name: str, draw_ib: str, component: int) -> str:
        '''Returns the display name used for Object naming, appending the alias when present.'''
        new_name = self.get_new_submesh_name(lod_name, draw_ib, component)
        alias = self.drawib_aliases.get(draw_ib, "")
        if alias:
            return f"{new_name}.{alias}"
        return new_name

    def get_folder_path(self, lod_name: str, draw_ib: str, component: int) -> str:
        '''Returns the full path of the actual subfolder.'''
        old_folder = self.get_old_folder_name(lod_name, draw_ib, component)
        if not old_folder:
            return ""
        if lod_name:
            return os.path.join(self.workspace_path, lod_name, old_folder)
        return os.path.join(self.workspace_path, old_folder)

    def get_submesh_folder_path_for_name(self, submesh_name: str) -> str:
        '''
        Returns the actual folder path for submesh_name (new format or old format).
        New format: "LOD0.94517393-0" or "94517393-0"
        Old format: "LOD0.94517393-16884-0" or "94517393-16884-0"
        '''
        parsed = self.parse_new_format_name(submesh_name)
        if parsed is not None:
            return self.get_folder_path(parsed["lod"], parsed["draw_ib"], parsed["component"])

        # Fallback: treat as old format and build the path directly
        lod_name, bare_name = SSMTWorkSpace.parse_lod_submesh_name(submesh_name)
        if lod_name:
            return os.path.join(self.workspace_path, lod_name, bare_name)
        return os.path.join(self.workspace_path, bare_name)

    def parse_new_format_name(self, name: str):
        '''
        Attempts to parse a name string in the new format.
        New format: [LOD prefix.]DrawIB-ComponentIndex[.alias]
        e.g. "LOD0.94517393-0.Body" -> {"lod": "LOD0", "draw_ib": "94517393", "component": 0, "alias": "Body"}
        e.g. "94517393-1" -> {"lod": "", "draw_ib": "94517393", "component": 1, "alias": ""}
        Returns None when the name cannot be recognized as new format.
        '''
        if not name:
            return None

        lod_name = ""
        bare = name

        # Strip the LOD prefix
        if name.upper().startswith("LOD") and "." in name:
            dot_idx = name.index(".")
            potential_lod = name[:dot_idx]
            lod_suffix = potential_lod[3:]
            if lod_suffix.isdigit():
                lod_name = potential_lod
                bare = name[dot_idx + 1:]

        # Split off the alias
        alias = ""
        if "." in bare:
            name_part, _, alias = bare.partition(".")
        else:
            name_part = bare

        # New format: DrawIB-ComponentIndex (exactly 2 segments; the second is purely numeric)
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
        Attempts to parse a name in any format (new format or old format).
        Tries the new format first; on failure falls back to the old format and converts via lookup tables to new-format info.
        Always returns a normalized result: {"lod", "draw_ib", "component", "alias", "old_folder_name"}
        Returns None when the name cannot be recognized.
        '''
        if not name:
            return None

        # Try the new format first
        result = self.parse_new_format_name(name)
        if result is not None:
            old_folder = self.get_old_folder_name(result["lod"], result["draw_ib"], result["component"])
            result["old_folder_name"] = old_folder
            return result

        # Fall back to old format: parse via parse_object_name_to_folder_info and look it up
        lod, folder_name, draw_ib = SSMTWorkSpace.parse_object_name_to_folder_info(name)
        if not draw_ib:
            return None

        # Split off the alias
        alias = ""
        if "." in name:
            _, _, alias = name.partition(".")
        if "." in alias:
            # Strip the LOD prefix before extracting the alias
            parts = alias.split(".")
            alias = parts[-1] if len(parts) > 1 else alias

        comp = self.get_component_index(lod, draw_ib, folder_name)
        if comp < 0:
            # Lookup failed; try parsing component from the old folder name
            # If no new-format name exists, the component mapping may not be built yet
            return None

        return {
            "lod": lod,
            "draw_ib": draw_ib,
            "component": comp,
            "alias": alias.strip(),
            "old_folder_name": folder_name,
        }

    def get_all_new_format_names(self) -> List[str]:
        '''Returns all new-format submesh names (with LOD prefix, without alias).'''
        names = []
        for lod_name in sorted(self.lod_components.keys()):
            for draw_ib in sorted(self.lod_components[lod_name].keys()):
                for comp in sorted(self.lod_components[lod_name][draw_ib].keys()):
                    names.append(self.get_new_submesh_name(lod_name, draw_ib, comp))
        return names

    def get_all_display_names(self) -> List[str]:
        '''Returns the list of all display names, including aliases.'''
        return list(self.all_display_names)

    def get_ordered_submesh_name_list_by_drawib(self, draw_ib: str) -> List[str]:
        '''
        Returns the new-format submesh_name list of all Components under the given DrawIB,
        sorted ascending by Component index and prefixed with the LOD name.
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

        # Prefer the alias explicitly configured in Config.json.
        configured_alias = str(drawib_aliasname_dict.get(draw_ib, "")).strip()
        if configured_alias:
            return configured_alias

        # If the name already carries an alias suffix, keep using it.
        if folder_alias.strip():
            return folder_alias.strip()

        # Without an alias, fall back to the raw Object name instead of writing a "custom name".
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
        # During import, sort by GPU types first, then CPU types
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
        Parses submesh_name and returns (lod_name, bare_name).
        If there is an LOD prefix (e.g. "LOD0.67f829fc-2653-0"), returns ("LOD0", "67f829fc-2653-0");
        Otherwise returns ("", submesh_name).
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
        Parses an imported Object name and returns (lod_name, submesh_folder_name, draw_ib).
        Object format: LOD0.{submesh_folder_name}[.{alias}]
        e.g. "LOD0.3ed2b2ba-2592-76086.Body"
          → ("LOD0", "3ed2b2ba-2592-76086", "3ed2b2ba")
        submesh_folder_name is characterized by containing at least 2 '-' (i.e. split('-') length >= 3).
        '''
        lod_name = ""
        bare_name = ""

        # 1. Strip the LOD prefix
        if object_name and object_name.upper().startswith("LOD") and "." in object_name:
            dot_idx = object_name.index(".")
            potential_lod = object_name[:dot_idx]
            lod_suffix = potential_lod[3:]
            if lod_suffix.isdigit():
                lod_name = potential_lod
                bare_name = object_name[dot_idx + 1:]
            else:
                # No LOD prefix; treat the whole name as bare_name
                bare_name = object_name
        else:
            bare_name = object_name

        # 2. Split submesh_folder_name out of bare_name
        #    bare_name may be "3ed2b2ba-2592-76086.Body" or "3ed2b2ba-2592-76086"
        #    submesh_folder_name contains >= 2 '-' characters
        parts = bare_name.split(".")
        submesh_folder_name = ""
        for i, part in enumerate(parts):
            if part.count("-") >= 2:
                submesh_folder_name = part
                break

        if not submesh_folder_name:
            # fallback: if no matching segment is found, bare_name itself is either the folder name
            # or parsing failed; return the whole name and let the caller decide
            submesh_folder_name = bare_name

        # 3. Extract the DrawIB (the part before the first '-')
        draw_ib = submesh_folder_name.split("-")[0] if submesh_folder_name else ""

        return lod_name, submesh_folder_name, draw_ib

    @staticmethod
    def get_submesh_folder_path(submesh_name: str) -> str:
        '''
        Returns the actual submesh folder path within the workspace for submesh_name (an LOD prefix is allowed).
        Supports new format: LOD0.94517393-0  → workspace/LOD0/94517393-16884-0/
        Supports old format: LOD0.67f829fc-2653-0 → workspace/LOD0/67f829fc-2653-0/
        '''
        workspace_folder = GlobalConfig.path_workspace_folder()

        # Try new-format parsing first
        ws_model = WorkSpaceModel(workspace_path=workspace_folder)
        parsed = ws_model.parse_new_format_name(submesh_name)
        if parsed is not None and parsed["draw_ib"] and parsed["lod"]:
            folder_path = ws_model.get_folder_path(parsed["lod"], parsed["draw_ib"], parsed["component"])
            if folder_path and os.path.isdir(folder_path):
                return folder_path

        # Fall back to old format
        lod_name, bare_name = SSMTWorkSpace.parse_lod_submesh_name(submesh_name)
        if lod_name:
            return os.path.join(workspace_folder, lod_name, bare_name)
        return os.path.join(workspace_folder, bare_name)

    @staticmethod
    def create_and_get_workspace_collection() -> bpy.types.Collection:
        # Create a Collection named after the current workspace and link it to the scene so it is guaranteed to exist
        workspace_collection = CollectionUtils.create_new_collection(collection_name=GlobalConfig.get_workspace_name(),color_tag=CollectionColor.Red)
        bpy.context.scene.collection.children.link(workspace_collection)
        return workspace_collection

    @staticmethod
    def _get_submesh_folderpath_list_from(base_folder: str) -> List[str]:
        '''
        Gets all SubMesh folders from the given directory (folders whose names contain at least two '-').
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
        Gets all directories under the current workspace that start with "LOD" followed by digits, sorted by name.
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
        Returns a {lod_name: [submesh_folder_path, ...]} dict, sorted by LOD.
        '''
        result: Dict[str, List[str]] = {}
        for lod_folder_path in SSMTWorkSpace.get_lod_folderpath_list():
            lod_name = os.path.basename(lod_folder_path)
            result[lod_name] = SSMTWorkSpace._get_submesh_folderpath_list_from(lod_folder_path)
        return result

    @staticmethod
    def get_submesh_folderpath_list() -> List[str]:
        '''
        Gets all SubMesh folders under the current workspace folder (compatible with the old layout without LOD folders).
        For new-format workspaces, use get_lod_submesh_folderpath_dict().
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
        Reads the DrawIB-to-alias mapping from the given directory.
        Prefers Config.json (old format); if absent, tries Config\Tabs\*.json (new format).
        '''
        drawib_aliasname_dict = {}

        # Strategy 1: read Config.json (old format)
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

        # Strategy 2: read from Config\Tabs\*.json (new format)
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
        Reads the DrawIB-to-alias mapping from the current workspace directory.
        Priority: Config.json > Config\\Tabs\\*.json > Config.json under LOD subfolders
        '''
        drawib_aliasname_dict = {}

        workspace_folder = GlobalConfig.path_workspace_folder()

        # Strategy 1: read the Config.json at the workspace root (old format)
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

        # Strategy 2: read from Config\\Tabs\\*.json (SSMT4 new format)
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

        # Strategy 3: scan the Config.json under LOD subfolders
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
        Finds the SubmeshJson file path corresponding to submesh_name.
        Supports both the new format (DrawIB-ComponentIndex) and the old format (DrawIB-IndexCount-FirstIndex).
        Returns the path when found; raises an SSMTErrorUtils error otherwise.
        """
        workspace_folder = GlobalConfig.path_workspace_folder()

        # Try new-format parsing to obtain the actual folder path and bare_name
        ws_model = WorkSpaceModel(workspace_path=workspace_folder)
        parsed = ws_model.parse_new_format_name(submesh_name)
        if parsed is not None and parsed["draw_ib"]:
            lod_name = parsed["lod"]
            old_folder_name = ws_model.get_old_folder_name(lod_name, parsed["draw_ib"], parsed["component"])
            if old_folder_name:
                submesh_folder = ws_model.get_folder_path(lod_name, parsed["draw_ib"], parsed["component"])
                bare_name = old_folder_name
            else:
                # New-format parsing succeeded but the lookup failed; fall back to the old logic
                lod_name, bare_name = SSMTWorkSpace.parse_lod_submesh_name(submesh_name)
                submesh_folder = SSMTWorkSpace.get_submesh_folder_path(submesh_name)
        else:
            # Old format
            lod_name, bare_name = SSMTWorkSpace.parse_lod_submesh_name(submesh_name)
            submesh_folder = SSMTWorkSpace.get_submesh_folder_path(submesh_name)

        if not os.path.exists(submesh_folder):
            SSMTErrorUtils.raise_fatal(
                f"submesh_name '{submesh_name}' has no corresponding extracted data.\n"
                + "Please make sure the model has been extracted from the game and run the \"One-Click Import Current Workspace Content\" operation."
            )

        workspace_import_json_path = os.path.join(workspace_folder, "Import.json")
        workspace_import_json = JsonUtils.LoadFromFile(workspace_import_json_path) if os.path.exists(workspace_import_json_path) else {}
        # The Import.json key may be in new format or old format; try both
        gametype_name = workspace_import_json.get(submesh_name, "")
        if not gametype_name and parsed is not None and old_folder_name:
            # Retry with the old-format key
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
                f"submesh_name '{submesh_name}' found the following Data Types but they were not recorded in Import.json: {', '.join(found_types)}\n"
                + "Please try running the \"One-Click Import Current Workspace Content\" operation again."
            )

        SSMTErrorUtils.raise_fatal(
            f"submesh_name '{submesh_name}' has no corresponding SubmeshJson.\n"
            + "Please make sure the model has been extracted from the game and run the \"One-Click Import Current Workspace Content\" operation."
        )

    @staticmethod
    def get_ordered_submesh_name_list_by_drawib(draw_ib: str) -> list[str]:
        """
        Finds the Submesh folders corresponding to the DrawIB in the workspace,
        sorts them ascending by FirstIndex and returns the submesh_name list (new format).
        New format: LOD0.94517393-0, LOD0.94517393-1, ...
        """
        ws_model = WorkSpaceModel()
        return ws_model.get_ordered_submesh_name_list_by_drawib(draw_ib)

    @staticmethod
    def get_hash_deduped_texture_info_dict(submesh_folder_name:str) -> Dict[str,DedupedTextureInfo]:

        draw_ib_folder_path = os.path.dirname(SSMTWorkSpace.get_submesh_folder_path(submesh_folder_name)) + "\\"
        # Next compute the ComponentList: the counts of all Components of the current DrawIB that use this texture, starting from 1
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

            # From a file name such as "b7ff7a6e_03d46264-R8G8B8A8_UNORM_SRGB.dds",
            # extract the "R8G8B8A8_UNORM_SRGB" portion:
            # - Drop the extension
            # - Locate the first underscore `_`
            # - After that underscore, find the first hyphen `-` and take the substring from it to the end of the file name
            # - If no such pattern is found, fall back to splitting at the last `-` and taking the last segment
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