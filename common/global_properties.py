import bpy
import os


_blueprint_enum_items_cache = []


def _get_blueprint_enum_items(self, context):
    global _blueprint_enum_items_cache

    try:
        from ..blueprint.blueprint_export_helper import BlueprintExportHelper
        _blueprint_enum_items_cache = BlueprintExportHelper.get_blueprint_enum_items(context=context)
    except Exception:
        _blueprint_enum_items_cache = [
            ("__NONE__", "当前没有蓝图", "当前没有可选蓝图，请先打开蓝图界面或执行一键导入"),
        ]

    return _blueprint_enum_items_cache


def _get_workspace_enum_items(self, context):
    try:
        from .global_config import GlobalConfig

        GlobalConfig.read_from_main_json_ssmt4()
        workspace_root = GlobalConfig.path_current_game_total_workspace_folder()
        if not workspace_root or not os.path.isdir(workspace_root):
            return [("", "当前没有工作空间", "当前游戏配置下未找到可用工作空间")]

        workspace_names = sorted(
            [entry.name for entry in os.scandir(workspace_root) if entry.is_dir()]
        )
        if not workspace_names:
            return [("", "当前没有工作空间", "当前游戏配置下未找到可用工作空间")]

        return [(name, name, "") for name in workspace_names]
    except Exception:
        return [("", "当前没有工作空间", "当前游戏配置下未找到可用工作空间")]


def _disable_high_fidelity_when_normal_enabled(self, _context):
    if self.use_normal_map and self.gimi_high_fidelity_rendering:
        self.gimi_high_fidelity_rendering = False


def _disable_normal_when_high_fidelity_enabled(self, _context):
    if self.gimi_high_fidelity_rendering and self.use_normal_map:
        self.use_normal_map = False


