import os
import time
import uuid

import bpy
from bpy_extras.io_utils import ImportHelper

from ..common.global_config import LogicName
from ..common.global_config import GlobalConfig
from ..common.global_properties import GlobalProperties
from .blueprint_export_helper import BlueprintExportHelper
from .blueprint_node_base import SSMTNodeBase
from .blueprint_node_shapekey import SSMTShapeKeyListItem
from ..workspace.ssmt_workspace import WorkSpaceModel

OBJECT_PERSISTENT_ID_KEY = "_ssmt_object_uuid"

_picking_node_name = None
_picking_tree_name = None


class ObjectPersistentIdManager:
    '''Persistent UUID management for Blender objects: generate, look up, verify.'''

    @staticmethod
    def _is_duplicate(target_obj, object_id):
        if not target_obj or not object_id:
            return False
        for obj in bpy.data.objects:
            if obj == target_obj:
                continue
            if str(obj.get(OBJECT_PERSISTENT_ID_KEY, "") or "") == object_id:
                return True
        return False

    @staticmethod
    def ensure_id(obj):
        """
        Get or create the persistent UUID of a Blender object.
        Note: this function may only be called in contexts where writing to
        data-blocks is allowed, not directly during node draw.
        """
        if obj is None:
            return ""
        object_id = str(obj.get(OBJECT_PERSISTENT_ID_KEY, "") or "")
        if not object_id or ObjectPersistentIdManager._is_duplicate(obj, object_id):
            object_id = uuid.uuid4().hex
            obj[OBJECT_PERSISTENT_ID_KEY] = object_id
        return object_id

    @staticmethod
    def find_by_id(object_id):
        if not object_id:
            return None
        for obj in bpy.data.objects:
            if str(obj.get(OBJECT_PERSISTENT_ID_KEY, "") or "") == str(object_id):
                return obj
        return None

    @staticmethod
    def resolve_node_target(node, allow_name_fallback=True):
        if not node or getattr(node, "bl_idname", "") != 'SSMTNode_Object_Info':
            return None
        resolved_obj = None
        node_object_name = str(getattr(node, "object_name", "") or "")
        node_object_id = str(getattr(node, "object_id", "") or "")
        if allow_name_fallback and node_object_name:
            resolved_obj = bpy.data.objects.get(node_object_name)
        if resolved_obj is None and node_object_id:
            resolved_obj = ObjectPersistentIdManager.find_by_id(node_object_id)
        return resolved_obj

    @staticmethod
    def refresh_node(node, allow_name_fallback=True):
        """
        Refresh a single Object Info node.
        Writes are only performed at safe moments:
        1. After an object is picked.
        2. When the user manually runs "Refresh Object Node Info".
        3. Before generating a Mod.
        4. After a node click, via a deferred timer, not directly in draw.
        """
        result = {"found": False, "changed": False, "object": None, "elapsed_ms": 0.0}
        start_time = time.perf_counter()
        resolved_obj = ObjectPersistentIdManager.resolve_node_target(node, allow_name_fallback=allow_name_fallback)
        if resolved_obj is None:
            result["elapsed_ms"] = (time.perf_counter() - start_time) * 1000.0
            return result
        result["found"] = True
        result["object"] = resolved_obj
        persistent_id = ObjectPersistentIdManager.ensure_id(resolved_obj)
        if str(getattr(node, "object_id", "") or "") != persistent_id:
            node.object_id = persistent_id
            result["changed"] = True
        if str(getattr(node, "object_name", "") or "") != resolved_obj.name:
            node.object_name = resolved_obj.name
            result["changed"] = True
        result["elapsed_ms"] = (time.perf_counter() - start_time) * 1000.0
        return result

    @staticmethod
    def refresh_all_nodes(context=None, tree=None, include_all_blueprints=False, source="unknown"):
        """
        Refresh all Object Info nodes in the blueprint.
        Must be called before export so that each node's object_name follows
        its UUID and is written back with the latest name.
        """
        checked_count = 0
        updated_count = 0
        missing_count = 0
        start_time = time.perf_counter()
        trees = []
        if include_all_blueprints:
            trees = [node_group for node_group in bpy.data.node_groups if getattr(node_group, "bl_idname", "") == 'SSMTBlueprintTreeType']
        else:
            tree = tree or BlueprintExportHelper.get_current_blueprint_tree(context=context)
            if tree:
                trees = [tree]
        for blueprint_tree in trees:
            for node in blueprint_tree.nodes:
                if getattr(node, "bl_idname", "") != 'SSMTNode_Object_Info':
                    continue
                checked_count += 1
                refresh_result = ObjectPersistentIdManager.refresh_node(node, allow_name_fallback=True)
                if refresh_result["changed"]:
                    updated_count += 1
                has_reference = bool(str(getattr(node, "object_name", "") or "") or str(getattr(node, "object_id", "") or ""))
                if has_reference and not refresh_result["found"]:
                    missing_count += 1
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        summary = {"checked_count": checked_count, "updated_count": updated_count, "missing_count": missing_count, "elapsed_ms": elapsed_ms, "source": source}
        print(f"[ObjectInfoRefresh:{source}] checked={checked_count}, updated={updated_count}, missing={missing_count}, elapsed={elapsed_ms:.3f} ms")
        return summary


