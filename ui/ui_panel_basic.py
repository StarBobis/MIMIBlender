'''
Basic Information Panel
'''
import bpy

from ..common.global_config import GlobalConfig
from ..common.global_config import LogicName
from ..blueprint.blueprint_export_helper import BlueprintExportHelper

from .ui_func_export import SSMTGenerateSelectedBlueprintMod
from .ui_func_import_ssmt import SSMT4ImportAllFromCurrentWorkSpaceBlueprint, SSMT4ImportRaw


class SSMT4RefreshWorkspaceList(bpy.types.Operator):
    bl_idname = "ssmt4.refresh_workspace_list"
    bl_label = "Refresh Workspace List"
    bl_description = "Refresh the workspace list of the current game configuration"

    def execute(self, context):
        GlobalConfig.read_from_main_json_ssmt4()

        for window in context.window_manager.windows:
            for area in window.screen.areas:
                area.tag_redraw()

        self.report({'INFO'}, "Workspace list refreshed")
        return {'FINISHED'}


class PanelBasicInformation(bpy.types.Panel):
    '''
    Basic Information Panel
    This panel refreshes in real time and reads the paths from the global configuration file.
    '''
    bl_label = "Basic Information Panel"
    bl_idname = "VIEW3D_PT_CATTER_Buttons_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'MIMITools'

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

        layout.label(text="SSMT Cache Folder: " + GlobalConfig.ssmtlocation)
        layout.label(text="Current Config Name: " + GlobalConfig.gamename)
        layout.label(text="Current Game Preset: " + GlobalConfig.logic_name)
        layout.label(text="Current Workspace: " + GlobalConfig.get_workspace_name())

        layout.prop(global_properties, "workspace_source_mode")
        if global_properties.workspace_source_mode == "SPECIFIC":
            workspace_row = layout.row(align=True)
            workspace_row.prop(global_properties, "specific_workspace_name", text="Specified Workspace")
            workspace_row.operator(SSMT4RefreshWorkspaceList.bl_idname, text="", icon='FILE_REFRESH')
        elif global_properties.workspace_source_mode == "CUSTOM":
            layout.prop(global_properties, "custom_workspace_folder_path", text="Custom Folder")

        # layout.prop(global_properties,"use_mirror_workflow")
        
        if len(context.selected_objects) != 0:
            obj = context.selected_objects[0]

            # Read the custom properties
            gametypename = obj.get("3DMigoto:GameTypeName", "")
            recalculate_tangent = obj.get("3DMigoto:RecalculateTANGENT", False)
            recalculate_color = obj.get("3DMigoto:RecalculateCOLOR", False)

            row = layout.row(align=True)
            row.label(text="Data Type: " + gametypename)
            row.operator("ssmt4.fix_drawib_datatype", text="", icon='TOOL_SETTINGS', emboss=False)
            row.operator("ssmt4.fix_submesh_datatype", text="", icon='TOOL_SETTINGS', emboss=False)
            layout.label(text="Recalculate TANGENT: " + str(recalculate_tangent))
            layout.label(text="Recalculate COLOR: " + str(recalculate_color))

        # Manually import an SSMT model
        layout.operator(SSMT4ImportRaw.bl_idname,icon='IMPORT')
        # One-click import of the current SSMT workspace contents
        layout.operator(SSMT4ImportAllFromCurrentWorkSpaceBlueprint.bl_idname,icon='IMPORT')
        
        # SSMT blueprint dropdown list
        blueprint_row = layout.row(align=True)
        blueprint_row.prop(global_properties, "selected_blueprint_name", text="SSMT Blueprint")

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

        # Quick Generate Mod button, to avoid opening the blueprint editor for it
        quick_generate_row = layout.row()
        quick_generate_row.operator(SSMTGenerateSelectedBlueprintMod.bl_idname, text="Generate Mod", icon='EXPORT')



        if GlobalConfig.logic_name == LogicName.WWMI:
            layout.prop(global_properties,"import_merged_vgmap")

        if GlobalConfig.logic_name == LogicName.WWMI or GlobalConfig.logic_name == LogicName.NTEMI:
            layout.prop(global_properties,"import_skip_empty_vertex_groups")

        # Whether to use the normal map when importing
        layout.prop(global_properties, "use_normal_map")

        if GlobalConfig.logic_name == LogicName.GIMI or str(GlobalConfig.gamename).strip().casefold() in {
            "gimi", "genshinimpact",
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
