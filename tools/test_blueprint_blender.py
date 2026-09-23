"""Real Blender regression coverage for blueprint UI and graph operations.

Run with blender -b --factory-startup --python-exit-code 1 --python this_file.
The suite uses a disposable factory scene and never opens a user's blend file.
"""
import importlib
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import tempfile

import bpy

# Load the checkout as an addon so RNA registration is exercised as shipped.
# Using the real entry point also exposes missing dependency registrations.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
addon = importlib.import_module(ROOT.name)
addon.register()
base = addon.blueprint_node_base
groups = addon.blueprint_node_group
lists = addon.blueprint_node_object_list


class BlueprintTests(unittest.TestCase):
    def setUp(self):
        # Each case owns its trees; a failure must not contaminate later cases.
        self.tree = bpy.data.node_groups.new("audit", base.MIMIBlueprintTree.bl_idname)

    def tearDown(self):
        # Clear only this factory-process test data, never external files.
        for tree in list(bpy.data.node_groups):
            if tree.bl_idname == base.MIMIBlueprintTree.bl_idname:
                bpy.data.node_groups.remove(tree)

    def test_group_rna_properties(self):
        # Deferred Python annotations must not swallow Blender properties.
        node = self.tree.nodes.new(groups.GROUP_NODE_IDNAME)
        self.assertIn("node_tree", node.bl_rna.properties)
        self.assertIn("group_name", bpy.ops.mimi.make_group.get_rna_type().properties)

    def test_global_hash_node_collection(self):
        # Global hash rows must work without sockets or an object traversal.
        node = self.tree.nodes.new("MIMINode_Hash_Texture_Global")
        self.assertEqual(len(node.inputs), 0)
        self.assertEqual(len(node.outputs), 0)
        item = node.texture_hash_items.add()
        item.texture_hash = "0123abcd"
        item.source_type = 'FILE'
        source_path = Path(tempfile.gettempdir()) / "mimi_global_hash_test.dds"
        source_path.write_bytes(b"test dds")
        item.file_path = str(source_path)

        result = bpy.ops.mimi.texhashbind_select_file(
            node_name=node.name,
            tree_name=self.tree.name,
            item_index=0,
            filepath=str(source_path),
        )
        self.assertIn('FINISHED', result)
        source_ids = [entry[0] for entry in addon.blueprint_node_hash_texture._texture_hash_source_type_items(item, bpy.context)]
        self.assertIn('MARK', source_ids)

        mark_source_path = Path(tempfile.gettempdir()) / "mimi_global_mark_test.dds"
        mark_source_path.write_bytes(b"marked dds")
        mark_item = node.texture_hash_items.add()
        mark_identifier = "global_hash_fedc9876_94517393_0_DiffuseMap"
        old_loader = addon.blueprint_node_hash_texture._load_global_hash_mark_entries
        addon.blueprint_node_hash_texture._load_global_hash_mark_entries = lambda: [{
            "identifier": mark_identifier,
            "label": "DiffuseMap [94517393-0]",
            "name": "DiffuseMap",
            "submesh_name": "94517393-0",
            "hash": "fedc9876",
            "filename": "diffuse.dds",
            "source_path": str(mark_source_path),
        }]
        try:
            mark_item.source_type = 'MARK'
            mark_item.mark_name = mark_identifier
            self.assertEqual(mark_item.texture_hash, "fedc9876")
            self.assertEqual(mark_item.mark_source_file_path, str(mark_source_path))
        finally:
            addon.blueprint_node_hash_texture._load_global_hash_mark_entries = old_loader

        from MIMIBlender.model.blueprint_model import BluePrintModel
        rows = BluePrintModel._collect_global_hash_texture_bindings(self.tree)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["texture_hash"], "0123abcd")
        self.assertEqual(rows[0]["source_type"], "FILE")
        self.assertEqual(rows[0]["file_path"], bpy.path.abspath(str(source_path)))
        self.assertEqual(rows[1]["texture_hash"], "fedc9876")
        self.assertEqual(rows[1]["source_type"], "MARK")
        self.assertEqual(rows[1]["mark_source_file_path"], str(mark_source_path))
        source_path.unlink(missing_ok=True)
        mark_source_path.unlink(missing_ok=True)

    def test_wwmi_connected_hash_file_export(self):
        # Exercise the screenshot's real node chain and the WWMI constructor.
        # Only geometry assembly and workspace lookups are mocked: parsing,
        # binding resolution, INI sections and file copying stay real.
        from contextlib import ExitStack
        from types import SimpleNamespace
        from MIMIBlender.games.wwmi import model as wwmi
        from MIMIBlender.model.draw_call_model import DrawCallModel
        from MIMIBlender.common.m_ini_helper import M_IniHelper
        from MIMIBlender.common.m_ini_builder import M_IniBuilder
        from MIMIBlender.workspace.texture_metadata_helper import TextureMarkUpInfo

        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            source = root / 'Components-0 t=679ad2f5.dds'
            source.write_bytes(b'external replacement bytes')
            mark_source = root / 'light.dds'
            mark_source.write_bytes(b'marked light bytes')
            output = root / 'Textures'
            output.mkdir()
            target = output / '6077b727_DiffuseMap.dds'
            target.write_bytes(b'old generated texture')

            # Object List -> Group -> Hash Bind -> Group -> Generate Mod.
            objects = self.tree.nodes.new('MIMINode_Object_List')
            for name in ('mesh_a', 'mesh_b'):
                lists._append_object_list_item(objects, name)
            before = self.tree.nodes.new('MIMINode_Object_Group')
            bind = self.tree.nodes.new('MIMINode_Hash_Texture_Bind')
            after = self.tree.nodes.new('MIMINode_Object_Group')
            result = self.tree.nodes.new('MIMINode_Result_Output')
            for upstream, downstream in ((objects, before), (before, bind), (bind, after), (after, result)):
                self.tree.links.new(upstream.outputs[0], downstream.inputs[0])

            marks = []
            for name, texture_hash in (('DiffuseMap', '6077b727'), ('LightMap', '10d9df5f')):
                mark = TextureMarkUpInfo()
                mark.mark_name, mark.mark_type, mark.mark_hash = name, 'Hash', texture_hash
                mark.mark_filename = name + '.dds'
                marks.append(mark)
            # Stable enum items isolate discovery, not the actual RNA rows or
            # the blueprint collector that serializes the user's selection.
            stack.enter_context(patch.object(addon.blueprint_node_hash_texture, '_texture_hash_bind_mark_name_items', return_value=[
                ('DiffuseMap', 'DiffuseMap', ''), ('LightMap', 'LightMap', ''),
            ]))
            for name, texture_hash, source_type in (('DiffuseMap', '6077b727', 'FILE'), ('LightMap', '10d9df5f', 'MARK')):
                item = bind.texture_hash_items.add()
                item.mark_name = name
                item.texture_hash = texture_hash
                item.source_type = source_type
                if source_type == 'FILE':
                    item.file_path = str(source)

            parser, _ = self.parser()
            parser.ordered_draw_obj_data_model_list = []
            submesh_name = 'LOD0.94517393-0'
            def emit(**kwargs):
                parser.ordered_draw_obj_data_model_list.append(DrawCallModel(
                    obj_name=kwargs['object_name'], submesh_name=submesh_name,
                ))
            parser._emit_object_source = emit
            parser.parse_current_node(result, [])
            self.assertEqual(len(parser.ordered_draw_obj_data_model_list), 2)
            self.assertTrue(all(len(draw.hash_texture_binding_list) == 2 for draw in parser.ordered_draw_obj_data_model_list))

            # WWMI owns a separate model and does not run DrawIBModel.__init__.
            # Mock expensive geometry while still calling WWMI.__post_init__.
            game_type = SimpleNamespace(GameTypeName='test', CategoryStrideDict={'Position': 12})
            merged = bpy.data.objects.new('wwmi_texture_test', None)
            merged_name = merged.name
            self.addCleanup(lambda: bpy.data.objects.remove(bpy.data.objects[merged_name]) if merged_name in bpy.data.objects else None)
            stack.enter_context(patch.object(wwmi.MMTWorkSpace, 'get_drawib_aliasname_dict', return_value={}))
            stack.enter_context(patch.object(wwmi.MMTWorkSpace, 'check_and_get_submesh_json_path', return_value='test.json'))
            stack.enter_context(patch.object(wwmi.MMTWorkSpace, 'get_ordered_submesh_name_list_by_drawib', return_value=[submesh_name]))
            stack.enter_context(patch.object(wwmi, 'SubmeshJson', return_value=SimpleNamespace(JsonDict={})))
            stack.enter_context(patch.object(wwmi.D3D11GameType, 'from_submesh_json_dict', return_value=game_type))
            stack.enter_context(patch.object(wwmi.WWMIInfoHelper, 'build_from_json_list', return_value=SimpleNamespace()))
            stack.enter_context(patch.object(wwmi.DrawIBModelWWMI, 'build_merged_object', return_value=SimpleNamespace(object=merged, components=[])))
            stack.enter_context(patch.object(wwmi.TextureMetadataResolver, 'load_submesh_texture_markup_info_from_all_submeshes', return_value={submesh_name: marks}))
            # No vertex buffers are needed to test a texture export. Keep the
            # constructor running past resolution with a zero-sized Position
            # buffer, rather than bypassing the constructor under test.
            stack.enter_context(patch.object(wwmi.ObjBufferHelper, 'check_and_verify_attributes'))
            stack.enter_context(patch.object(wwmi.ExportUtils, 'build_obj_element_context', return_value=SimpleNamespace(mesh=None, original_elementname_data_dict={}, final_elementname_data_dict={})))
            stack.enter_context(patch.object(wwmi.ObjBufferHelper, 'convert_to_element_vertex_ndarray', return_value={}))
            stack.enter_context(patch.object(wwmi.ExportUtils, 'build_wwmi_obj_buffer_result', return_value=SimpleNamespace(category_buffer_dict={'Position': b''})))
            stack.enter_context(patch.object(M_IniHelper, '_get_slot_texture_source_path', return_value=str(mark_source)))
            # Explicit bindings must still work with automatic textures off.
            # Redirect all copy destinations into the disposable test folder;
            # this test must never overwrite a user's generated Mod textures.
            stack.enter_context(patch.object(wwmi.MIMIGlobalProperties, 'forbid_auto_texture_ini', return_value=True))
            stack.enter_context(patch.object(wwmi.GlobalConfig, 'path_generatemod_texture_folder', return_value=str(output)))
            model = wwmi.DrawIBModelWWMI(draw_ib='94517393', blueprint_model=parser)
            # Check both job generation and object identity: detached copies
            # would leave the INI writer looking at unresolved draw calls.
            self.assertEqual(len(model.object_texture_binding_file_list), 2)
            self.assertIs(model.submesh_model_list[0].drawcall_model_list[0], model.submesh_drawcall_groups[0][0])
            self.assertEqual(M_IniHelper._collect_hash_binding_managed_hashes({'94517393': model}), {'6077b727', '10d9df5f'})

            builder = M_IniBuilder()
            M_IniHelper.add_object_texture_binding_resource_sections(builder, model)
            M_IniHelper.generate_hash_style_object_texture_ini(builder, {'94517393': model})
            text = '\n'.join(line for section in builder.ini_section_list for line in section.SectionLineList)
            self.assertIn('filename = Textures\\6077b727_DiffuseMap.dds', text)
            self.assertIn('[TextureOverride_Texture_6077b727_Switch]', text)
            M_IniHelper.move_object_texture_binding_files(model)
            self.assertEqual(target.read_bytes(), source.read_bytes())
            self.assertEqual((output / '10d9df5f_LightMap.dds').read_bytes(), mark_source.read_bytes())
            # Re-export must refresh an existing generated file, not skip it.
            source.write_bytes(b'changed external bytes')
            M_IniHelper.move_object_texture_binding_files(model)
            self.assertEqual(target.read_bytes(), source.read_bytes())

    def test_socket_draw_labels(self):
        # Socket circles are drawn by Blender, independently of this callback.
        # Record labels for linked and unlinked input/output sockets alike.
        node = self.tree.nodes.new("MIMINode_Object_List")
        labels = []

        class Layout:
            def label(self, **kwargs):
                labels.append(kwargs["text"])

        base.MIMISocketObject.draw(node.outputs[0], bpy.context, Layout(), node, "All")
        self.assertEqual(labels, ["All"])

    def test_clone_object_list(self):
        # Item collections and dynamic output sockets must survive grouping.
        node = self.tree.nodes.new("MIMINode_Object_List")
        lists._append_object_list_item(node, "body")
        lists._append_object_list_item(node, "hair")
        node.object_items[1].submesh_name = "hair_submesh"
        child = bpy.data.node_groups.new("child", self.tree.bl_idname)
        clone = groups._clone_node(node, child)
        self.assertEqual([item.object_name for item in clone.object_items], ["body", "hair"])
        self.assertEqual(clone.object_items[1].submesh_name, "hair_submesh")
        self.assertEqual([socket.name for socket in clone.outputs], ["All", "body", "hair"])

    def test_group_roundtrip(self):
        # Exercise the real node editor context, not a simulated graph.
        # The Object List exposes two independent boundary outputs.
        area = bpy.context.screen.areas[0]
        area.type = 'NODE_EDITOR'
        area.spaces.active.tree_type = self.tree.bl_idname
        area.spaces.active.node_tree = self.tree
        source = self.tree.nodes.new("MIMINode_Object_List")
        lists._append_object_list_item(source, "body")
        lists._append_object_list_item(source, "hair")
        target = self.tree.nodes.new("MIMINode_SwitchKey")
        target.inputs.new("MIMISocketObject", "Status 1")
        self.tree.links.new(source.outputs[1], target.inputs[0])
        self.tree.links.new(source.outputs[2], target.inputs[1])
        target.select = False
        source.select = True
        with bpy.context.temp_override(area=area):
            group = groups.make_group_from_selection(bpy.context)
        self.assertEqual(len(group.outputs), 2)
        self.assertEqual(len(self.tree.links), 2)
        # Refreshing an unchanged interface must never disconnect the caller.
        groups.sync_group_node_sockets(group)
        self.assertEqual(len(self.tree.links), 2)
        groups.ungroup_node(self.tree, group)
        self.assertEqual(len(self.tree.links), 2)
        self.assertEqual([link.from_socket.name for link in self.tree.links], ["body", "hair"])

    def parser(self):
        # Keep real graph traversal; isolate external workspace file lookups.
        from MIMIBlender.model.blueprint_model import BluePrintModel
        model = BluePrintModel.__new__(BluePrintModel)
        model._group_instance_stack = []
        model._emit_object_source = lambda **kwargs: emitted.append(kwargs['object_name'])
        emitted = []
        return model, emitted

    def test_reroute_and_cycle_export(self):
        # Reroutes must pass data through, while a cycle gives a useful error.
        source = self.tree.nodes.new('MIMINode_Object_Info')
        source.object_name = 'mesh'
        reroute = self.tree.nodes.new('NodeReroute')
        self.tree.links.new(source.outputs[0], reroute.inputs[0])
        model, emitted = self.parser()
        model.parse_single_node(reroute, [])
        self.assertEqual(emitted, ['mesh'])
        first = self.tree.nodes.new('MIMINode_Object_Group')
        second = self.tree.nodes.new('MIMINode_Object_Group')
        self.tree.links.new(first.outputs[0], second.inputs[0])
        self.tree.links.new(second.outputs[0], first.inputs[0])
        with self.assertRaisesRegex(ValueError, 'cycle'):
            model.parse_single_node(first, [])
        self.assertFalse(model._active_parse_path)

    def test_group_export_ports_and_preview(self):
        # Two outputs from one child must remain separate at export/preview.
        from MIMIBlender.blueprint.blueprint_graph import iter_object_sources
        child = bpy.data.node_groups.new('child', self.tree.bl_idname)
        source = child.nodes.new('MIMINode_Object_List')
        lists._append_object_list_item(source, 'body')
        lists._append_object_list_item(source, 'hair')
        output = child.nodes.new('NodeGroupOutput')
        for index, name in enumerate(('body', 'hair')):
            child.interface.new_socket(name=name, in_out='OUTPUT', socket_type='MIMISocketObject')
            child.links.new(source.outputs[index + 1], output.inputs[index])
        group = self.tree.nodes.new(groups.GROUP_NODE_IDNAME)
        group.node_tree = child
        target = self.tree.nodes.new('MIMINode_Object_Group')
        self.tree.links.new(group.outputs[1], target.inputs[0])
        model, emitted = self.parser()
        model.parse_single_node(target, [])
        self.assertEqual(emitted, ['hair'])
        self.assertEqual([row.object_name for row in iter_object_sources(target)], ['hair'])
        # Renaming and adding interfaces must preserve the existing caller wire.
        child.interface.items_tree[1].name = 'renamed'
        child.interface.new_socket(name='extra', in_out='OUTPUT', socket_type='MIMISocketObject')
        # Run the deferred custom-tree interface synchronization explicitly.
        groups._sync_group_interfaces()
        self.assertEqual(len(group.outputs), 3)
        self.assertEqual(len(self.tree.links), 1)
        self.assertEqual(self.tree.links[0].from_socket.name, 'renamed')

    def test_group_failure_rolls_back(self):
        # This used to dereference removed NodeLink structs and crash Blender.
        area = bpy.context.screen.areas[0]
        area.type = 'NODE_EDITOR'
        area.spaces.active.tree_type = self.tree.bl_idname
        area.spaces.active.node_tree = self.tree
        source = self.tree.nodes.new('MIMINode_Object_Info')
        target = self.tree.nodes.new('MIMINode_SwitchKey')
        target.select = False
        self.tree.links.new(source.outputs[0], target.inputs[0])
        with bpy.context.temp_override(area=area):
            with patch.object(groups, '_clone_node', side_effect=RuntimeError('injected')):
                with self.assertRaisesRegex(RuntimeError, 'injected'):
                    groups.make_group_from_selection(bpy.context)
        self.assertEqual(len(self.tree.nodes), 2)
        self.assertEqual(len(self.tree.links), 1)
        self.assertTrue(source.select)

    def test_object_identity_after_rename(self):
        # Reusing the old name must not redirect an existing object reference.
        objects = addon.blueprint_node_obj
        mesh = bpy.data.objects.new('original', None)
        node = self.tree.nodes.new('MIMINode_Object_Info')
        node.object_name = mesh.name
        listed = self.tree.nodes.new('MIMINode_Object_List')
        lists._append_object_list_item(listed, mesh.name)
        mesh.name = 'renamed'
        other = bpy.data.objects.new('original', None)
        self.assertEqual(objects.ObjectPersistentIdManager.resolve_node_target(node), mesh)
        lists._sync_item_socket_integrity(listed)
        self.assertEqual(listed.object_items[0].object_name, mesh.name)
        self.assertEqual(listed.outputs[1].name, mesh.name)
        bpy.data.objects.remove(mesh)
        bpy.data.objects.remove(other)

    def test_nested_group_passthrough(self):
        # Group Input inside a nested switch must resolve the outer caller.
        # The final ungroup also covers a child containing only a direct wire.
        def passthrough(name):
            tree = bpy.data.node_groups.new(name, self.tree.bl_idname)
            tree.interface.new_socket(name='in', in_out='INPUT', socket_type='MIMISocketObject')
            tree.interface.new_socket(name='out', in_out='OUTPUT', socket_type='MIMISocketObject')
            first, last = groups._make_group_input_output(tree)
            return tree, first, last
        inner, inner_in, inner_out = passthrough('inner')
        switch = inner.nodes.new('MIMINode_SwitchKey')
        inner.links.new(inner_in.outputs[0], switch.inputs[0])
        inner.links.new(switch.outputs[0], inner_out.inputs[0])
        outer, outer_in, outer_out = passthrough('outer')
        nested = outer.nodes.new(groups.GROUP_NODE_IDNAME)
        nested.node_tree = inner
        outer.links.new(outer_in.outputs[0], nested.inputs[0])
        outer.links.new(nested.outputs[0], outer_out.inputs[0])
        instance = self.tree.nodes.new(groups.GROUP_NODE_IDNAME)
        instance.node_tree = outer
        source = self.tree.nodes.new('MIMINode_Object_Info')
        source.object_name = 'nested_mesh'
        self.tree.links.new(source.outputs[0], instance.inputs[0])
        model, emitted = self.parser()
        model.parse_single_node(instance, [], instance.outputs[0])
        self.assertEqual(emitted, ['nested_mesh'])
        self.assertFalse(model._group_instance_stack)
        # Replace the outer's internal group with a direct interface wire.
        outer.nodes.remove(nested)
        outer.links.new(outer_in.outputs[0], outer_out.inputs[0])
        target = self.tree.nodes.new('MIMINode_Object_Group')
        self.tree.links.new(instance.outputs[0], target.inputs[0])
        groups.ungroup_node(self.tree, instance)
        self.assertEqual(len(self.tree.links), 1)
        self.assertEqual(self.tree.links[0].from_node, source)

    def test_shape_refresh_owns_output(self):
        # Refresh must affect its own output and include Object List meshes.
        mesh = bpy.data.meshes.new('shape_mesh')
        obj = bpy.data.objects.new('shape_object', mesh)
        bpy.context.scene.collection.objects.link(obj)
        obj.shape_key_add(name='Basis')
        obj.shape_key_add(name='Smile')
        source = self.tree.nodes.new('MIMINode_Object_List')
        lists._append_object_list_item(source, obj.name)
        first = self.tree.nodes.new('MIMINode_Result_Output')
        second = self.tree.nodes.new('MIMINode_Result_Output')
        first.shapekey_items.add().shapekey_name = 'keep'
        self.tree.links.new(source.outputs[0], second.inputs[0])
        result = bpy.ops.mimi.refresh_shapekey_list(tree_name=self.tree.name, node_name=second.name)
        self.assertEqual(result, {'FINISHED'})
        self.assertEqual([item.shapekey_name for item in second.shapekey_items], ['Smile'])
        self.assertEqual(first.shapekey_items[0].shapekey_name, 'keep')
        bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.meshes.remove(mesh)

    def test_group_output_batch_connect(self):
        # A pass-through group can connect to the input-only Generate Mod node.
        area = bpy.context.screen.areas[0]
        area.type = 'NODE_EDITOR'
        area.spaces.active.tree_type = self.tree.bl_idname
        area.spaces.active.node_tree = self.tree
        source = self.tree.nodes.new('MIMINode_Object_Group')
        target = self.tree.nodes.new('MIMINode_Result_Output')
        with bpy.context.temp_override(area=area):
            result = bpy.ops.mimi.batch_connect_nodes()
        self.assertEqual(result, {'FINISHED'})
        self.assertEqual(len(self.tree.links), 1)
        self.assertEqual(self.tree.links[0].from_node, source)
        self.assertEqual(self.tree.links[0].to_node, target)

    def test_save_load_collections_and_ports(self):
        # Library roundtrip exercises Blender serialization without replacing
        # the running test's context or loading any user-owned blend file.
        source = self.tree.nodes.new('MIMINode_Object_List')
        lists._append_object_list_item(source, 'first')
        lists._append_object_list_item(source, 'second')
        target = self.tree.nodes.new('MIMINode_SwitchKey')
        self.tree.links.new(source.outputs[2], target.inputs[0])
        with tempfile.TemporaryDirectory() as directory:
            filepath = str(Path(directory) / 'blueprint.blend')
            bpy.data.libraries.write(filepath, {self.tree})
            with bpy.data.libraries.load(filepath) as (saved, loaded):
                loaded.node_groups = saved.node_groups
            restored = loaded.node_groups[0]
        lists._sync_item_socket_integrity(restored.nodes[source.name])
        self.assertEqual(len(restored.links), 1)
        self.assertEqual(restored.links[0].from_socket.name, 'second')
        self.assertEqual(len(restored.nodes[source.name].object_items), 2)

    def test_clone_all_node_types(self):
        # Every registered node should be groupable without losing its ports.
        # This includes collection-backed shape and texture settings.
        child = bpy.data.node_groups.new('clones', self.tree.bl_idname)
        node_types = [cls.bl_idname for cls in base.MIMINodeBase.__subclasses__()] + ['NodeReroute', 'NodeFrame']
        for node_type in node_types:
            with self.subTest(node=node_type):
                node = self.tree.nodes.new(node_type)
                clone = groups._clone_node(node, child)
                self.assertEqual(len(node.inputs), len(clone.inputs))
                self.assertEqual(len(node.outputs), len(clone.outputs))

    def test_dynamic_target_group_roundtrip(self):
        # Removing all incoming wires can delete a Group node's empty sockets.
        # Both transformations must keep every target port alive until rewired.
        area = bpy.context.screen.areas[0]
        area.type = 'NODE_EDITOR'
        area.spaces.active.tree_type = self.tree.bl_idname
        area.spaces.active.node_tree = self.tree
        source = self.tree.nodes.new('MIMINode_Object_List')
        for name in ('body', 'hair', 'clothes'):
            lists._append_object_list_item(source, name)
        target = self.tree.nodes.new('MIMINode_Object_Group')
        for socket in list(source.outputs)[1:]:
            self.tree.links.new(socket, target.inputs[-1])
        target.select = False
        with bpy.context.temp_override(area=area):
            group = groups.make_group_from_selection(bpy.context)
        self.assertEqual(len(self.tree.links), 3)
        group.location.x += 100
        groups.ungroup_node(self.tree, group)
        self.assertEqual(len(self.tree.links), 3)
        self.assertEqual([link.from_socket.name for link in self.tree.links], ['body', 'hair', 'clothes'])
        clone = self.tree.links[0].from_node
        self.assertAlmostEqual(clone.location.x, 100)

    def test_exit_group_without_runtime_stack(self):
        # A restored Blender path must not trap the user inside a group.
        area = bpy.context.screen.areas[0]
        area.type = 'NODE_EDITOR'
        space = area.spaces.active
        space.tree_type = self.tree.bl_idname
        space.node_tree = self.tree
        child = bpy.data.node_groups.new('child', self.tree.bl_idname)
        group = self.tree.nodes.new(groups.GROUP_NODE_IDNAME)
        group.node_tree = child
        groups._enter_group(space, group)
        groups._navigation_state.clear()
        groups._exit_group(space)
        self.assertEqual(len(space.path), 1)
        self.assertEqual(space.edit_tree, self.tree)

    def test_stale_explicit_tree_is_not_retargeted(self):
        # Stale buttons must cancel rather than delete/edit another blueprint.
        helper = addon.blueprint_node_obj.BlueprintExportHelper
        self.tree.use_fake_user = True
        helper.set_runtime_blueprint_tree(self.tree)
        self.assertIsNone(helper.get_selected_blueprint_tree('deleted_tree', bpy.context))
        node = self.tree.nodes.new('MIMINode_Object_List')
        area = bpy.context.screen.areas[0]
        area.type = 'NODE_EDITOR'
        area.spaces.active.tree_type = self.tree.bl_idname
        area.spaces.active.node_tree = self.tree
        with bpy.context.temp_override(area=area):
            result = bpy.ops.mimi.objlist_add_item(tree_name='deleted_tree', node_name=node.name)
        self.assertEqual(result, {'CANCELLED'})
        self.assertFalse(node.object_items)

    def test_reused_group_instances_are_not_cycles(self):
        # Serial instances share child RNA addresses but represent a valid DAG.
        from MIMIBlender.blueprint.blueprint_graph import iter_object_sources
        child = bpy.data.node_groups.new('shared', self.tree.bl_idname)
        child.interface.new_socket(name='in', in_out='INPUT', socket_type='MIMISocketObject')
        child.interface.new_socket(name='out', in_out='OUTPUT', socket_type='MIMISocketObject')
        first, last = groups._make_group_input_output(child)
        switch = child.nodes.new('MIMINode_SwitchKey')
        child.links.new(first.outputs[0], switch.inputs[0])
        child.links.new(switch.outputs[0], last.inputs[0])
        source = self.tree.nodes.new('MIMINode_Object_Info')
        source.object_name = 'shared_mesh'
        instances = [self.tree.nodes.new(groups.GROUP_NODE_IDNAME) for _ in range(2)]
        for instance in instances:
            instance.node_tree = child
        self.tree.links.new(source.outputs[0], instances[0].inputs[0])
        self.tree.links.new(instances[0].outputs[0], instances[1].inputs[0])
        model, emitted = self.parser()
        model.parse_single_node(instances[1], [], instances[1].outputs[0])
        self.assertEqual(emitted, ['shared_mesh'])
        self.assertEqual([row.object_name for row in iter_object_sources(instances[1])], ['shared_mesh'])

    def test_texture_settings_survive_group_clone(self):
        # PropertyGroup rows, enum selections and row flags are user data.
        # Copy them without needing external workspace marks or image files.
        source = self.tree.nodes.new('MIMINode_Texture_Bind')
        item = source.texture_slot_items.add()
        item.source_type = 'RESOURCE'
        item.resource_name = 'ResourceBody'
        item.slot = 'ps-t2'
        item.enabled = False
        item.restore_after_draw = True
        child = bpy.data.node_groups.new('child', self.tree.bl_idname)
        clone = groups._clone_node(source, child)
        copied = clone.texture_slot_items[0]
        self.assertEqual(copied.source_type, 'RESOURCE')
        self.assertEqual(copied.resource_name, 'ResourceBody')
        self.assertEqual(copied.slot, 'ps-t2')
        self.assertFalse(copied.enabled)
        self.assertTrue(copied.restore_after_draw)

    def test_ungroup_failure_preserves_original(self):
        # An exception after creating a clone must remove only temporary nodes.
        child = bpy.data.node_groups.new('child', self.tree.bl_idname)
        child.nodes.new('MIMINode_Object_List')
        group = self.tree.nodes.new(groups.GROUP_NODE_IDNAME)
        group.node_tree = child
        clone_node = groups._clone_node

        def fail_after_clone(source, tree):
            clone_node(source, tree)
            raise RuntimeError('injected clone failure')

        with patch.object(groups, '_clone_node', side_effect=fail_after_clone):
            with self.assertRaisesRegex(RuntimeError, 'injected clone failure'):
                groups.ungroup_node(self.tree, group)
        self.assertEqual(list(self.tree.nodes), [group])
        self.assertEqual(group.node_tree, child)

    def test_orphan_list_port_rejected(self):
        # A stale extra port must not silently export the entire object list.
        source = self.tree.nodes.new('MIMINode_Object_List')
        lists._append_object_list_item(source, 'body')
        orphan = source.outputs.new('MIMISocketObject', 'orphan')
        model, emitted = self.parser()
        with self.assertRaisesRegex(ValueError, 'no matching item'):
            model.parse_single_node(source, [], orphan)
        self.assertFalse(emitted)

    def test_batch_ports_respect_node_contracts(self):
        # Fixed texture/group interfaces cannot acquire arbitrary extra inputs.
        menu = addon.blueprint_node_menu
        texture = self.tree.nodes.new('MIMINode_Texture_Bind')
        self.assertIsNone(menu._new_batch_input(texture))
        self.assertEqual(len(texture.inputs), 1)
        timeline = self.tree.nodes.new('MIMINode_TimeSwitch')
        self.assertEqual(menu._new_batch_input(timeline).name, 'Frame 1')

    def test_highlight_restore_saved_color(self):
        # ID properties deserialize arrays as IDPropertyArray, not Python lists.
        # Simulate a reload by clearing the nonpersistent pointer cache.
        highlight = addon.blueprint_node_highlight
        node = self.tree.nodes.new("MIMINode_Object_List")
        original = tuple(node.color)
        highlight._set_highlight(node, (0.0, 0.26, 0.27))
        highlight._base_color_cache.clear()
        highlight._restore_base_color(node)
        for actual, expected in zip(node.color, original):
            self.assertAlmostEqual(actual, expected)


if __name__ == "__main__":
    # Blender's --python-exit-code turns failed assertions into a failing job.
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(BlueprintTests))
    addon.unregister()
    if not result.wasSuccessful():
        raise AssertionError("Blueprint regression suite failed")