class SSMT_OT_RefreshNodeObjectIDs(bpy.types.Operator):
    '''Refresh the object reference info of every object node in blueprints'''
    bl_idname = "ssmt.refresh_node_object_ids"
    bl_label = "Refresh Object Node Info"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        refresh_summary = ObjectPersistentIdManager.refresh_all_nodes(include_all_blueprints=True, source="manual")

        if refresh_summary["missing_count"] > 0:
            self.report({'WARNING'}, "Refreshed {updated_count} object nodes, but {missing_count} nodes have no matching object, took {elapsed_ms:.3f} ms".format(updated_count=refresh_summary['updated_count'], missing_count=refresh_summary['missing_count'], elapsed_ms=refresh_summary['elapsed_ms']))
        elif refresh_summary["updated_count"] > 0:
            self.report({'INFO'}, "Refreshed {updated_count} object nodes, took {elapsed_ms:.3f} ms".format(updated_count=refresh_summary['updated_count'], elapsed_ms=refresh_summary['elapsed_ms']))
        else:
            self.report({'INFO'}, "All object nodes are already up to date, took {elapsed_ms:.3f} ms".format(elapsed_ms=refresh_summary['elapsed_ms']))
        
        return {'FINISHED'}


class SSMT_OT_SelectNodeObject(bpy.types.Operator):
    '''Select this object in 3D View'''
    bl_idname = "ssmt.select_node_object"
    bl_label = "Select Object"
    
    object_name: bpy.props.StringProperty() # type: ignore
    object_id: bpy.props.StringProperty() # type: ignore

    def execute(self, context):
        obj = None
        if self.object_name:
            obj = bpy.data.objects.get(self.object_name)
        if obj is None and self.object_id:
            obj = ObjectPersistentIdManager.find_by_id(self.object_id)

        if not obj:
            return {'CANCELLED'}

        if obj:
            try:
                bpy.ops.object.select_all(action='DESELECT')
            except Exception:
                pass
                
            obj.select_set(True)
            context.view_layer.objects.active = obj
            self.report({'INFO'}, "Selected object: {name}".format(name=obj.name))
        else:
            self.report({'WARNING'}, "Object not found")
        
        return {'FINISHED'}


class SSMT_OT_StartPickObject(bpy.types.Operator):
    '''Start picking an object from 3D View'''
    bl_idname = "ssmt.start_pick_object"
    bl_label = "Pick Object"
    bl_description = "Click to pick an object in the 3D View"
    
    node_name: bpy.props.StringProperty() # type: ignore
    tree_name: bpy.props.StringProperty() # type: ignore
    
    def execute(self, context):
        global _picking_node_name, _picking_tree_name
        
        tree = getattr(context.space_data, "edit_tree", None) or getattr(context.space_data, "node_tree", None)
        if not tree and self.tree_name:
            tree = bpy.data.node_groups.get(self.tree_name)
        if not tree:
            tree = BlueprintExportHelper.get_current_blueprint_tree(context=context)
        
        if not tree:
            self.report({'WARNING'}, "Cannot get node tree context")
            return {'CANCELLED'}
        
        _picking_node_name = self.node_name
        _picking_tree_name = tree.name
        self.report({'INFO'}, "Please click an object in the 3D View")
        
        bpy.ops.ssmt.pick_object_modal('INVOKE_DEFAULT')
        
        return {'FINISHED'}


class SSMT_OT_PickObjectModal(bpy.types.Operator):
    '''Modal operator for picking objects in 3D View'''
    bl_idname = "ssmt.pick_object_modal"
    bl_label = "Pick Object"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}
    
    def invoke(self, context, event):
        global _picking_node_name, _picking_tree_name
        
        if not _picking_node_name:
            return {'CANCELLED'}

        if not _picking_tree_name:
            current_tree = BlueprintExportHelper.get_current_blueprint_tree(context=context)
            _picking_tree_name = current_tree.name if current_tree else None
        
        self._initial_selected_objs = set(context.selected_objects)
        if context.selected_objects:
            self._last_selected_obj = context.selected_objects[0]
        else:
            self._last_selected_obj = None
        
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}
    
    def modal(self, context, event):
        global _picking_node_name, _picking_tree_name

        def clear_picking_state():
            global _picking_node_name, _picking_tree_name
            _picking_node_name = None
            _picking_tree_name = None

        def resolve_picking_node():
            tree = None
            if isinstance(_picking_tree_name, str) and _picking_tree_name:
                tree = bpy.data.node_groups.get(_picking_tree_name)

            if tree:
                node = tree.nodes.get(_picking_node_name)
                if node:
                    return tree, node

            current_tree = BlueprintExportHelper.get_current_blueprint_tree(context=context)
            if current_tree:
                node = current_tree.nodes.get(_picking_node_name)
                if node:
                    return current_tree, node

            node = BlueprintExportHelper.find_node_in_all_blueprints(_picking_node_name)
            if node:
                return getattr(node, "id_data", None), node

            return None, None
        
        if event.type == 'ESC':
            clear_picking_state()
            return {'CANCELLED'}
        
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            for area in context.screen.areas:
                if area.type == 'VIEW_3D':
                    region = next((r for r in area.regions if r.type == 'WINDOW'), None)
                    if region and area.x <= event.mouse_x <= area.x + area.width and area.y <= event.mouse_y <= area.y + area.height:
                        return {'PASS_THROUGH'}
        
        if event.type == 'MOUSEMOVE':
            current_selected = context.selected_objects
            if current_selected:
                current_obj = current_selected[0]
                if current_obj != self._last_selected_obj and current_obj not in self._initial_selected_objs:
                    tree, node = resolve_picking_node()
                    if not node:
                        clear_picking_state()
                        self.report({'WARNING'}, "Cannot get node tree context")
                        return {'CANCELLED'}

                    node.object_name = current_obj.name
                    node.object_id = ObjectPersistentIdManager.ensure_id(current_obj)
                    if tree:
                        BlueprintExportHelper.set_runtime_blueprint_tree(tree)
                    self.report({'INFO'}, "Picked object: {name}".format(name=current_obj.name))

                    clear_picking_state()
                    return {'FINISHED'}
        
        return {'PASS_THROUGH'}


