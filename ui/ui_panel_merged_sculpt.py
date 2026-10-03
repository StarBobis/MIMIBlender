"""
Merged Sculpt panel: generic N-object merged sculpting UI.

Placed directly below the Model Processing panel in the MIMITools sidebar
(registration order defines the panel order inside a category, and this
module is registered right after ui_panel_model).

The panel exposes four operators:
- create:  duplicate the selected mesh objects and join the copies into
           one temporary sculpt target;
- apply:   write the sculpted positions back into every source object;
- discard: delete the sculpt target without writing anything back;
- validate: read-only health check of the current sculpt session.

All heavy lifting lives in utils/merged_sculpt_utils.py; this module only
wires the core logic into Blender's operator/panel system.
"""

import json

import bpy

from ..i18n.i18n import tr, translatable, I18nOperator
from ..utils.merged_sculpt_utils import MergedSculptUtils, PROP_SOURCES


class MIMI_OT_merged_sculpt_create(I18nOperator):
    """Duplicate the selected objects and join the copies into one sculpt target."""

    bl_idname = "mimi.merged_sculpt_create"
    bl_label = "Create Merged Sculpt Object"
    bl_description = (
        "Duplicate the selected mesh objects and join the copies into one "
        "temporary sculpt target. Works with any N objects; no naming or "
        "transform requirements")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        # Merging only makes sense in object mode with 2+ mesh objects.
        if context.mode != 'OBJECT':
            return False
        meshes = [obj for obj in context.selected_objects if obj.type == 'MESH']
        return len(meshes) >= 2

    def execute(self, context):
        try:
            merged_obj, warnings = MergedSculptUtils.create_merged_object(context)
        except ValueError as error:
            self.report({'ERROR'}, tr("Merged sculpt failed: ") + str(error))
            return {'CANCELLED'}

        # Surface non-fatal problems (for example mismatched shape keys).
        for warning in warnings:
            self.report({'WARNING'}, warning)
        self.report({'INFO'}, tr("Merged sculpt object created: ") + merged_obj.name)

        # Jump straight into sculpt mode, like the WWMI workflow does. This
        # may fail in background mode; the merge itself already succeeded.
        try:
            bpy.ops.object.mode_set(mode='SCULPT')
        except RuntimeError:
            pass
        return {'FINISHED'}


class MIMI_OT_merged_sculpt_apply(I18nOperator):
    """Write the sculpted positions back into every source object."""

    bl_idname = "mimi.merged_sculpt_apply"
    bl_label = "Apply Sculpt To Sources"
    bl_description = (
        "Write the sculpted vertex positions back into every source object, "
        "clean the session stamps and delete the merged sculpt object")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        # Enabled only while a merged sculpt object can be located.
        if context.view_layer is None:
            return False
        try:
            MergedSculptUtils._find_merged_object(context)
        except ValueError:
            return False
        return True

    def execute(self, context):
        # The toggle lives on the scene because panel draw() must not own
        # operator properties in Blender 5.2.
        apply_deltas = bool(getattr(
            context.scene, "mimi_merged_sculpt_apply_deltas", False))
        try:
            count = MergedSculptUtils.apply_merged_sculpt(
                context, apply_deltas_to_shapekeys=apply_deltas)
        except (ValueError, RuntimeError) as error:
            # The core restores source coordinates on an unexpected write
            # failure; report the error while leaving the session available.
            self.report({'ERROR'}, tr("Merged sculpt failed: ") + str(error))
            return {'CANCELLED'}
        self.report(
            {'INFO'},
            tr("Applied sculpt to {count} source objects.").format(count=count))
        return {'FINISHED'}


class MIMI_OT_merged_sculpt_discard(I18nOperator):
    """Delete the merged sculpt object without writing anything back."""

    bl_idname = "mimi.merged_sculpt_discard"
    bl_label = "Discard Merged Sculpt Object"
    bl_description = (
        "Delete the merged sculpt object without writing anything back, "
        "and remove the session stamps from its source objects")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if context.view_layer is None:
            return False
        try:
            MergedSculptUtils._find_merged_object(context)
        except ValueError:
            return False
        return True

    def execute(self, context):
        try:
            MergedSculptUtils.discard_merged_sculpt(context)
        except ValueError as error:
            self.report({'ERROR'}, tr("Merged sculpt failed: ") + str(error))
            return {'CANCELLED'}
        self.report({'INFO'}, tr("Merged sculpt object discarded."))
        return {'FINISHED'}


