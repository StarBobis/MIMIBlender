"""Position-frame resources and validated whole-DrawIB switching.

A full-size frame replaces one shared Position resource. Independent clocks
cannot safely overwrite disjoint slices with CopyResource: the last full copy
would undo the earlier one. Require one shared clock and one common gate per
DrawIB until a range-copy/compute composition path is implemented.

Present runs at the end of rendering, before DXGI presents the image. Updates
here prepare subsequent draws, not draws already submitted in that frame.
The immutable shape reference must never be overwritten: shape deltas remain
(shape - original), while the accumulation seed can be the animated frame.
"""
from .m_ini_builder import M_IniBuilder, M_IniSection, M_SectionType
from .global_config import GlobalConfig, LogicName


def group_time_position_frames(frame_models):
    """Build the field consumed by both writers and reject ambiguous copies.

    Markers come from traversal, not variable names. Nodes sharing a clock
    can animate several submeshes together; every frame must have one common
    outer condition because a single full-buffer copy cannot gate each slice.
    """
    groups = {}
    common_gate = None
    for model in frame_models:
        key_name = model.time_position_key_name
        timeline_keys = [key for key in model.work_key_list if key.key_name == key_name]
        if len(timeline_keys) != 1:
            raise ValueError("Position.buf Based Dynamic Mod: each provider needs exactly one timeline state")
        gate = sorted((key.key_name, key.tmp_value) for key in model.work_key_list if key.key_name != key_name)
        if common_gate is not None and gate != common_gate:
            raise ValueError("Position.buf Based Dynamic Mod: all frames of a DrawIB must share the same outer conditions")
        common_gate = gate
        frames = groups.setdefault(key_name, {})
        models = frames.setdefault(timeline_keys[0].tmp_value, [])
        if any(other.match_submesh_name == model.match_submesh_name for other in models):
            raise ValueError("Position.buf Based Dynamic Mod: duplicate providers for submesh " + model.match_submesh_name)
        models.append(model)
    # A shared alias is the supported way to animate multiple slices together.
    # Reject independent clocks rather than emitting last-writer-wins output.
    if len(groups) > 1:
        raise ValueError("Position.buf Based Dynamic Mod: use one shared timeline alias per DrawIB")
    return groups


def get_time_position_support_error(blueprint_model) -> str:
    """Reject presets that do not bind the shared Position resource."""
    if not getattr(blueprint_model, "time_pos_frame_models", None):
        return ""
    if GlobalConfig.logic_name in (LogicName.WWMI, LogicName.NTEMI, LogicName.EFMI):
        return (
            "Position.buf Based Dynamic Mod is not supported for the " + str(GlobalConfig.logic_name)
            + " game preset yet; use the DrawIndex Based Dynamic Mod node (whole-mesh switching) instead"
        )
    return ""


def get_time_position_copy_target(draw_ib: str, drawib_model) -> str:
    """Return the mutable frame seed, never the immutable shape reference.

    Shape compute copies this seed to its accumulator but subtracts Position.1
    from every full-weight shape. This gives frame + weight * (shape - base).
    """
    if getattr(drawib_model, "shapekey_name_bytelist_dict", None):
        return "Resource" + draw_ib + "PositionTimeBase"
    return "Resource" + draw_ib + "Position"


