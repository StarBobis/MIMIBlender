"""Draw-scoped no-cloth support for one verified YYSLS vertex shader.

The hash marker never replaces or draws a shader by itself. Each submesh
checks the original VS before modifying any vertex, index, or texture slot.
A matching CustomShader binds VS first, then invokes the shared resource and
draw command list. Other VS hashes invoke that list without a shader change.
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


def append_scoped_submesh(section, command_section, mod_lines, name_suffix):
    """Select VS before running any submesh resource bindings or draws.

    The caller has already matched the submesh and checked the mod switch.
    Keep one shared command list for both shader paths so buffer bindings,
    texture bindings, object conditions and draw offsets cannot drift apart.
    CustomShader installs VS before running its command list, then restores
    the original shader after the entire submesh list returns.
    """
    custom_name = "CustomShader_YYSLS_NoCloth_" + name_suffix
    draw_name = "CommandList_YYSLS_Draw_" + name_suffix

    # Do not bind VB/IB/textures in the parent TextureOverride. That would
    # recreate the late shader switch which this scope is intended to avoid.
    # Evaluate the marker while all game bindings are still the originals.
    section.append("; Check the original VS before changing any mod resource slots.")
    section.append("if vs == " + str(CLOTH_VS_FILTER))
    section.append("  run = " + custom_name)
    section.append("else")
    section.append("  run = " + draw_name)
    section.append("endif")

    # Only the matched path replaces VS. CustomShader binds the shader before
    # executing run; a plain CommandList call does not establish shader scope.
    # Leave other shader stages and the game's ranged constant buffers alone.
    command_section.append("[" + custom_name + "]")
    command_section.append("; Install VS first, then bind resources and draw the submesh.")
    command_section.append("; Restore the original VS only after the shared list returns.")
    command_section.append("vs = " + CLOTH_SHADER_FILENAME)
    command_section.append("run = " + draw_name)
    command_section.new_line()

    # Include the complete original binding/drawing sequence exactly once.
    # Object texture save/restore commands stay beside their conditional draw.
    # All draws in this submesh execute under the selected shader scope.
    # No global shader flag or additional resource slot is introduced here.
    command_section.append("[" + draw_name + "]")
    command_section.append("; Reached with either the scoped no-cloth VS or the original VS.")
    command_section.append("; Keep resource bindings before the original conditional draws.")
    for line in mod_lines:
        command_section.append(line)
    command_section.new_line()