class GlobalProperties(bpy.types.PropertyGroup):
    selected_blueprint_name: bpy.props.EnumProperty(
        name="当前蓝图",
        description="选择要打开或快捷生成 Mod 的蓝图",
        items=_get_blueprint_enum_items,
    ) # type: ignore

    open_mod_folder_after_generate_mod: bpy.props.BoolProperty(
        name="生成后打开Mod文件夹",
        description="勾选后，在生成Mod完成后自动打开Mod文件夹",
        default=True,
    ) # type: ignore

    zzz_use_slot_fix: bpy.props.BoolProperty(
        name="槽位风格贴图使用SlotFix技术",
        description="仅适用于槽位风格贴图，勾选后，特定名称标记的贴图将使用SlotFix风格，能一定程度上解决槽位风格贴图跨槽位的问题，跨Pixel槽位指的是在前一个DrawCall中是ps-t3但是下一个DrawCall变为ps-t5这种情况，但由于负责维护的人也在偷懒所以并不可靠",
        default=True,
    ) # type: ignore

    gimi_use_orfix: bpy.props.BoolProperty(
        name="槽位风格贴图使用ORFix",
        description="勾选后，在使用槽位风格贴图标记时，如果偷懒不想手动维护由于贴图槽位变化导致的贴图损坏问题，可以勾选此选项将问题交给ORFix维护者来解决，仅GIMI可用\n注意，如果你不懂ORFix和NNFix的原理，请不要取消勾选，取消勾选会严格按照贴图标记来执行贴图部分ini生成，默认你会在ini中自行写判断语句修复来替代实现ORFix和NNFix的功能",
        default=True,
    ) # type: ignore

    generate_branch_mod_gui: bpy.props.BoolProperty(
        name="生成分支切换Mod面板(测试版)",
        description="生成Mod时，生成一个基于当前集合架构的分支Mod面板，可在游戏中按住Ctrl + Alt呼出，仍在测试改进中",
        default=False,
    ) # type: ignore

    recalculate_tangent: bpy.props.BoolProperty(
        name="向量归一化法线存入TANGENT(全局)",
        description="使用向量相加归一化重计算所有模型的TANGENT值，勾选此项后无法精细控制具体某个模型是否计算，是偷懒选项,在不勾选时默认使用右键菜单中标记的选项。\n用途:\n1.一般用于修复GI角色,HI3 1.0角色,HSR角色轮廓线。\n2.用于修复模型由于TANGENT不正确导致的黑色色块儿问题，比如HSR的薄裙子可能会出现此问题。",
        default=False,
    ) # type: ignore

    recalculate_color: bpy.props.BoolProperty(
        name="算术平均归一化法线存入COLOR(全局)",
        description="使用算术平均归一化重计算所有模型的COLOR值，勾选此项后无法精细控制具体某个模型是否计算，是偷懒选项,在不勾选时默认使用右键菜单中标记的选项，仅用于HI3 2.0角色修复轮廓线",
        default=False,
    ) # type: ignore

    use_specific_generate_mod_folder_path: bpy.props.BoolProperty(
        name="生成Mod到指定的文件夹中",
        description="勾选后将生成Mod到你指定的文件夹中",
        default=False,
    ) # type: ignore

    generate_mod_folder_path: bpy.props.StringProperty(
        name="生成Mod文件夹路径",
        description="选择的生成Mod的文件夹路径",
        default="",
        subtype='DIR_PATH',
    ) # type: ignore

    workspace_source_mode: bpy.props.EnumProperty(
        name="工作空间模式",
        description="控制当前使用的工作空间来源",
        items=[
            ("SYNC", "同步SSMT侧选项", "使用 SSMT 配置文件中当前同步的工作空间"),
            ("SPECIFIC", "使用指定的工作空间", "从当前游戏配置下的工作空间列表中手动选择"),
            ("CUSTOM", "使用自定义目录", "直接使用你指定的工作空间目录"),
        ],
        default="SYNC",
    ) # type: ignore

    specific_workspace_name: bpy.props.EnumProperty(
        name="指定工作空间",
        description="当前游戏配置下可选的工作空间列表",
        items=_get_workspace_enum_items,
    ) # type: ignore

    custom_workspace_folder_path: bpy.props.StringProperty(
        name="自定义工作空间目录",
        description="手动指定工作空间目录路径",
        default="",
        subtype='DIR_PATH',
    ) # type: ignore

    use_mirror_workflow: bpy.props.BoolProperty(
        name="使用非镜像工作流",
        description="默认为False, 启用后导入和导出模型将不再是镜像的，目前3Dmigoto的模型导入后是镜像存粹是由于历史遗留问题是错误的，但是当错误积累成粑粑山，人的习惯和旧的工程很难被改变，所以只有勾选后才能使用非镜像工作流",
        default=False,
    ) # type: ignore

    use_normal_map: bpy.props.BoolProperty(
        name="自动上贴图时使用法线贴图",
        description="启用后在导入模型时自动附加法线贴图节点, 在材质预览模式下得到略微更好的视觉效果",
        default=False,
        update=_disable_high_fidelity_when_normal_enabled,
    ) # type: ignore

    gimi_high_fidelity_rendering: bpy.props.BoolProperty(
        name="原神高拟真渲染",
        description="仅 GIMI / GenshinImpact / 原神工作空间可用。启用后导入角色会使用 LightMap、Body Ramp、MatCap 与边缘光节点组构建预览材质",
        default=False,
        update=_disable_normal_when_high_fidelity_enabled,
    ) # type: ignore

    align_face_on_import: bpy.props.BoolProperty(
        name="矫正面部",
        description="导入时根据 SubMeshRole 的 Face/Neck 标记旋转并平移面部物体；只修改物体变换，不修改顶点",
        default=False,
    ) # type: ignore

    gimi_body_outline_enabled: bpy.props.BoolProperty(
        name="GIMI Body 黑色描边",
        description="高拟真 GIMI Body 导入时创建反向外壳黑色描边",
        default=True,
    ) # type: ignore

    gimi_body_outline_width_ratio: bpy.props.FloatProperty(
        name="GIMI 描边相对宽度",
        default=0.0008,
        min=0.00001,
        max=0.01,
        precision=6,
    ) # type: ignore

    import_merged_vgmap: bpy.props.EnumProperty(
        name="顶点组模式",
        description="Merged: 导入融合后的统一顶点组 (Unreal的合并顶点组技术会用到)，一般鸣潮Mod选这个来降低制作Mod的复杂度\nPerComponent: 按每个组件独立的顶点组导入\nUniComponent: Merged导入，导出时自动拆分回组件级顶点组",
        items=[
            ('MERGED', 'Merged', '导入融合后的统一顶点组，导出时使用ComputeShader运行时映射'),
            ('PER_COMPONENT', 'PerComponent', '按每个组件独立的顶点组导入'),
            ('UNICOMPONENT', 'UniComponent', 'Merged导入，导出时自动按Submesh拆分并还原为本地顶点组'),
        ],
        default='MERGED',
    ) # type: ignore

    ignore_muted_shape_keys: bpy.props.BoolProperty(
        name="忽略未启用的形态键",
        description="勾选此项后，未勾选启用的形态键在生成Mod时会被忽略，勾选的形态键会参与生成Mod",
        default=True,
    ) # type: ignore

    apply_all_modifiers: bpy.props.BoolProperty(
        name="应用所有修改器",
        description="勾选此项后，生成Mod之前会自动对物体应用所有修改器",
        default=False,
    ) # type: ignore

    import_skip_empty_vertex_groups: bpy.props.BoolProperty(
        name="跳过空顶点组",
        description="勾选此项后，导入时会跳过空的顶点组",
        default=True,
    ) # type: ignore

    export_add_missing_vertex_groups: bpy.props.BoolProperty(
        name="导出时添加缺失顶点组",
        description="勾选此项后，生成Mod时会自动重新排列并填补数字顶点组间的间隙空缺",
        default=True,
    ) # type: ignore

    @classmethod
    def _instance(cls):
        return bpy.context.scene.global_properties

    @classmethod
    def open_mod_folder_after_generate_mod(cls):
        return cls._instance().open_mod_folder_after_generate_mod

    @classmethod
    def zzz_use_slot_fix(cls):
        return cls._instance().zzz_use_slot_fix

    @classmethod
    def gimi_use_orfix(cls):
        return cls._instance().gimi_use_orfix

    @classmethod
    def forbid_auto_texture_ini(cls) -> bool:
        """旧自动贴图流程已移除，保留该方法仅作兼容性垫片，始终返回 False。"""
        return False

    @classmethod
    def generate_branch_mod_gui(cls):
        try:
            from ..blueprint.blueprint_export_helper import BlueprintExportHelper
            return BlueprintExportHelper.has_mod_panel_node()
        except Exception:
            return False

    @classmethod
    def generate_branch_mod_gui_flow_effect(cls):
        try:
            from ..blueprint.blueprint_export_helper import BlueprintExportHelper
            return BlueprintExportHelper.is_mod_panel_flow_effect_enabled()
        except Exception:
            return False

    @classmethod
    def recalculate_tangent(cls):
        return cls._instance().recalculate_tangent

    @classmethod
    def recalculate_color(cls):
        return cls._instance().recalculate_color

    @classmethod
    def use_specific_generate_mod_folder_path(cls):
        return cls._instance().use_specific_generate_mod_folder_path

    @classmethod
    def generate_mod_folder_path(cls):
        return cls._instance().generate_mod_folder_path

    @classmethod
    def use_mirror_workflow(cls):
        return cls._instance().use_mirror_workflow

    @classmethod
    def workspace_source_mode(cls):
        return cls._instance().workspace_source_mode

    @classmethod
    def specific_workspace_name(cls):
        return cls._instance().specific_workspace_name

    @classmethod
    def custom_workspace_folder_path(cls):
        return cls._instance().custom_workspace_folder_path

    @classmethod
    def use_normal_map(cls):
        return cls._instance().use_normal_map

    @classmethod
    def gimi_high_fidelity_rendering(cls):
        return cls._instance().gimi_high_fidelity_rendering

    @classmethod
    def align_face_on_import(cls):
        return cls._instance().align_face_on_import

    @classmethod
    def gimi_body_outline_enabled(cls):
        return cls._instance().gimi_body_outline_enabled

    @classmethod
    def gimi_body_outline_width_ratio(cls):
        return cls._instance().gimi_body_outline_width_ratio

    @classmethod
    def import_merged_vgmap(cls) -> str:
        """返回 'MERGED' / 'PER_COMPONENT' / 'UNICOMPONENT'"""
        return cls._instance().import_merged_vgmap

    @classmethod
    def is_unico_component(cls) -> bool:
        return cls._instance().import_merged_vgmap == 'UNICOMPONENT'

    @classmethod
    def is_merged_mode(cls) -> bool:
        """MERGED 或 UNICOMPONENT 在导入时都使用 VGMap 合并"""
        return cls._instance().import_merged_vgmap in ('MERGED', 'UNICOMPONENT')

    @classmethod
    def ignore_muted_shape_keys(cls):
        return cls._instance().ignore_muted_shape_keys

    @classmethod
    def apply_all_modifiers(cls):
        return cls._instance().apply_all_modifiers

    @classmethod
    def import_skip_empty_vertex_groups(cls):
        return cls._instance().import_skip_empty_vertex_groups

    @classmethod
    def export_add_missing_vertex_groups(cls):
        return cls._instance().export_add_missing_vertex_groups

    @classmethod
    def selected_blueprint_name(cls):
        return cls._instance().selected_blueprint_name


def register():
    try:
        bpy.utils.register_class(GlobalProperties)
    except ValueError:
        pass
    if not hasattr(bpy.types.Scene, "global_properties"):
        bpy.types.Scene.global_properties = bpy.props.PointerProperty(type=GlobalProperties)


def unregister():
    if hasattr(bpy.types.Scene, "global_properties"):
        del bpy.types.Scene.global_properties
    try:
        bpy.utils.unregister_class(GlobalProperties)
    except (ValueError, RuntimeError):
        pass
