"""Draw-local YYSLS shape computation, based on the supplied dynamic mod.

The reference copies its base into a UAV before each draw. We keep that order,
but reuse the result across passes until the next Present. Immutable SRVs avoid
repeated input copies. A separate raw VB avoids STRUCTURED|VERTEX_BUFFER flags.
Packed normals accumulate in float scratch space and are normalized only once.
This keeps multiple keys independent of dispatch order and preserves normal W.
"""

from pathlib import Path

from ..blueprint.blueprint_export_helper import BlueprintExportHelper
from ..common.global_config import GlobalConfig
from ..common.m_ini_builder import M_IniSection, M_SectionType
from ..common.m_ini_helper import M_IniHelper


SLOTS = ("cs-u5", "cs-u6", "cs-t50", "cs-t51")


def shape_names(model, keys=None):
    # A DrawIB without a configured shape must never acquire a dangling hook.
    # Missing shapes in other DrawIBs are intentionally independent.
    if keys is None:
        keys = BlueprintExportHelper.get_current_shapekeyname_mkey_dict()
    buffers = getattr(model, "shapekey_name_bytelist_dict", {})
    return [name for name in keys if name in buffers]


def command_name(model):
    # DrawIB identifiers, unlike submesh labels, are already INI-safe hashes.
    return "CommandList_YYSLS_Shape_" + model.draw_ib


def ready_name(model):
    # Nonpersistent flags default to zero on reload, before the first draw.
    return "$mimi_yysls_shape_ready_" + model.draw_ib


def validate_model(model):
    """Resolve category-local word offsets and fail before writing any files.

    Both float positions and compressed UNORM16 positions use the same normal
    codec. Compressed deltas stay in the original bounding-box coordinate space.
    Unknown encodings must fail rather than quietly corrupting vertex bytes.
    Padding and unrelated fields remain opaque and are copied from the seed.
    GPU_PreSkinning is extraction metadata here: the YYSLS consumer is a VB.
    A compute-slot category is not that consumer and is deliberately rejected.
    """
    game = model.d3d11_game_type
    stride = game.CategoryStrideDict.get("Position", 0)
    slot = game.CategoryExtractSlotDict.get("Position", "")
    # D3D11 structured elements are at most 2048 bytes, with 32 IA slots.
    # Reject malformed metadata before HLSL compilation or resource allocation.
    if (stride <= 0 or stride > 2048 or stride % 4 or not slot.startswith("vb")
            or not slot[2:].isdigit() or int(slot[2:]) >= 32):
        raise ValueError("YYSLS shape keys require a word-aligned Position vertex buffer")
    offset = 0
    fields = {}
    for element in game.D3D11ElementList:
        if element.Category != "Position":
            continue
        # Offset is local to this category, not the interleaved export dtype.
        # Semantics may be separated by explicit RAWDATA padding fields.
        semantic = element.SemanticName
        if semantic in ("POSITION", "NORMAL"):
            if semantic in fields or getattr(element, "SemanticIndex", 0) != 0:
                raise ValueError("YYSLS shape keys require one POSITION and one NORMAL")
            fields[semantic] = (element.Format, int(element.ByteWidth), offset)
        offset += int(element.ByteWidth)
    position = fields.get("POSITION")
    normal = fields.get("NORMAL")
    if (offset != stride or position is None or normal is None
            or position[:2] not in (("R32G32B32_FLOAT", 12), ("R16G16B16A16_UNORM", 8))
            or normal[:2] != ("R8G8B8A8_UNORM", 4)
            or position[2] % 4 or normal[2] % 4):
        raise ValueError("Unsupported YYSLS shape layout: expected float3/UNORM16 POSITION and UNORM8 NORMAL; use DrawIndexed animation")
    count = model.vertex_count
    if not isinstance(count, int) or count < 1 or count > 65535 * 64:
        raise ValueError("YYSLS shape key vertex count exceeds the supported Dispatch range")
    # Validate actual byte sizes, not len(ndarray), which can count rows.
    # Even unselected buffers are checked so stale model data cannot leak out.
    buffers = {"base": model.category_buffer_dict.get("Position")}
    buffers.update(model.shapekey_name_bytelist_dict)
    for name, buffer in buffers.items():
        if buffer is None or memoryview(buffer).nbytes != count * stride:
            raise ValueError("YYSLS shape buffer size mismatch: " + str(name))
    return stride // 4, position[2] // 4, normal[2] // 4, int(position[1] == 8)


