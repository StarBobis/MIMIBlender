"""Object-level black outline for GIMI Body meshes."""
from __future__ import annotations

import bpy


class OutlineError(RuntimeError):
    pass


class GIMIBodyOutline:
    SCHEMA_VERSION = 1
    MODIFIER_NAME = "SSMT GIMI Body Outline"
    MATERIAL_NAME = "SSMT GIMI Outline Black v1"
    PROP_MANAGED = "SSMT:BodyOutlineManaged"
    PROP_SCHEMA_VERSION = "SSMT:BodyOutlineSchemaVersion"
    PROP_BASE_MATERIAL_COUNT = "SSMT:BodyOutlineBaseMaterialCount"
    PROP_SLOT_COUNT = "SSMT:BodyOutlineSlotCount"

    @classmethod
    def ensure(
        cls,
        obj,
        *,
        enabled: bool = True,
        width_mode: str = "RELATIVE",
        width_ratio: float = 0.0008,
        absolute_width: float = 0.0013,
    ):
        cls._validate_object(obj)
        if not enabled:
            cls.remove(obj)
            return None

        original_mesh = obj.data
        made_mesh_copy = False
        if obj.data.users > 1:
            obj.data = obj.data.copy()
            made_mesh_copy = True

        original_slots = list(obj.data.materials)
        original_props = dict(obj.items())
        modifier = obj.modifiers.get(cls.MODIFIER_NAME)
        modifier_existed = modifier is not None
        modifier_state = cls._modifier_state(modifier) if modifier else None
        created_modifier = False

        try:
            outline_material = cls._ensure_outline_material()
            cls._remove_managed_material_tail(obj, outline_material, strict=True)
            base_count = len(obj.data.materials)
            if base_count == 0:
                raise OutlineError(f"Object {obj.name!r} has no material slots")

            for _ in range(base_count):
                obj.data.materials.append(outline_material)

            thickness = cls._calculate_thickness(
                obj, width_mode, width_ratio, absolute_width
            )
            modifier = obj.modifiers.get(cls.MODIFIER_NAME)
            if modifier is None:
                modifier = obj.modifiers.new(cls.MODIFIER_NAME, "SOLIDIFY")
                created_modifier = True
            elif modifier.type != "SOLIDIFY":
                raise OutlineError(f"{cls.MODIFIER_NAME!r} exists but is not Solidify")
            cls._configure_modifier(modifier, thickness, base_count)
            cls._move_modifier_to_end(obj, modifier)

            obj[cls.PROP_MANAGED] = True
            obj[cls.PROP_SCHEMA_VERSION] = cls.SCHEMA_VERSION
            obj[cls.PROP_BASE_MATERIAL_COUNT] = base_count
            obj[cls.PROP_SLOT_COUNT] = base_count
            return modifier
        except Exception:
            if created_modifier and modifier is not None and modifier in obj.modifiers:
                obj.modifiers.remove(modifier)
            elif modifier_existed and modifier is not None and modifier in obj.modifiers:
                cls._restore_modifier(modifier, modifier_state)
            while len(obj.data.materials):
                obj.data.materials.pop(index=len(obj.data.materials) - 1)
            for material in original_slots:
                obj.data.materials.append(material)
            for key in list(obj.keys()):
                del obj[key]
            for key, value in original_props.items():
                obj[key] = value
            if made_mesh_copy:
                failed_mesh = obj.data
                obj.data = original_mesh
                if failed_mesh.users == 0:
                    bpy.data.meshes.remove(failed_mesh)
            raise

    @classmethod
    def remove(cls, obj) -> None:
        cls._validate_object(obj)
        modifier = obj.modifiers.get(cls.MODIFIER_NAME)
        if modifier is not None:
            if modifier.type != "SOLIDIFY":
                raise OutlineError(f"{cls.MODIFIER_NAME!r} is not Solidify")
            obj.modifiers.remove(modifier)
        outline_material = bpy.data.materials.get(cls.MATERIAL_NAME)
        if outline_material is not None:
            cls._remove_managed_material_tail(obj, outline_material, strict=True)
        for key in (
            cls.PROP_MANAGED,
            cls.PROP_SCHEMA_VERSION,
            cls.PROP_BASE_MATERIAL_COUNT,
            cls.PROP_SLOT_COUNT,
        ):
            if key in obj:
                del obj[key]

    @classmethod
    def _ensure_outline_material(cls):
        material = bpy.data.materials.get(cls.MATERIAL_NAME)
        if material is None:
            material = bpy.data.materials.new(cls.MATERIAL_NAME)
        material.use_nodes = True
        nodes, links = material.node_tree.nodes, material.node_tree.links
        nodes.clear()
        geometry = nodes.new("ShaderNodeNewGeometry")
        geometry.name = "Outline Backfacing"
        transparent = nodes.new("ShaderNodeBsdfTransparent")
        transparent.name = "Outline Transparent"
        try:
            black = nodes.new("ShaderNodeEmission")
            black.name = "Outline Black Emission"
            black.inputs["Color"].default_value = (0.0, 0.0, 0.0, 1.0)
            black.inputs["Strength"].default_value = 1.0
        except RuntimeError:
            black = nodes.new("ShaderNodeBsdfPrincipled")
            black.name = "Outline Black Principled"
            black.inputs["Base Color"].default_value = (0.0, 0.0, 0.0, 1.0)
            black.inputs["Roughness"].default_value = 1.0
            if "Specular IOR Level" in black.inputs:
                black.inputs["Specular IOR Level"].default_value = 0.0
        mix = nodes.new("ShaderNodeMixShader")
        mix.name = "Outline Backface Selector"
        output = nodes.new("ShaderNodeOutputMaterial")
        links.new(geometry.outputs["Backfacing"], mix.inputs[0])
        # Solidify flips the outline shell.  Its camera-facing surface is
        # reported as Backfacing, so that side must be transparent.
        links.new(black.outputs[0], mix.inputs[1])
        links.new(transparent.outputs[0], mix.inputs[2])
        links.new(mix.outputs[0], output.inputs[0])
        if hasattr(material, "surface_render_method"):
            material.surface_render_method = "DITHERED"
        elif hasattr(material, "blend_method"):
            material.blend_method = "HASHED"
        material["SSMT:BodyOutlineMaterial"] = True
        return material

    @classmethod
    def _remove_managed_material_tail(cls, obj, outline_material, *, strict: bool):
        if not obj.get(cls.PROP_MANAGED):
            return
        count = int(obj.get(cls.PROP_SLOT_COUNT, 0))
        if count <= 0 or len(obj.data.materials) < count:
            if strict:
                raise OutlineError(f"{obj.name!r} has invalid outline material metadata")
            return
        start = len(obj.data.materials) - count
        tail = [obj.data.materials[i] for i in range(start, len(obj.data.materials))]
        if any(material != outline_material for material in tail):
            if strict:
                raise OutlineError(f"{obj.name!r} outline material tail was modified")
            return
        for _ in range(count):
            obj.data.materials.pop(index=len(obj.data.materials) - 1)

    @staticmethod
    def _calculate_thickness(obj, width_mode, width_ratio, absolute_width):
        if width_mode == "ABSOLUTE":
            return max(float(absolute_width), 1e-6)
        if width_mode != "RELATIVE":
            raise OutlineError(f"Unknown outline width mode: {width_mode}")
        extent = max(abs(float(value)) for value in obj.dimensions)
        if extent <= 1e-8:
            raise OutlineError(f"Object {obj.name!r} has zero dimensions")
        scale = obj.matrix_world.to_scale()
        scale_ref = max(abs(float(value)) for value in scale)
        thickness = extent * float(width_ratio) / max(scale_ref, 1e-8)
        return max(1e-6, min(thickness, 0.05))

    @staticmethod
    def _configure_modifier(modifier, thickness, material_offset):
        modifier.thickness = thickness
        modifier.offset = 1.0
        modifier.use_flip_normals = True
        modifier.use_rim = False
        modifier.material_offset = material_offset
        if hasattr(modifier, "material_offset_rim"):
            modifier.material_offset_rim = 0
        if hasattr(modifier, "solidify_mode"):
            modifier.solidify_mode = "EXTRUDE"
        if hasattr(modifier, "use_even_offset"):
            modifier.use_even_offset = False
        if hasattr(modifier, "use_quality_normals"):
            modifier.use_quality_normals = True
        if hasattr(modifier, "thickness_clamp"):
            modifier.thickness_clamp = 0.02

    @staticmethod
    def _move_modifier_to_end(obj, modifier):
        if not hasattr(obj.modifiers, "move"):
            print(f"[GIMI Outline] WARNING: cannot move {modifier.name!r} to modifier-stack end")
            return
        target = len(obj.modifiers) - 1
        current = list(obj.modifiers).index(modifier)
        if current != target:
            obj.modifiers.move(current, target)

    @staticmethod
    def _modifier_state(modifier):
        return {key: getattr(modifier, key) for key in ("thickness", "offset", "use_flip_normals", "use_rim", "material_offset", "material_offset_rim") if hasattr(modifier, key)}

    @staticmethod
    def _restore_modifier(modifier, state):
        for key, value in (state or {}).items():
            setattr(modifier, key, value)

    @staticmethod
    def _validate_object(obj):
        if obj is None or obj.type != "MESH" or obj.data is None:
            raise OutlineError("GIMI Body outline requires a mesh object")


