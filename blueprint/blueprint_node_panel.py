import bpy

from ..utils.translate_utils import iface_
from .blueprint_node_base import SSMTNodeBase


class SSMTNode_ModPanel(SSMTNodeBase):
	'''Mod Panel Node'''
	bl_idname = 'SSMTNode_ModPanel'
	bl_label = '生成Mod面板'
	bl_icon = 'MENU_PANEL'

	enable_flow_effect: bpy.props.BoolProperty(
		name="流光边框效果",
		description="勾选后，生成的Mod面板启用流光边框效果",
		default=True,
	) # type: ignore

	def init(self, context):
		self.width = 220

	def draw_buttons(self, context, layout):
		info_box = layout.box()
		info_box.label(text=iface_("检测到该节点时生成Mod面板"), icon='INFO')
		layout.prop(self, "enable_flow_effect", text=iface_("流光效果"))


classes = (
	SSMTNode_ModPanel,
)


def register():
	for cls in classes:
		bpy.utils.register_class(cls)


def unregister():
	for cls in reversed(classes):
		bpy.utils.unregister_class(cls)