def append_time_position_sections(ini_builder: M_IniBuilder, blueprint_model, drawib_models):
    """Emit buffers and copy only when the selected frame or gate changes.

    An empty socket and a disabled gate select the base file explicitly, so
    the last animation frame cannot leak into an inactive branch. Cached state
    is runtime-only and is reset on reload. Shape compute does not modify the
    seed, making this cache valid even when shape weights change every frame.
    """
    if blueprint_model is None or not getattr(blueprint_model, "time_pos_frame_models", None):
        return
    # Input events are processed after pre-Present commands. Run gate-sensitive
    # copies in post-Present so the seed agrees with the hotkey state seen by
    # subsequent draws. A command list keeps every if/local in the same phase.
    present = M_IniSection(M_SectionType.CommandList)
    present.append("[CommandListMimiTimePosition]")
    hook = M_IniSection(M_SectionType.Present)
    hook.SectionName = "Present"
    constants = M_IniSection(M_SectionType.Constants)
    constants.SectionName = "Constants"
    resources = M_IniSection(M_SectionType.ResourceBuffer)

    for model in drawib_models or []:
        groups = getattr(model, "time_pos_frame_groups", {})
        if not groups:
            continue
        draw_ib = model.draw_ib
        target = get_time_position_copy_target(draw_ib, model)
        stride = model.d3d11_game_type.CategoryStrideDict.get("Position", 0)
        has_shapes = bool(getattr(model, "shapekey_name_bytelist_dict", None))
        # Structured seeds feed the shape UAV; raw seeds feed GPU skinning.
        # Ordinary vertex-buffer consumers need neither structured nor raw views.
        resource_type = "Buffer"
        if has_shapes:
            resource_type = "StructuredBuffer"
        elif getattr(model.d3d11_game_type, "GPU_PreSkinning", False):
            resource_type = "ByteAddressBuffer"

        def resource(name, filename):
            resources.append("[" + name + "]")
            resources.append("type = " + resource_type)
            resources.append("stride = " + str(stride))
            resources.append("filename = " + GlobalConfig.ini_buffer_filename(filename))
            resources.new_line()

        # The fallback is separate from the target: restoring from a resource
        # already overwritten by a frame would leave that frame stuck forever.
        fallback = "Resource" + draw_ib + "PositionTimeOriginal"
        base_filename = model.get_category_buffer_filename("Position")
        resource(fallback, base_filename)
        if has_shapes:
            resource(target, base_filename)

        for key_name, frames in groups.items():
            if not frames or key_name not in blueprint_model.keyname_mkey_dict:
                raise ValueError("Position.buf Based Dynamic Mod: missing timeline or frame resources")
            safe_name = key_name.lstrip("$")
            # DrawIB and timeline identifiers are exporter-controlled tokens.
            # Prefix with a letter even when the hash starts with a digit.
            last = "$mimi_pos_" + draw_ib + "_" + safe_name
            selected = last + "_selected"
            constants.append("global " + last + " = -2")
            present.append("local " + selected)
            present.append(selected + " = -1")
            for index, value in enumerate(sorted(frames)):
                name = model.get_time_position_resource_name(draw_ib, safe_name, value)
                resource(name, model.get_time_position_buffer_filename(safe_name, value))
                conditions = [key_name + " == " + str(value)]
                timeline = blueprint_model.keyname_mkey_dict[key_name]
                # The draw timeline uses frame zero when disabled, but Position
                # must restore the separately connected base, not frame zero.
                # Keep enabled in the selection gate so the cache sees -1/off.
                if timeline.toggle_key:
                    conditions.append(timeline.animation_control_name() + "_enabled == 1")
                # Group validation guarantees that all providers share a gate.
                for key in getattr(frames[value][0], "work_key_list", []):
                    if key.key_name != key_name:
                        conditions.append(key.key_name + " == " + str(key.tmp_value))
                present.append(("if " if index == 0 else "elif ") + " && ".join(conditions))
                present.append("  " + selected + " = " + str(value))
            present.append("endif")
            present.append("if " + selected + " != " + last)
            for index, value in enumerate(sorted(frames)):
                name = model.get_time_position_resource_name(draw_ib, safe_name, value)
                present.append(("  if " if index == 0 else "  elif ") + selected + " == " + str(value))
                present.append("    " + target + " = copy " + name)
            present.append("  else")
            present.append("    " + target + " = copy " + fallback)
            present.append("  endif")
            present.append("  " + last + " = " + selected)
            present.append("endif")
            present.new_line()

    # Do not emit an empty command-list hook when this file has no providers.
    # Standard exporters append shape compute after this hook, so post-Present
    # ordering is clock update -> selected seed -> shape accumulation.
    if resources.empty():
        return
    hook.append("post run = CommandListMimiTimePosition")
    ini_builder.append_section(constants)
    ini_builder.append_section(hook)
    ini_builder.append_section(present)
    ini_builder.append_section(resources)