def draw_view3d_header(self, context):
    global _picking_node_name
    if _picking_node_name:
        self.layout.label(text="Please click an object in the 3D View...", icon='EYEDROPPER')


class SSMTTextureSlotItem(bpy.types.PropertyGroup):
    """Configuration item for each texture slot input on the Object Info node"""
    slot_index: bpy.props.IntProperty(
        name="Slot Index",
        description="Texture slot number",
        default=0,
        min=0,
        max=127,
    )  # type: ignore

    # Slot output type: ps-t by default; also supports toolkit-managed forms (e.g. ZZMI) or custom.
    slot_type: bpy.props.EnumProperty(
        name="Slot Type",
        description="Key name form used by this slot when generating INI",
        items=[
            ('PS_T', 'ps-t', 'Regular 3Dmigoto pixel shader slot (ps-t0, ps-t1...)'),
            ('ZZMI_DIFFUSE', 'ZZMI Diffuse', 'Resource\\ZZMI\\Diffuse'),
            ('ZZMI_NORMALMAP', 'ZZMI NormalMap', 'Resource\\ZZMI\\NormalMap'),
            ('ZZMI_LIGHTMAP', 'ZZMI LightMap', 'Resource\\ZZMI\\LightMap'),
            ('ZZMI_MATERIALMAP', 'ZZMI MaterialMap', 'Resource\\ZZMI\\MaterialMap'),
            ('RABBITFX_FXMAP', 'RabbitFX FXMap', 'Resource\\RabbitFX\\FXMap'),
            ('CUSTOM', 'Custom', 'Manually enter the slot key name'),
        ],
        default='PS_T',
    )  # type: ignore

    custom_slot_key: bpy.props.StringProperty(
        name="Custom Key",
        description="Full key name used when Slot Type is Custom, e.g. ps-t3 or Resource\\MyTool\\Diffuse",
        default="",
    )  # type: ignore

    @property
    def effective_slot_key(self) -> str:
        """Return the key name used when generating INI, based on slot_type."""
        type_map = {
            'PS_T': f"ps-t{self.slot_index}",
            'ZZMI_DIFFUSE': r"Resource\ZZMI\Diffuse",
            'ZZMI_NORMALMAP': r"Resource\ZZMI\NormalMap",
            'ZZMI_LIGHTMAP': r"Resource\ZZMI\LightMap",
            'ZZMI_MATERIALMAP': r"Resource\ZZMI\MaterialMap",
            'RABBITFX_FXMAP': r"Resource\RabbitFX\FXMap",
        }
        if self.slot_type == 'CUSTOM':
            return self.custom_slot_key.strip() or f"ps-t{self.slot_index}"
        return type_map.get(self.slot_type, f"ps-t{self.slot_index}")


