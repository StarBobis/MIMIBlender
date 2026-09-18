"""Draw-scoped no-cloth support for one verified YYSLS vertex shader.

The hash marker never replaces or draws a shader by itself. Each generated
mod draw checks the current VS, then calls a CustomShader for that draw only.
Other VS hashes keep their original draw command and original shader object.
No global frame flag, IniParams slot, or deformation resource is modified.
"""

import os
import shutil

from ..common.global_config import GlobalConfig
from ..common.m_ini_builder import M_IniSection, M_SectionType


# A shared marker lets independently generated mods recognize the same VS.
# Keep it exactly representable as float32, which is how INI filters are stored.
# Do not reuse this value for another hash or an unrelated shader family.
CLOTH_VS_HASH = "ab148fe238420411"
CLOTH_VS_FILTER = 823114
CLOTH_SHADER_FILENAME = "yysls_no_cloth.hlsl"


def copy_shader_asset():
    """Package the shader beside the mod INI, never inside ShaderFixes."""
    # The addon owns the template; exported mods must not depend on the
    # author's local game installation or an absolute ShaderFixes path.
    addon_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    source = os.path.join(addon_root, "resources", CLOTH_SHADER_FILENAME)
    destination = GlobalConfig.path_generate_mod_folder()
    os.makedirs(destination, exist_ok=True)
    shutil.copyfile(source, os.path.join(destination, CLOTH_SHADER_FILENAME))


def add_shader_check(ini_builder):
    """Declare identification metadata once per exported INI."""
    # This section has no run, skip, or resource commands: merely seeing
    # this VS on an unmodified game mesh cannot activate the custom shader.
    section = M_IniSection(M_SectionType.VertexShaderCheck)
    section.append("; Identify the original VS without replacing it globally.")
    section.append("; All YYSLS mods use the same marker for this exact hash.")
    section.append("[ShaderOverride_YYSLS_ClothVS]")
    section.append("hash = " + CLOTH_VS_HASH)
    section.append("allow_duplicate_hash = true")
    section.append("filter_index = " + str(CLOTH_VS_FILTER))
    section.new_line()
    ini_builder.append_section(section)


def append_scoped_draws(section, custom_section, draw_lines, name_suffix):
    """Wrap only actual drawindexed commands, preserving object conditions.

    The caller has already matched the submesh and checked the mod switch.
    Leave texture save/bind/restore commands in their original order. Testing
    the VS at each draw avoids leaking a decision across objects or contexts.
    """
    for line_index, line in enumerate(draw_lines):
        command = line.strip()
        # Branches, mesh comments and per-object texture bindings must not
        # move into a different branch or execute an extra time.
        if not command.lower().startswith("drawindexed ="):
            section.append(line)
            continue

        # Every draw keeps its literal index count, start index and base vertex.
        # A unique section name also preserves separate draws in switch branches.
        indent = line[:len(line) - len(line.lstrip())]
        custom_name = "CustomShader_YYSLS_NoCloth_" + name_suffix + "_" + str(line_index)
        section.append(indent + "; Use the no-cloth VS only for this matching mod draw.")
        section.append(indent + "if vs == " + str(CLOTH_VS_FILTER))
        section.append(indent + "  run = " + custom_name)
        section.append(indent + "else")
        section.append(indent + "  " + command)
        section.append(indent + "endif")

        # CustomShader saves/restores shader objects around the draw. Only
        # VS is replaced, so the game's PS/GS/HS/DS and render state remain.
        # No resource slots are borrowed here, hence no extra slot restoration
        # or global shader-state variable is necessary.
        custom_section.append("[" + custom_name + "]")
        custom_section.append("; The caller checks the original VS before entering.")
        custom_section.append("; CustomShader restores that VS when this draw returns.")
        custom_section.append("vs = " + CLOTH_SHADER_FILENAME)
        custom_section.append(command)
        custom_section.new_line()
