
import bpy
import copy
import math
import re

from ..utils.log_utils import LOG
from ..utils.vertexgroup_utils import VertexGroupUtils

from ..common.m_key import M_Key
from ..common.mimi_global_properties import MIMIGlobalProperties
from .draw_call_model import DrawCallModel
from .submesh_model import SubMeshModel
from .drawib_model import DrawIBModel
from ..common.global_config import GlobalConfig
from ..blueprint.blueprint_export_helper import BlueprintExportHelper

from ..blueprint.blueprint_node_obj import MIMINode_Object_Group, MIMINode_SwitchKey, MIMINode_Object_Info, MIMINode_Result_Output
from ..blueprint.blueprint_node_object_list import MIMINode_Object_List
from ..blueprint.blueprint_node_texture import MIMINode_Texture_Bind, normalize_mark_name_enum_value
from ..blueprint.blueprint_node_hash_texture import (
    MIMINode_Hash_Texture_Bind,
    MIMINode_Hash_Texture_Global,
)
from ..blueprint.blueprint_node_time_switch import MIMINode_TimeSwitch
from ..blueprint.blueprint_node_time_pos_switch import MIMINode_TimePosSwitch

from ..blueprint.blueprint_node_group import (
    GROUP_INPUT_IDNAME,
    GROUP_NODE_IDNAME,
    GROUP_OUTPUT_IDNAME,
    _group_socket_for_interface,
)