class SSMTNode_Object_Info(SSMTNodeBase):
    '''Object Info Node'''
    bl_idname = 'SSMTNode_Object_Info'
    bl_label = 'Object Info'
    bl_icon = 'OBJECT_DATAMODE'
    bl_width_min = 400

    def _get_effective_parse_name(self):
        normalized_submesh_name = str(self.submesh_name or "").strip()
        prefix_name = normalized_submesh_name.partition(".")[0]
        # Both the new format (2 segments) and the old format (>=3 segments) are valid submesh_name values
        if normalized_submesh_name and len(prefix_name.split("-")) >= 2:
            return normalized_submesh_name
        return self.object_name

    def _refresh_display_fields(self):
        if self.object_name:
            self.label = self.object_name
        else:
            self.label = "Object Info"

        # Collect all texts that participate in the width calculation
        width_texts = [self.object_name, self.submesh_name]

        # Also include every Submesh name from the dropdown in the width
        # calculation, so long names that are not currently selected are not truncated
        tree = self.id_data if hasattr(self, "id_data") and getattr(self.id_data, "bl_idname", "") == 'SSMTBlueprintTreeType' else None
        if tree is not None:
            for item in getattr(tree, "ssmt_submesh_items", []):
                name = str(getattr(item, "name", "") or "")
                if name:
                    width_texts.append(name)

        self.update_node_width(width_texts)

    def _refresh_index_info(self):
        """Refresh the IndexCount/FirstIndex display based on submesh_name."""
        self.index_count_display = ""
        self.first_index_display = ""

        submesh_name = str(self.submesh_name or "").strip()
        if not submesh_name:
            return

        try:
            ws_model = WorkSpaceModel()
            parsed = ws_model.parse_any_format_name(submesh_name)
            if parsed and parsed["lod"] and parsed["draw_ib"]:
                ic = ws_model.get_index_count(parsed["lod"], parsed["draw_ib"], parsed["component"])
                fi = ws_model.get_first_index(parsed["lod"], parsed["draw_ib"], parsed["component"])
                self.index_count_display = str(ic)
                self.first_index_display = str(fi)
        except Exception:
            pass

    def update_object_name(self, context):
        self._refresh_display_fields()
        self._refresh_index_info()

        if self.object_name:
            obj = bpy.data.objects.get(self.object_name)
            if obj:
                self.object_id = ObjectPersistentIdManager.ensure_id(obj)
        else:
            self.object_id = ""

    def update_submesh_name(self, context):
        self._refresh_display_fields()
        self._refresh_index_info()

    object_name: bpy.props.StringProperty(name="Object Name", default="", update=update_object_name) #type: ignore
    object_id: bpy.props.StringProperty(name="Object ID", default="") #type: ignore
    original_object_name: bpy.props.StringProperty(name="Original Object Name", default="") #type: ignore
    component: bpy.props.StringProperty(name="Component", default="") #type: ignore
    submesh_name: bpy.props.StringProperty(name="Submesh", default="", update=update_submesh_name) #type: ignore
    index_count_display: bpy.props.StringProperty(name="IndexCount", default="") #type: ignore
    first_index_display: bpy.props.StringProperty(name="FirstIndex", default="") #type: ignore

    texture_slot_items: bpy.props.CollectionProperty(type=SSMTTextureSlotItem)  # type: ignore

    def init(self, context):
        self.outputs.new('SSMTSocketObject', "Object")
        self._add_texture_slot(slot_index=0)
        self._add_custom_shader_socket()

    def _get_texture_sockets(self):
        return [sock for sock in self.inputs if getattr(sock, "bl_idname", "") == 'SSMTSocketTexture']

    def _get_texture_socket_by_item_index(self, item_index):
        texture_sockets = self._get_texture_sockets()
        if 0 <= item_index < len(texture_sockets):
            return texture_sockets[item_index]
        return None

    def _get_custom_shader_sockets(self):
        return [
            sock for sock in self.inputs
            if getattr(sock, 'bl_idname', '') == 'SSMTSocketCustomShader'
        ]

    def _group_dynamic_input_sockets(self):
        """Keep Texture and CustomShader inputs in two contiguous groups.

        Blender appends new sockets, which otherwise makes an Object Info node
        alternate between Texture and CustomShader sockets as each group grows.
        Moving sockets preserves their links and their relative order.
        """
        texture_count = len(self._get_texture_sockets())
        # Stable partition: repeatedly move the next Texture socket into the
        # Texture block. Looking sockets up again after every move avoids stale
        # RNA wrappers in Blender 5.2.
        for target_index in range(texture_count):
            current_index = next(
                index
                for index, socket in enumerate(self.inputs)
                if index >= target_index
                and getattr(socket, "bl_idname", "") == 'SSMTSocketTexture'
            )
            if current_index != target_index:
                self.inputs.move(current_index, target_index)

    def _add_custom_shader_socket(self):
        self.inputs.new('SSMTSocketCustomShader', 'CustomShader')
        self._group_dynamic_input_sockets()

    def ensure_custom_shader_socket(self):
        if not self._get_custom_shader_sockets():
            self._add_custom_shader_socket()

    def _get_next_texture_slot_index(self):
        existing = {item.slot_index for item in self.texture_slot_items}
        idx = 0
        while idx in existing:
            idx += 1
        return idx

    def _add_texture_slot(self, slot_index=None):
        if slot_index is None:
            slot_index = self._get_next_texture_slot_index()
        # Sockets use neutral names: slot semantics are only determined by the matching slot item once linked
        self.inputs.new('SSMTSocketTexture', "Texture")
        self._group_dynamic_input_sockets()
        item = self.texture_slot_items.add()
        item.slot_index = slot_index


    def update(self):
        self._group_dynamic_input_sockets()
        # Texture slots are entirely link-driven: always keep exactly one unlinked empty slot at the end
        texture_sockets = self._get_texture_sockets()
        if texture_sockets and texture_sockets[-1].is_linked:
            self._add_texture_slot()
            texture_sockets = self._get_texture_sockets()
        while len(texture_sockets) > 1 and not texture_sockets[-1].is_linked and not texture_sockets[-2].is_linked:
            self.inputs.remove(texture_sockets[-1])
            texture_sockets = self._get_texture_sockets()
        self._sync_texture_slot_items()

        self.ensure_custom_shader_socket()
        custom_shader_sockets = self._get_custom_shader_sockets()
        if custom_shader_sockets and custom_shader_sockets[-1].is_linked:
            self._add_custom_shader_socket()
            custom_shader_sockets = self._get_custom_shader_sockets()
        while (
            len(custom_shader_sockets) > 1
            and not custom_shader_sockets[-1].is_linked
            and not custom_shader_sockets[-2].is_linked
        ):
            self.inputs.remove(custom_shader_sockets[-1])
            custom_shader_sockets = self._get_custom_shader_sockets()
        self._group_dynamic_input_sockets()

    def _sync_texture_slot_items(self):
        """Keep texture_slot_items in one-to-one correspondence with the texture input sockets."""
        socket_count = len(self._get_texture_sockets())
        while len(self.texture_slot_items) < socket_count:
            item = self.texture_slot_items.add()
            item.slot_index = self._get_next_texture_slot_index()
        while len(self.texture_slot_items) > socket_count:
            self.texture_slot_items.remove(len(self.texture_slot_items) - 1)

    def link_texture_node(self, texture_node, slot_index: int):
        """Link the Texture node's Slot output to the first free texture input and record the slot number."""
        self._sync_texture_slot_items()
        texture_sockets = self._get_texture_sockets()
        target_socket = None
        target_item_index = -1
        for idx, socket in enumerate(texture_sockets):
            if not socket.is_linked:
                target_socket = socket
                target_item_index = idx
                break
        if target_socket is None:
            self._add_texture_slot()
            texture_sockets = self._get_texture_sockets()
            target_socket = texture_sockets[-1]
            target_item_index = len(texture_sockets) - 1
        item = self.texture_slot_items[target_item_index]
        item.slot_index = slot_index
        self.id_data.links.new(texture_node.outputs["Slot"], target_socket)
        return item

    def draw_buttons(self, context, layout):
        tree = self.id_data if getattr(self, "id_data", None) and getattr(self.id_data, "bl_idname", "") == 'SSMTBlueprintTreeType' else None
        row = layout.row(align=True)

        row.prop_search(self, "object_name", bpy.data, "objects", text="", icon='OBJECT_DATA')
        
        op = row.operator("ssmt.start_pick_object", text="", icon='EYEDROPPER')
        op.node_name = self.name
        op.tree_name = tree.name if tree else ""

        if self.object_name or self.object_id:
            op = row.operator("ssmt.select_node_object", text="", icon='RESTRICT_SELECT_OFF')
            op.object_name = self.object_name
            op.object_id = self.object_id

        if tree is not None:
            layout.prop_search(self, "submesh_name", tree, "ssmt_submesh_items", text="Submesh", icon='OUTLINER_COLLECTION')

            if self.submesh_name:
                layout.label(text=f"IndexCount: {self.index_count_display or '—'}")
                layout.label(text=f"FirstIndex: {self.first_index_display or '—'}")

            if self.submesh_name and self.submesh_name not in BlueprintExportHelper.get_tree_submesh_names(tree=tree):
                layout.label(text="Current Submesh is not in the list; export will fall back to object name resolution", icon='ERROR')

        # Texture slot configuration only matters once textures are linked, so only linked slots are shown
        texture_sockets = self._get_texture_sockets()
        box = None
        for idx, item in enumerate(self.texture_slot_items):
            socket = texture_sockets[idx] if idx < len(texture_sockets) else None
            if socket is None or not socket.is_linked:
                continue
            if box is None:
                box = layout.box()
                box.label(text="Texture Slot", icon='IMAGE_DATA')
            col = box.column(align=True)
            row = col.row(align=True)
            linked_node = socket.links[0].from_node if socket.links else None
            linked_label = str(getattr(linked_node, "texture_hash", "") or getattr(linked_node, "label", "") or "")
            row.label(text=linked_label, icon='IMAGE_DATA')
            row.prop(item, "slot_type", text="")
            if item.slot_type == 'PS_T':
                row.prop(item, "slot_index", text="")
            if item.slot_type == 'CUSTOM':
                col.prop(item, "custom_slot_key", text="Custom Key")
            col.label(text="Effective Key Name: " + item.effective_slot_key)

        for socket in self._get_custom_shader_sockets():
            if not socket.is_linked:
                continue
            linked_node = socket.links[0].from_node if socket.links else None
            mark_name = str(getattr(linked_node, 'mark_name', '') or '').strip()
            layout.label(
                text='CustomShader ' + (mark_name or '?'),
                icon='NODE_COMPOSITING',
            )




