"""APMI shader-scoped skin dispatch and indexed draw replacement."""
from pathlib import Path
import re
from shutil import copyfile

from ..common.buffer_export_helper import BufferExportHelper
from ..common.global_config import GlobalConfig
from ..common.m_ini_builder import M_IniSection, M_SectionType
from ..common.m_ini_helper import M_IniHelper
from ..common.mimi_global_properties import MIMIGlobalProperties
from ..common.skip_draw import is_submesh_skipped
from ..utils.json_utils import JsonUtils
from .base import sections
from .base.standard_exporter import StandardExporter


def section(builder, kind, name, *lines):
    block = M_IniSection(kind)
    block.SectionLineList = ["[" + name + "]", *lines, ""]
    builder.append_section(block)


class APMIExporter(StandardExporter):
    """Keep CPU buffers local to each draw, even when the same IB changes stride."""

    def __init__(self, blueprint_model):
        super().__init__(blueprint_model)
        self.markers = {}
        self.shader_commands = {}
        self.indirect = False
        self.global_hashes = M_IniHelper._collect_global_active_hashes(blueprint_model.global_hash_texture_binding_list)
        self.global_hash_components = {}
        for model in self.drawib_model_list:
            for part in model.submesh_model_list:
                # Old workspaces lack the VS/base-vertex identity for shared CPU IBs.
                # Re-extraction also selects the actual shader's Blend record.
                if not part.apmi_draw.get("VertexShaders"):
                    raise ValueError("Re-extract the APMI workspace with the current MMT version.")
                if part.match_cs == "38cddb8c0126726a":
                    raise ValueError("This historical APMI DynamicBlend shader requires a variable-length encoder.")

    def generate_buffer_files(self):
        folder = Path(GlobalConfig.path_generatemod_buffer_folder())
        for model in self.drawib_model_list:
            if model.d3d11_game_type.GPU_PreSkinning:
                # The skinning dispatch produces one shared VB for its submeshes.
                model.generate_buffer_files(str(folder))
                continue
            for part in model.submesh_model_list:
                # Dynamic CPU allocations share an IB across draws. Each part's
                # local indices must address its own vertex stride and base.
                if part.ib:
                    BufferExportHelper.write_buf_ib_r32_uint(part.ib, str(folder / (part.display_str + "-Index.buf")))
                for name, data in part.category_buffer_dict.items():
                    data.tofile(folder / (part.display_str + "-" + name + ".buf"))

    def marker(self, resource_hash):
        # Integer filter indices must survive conversion through a shader float.
        # Resolve collisions in this mod and share a declaration for repeated hashes.
        if resource_hash not in self.markers:
            value = (int(resource_hash, 16) % 16000000) + 2
            while value in self.markers.values():
                value = value % 16000000 + 2
            self.markers[resource_hash] = value
        return self.markers[resource_hash]

    def hook(self, shader, condition, command):
        # Multiple passes using the same VS get one ShaderOverride section.
        # Each command list only runs for its original IB, VB and draw range.
        lines = self.shader_commands.setdefault(shader, [])
        lines.extend(["if $costume_mods && " + condition, "  run = " + command, "endif"])

    def add_skin(self, builder, model):
        draw = model.draw_ib
        shader = model.submesh_model_list[0].match_cs
        # Preserve live cs-t2 bone matrices and the game's UAV output. Both the
        # bound and thread-group size come from the captured compute program.
        test = "cs-t0 == {} && cs-t1 == {}".format(
            self.marker(model.category_hash_dict["Position"]), self.marker(model.category_hash_dict["Blend"]))
        command = "CommandListAPMISkin_" + draw
        self.hook(shader, test, command)
        section(builder, M_SectionType.CommandList, command,
                "handling = skip", "ResourceAPMIOldCB = ref cs-cb0",
                "ResourceAPMIOldPos = ref cs-t0", "ResourceAPMIOldBlend = ref cs-t1",
                "cs-cb0 = Resource_" + draw + "_VertexLimit",
                "cs-t0 = Resource" + draw + "Position", "cs-t1 = Resource" + draw + "Blend",
                "dispatch = {},1,1".format((model.draw_number + 63) // 64),
                "cs-t1 = ref ResourceAPMIOldBlend", "cs-t0 = ref ResourceAPMIOldPos", "cs-cb0 = ref ResourceAPMIOldCB")
        # The same output hash is also tested by the VS hook. Put its marker on
        # the vertex-limit override to avoid a second section for the same hash.
        sections.add_unity_vs_texture_override_vlr_section(builder, model, filter_index=self.marker(model.vertex_limit_hash))
        sections.add_unity_cs_resource_vertexlimit(builder, model)
        sections.add_unity_cs_resource_vb_sections(builder, model)

    def uses_hash_textures(self, part, marks):
        # A missing automatic DDS produces no Hash override. Explicit hash nodes
        # have their own resolved rows and still work with automatic export off.
        if any(mark.mark_type == "Hash" and (mark.mark_hash or "").lower() in self.automatic_texture_hashes for mark in marks):
            return True
        if any(draw.resolved_hash_texture_binding_list or draw.resolved_hash_slot_binding_list
               for draw in part.drawcall_model_list):
            return True
        if not self.global_hashes:
            return False
        if any((mark.mark_hash or "").lower() in self.global_hashes for mark in marks):
            return True

        # A manually entered global hash can name an unmarked texture. Match the
        # live workspace's texture and component indices, once per LOD, to limit
        # the package check to IBs that actually used a replaced texture.
        folder = Path(part.d3d11_game_type.FilePath).parents[1]
        lod = folder.parent
        if lod not in self.global_hash_components:
            textures = JsonUtils.LoadFromFile(lod / "TrianglelistDedupedFileName.json")
            calls = set()
            for filename in textures:
                # FrameAnalysis can prefix a written resource hash with "!C!=".
                match = re.match(r"^(\d+)-ps-t\d+=(?:!C!=)?([0-9a-f]{8})\b", filename, re.I)
                if match and match[2].lower() in self.global_hashes:
                    calls.add(match[1])
            components = JsonUtils.LoadFromFile(lod / "ComponentName_DrawCallIndexList.json")
            self.global_hash_components[lod] = {name for name, indices in components.items()
                                                if not calls.isdisjoint(indices)}
        return folder.name in self.global_hash_components[lod]

    def add_drawib_sections(self, ini_builder, drawib_model):
        model = drawib_model
        gpu = model.d3d11_game_type.GPU_PreSkinning
        if gpu:
            self.add_skin(ini_builder, model)
        for part in model.submesh_model_list:
            meta = part.apmi_draw
            suffix = model.get_submesh_unique_key(part)
            command = "CommandListAPMIDraw_" + suffix
            test = "ib == {} && vb0 == {}".format(self.marker(model.draw_ib), self.marker(part.apmi_vb0))
            if meta.get("IndirectOffset") is None:
                # ProjectBunny exposes FirstVertex as UINT even for a signed base.
                test += " && (draw_type == 2 || draw_type == 4) && first_vertex == {} && first_index == {} && index_count == {}".format(
                    meta["BaseVertex"] & 0xffffffff, part.match_first_index, part.match_index_count)
            else:
                test += " && draw_type == 6 && indirect_offset == " + str(meta["IndirectOffset"])
            for vs in meta["VertexShaders"]:
                self.hook(vs, test, command)
            lines = ["handling = skip"]
            if self.blueprint_model.keyname_mkey_dict:
                lines += ["$active" + str(GlobalConfig.generated_mod_number) + " = 1", "$mod_visible = 1"]
            # The draw executes inside the VS hook. Replace the CPU VB directly
            # and leave zero-stride constants or the GPU's skinned VB untouched.
            if not is_submesh_skipped(part) and part.ib:
                ib = model.get_submesh_ib_resource_name(part)
                lines.append("ResourceAPMIOldIB = ref ib")
                if gpu:
                    if "Texcoord" in part.category_buffer_dict:
                        lines.extend(["ResourceAPMIOldVB1 = ref vb1", "vb1 = Resource" + model.draw_ib + "Texcoord"])
                else:
                    pos = "Resource_" + suffix + "_Position"
                    section(ini_builder, M_SectionType.ResourceBuffer, pos, "type = Buffer",
                            "stride = " + str(part.d3d11_game_type.CategoryStrideDict["Position"]),
                            "filename = " + GlobalConfig.ini_buffer_filename(part.display_str + "-Position.buf"))
                    section(ini_builder, M_SectionType.ResourceBuffer, ib, "type = Buffer", "format = R32_UINT",
                            "filename = " + GlobalConfig.ini_buffer_filename(part.display_str + "-Index.buf"))
                    lines += ["ResourceAPMIOldVB0 = ref vb0", "vb0 = " + pos]
                lines.append("ib = " + ib)
                marks = model.get_submesh_texture_markup_info_list(part)
                if self.uses_hash_textures(part, marks):
                    # The package checks ps-t0 through ps-t19. Explicit slot
                    # bindings below keep their precedence on mixed components.
                    lines.append("run = CommandListSkinTexture")
                if not MIMIGlobalProperties.forbid_auto_texture_ini():
                    for texture in marks:
                        if texture.mark_type == "Hash" and not re.fullmatch(r"ps-t(?:[0-9]|1[0-9])", texture.mark_slot, re.I):
                            # Preserve explicit checks for slots outside package coverage.
                            lines.append("checktextureoverride = " + texture.mark_slot)
                        elif texture.mark_type in ("Slot", "SharedSlot"):
                            lines.append(texture.mark_slot + " = " + texture.get_resource_name())
                lines.extend(self.draw_commands(ini_builder, model, part))
                # Draw hooks run before the game can change IA bindings again.
                # Restore the original buffers for passes that reuse sticky state.
                lines.append("ib = ref ResourceAPMIOldIB")
                if not gpu:
                    lines.append("vb0 = ref ResourceAPMIOldVB0")
                elif "Texcoord" in part.category_buffer_dict:
                    lines.append("vb1 = ref ResourceAPMIOldVB1")
            section(ini_builder, M_SectionType.CommandList, command, *lines)
        sections.add_resource_texture_sections(ini_builder, model)

    def draw_commands(self, builder, model, part):
        # For a direct instanced call reuse the caller's live instance range.
        # DrawIndexedInstanced may have zero visible instances. Its draw type
        # stays 4, so a zero count never falls through to a non-instanced draw.
        args = (part.drawcall_model_list, model.obj_name_draw_offset)
        direct = M_IniHelper.get_drawindexed_str_list(*args)
        indirect_offset = part.apmi_draw.get("IndirectOffset")
        if indirect_offset is None:
            return ["if draw_type == 4", *M_IniHelper.get_drawindexed_instanced_str_list(*args),
                    "else", *direct, "endif"]

        # ProjectBunny exposes the original indirect argument buffer as 'this'
        # inside a ShaderOverride. Keep live instance count and first instance.
        self.indirect = True
        lines = ["ResourceAPMIOriginalArgs = copy this"]
        for line in direct:
            if not line.lstrip().startswith("drawindexed = "):
                lines.append(line)
                continue
            count, start, _ = line.split("=")[1].strip().split(",")
            params = "ResourceAPMIArgs_{}_{}_{}".format(indirect_offset, count, start)
            if params not in self.indirect_params:
                self.indirect_params.add(params)
                section(builder, M_SectionType.ResourceBuffer, params, "type = Buffer", "format = R32G32B32A32_UINT",
                        "data = {} {} {} 0".format(indirect_offset // 4, count, start))
            lines.extend(["ResourceAPMIParams = ref " + params, "run = CustomShaderAPMIArgs",
                          "drawindexedinstancedindirect = ResourceAPMIArgs, 0"])
        return lines

    def export(self):
        self.indirect_params = set()
        super().export()

    def add_final_sections(self, ini_builder, drawib_drawibmodel_dict):
        # Only selected meshes contribute hooks. The supplied Core.ini contains
        # the costume toggle but no shader-side checks for these slots.
        outputs = {m.vertex_limit_hash for m in self.drawib_model_list if m.d3d11_game_type.GPU_PreSkinning}
        for resource_hash, value in self.markers.items():
            if resource_hash not in outputs:
                section(ini_builder, M_SectionType.TextureOverrideGeneral, "TextureOverrideAPMI_" + resource_hash,
                        "hash = " + resource_hash, "filter_index = " + str(value))
        for shader, lines in self.shader_commands.items():
            section(ini_builder, M_SectionType.ShaderOverride, "ShaderOverrideAPMI_" + shader,
                    "hash = " + shader, "allow_duplicate_hash = true", *lines)
        for name in ("OldIB", "OldVB0", "OldVB1"):
            section(ini_builder, M_SectionType.ResourceBuffer, "ResourceAPMI" + name)
        if outputs:
            for name in ("OldCB", "OldPos", "OldBlend"):
                section(ini_builder, M_SectionType.ResourceBuffer, "ResourceAPMI" + name)
        if self.indirect:
            # Copy the game's argument block into a typed SRV before rebuilding
            # only the index range in a private five-word indirect buffer.
            name = "apmi_indirect.hlsl"
            copyfile(Path(__file__).resolve().parents[1] / "resources" / name, Path(GlobalConfig.path_generate_mod_folder()) / name)
            section(ini_builder, M_SectionType.ResourceBuffer, "ResourceAPMIOriginalArgs", "type = Buffer", "format = R32_UINT")
            section(ini_builder, M_SectionType.ResourceBuffer, "ResourceAPMIParams")
            section(ini_builder, M_SectionType.ResourceBuffer, "ResourceAPMIArgs", "type = RWBuffer", "format = R32_UINT", "array = 5")
            for slot in ("T0", "CB0", "U0"):
                section(ini_builder, M_SectionType.ResourceBuffer, "ResourceAPMIIndirectOld" + slot)
            section(ini_builder, M_SectionType.CommandList, "CustomShaderAPMIArgs", "cs = " + name,
                    "ResourceAPMIIndirectOldT0 = ref cs-t0", "ResourceAPMIIndirectOldCB0 = ref cs-cb0",
                    "ResourceAPMIIndirectOldU0 = ref cs-u0", "cs-t0 = ResourceAPMIOriginalArgs",
                    "cs-cb0 = ResourceAPMIParams", "cs-u0 = ResourceAPMIArgs", "dispatch = 1,1,1",
                    "post cs-u0 = ref ResourceAPMIIndirectOldU0", "post cs-cb0 = ref ResourceAPMIIndirectOldCB0",
                    "post cs-t0 = ref ResourceAPMIIndirectOldT0")
        super().add_final_sections(ini_builder, drawib_drawibmodel_dict)
