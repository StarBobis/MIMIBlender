import bpy
import os
import json


from .global_properties import GlobalProperties


'''
执行逻辑名称
在SSMT3系列中，任意游戏可以配置任意执行逻辑，根据执行逻辑决定具体游戏流程
在SSMT4系列中，为了简化流程，降低维护成本，每个游戏都对应一个LogicName
或者说LogicName字段本身就是和SSMT4端的GamePreset游戏预设字段一一对应

另外，不管在数据类型上理解有多么深刻，当大部分用户选择使用错误的数据类型，并形成习惯时
例如WWMI的COLOR1还是TEXCOORD问题，此时为了降低维护成本，应该尊重大众的选择
毕竟这个世界大部分都是普通人，普通人是不想思考的，越简单越好。
也可以理解为一个概念若是被大部分人误解了，那么这个概念的正确理解就不重要了，
重要的是这个概念被大部分人误解成什么样了。
SSMT的本质是什么不重要，重要的是在大部分人眼中SSMT是什么。
'''
class LogicName:
    # 高人气游戏，常驻维护
    GIMI = "GIMI"
    HIMI = "HIMI"
    SRMI = "SRMI"
    ZZMI = "ZZMI"
    ZZMIDX12 = "ZZMIDX12"
    WWMI = "WWMI"
    EFMI = "EFMI"

    # 小众游戏，使用人数极少，有用户反馈时进行维护即可
    # 注意，如果一个游戏有原生Mod方式，就不应该使用3Dmigoto来进行Mod制作
    # 与主流相悖的路线只会导致维护成本过高，最终被世人遗忘
    # 如果只给少数部分人提供服务的话，就必须要考虑维护成本问题
    GF2 = "GF2" # 少女前线2，或者CPU-PreSkinning类型游戏，使用3Dmigoto强行修改的代表性方法
    IdentityV = "IdentityV" # 第五人格Neox3引擎，目前留着也只是为部分抽象二创视频作者提供服务
    AILIMIT = "AILIMIT" # 小厂小游戏，但是虹汐哥还在开设粉丝群，暂且给他的粉丝群留着
    DOAV = "DOAV" # 古董游戏，万恶之源，就算添加了又有什么用呢，留着只是致敬
    SnowBreak = "SnowBreak" # 尘白禁区已经有原生Mod方式了，但是呢，万一哪天失效了，3Dmigoto将成为备选
    YYSLS = "YYSLS" # 燕云十六声，花费巨大宣发经费，但玩的人还是很少
    Naraka = "Naraka" # 使用Mod会掉帧/封禁帐号30天/封禁永久
    NarakaM = "NarakaM" # 使用Mod会掉帧/封禁帐号30天/封禁永久
    
    NTEMI = "NTEMI" # 异环，仅测试
    
    # 预留位置
    APMI = "APMI" # 还在内测的蓝色星原，已在测试服中测试过，完美支持3Dmigoto，预计发布就会被XXMI收录
    NEMI = "NEMI" # 还在内测的异环，已在测试服中测试过，完美支持3Dmigoto，预计发布就会被XXMI收录

    @classmethod
    def is_zzmi_family(cls, logic_name: str) -> bool:
        return logic_name in {cls.ZZMI, cls.ZZMIDX12}