class SSMTNode_Object_Group(SSMTNodeBase):
    '''Node used purely for grouping; accepts any node as input and gathers it into one group'''
    bl_idname = 'SSMTNode_Object_Group'
    bl_label = 'Group'
    bl_icon = 'GROUP'

    def init(self, context):
        self.inputs.new('SSMTSocketObject', "Input 1")
        self.outputs.new('SSMTSocketObject', "Output")
        self.width = 200

    def draw_buttons(self, context, layout):
        layout.operator("ssmt.view_group_objects", text="Preview Recursive Objects", icon='HIDE_OFF').node_name = self.name

    def update(self):
        if self.inputs and self.inputs[-1].is_linked:
            self.inputs.new('SSMTSocketObject', "Input {count}".format(count=len(self.inputs) + 1))
        
        if len(self.inputs) > 1 and not self.inputs[-1].is_linked and not self.inputs[-2].is_linked:
             self.inputs.remove(self.inputs[-1])




class SSMT_OT_SwitchKey_AddSocket(bpy.types.Operator):
    '''Add a new socket to the switch node'''
    bl_idname = "ssmt.switch_add_socket"
    bl_label = "Add Socket"
    bl_options = {'REGISTER', 'UNDO'}
    
    node_name: bpy.props.StringProperty() # type: ignore

    def execute(self, context):
        tree = getattr(context.space_data, "edit_tree", None) or getattr(context.space_data, "node_tree", None)
        if not tree:
             return {'CANCELLED'}
        node = tree.nodes.get(self.node_name)
        if node:
               node.inputs.new('SSMTSocketObject', "Status {count}".format(count=len(node.inputs)))
        return {'FINISHED'}


