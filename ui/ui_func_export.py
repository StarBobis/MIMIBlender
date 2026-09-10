import glob
import os

import bpy

from ..utils.timer_utils import TimerUtils
from ..utils.command_utils import CommandUtils

from ..common.global_config import GlobalConfig
from ..common.global_config import LogicName

from ..games.efmi import ExportEFMI
from ..games.gimi import ExportGIMI
from ..games.himi import ExportHIMI
from ..games.identityv import ExportIdentityV
from ..games.snowbreak import ExportSnowBreak
from ..games.srmi import ExportSRMI
from ..games.unity import ExportUnity
from ..games.wwmi import ExportWWMI
from ..games.ntemi import ExportNTEMI
from ..games.yysls import ExportYYSLS
from ..games.zzmi import ExportZZMI
from ..games.zzmidx12 import ExportZZMIDX12

from ..model.blueprint_model import BluePrintModel
from ..blueprint.blueprint_export_helper import BlueprintExportHelper
from ..blueprint.blueprint_node_obj import ObjectPersistentIdManager
from ..blueprint.blueprint_node_face_mod import (
    FaceModExportError,
    export_face_mod_from_node,
)
from ..i18n.i18n import I18nOperator, tr


def _export_blueprint_model(blueprint_model):
    """Dispatch one parsed output layer to the selected game exporter."""
    if GlobalConfig.logic_name == LogicName.EFMI:
        ExportEFMI(blueprint_model=blueprint_model).export()
    elif GlobalConfig.logic_name == LogicName.GIMI:
        ExportGIMI(blueprint_model=blueprint_model).export()
    elif GlobalConfig.logic_name == LogicName.HIMI:
        ExportHIMI(blueprint_model=blueprint_model).export()
    elif GlobalConfig.logic_name == LogicName.IdentityV:
        ExportIdentityV(blueprint_model=blueprint_model).export()
    elif GlobalConfig.logic_name == LogicName.SRMI:
        ExportSRMI(blueprint_model=blueprint_model).export()
    elif GlobalConfig.logic_name == LogicName.ZZMIDX12:
        ExportZZMIDX12(blueprint_model=blueprint_model).export()
    elif GlobalConfig.logic_name == LogicName.ZZMI:
        ExportZZMI(blueprint_model=blueprint_model).export()
    elif GlobalConfig.logic_name == LogicName.WWMI:
        ExportWWMI(blueprint_model=blueprint_model).export()
    elif GlobalConfig.logic_name == LogicName.NTEMI:
        ExportNTEMI(blueprint_model=blueprint_model).export()
    elif GlobalConfig.logic_name == LogicName.SnowBreak:
        ExportSnowBreak(blueprint_model=blueprint_model).export()
    elif GlobalConfig.logic_name == LogicName.YYSLS:
        ExportYYSLS(blueprint_model=blueprint_model).export()
    elif GlobalConfig.logic_name in {
        LogicName.Naraka, LogicName.NarakaM, LogicName.GF2, LogicName.AILIMIT,
    }:
        ExportUnity(blueprint_model=blueprint_model).export()
    else:
        raise ValueError(tr("The current game preset does not yet support generating Mods"))


_OUTPUT_NODE_IDS = {"SSMTNode_Result_Output", "SSMTNode_Face_Mod_Export"}


def _export_regular_output(tree, context, output_node, config_name):
    output_folder = GlobalConfig.path_generate_mod_folder()
    stem = os.path.splitext(config_name)[0]
    GlobalConfig.generated_mod_name_override = stem
    BlueprintExportHelper.runtime_output_node = output_node
    blueprint_model = None
    try:
        blueprint_model = BluePrintModel(tree=tree, context=context, output_node=output_node)
        _export_blueprint_model(blueprint_model)
    finally:
        if blueprint_model is not None:
            _cleanup_unico_temp_objects(blueprint_model)
        BlueprintExportHelper.runtime_output_node = None
        GlobalConfig.generated_mod_name_override = ""

    if GlobalConfig.logic_name == LogicName.WWMI:
        generated = sorted(glob.glob(os.path.join(output_folder, stem + "_*.ini")))
    else:
        generated = [os.path.join(output_folder, stem + ".ini")]
    generated = [path for path in generated if os.path.isfile(path)]
    if not generated:
        raise ValueError(tr("Output node '{name}' did not generate an INI file").format(name=output_node.name))
    return generated


