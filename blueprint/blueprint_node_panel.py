import bpy

from .blueprint_node_base import SSMTNodeBase


class SSMTNode_ModPanel(SSMTNodeBase):
	'''Mod Panel Node'''
	bl_idname = 'SSMTNode_ModPanel'
	bl_label = 'Generate Mod Panel'
	bl_icon = 'MENU_PANEL'

	enable_flow_effect: bpy.props.BoolProperty(
		name="Flowing Border Effect",
		description="When enabled, the generated Mod panel gets a flowing border effect",
		default=True,
	) # type: ignore

	def init(self, context):
		self.width = 220

	def draw_buttons(self, context, layout):
		info_box = layout.box()
		info_box.label(text="When this node is present, generate the Mod panel", icon='INFO')
		layout.prop(self, "enable_flow_effect", text="Flow Effect")


classes = (
	SSMTNode_ModPanel,
)


def register():
	for cls in classes:
		bpy.utils.register_class(cls)


def unregister():
	for cls in reversed(classes):
		bpy.utils.unregister_class(cls)
