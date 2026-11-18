"""Apply an MMT-generated MMD rig to an armature already built by the importer.

The payload owns the bone layout, channel names and constraints. This module
only translates those fields into Blender and MMD Tools properties.
"""

from importlib import import_module

import bpy


def get_tools():
    # Both legacy add-ons and Blender Extensions register the bone properties.
    # Derive the package from that registration rather than assuming its prefix.
    prop = bpy.types.PoseBone.bl_rna.properties.get("mmd_bone")
    if prop is None:
        return None
    bone_type = bpy.types.PropertyGroup.bl_rna_get_subclass_py(prop.fixed_type.identifier)
    if bone_type is None:
        return None
    package, separator, _ = bone_type.__module__.partition(".properties")
    if not separator:
        return None
    try:
        model = import_module(f"{package}.core.model")
        bone = import_module(f"{package}.core.bone")
        return model.Model, bone.FnBone
    except (ImportError, AttributeError):
        return None


def apply(tools, armature, names, payload, character):
    model_type, bone_api = tools
    view_layer = bpy.context.view_layer
    selection = list(bpy.context.selected_objects)
    active = view_layer.objects.active
    collection = armature.users_collection[0]
    label = character.get("Name") or character["Id"]

    # Model.create installs the MMD Tools root metadata and standard frames.
    # Keep its root next to the armature in the collection created by import.
    model = model_type.create(label, character["Id"], scale=0.08, armature_object=armature)
    root = model.rootObject()
    if collection not in root.users_collection:
        collection.objects.link(root)
        for other in list(root.users_collection):
            if other != collection:
                other.objects.unlink(root)

    try:
        bones = [armature.pose.bones[name] for name in names]
        channels = payload["Channels"]
        movable = set(payload["Movable"])
        for index, bone in enumerate(bones):
            channel = channels.get(str(index))
            bone.mmd_bone.name_j = channel or bone.name
            bone.mmd_bone.name_e = bone.name
            bone.mmd_bone.is_controllable = channel is not None
            if channel:
                bone.lock_location = (index not in movable,) * 3

        # MMT supplies the display links independently from parenting, which
        # may pass through game helper bones. Link to Blender's actual names.
        for index, target in payload.get("DisplayConnections", {}).items():
            if target is not None:
                prop = bones[int(index)].mmd_bone
                prop.display_connection_type = 'BONE'
                prop.display_connection_bone = bones[target].name

        # Blender solves to the constraint owner's tail, which MMT placed at
        # the corresponding ankle or toe pivot in the serialized rest rig.
        for entry in payload["Ik"]:
            owner = bones[entry["Owner"]]
            controller = bones[entry["Controller"]]
            constraint = owner.constraints.new("IK")
            constraint.name = "mmd_ik"
            constraint.target = armature
            constraint.subtarget = controller.name
            constraint.use_tail = True
            constraint.chain_count = entry["ChainLength"]
            constraint.iterations = entry["Iterations"]
            constraint.use_stretch = False
            owner.mmd_bone.ik_rotation_constraint = entry["Step"]
            if entry["LimitX"] is not None:
                owner.use_ik_limit_x = True
                owner.ik_min_x, owner.ik_max_x = entry["LimitX"]
                owner.lock_ik_y = True
                owner.lock_ik_z = True

        for entry in payload["AppendRotation"]:
            prop = bones[entry["Bone"]].mmd_bone
            prop.additional_transform_bone = bones[entry["Source"]].name
            prop.additional_transform_influence = entry["Influence"]
            prop.has_additional_rotation = True
            prop.transform_order = 1
        bone_api.apply_additional_transformation(armature)

        model.initialDisplayFrames()
        frame = root.mmd_root.display_item_frames.add()
        frame.name = "操作"
        frame.name_e = "Controls"
        for index in channels:
            item = frame.data.add()
            item.type = 'BONE'
            item.name = bones[int(index)].name
    finally:
        # MMD Tools activates the root while creating it. Restore the import
        # operator's context so later material and blueprint steps can proceed.
        for obj in list(bpy.context.selected_objects):
            obj.select_set(False)
        for obj in selection:
            obj.select_set(True)
        view_layer.objects.active = active