def shader_filename(model):
    # Lowercase portable names also work on case-sensitive installations.
    return "yysls_shapes_" + model.draw_ib.lower() + ".hlsl"


def write_shaders(models):
    """Package self-contained shaders beside the generated mod INI.

    No absolute developer path or include search path reaches the output.
    The source buffer files are still written by the unchanged DrawIB exporter.
    Layout constants are generated from metadata rather than from a fixed hash.
    A different mesh stride therefore receives its own verified shader layout.
    """
    # Preflight every model before creating a partial set of shader assets.
    keys = BlueprintExportHelper.get_current_shapekeyname_mkey_dict()
    layouts = [(model, validate_model(model)) for model in models if shape_names(model, keys)]
    if not layouts:
        return
    template = (Path(__file__).resolve().parents[1] / "resources/yysls_shapes.hlsl").read_text(encoding="utf-8")
    output = Path(GlobalConfig.path_generate_mod_folder())
    output.mkdir(parents=True, exist_ok=True)
    for model, layout in layouts:
        # Bake the layout into shader constants instead of spending IniParams
        # slots on metadata. One shader is compiled per DrawIB by the loader.
        labels = ("VERTEX_WORDS", "POSITION_WORD", "NORMAL_WORD", "POSITION_UNORM16")
        defines = "// Layout validated by the YYSLS exporter.\n"
        defines += "".join("#define " + label + " " + str(value) + "\n" for label, value in zip(labels, layout))
        (output / shader_filename(model)).write_text(defines + template, encoding="utf-8")


def add_ini_sections(ini_builder, models):
    """Append controls once, then append independent per-DrawIB resources.

    Classic weights remain persistent because they are user-selected settings.
    Time weights and cache flags are transient because reload recreates buffers.
    Present only updates state: dispatch is deferred until a visible mod draw.
    This also initializes correctly if a draw happens before the first Present.
    Missing shape names never produce bindings to nonexistent resource sections.
    """
    # Reuse the existing animation state machine, including playback toggles.
    # Only the GPU work and its scheduling differ from the shared exporter.
    keys = BlueprintExportHelper.get_current_shapekeyname_mkey_dict()
    if not keys:
        return
    usable = [model for model in models if shape_names(model, keys)]
    for model in usable:
        validate_model(model)
    constants = M_IniSection(M_SectionType.Constants)
    present = M_IniSection(M_SectionType.Present)
    hotkeys = M_IniSection(M_SectionType.Key)
    for name, key in keys.items():
        constants.append("; ShapeKey: " + name)
        timed = getattr(key, "key_type", "key") == "time_shapekey"
        persistence = "" if timed else "persist "
        constants.append("global " + persistence + key.key_name + " = " + str(key.initialize_value))
        if timed:
            M_IniHelper.add_time_animation_sections(ini_builder, present, key)
        elif key.initialize_vk_str:
            hotkeys.append("[Key_ShapeKey_" + name + "]")
            if getattr(key, "comment", ""):
                hotkeys.append("; " + key.comment)
            hotkeys.append("key = " + key.initialize_vk_str)
            hotkeys.append("type = cycle")
            hotkeys.append(key.key_name + " = 0,0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8,0.9,1")
            hotkeys.new_line()
    for model in usable:
        # Invalidate after input, time weights, and any Position frame copies.
        # Work stays inside enabled draws; offscreen/disabled models cost nothing.
        constants.append("global " + ready_name(model) + " = 0")
        present.append("post " + ready_name(model) + " = 0")
        add_model_sections(ini_builder, model, keys)
    ini_builder.append_section(constants)
    ini_builder.append_section(present)
    ini_builder.append_section(hotkeys)