def generate_mod_from_output_node(tree, context, output_node, report_callback):
    if getattr(output_node, "bl_idname", "") not in _OUTPUT_NODE_IDS:
        report_callback({'ERROR'}, tr("Please select a valid Output node"))
        return {'CANCELLED'}

    TimerUtils.Start("GenerateMod Mod")
    GlobalConfig.initialize_key_count()
    BlueprintExportHelper.runtime_output_node = None
    BlueprintExportHelper.set_runtime_blueprint_tree(tree)
    refresh_summary = ObjectPersistentIdManager.refresh_all_nodes(tree=tree, source="export")
    if refresh_summary["missing_count"] > 0:
        report_callback({'WARNING'}, tr("Before export, {count} object nodes found no matching object").format(count=refresh_summary['missing_count']))

    try:
        if getattr(output_node, "bl_idname", "") == "SSMTNode_Face_Mod_Export":
            # Face Mod nodes write their own Face.ini and do not use the
            # regular workspace-named INI path.
            export_face_mod_from_node(output_node)
        else:
            # The generated root INI is always named after the workspace.
            config_name = f"{GlobalConfig.get_workspace_name()}.ini"
            _export_regular_output(tree, context, output_node, config_name)
    except (FaceModExportError, OSError, ValueError) as error:
        BlueprintExportHelper.runtime_output_node = None
        GlobalConfig.generated_mod_name_override = ""
        TimerUtils.End("GenerateMod Mod")
        report_callback({'ERROR'}, str(error))
        return {'CANCELLED'}

    TimerUtils.End("GenerateMod Mod")
    report_callback({'INFO'}, tr("Generate Mod Success!"))
    CommandUtils.OpenGeneratedModFolder()
    return {'FINISHED'}


def generate_mod_from_tree(tree, context, report_callback):
    if not tree:
        report_callback({'ERROR'}, tr("No valid blueprint found"))
        return {'CANCELLED'}
    output_nodes = [
        node for node in tree.nodes
        if getattr(node, "bl_idname", "") in _OUTPUT_NODE_IDS
    ]
    if not output_nodes:
        report_callback({'ERROR'}, tr("The current blueprint is missing a Generate Mod output node"))
        return {'CANCELLED'}

    # The toolbar shortcut has no node identity.  With several independent
    # targets users must click the intended node so a root INI is never
    # accidentally overwritten.
    if len(output_nodes) != 1:
        report_callback({'ERROR'}, tr("Multiple independent Outputs exist; click \"Generate Mod\" on the Output node you want to export"))
        return {'CANCELLED'}
    return generate_mod_from_output_node(tree, context, output_nodes[0], report_callback)


def _cleanup_unico_temp_objects(blueprint_model: BluePrintModel):
    """Clean up temporary objects created by UniComponent splitting"""
    temp_objects = getattr(blueprint_model, '_unico_temp_objects', None)
    if not temp_objects:
        return
    for temp_obj in temp_objects:
        try:
            if temp_obj and temp_obj.name in bpy.data.objects:
                bpy.data.objects.remove(temp_obj, do_unlink=True)
        except Exception as e:
            print(f"[UniComponent] Error cleaning up temporary objects: {e}")
    print(f"[UniComponent] Cleaned up {len(temp_objects)} temporary split objects")


class SSMTGenerateModBlueprint(I18nOperator):
    bl_idname = "ssmt.generate_mod_blueprint"
    bl_label = "Generate Mod"
    bl_description = "Generate the Mod files from the blueprint architecture for the current workspace"
    bl_options = {'REGISTER','UNDO'}

    node_name: bpy.props.StringProperty()  # type: ignore
    tree_name: bpy.props.StringProperty()  # type: ignore

    def execute(self, context):
        tree = bpy.data.node_groups.get(self.tree_name) if self.tree_name else None
        tree = tree or BlueprintExportHelper.get_current_blueprint_tree(context=context)
        if not tree:
            self.report({'ERROR'}, tr("No current blueprint found; click \"Generate Mod\" in the blueprint editor"))
            return {'CANCELLED'}
        if self.node_name:
            output_node = tree.nodes.get(self.node_name)
            if output_node is None:
                self.report({'ERROR'}, tr("Output node not found"))
                return {'CANCELLED'}
            return generate_mod_from_output_node(tree, context, output_node, self.report)
        return generate_mod_from_tree(tree=tree, context=context, report_callback=self.report)


class SSMTGenerateSelectedBlueprintMod(I18nOperator):
    bl_idname = "ssmt.generate_selected_blueprint_mod"
    bl_label = "Generate Mod"
    bl_description = "Quickly generate the Mod files from the currently selected blueprint"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        global_properties = getattr(getattr(context, "scene", None), "global_properties", None)
        selected_name = getattr(global_properties, "selected_blueprint_name", "") if global_properties else ""

        tree = BlueprintExportHelper.get_selected_blueprint_tree(
            selected_name=selected_name,
            context=context,
        )
        if not tree:
            self.report({'ERROR'}, tr("Please select a valid blueprint"))
            return {'CANCELLED'}

        if global_properties and global_properties.selected_blueprint_name != tree.name:
            global_properties.selected_blueprint_name = tree.name

        return generate_mod_from_tree(tree=tree, context=context, report_callback=self.report)
    
def register():
    bpy.utils.register_class(SSMTGenerateModBlueprint)
    bpy.utils.register_class(SSMTGenerateSelectedBlueprintMod)


def unregister():
    bpy.utils.unregister_class(SSMTGenerateSelectedBlueprintMod)
    bpy.utils.unregister_class(SSMTGenerateModBlueprint)

