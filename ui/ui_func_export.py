import os

import bpy

from ..utils.timer_utils import TimerUtils
from ..utils.command_utils import CommandUtils
from ..utils.format_utils import Fatal

from ..common.global_config import GlobalConfig
from ..common import texture_format_service as texture_format

from ..games import get_exporter_class

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
    exporter_class = get_exporter_class(GlobalConfig.logic_name)
    if exporter_class is None:
        raise ValueError(tr("The current game preset does not yet support generating Mods"))
    exporter_class(blueprint_model=blueprint_model).export()


_OUTPUT_NODE_IDS = {"MIMINode_Result_Output", "MIMINode_Face_Mod_Export"}


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
        BlueprintExportHelper.runtime_output_node = None
        GlobalConfig.generated_mod_name_override = ""

    # WWMI now writes one consolidated INI with the same name as other presets.
    # Old per-DrawIB INIs must not hide a missing current workspace output.
    generated = [os.path.join(output_folder, stem + ".ini")]
    generated = [path for path in generated if os.path.isfile(path)]
    if not generated:
        raise ValueError(tr("Output node '{name}' did not generate an INI file").format(name=output_node.name))
    return generated


def generate_mod_from_output_node(tree, context, output_node, report_callback):
    # Validate the selected output before changing generation state.
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
        if getattr(output_node, "bl_idname", "") == "MIMINode_Face_Mod_Export":
            # Face Mod nodes write their own Face.ini and do not use the
            # regular workspace-named INI path.
            export_face_mod_from_node(output_node)
        else:
            # The generated root INI is always named after the workspace.
            config_name = f"{GlobalConfig.get_workspace_name()}.ini"
            _export_regular_output(tree, context, output_node, config_name)
    except (FaceModExportError, Fatal, OSError, ValueError) as error:
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
    # Shared shortcuts require one unambiguous output before exporting.
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


class MMTGenerateModBlueprint(I18nOperator):
    bl_idname = "mimi.generate_mod_blueprint"
    bl_label = "Generate Mod"
    bl_description = "Generate the Mod files from the blueprint architecture for the current workspace"
    bl_options = {'REGISTER','UNDO'}

    node_name: bpy.props.StringProperty()  # type: ignore
    tree_name: bpy.props.StringProperty()  # type: ignore

    def _resolve_target(self, context):
        """Return (tree, output node) for this invocation, or (None, None)."""
        tree = bpy.data.node_groups.get(self.tree_name) if self.tree_name else None
        tree = tree or BlueprintExportHelper.get_current_blueprint_tree(context=context)
        if not tree:
            return None, None
        if not self.node_name:
            return tree, None
        return tree, tree.nodes.get(self.node_name)

    @staticmethod
    def _pending_jobs(tree):
        """Return the replacement rows that still need a conversion.

        Planning reads headers only, so this stays cheap even for a blueprint
        with many rows. A job that cannot be planned is kept, because the
        runner reports the precise error before the export starts.
        """
        try:
            jobs = texture_format.collect_tree_jobs(tree)
        except Exception as error:
            print("Generate Mod: could not collect texture format jobs: " + str(error))
            return []
        pending = []
        for job in jobs:
            try:
                if texture_format.plan_for_job(job) is not None:
                    pending.append(job)
            except Exception:
                pending.append(job)
        return pending

    def invoke(self, context, event):
        # Prepare every replacement texture in the background first, then run
        # the normal synchronous export. Without pending jobs the behaviour is
        # exactly the historical one.
        tree, output_node = self._resolve_target(context)
        if tree is None or output_node is None:
            return self.execute(context)
        jobs = self._pending_jobs(tree)
        if not jobs:
            return self.execute(context)
        started = texture_format.start_conversion(jobs)
        if not started:
            return self.execute(context)
        self.operation_timer = context.window_manager.event_timer_add(0.2, window=context.window)
        context.window_manager.modal_handler_add(self)
        self.report({'INFO'}, tr("{count} replacement texture(s) need conversion before export").format(count=started))
        return {'RUNNING_MODAL'}

    def _stop_timer(self, context):
        """Remove the modal timer once the preparation phase has ended."""
        timer = getattr(self, "operation_timer", None)
        if timer is None:
            return
        try:
            context.window_manager.event_timer_remove(timer)
        except Exception:
            pass
        self.operation_timer = None

    def modal(self, context, event):
        if event.type == 'ESC':
            texture_format.cancel_conversion()
            self._stop_timer(context)
            self.report({'WARNING'}, tr("Texture format conversion cancelled"))
            return {'CANCELLED'}
        if event.type != 'TIMER':
            return {'PASS_THROUGH'}
        if texture_format.is_running():
            return {'RUNNING_MODAL'}
        self._stop_timer(context)
        errors = texture_format.progress_snapshot().get("errors") or []
        if errors:
            # Converting is mandatory: exporting the wrong DXGI format would
            # silently produce a broken mod, so stop with the first reason.
            self.report(
                {'ERROR'},
                tr("Replacement texture conversion failed; export stopped") + ": " + str(errors[0]),
            )
            return {'CANCELLED'}
        return self.execute(context)

    def execute(self, context):
        # Resolve the requested blueprint before selecting its output.
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


class MMTGenerateSelectedBlueprintMod(I18nOperator):
    bl_idname = "mimi.generate_selected_blueprint_mod"
    bl_label = "Generate Mod"
    bl_description = "Quickly generate the Mod files from the currently selected blueprint"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        # Resolve the selected blueprint without imposing preset restrictions.
        mimi_global_properties = getattr(getattr(context, "scene", None), "mimi_global_properties", None)
        selected_name = getattr(mimi_global_properties, "selected_blueprint_name", "") if mimi_global_properties else ""

        tree = BlueprintExportHelper.get_selected_blueprint_tree(
            selected_name=selected_name,
            context=context,
        )
        if not tree:
            self.report({'ERROR'}, tr("Please select a valid blueprint"))
            return {'CANCELLED'}

        if mimi_global_properties and mimi_global_properties.selected_blueprint_name != tree.name:
            mimi_global_properties.selected_blueprint_name = tree.name

        return generate_mod_from_tree(tree=tree, context=context, report_callback=self.report)

def register():
    bpy.utils.register_class(MMTGenerateModBlueprint)
    bpy.utils.register_class(MMTGenerateSelectedBlueprintMod)


def unregister():
    bpy.utils.unregister_class(MMTGenerateSelectedBlueprintMod)
    bpy.utils.unregister_class(MMTGenerateModBlueprint)

