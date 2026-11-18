"""Draw-scoped native-cloth support for verified YYSLS vertex shaders.

Each supported shader hash has its own replacement asset because input
signatures and UV layouts are part of the vertex-shader ABI. The hash marker
never replaces or draws a shader by itself. Each submesh checks the original VS
before modifying any vertex, index, or texture slot.
"""

import os
import shutil

from ..common.global_config import GlobalConfig
from ..common.m_ini_builder import M_IniSection, M_SectionType


# Native cloth assets retain original simulation reads with source-ID remapping.
# The main asset comes from the supplied 2026-11-15 shader. The shadow template
# retains the established package shadow ABI; game acceptance is still required.
# Filters are float32-safe and distinct from the legacy bypass marker.
CLOTH_VS_HASH = "21bcfc11171589cb"
CLOTH_VS_FILTER = 823116
CLOTH_SHADER_FILENAME = "yysls_cloth_21bcfc.hlsl"

# The known shadow hash shares the package's established filter value.
# This path does not emit the legacy t119 deformation-bypass marker.
SHADOW_VS_FILTER = 823115

# Tuple fields are original hash, filter value, packaged filename, and a stable
# name suffix used only for sections belonging to variants after the first.
# The tuple stays so a later game build can add a hash without rewriting the
# marker, route, or packaging code around it.
CLOTH_SHADER_VARIANTS = (
    (CLOTH_VS_HASH, CLOTH_VS_FILTER, CLOTH_SHADER_FILENAME, "default"),
    ("18939b13d3a1abcf", 823115, "yysls_cloth_shadow.hlsl", "shadow"),
    # c01 uses the same VS code and binding layout. Its differing material
    # constant declarations are unused by the vertex program.
    ("c01b8886cbc05321", 823114, CLOTH_SHADER_FILENAME, "c01"),
)

# Captured with active cloth, but the original bytecode is not available for
# validating a replacement. Keep the game mesh for this pass.
UNSUPPORTED_CLOTH_VS_HASH = "89f65adb8660822d"
UNSUPPORTED_CLOTH_VS_FILTER = 823118


def copy_shader_asset():
    """Package every supported shader beside the mod INI.

    The addon owns the templates; exported mods must not depend on an author's
    local game installation or an absolute ShaderFixes path. Copying all
    variants keeps the generated INI self-contained.
    """
    addon_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    destination = GlobalConfig.path_generate_mod_folder()
    os.makedirs(destination, exist_ok=True)
    for filename in dict.fromkeys(variant[2] for variant in CLOTH_SHADER_VARIANTS):
        source = os.path.join(addon_root, "resources", filename)
        shutil.copyfile(source, os.path.join(destination, filename))


def _marker_section_name(variant_index, variant):
    """Return a unique identification section name for one shader variant."""
    if variant_index == 0:
        return "ShaderOverride_YYSLS_ClothVS"
    return "ShaderOverride_YYSLS_ClothVS_" + variant[3]


def add_shader_check(ini_builder):
    """Declare identification metadata once per exported INI."""
    # These sections contain no run, skip, or resource commands. Encountering a
    # supported VS on an unmodified game mesh therefore cannot activate a
    # custom shader. Each marker cooperates with independently generated mods.
    # Any duplicate ShaderOverride for the same hash must repeat this filter;
    # 3Dmigoto uses the last duplicate's filter_index when resolving `vs`.
    section = M_IniSection(M_SectionType.ShaderOverride)
    section.append("; Identify original VS hashes without replacing them globally.")
    section.append("; Each supported hash uses a separate float32-safe filter value.")
    for variant_index, variant in enumerate(CLOTH_SHADER_VARIANTS):
        shader_hash, shader_filter, _, _ = variant
        section.append("[" + _marker_section_name(variant_index, variant) + "]")
        section.append("hash = " + shader_hash)
        section.append("allow_duplicate_hash = true")
        section.append("filter_index = " + str(shader_filter))
        section.new_line()
    section.append("[ShaderOverride_YYSLS_UnmappedClothVS]")
    section.append("hash = " + UNSUPPORTED_CLOTH_VS_HASH)
    section.append("allow_duplicate_hash = true")
    section.append("filter_index = " + str(UNSUPPORTED_CLOTH_VS_FILTER))
    section.new_line()
    ini_builder.append_section(section)


def _custom_shader_name(name_suffix, variant_index, variant):
    """Keep the original section name and suffix later variants."""
    base = "CustomShader_YYSLS_NativeCloth_" + name_suffix
    if variant_index == 0:
        return base
    return base + "_" + variant[3]


def append_scoped_submesh(section, command_section, mod_lines, name_suffix, draw_ib):
    """Select a matching VS before running any submesh binding or draw.

    The caller has already matched the submesh and checked the mod switch. One
    shared command list is used by every shader route so buffer bindings,
    texture bindings, object conditions, and draw offsets cannot drift apart.
    A CustomShader installs its variant before executing that shared list and
    restores the original shader after the complete list returns.
    """
    draw_name = "CommandList_YYSLS_Draw_" + name_suffix

    # Recursively emit nested conditions instead of relying on loader-specific
    # support for an "else if" spelling. The final branch keeps the original VS.
    def append_route(variant_index, indent):
        if variant_index == len(CLOTH_SHADER_VARIANTS):
            section.append(indent + "run = " + draw_name)
            return
        variant = CLOTH_SHADER_VARIANTS[variant_index]
        _, shader_filter, _, _ = variant
        custom_name = _custom_shader_name(name_suffix, variant_index, variant)
        section.append(indent + "if vs == " + str(shader_filter))
        section.append(indent + "  run = " + custom_name)
        section.append(indent + "else")
        append_route(variant_index + 1, indent + "  ")
        section.append(indent + "endif")

    # Do not bind VB, IB, or textures in the parent TextureOverride. Evaluating
    # every marker while the game's bindings are original avoids a late shader
    # switch after mod resources have already been installed.
    section.append("; Check the original VS before changing mod resource slots.")
    append_route(0, "")

    # Only the matching CustomShader replaces VS. A plain CommandList call does
    # not establish a shader scope and is therefore used for all other hashes.
    for variant_index, variant in enumerate(CLOTH_SHADER_VARIANTS):
        _, _, filename, _ = variant
        custom_name = _custom_shader_name(name_suffix, variant_index, variant)
        command_section.append("[" + custom_name + "]")
        command_section.append("; Install this VS before the shared binding and draw list.")
        command_section.append("; Restore the original VS only after that list returns.")
        command_section.append("vs = " + filename)
        # The map follows the combined VB and stays bound across every draw.
        # Reserved t118 is explicitly cleared before returning to the game.
        command_section.append("vs-t118 = ref Resource" + draw_ib + "YYSLSClothMap")
        command_section.append("run = " + draw_name)
        command_section.append("vs-t118 = null")
        command_section.new_line()

    # Include the complete original binding and drawing sequence exactly once.
    # Per-object texture restoration remains inside the selected shader scope.
    command_section.append("[" + draw_name + "]")
    command_section.append("; Reached with a selected replacement VS or the original VS.")
    command_section.append("; Keep resource bindings before the original conditional draws.")
    # Preserve object conditions, texture restoration, and exact draw offsets.
    # No t119 bypass marker is emitted on this native-cloth path.
    for line in mod_lines:
        command_section.append(line)
    command_section.new_line()