def add_model_sections(ini_builder, model, keys):
    """Emit one cached computation and its resources for this DrawIB.

    The visible Position resource is never the immutable delta reference.
    Time Position animation changes the seed, not the shape's base coordinates.
    Borrowed game CS slots are restored before returning to the draw command.
    The output copy removes STRUCTURED flags before it can become a vertex VB.
    """
    root = "Resource" + model.draw_ib
    base = root + "YYSLSShapeBase"
    seed = root + "PositionTimeBase" if getattr(model, "time_pos_frame_groups", None) else base
    names = shape_names(model, keys)
    commands = M_IniSection(M_SectionType.CommandList)
    commands.append("[" + command_name(model) + "]")
    commands.append("if !" + ready_name(model))
    commands.append("run = CustomShader_YYSLS_Shape_" + model.draw_ib)
    commands.append(ready_name(model) + " = 1")
    commands.append("endif")
    # Rebind even on cached draws: another command may have changed Position.
    commands.append(root + "Position = ref " + root + "YYSLSShapeComputed")
    commands.new_line()
    commands.append("[CustomShader_YYSLS_Shape_" + model.draw_ib + "]")
    commands.append("cs = " + shader_filename(model))
    for slot in SLOTS:
        commands.append(root + "YYSLSShapeBackup_" + slot + " = ref " + slot)
    # Copy into the UAV first, as in the working reference, not into a VB ref.
    # Structured immutable inputs already have the correct SRV descriptor.
    commands.append("cs-u5 = copy " + seed)
    commands.append("cs-u6 = ref " + root + "YYSLSShapeScratch")
    commands.append("cs-t50 = ref " + base)
    for index, name in enumerate(names):
        commands.append("x88 = " + keys[name].key_name)
        commands.append("y88 = " + str(int(index == 0)))
        commands.append("z88 = " + str(int(index == len(names) - 1)))
        commands.append("cs-t51 = ref " + root + "YYSLSShapeTarget" + str(index))
        commands.append("Dispatch = " + str((model.vertex_count + 63) // 64) + ",1,1")
    # Explicit RAW-only destination flags prevent inherited structured flags.
    # Referring cs-u5 directly as a VB is not legal on standard D3D11 drivers.
    commands.append(root + "YYSLSShapeComputed = copy cs-u5")
    for slot in SLOTS:
        commands.append(slot + " = ref " + root + "YYSLSShapeBackup_" + slot)
    ini_builder.append_section(commands)

    resources = M_IniSection(M_SectionType.ResourceBuffer)
    stride = model.d3d11_game_type.CategoryStrideDict["Position"]
    resources.append("[" + root + "YYSLSShapeComputed]")
    resources.append("type = ByteAddressBuffer")
    resources.append("misc_flags = buffer_allow_raw_views")
    resources.append("bind_flags = vertex_buffer")
    resources.append("stride = " + str(stride))
    resources.new_line()
    # Float scratch avoids quantizing/normalizing after every individual key.
    # Each first dispatch initializes its own vertex; no CPU clearing is needed.
    resources.append("[" + root + "YYSLSShapeScratch]")
    resources.append("type = StructuredBuffer")
    resources.append("bind_flags = unordered_access")
    resources.append("stride = 32")
    # Single-key blending stays in registers and needs no per-vertex scratch.
    # Keep one bound record so the shader always has a valid UAV descriptor.
    scratch_count = model.vertex_count if len(names) > 1 else 1
    resources.append("array = " + str(scratch_count))
    resources.new_line()
    for slot in SLOTS:
        resources.append("[" + root + "YYSLSShapeBackup_" + slot + "]")
        resources.new_line()
    files = [(base, model.get_category_buffer_filename("Position"))]
    for index, name in enumerate(names):
        # Numeric resource suffixes cannot collide with user shape names.
        # Keep the existing buffer filenames produced by DrawIBModel.
        files.append((root + "YYSLSShapeTarget" + str(index), model.draw_ib + "-Position." + name + ".buf"))
    for resource, filename in files:
        resources.append("[" + resource + "]")
        resources.append("type = StructuredBuffer")
        resources.append("stride = " + str(stride))
        resources.append("filename = " + GlobalConfig.ini_buffer_filename(filename))
        resources.new_line()
    ini_builder.append_section(resources)
