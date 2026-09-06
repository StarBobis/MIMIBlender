import bpy
import os
import json


from .global_properties import GlobalProperties


'''
Execution logic names.
In the SSMT3 family, any game can be configured with any execution logic, and the execution logic determines the concrete game flow.
In the SSMT4 family, to simplify the flow and lower maintenance cost, every game maps to exactly one LogicName.
Put differently, the LogicName field itself maps one-to-one onto the GamePreset game preset field on the SSMT4 side.

Also, no matter how deeply the data types are understood, when most users pick a wrong data type and it becomes a habit,
as with the WWMI COLOR1 vs TEXCOORD issue, the popular choice should be respected to keep maintenance cost low.
After all, most people in this world are ordinary, and ordinary people do not want to think; the simpler the better.
It can also be read as: if most people misunderstand a concept, the correct understanding of that concept no longer matters;
what matters is how most people misunderstand that concept.
What SSMT essentially is does not matter; what matters is what SSMT looks like in most people's eyes.
'''
class LogicName:
    # Popular games, kept under ongoing maintenance
    GIMI = "GIMI"
    HIMI = "HIMI"
    SRMI = "SRMI"
    ZZMI = "ZZMI"
    ZZMIDX12 = "ZZMIDX12"
    WWMI = "WWMI"
    EFMI = "EFMI"

    # Niche games with very few users; maintain them when users provide feedback
    # Note: if a game has a native mod method, 3Dmigoto should not be used for mod making
    # A path against the mainstream only raises maintenance cost too high and ends up forgotten by the world
    # If only a small minority of people are served, the maintenance cost must be considered
    GF2 = "GF2" # Girls' Frontline 2, or a CPU-PreSkinning type game; the representative way of forcing modifications with 3Dmigoto
    IdentityV = "IdentityV" # Identity V (Neox3 engine); kept only to serve some abstract fan-made video creators
    AILIMIT = "AILIMIT" # A small game from a small studio, but Hongxi still runs a fan group, so keep it for his followers for now
    DOAV = "DOAV" # An antique game, the root of all evil; even adding it serves little purpose, keeping it is just a tribute
    SnowBreak = "SnowBreak" # Snowbreak already has a native mod method, but if it ever stops working one day, 3Dmigoto becomes the backup
    YYSLS = "YYSLS" # Where Winds Meet: huge marketing budget, yet still very few players
    Naraka = "Naraka" # Using mods can cause frame drops / 30-day account ban / permanent ban
    NarakaM = "NarakaM" # Using mods can cause frame drops / 30-day account ban / permanent ban
    
    NTEMI = "NTEMI" # Neverness to Everness; testing only
    
    # Reserved slots
    APMI = "APMI" # Azur Promilia, still in closed beta; already tested on the beta server, perfect 3Dmigoto support, expected to be adopted by XXMI when released
    NEMI = "NEMI" # Neverness to Everness, still in closed beta; already tested on the beta server, perfect 3Dmigoto support, expected to be adopted by XXMI when released

    @classmethod
    def is_zzmi_family(cls, logic_name: str) -> bool:
        return logic_name in {cls.ZZMI, cls.ZZMIDX12}