class SSMT_OT_SwitchKey_RemoveSocket(bpy.types.Operator):
    '''Remove the last socket from the switch node'''
    bl_idname = "ssmt.switch_remove_socket"
    bl_label = "Remove Socket"
    bl_options = {'REGISTER', 'UNDO'}
    
    node_name: bpy.props.StringProperty() # type: ignore

    def execute(self, context):
        tree = getattr(context.space_data, "edit_tree", None) or getattr(context.space_data, "node_tree", None)
        if not tree:
             return {'CANCELLED'}
        node = tree.nodes.get(self.node_name)
        if node and len(node.inputs) > 0:
            node.inputs.remove(node.inputs[-1])
        return {'FINISHED'}


class SSMTNode_SwitchKey(SSMTNodeBase):
    '''Switch Key assigns each connected branch to its own separate variable'''
    bl_idname = 'SSMTNode_SwitchKey'
    bl_label = 'Switch Key'
    bl_icon = 'GROUP'

    def update_key_name(self, context):
        self.update_node_width([self.key_name, self.key_alias, self.comment])

    def update_key_alias(self, context):
        sanitized_alias = "".join(
            char for char in str(self.key_alias or "")
            if char.isascii() and char.isalnum()
        )
        if self.key_alias != sanitized_alias:
            self.key_alias = sanitized_alias
            return
        self.update_node_width([self.key_name, self.key_alias, self.comment])
    
    def update_comment(self, context):
        self.update_node_width([self.key_name, self.key_alias, self.comment])
    
    key_name: bpy.props.StringProperty(name="Key Name", default="", update=update_key_name) # type: ignore
    key_alias: bpy.props.StringProperty(name="Variable Alias", description="Only ASCII letters and digits are allowed; the same alias shares a variable and different branch counts expand by least common multiple", default="", update=update_key_alias) # type: ignore
    comment: bpy.props.StringProperty(name="Comment", description="Comment text; written into the config table as comments", default="", update=update_comment) # type: ignore
    
    def init(self, context):
        self.label = "Switch Key"
        self.inputs.new('SSMTSocketObject', "Status 0")
        self.outputs.new('SSMTSocketObject', "Output")
        self.width = 200
        self.use_custom_color = True
        self.color = (0.34, 0.54, 0.34)

    def draw_buttons(self, context, layout):
        row = layout.row(align=True)
        row.prop(self, "key_name", text="Key")
        row.operator("wm.url_open", text="", icon='HELP').url = "https://learn.microsoft.com/en-us/windows/win32/inputdev/virtual-key-codes"
        
        layout.prop(self, "key_alias", text="Variable Alias")
        layout.prop(self, "comment", text="Comment")
        
        row = layout.row(align=True)
        op_add = row.operator("ssmt.switch_add_socket", text="Add", icon='ADD')
        op_add.node_name = self.name
        
        op_rem = row.operator("ssmt.switch_remove_socket", text="Remove", icon='REMOVE')
        op_rem.node_name = self.name


