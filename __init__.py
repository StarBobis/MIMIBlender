import bpy


from .common import global_properties
from .common import gimi_body_outline
from .utils import translate_utils


# UI界面
from .ui import ui_panel_basic
from .ui import ui_panel_model
from .sword import ui_panel_sword
from .ui import ui_func_import_ssmt
from .ui import ui_panel_fast_texture

from .blueprint import blueprint_node_obj
from .blueprint import blueprint_node_base
from .blueprint import blueprint_node_menu
from .blueprint import blueprint_node_shapekey
from .blueprint import blueprint_node_panel

from .blueprint import blueprint_node_texture
from .blueprint import blueprint_node_custom_shader
from .blueprint import blueprint_node_face_mod
from .blueprint import blueprint_node_group
from .blueprint import blueprint_file_drop
from .blueprint import blueprint_node_highlight

from .ui import ui_func_export

# 自动更新功能
from . import addon_updater_ops

# 贴图合并工具 (texcomb) - 从另一个插件集成过来的材质合并功能
from . import texcomb

# 开发时确保同时自动更新 addon_updater_ops
import importlib
importlib.reload(addon_updater_ops)

bl_info = {
    "name": "TheHerta4",
    "description": "Blender Plugin of SSMT4",
    "blender": (5, 2, 0),
    "version": (4, 1, 49),
    "location": "View3D",
    "category": "Generic"
}


class UpdaterPanel(bpy.types.Panel):
    """Update Panel"""
    bl_label = "检查版本更新"
    bl_idname = "HERTA_PT_UpdaterPanel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_context = "objectmode"
    bl_category = "TheHerta4"
    bl_order = 99
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        
        # Call to check for update in background.
        # Note: built-in checks ensure it runs at most once, and will run in
        # the background thread, not blocking or hanging blender.
        # Internally also checks to see if auto-check enabled and if the time
        # interval has passed.
        # addon_updater_ops.check_for_update_background()
        col = layout.column()
        col.scale_y = 0.7
        # Could also use your own custom drawing based on shared variables.
        if addon_updater_ops.updater.update_ready:
            layout.label(text="存在可用更新！", icon="INFO")

        # Call built-in function with draw code/checks.
        # addon_updater_ops.update_notice_box_ui(self, context)
        addon_updater_ops.update_settings_ui(self, context)


class HertaUpdatePreference(bpy.types.AddonPreferences):
    # Addon updater preferences.
    bl_label = "TheHerta 更新器"
    bl_idname = __package__

    
    auto_check_update: bpy.props.BoolProperty(
        name="自动检查更新",
        description="如启用，按设定的时间间隔自动检查更新",
        default=True) # type: ignore

    updater_interval_months: bpy.props.IntProperty(
        name='月',
        description="自动检查更新间隔月数",
        default=0,
        min=0) # type: ignore

    updater_interval_days: bpy.props.IntProperty(
        name='天',
        description="自动检查更新间隔天数",
        default=1,
        min=0,
        max=31) # type: ignore

    updater_interval_hours: bpy.props.IntProperty(
        name='小时',
        description="自动检查更新间隔小时数",
        default=0,
        min=0,
        max=23) # type: ignore

    updater_interval_minutes: bpy.props.IntProperty(
        name='分钟',
        description="自动检查更新间隔分钟数",
        default=0,
        min=0,
        max=59) # type: ignore
    def draw(self, context):
        layout = self.layout
        layout.prop(self, "auto_check_update")
        addon_updater_ops.update_settings_ui(self, context)

def register():
    # 逐模块容错注册：历史上曾出现单个节点类注册失败导致 register 中断、
    # 侧栏面板全部丢失的问题；这里保证一个模块失败不影响其它模块，
    # 失败信息打印到控制台便于排查。
    for step in _register_steps():
        try:
            step()
        except Exception:
            import traceback
            print(f"[TheHerta4] register step failed: {getattr(step, '__module__', step)}")
            traceback.print_exc()


def _register_steps():
    # 1. Configs
    yield global_properties.register
    yield gimi_body_outline.register
    yield translate_utils.register

    # 2. Addon Updater (local classes)
    def _register_updater():
        addon_updater_ops.register(bl_info)
        bpy.utils.register_class(UpdaterPanel)
        bpy.utils.register_class(HertaUpdatePreference)
    yield _register_updater

    # 3. UI Panels & Logic
    yield blueprint_node_base.register
    yield blueprint_node_group.register
    yield ui_panel_basic.register
    yield ui_panel_model.register
    yield ui_panel_sword.register
    yield ui_func_import_ssmt.register
    yield ui_panel_fast_texture.register

    # 蓝图系统
    # ShapeKey PropertyGroup 必须先于引用它的 Generate Mod 节点注册。
    yield blueprint_node_shapekey.register
    yield blueprint_node_obj.register
    yield ui_func_export.register
    yield blueprint_node_menu.register
    yield blueprint_node_panel.register

    yield blueprint_node_texture.register
    yield blueprint_node_custom_shader.register
    yield blueprint_node_face_mod.register
    yield blueprint_file_drop.register
    yield blueprint_node_highlight.register

    # 贴图合并工具 (texcomb)
    yield texcomb.register


def unregister():
    # 按 register 的逆序注销，避免类型依赖问题
    # 逐步容错：之前会话可能处于半注册状态（例如某类从未注册成功），
    # 直接注销会抛 RuntimeError 并中断后续所有注销，导致下次启用时
    # “already registered” 连锁失败、面板消失。
    def _unregister_updater():
        bpy.utils.unregister_class(HertaUpdatePreference)
        bpy.utils.unregister_class(UpdaterPanel)
        addon_updater_ops.unregister()

    steps = [
        gimi_body_outline.unregister,
        texcomb.unregister,
        blueprint_node_highlight.unregister,
        blueprint_file_drop.unregister,
        blueprint_node_face_mod.unregister,
        blueprint_node_group.unregister,
        blueprint_node_custom_shader.unregister,
        blueprint_node_texture.unregister,
        blueprint_node_panel.unregister,
        blueprint_node_menu.unregister,
        ui_func_export.unregister,
        blueprint_node_obj.unregister,
        blueprint_node_shapekey.unregister,
        ui_panel_fast_texture.unregister,
        ui_func_import_ssmt.unregister,
        ui_panel_sword.unregister,
        ui_panel_model.unregister,
        ui_panel_basic.unregister,
        blueprint_node_base.unregister,
        _unregister_updater,
        translate_utils.unregister,
        global_properties.unregister,
    ]
    for step in steps:
        try:
            step()
        except Exception:
            import traceback
            print(f"[TheHerta4] unregister step failed: {getattr(step, '__module__', step)}")
            traceback.print_exc()