# Global config class: fields are by default the only globally accessible static variables, implementing global state
class GlobalConfig:
    # Global static variables: the value accessed from anywhere is always the same one
    gamename = ""
    workspacename = ""
    ssmtlocation = ""
    current_game_migoto_folder = ""
    logic_name = ""

    '''
    In the new Generate Mod architecture, tracks the global key index within a Mod
    and the number of Mods generated so far; every DrawIB is one Mod.
    Global variables are used to avoid overly complex variable passing.
    '''
    global_key_index: int = 0
    generated_mod_number: int = 0
    # Temporary INI stem used when a blueprint contains chained output nodes.
    # The generated Mod directory itself must continue to use the workspace name.
    generated_mod_name_override: str = ""

    @classmethod
    def initialize_key_count(cls):
        cls.global_key_index = 0
        cls.generated_mod_number = 0
        cls.generated_mod_name_override = ""

    @classmethod
    def get_generated_mod_name(cls):
        """Return the current INI filename stem for game exporters."""
        return cls.generated_mod_name_override or cls.get_workspace_name()

    @classmethod
    def read_from_main_json_ssmt4(cls) :
        try:
            # SSMT5/ProjectBunny panel must read its own settings only,
            # never fall back to MMT / MIMITools settings here.
            main_settings = GlobalConfig._ssmt_settings()
            cls.gamename = main_settings.get("CurrentGameName", "")
            # SSMT records the workspace name per game in CurrentWorkSpaceByGame,
            # which has higher priority than the global CurrentWorkSpace.
            workspace_by_game = main_settings.get("CurrentWorkSpaceByGame", {})
            if not isinstance(workspace_by_game, dict):
                workspace_by_game = {}
            cls.workspacename = str(
                workspace_by_game.get(cls.gamename, "")
                or main_settings.get("CurrentWorkSpace", "")
                or ""
            )
            # SSMT5/ProjectBunny writes its cache folder path under the legacy key
            # "DBMTWorkFolder" in ProjectBunnyGlobalConfigs/settings.json.
            # When the key is empty, fall back to the legacy SSMT4CachedFolder.
            ssmt_work_folder = str(main_settings.get("DBMTWorkFolder", "") or "").strip()
            if not ssmt_work_folder:
                ssmt_work_folder = os.path.join(
                    GlobalConfig.path_appdata_local(), "SSMT4CachedFolder"
                )
            cls.ssmtlocation = ssmt_work_folder + "\\"

            # SSMT5/ProjectBunny panel only trusts the game config written by
            # the host itself; MMT / MIMITools game configs must not leak here.
            # Try the new ProjectBunny location first, then the legacy SSMT4 one.
            game_config_json_path = ""
            for config_root in (
                GlobalConfig.path_project_bunny_global_configs_folder(),
                os.path.join(GlobalConfig.path_appdata_local(), "SSMT4GlobalConfigs\\"),
            ):
                candidate = os.path.join(config_root, "Games", cls.gamename, "Config.json")
                if os.path.exists(candidate):
                    game_config_json_path = candidate
                    break

            game_config_json = GlobalConfig._load_json_dict(game_config_json_path)
            cls.current_game_migoto_folder = game_config_json.get("installDir", "")
            cls.logic_name = game_config_json.get("gamePreset", "")
        except Exception as e:
            print(e)
            
    @classmethod
    def base_path(cls):
        return cls.ssmtlocation
    
    @staticmethod
    def path_drawib_config_json_path():
        '''
        Config.json in the current workspace folder,
        stores all DrawIBs and their aliases.
        '''
        game_config_json_path = os.path.join(GlobalConfig.path_workspace_folder(),"Config.json")
        return game_config_json_path
    
    @staticmethod
    def path_configs_folder():
        return os.path.join(GlobalConfig.base_path(),"Configs\\")
    
    @staticmethod
    def path_reverse_output_folder():
        # Reverse output belongs to the ProjectBunny/MMT toolchain.
        settings = GlobalConfig._mmt_family_settings()
        reverse_output_folder = str(settings.get("ReverseOutputFolder", "") or "").strip()
        if reverse_output_folder:
            return reverse_output_folder
        return ""

    @staticmethod
    def reverse_output_format():
        # Reverse output format is written by ProjectBunny/MMT on reverse success,
        # symmetric to ReverseOutputFolder. Values: ib_vb_fmt / ssmt_fmt.
        # When the key is missing, treat the output as the legacy ib_vb_fmt format.
        settings = GlobalConfig._mmt_family_settings()
        reverse_output_format = str(settings.get("ReverseOutputFormat", "") or "").strip()
        if reverse_output_format:
            return reverse_output_format
        return "ib_vb_fmt"

    @staticmethod
    def path_project_bunny_global_configs_folder():
        # SSMT5/ProjectBunny now writes Blender-facing configs here.
        return os.path.join(GlobalConfig.path_appdata_local(), "ProjectBunnyGlobalConfigs\\")

    @staticmethod
    def path_mimitools_settings_json():
        # Kept as legacy fallback only; new host no longer writes this file.
        return os.path.join(GlobalConfig.path_appdata_local(), "MIMIToolsGlobalConfigs", "MIMIToolsSettings.json")

    @staticmethod
    def path_mmt_settings_json():
        return os.path.join(GlobalConfig.path_project_bunny_global_configs_folder(), "MMTSettings.json")

    @staticmethod
    def path_mmt_global_configs_folder():
        return GlobalConfig.path_project_bunny_global_configs_folder()

    @staticmethod
    def path_mimitools_global_configs_folder():
        # Kept as legacy fallback only; new host no longer writes this folder.
        return os.path.join(GlobalConfig.path_appdata_local(), "MIMIToolsGlobalConfigs\\")

    @staticmethod
    def _load_json_dict(file_path):
        try:
            if file_path and os.path.exists(file_path):
                with open(file_path, 'r', encoding='utf-8') as f:
                    return json.load(f) or {}
        except Exception as e:
            print(e)
        return {}

    @staticmethod
    def _ssmt_settings():
        # Read SSMT5/ProjectBunny's settings.json first, then fall back to the
        # legacy SSMT4GlobalConfigs/settings.json for older installs.
        settings = GlobalConfig._load_json_dict(
            os.path.join(GlobalConfig.path_project_bunny_global_configs_folder(), "settings.json")
        )
        if not settings:
            settings = GlobalConfig._load_json_dict(
                os.path.join(GlobalConfig.path_appdata_local(), "SSMT4GlobalConfigs", "settings.json")
            )
        return settings

    @staticmethod
    def _mmt_settings():
        # Read the host reverse/app-state file written by SSMT5/ProjectBunny.
        return GlobalConfig._load_json_dict(GlobalConfig.path_mmt_settings_json())

    @staticmethod
    def _mimitools_settings():
        # Legacy fallback only; the new host no longer writes MIMIToolsSettings.json.
        return GlobalConfig._load_json_dict(GlobalConfig.path_mimitools_settings_json())

    @staticmethod
    def _mmt_family_settings():
        # The reverse toolchain is shared by MMT/MIMITools/ProjectBunny.
        # ProjectBunny's MMTSettings.json has highest priority; legacy
        # MMTGlobalConfigs and MIMIToolsSettings remain fallbacks for older installs.
        settings = GlobalConfig._mmt_settings()
        if not settings:
            settings = GlobalConfig._load_json_dict(
                os.path.join(GlobalConfig.path_appdata_local(), "MMTGlobalConfigs", "MMTSettings.json")
            )
        if not settings:
            settings = GlobalConfig._mimitools_settings()
        return settings

    @staticmethod
    def path_mimitools_reversed_root():
        # MIMITools reverse panel reads the ProjectBunny/MMT toolchain only,
        # SSMT extraction settings are never involved.
        settings = GlobalConfig._mmt_family_settings()
        work_folder = str(settings.get("DBMTWorkFolder", "") or "").strip()
        if work_folder:
            return os.path.join(work_folder, "Reversed")
        # Only MMT / MIMITools cache folders are valid here,
        # SSMT4CachedFolder must not be used by MIMITools reverse panel.
        for cache_folder_name in ("MMTCachedFolder", "MIMIToolsCachedFolder"):
            candidate = os.path.join(GlobalConfig.path_appdata_local(), cache_folder_name, "Reversed")
            if os.path.isdir(candidate):
                return candidate
        return ""

    @staticmethod
    def path_mimitools_reverse_output_folder():
        # Reverse output folder is stored by the ProjectBunny/MMT toolchain.
        settings = GlobalConfig._mmt_family_settings()
        reverse_output_folder = str(settings.get("ReverseOutputFolder", "") or "").strip()
        if reverse_output_folder:
            return reverse_output_folder
        reversed_root = GlobalConfig.path_mimitools_reversed_root()
        if not reversed_root:
            return ""
        workspace_name = str(
            settings.get("ReversedWorkSpaceName", "")
            or settings.get("CurrentWorkSpace", "")
            or ""
        ).strip()
        if workspace_name:
            return os.path.join(reversed_root, workspace_name)
        return reversed_root

    @classmethod
    def _read_d3dx_ini_mod_folder_name(cls):
        """Read the actual mod folder from d3dx.ini's include_recursive.

        3DMigoto does not require the mod folder to be named ``Mods``.  The
        real folder is configured in the [Include] section of the d3dx.ini
        located next to the 3DMigoto DLL.  Fall back to ``Mods`` if the file
        or setting cannot be found.
        """
        if not cls.current_game_migoto_folder:
            return "Mods"
        d3dx_ini_path = os.path.join(cls.current_game_migoto_folder, "d3dx.ini")
        try:
            with open(d3dx_ini_path, "r", encoding="utf-8-sig") as d3dx_ini_file:
                for raw_line in d3dx_ini_file:
                    line = raw_line.strip()
                    if not line or line.startswith(";") or line.startswith("#"):
                        continue
                    if line.startswith("[") and line.endswith("]"):
                        continue
                    key, separator, value = line.partition("=")
                    if separator and key.strip().lower() == "include_recursive":
                        mod_folder = value.strip().strip("\"'").strip()
                        if mod_folder:
                            # Keep only the first component if d3dx.ini uses
                            # comma-separated recursive include directories.
                            mod_folder = mod_folder.split(",")[0].strip().strip("\"'").strip()
                            mod_folder = mod_folder.rstrip("\\/")
                            if mod_folder:
                                return mod_folder
                return "Mods"
        except (OSError, UnicodeDecodeError):
            return "Mods"

    @classmethod
    def path_mods_folder(cls):
        mod_folder = cls._read_d3dx_ini_mod_folder_name()
        return os.path.join(cls.current_game_migoto_folder, mod_folder + "\\")

    @staticmethod
    def path_total_workspace_folder():
        return os.path.join(GlobalConfig.base_path(),"WorkSpace\\") 
    
    @staticmethod
    def path_current_game_total_workspace_folder():
        return os.path.join(GlobalConfig.path_total_workspace_folder(),GlobalConfig.gamename + "\\") 

    @staticmethod
    def _normalize_workspace_folder_path(folder_path: str) -> str:
        normalized = str(folder_path or "").strip()
        if not normalized:
            return ""

        normalized = os.path.normpath(normalized)
        if not normalized.endswith("\\"):
            normalized = normalized + "\\"
        return normalized

    @classmethod
    def get_workspace_name(cls):
        try:
            workspace_source_mode = GlobalProperties.workspace_source_mode()

            if workspace_source_mode == "SPECIFIC":
                specified_workspace_name = GlobalProperties.specific_workspace_name()
                if specified_workspace_name:
                    return specified_workspace_name

            if workspace_source_mode == "CUSTOM":
                custom_workspace_folder_path = GlobalConfig._normalize_workspace_folder_path(
                    GlobalProperties.custom_workspace_folder_path()
                )
                if custom_workspace_folder_path:
                    return os.path.basename(custom_workspace_folder_path.rstrip("\\/"))
        except Exception:
            pass

        return cls.workspacename
    
    @classmethod
    def path_workspace_folder(cls):
        try:
            if GlobalProperties.workspace_source_mode() == "CUSTOM":
                custom_workspace_folder_path = GlobalConfig._normalize_workspace_folder_path(
                    GlobalProperties.custom_workspace_folder_path()
                )
                if custom_workspace_folder_path:
                    return custom_workspace_folder_path
                return ""
        except Exception:
            pass

        return os.path.join(GlobalConfig.path_current_game_total_workspace_folder(), cls.get_workspace_name() + "\\")
    
    @classmethod
    def path_generate_mod_folder(cls):
        # If the user enabled the "use a specified folder" option, return that folder location,
        # otherwise return our default location. Note that SkipIB and VSCheck are not generated into the specified location.
        if GlobalProperties.use_specific_generate_mod_folder_path():
            return GlobalProperties.generate_mod_folder_path()
        else:
            # Make sure the caller directly receives an already-existing directory
            ssmt_generated_mod_folder_path = os.path.join(GlobalConfig.path_mods_folder(),"SSMTGeneratedMod\\")
            generate_mod_folder_path = os.path.join(ssmt_generated_mod_folder_path, cls.get_workspace_name() + "\\")
            if not os.path.exists(generate_mod_folder_path):
                os.makedirs(generate_mod_folder_path)
            return generate_mod_folder_path
    
    @staticmethod
    def path_extract_gametype_folder(draw_ib:str,gametype_name:str):
        return os.path.join(GlobalConfig.path_workspace_folder(), draw_ib + "\\TYPE_" + gametype_name + "\\")
    
    @staticmethod
    def path_generatemod_buffer_folder():
       
        buffer_folder_name = "Meshes"
        buffer_path = os.path.join(GlobalConfig.path_generate_mod_folder(), buffer_folder_name + "\\")
        if not os.path.exists(buffer_path):
            os.makedirs(buffer_path)
        return buffer_path
    
    @staticmethod
    def path_generatemod_texture_folder(draw_ib:str):

        texture_path = os.path.join(GlobalConfig.path_generate_mod_folder(),"Textures\\")
        if not os.path.exists(texture_path):
            os.makedirs(texture_path)
            print("GlobalConfig: Texture output folder created: " + texture_path + " (DrawIB: " + str(draw_ib) + ")")
        else:
            print("GlobalConfig: Using existing texture output folder: " + texture_path + " (DrawIB: " + str(draw_ib) + ")")
        return texture_path
    
    @staticmethod
    def path_appdata_local():
        return os.path.join(os.environ['LOCALAPPDATA'])
    
    @staticmethod
    def path_ssmt4_global_configs_folder():
        # SSMT5/ProjectBunny's settings.json now lives in ProjectBunnyGlobalConfigs.
        return GlobalConfig.path_project_bunny_global_configs_folder()

    # Define the base JSON file paths
    @staticmethod
    def path_main_json_ssmt4():
        legacy_ssmt4 = os.path.join(GlobalConfig.path_appdata_local(), "SSMT4GlobalConfigs\\")
        legacy_mmt = os.path.join(GlobalConfig.path_appdata_local(), "MMTGlobalConfigs\\")
        for folder, filename in (
            (GlobalConfig.path_project_bunny_global_configs_folder(), "settings.json"),
            (legacy_ssmt4, "settings.json"),
            (GlobalConfig.path_project_bunny_global_configs_folder(), "MMTSettings.json"),
            (legacy_mmt, "MMTSettings.json"),
            (GlobalConfig.path_mimitools_global_configs_folder(), "MIMIToolsSettings.json"),
        ):
            candidate = os.path.join(folder, filename)
            if os.path.exists(candidate):
                return candidate
        return os.path.join(GlobalConfig.path_project_bunny_global_configs_folder(), "settings.json")