class SSMTNode_Result_Output(SSMTNodeBase):
    '''Result Output Node'''
    bl_idname = 'SSMTNode_Result_Output'
    bl_label = 'Generate Mod'
    bl_icon = 'EXPORT'

    enable_shapekey: bpy.props.BoolProperty(
        name="Use Shape Key Options",
        description="Export the checked shape key buffers and runtime control config",
        default=False,
    ) # type: ignore
    shapekey_items: bpy.props.CollectionProperty(type=SSMTShapeKeyListItem) # type: ignore

    ini_filename: bpy.props.StringProperty(
        name="Child INI File Name",
        description="Sub-config name used when chaining outputs; written as .cfg to avoid duplicate recursive loading",
        default="",
    )  # type: ignore

    def init(self, context):
        self.outputs.new('SSMTSocketObject', "Output")
        self.inputs.new('SSMTSocketObject', "Group 1")
        self.width = 400

    def draw_buttons(self, context, layout):
        operator = layout.operator("ssmt.generate_mod_blueprint", text="Generate Mod", icon='EXPORT')
        operator.node_name = self.name
        operator.tree_name = self.id_data.name if self.id_data else ""
        layout.prop(self, "ini_filename", text="Child INI File Name")

        from .blueprint_node_shapekey import draw_shapekey_settings
        draw_shapekey_settings(self, layout)
        
        if GlobalConfig.logic_name == LogicName.WWMI:
            layout.prop(context.scene.global_properties, "ignore_muted_shape_keys")
            layout.prop(context.scene.global_properties, "apply_all_modifiers")
            layout.prop(context.scene.global_properties, "export_add_missing_vertex_groups")

        if GlobalConfig.logic_name != LogicName.GF2:
            layout.prop(context.scene.global_properties,
                        "recalculate_tangent",text="Store Vector-Normalized Normals in TANGENT (Global)")

        if GlobalConfig.logic_name == LogicName.HIMI:
            layout.prop(context.scene.global_properties,
                        "recalculate_color",text="Store Arithmetic-Average Normals in COLOR (Global)")

        if LogicName.is_zzmi_family(GlobalConfig.logic_name):
            layout.prop(context.scene.global_properties, "zzz_use_slot_fix")

        if GlobalConfig.logic_name == LogicName.GIMI:
            layout.prop(context.scene.global_properties, "gimi_use_orfix")

        layout.prop(context.scene.global_properties, "open_mod_folder_after_generate_mod",text="Open Mod Folder After Generating Mod")

        layout.prop(context.scene.global_properties, "use_specific_generate_mod_folder_path")

        if GlobalProperties.use_specific_generate_mod_folder_path():
            box = layout.box()
            box.label(text="Current Generate Mod Folder: ")
            box.label(text=context.scene.global_properties.generate_mod_folder_path)

            layout.operator("ssmt.select_generate_mod_folder", icon='FILE_FOLDER')
        
        # Add a button to go back to the previous level
        layout.separator()
        row = layout.row(align=True)
        row.operator("ssmt.blueprint_nest_navigate", text="Back to Previous Level", icon='BACK')

    def update(self):
        if len(self.outputs) == 0:
            self.outputs.new('SSMTSocketObject', "Output")
        if self.inputs and self.inputs[-1].is_linked:
            self.inputs.new('SSMTSocketObject', "Group {count}".format(count=len(self.inputs) + 1))
        
        if len(self.inputs) > 1 and not self.inputs[-1].is_linked and not self.inputs[-2].is_linked:
             self.inputs.remove(self.inputs[-1])


