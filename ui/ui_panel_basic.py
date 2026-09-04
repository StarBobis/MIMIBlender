'''
基础信息面板
'''
import bpy

from ..common.global_config import GlobalConfig
from ..common.global_config import LogicName
from ..blueprint.blueprint_export_helper import BlueprintExportHelper

from ..utils.translate_utils import iface_

from .ui_func_export import SSMTGenerateSelectedBlueprintMod
from .ui_func_import_ssmt import SSMT4ImportAllFromCurrentWorkSpaceBlueprint, SSMT4ImportRaw


class SSMT4RefreshWorkspaceList(bpy.types.Operator):
    bl_idname = "ssmt4.refresh_workspace_list"
    bl_label = "刷新工作空间列表"
    bl_description = "刷新当前游戏配置下的工作空间列表"

    def execute(self, context):
        GlobalConfig.read_from_main_json_ssmt4()

        for window in context.window_manager.windows:
            for area in window.screen.areas:
                area.tag_redraw()

        self.report({'INFO'}, iface_("已刷新工作空间列表"))
        return {'FINISHED'}


class PanelBasicInformation(bpy.types.Panel):
    '''
    基础信息面板
    此面板实时刷新并读取全局配置文件中的路径
    '''
    bl_label = "基础信息面板"
    bl_idname = "VIEW3D_PT_CATTER_Buttons_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'TheHerta4'

    def draw(self, context):
        layout = self.layout
        global_properties = context.scene.global_properties
        
        GlobalConfig.read_from_main_json_ssmt4()

        preferred_blueprint_name = BlueprintExportHelper.get_preferred_blueprint_name(
            selected_name=getattr(global_properties, "selected_blueprint_name", ""),
            context=context,
        )
        # Blender 5.2 forbids writing Scene/ID properties from Panel.draw().
        # Keep drawing read-only and use the computed preferred name for the
        # action buttons below. Operators/import callbacks remain responsible
        # for persisting an explicit selection.

        layout.label(text=iface_("SSMT缓存文件夹路径: ") + GlobalConfig.ssmtlocation)
        layout.label(text=iface_("当前配置名称: ") + GlobalConfig.gamename)
        layout.label(text=iface_("当前游戏预设: ") + GlobalConfig.logic_name)
        layout.label(text=iface_("当前工作空间: ") + GlobalConfig.get_workspace_name())

        layout.prop(global_properties, "workspace_source_mode")
        if global_properties.workspace_source_mode == "SPECIFIC":
            workspace_row = layout.row(align=True)
            workspace_row.prop(global_properties, "specific_workspace_name", text=iface_("指定工作空间"))
            workspace_row.operator(SSMT4RefreshWorkspaceList.bl_idname, text="", icon='FILE_REFRESH')
        elif global_properties.workspace_source_mode == "CUSTOM":
            layout.prop(global_properties, "custom_workspace_folder_path", text=iface_("自定义目录"))

        # layout.prop(global_properties,"use_mirror_workflow")
        
        if len(context.selected_objects) != 0:
            obj = context.selected_objects[0]

            # 获取自定义属性
            gametypename = obj.get("3DMigoto:GameTypeName", "")
            recalculate_tangent = obj.get("3DMigoto:RecalculateTANGENT", False)
            recalculate_color = obj.get("3DMigoto:RecalculateCOLOR", False)

            row = layout.row(align=True)
            row.label(text=iface_("数据类型: ") + gametypename)
            row.operator("ssmt4.fix_drawib_datatype", text="", icon='TOOL_SETTINGS', emboss=False)
            row.operator("ssmt4.fix_submesh_datatype", text="", icon='TOOL_SETTINGS', emboss=False)
            layout.label(text=iface_("重计算TANGENT: ") + str(recalculate_tangent))
            layout.label(text=iface_("重计算COLOR: ") + str(recalculate_color))

        # 手动导入SSMT格式模型
        layout.operator(SSMT4ImportRaw.bl_idname,icon='IMPORT')
        # 一键导入当前SSMT工作空间内容
        layout.operator(SSMT4ImportAllFromCurrentWorkSpaceBlueprint.bl_idname,icon='IMPORT')
        
        # SSMT蓝图下拉列表
        blueprint_row = layout.row(align=True)
        blueprint_row.prop(global_properties, "selected_blueprint_name", text=iface_("SSMT蓝图"))

        rename_blueprint_operator = blueprint_row.operator(
            "theherta3.rename_persistent_blueprint",
            text="",
            icon='GREASEPENCIL',
        )
        rename_blueprint_operator.blueprint_name = preferred_blueprint_name or global_properties.selected_blueprint_name

        delete_blueprint_operator = blueprint_row.operator(
            "theherta3.delete_persistent_blueprint",
            text="",
            icon='TRASH',
        )
        delete_blueprint_operator.blueprint_name = preferred_blueprint_name or global_properties.selected_blueprint_name

        open_blueprint_operator = blueprint_row.operator(
            "theherta3.open_persistent_blueprint",
            text="",
            icon='NODETREE',
        )
        open_blueprint_operator.blueprint_name = preferred_blueprint_name

        # 快速生成Mod按钮，省的去蓝图里点击了
        quick_generate_row = layout.row()
        quick_generate_row.operator(SSMTGenerateSelectedBlueprintMod.bl_idname, text=iface_("生成Mod"), icon='EXPORT')



        if GlobalConfig.logic_name == LogicName.WWMI:
            layout.prop(global_properties,"import_merged_vgmap")

        if GlobalConfig.logic_name == LogicName.WWMI or GlobalConfig.logic_name == LogicName.NTEMI:
            layout.prop(global_properties,"import_skip_empty_vertex_groups")

        # 决定导入时是否调用法线贴图
        layout.prop(global_properties, "use_normal_map")

        if GlobalConfig.logic_name == LogicName.GIMI or str(GlobalConfig.gamename).strip().casefold() in {
            "gimi", "genshinimpact", "原神",
        }:
            layout.prop(global_properties, "align_face_on_import")
            layout.prop(global_properties, "gimi_high_fidelity_rendering")
            if global_properties.gimi_high_fidelity_rendering:
                outline = layout.column(align=True)
                outline.prop(global_properties, "gimi_body_outline_enabled")
                outline.prop(global_properties, "gimi_body_outline_width_ratio")
                row = outline.row(align=True)
                row.operator("ssmt.build_gimi_body_outline", icon='MOD_SOLIDIFY')
                row.operator("ssmt.remove_gimi_body_outline", text="", icon='X')




def register():
    bpy.utils.register_class(SSMT4RefreshWorkspaceList)
    bpy.utils.register_class(PanelBasicInformation)

def unregister():
    bpy.utils.unregister_class(SSMT4RefreshWorkspaceList)
    bpy.utils.unregister_class(PanelBasicInformation)