class MIMI_OT_merged_sculpt_validate(I18nOperator):
    """Read-only health check of the current merged sculpt session."""

    bl_idname = "mimi.merged_sculpt_validate"
    bl_label = "Validate Merged Sculpt"
    bl_description = (
        "Check the merged sculpt session: missing sources, vertex count "
        "changes and moved sources are reported before applying")
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        if context.view_layer is None:
            return False
        try:
            MergedSculptUtils._find_merged_object(context)
        except ValueError:
            return False
        return True

    def execute(self, context):
        try:
            issues = MergedSculptUtils.validate_merged_sculpt(context)
        except ValueError as error:
            self.report({'ERROR'}, tr("Merged sculpt failed: ") + str(error))
            return {'CANCELLED'}
        if not issues:
            self.report({'INFO'}, tr("Validation passed: no issues."))
        else:
            # One report per issue keeps long lists readable in the UI.
            for issue in issues:
                self.report({'WARNING'}, issue)
        return {'FINISHED'}


@translatable
class MIMIPanelMergedSculpt(bpy.types.Panel):
    """Sidebar panel placed directly below the Model Processing panel."""

    bl_label = "Merged Sculpt Panel"
    bl_idname = "MIMI_PT_merged_sculpt"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'MIMITools'
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout

        # Create row: always visible; the poll greys it out until the
        # selection holds at least two mesh objects.
        layout.operator("mimi.merged_sculpt_create", icon='SCULPTMODE_HLT')
        # Show the safety constraints before the user starts a session.
        layout.label(text=tr("Use single-user meshes; one session per source."))
        layout.label(text=tr("Keep source UID stamps; do not change vertex count."))

        # Status block: locate the current merged object (if any) and show
        # its session summary. Reading custom properties in draw() is fine;
        # only writes are forbidden there.
        merged_obj = None
        try:
            merged_obj = MergedSculptUtils._find_merged_object(context)
        except (ValueError, AttributeError):
            merged_obj = None

        if merged_obj is None:
            layout.label(text=tr("No merged sculpt object in scene."))
            return

        # A hand-edited or otherwise corrupt payload must never break the
        # whole sidebar; surface it as a plain label instead.
        try:
            payload = json.loads(merged_obj[PROP_SOURCES])
        except (TypeError, ValueError, KeyError):
            layout.label(text=tr("Merged sculpt session data is corrupt."))
            return
        box = layout.box()
        box.label(
            text=tr("Active merged object: ") + merged_obj.name,
            icon='OBJECT_DATA')
        box.label(text=tr("Sources: ") + str(len(payload["sources"])))
        box.label(text=tr("Vertices: ") + str(len(merged_obj.data.vertices)))

        # Apply options + action buttons.
        layout.prop(context.scene, "mimi_merged_sculpt_apply_deltas")
        layout.operator("mimi.merged_sculpt_validate", icon='CHECKMARK')
        row = layout.row(align=True)
        row.operator("mimi.merged_sculpt_apply", icon='IMPORT')
        row.operator("mimi.merged_sculpt_discard", icon='TRASH')


# Scene-level option: write the sculpt delta into every shape key of each
# source object instead of only into the Basis key. Kept on the scene so
# the panel can draw it without owning operator state.
_SCENE_PROP = "mimi_merged_sculpt_apply_deltas"


def register():
    """Register operators, the panel and the scene-level option."""
    bpy.utils.register_class(MIMI_OT_merged_sculpt_create)
    bpy.utils.register_class(MIMI_OT_merged_sculpt_apply)
    bpy.utils.register_class(MIMI_OT_merged_sculpt_discard)
    bpy.utils.register_class(MIMI_OT_merged_sculpt_validate)
    bpy.utils.register_class(MIMIPanelMergedSculpt)

    setattr(bpy.types.Scene, _SCENE_PROP, bpy.props.BoolProperty(
        name=tr("Also apply deltas to shape keys"),
        description=tr(
            "Write the sculpt delta into every shape key of each source "
            "object; otherwise only the Basis key receives the sculpted "
            "positions"),
        default=False,
    ))


def unregister():
    """Unregister in reverse order and drop the scene-level option."""
    if hasattr(bpy.types.Scene, _SCENE_PROP):
        delattr(bpy.types.Scene, _SCENE_PROP)

    bpy.utils.unregister_class(MIMIPanelMergedSculpt)
    bpy.utils.unregister_class(MIMI_OT_merged_sculpt_validate)
    bpy.utils.unregister_class(MIMI_OT_merged_sculpt_discard)
    bpy.utils.unregister_class(MIMI_OT_merged_sculpt_apply)
    bpy.utils.unregister_class(MIMI_OT_merged_sculpt_create)