class SSMT_OT_View_Group_Objects(bpy.types.Operator):
    '''Recursively resolve all objects under the current group and display them in the current 3D View; clicking toggles local view. Note: group nodes should preferably not contain Switch Key, otherwise all switch branches are shown at once'''
    bl_idname = "ssmt.view_group_objects"
    bl_label = "View Objects in Group"
    
    node_name: bpy.props.StringProperty() # type: ignore

    def execute(self, context):
        tree = getattr(context.space_data, "edit_tree", None) or getattr(context.space_data, "node_tree", None)
        if not tree:
             return {'CANCELLED'}
        node = tree.nodes.get(self.node_name)
        if not node:
             return {'CANCELLED'}

        # Find a 3D View in the current context to keep area and screen consistent
        view_3d_area = None
        target_window = None
        target_screen = context.screen

        # Search the current screen first
        for area in target_screen.areas:
            if area.type == 'VIEW_3D':
                view_3d_area = area
                break

        # If the current screen has none, search other windows/screens
        if not view_3d_area:
            for window in context.window_manager.windows:
                for area in window.screen.areas:
                    if area.type == 'VIEW_3D':
                        view_3d_area = area
                        target_window = window
                        target_screen = window.screen
                        break
                if view_3d_area:
                    break

        if not view_3d_area:
            self.report({'WARNING'}, "No 3D View found")
            return {'CANCELLED'}

        in_local_view = False
        for space in view_3d_area.spaces:
            if space.type == 'VIEW_3D' and space.local_view:
                in_local_view = True
                break

        if in_local_view:
            # Exit local view safely
            try:
                if target_window:
                    with context.temp_override(window=target_window, area=view_3d_area, screen=target_screen):
                        bpy.ops.view3d.localview()
                else:
                    with context.temp_override(area=view_3d_area, screen=target_screen):
                        bpy.ops.view3d.localview()
            except Exception:
                # Fallback: modify the space data directly instead of using the operator
                for space in view_3d_area.spaces:
                    if space.type == 'VIEW_3D':
                        space.local_view = None
                        break
            self.report({'INFO'}, "Exited local view")
            return {'FINISHED'}

        objects_to_show = set()
        checked_nodes = set()
        visited_blueprints = set()

        def collect_objects(current_node):
            if current_node in checked_nodes:
                return
            checked_nodes.add(current_node)

            if getattr(current_node, "bl_idname", "") == 'SSMTNode_Object_Info':
                obj_name = getattr(current_node, "object_name", "")
                if obj_name:
                    obj = bpy.data.objects.get(obj_name)
                    if obj:
                        objects_to_show.add(obj)


            if hasattr(current_node, "inputs"):
                for inp in current_node.inputs:
                    if inp.is_linked:
                        for link in inp.links:
                            collect_objects(link.from_node)

        collect_objects(node)

        if not objects_to_show:
            self.report({'WARNING'}, "No objects found in this group")
            return {'CANCELLED'}

        def deselect_all_safe():
            for o in bpy.context.selected_objects:
                o.select_set(False)

        if context.mode != 'OBJECT':
            try:
                bpy.ops.object.mode_set(mode='OBJECT')
            except Exception:
                pass

        deselect_all_safe()
        for obj in objects_to_show:
            obj.select_set(True)

        # Get the 3D View space and configure it
        view_3d_space = None
        for space in view_3d_area.spaces:
            if space.type == 'VIEW_3D':
                view_3d_space = space
                break

        if view_3d_space:
            # Set the shading type directly
            view_3d_space.shading.type = 'SOLID'

            # Find a valid region
            region = next((r for r in view_3d_area.regions if r.type == 'WINDOW'), None)

            if region:
                # Build a complete override context including window/screen/area/region
                try:
                    override_kwargs = {
                        'area': view_3d_area,
                        'region': region,
                        'screen': target_screen
                    }
                    if target_window:
                        override_kwargs['window'] = target_window

                    with context.temp_override(**override_kwargs):
                        try:
                            bpy.ops.view3d.localview()
                            bpy.ops.view3d.view_axis(type='FRONT')
                            bpy.ops.view3d.view_selected()
                        except Exception as e:
                            print(f"View setup warning: {e}")
                except TypeError as e:
                    # If temp_override still fails, fall back: do not use the operator
                    print(f"temp_override failed, using fallback: {e}")
                    # At least the shading type was set; inform the user
                    self.report({'WARNING'}, "Objects are selected, but the view switch failed. Press '/' to enter local view manually")

        self.report({'INFO'}, "Showing {count} objects in local view".format(count=len(objects_to_show)))
        return {'FINISHED'}


class SSMT_OT_SelectGenerateModFolder(bpy.types.Operator, ImportHelper):
    '''Choose the target folder for the generated Mod'''
    bl_idname = "ssmt.select_generate_mod_folder"
    bl_label = "Select Generate Mod Folder"

    directory: bpy.props.StringProperty(subtype='DIR_PATH') # type: ignore
    filter_folder: bpy.props.BoolProperty(default=True, options={'HIDDEN'}) # type: ignore
    filter_image: bpy.props.BoolProperty(default=False, options={'HIDDEN'}) # type: ignore

    def invoke(self, context, event):
        current_directory = context.scene.global_properties.generate_mod_folder_path
        if current_directory:
            self.directory = bpy.path.abspath(current_directory)
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        selected_directory = bpy.path.abspath(self.directory).rstrip("\\/")
        if not selected_directory:
            self.report({'ERROR'}, "Please select a valid folder")
            return {'CANCELLED'}

        os.makedirs(selected_directory, exist_ok=True)
        context.scene.global_properties.generate_mod_folder_path = selected_directory
        self.report({'INFO'}, "Generate Mod folder set to: {path}".format(path=selected_directory))
        return {'FINISHED'}

classes = (
    SSMT_OT_SelectGenerateModFolder,
    SSMT_OT_RefreshNodeObjectIDs,
    SSMT_OT_SelectNodeObject,
    SSMT_OT_StartPickObject,
    SSMT_OT_PickObjectModal,
    SSMT_OT_View_Group_Objects,
    SSMTTextureSlotItem,
    SSMTNode_Object_Info,
    SSMTNode_Object_Group,
    SSMTNode_Result_Output,
    SSMTNode_SwitchKey,
    SSMT_OT_SwitchKey_AddSocket,
    SSMT_OT_SwitchKey_RemoveSocket,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    # During Blender registration bpy.data can still be _RestrictData, which
    # does not expose node_groups.  Existing blueprints are refreshed later
    # when normal data access is available.
    node_groups = getattr(getattr(bpy, 'data', None), 'node_groups', ())
    for tree in node_groups:
        if getattr(tree, 'bl_idname', '') != 'SSMTBlueprintTreeType':
            continue
        for node in tree.nodes:
            if getattr(node, 'bl_idname', '') == SSMTNode_Object_Info.bl_idname:
                node.ensure_custom_shader_socket()
    bpy.types.VIEW3D_HT_header.append(draw_view3d_header)


def unregister():
    bpy.types.VIEW3D_HT_header.remove(draw_view3d_header)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