class SSMT_OT_build_gimi_body_outline(bpy.types.Operator):
    bl_idname = "ssmt.build_gimi_body_outline"
    bl_label = "Build GIMI Body Outline"
    bl_options = {"REGISTER", "UNDO"}
    width_mode: bpy.props.EnumProperty(items=[("RELATIVE", "Relative", ""), ("ABSOLUTE", "Absolute", "")], default="RELATIVE")
    width_ratio: bpy.props.FloatProperty(default=0.0008, min=0.00001, max=0.01, precision=6)
    absolute_width: bpy.props.FloatProperty(default=0.0013, min=0.000001, max=0.1, precision=6)

    @classmethod
    def poll(cls, context):
        return context.active_object is not None and context.active_object.type == "MESH"

    def execute(self, context):
        try:
            GIMIBodyOutline.ensure(context.active_object, width_mode=self.width_mode, width_ratio=self.width_ratio, absolute_width=self.absolute_width)
        except OutlineError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        return {"FINISHED"}


class SSMT_OT_remove_gimi_body_outline(bpy.types.Operator):
    bl_idname = "ssmt.remove_gimi_body_outline"
    bl_label = "Remove GIMI Body Outline"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.active_object is not None and context.active_object.type == "MESH"

    def execute(self, context):
        try:
            GIMIBodyOutline.remove(context.active_object)
        except OutlineError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        return {"FINISHED"}


def register():
    bpy.utils.register_class(SSMT_OT_build_gimi_body_outline)
    bpy.utils.register_class(SSMT_OT_remove_gimi_body_outline)


def unregister():
    bpy.utils.unregister_class(SSMT_OT_remove_gimi_body_outline)
    bpy.utils.unregister_class(SSMT_OT_build_gimi_body_outline)
