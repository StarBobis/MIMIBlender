'''
Time Position Switch INI emission.

This module writes the 3Dmigoto-side half of the Time Position Switch node:
for every (timeline variable, frame value) the exporter has already written
a full-size Position buffer file (see DrawIBModel.write_time_position_files),
and here we declare one resource per frame plus a [Present] block that copies
the active frame's bytes into the real Position resource:

    [Resource65b9cf5aPosition.dyntime0_0]
    type = Buffer
    stride = 12
    filename = Buffers\\65b9cf5a-Position.dyntime0_0.buf

    [Present]
    if $dyntime0 == 0
        Resource65b9cf5aPosition = copy Resource65b9cf5aPosition.dyntime0_0
    elif $dyntime0 == 1
        Resource65b9cf5aPosition = copy Resource65b9cf5aPosition.dyntime0_1
    endif

3Dmigoto facts backing this design (bo3b/3Dmigoto, DirectX11):
- "dst = copy src" recreates the destination buffer only when it is not
  compatible with the source and otherwise reuses the cached one, then runs
  a single CopyResource (CommandList.cpp ResourceCopyOperation::run ->
  RecreateCompatibleResource).  Per-frame copies are therefore cheap.
- The shape key system already proves the "copy into the original resource
  name" pattern in production: the shared slot-style path runs
  "Resource...Position = copy Resource...Position.1" on the first frame
  (m_ini_helper.py add_shapekey_ini_sections).
- [Present] runs once per frame before the draws of that frame
  (HackerDXGI.cpp RunFrameActions), so a copy issued there is visible to
  every drawindexed of the same frame.

Shape key composition: when the DrawIB also has shape key buffers, the copy
targets the PRISTINE backup resource (Resource...Position.1) instead of the
bound one.  The shape key compute shader reads the pristine resource every
frame and adds the weighted deltas on top, so position switching and shape
keys compose instead of overwriting each other.
'''
from .m_ini_builder import M_IniBuilder, M_IniSection, M_SectionType
from .global_config import GlobalConfig, LogicName


def get_time_position_support_error(blueprint_model) -> str:
    '''Return an error message when the current game preset cannot drive
    Time Position Switch mods, or "" when it can.

    Checked once per export in BluePrintModel, so presets without the shared
    slot-style Position resource flow fail loudly instead of silently
    exporting a static mod.
    '''
    if not getattr(blueprint_model, "time_pos_frame_models", None):
        return ""
    # WWMI keeps its positions in an Unreal-style float pipeline with its
    # own resource names (ResourcePositionBuffer...), and NTEMI skins every
    # part on the GPU; neither binds Resource<drawib>Position directly.
    if GlobalConfig.logic_name == LogicName.WWMI:
        return (
            "Time Position Switch is not supported for the WWMI game preset yet; "
            "use the Time Switch node (whole-mesh switching) instead"
        )
    if GlobalConfig.logic_name == LogicName.NTEMI:
        return (
            "Time Position Switch is not supported for the NTEMI game preset yet; "
            "use the Time Switch node (whole-mesh switching) instead"
        )
    # EFMI binds one position resource per Submesh (Resource_<key>_Position)
    # instead of the shared Resource<drawib>Position, so the whole-DrawIB
    # copy mechanism of this node does not apply there.
    if GlobalConfig.logic_name == LogicName.EFMI:
        return (
            "Time Position Switch is not supported for the EFMI game preset yet; "
            "use the Time Switch node (whole-mesh switching) instead"
        )
    return ""


def get_time_position_copy_target(draw_ib: str, drawib_model) -> str:
    '''Return the resource that the per-frame copy writes into.

    Slot-style games bind "Resource<drawib>Position" as the position vertex
    buffer.  When shape keys exist on the same DrawIB, the shape key compute
    rebuilds that resource every frame from the pristine backup
    "Resource<drawib>Position.1", so the frame bytes must be copied into the
    backup instead; the compute then layers the weights on top.
    '''
    if getattr(drawib_model, "shapekey_name_bytelist_dict", None):
        return "Resource" + draw_ib + "Position.1"
    return "Resource" + draw_ib + "Position"


def append_time_position_sections(ini_builder: M_IniBuilder, blueprint_model, drawib_models):
    '''Append the resource declarations and [Present] copy lines of every
    Time Position Switch timeline to the INI builder.

    drawib_models: the DrawIBModel instances this INI file covers (the whole
    list for single-INI games, one model per file for WWMI-style exporters).
    DrawIBs not present in the list are skipped, so per-file exporters never
    emit resources of another file's DrawIB.
    '''
    if blueprint_model is None:
        return
    if not getattr(blueprint_model, "time_pos_frame_models", None):
        return

    keyname_mkey_dict = getattr(blueprint_model, "keyname_mkey_dict", {})

    present_section = M_IniSection(M_SectionType.Present)
    present_section.SectionName = "Present"
    resource_section = M_IniSection(M_SectionType.ResourceBuffer)
    emitted_any = False

    for drawib_model in (drawib_models or []):
        frame_groups = getattr(drawib_model, "time_pos_frame_groups", None)
        if not frame_groups:
            continue

        draw_ib = drawib_model.draw_ib
        position_stride = drawib_model.d3d11_game_type.CategoryStrideDict.get("Position", 0)
        copy_target = get_time_position_copy_target(draw_ib, drawib_model)

        for key_name, value_frame_dict in frame_groups.items():
            timeline_key = keyname_mkey_dict.get(key_name)
            if timeline_key is None:
                continue
            safe_var_name = key_name.lstrip("$")

            # One resource per frame, mirroring the slot-style buffer
            # resource declarations (type/stride/filename).
            for frame_value in sorted(value_frame_dict.keys()):
                resource_name = drawib_model.get_time_position_resource_name(draw_ib, safe_var_name, frame_value)
                resource_section.append("[" + resource_name + "]")
                resource_section.append("type = Buffer")
                resource_section.append("stride = " + str(position_stride))
                resource_section.append(
                    "filename = " + GlobalConfig.ini_buffer_filename(
                        drawib_model.get_time_position_buffer_filename(safe_var_name, frame_value)
                    )
                )
                resource_section.new_line()

            # The copy runs every frame; exactly one branch matches because
            # the timeline variable always holds a value of value_list.
            present_section.append("; Time Position Switch: " + key_name + " -> " + copy_target)
            is_first = True
            for frame_value in sorted(value_frame_dict.keys()):
                keyword = "if" if is_first else "elif"
                is_first = False
                # Conditions the frame branch carries besides the timeline
                # (e.g. an outer Switch Key gate) must ride along, otherwise
                # the position copy would apply even when the outer condition
                # hides the mesh.  All frame models of one (timeline, frame)
                # group share the same chain, so the first one is enough.
                frame_model_list = value_frame_dict[frame_value]
                extra_condition_list = []
                if frame_model_list:
                    first_model = frame_model_list[0]
                    for work_key in getattr(first_model, "work_key_list", []):
                        if work_key.key_name == key_name:
                            continue
                        extra_condition_list.append(work_key.key_name + " == " + str(work_key.tmp_value))
                condition_str = key_name + " == " + str(frame_value)
                if extra_condition_list:
                    condition_str += " && " + " && ".join(extra_condition_list)
                present_section.append(keyword + " " + condition_str)
                resource_name = drawib_model.get_time_position_resource_name(draw_ib, safe_var_name, frame_value)
                present_section.append("  " + copy_target + " = copy " + resource_name)
            present_section.append("endif")
            present_section.new_line()
            emitted_any = True

    if not emitted_any:
        return
    ini_builder.append_section(present_section)
    ini_builder.append_section(resource_section)
