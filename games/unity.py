"""
Unity-style mod exporters (vertex-shader and compute-shader variants).

This module used to hold a single ExportUnity class that picked the VS or
CS path by checking GlobalConfig.logic_name at runtime.  The registry now
maps every LogicName straight to the right variant, so the runtime check
is gone:

- UnityVsExporter: CPU pre-skinning games (GF2, HIMI).
- UnityCsExporter: GPU pre-skinning games (NarakaM, AILIMIT).

All section builders live in games/base/sections.py; this file only
declares the section assembly order of each variant.
"""

from ..common.m_ini_builder import M_IniBuilder
from .base.standard_exporter import StandardExporter
from .base import sections


class UnityVsExporter(StandardExporter):
    """Vertex-shader (CPU pre-skinning) Unity-style exporter."""

    def add_drawib_sections(self, ini_builder: M_IniBuilder, drawib_model):
        sections.add_unity_vs_texture_override_vlr_section(ini_builder=ini_builder, drawib_model=drawib_model)
        sections.add_unity_vs_texture_override_vb_sections(ini_builder=ini_builder, drawib_model=drawib_model, blueprint_model=self.blueprint_model)
        sections.add_unity_vs_texture_override_ib_sections(ini_builder=ini_builder, drawib_model=drawib_model, blueprint_model=self.blueprint_model)
        sections.add_unity_vs_resource_vb_sections(ini_builder=ini_builder, drawib_model=drawib_model)
        sections.add_resource_texture_sections(ini_builder=ini_builder, drawib_model=drawib_model)


class UnityCsExporter(StandardExporter):
    """Compute-shader (GPU pre-skinning) Unity-style exporter."""

    def add_drawib_sections(self, ini_builder: M_IniBuilder, drawib_model):
        sections.add_unity_vs_texture_override_vlr_section(ini_builder=ini_builder, drawib_model=drawib_model)
        sections.add_unity_cs_texture_override_vb_sections(ini_builder=ini_builder, drawib_model=drawib_model, blueprint_model=self.blueprint_model)
        sections.add_unity_cs_texture_override_ib_sections(ini_builder=ini_builder, drawib_model=drawib_model, blueprint_model=self.blueprint_model)
        sections.add_unity_cs_resource_vertexlimit(ini_builder=ini_builder, drawib_model=drawib_model)
        sections.add_unity_cs_resource_vb_sections(ini_builder=ini_builder, drawib_model=drawib_model)
        sections.add_resource_texture_sections(ini_builder=ini_builder, drawib_model=drawib_model)

    def add_final_sections(self, ini_builder: M_IniBuilder, drawib_drawibmodel_dict: dict):
        # The compute path closes the INI with an extra VertexShaderCheck
        # marker section after the usual branch key + shape key sections.
        super().add_final_sections(ini_builder=ini_builder, drawib_drawibmodel_dict=drawib_drawibmodel_dict)
        sections.add_unity_cs_vertex_shader_check(ini_builder=ini_builder)
