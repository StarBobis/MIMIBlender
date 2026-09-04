"""Genshin Impact character material construction for imported meshes.

The groups created here deliberately follow the semantic functions in
``tmp/shader_semantic_pseudocode.rs``.  Keeping the calculations grouped makes
the imported material practical to inspect and adjust in Blender's shader
editor instead of leaving the user with one large anonymous node graph.
"""
import os

import bpy

from .global_config import GlobalConfig, LogicName


class GIMIHighFidelityMaterial:
    """Build the non-photorealistic Genshin character preview material.

    This is deliberately a character-material builder, not a branch of
    ``MeshCreateHelper``.  Future face and hair modes can live beside it as
    separate builders and use the same small importer dispatch point.
    """

    GROUP_PREFIX = "SSMT GIMI v12 "
    SHADER_SCHEMA_VERSION = 12
    PREVIEW_COLLECTION_NAME = "SSMT GIMI Preview"
    VIRTUAL_SUN_NAME = "虚拟日光"
    PREVIEW_CAMERA_NAME = "SSMT GIMI Preview Camera"

    @staticmethod
    def is_genshin_workspace(logic_name: str | None = None, game_name: str | None = None) -> bool:
        """Accept both the SSMT preset and the two common workspace labels."""
        logic_name = str(logic_name if logic_name is not None else GlobalConfig.logic_name).strip()
        game_name = str(game_name if game_name is not None else GlobalConfig.gamename).strip()
        normalized_game_name = game_name.casefold().replace(" ", "").replace("_", "")
        return logic_name.casefold() == LogicName.GIMI.casefold() or normalized_game_name in {
            "gimi", "genshinimpact", "原神",
        }

    @staticmethod
    def find_optional_texture(directory: str, keywords: tuple[str, ...]) -> str | None:
        """Find an optional authored lookup texture without imposing a folder layout."""
        if not directory or not os.path.isdir(directory):
            return None
        normalized_keywords = tuple(keyword.casefold() for keyword in keywords)
        for root, _, files in os.walk(directory):
            for filename in files:
                name = filename.casefold()
                if not name.endswith((".dds", ".png", ".jpg", ".jpeg", ".tga")):
                    continue
                if any(keyword in name for keyword in normalized_keywords):
                    return os.path.join(root, filename)
        return None

    @staticmethod
    def _resource_texture_path(filename: str) -> str:
        addon_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(addon_root, 'resources', filename)

    @classmethod
    def _ensure_preview_objects(cls):
        """Create reusable scene helpers required by the virtual-light shader."""
        scene = bpy.context.scene
        collection = bpy.data.collections.get(cls.PREVIEW_COLLECTION_NAME)
        if collection is None:
            collection = bpy.data.collections.new(cls.PREVIEW_COLLECTION_NAME)
            scene.collection.children.link(collection)

        light_object = bpy.data.objects.get(cls.VIRTUAL_SUN_NAME)
        if light_object is None:
            light_object = bpy.data.objects.new(cls.VIRTUAL_SUN_NAME, None)
            light_object.empty_display_type = 'SINGLE_ARROW'
            light_object.empty_display_size = 0.5
            # Match the source preset's virtual-sun default (50 degrees X).
            light_object.rotation_euler = (0.87266457, 0.0, 0.0)
        if not light_object.users_collection:
            collection.objects.link(light_object)
        light_object['SSMT:PreviewHelper'] = True

        camera_data = bpy.data.cameras.get(cls.PREVIEW_CAMERA_NAME)
        if camera_data is None:
            camera_data = bpy.data.cameras.new(cls.PREVIEW_CAMERA_NAME)
        camera_data.lens = 50.0
        camera_object = bpy.data.objects.get(cls.PREVIEW_CAMERA_NAME)
        if camera_object is None:
            camera_object = bpy.data.objects.new(cls.PREVIEW_CAMERA_NAME, camera_data)
        if not camera_object.users_collection:
            collection.objects.link(camera_object)
        camera_object.location = (0.0, -6.0, 1.5)
        camera_object.rotation_euler = (1.413717, 0.0, 0.0)
        camera_object['SSMT:PreviewHelper'] = True
        if scene.camera is None:
            scene.camera = camera_object

        return light_object, camera_object

    @classmethod
    def _bind_virtual_sun_drivers(cls, group):
        """Bind every virtual-sun group input to the scene helper object."""
        light_object = bpy.data.objects.get(cls.VIRTUAL_SUN_NAME)
        if light_object is None:
            return

        for node in group.nodes:
            if node.bl_idname != 'ShaderNodeGroup' or node.name != 'evaluate_virtual_sun':
                continue
            socket = node.inputs.get('Sun Rotation')
            if socket is None:
                continue
            socket.default_value = light_object.rotation_euler
            for axis in range(3):
                try:
                    socket.driver_remove('default_value', axis)
                except (RuntimeError, TypeError):
                    pass
                driver = socket.driver_add('default_value', axis).driver
                driver.type = 'SCRIPTED'
                driver.expression = 'rotation'
                for variable in list(driver.variables):
                    driver.variables.remove(variable)
                variable = driver.variables.new()
                variable.name = 'rotation'
                variable.type = 'SINGLE_PROP'
                variable.targets[0].id = light_object
                variable.targets[0].data_path = f'rotation_euler[{axis}]'

    @classmethod
    def _configure_preview_compositor(cls):
        """Install the requested Bloom compositor and viewport preview flags."""
        scene = bpy.context.scene
        scene.use_nodes = True
        tree = getattr(scene, 'compositing_node_group', None)
        if tree is None:
            tree = bpy.data.node_groups.new('SSMT GIMI Preview Compositor', 'CompositorNodeTree')
            scene.compositing_node_group = tree

        nodes, links = tree.nodes, tree.links

        def get_or_create(node_type, name):
            node = nodes.get(name)
            if node is None or node.bl_idname != node_type:
                if node is not None:
                    nodes.remove(node)
                node = nodes.new(node_type)
                node.name = name
                node.label = name
            return node

        if hasattr(tree, 'interface'):
            output_sockets = [
                item for item in tree.interface.items_tree
                if getattr(item, 'item_type', None) == 'SOCKET'
                and getattr(item, 'in_out', None) == 'OUTPUT'
            ]
            if not output_sockets:
                tree.interface.new_socket(name='Image', in_out='OUTPUT', socket_type='NodeSocketColor')
        elif not tree.outputs:
            tree.outputs.new('NodeSocketColor', 'Image')

        render_layers = get_or_create('CompositorNodeRLayers', 'Render Layers')
        glare = get_or_create('CompositorNodeGlare', 'Glare')
        composite = get_or_create('NodeGroupOutput', 'Group Outpit')
        viewer = get_or_create('CompositorNodeViewer', 'Viewer')
        render_layers.location = (-420, 60)
        glare.location = (-120, 60)
        composite.location = (220, 120)
        viewer.location = (220, -40)

        # Blender 5 exposes Goo's glare controls as typed input sockets.
        glare.inputs['Type'].default_value = 'Bloom'
        glare.inputs['Quality'].default_value = 'High'
        glare.inputs['Threshold'].default_value = 1.0
        glare.inputs['Smoothness'].default_value = 1.0
        glare.inputs['Strength'].default_value = 0.298
        glare.inputs['Saturation'].default_value = 1.0
        glare.inputs['Tint'].default_value = (1.0, 0.23455, 0.19752, 1.0)
        glare.inputs['Size'].default_value = 0.669

        for link in list(links):
            if link.to_node in (glare, composite, viewer):
                links.remove(link)
        links.new(render_layers.outputs['Image'], glare.inputs['Image'])
        # Use Blender's primary Glare image output for both compositor targets.
        links.new(glare.outputs[0], composite.inputs[0])
        links.new(glare.outputs[0], viewer.inputs['Image'])
        scene['SSMT:GIMICompositor'] = 'Bloom'

        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type != 'VIEW_3D':
                    continue
                shading = area.spaces.active.shading
                if hasattr(shading, 'use_compositor'):
                    shading.use_compositor = 'ALWAYS'
                shading.use_scene_lights = False
                shading.use_scene_world = False
                if hasattr(shading, 'use_scene_lights_render'):
                    shading.use_scene_lights_render = False
                if hasattr(shading, 'use_scene_world_render'):
                    shading.use_scene_world_render = False

    @staticmethod
    def _socket(group, in_out: str, socket_type: str, name: str):
        if hasattr(group, "interface"):
            return group.interface.new_socket(name=name, in_out=in_out, socket_type=socket_type)
        collection = group.inputs if in_out == 'INPUT' else group.outputs
        return collection.new(socket_type, name)

    @classmethod
    def _group(cls, suffix: str, inputs: list[tuple[str, str]], outputs: list[tuple[str, str]]):
        name = cls.GROUP_PREFIX + suffix
        group = bpy.data.node_groups.get(name)
        if group is not None:
            return group
        group = bpy.data.node_groups.new(name, 'ShaderNodeTree')
        group['SSMT:ShaderSchemaVersion'] = cls.SHADER_SCHEMA_VERSION
        for socket_type, socket_name in inputs:
            cls._socket(group, 'INPUT', socket_type, socket_name)
        for socket_type, socket_name in outputs:
            cls._socket(group, 'OUTPUT', socket_type, socket_name)
        group.nodes.new('NodeGroupInput').location = (-600, 0)
        group.nodes.new('NodeGroupOutput').location = (600, 0)
        return group

    @staticmethod
    def _node(group, node_type: str, name: str, location: tuple[float, float]):
        node = group.nodes.new(node_type)
        node.name = name
        node.label = name
        node.location = location
        return node

    @staticmethod
    def _link(group, output_node, output_name: str, input_node, input_name: str):
        group.links.new(output_node.outputs[output_name], input_node.inputs[input_name])

    @classmethod
    def _decode_normal_group(cls):
        group = cls._group(
            "Decode Tangent Normal RG",
            [('NodeSocketColor', 'Encoded RG')],
            [('NodeSocketVector', 'Normal')],
        )
        if len(group.nodes) > 2:
            return group
        nodes, links = group.nodes, group.links
        group_in, group_out = nodes['Group Input'], nodes['Group Output']
        separate = cls._node(group, 'ShaderNodeSeparateColor', 'Encoded RG', (-760, 40))
        separate.mode = 'RGB'
        r_scale = cls._node(group, 'ShaderNodeMath', 'R * 2', (-580, 120))
        r_scale.operation = 'MULTIPLY'
        r_scale.inputs[1].default_value = 2.0
        g_scale = cls._node(group, 'ShaderNodeMath', 'G * 2', (-580, -20))
        g_scale.operation = 'MULTIPLY'
        g_scale.inputs[1].default_value = 2.0
        r_signed = cls._node(group, 'ShaderNodeMath', 'R - 1', (-420, 120))
        r_signed.operation = 'SUBTRACT'
        r_signed.inputs[1].default_value = 1.0
        g_signed = cls._node(group, 'ShaderNodeMath', 'G - 1', (-420, -20))
        g_signed.operation = 'SUBTRACT'
        g_signed.inputs[1].default_value = 1.0
        signed_xy = cls._node(group, 'ShaderNodeCombineXYZ', 'Signed XY', (-240, 60))
        xy_length = cls._node(group, 'ShaderNodeVectorMath', 'Signed XY Length Squared', (-60, 60))
        xy_length.operation = 'DOT_PRODUCT'
        one_minus = cls._node(group, 'ShaderNodeMath', '1 - XY Length Squared', (120, 60))
        one_minus.operation = 'SUBTRACT'
        one_minus.inputs[0].default_value = 1.0
        clamp_z = cls._node(group, 'ShaderNodeMath', 'Clamp Reconstructed Z', (280, 60))
        clamp_z.operation = 'MAXIMUM'
        clamp_z.inputs[1].default_value = 0.0
        z = cls._node(group, 'ShaderNodeMath', 'Reconstruct Z', (440, 60))
        z.operation = 'SQRT'
        signed_xyz = cls._node(group, 'ShaderNodeCombineXYZ', 'Signed XYZ', (600, 60))
        encode = cls._node(group, 'ShaderNodeVectorMath', 'Re-encode Normal RGB', (760, 60))
        encode.operation = 'MULTIPLY_ADD'
        encode.inputs[1].default_value = (0.5, 0.5, 0.5)
        encode.inputs[2].default_value = (0.5, 0.5, 0.5)
        normal_map = cls._node(group, 'ShaderNodeNormalMap', 'Tangent Normal Map', (940, -100))
        normal_map.space = 'TANGENT'
        normal_map.uv_map = 'TEXCOORD.xy'
        normal_map.inputs['Strength'].default_value = 1.0
        links.new(group_in.outputs['Encoded RG'], separate.inputs['Color'])
        links.new(separate.outputs['Red'], r_scale.inputs[0])
        links.new(separate.outputs['Green'], g_scale.inputs[0])
        links.new(r_scale.outputs[0], r_signed.inputs[0])
        links.new(g_scale.outputs[0], g_signed.inputs[0])
        links.new(r_signed.outputs[0], signed_xy.inputs['X'])
        links.new(g_signed.outputs[0], signed_xy.inputs['Y'])
        signed_xy.inputs['Z'].default_value = 0.0
        links.new(signed_xy.outputs['Vector'], xy_length.inputs[0])
        links.new(xy_length.outputs['Value'], one_minus.inputs[1])
        links.new(one_minus.outputs[0], clamp_z.inputs[0])
        links.new(clamp_z.outputs[0], z.inputs[0])
        links.new(r_signed.outputs[0], signed_xyz.inputs['X'])
        links.new(g_signed.outputs[0], signed_xyz.inputs['Y'])
        links.new(z.outputs[0], signed_xyz.inputs['Z'])
        links.new(signed_xyz.outputs['Vector'], encode.inputs[0])
        links.new(encode.outputs['Vector'], normal_map.inputs['Color'])
        links.new(normal_map.outputs['Normal'], group_out.inputs['Normal'])
        return group

    @classmethod
    def _virtual_sun_group(cls):
        group = cls._group(
            "NT虚拟日光",
            [
                ('NodeSocketVector', 'Surface Normal'), ('NodeSocketFloat', 'Light Gain'),
                ('NodeSocketVector', 'Sun Rotation'),
            ],
            [('NodeSocketFloat', 'Lambert'), ('NodeSocketFloat', 'Half Lambert')],
        )
        if len(group.nodes) > 2:
            return group
        nodes, links = group.nodes, group.links
        group_in, group_out = nodes['Group Input'], nodes['Group Output']
        sun_rotation = cls._node(group, 'ShaderNodeVectorRotate', 'Virtual Sun Direction', (-420, 100))
        sun_rotation.rotation_type = 'EULER_XYZ'
        sun_rotation.inputs['Vector'].default_value = (0.0, 0.0, 1.0)
        dot = cls._node(group, 'ShaderNodeVectorMath', 'N dot L', (-240, 100))
        dot.operation = 'DOT_PRODUCT'
        clamp_dot = cls._node(group, 'ShaderNodeMath', 'Saturate N dot L', (-80, 100))
        clamp_dot.operation = 'MULTIPLY_ADD'
        clamp_dot.inputs[1].default_value = 1.0
        clamp_dot.inputs[2].default_value = 0.0
        clamp_dot.use_clamp = True
        gain = cls._node(group, 'ShaderNodeMath', 'Saturate LightMap G x 2.2', (-240, -100))
        gain.operation = 'MULTIPLY'
        gain.inputs[1].default_value = 2.2
        gain.use_clamp = True
        lambert = cls._node(group, 'ShaderNodeMath', 'Lambert', (100, 100))
        lambert.operation = 'MULTIPLY'
        lambert.use_clamp = True
        half_mul = cls._node(group, 'ShaderNodeMath', '0.5 N dot L + 0.5', (100, -40))
        half_mul.operation = 'MULTIPLY_ADD'
        half_mul.inputs[1].default_value = 0.5
        half_mul.inputs[2].default_value = 0.5
        half_pow = cls._node(group, 'ShaderNodeMath', 'Half Lambert Squared', (270, -40))
        half_pow.operation = 'POWER'
        half_pow.inputs[1].default_value = 2.0
        gain_bias = cls._node(group, 'ShaderNodeMath', 'Light Gain + 0.01', (270, -150))
        gain_bias.operation = 'ADD'
        gain_bias.inputs[1].default_value = 0.01
        half_gain = cls._node(group, 'ShaderNodeMath', 'Half Lambert', (440, -40))
        half_gain.operation = 'MULTIPLY'
        links.new(group_in.outputs['Surface Normal'], dot.inputs[0])
        links.new(group_in.outputs['Sun Rotation'], sun_rotation.inputs['Rotation'])
        links.new(sun_rotation.outputs['Vector'], dot.inputs[1])
        links.new(dot.outputs['Value'], clamp_dot.inputs[0])
        links.new(group_in.outputs['Light Gain'], gain.inputs[0])
        links.new(clamp_dot.outputs[0], lambert.inputs[0])
        links.new(gain.outputs[0], lambert.inputs[1])
        links.new(clamp_dot.outputs[0], half_mul.inputs[0])
        links.new(half_mul.outputs[0], half_pow.inputs[0])
        links.new(half_pow.outputs[0], half_gain.inputs[0])
        links.new(gain.outputs[0], gain_bias.inputs[0])
        links.new(gain_bias.outputs[0], half_gain.inputs[1])
        links.new(lambert.outputs[0], group_out.inputs['Lambert'])
        links.new(half_gain.outputs[0], group_out.inputs['Half Lambert'])
        return group

    @classmethod
    def _grade_base_group(cls):
        group = cls._group("NT调色", [('NodeSocketColor', 'Base Color')], [('NodeSocketColor', 'Graded Color')])
        if len(group.nodes) > 2:
            return group
        nodes, links = group.nodes, group.links
        curve = cls._node(group, 'ShaderNodeRGBCurve', 'CurveMap.BaseColor.Combined', (-180, 0))
        curve.label = 'CurveMap | NT调色 | Combined point (0.457726, 0.298387)'
        curve.mapping.initialize()
        curve.mapping.curves[3].points.new(0.457726, 0.298387)
        curve.mapping.update()
        hsv = cls._node(group, 'ShaderNodeHueSaturation', 'Value x 1.8', (80, 0))
        hsv.inputs['Hue'].default_value = 0.5
        hsv.inputs['Saturation'].default_value = 1.0
        hsv.inputs['Value'].default_value = 1.8
        hsv.inputs['Fac'].default_value = 1.0
        links.new(nodes['Group Input'].outputs['Base Color'], curve.inputs['Color'])
        links.new(curve.outputs['Color'], hsv.inputs['Color'])
        links.new(hsv.outputs['Color'], nodes['Group Output'].inputs['Graded Color'])
        return group

    @classmethod
    def _body_ramp_coordinates_group(cls):
        group = cls._group(
            "NTramp.clothes Coordinates",
            [('NodeSocketFloat', 'Half Lambert'), ('NodeSocketFloat', 'Material ID')],
            [('NodeSocketVector', 'Ramp UV'), ('NodeSocketFloat', 'Fully Lit Mask')],
        )
        if len(group.nodes) > 2:
            return group
        nodes, links = group.nodes, group.links
        group_in, group_out = nodes['Group Input'], nodes['Group Output']
        row_values = ((1.0, 0.85), (0.7, 0.55), (0.5, 0.75), (0.3, 0.65), (0.0, 0.95))
        row_sum = None
        y = 150
        for material_id, row in row_values:
            compare = cls._node(group, 'ShaderNodeMath', f'Material ID {material_id}', (-320, y))
            compare.operation = 'COMPARE'
            compare.inputs[1].default_value = material_id
            compare.inputs[2].default_value = 0.05
            multiply = cls._node(group, 'ShaderNodeMath', f'Ramp Row {row}', (-140, y))
            multiply.operation = 'MULTIPLY'
            multiply.inputs[1].default_value = row
            links.new(group_in.outputs['Material ID'], compare.inputs[0])
            links.new(compare.outputs[0], multiply.inputs[0])
            if row_sum is None:
                row_sum = multiply
            else:
                add = cls._node(group, 'ShaderNodeMath', 'Add Ramp Rows', (30, y))
                add.operation = 'ADD'
                links.new(row_sum.outputs[0], add.inputs[0])
                links.new(multiply.outputs[0], add.inputs[1])
                row_sum = add
            y -= 100
        ramp_x = cls._node(group, 'ShaderNodeMapRange', 'Map Half Lambert to Ramp X', (20, -250))
        ramp_x.clamp = True
        ramp_x.inputs['From Min'].default_value = 0.0
        ramp_x.inputs['From Max'].default_value = 0.5
        ramp_x.inputs['To Min'].default_value = 0.0
        ramp_x.inputs['To Max'].default_value = 1.0
        combine = cls._node(group, 'ShaderNodeCombineXYZ', 'Body Ramp UV', (220, -120))
        fully_lit = cls._node(group, 'ShaderNodeMath', 'Ramp X > 0.998', (220, -260))
        fully_lit.operation = 'GREATER_THAN'
        fully_lit.inputs[1].default_value = 0.998
        links.new(group_in.outputs['Half Lambert'], ramp_x.inputs['Value'])
        links.new(ramp_x.outputs['Result'], combine.inputs['X'])
        links.new(row_sum.outputs[0], combine.inputs['Y'])
        links.new(ramp_x.outputs['Result'], fully_lit.inputs[0])
        links.new(combine.outputs['Vector'], group_out.inputs['Ramp UV'])
        links.new(fully_lit.outputs[0], group_out.inputs['Fully Lit Mask'])
        return group

    @classmethod
    def _body_ramp_shading_group(cls):
        group = cls._group(
            "NTramp.clothes Color",
            [('NodeSocketColor', 'Ramp Color'), ('NodeSocketFloat', 'Fully Lit Mask')],
            [('NodeSocketColor', 'Body Ramp Color')],
        )
        if len(group.nodes) > 2:
            # Shared groups survive re-imports; restore the tuned shadow value
            # instead of retaining a brighter value from an older material.
            shadow_value = next(
                (node for node in group.nodes
                 if node.bl_idname == 'ShaderNodeHueSaturation'
                 and node.name.startswith('Darken Shadow Ramp')),
                None,
            )
            if shadow_value is not None:
                shadow_value.inputs['Hue'].default_value = 0.5
                shadow_value.inputs['Saturation'].default_value = 1.0
                shadow_value.inputs['Value'].default_value = 0.97
                shadow_value.inputs['Fac'].default_value = 1.0
            return group
        nodes, links = group.nodes, group.links
        curve = cls._node(group, 'ShaderNodeRGBCurve', 'CurveMap.Ramp.Combined', (-220, 0))
        curve.label = 'CurveMap | NTramp.clothes | Combined point (0.499811, 0.378282)'
        curve.mapping.initialize()
        curve.mapping.curves[3].points.new(0.499811, 0.378282)
        curve.mapping.update()
        shadow_value = cls._node(group, 'ShaderNodeHueSaturation', 'Darken Shadow Ramp 0.97', (-20, 0))
        shadow_value.inputs['Hue'].default_value = 0.5
        shadow_value.inputs['Saturation'].default_value = 1.0
        shadow_value.inputs['Value'].default_value = 0.97
        shadow_value.inputs['Fac'].default_value = 1.0
        mix = cls._node(group, 'ShaderNodeMixRGB', 'Fully Lit Daylight Color', (40, 0))
        mix.blend_type = 'MIX'
        mix.inputs[2].default_value = (0.85, 0.77519834, 0.765, 1.0)
        links.new(nodes['Group Input'].outputs['Ramp Color'], curve.inputs['Color'])
        links.new(nodes['Group Input'].outputs['Fully Lit Mask'], mix.inputs[0])
        links.new(curve.outputs['Color'], shadow_value.inputs['Color'])
        links.new(shadow_value.outputs['Color'], mix.inputs[1])
        links.new(mix.outputs['Color'], nodes['Group Output'].inputs['Body Ramp Color'])
        return group

    @classmethod
    def _metal_matcap_group(cls):
        group = cls._group(
            "NT金属",
            [
                ('NodeSocketColor', 'Base Color'), ('NodeSocketColor', 'LightMap'),
                ('NodeSocketColor', 'MatCap Color'), ('NodeSocketVector', 'Surface Normal'),
            ],
            [('NodeSocketColor', 'Metal Color'), ('NodeSocketFloat', 'Metal Mask')],
        )
        if len(group.nodes) > 2:
            return group
        nodes, links = group.nodes, group.links
        group_in, group_out = nodes['Group Input'], nodes['Group Output']
        lightmap = cls._node(group, 'ShaderNodeSeparateColor', 'LightMap Channels', (-440, 40))
        lightmap.mode = 'RGB'
        mask = cls._node(group, 'ShaderNodeMath', 'LightMap R > 0.55', (-250, 120))
        mask.operation = 'GREATER_THAN'
        mask.inputs[1].default_value = 0.55
        masked_specular = cls._node(group, 'ShaderNodeMath', 'Masked Specular', (-60, -10))
        masked_specular.operation = 'MULTIPLY'
        specular_blue = cls._node(group, 'ShaderNodeMath', 'LightMap B Modulation', (100, -10))
        specular_blue.operation = 'MULTIPLY'
        specular_level = cls._node(group, 'ShaderNodeMapRange', 'Specular Level 0.02..0.5', (260, -10))
        specular_level.clamp = True
        specular_level.inputs['To Min'].default_value = 0.02
        specular_level.inputs['To Max'].default_value = 0.5
        matcap_level = cls._node(group, 'ShaderNodeMapRange', 'MatCap Level 0.1..1.0', (100, -180))
        matcap_level.clamp = True
        matcap_level.inputs['To Min'].default_value = 0.1
        matcap_level.inputs['To Max'].default_value = 1.0
        intensity = cls._node(group, 'ShaderNodeMath', 'Metal Intensity x 20', (430, -80))
        intensity.operation = 'MULTIPLY'
        intensity.inputs[1].default_value = 20.0
        intensity_product = cls._node(group, 'ShaderNodeMath', 'Specular x MatCap', (270, -90))
        intensity_product.operation = 'MULTIPLY'
        color = cls._node(group, 'ShaderNodeMixRGB', 'Base x Metal Intensity', (600, -40))
        color.blend_type = 'MULTIPLY'
        color.inputs[0].default_value = 1.0
        links.new(group_in.outputs['LightMap'], lightmap.inputs['Color'])
        links.new(lightmap.outputs['Red'], mask.inputs[0])
        glossy = cls._node(group, 'ShaderNodeBsdfAnisotropic', 'Glossy BSDF', (-270, -80))
        glossy.inputs['Color'].default_value = (0.8, 0.8, 0.8, 1.0)
        glossy.inputs['Roughness'].default_value = 0.5
        shader_to_rgb = cls._node(group, 'ShaderNodeShaderToRGB', 'Shader to RGB', (-80, -110))
        links.new(group_in.outputs['Surface Normal'], glossy.inputs['Normal'])
        links.new(glossy.outputs['BSDF'], shader_to_rgb.inputs['Shader'])
        links.new(shader_to_rgb.outputs['Color'], masked_specular.inputs[0])
        links.new(mask.outputs[0], masked_specular.inputs[1])
        links.new(masked_specular.outputs[0], specular_blue.inputs[0])
        links.new(lightmap.outputs['Blue'], specular_blue.inputs[1])
        links.new(specular_blue.outputs[0], specular_level.inputs['Value'])
        # Preserve Blender's native Color -> Float conversion used by preset.
        links.new(group_in.outputs['MatCap Color'], matcap_level.inputs['Value'])
        links.new(specular_level.outputs['Result'], intensity_product.inputs[0])
        links.new(matcap_level.outputs['Result'], intensity_product.inputs[1])
        links.new(intensity_product.outputs[0], intensity.inputs[0])
        links.new(group_in.outputs['Base Color'], color.inputs[1])
        links.new(intensity.outputs[0], color.inputs[2])
        links.new(color.outputs['Color'], group_out.inputs['Metal Color'])
        links.new(mask.outputs[0], group_out.inputs['Metal Mask'])
        return group

    @classmethod
    def _special_emission_group(cls):
        group = cls._group(
            "NT神之眼颜色",
            [('NodeSocketColor', 'Graded Base'), ('NodeSocketFloat', 'Frame'), ('NodeSocketColor', 'Element Color')],
            [('NodeSocketColor', 'Emission Color')],
        )
        if len(group.nodes) > 2:
            return group
        nodes, links = group.nodes, group.links
        divide = cls._node(group, 'ShaderNodeMath', 'Frame / 50', (-360, 40))
        divide.operation = 'DIVIDE'
        divide.inputs[1].default_value = 50.0
        cosine = cls._node(group, 'ShaderNodeMath', 'Pulse Cosine', (-190, 40))
        cosine.operation = 'COSINE'
        pulse = cls._node(group, 'ShaderNodeMapRange', 'Pulse 1..5', (-10, 40))
        pulse.clamp = True
        pulse.inputs['From Min'].default_value = -1.0
        pulse.inputs['From Max'].default_value = 1.0
        pulse.inputs['To Min'].default_value = 1.0
        pulse.inputs['To Max'].default_value = 5.0
        tint = cls._node(group, 'ShaderNodeMixRGB', 'Base x Element', (-10, -100))
        tint.blend_type = 'MULTIPLY'
        tint.inputs[0].default_value = 1.0
        result = cls._node(group, 'ShaderNodeMixRGB', 'Pulse x Tinted Base', (180, -20))
        result.blend_type = 'MULTIPLY'
        result.inputs[0].default_value = 1.0
        links.new(nodes['Group Input'].outputs['Frame'], divide.inputs[0])
        links.new(divide.outputs[0], cosine.inputs[0])
        links.new(cosine.outputs[0], pulse.inputs['Value'])
        links.new(nodes['Group Input'].outputs['Graded Base'], tint.inputs[1])
        links.new(nodes['Group Input'].outputs['Element Color'], tint.inputs[2])
        links.new(tint.outputs['Color'], result.inputs[1])
        links.new(pulse.outputs['Result'], result.inputs[2])
        links.new(result.outputs['Color'], nodes['Group Output'].inputs['Emission Color'])
        return group

    @classmethod
    def _edge_light_group(cls):
        group = cls._group("NT屏幕空间边缘光", [('NodeSocketColor', 'Color')], [('NodeSocketColor', 'Edge Lit Color')])
        if len(group.nodes) > 2:
            return group
        nodes, links = group.nodes, group.links
        bright = cls._node(group, 'ShaderNodeHueSaturation', 'Bright Edge Color', (-140, -60))
        bright.inputs['Hue'].default_value = 0.5
        bright.inputs['Saturation'].default_value = 1.0
        bright.inputs['Value'].default_value = 2.8
        bright.inputs['Fac'].default_value = 1.0
        try:
            curvature = cls._node(group, 'ShaderNodeCurvature', 'Goo Engine Curvature', (520, 120))
        except RuntimeError:
            # Standard Blender has no Goo Curvature node.  The requested
            # behavior here is a literal passthrough, not a rim approximation.
            group.nodes.remove(bright)
            links.new(nodes['Group Input'].outputs['Color'], nodes['Group Output'].inputs['Edge Lit Color'])
            group['SSMT:GooCurvature'] = False
            group['SSMT:EdgeLightMode'] = 'DIRECT_OUTPUT'
            return group
        group['SSMT:GooCurvature'] = True
        group['SSMT:EdgeLightMode'] = 'CURVATURE'
        camera = cls._node(group, 'ShaderNodeCameraData', 'Camera Data', (-560, 120))
        abs_depth = cls._node(group, 'ShaderNodeMath', 'Abs View Z Depth', (-380, 120))
        abs_depth.operation = 'ABSOLUTE'
        depth = cls._node(group, 'ShaderNodeMath', 'Safe View Z Depth', (-210, 120))
        depth.operation = 'MAXIMUM'
        depth.inputs[1].default_value = 1.0e-6
        inverse_square = cls._node(group, 'ShaderNodeMath', '1 / Depth Squared', (-20, 180))
        inverse_square.operation = 'POWER'
        inverse_square.inputs[1].default_value = -2.0
        inverse = cls._node(group, 'ShaderNodeMath', '1 / Depth', (-20, 80))
        inverse.operation = 'DIVIDE'
        inverse.inputs[0].default_value = 1.0
        farther_than_one = cls._node(group, 'ShaderNodeMath', 'Depth > 1', (150, 120))
        farther_than_one.operation = 'GREATER_THAN'
        farther_than_one.inputs[1].default_value = 1.0
        thickness = cls._node(group, 'ShaderNodeMix', 'Depth Based Thickness', (320, 120))
        thickness.data_type = 'FLOAT'
        curvature.inputs['Samples'].default_value = 8.0
        curvature.inputs['Sample Radius'].default_value = 0.2
        curvature.inputs['Scale'].default_value = (1.0, 1.0, 0.0)
        rim = cls._node(group, 'ShaderNodeMath', 'Scene Rim > 0.05', (720, 120))
        rim.operation = 'GREATER_THAN'
        rim.inputs[1].default_value = 0.05
        links.new(camera.outputs['View Z Depth'], abs_depth.inputs[0])
        links.new(abs_depth.outputs[0], depth.inputs[0])
        links.new(depth.outputs[0], inverse_square.inputs[0])
        links.new(depth.outputs[0], inverse.inputs[1])
        links.new(depth.outputs[0], farther_than_one.inputs[0])
        links.new(farther_than_one.outputs[0], thickness.inputs['Factor'])
        links.new(inverse_square.outputs[0], thickness.inputs['A'])
        links.new(inverse.outputs[0], thickness.inputs['B'])
        links.new(thickness.outputs['Result'], curvature.inputs['Thickness'])
        links.new(curvature.outputs['Scene Rim'], rim.inputs[0])
        mix = cls._node(group, 'ShaderNodeMixRGB', 'Apply Edge Light', (230, 0))
        links.new(nodes['Group Input'].outputs['Color'], bright.inputs['Color'])
        links.new(rim.outputs[0], mix.inputs[0])
        links.new(nodes['Group Input'].outputs['Color'], mix.inputs[1])
        links.new(bright.outputs['Color'], mix.inputs[2])
        links.new(mix.outputs['Color'], nodes['Group Output'].inputs['Edge Lit Color'])
        return group

    @classmethod
    def _body_shader_group(cls):
        """The shared Body/Clothes shader; component materials only sample maps."""
        group = cls._group(
            "NTclothes Body Master",
            [
                ('NodeSocketColor', 'Diffuse Color'), ('NodeSocketFloat', 'Diffuse Alpha'),
                ('NodeSocketColor', 'Normal Color'), ('NodeSocketColor', 'LightMap Color'),
                ('NodeSocketFloat', 'LightMap Alpha'), ('NodeSocketColor', 'Ramp Color'),
                ('NodeSocketColor', 'Metal Color'),
            ],
            [
                ('NodeSocketColor', 'Shader Color'), ('NodeSocketVector', 'Ramp UV'),
                ('NodeSocketVector', 'MatCap UV'),
            ],
        )
        if len(group.nodes) > 2:
            cls._bind_virtual_sun_drivers(group)
            return group
        nodes, links = group.nodes, group.links
        group_in, group_out = nodes['Group Input'], nodes['Group Output']

        decoded_normal = cls._node(group, 'ShaderNodeGroup', 'decode_tangent_normal_rg', (-1040, -40))
        decoded_normal.node_tree = cls._decode_normal_group()
        links.new(group_in.outputs['Normal Color'], decoded_normal.inputs['Encoded RG'])

        virtual_sun = cls._node(group, 'ShaderNodeGroup', 'evaluate_virtual_sun', (-820, -100))
        virtual_sun.node_tree = cls._virtual_sun_group()
        links.new(decoded_normal.outputs['Normal'], virtual_sun.inputs['Surface Normal'])
        cls._bind_virtual_sun_drivers(group)
        lightmap_separate = cls._node(group, 'ShaderNodeSeparateColor', 'LightMap Channels', (-1040, -300))
        links.new(group_in.outputs['LightMap Color'], lightmap_separate.inputs['Color'])
        links.new(lightmap_separate.outputs['Green'], virtual_sun.inputs['Light Gain'])

        grade = cls._node(group, 'ShaderNodeGroup', 'grade_base_color', (-820, 260))
        grade.node_tree = cls._grade_base_group()
        links.new(group_in.outputs['Diffuse Color'], grade.inputs['Base Color'])

        body_uv = cls._node(group, 'ShaderNodeGroup', 'sample_body_ramp coordinates', (-600, -250))
        body_uv.node_tree = cls._body_ramp_coordinates_group()
        links.new(virtual_sun.outputs['Half Lambert'], body_uv.inputs['Half Lambert'])
        links.new(group_in.outputs['LightMap Alpha'], body_uv.inputs['Material ID'])
        links.new(body_uv.outputs['Ramp UV'], group_out.inputs['Ramp UV'])
        body_shading = cls._node(group, 'ShaderNodeGroup', 'sample_body_ramp', (-360, -250))
        body_shading.node_tree = cls._body_ramp_shading_group()
        links.new(group_in.outputs['Ramp Color'], body_shading.inputs['Ramp Color'])
        links.new(body_uv.outputs['Fully Lit Mask'], body_shading.inputs['Fully Lit Mask'])
        nonmetal = cls._node(group, 'ShaderNodeMixRGB', 'GIMI Nonmetal Color', (-100, 230))
        nonmetal.blend_type = 'MULTIPLY'
        nonmetal.inputs[0].default_value = 1.0
        links.new(grade.outputs['Graded Color'], nonmetal.inputs[1])
        links.new(body_shading.outputs['Body Ramp Color'], nonmetal.inputs[2])

        texcoord = cls._node(group, 'ShaderNodeTexCoord', 'GIMI Geometric Coordinates', (-820, -680))
        normal_to_camera = cls._node(group, 'ShaderNodeVectorTransform', 'GIMI Object Normal to Camera', (-600, -680))
        normal_to_camera.vector_type = 'NORMAL'
        normal_to_camera.convert_from = 'OBJECT'
        normal_to_camera.convert_to = 'CAMERA'
        matcap_uv = cls._node(group, 'ShaderNodeVectorMath', 'GIMI MatCap UV', (-380, -680))
        matcap_uv.operation = 'MULTIPLY_ADD'
        matcap_uv.inputs[1].default_value = (0.5, 0.5, 1.0)
        matcap_uv.inputs[2].default_value = (0.5, 0.5, 0.0)
        links.new(texcoord.outputs['Normal'], normal_to_camera.inputs['Vector'])
        links.new(normal_to_camera.outputs['Vector'], matcap_uv.inputs[0])
        links.new(matcap_uv.outputs['Vector'], group_out.inputs['MatCap UV'])

        metal = cls._node(group, 'ShaderNodeGroup', 'evaluate_metal_matcap', (-100, -70))
        metal.node_tree = cls._metal_matcap_group()
        links.new(group_in.outputs['Diffuse Color'], metal.inputs['Base Color'])
        links.new(group_in.outputs['LightMap Color'], metal.inputs['LightMap'])
        links.new(group_in.outputs['Metal Color'], metal.inputs['MatCap Color'])
        links.new(decoded_normal.outputs['Normal'], metal.inputs['Surface Normal'])
        ordinary = cls._node(group, 'ShaderNodeMixRGB', 'GIMI Ordinary Color', (150, 210))
        links.new(metal.outputs['Metal Mask'], ordinary.inputs[0])
        links.new(nonmetal.outputs['Color'], ordinary.inputs[1])
        links.new(metal.outputs['Metal Color'], ordinary.inputs[2])

        frame = cls._node(group, 'ShaderNodeValue', 'GIMI Current Frame', (-120, -500))
        frame.outputs['Value'].default_value = 1.0
        frame.outputs['Value'].driver_add('default_value').driver.expression = 'frame'
        emission = cls._node(group, 'ShaderNodeGroup', 'evaluate_special_emission', (120, -360))
        emission.node_tree = cls._special_emission_group()
        emission.inputs['Element Color'].default_value = (0.39373726, 0.39373726, 0.39373726, 1.0)
        links.new(grade.outputs['Graded Color'], emission.inputs['Graded Base'])
        links.new(frame.outputs['Value'], emission.inputs['Frame'])
        special_mask = cls._node(group, 'ShaderNodeMath', 'GIMI Diffuse Alpha > 0.5', (120, -500))
        special_mask.operation = 'GREATER_THAN'
        special_mask.inputs[1].default_value = 0.5
        links.new(group_in.outputs['Diffuse Alpha'], special_mask.inputs[0])
        selected = cls._node(group, 'ShaderNodeMixRGB', 'GIMI Special Region Selection', (390, 130))
        links.new(special_mask.outputs[0], selected.inputs[0])
        links.new(ordinary.outputs['Color'], selected.inputs[1])
        links.new(emission.outputs['Emission Color'], selected.inputs[2])
        edge = cls._node(group, 'ShaderNodeGroup', 'apply_screen_space_edge_light', (620, 130))
        edge.node_tree = cls._edge_light_group()
        links.new(selected.outputs['Color'], edge.inputs['Color'])
        links.new(edge.outputs['Edge Lit Color'], group_out.inputs['Shader Color'])
        return group

    @classmethod
    def _body_coordinates_group(cls):
        """Shared pre-sampling coordinates; kept separate to avoid feedback loops."""
        group = cls._group(
            "NTclothes Coordinates",
            [
                ('NodeSocketColor', 'Normal Color'), ('NodeSocketColor', 'LightMap Color'),
                ('NodeSocketFloat', 'LightMap Alpha'),
            ],
            [('NodeSocketVector', 'Ramp UV'), ('NodeSocketVector', 'MatCap UV')],
        )
        if len(group.nodes) > 2:
            cls._bind_virtual_sun_drivers(group)
            return group
        nodes, links = group.nodes, group.links
        group_in, group_out = nodes['Group Input'], nodes['Group Output']
        decoded_normal = cls._node(group, 'ShaderNodeGroup', 'decode_tangent_normal_rg', (-840, 40))
        decoded_normal.node_tree = cls._decode_normal_group()
        links.new(group_in.outputs['Normal Color'], decoded_normal.inputs['Encoded RG'])
        virtual_sun = cls._node(group, 'ShaderNodeGroup', 'evaluate_virtual_sun', (-620, 40))
        virtual_sun.node_tree = cls._virtual_sun_group()
        links.new(decoded_normal.outputs['Normal'], virtual_sun.inputs['Surface Normal'])
        cls._bind_virtual_sun_drivers(group)
        lightmap = cls._node(group, 'ShaderNodeSeparateColor', 'LightMap Channels', (-840, -130))
        links.new(group_in.outputs['LightMap Color'], lightmap.inputs['Color'])
        links.new(lightmap.outputs['Green'], virtual_sun.inputs['Light Gain'])
        body_uv = cls._node(group, 'ShaderNodeGroup', 'sample_body_ramp coordinates', (-380, 20))
        body_uv.node_tree = cls._body_ramp_coordinates_group()
        links.new(virtual_sun.outputs['Half Lambert'], body_uv.inputs['Half Lambert'])
        links.new(group_in.outputs['LightMap Alpha'], body_uv.inputs['Material ID'])
        links.new(body_uv.outputs['Ramp UV'], group_out.inputs['Ramp UV'])
        texcoord = cls._node(group, 'ShaderNodeTexCoord', 'GIMI Geometric Coordinates', (-600, -360))
        normal_to_camera = cls._node(group, 'ShaderNodeVectorTransform', 'GIMI Object Normal to Camera', (-380, -360))
        normal_to_camera.vector_type = 'NORMAL'
        normal_to_camera.convert_from = 'OBJECT'
        normal_to_camera.convert_to = 'CAMERA'
        matcap_uv = cls._node(group, 'ShaderNodeVectorMath', 'GIMI MatCap UV', (-160, -360))
        matcap_uv.operation = 'MULTIPLY_ADD'
        matcap_uv.inputs[1].default_value = (0.5, 0.5, 1.0)
        matcap_uv.inputs[2].default_value = (0.5, 0.5, 0.0)
        links.new(texcoord.outputs['Normal'], normal_to_camera.inputs['Vector'])
        links.new(normal_to_camera.outputs['Vector'], matcap_uv.inputs[0])
        links.new(matcap_uv.outputs['Vector'], group_out.inputs['MatCap UV'])
        return group

    @classmethod
    def _make_image_node(cls, nodes, image_path: str | None, name: str, location, non_color: bool = False):
        node = nodes.new('ShaderNodeTexImage')
        node.name = name
        node.label = name
        node.location = location
        if image_path:
            try:
                node.image = bpy.data.images.load(image_path, check_existing=True)
            except Exception as error:
                print(f"[GIMI Material] Cannot load {name}: {image_path}: {error}")
        if node.image and non_color:
            try:
                node.image.colorspace_settings.name = 'Non-Color'
            except Exception:
                pass
        return node

    @classmethod
    def _default_lookup_image(cls, name: str, color: tuple[float, float, float, float]):
        image = bpy.data.images.get(name)
        if image is None:
            image = bpy.data.images.new(name, width=1, height=1, alpha=True, float_buffer=False)
            image.pixels[:] = color
            image.pack()
        return image

    @staticmethod
    def _image_has_alpha(image) -> bool:
        """Whether an image can carry the masks encoded in a texture alpha channel."""
        if image is None or getattr(image, 'channels', 0) < 4:
            return False
        filepath = str(getattr(image, 'filepath', '')).casefold()
        return not filepath.endswith(('.jpg', '.jpeg'))

    @classmethod
    def configure_eye_alpha_emission(cls, material, diffuse_paths: list[str]) -> bool:
        """Build SSMT4's eye pass: base + straight-alpha diffuse overlays."""
        if material is None or not diffuse_paths:
            return False
        material.use_nodes = True
        nodes, links = material.node_tree.nodes, material.node_tree.links
        nodes.clear()

        uv = nodes.new('ShaderNodeUVMap')
        uv.name = 'GIMI TEXCOORD.xy'
        uv.uv_map = 'TEXCOORD.xy'
        uv.location = (-1000, 0)
        diffuse_color = None
        # SSMT4 exposes four authored diffuse-layer uniforms.  Do not silently
        # reinterpret later layers with a different blend equation.
        for index, path in enumerate(diffuse_paths[:4]):
            texture = cls._make_image_node(nodes, path, f'Eye DiffuseMap{index}', (-780, -index * 260))
            if texture.image is None:
                continue
            try:
                texture.image.alpha_mode = 'STRAIGHT'
            except (AttributeError, TypeError, ValueError):
                pass
            links.new(uv.outputs['UV'], texture.inputs['Vector'])
            if diffuse_color is None:
                # Map 0 is opaque base; its alpha is authored detail, not
                # coverage, so it must not attenuate the base RGB.
                diffuse_color = texture.outputs['Color']
                continue

            overlay = nodes.new('ShaderNodeMixRGB')
            overlay.name = f'Eye DiffuseMap{index} Source Over'
            overlay.label = 'SSMT4 overlay alpha coverage'
            overlay.blend_type = 'MIX'
            overlay.location = (-300, -index * 260)
            links.new(texture.outputs['Alpha'], overlay.inputs[0])
            links.new(diffuse_color, overlay.inputs[1])
            links.new(texture.outputs['Color'], overlay.inputs[2])
            diffuse_color = overlay.outputs['Color']

        if diffuse_color is None:
            return False
        output = nodes.new('ShaderNodeOutputMaterial')
        output.location = (300, 0)
        try:
            emission = nodes.new('ShaderNodeEmission')
            emission.name = 'SSMT4 Eye Unlit Output'
            emission.location = (60, 0)
            emission.inputs['Strength'].default_value = 1.0
            links.new(diffuse_color, emission.inputs['Color'])
            links.new(emission.outputs['Emission'], output.inputs['Surface'])
        except RuntimeError:
            emission = nodes.new('ShaderNodeBsdfPrincipled')
            emission.name = 'SSMT4 Eye Unlit Output'
            emission.location = (60, 0)
            emission.inputs['Base Color'].default_value = (0.0, 0.0, 0.0, 1.0)
            emission.inputs['Emission Strength'].default_value = 1.0
            links.new(diffuse_color, emission.inputs['Emission Color'])
            links.new(emission.outputs['BSDF'], output.inputs['Surface'])

        material['SSMT:EyeDiffuseMapPaths'] = list(diffuse_paths)
        material['SSMT:MaterialModel'] = 'GIMI Eye SSMT4 Unlit'
        material['SSMT:SubMeshRole'] = 'Eye'
        return True

    @classmethod
    def configure_face_sdf_material(
        cls, material, diffuse_paths: list[str], face_sdf_path: str, face_sdf_channel: str = 'R', face_shadow_path: str | None = None,
    ) -> bool:
        """Build SSMT4's FaceSDF unlit pass (separate from Body/Clothes)."""
        if material is None or not diffuse_paths or not face_sdf_path:
            return False
        material.use_nodes = True
        nodes, links = material.node_tree.nodes, material.node_tree.links
        nodes.clear()
        light_object, _ = cls._ensure_preview_objects()

        def bind_sun_azimuth(socket, expression: str):
            """Drive a scalar from the shared virtual sun's horizontal angle."""
            try:
                socket.driver_remove('default_value')
            except (RuntimeError, TypeError):
                pass
            driver = socket.driver_add('default_value').driver
            driver.type = 'SCRIPTED'
            driver.expression = expression
            variable = driver.variables.new()
            variable.name = 'azimuth'
            variable.type = 'SINGLE_PROP'
            variable.targets[0].id = light_object
            variable.targets[0].data_path = 'rotation_euler[2]'

        uv = nodes.new('ShaderNodeUVMap')
        uv.name = 'GIMI TEXCOORD.xy'
        uv.uv_map = 'TEXCOORD.xy'
        uv.location = (-1250, 0)
        diffuse_color = None
        for index, path in enumerate(diffuse_paths):
            texture = cls._make_image_node(nodes, path, f'Face DiffuseMap{index}', (-1050, 220 - index * 220))
            if texture.image is None:
                continue
            # Face diffuse alpha carries packed blush/detail data.  It is not
            # a premultiplied colour channel and must remain untouched by the
            # image loader; FaceSDF owns the actual face-shadow semantics.
            try:
                texture.image.alpha_mode = 'CHANNEL_PACKED'
            except (AttributeError, TypeError, ValueError):
                pass
            links.new(uv.outputs['UV'], texture.inputs['Vector'])
            if diffuse_color is None:
                diffuse_color = texture.outputs['Color']
                continue
            # SSMT4: map 0 is the base; later DiffuseMaps are straight-alpha overlays.
            overlay = nodes.new('ShaderNodeMixRGB')
            overlay.name = f'Face DiffuseMap{index} Source Over'
            overlay.label = 'Overlay Alpha coverage'
            overlay.blend_type = 'MIX'
            overlay.location = (-780, 220 - index * 220)
            links.new(texture.outputs['Alpha'], overlay.inputs[0])
            links.new(diffuse_color, overlay.inputs[1])
            links.new(texture.outputs['Color'], overlay.inputs[2])
            diffuse_color = overlay.outputs['Color']
        if diffuse_color is None:
            return False

        # Keep Face in the same preview colour pipeline as Body/Clothes.
        # Without this shared curve + value lift, an otherwise correct SDF
        # branch is visibly desaturated/darker than the neighbouring body.
        grade = nodes.new('ShaderNodeGroup')
        grade.name = 'grade_face_base_color'
        grade.label = 'NT调色（与身体一致）'
        grade.node_tree = cls._grade_base_group()
        grade.location = (-780, 270)
        links.new(diffuse_color, grade.inputs['Base Color'])
        diffuse_color = grade.outputs['Graded Color']

        sdf = cls._make_image_node(nodes, face_sdf_path, 'FaceSDFMap', (-1050, -520), non_color=True)
        if sdf.image is None:
            return False
        # Face shadows use the virtual sun projected onto the face X/Y plane.
        # In that plane Z rotation is the horizontal azimuth: (sin(z), cos(z)).
        # This is the same front/side split that SSMT4 feeds to FaceSDF.
        face_front = nodes.new('ShaderNodeValue')
        face_front.name = 'Face Light Front Dot'
        face_front.label = 'Virtual Sun · Face Forward'
        face_front.location = (-1030, -700)
        bind_sun_azimuth(face_front.outputs[0], 'cos(azimuth)')
        face_side = nodes.new('ShaderNodeValue')
        face_side.name = 'Face Light Side Dot'
        face_side.label = 'Virtual Sun · Face Right'
        face_side.location = (-1030, -790)
        bind_sun_azimuth(face_side.outputs[0], 'sin(azimuth)')

        separate_uv = nodes.new('ShaderNodeSeparateXYZ')
        separate_uv.name = 'FaceSDF UV Split'
        separate_uv.location = (-800, -700)
        links.new(uv.outputs['UV'], separate_uv.inputs['Vector'])
        flip_x = nodes.new('ShaderNodeMath')
        flip_x.name = 'FaceSDF Mirror X'
        flip_x.operation = 'SUBTRACT'
        flip_x.inputs[0].default_value = 1.0
        flip_x.location = (-610, -700)
        links.new(separate_uv.outputs['X'], flip_x.inputs[1])
        mirror_for_left_light = nodes.new('ShaderNodeMath')
        mirror_for_left_light.name = 'FaceSDF Mirror for Left Light'
        mirror_for_left_light.operation = 'LESS_THAN'
        mirror_for_left_light.inputs[1].default_value = 0.0
        mirror_for_left_light.location = (-610, -790)
        links.new(face_side.outputs[0], mirror_for_left_light.inputs[0])
        select_x = nodes.new('ShaderNodeMix')
        select_x.name = 'FaceSDF Mirrored X'
        select_x.data_type = 'FLOAT'
        select_x.location = (-410, -690)
        links.new(mirror_for_left_light.outputs[0], select_x.inputs['Factor'])
        links.new(separate_uv.outputs['X'], select_x.inputs['A'])
        links.new(flip_x.outputs[0], select_x.inputs['B'])
        sdf_uv = nodes.new('ShaderNodeCombineXYZ')
        sdf_uv.name = 'FaceSDF UV (light side)'
        sdf_uv.location = (-210, -690)
        links.new(select_x.outputs['Result'], sdf_uv.inputs['X'])
        links.new(separate_uv.outputs['Y'], sdf_uv.inputs['Y'])
        links.new(sdf_uv.outputs['Vector'], sdf.inputs['Vector'])
        channel = str(face_sdf_channel or 'R').upper()
        if channel == 'A':
            sdf_value = sdf.outputs['Alpha']
        else:
            separate = nodes.new('ShaderNodeSeparateColor')
            separate.name = 'FaceSDF Channel'
            separate.mode = 'RGB'
            separate.location = (-780, -520)
            links.new(sdf.outputs['Color'], separate.inputs['Color'])
            sdf_value = separate.outputs[{'R': 'Red', 'G': 'Green', 'B': 'Blue'}.get(channel, 'Red')]

        # threshold = saturate(0.5 - 0.5 * frontDot), exactly as SSMT4.
        threshold = nodes.new('ShaderNodeMath')
        threshold.name = 'FaceSDF Shadow Threshold'
        threshold.label = '0.5 - 0.5 × Face Forward'
        threshold.operation = 'MULTIPLY_ADD'
        threshold.inputs[1].default_value = -0.5
        threshold.inputs[2].default_value = 0.5
        threshold.use_clamp = True
        threshold.location = (-530, -640)
        links.new(face_front.outputs[0], threshold.inputs[0])
        shadow = nodes.new('ShaderNodeMath')
        shadow.name = 'FaceSDF Shadow Mask'
        shadow.operation = 'GREATER_THAN'
        shadow.location = (-300, -520)
        links.new(threshold.outputs[0], shadow.inputs[0])
        links.new(sdf_value, shadow.inputs[1])

        light_tint = nodes.new('ShaderNodeRGB')
        light_tint.name = 'Face Light Tint'
        light_tint.outputs[0].default_value = (0.85, 0.787525, 0.780263, 1.0)
        light_tint.location = (-530, 40)
        shadow_tint = nodes.new('ShaderNodeRGB')
        shadow_tint.name = 'Face Shadow Tint'
        shadow_tint.outputs[0].default_value = (0.7553715, 0.31918, 0.2698094, 1.0)
        shadow_tint.location = (-530, -80)
        lit = nodes.new('ShaderNodeMixRGB')
        lit.name = 'Face Light Color'
        lit.blend_type = 'MULTIPLY'
        lit.inputs[0].default_value = 1.0
        lit.location = (-300, 80)
        links.new(diffuse_color, lit.inputs[1])
        links.new(light_tint.outputs[0], lit.inputs[2])
        dark = nodes.new('ShaderNodeMixRGB')
        dark.name = 'Face Shadow Color'
        dark.blend_type = 'MULTIPLY'
        dark.inputs[0].default_value = 1.0
        dark.location = (-300, -80)
        links.new(diffuse_color, dark.inputs[1])
        links.new(shadow_tint.outputs[0], dark.inputs[2])
        toon = nodes.new('ShaderNodeMixRGB')
        toon.name = 'FaceSDF Toon Color'
        toon.blend_type = 'MIX'
        toon.location = (-50, 40)
        links.new(shadow.outputs[0], toon.inputs[0])
        links.new(lit.outputs['Color'], toon.inputs[1])
        links.new(dark.outputs['Color'], toon.inputs[2])
        final_color = toon.outputs['Color']

        if face_shadow_path:
            face_shadow = cls._make_image_node(nodes, face_shadow_path, 'FaceShadow / LightMap', (-520, -320), non_color=True)
            if face_shadow.image is not None:
                links.new(uv.outputs['UV'], face_shadow.inputs['Vector'])
                fixed_regions = nodes.new('ShaderNodeMixRGB')
                fixed_regions.name = 'Face Fixed Regions (LightMap Alpha)'
                fixed_regions.blend_type = 'MIX'
                fixed_regions.location = (160, 40)
                links.new(face_shadow.outputs['Alpha'], fixed_regions.inputs[0])
                links.new(final_color, fixed_regions.inputs[1])
                links.new(diffuse_color, fixed_regions.inputs[2])
                final_color = fixed_regions.outputs['Color']

        output = nodes.new('ShaderNodeOutputMaterial')
        output.location = (600, 40)
        try:
            emission = nodes.new('ShaderNodeEmission')
            emission.name = 'SSMT Face Unlit Output'
            emission.location = (390, 40)
            emission.inputs['Strength'].default_value = 1.0
            links.new(final_color, emission.inputs['Color'])
            links.new(emission.outputs['Emission'], output.inputs['Surface'])
        except RuntimeError:
            emission = nodes.new('ShaderNodeBsdfPrincipled')
            emission.name = 'SSMT Face Unlit Output'
            emission.location = (390, 40)
            emission.inputs['Emission Strength'].default_value = 1.0
            links.new(final_color, emission.inputs['Emission Color'])
            links.new(emission.outputs['BSDF'], output.inputs['Surface'])

        material['SSMT:MaterialModel'] = 'GIMI FaceSDF Unlit'
        material['SSMT:FaceSDFMapPath'] = face_sdf_path
        material['SSMT:FaceSDFChannel'] = channel
        material['SSMT:FaceShadowPath'] = face_shadow_path or ''
        material['SSMT:SubMeshRole'] = 'Face'
        return True

    @classmethod
    def build_character(
        cls,
        material,
        diffuse_path: str | None,
        normal_path: str | None,
        lightmap_path: str | None,
        directory: str,
    ) -> None:
        """Replace a new import material with the grouped high-fidelity graph."""
        nodes, links = material.node_tree.nodes, material.node_tree.links
        nodes.clear()
        light_object, _ = cls._ensure_preview_objects()
        cls._configure_preview_compositor()
        body_ramp_path = cls.find_optional_texture(directory, ('bodyramp', 'body_ramp', 'rampmap'))
        metal_map_path = cls.find_optional_texture(directory, ('metalmap', 'metal_map', 'matcap'))
        if body_ramp_path is None:
            body_ramp_path = cls._resource_texture_path('DisplayRampMap.dds')
        if metal_map_path is None:
            metal_map_path = cls._resource_texture_path('DisplayMatalMap.dds')

        print(
            '[GIMI Material] maps: '
            f'DiffuseMap={diffuse_path or "<missing>"}; '
            f'NormalMap={normal_path or "<missing>"}; '
            f'LightMap={lightmap_path or "<missing>"}; '
            f'RampMap={body_ramp_path}; MetalMap={metal_map_path}'
        )
        material['SSMT:DiffuseMapPath'] = diffuse_path or '<missing>'
        material['SSMT:NormalMapPath'] = normal_path or '<missing>'
        material['SSMT:LightMapPath'] = lightmap_path or '<missing>'
        material['SSMT:RampMapPath'] = body_ramp_path
        material['SSMT:MetalMapPath'] = metal_map_path

        diffuse = cls._make_image_node(nodes, diffuse_path, 'GIMI DiffuseMap', (-1500, 260))
        normal = cls._make_image_node(nodes, normal_path, 'GIMI NormalMap', (-1500, -40), non_color=True)
        lightmap = cls._make_image_node(nodes, lightmap_path, 'GIMI LightMap', (-1500, -330), non_color=True)
        ramp = cls._make_image_node(nodes, body_ramp_path, 'GIMI BodyRampMap', (-700, -560))
        matcap = cls._make_image_node(nodes, metal_map_path, 'GIMI MetalMap', (-700, -810), non_color=True)
        ramp.interpolation = 'Smart'
        ramp.extension = 'REPEAT'
        ramp.projection = 'FLAT'
        if diffuse.image is None:
            print('[GIMI Material] WARNING: DiffuseMap 缺失，使用洋红纯色占位图。')
            diffuse.image = cls._default_lookup_image(
                cls.GROUP_PREFIX + 'Missing DiffuseMap', (1.0, 0.0, 1.0, 0.0)
            )
        if lightmap.image is None:
            print('[GIMI Material] WARNING: LightMap 缺失，使用纯色占位图 (0, 1, 0, 0)。')
            lightmap.image = cls._default_lookup_image(
                cls.GROUP_PREFIX + 'Missing LightMap', (0.0, 1.0, 0.0, 0.0)
            )
        if normal.image is None:
            print('[GIMI Material] WARNING: NormalMap 缺失，使用 #8080FFFF 纯色图。')
            normal.image = cls._default_lookup_image(
                cls.GROUP_PREFIX + 'Default NormalMap #8080FFFF',
                (128.0 / 255.0, 128.0 / 255.0, 1.0, 1.0),
            )
        if ramp.image is None:
            print('[GIMI Material] WARNING: DisplayRampMap.dds 不可用，使用纯色后备图。')
            ramp.image = cls._default_lookup_image(cls.GROUP_PREFIX + 'Default Body Ramp', (0.72, 0.62, 0.58, 1.0))
        if matcap.image is None:
            print('[GIMI Material] WARNING: DisplayMatalMap.dds 不可用，使用纯色后备图。')
            matcap.image = cls._default_lookup_image(cls.GROUP_PREFIX + 'Default Metal Map', (0.75, 0.75, 0.75, 1.0))
        for data_texture in (normal, lightmap, matcap):
            try:
                data_texture.image.colorspace_settings.name = 'Non-Color'
            except Exception:
                pass

        uv_map = nodes.new('ShaderNodeUVMap')
        uv_map.name = 'GIMI TEXCOORD.xy'
        uv_map.label = 'GIMI primary UV (TEXCOORD.xy)'
        uv_map.location = (-1750, 0)
        # The importer can create TEXCOORD1/2 after TEXCOORD, which makes
        # Blender's implicit active UV unstable.  GIMI color, normal and
        # light maps are sampled from the primary TEXCOORD semantic.
        uv_map.uv_map = 'TEXCOORD.xy'
        for texture in (diffuse, normal, lightmap):
            links.new(uv_map.outputs['UV'], texture.inputs['Vector'])
        coordinates = nodes.new('ShaderNodeGroup')
        coordinates.name = 'GIMI Shared Coordinates'
        coordinates.label = 'SSMT GIMI v12 NTclothes Coordinates'
        coordinates.node_tree = cls._body_coordinates_group()
        coordinates.location = (-700, -220)
        links.new(normal.outputs['Color'], coordinates.inputs['Normal Color'])
        links.new(lightmap.outputs['Color'], coordinates.inputs['LightMap Color'])

        master = nodes.new('ShaderNodeGroup')
        master.name = 'GIMI Body/Clothes Shared Shader'
        master.label = 'SSMT GIMI v12 NTclothes Body Master'
        master.node_tree = cls._body_shader_group()
        master.location = (-450, 80)
        links.new(diffuse.outputs['Color'], master.inputs['Diffuse Color'])
        links.new(normal.outputs['Color'], master.inputs['Normal Color'])
        links.new(lightmap.outputs['Color'], master.inputs['LightMap Color'])
        if cls._image_has_alpha(diffuse.image):
            links.new(diffuse.outputs['Alpha'], master.inputs['Diffuse Alpha'])
        else:
            print('[GIMI Material] WARNING: DiffuseMap 不含 Alpha，禁用特殊发光区域遮罩。')
            master.inputs['Diffuse Alpha'].default_value = 0.0
        if cls._image_has_alpha(lightmap.image):
            links.new(lightmap.outputs['Alpha'], master.inputs['LightMap Alpha'])
            links.new(lightmap.outputs['Alpha'], coordinates.inputs['LightMap Alpha'])
        else:
            print('[GIMI Material] WARNING: LightMap 不含 Alpha，Ramp 材质行使用 0.0。')
            master.inputs['LightMap Alpha'].default_value = 0.0
            coordinates.inputs['LightMap Alpha'].default_value = 0.0
        links.new(coordinates.outputs['Ramp UV'], ramp.inputs['Vector'])
        links.new(ramp.outputs['Color'], master.inputs['Ramp Color'])
        links.new(coordinates.outputs['MatCap UV'], matcap.inputs['Vector'])
        links.new(matcap.outputs['Color'], master.inputs['Metal Color'])
        output = nodes.new('ShaderNodeOutputMaterial')
        output.location = (300, 80)
        try:
            surface = nodes.new('ShaderNodeEmission')
            surface.name = 'GIMI Unlit Output'
            surface.location = (80, 80)
            surface.inputs['Strength'].default_value = 1.0
            links.new(master.outputs['Shader Color'], surface.inputs['Color'])
            links.new(surface.outputs['Emission'], output.inputs['Surface'])
        except RuntimeError:
            surface = nodes.new('ShaderNodeBsdfPrincipled')
            surface.name = 'GIMI Unlit Output'
            surface.location = (80, 80)
            links.new(master.outputs['Shader Color'], surface.inputs['Emission Color'])
            surface.inputs['Emission Strength'].default_value = 1.0
            links.new(surface.outputs['BSDF'], output.inputs['Surface'])

        material['SSMT:MaterialModel'] = 'GIMI High Fidelity'
