'''
Basic Information Panel
'''
import bpy

from ..common.global_config import GlobalConfig
from ..common.global_config import LogicName
from ..blueprint.blueprint_export_helper import BlueprintExportHelper
from ..i18n.i18n import I18nOperator, tr, translatable, get_preferences

from .ui_func_export import SSMTGenerateSelectedBlueprintMod
from .ui_func_import_ssmt import SSMT4ImportAllFromCurrentWorkSpaceBlueprint, SSMT4ImportRaw


class SSMT4RefreshWorkspaceList(I18nOperator):
    bl_idname = "mimi.refresh_workspace_list"
    bl_label = "Refresh Workspace List"
    bl_description = "Refresh the workspace list of the current game configuration"

    def execute(self, context):
        GlobalConfig.read_from_main_json_ssmt4()

        for window in context.window_manager.windows:
            for area in window.screen.areas:
                area.tag_redraw()

        self.report({'INFO'}, tr("Workspace list refreshed"))
        return {'FINISHED'}


@translatable
class MIMIPanelBasicInformation(bpy.types.Panel):
    '''
    Basic Information Panel
    This panel refreshes in real time and reads the paths from the global configuration file.
    '''
    bl_label = "Basic Information Panel"
    bl_idname = "MIMI_PT_catter_buttons"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'MIMITools'

    def draw(self, context):
        layout = self.layout
        mimi_global_properties = context.scene.mimi_global_properties

        # UI language switch: offered at the top of the first panel so users
        # can always find it. The choice is stored in the add-on preferences.
        prefs = get_preferences()
        if prefs is not None:
            layout.prop(prefs, "ui_language", expand=True)
        
        GlobalConfig.read_from_main_json_ssmt4()

        preferred_blueprint_name = BlueprintExportHelper.get_preferred_blueprint_name(
            selected_name=getattr(mimi_global_properties, "selected_blueprint_name", ""),
            context=context,
        )
        # Blender 5.2 forbids writing Scene/ID properties from Panel.draw().
        # Keep drawing read-only and use the computed preferred name for the
        # action buttons below. Operators/import callbacks remain responsible
        # for persisting an explicit selection.

        layout.label(text=tr("SSMT Cache Folder: ") + GlobalConfig.ssmtlocation)
        layout.label(text=tr("Current Config Name: ") + GlobalConfig.gamename)
        layout.label(text=tr("Current Game Preset: ") + GlobalConfig.logic_name)
        layout.label(text=tr("Current Workspace: ") + GlobalConfig.get_workspace_name())

        layout.prop(mimi_global_properties, "workspace_source_mode", text=tr("Workspace Mode"))
        if mimi_global_properties.workspace_source_mode == "SPECIFIC":
            workspace_row = layout.row(align=True)
            workspace_row.prop(mimi_global_properties, "specific_workspace_name", text=tr("Specified Workspace"))
            workspace_row.operator(SSMT4RefreshWorkspaceList.bl_idname, text="", icon='FILE_REFRESH')
        elif mimi_global_properties.workspace_source_mode == "CUSTOM":
            layout.prop(mimi_global_properties, "custom_workspace_folder_path", text=tr("Custom Folder"))

        # layout.prop(mimi_global_properties,"use_mirror_workflow")
        
        if len(context.selected_objects) != 0:
            obj = context.selected_objects[0]

            # Read the custom properties
            gametypename = obj.get("3DMigoto:GameTypeName", "")
            recalculate_tangent = obj.get("3DMigoto:RecalculateTANGENT", False)
            recalculate_color = obj.get("3DMigoto:RecalculateCOLOR", False)

            row = layout.row(align=True)
            row.label(text=tr("Data Type: ") + gametypename)
            row.operator("mimi.fix_drawib_datatype", text="", icon='TOOL_SETTINGS', emboss=False)
            row.operator("mimi.fix_submesh_datatype", text="", icon='TOOL_SETTINGS', emboss=False)
            layout.label(text=tr("Recalculate TANGENT: ") + str(recalculate_tangent))
            layout.label(text=tr("Recalculate COLOR: ") + str(recalculate_color))

        # Manually import an SSMT model
        layout.operator(SSMT4ImportRaw.bl_idname, text=tr(SSMT4ImportRaw.bl_label), icon='IMPORT')
        # One-click import of the current SSMT workspace contents
        layout.operator(SSMT4ImportAllFromCurrentWorkSpaceBlueprint.bl_idname, text=tr(SSMT4ImportAllFromCurrentWorkSpaceBlueprint.bl_label), icon='IMPORT')
        
        # SSMT blueprint dropdown list
        blueprint_row = layout.row(align=True)
        blueprint_row.prop(mimi_global_properties, "selected_blueprint_name", text=tr("SSMT Blueprint"))

        rename_blueprint_operator = blueprint_row.operator(
            "mimi.rename_persistent_blueprint",
            text="",
            icon='GREASEPENCIL',
        )
        rename_blueprint_operator.blueprint_name = preferred_blueprint_name or mimi_global_properties.selected_blueprint_name

        delete_blueprint_operator = blueprint_row.operator(
            "mimi.delete_persistent_blueprint",
            text="",
            icon='TRASH',
        )
        delete_blueprint_operator.blueprint_name = preferred_blueprint_name or mimi_global_properties.selected_blueprint_name

        open_blueprint_operator = blueprint_row.operator(
            "mimi.open_persistent_blueprint",
            text="",
            icon='NODETREE',
        )
        open_blueprint_operator.blueprint_name = preferred_blueprint_name

        # Quick Generate Mod button, to avoid opening the blueprint editor for it
        quick_generate_row = layout.row()
        quick_generate_row.operator(SSMTGenerateSelectedBlueprintMod.bl_idname, text=tr("Generate Mod"), icon='EXPORT')



        if GlobalConfig.logic_name == LogicName.WWMI:
            layout.prop(mimi_global_properties,"import_merged_vgmap", text=tr("Vertex Group Mode"))

        if GlobalConfig.logic_name == LogicName.WWMI or GlobalConfig.logic_name == LogicName.NTEMI:
            layout.prop(mimi_global_properties,"import_skip_empty_vertex_groups", text=tr("Skip Empty Vertex Groups"))

        if GlobalConfig.logic_name == LogicName.GIMI or str(GlobalConfig.gamename).strip().casefold() in {
            "gimi", "genshinimpact",
        }:
            layout.prop(mimi_global_properties, "align_face_on_import", text=tr("Align Face"))
            layout.prop(mimi_global_properties, "gimi_high_fidelity_rendering", text=tr("Genshin High-Fidelity Rendering"))
            if mimi_global_properties.gimi_high_fidelity_rendering:
                outline = layout.column(align=True)
                outline.prop(mimi_global_properties, "gimi_body_outline_enabled", text=tr("GIMI Body Black Outline"))
                outline.prop(mimi_global_properties, "gimi_body_outline_width_ratio", text=tr("GIMI Outline Relative Width"))
                row = outline.row(align=True)
                row.operator("mimi.build_gimi_body_outline", text=tr("Build GIMI Body Outline"), icon='MOD_SOLIDIFY')
                row.operator("mimi.remove_gimi_body_outline", text="", icon='X')




def register():
    bpy.utils.register_class(SSMT4RefreshWorkspaceList)
    bpy.utils.register_class(MIMIPanelBasicInformation)

def unregister():
    bpy.utils.unregister_class(SSMT4RefreshWorkspaceList)
    bpy.utils.unregister_class(MIMIPanelBasicInformation)
