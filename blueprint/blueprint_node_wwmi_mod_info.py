"""WWMI-only, socketless metadata for the Mod generated from this tree.

The node describes the complete Mod rather than an individual draw call.
It uses the existing global-manager pattern, without adding a socket type.
Only a node in the exported top-level blueprint contributes metadata.
Nested node groups remain object-processing graphs, not metadata containers.
The collector rejects multiple managers rather than choosing one silently.
Removing the node restores the exporter's historical default information.
Changing presets leaves the saved node intact but prevents its application.
Logo conversion is intentionally absent: this field accepts an existing DDS.
"""

import bpy
from ..common.global_config import GlobalConfig, LogicName
from ..i18n.i18n import tr, translatable
from .blueprint_node_base import MIMINodeBase


@translatable
class MIMINode_WWMI_Mod_Info(MIMINodeBase):
    bl_idname = 'MIMINode_WWMI_Mod_Info'
    bl_label = 'WWMI Mod Info'
    bl_icon = 'INFO'

    # No sockets: like global texture managers, this describes the whole Mod.
    # RNA stores these fields in the blueprint and supports ordinary node copies.
    mod_name: bpy.props.StringProperty(name=tr("Mod Name"), default='Unnamed Mod') # type: ignore
    mod_author: bpy.props.StringProperty(name=tr("Mod Author"), default='Unknown Author') # type: ignore
    mod_desc: bpy.props.StringProperty(name=tr("Mod Description")) # type: ignore
    mod_link: bpy.props.StringProperty(name=tr("Mod Link")) # type: ignore
    mod_logo: bpy.props.StringProperty(name=tr("Mod Logo (DDS)"), subtype='FILE_PATH') # type: ignore

    @classmethod
    def poll(cls, ntree):
        # Hide from search as well as the add menu outside the WWMI preset.
        return super().poll(ntree) and GlobalConfig.logic_name == LogicName.WWMI

    def init(self, context):
        self.width = 340

    def draw_buttons(self, context, layout):
        # A saved node remains visible after changing presets but cannot apply.
        if GlobalConfig.logic_name != LogicName.WWMI:
            layout.label(text=tr("This node is only available for WWMI"), icon='INFO')
            return
        layout.label(text=tr("Applies to this blueprint; no connection needed"))
        for field in ('mod_name', 'mod_author', 'mod_desc', 'mod_link', 'mod_logo'):
            layout.prop(self, field)


def register():
    bpy.utils.register_class(MIMINode_WWMI_Mod_Info)


def unregister():
    bpy.utils.unregister_class(MIMINode_WWMI_Mod_Info)