# 全局配置类，使用字段默认为全局可访问的唯一静态变量的特性，来实现全局变量
class GlobalConfig:
    # 全局静态变量,任何地方访问到的值都是唯一的
    gamename = ""
    workspacename = ""
    ssmtlocation = ""
    current_game_migoto_folder = ""
    logic_name = ""

    '''
    在新版的生成Mod架构中用于统计一个Mod中全局的按键索引
    以及当前生成Mod的数量，每个DrawIB都是一个Mod。
    使用全局变量来避免过于复杂的变量传递。
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
            # SSMT4 panel must read SSMT tool's own settings only,
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
            # SSMT writes its cache folder path under the legacy key
            # "DBMTWorkFolder" in SSMT4GlobalConfigs/settings.json.
            # When the key is empty, SSMT uses the default SSMT4CachedFolder.
            ssmt_work_folder = str(main_settings.get("DBMTWorkFolder", "") or "").strip()
            if not ssmt_work_folder:
                ssmt_work_folder = os.path.join(
                    GlobalConfig.path_appdata_local(), "SSMT4CachedFolder"
                )
            cls.ssmtlocation = ssmt_work_folder + "\\"

            # SSMT4 panel only trusts the game config written by SSMT itself,
            # MMT / MIMITools game configs must not leak into this panel.
            game_config_json_path = ""
            candidate = os.path.join(
                GlobalConfig.path_ssmt4_global_configs_folder(),
                "Games", cls.gamename, "Config.json"
            )
            if os.path.exists(candidate):
                game_config_json_path = candidate

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
        当前工作空间目录下的Config.json
        存储了所有的DrawIB和别名
        '''
        game_config_json_path = os.path.join(GlobalConfig.path_workspace_folder(),"Config.json")
        return game_config_json_path
    
    @staticmethod
    def path_configs_folder():
        return os.path.join(GlobalConfig.base_path(),"Configs\\")
    
    @staticmethod
    def path_reverse_output_folder():
        # Reverse output belongs to the MMT toolchain, read MMT settings first.
        settings = GlobalConfig._mmt_family_settings()
        reverse_output_folder = str(settings.get("ReverseOutputFolder", "") or "").strip()
        if reverse_output_folder:
            return reverse_output_folder
        return ""

    @staticmethod
    def reverse_output_format():
        # Reverse output format is written by the MMT toolchain on reverse success,
        # symmetric to ReverseOutputFolder. Values: ib_vb_fmt / ssmt_fmt.
        # When the key is missing, treat the output as the legacy ib_vb_fmt format.
        settings = GlobalConfig._mmt_family_settings()
        reverse_output_format = str(settings.get("ReverseOutputFormat", "") or "").strip()
        if reverse_output_format:
            return reverse_output_format
        return "ib_vb_fmt"

    @staticmethod
    def path_mimitools_settings_json():
        return os.path.join(GlobalConfig.path_appdata_local(), "MIMIToolsGlobalConfigs", "MIMIToolsSettings.json")

    @staticmethod
    def path_mmt_settings_json():
        return os.path.join(GlobalConfig.path_appdata_local(), "MMTGlobalConfigs", "MMTSettings.json")

    @staticmethod
    def path_mmt_global_configs_folder():
        return os.path.join(GlobalConfig.path_appdata_local(), "MMTGlobalConfigs\\")

    @staticmethod
    def path_mimitools_global_configs_folder():
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
        # Read SSMT tool's own settings file only, no cross-tool fallback.
        return GlobalConfig._load_json_dict(
            os.path.join(GlobalConfig.path_ssmt4_global_configs_folder(), "settings.json")
        )

    @staticmethod
    def _mmt_settings():
        # Read MMT tool's own settings file only, no cross-tool fallback.
        return GlobalConfig._load_json_dict(GlobalConfig.path_mmt_settings_json())

    @staticmethod
    def _mimitools_settings():
        # Read MIMITools settings file only, no cross-tool fallback.
        return GlobalConfig._load_json_dict(GlobalConfig.path_mimitools_settings_json())

    @staticmethod
    def _mmt_family_settings():
        # The reverse toolchain is shared by MMT and MIMITools.
        # MMT has higher priority, SSMT settings must never be read here.
        settings = GlobalConfig._mmt_settings()
        if not settings:
            settings = GlobalConfig._mimitools_settings()
        return settings

    @staticmethod
    def path_mimitools_reversed_root():
        # Sword4 panel reads the MMT toolchain only, SSMT is never involved.
        settings = GlobalConfig._mmt_family_settings()
        work_folder = str(settings.get("DBMTWorkFolder", "") or "").strip()
        if work_folder:
            return os.path.join(work_folder, "Reversed")
        # Only MMT / MIMITools cache folders are valid here,
        # SSMT4CachedFolder must not be used by Sword4 panel.
        for cache_folder_name in ("MMTCachedFolder", "MIMIToolsCachedFolder"):
            candidate = os.path.join(GlobalConfig.path_appdata_local(), cache_folder_name, "Reversed")
            if os.path.isdir(candidate):
                return candidate
        return ""

    @staticmethod
    def path_mimitools_reverse_output_folder():
        # Reverse output folder is stored by the MMT toolchain only.
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
    def path_mods_folder(cls):
        return os.path.join(cls.current_game_migoto_folder,"Mods\\") 

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
        # 如果用户勾选了使用指定文件夹，那就返回指定文件夹位置，否则返回我们的默认位置。
        # 但是这里有个问题就是SkipIB和VSCheck不会生成在指定位置。
        if GlobalProperties.use_specific_generate_mod_folder_path():
            return GlobalProperties.generate_mod_folder_path()
        else:
            # 确保用的时候直接拿到的就是已经存在的目录
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
            print("GlobalConfig: 已创建贴图输出目录: " + texture_path + " (DrawIB: " + str(draw_ib) + ")")
        else:
            print("GlobalConfig: 使用已有贴图输出目录: " + texture_path + " (DrawIB: " + str(draw_ib) + ")")
        return texture_path
    
    @staticmethod
    def path_appdata_local():
        return os.path.join(os.environ['LOCALAPPDATA'])
    
    @staticmethod
    def path_ssmt4_global_configs_folder():
        return os.path.join(GlobalConfig.path_appdata_local(),"SSMT4GlobalConfigs\\")

    # 定义基础的Json文件路径
    @staticmethod
    def path_main_json_ssmt4():
        for folder, filename in (
            (GlobalConfig.path_ssmt4_global_configs_folder(), "settings.json"),
            (GlobalConfig.path_mmt_global_configs_folder(), "MMTSettings.json"),
            (GlobalConfig.path_mimitools_global_configs_folder(), "MIMIToolsSettings.json"),
        ):
            candidate = os.path.join(folder, filename)
            if os.path.exists(candidate):
                return candidate
        return os.path.join(GlobalConfig.path_ssmt4_global_configs_folder(), "settings.json")
