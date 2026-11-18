"""Naraka clothing opacity controls for the object draw branch."""

import bpy

from ..common.global_config import GlobalConfig, LogicName
from ..i18n.i18n import tr, translatable
from .blueprint_node_base import MIMINodeBase
from .blueprint_node_texture import draw_switch_state


@translatable
class MIMINode_Naraka_Opacity(MIMINodeBase):
    bl_idname = "MIMINode_Naraka_Opacity"
    bl_label = "Clothing Transparency"
    bl_description = "Make clothing translucent in Naraka materials that use a texture alpha channel for opacity"
    bl_icon = 'TEXTURE'

    # Keep a stable enum for saved .blend files and show only the fields
    # needed by the selected method. Auto resolution runs for each draw.
    slot_mode: bpy.props.EnumProperty(
        name=tr("Texture Slot"),
        items=[
            ('AUTO', tr("Auto from Marks"), tr("Use the workspace texture marks for each connected Submesh")),
            ('MANUAL', tr("Manual Slot"), tr("Enter the captured pixel shader texture slot")),
        ],
        default='AUTO',
    )
    slot: bpy.props.StringProperty(
        name=tr("Texture Slot"),
        description=tr("Read the clothing opacity slot in MMT, e.g. ps-t4."),
    )
    mark_name: bpy.props.StringProperty(
        name=tr("Clothing Opacity Mark"),
        description=tr("Leave blank to detect Opacity or the sample texture hashes"),
    )

    # The DDS stores literal RGB and alpha bytes. Use a gamma color picker
    # so the displayed gray corresponds to the bytes in the sample.
    opacity: bpy.props.FloatProperty(
        name=tr("Opacity"), subtype='FACTOR', min=0, max=1, default=128 / 255,
        description=tr("Alpha of the generated DDS. Lower values reveal more underneath."),
    )
    tint: bpy.props.FloatVectorProperty(
        name=tr("Texture Tint"), subtype='COLOR_GAMMA', size=3, min=0, max=1,
        default=(126 / 255,) * 3,
        description=tr("RGB of the generated DDS. The default matches the sample gray."),
    )

    def init(self, context):
        self.label = self.default_title()
        self.inputs.new('MIMISocketObject', "Object")
        self.outputs.new('MIMISocketObject', "Output")
        self.width = 445

    def draw_buttons(self, context, layout):
        if GlobalConfig.logic_name != LogicName.Naraka:
            layout.label(text=tr("Clothing Transparency is available only in Naraka"), icon='ERROR')
            return

        # Show the wiring and material requirement up front, even on a
        # freshly added node with no workspace marks or links.
        help_box = layout.box()
        help_box.label(text=tr("Connect clothing only → this node → Result Output."), icon='INFO')
        help_box.label(text=tr("Keep the mesh underneath on a separate branch."))
        help_box.label(text=tr("The game material must support opacity from texture alpha."))
        draw_switch_state(layout, self)
        layout.prop(self, "slot_mode", text=tr("Texture Slot"))
        if self.slot_mode == 'MANUAL':
            layout.prop(self, "slot", text=tr("Texture Slot"))
            layout.label(text=tr("Read the clothing opacity slot in MMT, e.g. ps-t4."))
        else:
            layout.label(text=tr("Mark the clothing opacity texture as Opacity in MMT."))
            layout.label(text=tr("Already named it? Enter the same mark name here."))
            layout.prop(self, "mark_name", text=tr("Clothing Opacity Mark"))
        layout.prop(self, "opacity", text=tr("Opacity"), slider=True)
        layout.prop(self, "tint", text=tr("Texture Tint"))


def register():
    bpy.utils.register_class(MIMINode_Naraka_Opacity)


def unregister():
    bpy.utils.unregister_class(MIMINode_Naraka_Opacity)