class BluePrintModel:

    # 3Dmigoto lowercases INI tokens and rejects digit-leading variables.
    # Underscores are legal in the parser even when older node UIs omit them.
    _KEY_ALIAS_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
    
    def __init__(self, tree=None, context=None, output_node=None):
        # Global key name and key attribute dict
        self.keyname_mkey_dict:dict[str,M_Key] = {} 

        # Global obj_model list; each obj_model stores the active condition of its obj.
        self.ordered_draw_obj_data_model_list:list[DrawCallModel] = []

        # Unconnected global hash nodes are collected separately from the
        # object traversal, then every exporter can emit their replacements.
        self.global_hash_texture_binding_list:list[dict] = []

        # Temporary objects created by UniComponent splitting; must be cleaned up after export
        self._unico_temp_objects: list[bpy.types.Object] = []
        self._group_instance_stack: list[bpy.types.Node] = []

        # Recursively parse all nodes starting from the output node
        tree = tree or BlueprintExportHelper.get_current_blueprint_tree(context=context)
        if not tree:
            raise ValueError("No blueprint tree found; please open the correct blueprint editor")

        # Global hash nodes are intentionally independent of the output graph.
        # Collect them before traversing connected object nodes so an export
        # with only conditional objects still sees every global replacement.
        self.global_hash_texture_binding_list = self._collect_global_hash_texture_bindings(tree)

        # Nodes sharing an explicit alias share one INI variable.  Its period
        # is the LCM of the participating nodes' branch counts.
        self._switch_alias_state_counts = self._collect_switch_alias_state_counts(tree)

        # Switch Key nodes bound to the same hotkey (and without an explicit
        # alias) also merge into one shared variable: the INI then emits a
        # single [Key] section that cycles all of them in sync.  The merged
        # variable's period is the LCM of the participating branch counts,
        # exactly like an alias group.  This maps normalized key binding ->
        # LCM state count, pre-scanned before parsing starts.
        self._key_group_state_counts = self._collect_key_group_state_counts(tree)
        # Normalized key binding -> allocated shared $swapkeyN variable name,
        # filled lazily while parsing so every group member reuses one name.
        self._key_group_var_names: dict[str, str] = {}

        # Auto-allocated Time Switch variables use their own $dyntime counter,
        # kept apart from the $swapkey namespace of hotkey-driven switches.
        self._time_key_index = 0
        # Re-visiting a linked node under several outer branches must reuse
        # its clock instead of allocating a different timeline on each visit.
        self._time_node_key_names = {}

        # Time Position Switch tracking: the variable names allocated by Time
        # Position Switch nodes (a subset of the "time" key namespace) and the
        # DrawCallModels of their frame branches.  Frame draw calls are moved
        # out of ordered_draw_obj_data_model_list after parsing (they only
        # provide per-frame Position bytes, never their own drawindexed call).
        self.time_pos_key_names: set[str] = set()
        self.time_pos_frame_models: list[DrawCallModel] = []

        print(tree)
        output_node = output_node or BlueprintExportHelper.get_node_from_bl_idname(
            tree, MIMINode_Result_Output.bl_idname
        )
        if not output_node:
            raise ValueError("The current blueprint is missing the Generate Mod output node")

        print("BluePrintModel: number of nodes connected to the output node: " + str(len(BlueprintExportHelper.get_connected_nodes(output_node))))
        self.parse_current_node(output_node, [])

        # Move Time Position Switch frame draw calls out of the normal draw
        # list before any game post-processor sees them.
        self._reclassify_time_pos_frames()

        # Fail loudly when the current game preset cannot drive position
        # buffer switching at all (checked here so every exporter benefits).
        from ..common.m_time_position import get_time_position_support_error
        support_error = get_time_position_support_error(self)
        if support_error:
            raise ValueError(support_error)

        # Game-specific tree post-processors (e.g. Naraka cross-IB pairs) run
        # after the whole tree has been parsed into DrawCallModels.  The
        # registry keeps this shared model free of per-game logic.
        from ..games import get_tree_post_processor
        tree_post_processor = get_tree_post_processor(GlobalConfig.logic_name)
        if tree_post_processor is not None:
            tree_post_processor(tree, self)

    @classmethod
    def _normalize_switch_key_alias(cls, switch_node: bpy.types.Node) -> str:
        alias = str(getattr(switch_node, "key_alias", "") or "").strip()
        if alias == "":
            return ""
        if cls._KEY_ALIAS_PATTERN.fullmatch(alias) is None:
            raise ValueError("The variable alias of a key switch node must start with an ASCII letter or underscore and contain only ASCII letters, digits or underscores: " + alias)
        # Internal animation/activation variables share the same INI namespace.
        # Reject collisions rather than emitting two declarations for one name.
        alias = alias.lower()
        if re.fullmatch(r"active\d+|shapekey\d+(_frame)?|shapekey_first_run", alias) or alias.startswith("mimi_"):
            raise ValueError("This variable alias is reserved by the exporter: " + alias)
        return "$" + alias

    @classmethod
    def _normalize_time_alias(cls, time_node: bpy.types.Node) -> str:
        alias = str(getattr(time_node, "time_alias", "") or "").strip()
        if alias == "":
            return ""
        if cls._KEY_ALIAS_PATTERN.fullmatch(alias) is None:
            raise ValueError("The time variable alias of a dynamic mod timeline node must start with an ASCII letter or underscore and contain only ASCII letters, digits or underscores: " + alias)
        # Internal animation/activation variables share the same INI namespace.
        # Reject collisions rather than emitting two declarations for one name.
        alias = alias.lower()
        if re.fullmatch(r"active\d+|shapekey\d+(_frame)?|shapekey_first_run", alias) or alias.startswith("mimi_"):
            raise ValueError("This variable alias is reserved by the exporter: " + alias)
        return "$" + alias

    def _allocate_time_key_name(self, time_node: bpy.types.Node) -> str:
        # An explicit alias names the shared timeline variable directly;
        # otherwise allocate the next free $dyntimeN name.
        key_alias = self._normalize_time_alias(time_node)
        if key_alias:
            return key_alias

        identity = tuple(group.as_pointer() for group in self._group_instance_stack) + (time_node.as_pointer(),)
        if identity in self._time_node_key_names:
            return self._time_node_key_names[identity]
        key_name = "$dyntime" + str(self._time_key_index)
        while (
            key_name in self.keyname_mkey_dict
            or key_name in self._switch_alias_state_counts
        ):
            self._time_key_index = self._time_key_index + 1
            key_name = "$dyntime" + str(self._time_key_index)
        self._time_node_key_names[identity] = key_name
        return key_name

    @classmethod
    def _normalize_switch_key_binding(cls, key_name: str) -> str:
        # 3Dmigoto parses key bindings case-insensitively and ignores extra
        # whitespace, so group Switch Key nodes by this normalized form:
        # "ctrl f6", "CTRL  F6" and "Ctrl F6" all mean the same hotkey.
        return " ".join(str(key_name or "").upper().split())

    @classmethod
    def _collect_key_group_state_counts(cls, root_tree) -> dict[str, int]:
        # Pre-scan every reachable tree for Switch Key nodes without an
        # explicit alias: nodes bound to the same normalized hotkey merge
        # into one variable whose period is the LCM of their branch counts.
        # Nodes with an alias are skipped here; they merge by alias instead.
        counts: dict[str, list[int]] = {}
        visited_trees = set()

        def visit(tree):
            if tree is None or id(tree) in visited_trees:
                return
            visited_trees.add(id(tree))
            for node in getattr(tree, "nodes", []):
                if getattr(node, "bl_idname", "") == MIMINode_SwitchKey.bl_idname:
                    key_binding = cls._normalize_switch_key_binding(getattr(node, "key_name", ""))
                    branch_count = len(getattr(node, "inputs", []))
                    if key_binding and not cls._normalize_switch_key_alias(node) and branch_count > 1:
                        counts.setdefault(key_binding, []).append(branch_count)
                if getattr(node, "bl_idname", "") == GROUP_NODE_IDNAME:
                    visit(getattr(node, "node_tree", None))

        visit(root_tree)
        # Reuse the alias-group cap: LCM expansion can explode for relatively
        # prime branch counts, so bound it before lists are built.
        periods = {binding: math.lcm(*sizes) for binding, sizes in counts.items()}
        if any(period > 10000 for period in periods.values()):
            raise ValueError("Switch Key nodes sharing one hotkey may expand to at most 10000 states")
        return periods

    def _next_free_switch_key_name(self) -> str:
        # Allocate the next unused $swapkeyN name; aliases and already shared
        # key-group variables occupy the same namespace and must be skipped.
        key_name = "$swapkey" + str(GlobalConfig.global_key_index)
        while (
            key_name in self.keyname_mkey_dict
            or key_name in self._switch_alias_state_counts
        ):
            GlobalConfig.global_key_index = GlobalConfig.global_key_index + 1
            key_name = "$swapkey" + str(GlobalConfig.global_key_index)

        if key_name in self.keyname_mkey_dict:
            raise ValueError("Duplicate variable name of a key switch node: " + key_name)
        return key_name

    def _allocate_switch_key_name(self, switch_node: bpy.types.Node) -> tuple[str, bool]:
        key_alias = self._normalize_switch_key_alias(switch_node)
        if key_alias:
            return key_alias, False

        # Without an explicit alias, nodes bound to the same hotkey merge
        # into one shared variable, so the INI emits a single [Key] section
        # that cycles every participating node in sync.  An empty key keeps
        # the legacy behavior: every node gets its own variable.
        key_binding = self._normalize_switch_key_binding(getattr(switch_node, "key_name", ""))
        if key_binding:
            shared_key_name = self._key_group_var_names.get(key_binding)
            if shared_key_name is not None:
                return shared_key_name, False
            key_name = self._next_free_switch_key_name()
            self._key_group_var_names[key_binding] = key_name
            # Key the pre-scanned LCM state count by the allocated variable
            # name so the parser sizes value_list exactly like an alias group.
            state_count = self._key_group_state_counts.get(key_binding)
            if state_count is not None:
                self._switch_alias_state_counts[key_name] = state_count
            return key_name, True

        return self._next_free_switch_key_name(), True

    @classmethod
    def _collect_switch_alias_state_counts(cls, root_tree) -> dict[str, int]:
        counts: dict[str, list[int]] = {}
        visited_trees = set()

        def visit(tree):
            if tree is None or id(tree) in visited_trees:
                return
            visited_trees.add(id(tree))
            for node in getattr(tree, "nodes", []):
                if getattr(node, "bl_idname", "") == MIMINode_SwitchKey.bl_idname:
                    alias = cls._normalize_switch_key_alias(node)
                    branch_count = len(getattr(node, "inputs", []))
                    if alias and branch_count > 1:
                        counts.setdefault(alias, []).append(branch_count)
                # Time Switch aliases live in the same variable namespace:
                # one shared timeline variable per alias, LCM period included.
                # Time Position Switch uses the same time_alias property, so
                # the same scan covers both node types.
                if getattr(node, "bl_idname", "") in (
                    MIMINode_TimeSwitch.bl_idname,
                    MIMINode_TimePosSwitch.bl_idname,
                ):
                    alias = cls._normalize_time_alias(node)
                    branch_count = len(getattr(node, "inputs", []))
                    if alias and branch_count > 1:
                        counts.setdefault(alias, []).append(branch_count)
                if getattr(node, "bl_idname", "") == GROUP_NODE_IDNAME:
                    visit(getattr(node, "node_tree", None))

        visit(root_tree)
        # LCM expansion can explode for relatively prime branch counts.
        # Bound it before building lists or traversing every generated state.
        periods = {alias: math.lcm(*sizes) for alias, sizes in counts.items()}
        if any(period > 10000 for period in periods.values()):
            raise ValueError("Shared switch aliases may expand to at most 10000 states")
        return periods

    def parse_current_node(self, current_node:bpy.types.Node, chain_key_list:list[M_Key]):
        for input_socket in current_node.inputs:
            for link in input_socket.links:
                if link.from_node.bl_idname == GROUP_INPUT_IDNAME:
                    self._parse_group_input(link.from_node, link.from_socket, chain_key_list)
                else:
                    # The from_socket matters for fan-out source nodes such as
                    # Object List, where each output socket carries a
                    # different subset of the contained objects.
                    self.parse_single_node(link.from_node, chain_key_list, link.from_socket)

    def parse_single_node(self, unknown_node:bpy.types.Node, chain_key_list:list[M_Key], from_socket:bpy.types.NodeSocket=None):
        """Reject cycles on the active path without suppressing valid fan-out."""
        # A global visited set would incorrectly drop repeated objects in
        # separate switch branches. Only nodes on the current path are cycles.
        # Socket identity permits independent outputs of one group instance.
        node_id = unknown_node.as_pointer() if hasattr(unknown_node, "as_pointer") else id(unknown_node)
        socket_id = from_socket.as_pointer() if hasattr(from_socket, "as_pointer") else id(from_socket)
        # Two sequential instances of the same group share child RNA nodes,
        # but are not a cycle. Include the current instance context in the key.
        instances = tuple(node.as_pointer() if hasattr(node, "as_pointer") else id(node) for node in getattr(self, "_group_instance_stack", ()))
        key = (node_id, socket_id, instances)
        if not hasattr(self, "_active_parse_path"):
            self._active_parse_path = set()
        if key in self._active_parse_path:
            raise ValueError("Blueprint contains a cycle at node: " + unknown_node.name)
        self._active_parse_path.add(key)
        try:
            return self._parse_single_node_impl(unknown_node, chain_key_list, from_socket)
        finally:
            self._active_parse_path.remove(key)

    def _parse_single_node_impl(self, unknown_node:bpy.types.Node, chain_key_list:list[M_Key], from_socket:bpy.types.NodeSocket=None):
        '''
        Recursive method.
        Parse the current node, gathering info about all nodes connected to it and parsing them by type.
        '''
        
        if unknown_node.mute:
            return

        if unknown_node.bl_idname == GROUP_NODE_IDNAME:
            self._parse_custom_group(unknown_node, chain_key_list, from_socket)

        elif unknown_node.bl_idname == GROUP_INPUT_IDNAME:
            # Switch/timeline branches call parse_single_node directly too.
            # Resolve group inputs here rather than only in plain groups.
            self._parse_group_input(unknown_node, from_socket, chain_key_list)

        elif unknown_node.bl_idname == 'NodeReroute':
            # Rerouting a wire must not silently remove its objects at export.
            self.parse_current_node(unknown_node, chain_key_list)

        elif unknown_node.bl_idname == MIMINode_Object_Group.bl_idname:
            # If it is a plain group node, pass through without further processing
            self.parse_current_node(unknown_node, chain_key_list)

        elif unknown_node.bl_idname == MIMINode_SwitchKey.bl_idname:
            # If it is a key switch node, take all of its branch nodes and process them one by one.
            # Here we iterate over all inputs directly instead of using get_connected_nodes,
            # because get_connected_nodes ignores unconnected (empty) sockets and would compute a wrong branch count.

            # Every Input of a SwitchKey node is an effective branch, since sockets can be
            # added/removed manually and an empty socket means an empty state (nothing is shown)
            valid_input_sockets = unknown_node.inputs[:]

            # If no sockets are connected at all, skip this node entirely
            is_all_socket_linked = False
            for sock in valid_input_sockets:
                if sock.is_linked:
                    is_all_socket_linked = True
                    break

            if not is_all_socket_linked:
                # If nothing is connected, do nothing
                return

            if len(valid_input_sockets) == 1:
                # If there is only 1 effective branch socket:
                # 1. If it is connected -> treat it as a Group node pass-through
                # 2. If it is disconnected -> ignore it (already filtered by all_socket_linked above)
                if valid_input_sockets[0].is_linked:
                        for link in valid_input_sockets[0].links:
                            self.parse_single_node(link.from_node, chain_key_list, link.from_socket)
            else:
                # With more than 1 effective branch socket, a Key must be created even when some sockets are empty (they stand for empty branches)
                m_key = M_Key()
                current_add_key_index = len(self.keyname_mkey_dict.keys())
                m_key.key_name, uses_auto_key_name = self._allocate_switch_key_name(unknown_node)

                state_count = self._switch_alias_state_counts.get(
                    m_key.key_name, len(valid_input_sockets)
                )
                m_key.value_list = list(range(state_count))

                m_key.initialize_vk_str = unknown_node.key_name
                m_key.initialize_value = 0  # Select the first branch by default

                # Set the comment field
                m_key.comment = getattr(unknown_node, 'comment', '')

                # Nodes sharing an explicit alias create one global Key; the LCM state count was already determined in the pre-scan.
                existing_key = self.keyname_mkey_dict.get(m_key.key_name)
                if existing_key is None:
                    self.keyname_mkey_dict[m_key.key_name] = m_key
                else:
                    # Check both traversal orders: a hotkey visited after a
                    # time node must not silently inherit its clock driver.
                    if existing_key.key_type != "key":
                        raise ValueError("A Switch Key node and a dynamic mod timeline node cannot share alias " + m_key.key_name)
                    m_key = existing_key

                # Update the global key index
                if uses_auto_key_name and len(self.keyname_mkey_dict.keys()) > current_add_key_index:
                    GlobalConfig.global_key_index = GlobalConfig.global_key_index + 1

                # Process each branch socket in turn (including empty branches)
                self._parse_branch_sockets(valid_input_sockets, m_key, state_count, chain_key_list)

        elif unknown_node.bl_idname == MIMINode_TimeSwitch.bl_idname:
            # Time Switch: a Switch Key variant whose variable is recomputed
            # from wall-clock time every frame instead of a hotkey.
            self._parse_time_switch_node(unknown_node, chain_key_list)

        elif unknown_node.bl_idname == MIMINode_TimePosSwitch.bl_idname:
            # Time Position Switch: same timeline parsing as Time Switch, but
            # the branch draw calls become per-frame Position side buffers
            # instead of conditional drawindexed calls.
            self._parse_time_switch_node(unknown_node, chain_key_list, is_position_switch=True)

        elif unknown_node.bl_idname == MIMINode_Texture_Bind.bl_idname:
            # Texture Bind is a transparent pass-through: parse the upstream
            # object chain first, then tag every DrawCallModel that this
            # visit produced with the node's slot bindings. Each visit news
            # its own DrawCallModels, so the same Object Info passing
            # through different branches/bind nodes stays independent.
            draw_model_count_before = len(self.ordered_draw_obj_data_model_list)
            self.parse_current_node(unknown_node, chain_key_list)
            bindings = self._collect_texture_bindings(unknown_node)
            if bindings:
                for obj_model in self.ordered_draw_obj_data_model_list[draw_model_count_before:]:
                    obj_model.texture_slot_binding_list = self._merge_texture_slot_bindings(
                        getattr(obj_model, "texture_slot_binding_list", []),
                        bindings,
                    )

        elif unknown_node.bl_idname == MIMINode_Hash_Texture_Bind.bl_idname:
            # Hash Texture Bind is a transparent pass-through like the Slot
            # variant; the resolved rows later merge into one global
            # [TextureOverride_Texture_<hash>] section per hash, so the same
            # "parse first, then tag the new models" pattern applies here.
            draw_model_count_before = len(self.ordered_draw_obj_data_model_list)
            self.parse_current_node(unknown_node, chain_key_list)
            bindings = self._collect_hash_texture_bindings(unknown_node)
            if bindings:
                for obj_model in self.ordered_draw_obj_data_model_list[draw_model_count_before:]:
                    obj_model.hash_texture_binding_list = self._merge_hash_texture_bindings(
                        getattr(obj_model, "hash_texture_binding_list", []),
                        bindings,
                    )

        elif unknown_node.bl_idname == MIMINode_Object_List.bl_idname:
            # Fan-out source: the link's from_socket decides what is emitted.
            # A per-item socket carries exactly that object; the leading
            # "All" socket (or a visit without socket info) emits every
            # enabled item in list order.
            node_label = str(getattr(unknown_node, "label", "") or getattr(unknown_node, "name", "") or "Object List")
            output_sockets = list(unknown_node.outputs)
            selected_items = list(unknown_node.object_items)
            if from_socket is not None:
                # A stale/foreign socket must not silently expand to All.
                # Fail before emitting unrelated geometry into the export.
                if from_socket not in output_sockets:
                    raise ValueError("Object List has an unknown output socket: " + node_label)
                output_index = output_sockets.index(from_socket)
                if output_index > len(unknown_node.object_items):
                    raise ValueError("Object List output has no matching item: " + node_label)
                if output_index > 0:
                    selected_items = [unknown_node.object_items[output_index - 1]]

            emitted_names = []
            for item in selected_items:
                if not item.enabled:
                    continue
                # Export may run before the rename-sync timer has ticked.
                # Read the stable pointer first without writing during traversal.
                object_ref = getattr(item, "object_ref", None)
                object_name = object_ref.name if object_ref is not None else str(getattr(item, "object_name", "") or "").strip()
                if not object_name:
                    LOG.warning("BluePrintModel: Object List node '" + node_label + "' has an empty object entry; skipped")
                    continue
                emitted_names.append(object_name)
                self._emit_object_source(
                    object_name=object_name,
                    submesh_name=str(getattr(item, "submesh_name", "") or ""),
                    original_object_name="",
                    chain_key_list=chain_key_list,
                )

            # Duplicate objects within one expansion would silently emit
            # duplicate drawindexed calls; fail loudly instead.
            normalized_names = [name.lower() for name in emitted_names]
            if len(set(normalized_names)) != len(normalized_names):
                duplicated = sorted({name for name in normalized_names if normalized_names.count(name) > 1})
                raise ValueError(
                    "Object List node '" + node_label + "' contains the same object more than once: "
                    + ", ".join(duplicated) + "; remove the duplicates or disable the extra entries."
                )

        elif unknown_node.bl_idname == MIMINode_Object_Info.bl_idname:
            # Nested groups may be parsed before their display names refresh.
            # Resolve UUIDs read-only so a reused name cannot redirect export.
            from ..blueprint.blueprint_node_obj import ObjectPersistentIdManager
            resolved = ObjectPersistentIdManager.resolve_node_target(unknown_node)
            self._emit_object_source(
                object_name=resolved.name if resolved is not None else str(unknown_node.object_name),
                submesh_name=str(getattr(unknown_node, 'submesh_name', '') or ""),
                original_object_name=str(getattr(unknown_node, 'original_object_name', '') or ""),
                chain_key_list=chain_key_list,
            )

        elif unknown_node.bl_idname == MIMINode_Result_Output.bl_idname:
            # Result Output nodes are composition boundaries.  The selected
            # output is handled as the root by __init__; any other output node
            # found upstream is never parsed into this INI layer.
            return

        elif unknown_node.bl_idname == "MIMINode_Face_Mod_Export":
            # Face Output is a composition boundary, just like the regular
            # Result Output.  Parsing its mesh inputs here would duplicate
            # them in the regular output layer.
            return

    def _emit_object_source(self, object_name: str, submesh_name: str, original_object_name: str, chain_key_list: list[M_Key]):
        '''Emit one DrawCallModel (or its UniComponent splits) for an object.

        Shared by the Object Info branch and the Object List branch so both
        nodes behave identically: empty meshes are filtered early, and
        UniComponent mode splits the object per Submesh VG range.
        '''
        obj = bpy.data.objects.get(object_name)

        # Filter empty meshes early while parsing the blueprint, so the later export step never hits the "all vertex groups locked" error.
        if obj is None or obj.type != 'MESH' or obj.data is None or len(obj.data.vertices) == 0:
            LOG.info("BluePrintModel: skipping empty mesh or invalid object: " + str(object_name))
            return

        # UniComponent mode: automatically detect and split the object
        if MIMIGlobalProperties.is_unico_component():
            split_results = self._unico_split_object(
                obj=obj,
                node_submesh_name=submesh_name,
            )
            for split_submesh_name, temp_obj in split_results:
                obj_model = DrawCallModel(
                    obj_name=temp_obj.name,
                    submesh_name=split_submesh_name,
                )
                obj_model.work_key_list = copy.deepcopy(chain_key_list)
                self.ordered_draw_obj_data_model_list.append(obj_model)
                self._unico_temp_objects.append(temp_obj)
                LOG.info(f"BluePrintModel: UniComponent split '{object_name}' -> "
                         f"submesh='{split_submesh_name}' parsed='{obj_model.match_submesh_name}' "
                         f"draw_ib='{obj_model.match_draw_ib}' (temporary object: '{temp_obj.name}')")
        else:
            # Legacy mode: use the original object directly
            obj_model = DrawCallModel(
                obj_name=object_name,
                submesh_name=submesh_name,
            )

            if original_object_name:
                obj_model.display_name = original_object_name

            obj_model.work_key_list = copy.deepcopy(chain_key_list)

            self.ordered_draw_obj_data_model_list.append(obj_model)

    @staticmethod
    def _collect_global_hash_texture_bindings(root_tree):
        '''Collect unconnected global hash rows from this tree and its groups.'''
        bindings = []
        visited_tree_ids = set()

        def visit_tree(tree):
            if tree is None:
                return
            tree_id = id(tree)
            if tree_id in visited_tree_ids:
                return
            visited_tree_ids.add(tree_id)

            for node in getattr(tree, "nodes", []):
                if getattr(node, "bl_idname", "") == MIMINode_Hash_Texture_Global.bl_idname:
                    # Muted nodes behave like every other muted blueprint node.
                    if not getattr(node, "mute", False):
                        node_label = str(getattr(node, "label", "") or getattr(node, "name", "") or "Global Hash Texture Bind")
                        for item in getattr(node, "texture_hash_items", []):
                            file_path = str(getattr(item, "file_path", "") or "").strip()
                            if file_path:
                                try:
                                    file_path = bpy.path.abspath(file_path)
                                except Exception:
                                    pass
                            bindings.append({
                                "enabled": bool(getattr(item, "enabled", True)),
                                "texture_hash": str(getattr(item, "texture_hash", "") or "").strip().lower(),
                                "source_type": str(getattr(item, "source_type", "") or ""),
                                "file_path": file_path,
                                "mark_name": str(getattr(item, "mark_source_name", "") or ""),
                                "mark_source_submesh": str(getattr(item, "mark_source_submesh", "") or ""),
                                "mark_source_file_path": str(getattr(item, "mark_source_file_path", "") or ""),
                                "resource_name": str(getattr(item, "resource_name", "") or ""),
                                "node_label": node_label,
                            })

                # A group may contain an unconnected global node. It is still
                # part of the current blueprint and must not be hidden by the
                # regular object-link traversal.
                if getattr(node, "bl_idname", "") == GROUP_NODE_IDNAME:
                    visit_tree(getattr(node, "node_tree", None))

        visit_tree(root_tree)
        return bindings

    @staticmethod
    def _collect_texture_bindings(bind_node):
        '''Read the Texture Bind node rows into plain dicts for the export pass.

        FILE paths are resolved to absolute paths here (bpy lives in this
        layer, not in the model layer) so DrawIBModel only sees real paths.
        '''
        bindings = []
        for item in getattr(bind_node, "texture_slot_items", []):
            file_path = str(getattr(item, "file_path", "") or "").strip()
            if file_path:
                try:
                    file_path = bpy.path.abspath(file_path)
                except Exception:
                    pass
            bindings.append({
                "enabled": bool(getattr(item, "enabled", True)),
                "slot": str(getattr(item, "slot", "") or ""),
                "source_type": str(getattr(item, "source_type", "") or ""),
                "mark_name": normalize_mark_name_enum_value(getattr(item, "mark_name", "")),
                "file_path": file_path,
                "resource_name": str(getattr(item, "resource_name", "") or ""),
                "restore_after_draw": bool(getattr(item, "restore_after_draw", False)),
                "node_label": str(getattr(bind_node, "label", "") or getattr(bind_node, "name", "") or "Slot Texture Bind"),
            })
        return bindings

    @staticmethod
    def _merge_texture_slot_bindings(inner_list, outer_list):
        '''Merge bindings of nested Texture Bind nodes, keyed by slot.

        The node closest to the Object Info node wins for the same slot
        (it is the most specific one); bindings for different slots add up.
        '''
        merged = {}
        order = []
        for binding in outer_list + inner_list:
            key = str(binding.get("slot", "")).strip().lower()
            if key not in merged:
                order.append(key)
            merged[key] = binding
        return [merged[key] for key in order]

    @staticmethod
    def _collect_hash_texture_bindings(bind_node):
        '''Read the Hash Texture Bind node rows into plain dicts for export.'''
        bindings = []
        for item in getattr(bind_node, "texture_hash_items", []):
            file_path = str(getattr(item, "file_path", "") or "").strip()
            if file_path:
                try:
                    file_path = bpy.path.abspath(file_path)
                except Exception:
                    pass
            bindings.append({
                "enabled": bool(getattr(item, "enabled", True)),
                "texture_hash": str(getattr(item, "texture_hash", "") or "").strip().lower(),
                "source_type": str(getattr(item, "source_type", "") or ""),
                "mark_name": normalize_mark_name_enum_value(getattr(item, "mark_name", "")),
                "file_path": file_path,
                "resource_name": str(getattr(item, "resource_name", "") or ""),
                "node_label": str(getattr(bind_node, "label", "") or getattr(bind_node, "name", "") or "Hash Texture Bind"),
            })
        return bindings

    @staticmethod
    def _merge_hash_texture_bindings(inner_list, outer_list):
        '''Merge bindings of nested Hash Texture Bind nodes, keyed by hash.

        Same rule as the slot variant: the node closest to the Object Info
        node wins for the same texture hash.
        '''
        merged = {}
        order = []
        for binding in outer_list + inner_list:
            key = str(binding.get("texture_hash", "")).strip().lower()
            if key not in merged:
                order.append(key)
            merged[key] = binding
        return [merged[key] for key in order]

    def _parse_branch_sockets(self, branch_sockets, m_key: M_Key, state_count: int, chain_key_list: list[M_Key]):
        """
        Process each branch socket of a switch-style node in turn (including
        empty branches, which map to a key value that draws nothing).
        Shared by the Switch Key node and the Time Switch node.
        """
        for branch_index, socket in enumerate(branch_sockets):
            # Whether a socket is connected to a node or left empty, it always maps to one key value
            if not socket.is_linked:
                # An empty (unconnected) socket means this value maps to an empty object
                # No parsing is needed here because no obj has to be generated under this condition
                # The key value stays in key.value_list, yet no obj condition will ever match it
                # This achieves the effect of "switching to this branch displays nothing"
                continue

            # If a socket is connected to a node, propagate the key for this value downstream for parsing
            matching_states = range(branch_index, state_count, len(branch_sockets))
            for state in matching_states:
                # Nested nodes with the same alias intersect the
                # existing state instead of emitting contradictions.
                existing_state = next(
                    (key.tmp_value for key in chain_key_list if key.key_name == m_key.key_name),
                    None,
                )
                if existing_state is not None and existing_state != state:
                    continue
                for link in socket.links:
                    tmp_chain_key_list = copy.deepcopy(chain_key_list)
                    if existing_state is None:
                        chain_tmp_key = copy.deepcopy(m_key)
                        chain_tmp_key.tmp_value = state
                        tmp_chain_key_list.append(chain_tmp_key)
                    self.parse_single_node(link.from_node, tmp_chain_key_list, link.from_socket)

    def _parse_time_switch_node(self, time_node: bpy.types.Node, chain_key_list: list[M_Key], is_position_switch: bool = False):
        """
        Parse a Time Switch / Time Position Switch node.

        The branch handling is identical to the Switch Key node: branch k maps
        to value k of the node's variable. The only difference is the driver:
        the variable is declared with key_type "time" so the INI writer
        recomputes it from wall-clock time in the [Present] command list
        rather than cycling individual frames with a hotkey. An optional
        playback toggle is emitted separately by the shared timeline writer.

        is_position_switch marks the variable name as a position timeline:
        after parsing, every DrawCallModel carrying it is reclassified as a
        per-frame Position provider (see _reclassify_time_pos_frames).
        """
        valid_input_sockets = time_node.inputs[:]

        # If no sockets are connected at all, skip this node entirely
        is_any_socket_linked = False
        for sock in valid_input_sockets:
            if sock.is_linked:
                is_any_socket_linked = True
                break
        if not is_any_socket_linked:
            return

        # Keep even a one-frame node's configured control in the export.
        # Older one-frame draw nodes without a toggle remain pass-throughs.
        has_toggle = bool(str(getattr(time_node, "toggle_key", "") or "").strip())
        if len(valid_input_sockets) == 1 and not is_position_switch and not has_toggle:
            # A one-frame draw switch is a pass-through. A position provider
            # must still replace the separate base object, never draw twice.
            for link in valid_input_sockets[0].links:
                self.parse_single_node(link.from_node, chain_key_list, link.from_socket)
            return

        fps = float(getattr(time_node, 'fps', 0.0) or 0.0)
        if not math.isfinite(fps) or fps <= 0.0:
            raise ValueError(
                "Dynamic mod timeline node '" + time_node.name + "' has an invalid FPS (must be greater than 0)"
            )

        m_key = M_Key()
        m_key.key_name = self._allocate_time_key_name(time_node)

        state_count = self._switch_alias_state_counts.get(
            m_key.key_name, len(valid_input_sockets)
        )
        m_key.value_list = list(range(state_count))

        m_key.key_type = "time"
        m_key.fps = fps
        m_key.initialize_value = 0  # Used until the first Present update.
        m_key.configure_animation_toggle(time_node)
        m_key.timeline_expression()

        # Set the comment field
        m_key.comment = getattr(time_node, 'comment', '')

        # Nodes sharing an explicit alias share one timeline variable.
        existing_key = self.keyname_mkey_dict.get(m_key.key_name)
        if existing_key is None:
            self.keyname_mkey_dict[m_key.key_name] = m_key
        else:
            if existing_key.key_type != "time":
                raise ValueError(
                    "The alias '" + m_key.key_name + "' is shared by both a Switch Key node and a dynamic mod timeline node; please use different aliases"
                )
            if abs(existing_key.fps - fps) > 1e-6:
                # Traversal order must not silently change playback speed.
                raise ValueError(
                    "Dynamic mod timeline nodes sharing alias '" + m_key.key_name
                    + "' must use the same FPS"
                )
            # One alias owns one runtime switch. Conflicting node settings
            # must not make the chosen hotkey depend on traversal order.
            if (existing_key.toggle_key, existing_key.start_enabled, existing_key.playback_mode) != (m_key.toggle_key, m_key.start_enabled, m_key.playback_mode):
                raise ValueError("Dynamic mod timeline nodes sharing alias '" + m_key.key_name + "' must use the same playback mode, animation toggle key and start state")
            m_key = existing_key

        # Tag only draw calls reached through this position node. A shared
        # alias synchronizes clocks; it must not turn ordinary draws into
        # position providers elsewhere in the graph.
        first_draw = len(self.ordered_draw_obj_data_model_list)
        self._parse_branch_sockets(valid_input_sockets, m_key, state_count, chain_key_list)
        if is_position_switch:
            self.time_pos_key_names.add(m_key.key_name)
            for draw_call in self.ordered_draw_obj_data_model_list[first_draw:]:
                if draw_call.time_position_key_name:
                    raise ValueError("Nested Position.buf Based Dynamic Mod nodes are not supported")
                draw_call.time_position_key_name = m_key.key_name

    def _reclassify_time_pos_frames(self):
        """
        Move Time Position Switch frame draw calls out of the normal draw list.

        A frame branch of a Time Position Switch node only contributes its
        Position bytes to a per-frame side buffer; it must never reach the
        merged submesh buffers (that would duplicate the vertices) nor emit
        its own drawindexed call. The marker records graph provenance rather
        than variable identity, so sharing an alias with a draw switch is safe.
        """
        if not self.time_pos_key_names:
            return
        kept_draw_call_list = []
        for draw_call_model in self.ordered_draw_obj_data_model_list:
            is_time_pos_frame = bool(draw_call_model.time_position_key_name)
            if is_time_pos_frame:
                self.time_pos_frame_models.append(draw_call_model)
            else:
                kept_draw_call_list.append(draw_call_model)
        self.ordered_draw_obj_data_model_list = kept_draw_call_list
        LOG.info(
            "BluePrintModel: reclassified " + str(len(self.time_pos_frame_models))
            + " draw call(s) as Time Position Switch frames"
        )

    def _parse_custom_group(self, group_node: bpy.types.Node, chain_key_list: list[M_Key], from_socket=None):
        """Expand only the connected output of this particular group instance."""
        group_tree = getattr(group_node, "node_tree", None)
        if group_tree is None:
            return
        # A corrupt legacy file can contain recursive group datablocks even
        # though the current UI rejects assigning them.
        if any(instance.node_tree == group_tree for instance in self._group_instance_stack):
            raise ValueError("Blueprint contains a recursive group cycle: " + group_node.name)
        # Exporting every output duplicates objects and bypasses switch states.
        # The caller's socket position corresponds to the child interface order.
        output_index = list(group_node.outputs).index(from_socket) if from_socket is not None else None
        self._group_instance_stack.append(group_node)
        try:
            from ..blueprint.blueprint_node_group import get_group_output_node
            output_node = get_group_output_node(group_tree)
            if output_node is not None:
                sockets = list(output_node.inputs)
                if output_index is not None:
                    sockets = sockets[output_index:output_index + 1]
                for socket in sockets:
                    for link in socket.links:
                        self.parse_single_node(link.from_node, chain_key_list, link.from_socket)
        finally:
            self._group_instance_stack.pop()

    def _parse_group_input(
        self,
        group_input: bpy.types.Node,
        output_socket: bpy.types.NodeSocket,
        chain_key_list: list[M_Key],
    ):
        """Resolve an inner Group Input socket to its caller's linked input."""
        if not self._group_instance_stack:
            return
        group_node = self._group_instance_stack[-1]
        interface_items = [
            item for item in group_node.node_tree.interface.items_tree
            if getattr(item, "item_type", "") == "SOCKET" and item.in_out == "INPUT"
        ]
        try:
            index = list(group_input.outputs).index(output_socket)
        except ValueError:
            return
        parent_socket = (
            _group_socket_for_interface(group_node, group_node.node_tree, interface_items[index], "INPUT")
            if index < len(interface_items) else None
        )
        if parent_socket is None:
            return
        # We are crossing into the caller's tree. Pop the current instance
        # while resolving its inputs, otherwise nested groups resolve outer
        # Group Input nodes against the wrong interface (or recurse forever).
        self._group_instance_stack.pop()
        try:
            for link in parent_socket.links:
                self.parse_single_node(link.from_node, chain_key_list, link.from_socket)
        finally:
            self._group_instance_stack.append(group_node)

    def _unico_split_object(
        self,
        obj: bpy.types.Object,
        node_submesh_name: str,
    ) -> list[tuple[str, bpy.types.Object]]:
        """
        UniComponent split: split the Merged object's vertices per each Submesh's VG range.

        Derives the draw_ib from the submesh_name bound to the node, loads the SubmeshJson
        of every Submesh under that DrawIB, builds a submesh -> VG mapping, then calls
        VertexGroupUtils.split_merged_object_by_submesh_vg_ranges().

        Returns:
            [(submesh_name, temp_split_object), ...]
        """
        from ..workspace.mmt_workspace import MMTWorkSpace
        from ..workspace.submesh_json import SubmeshJson

        # Derive draw_ib from the node's submesh_name
        # submesh_name format: "LOD0.94517393-0" or "94517393-0"
        normalized_name = str(node_submesh_name or "").strip()
        if not normalized_name:
            LOG.warning(f"BluePrintModel: UniComponent node '{obj.name}' has no Submesh set; skipping the split")
            return []

        # Strip the LOD prefix to get the bare name
        if normalized_name.upper().startswith("LOD") and "." in normalized_name:
            bare_name = normalized_name.split(".", 1)[1]
        else:
            bare_name = normalized_name

        # Extract draw_ib (the part before the first '-')
        draw_ib = bare_name.split("-")[0] if "-" in bare_name else ""
        if not draw_ib:
            LOG.warning(f"BluePrintModel: cannot parse draw_ib from submesh_name '{node_submesh_name}'")
            return []

        # Get the names of all Submeshes under this DrawIB
        all_submesh_names = MMTWorkSpace.get_ordered_submesh_name_list_by_drawib(draw_ib)
        if not all_submesh_names:
            LOG.warning(f"BluePrintModel: no Submesh found under DrawIB '{draw_ib}'")
            return []

        LOG.info(f"BluePrintModel: found {len(all_submesh_names)} Submeshes: {all_submesh_names}")

        # Load each Submesh's VGMap and build the submesh -> VG mapping
        submesh_vg_map: dict[str, set[int]] = {}
        submesh_reverse_vg_map: dict[str, dict[int, int]] = {}

        for sm_name in all_submesh_names:
            try:
                sm_path = MMTWorkSpace.check_and_get_submesh_json_path(sm_name)
                sm_json = SubmeshJson(sm_path)
                vg_map = sm_json.VGMap  # {local_idx: global_bone_id}
                LOG.info(f"BluePrintModel:   Submesh '{sm_name}' VGMap = {dict(vg_map)}")
                if not vg_map:
                    continue

                global_vg_set = set(int(v) for v in vg_map.values())
                reverse_map = {int(v): int(k) for k, v in vg_map.items()}

                submesh_vg_map[sm_name] = global_vg_set
                submesh_reverse_vg_map[sm_name] = reverse_map
            except Exception as e:
                LOG.warning(f"BluePrintModel: failed to load the VGMap of Submesh '{sm_name}': {e}")
                continue

        if not submesh_vg_map:
            LOG.warning(f"BluePrintModel: none of the Submeshes under DrawIB '{draw_ib}' has a VGMap; cannot split")
            return []

        # --- Filter: split only into Submeshes with unique VGs (falling back to the node-bound Submesh) ---
        # Compute shared VGs (VGs appearing in more than one Submesh VGMap)
        vg_occurrence: dict[int, set[str]] = {}
        for sm_name, vg_set in submesh_vg_map.items():
            for vg_id in vg_set:
                vg_occurrence.setdefault(vg_id, set()).add(sm_name)

        # The VGs actually present on the object
        obj_vg_ids = set()
        for vg in obj.vertex_groups:
            try:
                obj_vg_ids.add(int(vg.name))
            except ValueError:
                pass

        # Keep only the Submeshes that matter
        filtered_vg_map: dict[str, set[int]] = {}
        for sm_name, vg_set in submesh_vg_map.items():
            unique_vgs = {vg for vg in vg_set if len(vg_occurrence.get(vg, set())) == 1}
            has_unique = bool(unique_vgs & obj_vg_ids)
            is_node_submesh = (sm_name == node_submesh_name)
            if has_unique or is_node_submesh:
                filtered_vg_map[sm_name] = vg_set

        LOG.info(f"BluePrintModel: UniComponent split of '{obj.name}' "
                 f"(vertices: {len(obj.data.vertices)}, VG: {len(obj.vertex_groups)})")
        LOG.info(f"  node Submesh: '{node_submesh_name}', draw_ib: '{draw_ib}'")
        LOG.info(f"  object VG: {sorted(obj_vg_ids)}")
        LOG.info(f"  splitting into: {list(filtered_vg_map.keys())} "
                 f"(Submeshes without unique VGs were filtered out)")

        if not filtered_vg_map:
            LOG.warning(f"BluePrintModel: no valid Submesh to split into; skipping")
            return []
        filtered_reverse_map = {k: v for k, v in submesh_reverse_vg_map.items() if k in filtered_vg_map}

        # Build the unique-VG mapping (used to determine vertex ownership precisely)
        filtered_unique_vg_map: dict[str, set[int]] = {}
        for sm_name in filtered_vg_map:
            unique = {vg for vg in submesh_vg_map[sm_name] if len(vg_occurrence.get(vg, set())) == 1}
            filtered_unique_vg_map[sm_name] = unique

        return VertexGroupUtils.split_merged_object_by_submesh_vg_ranges(
            obj=obj,
            submesh_vg_map=filtered_vg_map,
            submesh_reverse_vg_map=filtered_reverse_map,
            submesh_unique_vg_map=filtered_unique_vg_map,
        )

    def parse_submesh_model_list(self) -> list[SubMeshModel]:
        """
        Parse a SubMeshModel list out of the current BluePrintModel.
        DrawCallModels sharing the same submesh_name are grouped together, with one SubMeshModel per group.
        """
        from ..workspace.mmt_workspace import WorkSpaceModel

        submesh_model_list: list[SubMeshModel] = []
        draw_call_model_dict: dict[str, list[DrawCallModel]] = {}

        for draw_call_model in self.ordered_draw_obj_data_model_list:
            submesh_name = draw_call_model.get_submesh_name()
            draw_call_model_list = draw_call_model_dict.get(submesh_name, [])
            draw_call_model_list.append(draw_call_model)
            draw_call_model_dict[submesh_name] = draw_call_model_list

        # Create a WorkSpaceModel to correct the new format's IndexCount/FirstIndex
        workspace_model = WorkSpaceModel()

        for submesh_name, draw_call_model_list in draw_call_model_dict.items():
            submesh_model = SubMeshModel(drawcall_model_list=draw_call_model_list)
            # In the new format match_index_count/match_first_index start at -1; correct them with WorkSpaceModel
            submesh_model.fix_indices_from_workspace(workspace_model)
            submesh_model_list.append(submesh_model)

        # Sort by match_first_index ascending so DrawIB-0 (the smallest FirstIndex) comes first
        # Submeshes whose match_first_index is -1 (unset) are pushed to the end
        submesh_model_list.sort(key=lambda sm: sm.match_first_index if sm.match_first_index >= 0 else float('inf'))

        return submesh_model_list

    def parse_drawib_model_list(self, combine_ib: bool = False) -> list[DrawIBModel]:
        """
        Parse a DrawIBModel list out of the current BluePrintModel.
        Intended for games that need several SubMeshes combined into a single exported DrawIB.
        """
        drawib_model_list: list[DrawIBModel] = []
        draw_ib_submesh_model_list_dict: dict[str, list[SubMeshModel]] = {}

        for submesh_model in self.parse_submesh_model_list():
            draw_ib = submesh_model.match_draw_ib
            tmp_submesh_model_list = draw_ib_submesh_model_list_dict.get(draw_ib, [])
            tmp_submesh_model_list.append(submesh_model)
            draw_ib_submesh_model_list_dict[draw_ib] = tmp_submesh_model_list

        # A provider without a base DrawIB used to disappear silently because
        # the loop below visits only normally connected base objects.
        for frame_model in self.time_pos_frame_models:
            if frame_model.match_draw_ib not in draw_ib_submesh_model_list_dict:
                raise ValueError("Position.buf Based Dynamic Mod: connect a base object for DrawIB " + frame_model.match_draw_ib)

        for draw_ib, submesh_model_list in draw_ib_submesh_model_list_dict.items():
            drawib_model = DrawIBModel(submesh_model_list=submesh_model_list, combine_ib=combine_ib)
            # Attach this DrawIB's Time Position Switch frame draw calls so
            # generate_buffer_files() can write their per-frame Position side
            # buffers without the exporters knowing about the feature.
            # Populate the exact field consumed by both buffer and INI writers.
            # Attaching an unrelated dynamic attribute left this dict empty.
            from ..common.m_time_position import group_time_position_frames
            drawib_model.time_pos_frame_groups = group_time_position_frames([
                frame_model for frame_model in self.time_pos_frame_models
                if frame_model.match_draw_ib == draw_ib
            ])
            drawib_model_list.append(drawib_model)

        return drawib_model_list
