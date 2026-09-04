import os
import numpy
import hashlib

from ..model.blueprint_model import BluePrintModel
from ..model.drawib_model import DrawIBModel
from ..common.global_config import GlobalConfig
from ..common.global_properties import GlobalProperties
from ..common.global_config import GlobalConfig
from ..common.m_ini_builder import M_IniBuilder, M_IniSection, M_SectionType
from ..common.m_ini_helper import M_IniHelper
from ..common.m_ini_helper_gui import M_IniHelperGUI
from ..blueprint.blueprint_export_helper import BlueprintExportHelper
from ..workspace.ssmt_workspace import SSMTWorkSpace
from ..utils.format_utils import FormatUtils

from dataclasses import dataclass, field

# NTMIv1 compute shader slot bindings (standard for the NTMIv1 skinning framework)
_NTMI_SKIN_T_GLOBAL_T0 = "cs-t64"
_NTMI_SKIN_T_PALETTE = "cs-t65"
_NTMI_SKIN_T_BLEND = "cs-t66"
_NTMI_SKIN_T_FRAME = "cs-t67"
_NTMI_SKIN_T_POSITION = "cs-t68"
_NTMI_SKIN_T_SHAPEKEY_STATIC = "cs-t69"
_NTMI_SKIN_T_SHAPEKEY_RUNTIME = "cs-t70"
_NTMI_SKIN_U_NORMAL = "cs-u6"
_NTMI_SKIN_U_POSITION = "cs-u7"

# Core NTMIv1 resources and commands
_NTMI_CORE_GLOBAL_T0_RESOURCE = "Resource\\NTMIv1\\RuntimeGlobalT0"
_NTMI_CORE_SKIN_COMMAND = "Resource\\NTMIv1\\SkinFromBoundSlots"
_NTMI_CORE_VERTEX_COUNT = "cs-cb1[0]"

_DEFAULT_DYNAMIC_SLOTS = 16


@dataclass
class ExportNTEMI:

    blueprint_model: BluePrintModel
    drawib_model_list: list[DrawIBModel] = field(default_factory=list, init=False)

    def __post_init__(self):
        self.drawib_model_list = self.blueprint_model.parse_drawib_model_list(combine_ib=False)
        for drawib_model in self.drawib_model_list:
            drawib_model.apply_drawib_alias()

    @staticmethod
    def _resource_token(name: str) -> str:
        """Sanitize a name into a valid INI resource token."""
        return name.replace("-", "_").replace(" ", "_").replace(".", "_")

    # ── buffer file generation ──

    def generate_buffer_files(self):
        buf_output_folder = GlobalConfig.path_generatemod_buffer_folder()

        for drawib_model in self.drawib_model_list:
            for part_index, submesh_model in enumerate(drawib_model.submesh_model_list):
                part_name = self._part_name(drawib_model, part_index, submesh_model)
                self._write_ntmi_buffers(submesh_model, part_name, buf_output_folder)

    def _part_name(self, drawib_model: DrawIBModel, part_index: int, submesh_model) -> str:
        """Build NTMIv1 part name: {draw_ib}_part{index:02d}"""
        return f"{drawib_model.draw_ib}_part{part_index:02d}"

    def _write_ntmi_buffers(self, submesh_model, part_name: str, buf_folder: str):
        """Write all NTMIv1-format buffer files for one part.

        category_buffer_dict values are flat uint8 arrays (raw bytes per category).
        We reinterpret them using the D3D11Element layout from the game type.
        """
        category_bufs = submesh_model.category_buffer_dict
        game_type = submesh_model.d3d11_game_type
        stride_dict = game_type.CategoryStrideDict if game_type else {}
        # Build per-category element layouts: category -> [(element_name, byte_offset, byte_width, format), ...]
        cat_layouts = self._build_category_layouts(game_type) if game_type else {}

        # --- Position buffer (R32_FLOAT) ---
        pos_bytes = category_bufs.get("Position")
        if pos_bytes is not None and "Position" in stride_dict:
            self._write_position_buffer(pos_bytes, stride_dict["Position"],
                                        os.path.join(buf_folder, f"{part_name}-position.buf"))

        # --- Blend buffer (R32_UINT pairs) ---
        blend_bytes = category_bufs.get("Blend")
        if blend_bytes is not None and "Blend" in cat_layouts:
            self._write_blend_buffer(blend_bytes, stride_dict["Blend"], cat_layouts["Blend"],
                                     os.path.join(buf_folder, f"{part_name}-blend.buf"))

        # --- Normal buffer (R8G8B8A8_SNORM alternating TANGENT, NORMAL) ---
        normal_bytes = category_bufs.get("Normal")
        if normal_bytes is not None and "Normal" in cat_layouts:
            self._write_normal_buffer(normal_bytes, stride_dict["Normal"], cat_layouts["Normal"],
                                      os.path.join(buf_folder, f"{part_name}-normal.buf"))

        # --- Texcoord buffer (R16G16_FLOAT) ---
        tex_bytes = category_bufs.get("Texcoord")
        if tex_bytes is not None and "Texcoord" in cat_layouts:
            self._write_texcoord_buffer(tex_bytes, stride_dict["Texcoord"], cat_layouts["Texcoord"],
                                        os.path.join(buf_folder, f"{part_name}-texcoord.buf"))

        # --- Outline buffer (R8G8B8A8_UNORM from COLOR) ---
        color_bytes = category_bufs.get("Color")
        if color_bytes is not None:
            stride = stride_dict.get("Color", 4)
            n_verts = len(color_bytes) // stride if stride > 0 else 0
            if n_verts > 0:
                color_u8 = color_bytes[:n_verts * stride].reshape(n_verts, stride)
                self._write_buf(os.path.join(buf_folder, f"{part_name}-outline.buf"), color_u8.reshape(-1))

        # --- Index buffer (auto R16_UINT or R32_UINT) ---
        ib = submesh_model.ib
        if ib:
            max_index = max(ib)
            if max_index <= 65535:
                ib_arr = numpy.asarray(ib, dtype=numpy.uint16)
            else:
                ib_arr = numpy.asarray(ib, dtype=numpy.uint32)
            self._write_buf(os.path.join(buf_folder, f"{part_name}-ib.buf"), ib_arr)

        # --- Bone palette buffer (R32_UINT) ---
        palette = getattr(submesh_model, 'ntemi_bone_palette', None) or []
        if palette:
            pal_arr = numpy.asarray(palette, dtype=numpy.uint32)
            draw_ib = submesh_model.match_draw_ib
            index_count = submesh_model.match_index_count
            chunk_index = submesh_model.match_first_index
            palette_filename = f"{draw_ib}-{index_count}-{chunk_index}-Palette.buf"
            self._write_buf(os.path.join(buf_folder, palette_filename), pal_arr)

    @staticmethod
    def _build_category_layouts(game_type) -> dict:
        """Build per-category element layouts from D3D11GameType.

        AlignedByteOffset is global across all elements. Category buffers only
        contain the bytes for their own elements, so we subtract the first
        element's offset to make them category-local.

        Returns: {category_name: [(element_name, local_byte_offset, byte_width, format), ...]}
        """
        layouts: dict[str, list] = {}
        for elem in game_type.D3D11ElementList:
            cat = elem.Category
            if cat not in layouts:
                layouts[cat] = []
            byte_width = elem.ByteWidth if elem.ByteWidth > 0 else FormatUtils.format_size(elem.Format)
            layouts[cat].append((elem.ElementName, elem.AlignedByteOffset, byte_width, elem.Format))
        # Make offsets category-local
        for cat, elems in layouts.items():
            base = elems[0][1]  # first element's global offset
            layouts[cat] = [(name, off - base, width, fmt) for name, off, width, fmt in elems]
        return layouts

    def _write_position_buffer(self, data: numpy.ndarray, stride: int, filepath: str):
        """Write R32_FLOAT position buffer. data is flat uint8 per-vertex bytes."""
        n_verts = len(data) // stride if stride > 0 else 0
        if n_verts == 0:
            return
        chunk = data[:n_verts * stride]
        # POSITION is R32G32B32_FLOAT: first 12 bytes = 3 float32s
        pos_f32 = chunk.reshape(n_verts, stride)[:, :12].reshape(-1).view(numpy.float32)
        self._write_buf(filepath, pos_f32)

    def _write_blend_buffer(self, data: numpy.ndarray, stride: int, layout: list, filepath: str):
        """Write NTMIv1 blend buffer: interleaved (index_u32, weight_fixed_u32) per influence.

        layout: list of (element_name, byte_offset, byte_width, format)
        """
        n_verts = len(data) // stride if stride > 0 else 0
        if n_verts == 0:
            return

        chunk = data[:n_verts * stride].reshape(n_verts, stride)

        # Find BLENDINDICES and BLENDWEIGHTS elements in layout
        idx_elem = None
        wt_elem = None
        for name, offset, width, fmt in layout:
            if name == "BLENDINDICES":
                idx_elem = (offset, width, fmt)
            elif name == "BLENDWEIGHTS" or name == "BLENDWEIGHT":
                wt_elem = (offset, width, fmt)

        if idx_elem is None or wt_elem is None:
            print(f"WARNING: Blend layout missing BLENDINDICES/BLENDWEIGHTS, skipping blend buffer")
            return

        idx_offset, idx_width, idx_fmt = idx_elem
        wt_offset, wt_width, wt_fmt = wt_elem

        # Extract raw bytes for indices and weights
        raw_indices = chunk[:, idx_offset:idx_offset + idx_width]
        raw_weights = chunk[:, wt_offset:wt_offset + wt_width]

        # Number of influences = byte_width (R8G8B8A8_UINT has 4 bytes = 4 uint8s)
        n_influences = idx_width

        idx_u32 = numpy.asarray(raw_indices, dtype=numpy.uint32)
        wt_u8 = numpy.asarray(raw_weights, dtype=numpy.uint32)
        wt_fixed = wt_u8 * 257  # [0,255] 鈫?[0,65535]

        # Interleave: idx_0, wt_0, idx_1, wt_1, ...
        interleaved = numpy.empty((n_verts, n_influences * 2), dtype=numpy.uint32)
        interleaved[:, 0::2] = idx_u32
        interleaved[:, 1::2] = wt_fixed

        self._write_buf(filepath, interleaved.reshape(-1))

    def _write_normal_buffer(self, data: numpy.ndarray, stride: int, layout: list, filepath: str):
        """Write NTMIv1 normal buffer: alternating TANGENT and NORMAL as R8G8B8A8_SNORM."""
        n_verts = len(data) // stride if stride > 0 else 0
        if n_verts == 0:
            return

        chunk = data[:n_verts * stride].reshape(n_verts, stride)

        tg_elem = None
        nm_elem = None
        for name, offset, width, fmt in layout:
            if name == "TANGENT":
                tg_elem = (offset, width, fmt)
            elif name == "NORMAL":
                nm_elem = (offset, width, fmt)

        if tg_elem is None or nm_elem is None:
            print(f"WARNING: Normal layout missing TANGENT/NORMAL, skipping normal buffer")
            return

        tg_offset, tg_width, _ = tg_elem
        nm_offset, nm_width, _ = nm_elem

        if tg_width == 0 or nm_width == 0:
            print(f"WARNING: Normal element width is 0 (TANGENT={tg_width}, NORMAL={nm_width}), skipping normal buffer")
            return

        tangents = chunk[:, tg_offset:tg_offset + tg_width].astype(numpy.int8)
        normals = chunk[:, nm_offset:nm_offset + nm_width].astype(numpy.int8)

        # Interleave: T0, N0, T1, N1, ...
        interleaved = numpy.empty((n_verts * 2, tg_width), dtype=numpy.int8)
        interleaved[0::2] = tangents
        interleaved[1::2] = normals
        self._write_buf(filepath, interleaved.reshape(-1))

    def _write_texcoord_buffer(self, data: numpy.ndarray, stride: int, layout: list, filepath: str):
        """Write NTMIv1 texcoord buffer: R16G16_FLOAT from R32G32_FLOAT source."""
        n_verts = len(data) // stride if stride > 0 else 0
        if n_verts == 0:
            return

        chunk = data[:n_verts * stride].reshape(n_verts, stride)

        # Find TEXCOORD element
        tc_elem = None
        for name, offset, width, fmt in layout:
            if name.startswith("TEXCOORD"):
                tc_elem = (offset, width, fmt)
                break

        if tc_elem is None:
            print(f"WARNING: Texcoord layout missing TEXCOORD, skipping texcoord buffer")
            return

        tc_offset, tc_width, tc_fmt = tc_elem

        raw_tc = chunk[:, tc_offset:tc_offset + tc_width]
        # Source is R32G32_FLOAT (8 bytes = 2 float32s)
        tc_f32 = raw_tc.view(numpy.float32).reshape(n_verts, -1)[:, :2]
        tc_f16 = tc_f32.astype(numpy.float16)
        self._write_buf(filepath, tc_f16.reshape(-1))

    @staticmethod
    def _write_buf(filepath: str, arr: numpy.ndarray):
        with open(filepath, 'wb') as f:
            arr.tofile(f)

    # 鈹€鈹€ INI generation 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

    def generate_ini_file(self):
        lines: list[str] = []

        drawib_drawibmodel_dict: dict[str, DrawIBModel] = {}
        draw_ib_active_index_dict: dict[str, int] = {}
        for index, drawib_model in enumerate(self.drawib_model_list):
            draw_ib = drawib_model.draw_ib
            drawib_drawibmodel_dict[draw_ib] = drawib_model
            draw_ib_active_index_dict[draw_ib] = index

        source_suffix = self._source_suffix()

        self._append_constants(lines)
        self._append_present(lines)
        self._append_setup_commandlist(lines)
        self._append_resource_sections(lines, drawib_drawibmodel_dict, source_suffix)
        self._append_collector(lines, source_suffix, drawib_drawibmodel_dict)
        self._append_skin_commandlist(lines, source_suffix, drawib_drawibmodel_dict)
        self._append_draw_overrides(lines, drawib_drawibmodel_dict, draw_ib_active_index_dict, source_suffix)

        # Texture handling
        if not GlobalProperties.forbid_auto_texture_ini():
            self._append_texture_resources(lines, drawib_drawibmodel_dict)
            # Also generate hash-style texture overrides (standard for all game types)
            tex_ini_builder = M_IniBuilder()
            M_IniHelper.generate_hash_style_texture_ini(
                ini_builder=tex_ini_builder,
                drawib_drawibmodel_dict=drawib_drawibmodel_dict,
            )
            M_IniHelper.generate_shared_slot_style_texture_ini(
                ini_builder=tex_ini_builder,
                drawib_drawibmodel_dict=drawib_drawibmodel_dict,
            )
            for section in tex_ini_builder.ini_section_list:
                for sl in section.SectionLineList:
                    if sl:
                        lines.append(sl)
            for drawib_model in self.drawib_model_list:
                M_IniHelper.move_slot_style_textures(draw_ib_model=drawib_model)

        GlobalConfig.generated_mod_number = len(self.drawib_model_list)

        # Branch key / GUI sections
        key_lines = self._build_branch_key_lines()
        lines.extend(key_lines)
        gui_lines = self._build_gui_lines()
        lines.extend(gui_lines)

        ini_filepath = os.path.join(
            GlobalConfig.path_generate_mod_folder(),
            GlobalConfig.get_generated_mod_name() + ".ini",
        )
        self._write_ini(ini_filepath, lines)

    def _source_suffix(self) -> str:
        if self.drawib_model_list:
            return self.drawib_model_list[0].draw_ib
        return "shared"

    # 鈹€鈹€ section builders 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

    def _append_constants(self, lines: list[str]):
        lines.extend([
            "[Constants]",
            "global $ntemi_mod_enabled = 0",
        ])
        if GlobalProperties.generate_branch_mod_gui():
            lines.append("global $ActiveCharacter = 1")
        lines.append("")

    def _append_present(self, lines: list[str]):
        lines.extend([
            "[Present]",
            "if $ntemi_mod_enabled",
            "  run = CommandListNTMISetupResources",
            "endif",
            "",
        ])

    def _append_setup_commandlist(self, lines: list[str]):
        lines.extend([
            "[CommandListNTMISetupResources]",
            "$ntemi_mod_enabled = 1",
            "",
        ])

    def _append_resource_sections(self, lines: list[str], drawib_drawibmodel_dict: dict, source_suffix: str):
        lines.append("; MARK: NTMIv1 Resources")
        lines.append("")

        for drawib_model in self.drawib_model_list:
            for part_index, submesh_model in enumerate(drawib_model.submesh_model_list):
                part_name = self._part_name(drawib_model, part_index, submesh_model)
                token = ExportNTEMI._resource_token(part_name)
                vertex_count = self._get_vertex_count(submesh_model)
                position_float_count = vertex_count * 3
                normal_row_count = vertex_count * 2

                palette_filename = self._palette_filename(submesh_model)
                buffers = {
                    "position": f"{part_name}-position.buf",
                    "blend": f"{part_name}-blend.buf",
                    "normal": f"{part_name}-normal.buf",
                    "texcoord": f"{part_name}-texcoord.buf",
                    "outline": f"{part_name}-outline.buf",
                    "ib": f"{part_name}-ib.buf",
                }
                ib_format = "DXGI_FORMAT_R16_UINT"
                ib = submesh_model.ib
                if ib and max(ib) > 65535:
                    ib_format = "DXGI_FORMAT_R32_UINT"

                lines.extend([
                    f"; [part:{part_name}]",
                    f"[ResourcePalette_{token}]",
                    "type = Buffer",
                    "format = R32_UINT",
                    f"filename = Meshes\\{palette_filename}",
                    "",
                    f"[ResourcePart_{token}_RuntimeSkinnedPosition_UAV]",
                    f"dynamic_slots = {_DEFAULT_DYNAMIC_SLOTS}",
                    "type = RWBuffer",
                    "format = R32_FLOAT",
                    f"array = {position_float_count}",
                    "",
                    f"[ResourcePart_{token}_RuntimeSkinnedPosition]",
                    f"dynamic_slots = {_DEFAULT_DYNAMIC_SLOTS}",
                    "type = Buffer",
                    "format = R32_FLOAT",
                    f"array = {position_float_count}",
                    "",
                    f"[ResourcePart_{token}_RuntimeSkinnedPositionVB]",
                    f"dynamic_slots = {_DEFAULT_DYNAMIC_SLOTS}",
                    "type = Buffer",
                    "stride = 12",
                    "",
                    f"[ResourcePart_{token}_RuntimeSkinnedNormal_UAV]",
                    f"dynamic_slots = {_DEFAULT_DYNAMIC_SLOTS}",
                    "type = RWBuffer",
                    "format = R16G16B16A16_SNORM",
                    f"array = {normal_row_count}",
                    "",
                    f"[ResourcePart_{token}_RuntimeSkinnedNormal]",
                    f"dynamic_slots = {_DEFAULT_DYNAMIC_SLOTS}",
                    "type = Buffer",
                    "format = R16G16B16A16_SNORM",
                    f"array = {normal_row_count}",
                    "",
                    f"[ResourcePart_{token}_RuntimePrevSkinnedPosition]",
                    f"dynamic_slots = {_DEFAULT_DYNAMIC_SLOTS}",
                    f"dynamic_prev_of = ResourcePart_{token}_RuntimeSkinnedPosition",
                    "type = Buffer",
                    "format = R32_FLOAT",
                    f"array = {position_float_count}",
                    "",
                    f"[ResourcePart_{token}_IB]",
                    "type = Buffer",
                    f"format = {ib_format}",
                    f"filename = Meshes\\{buffers['ib']}",
                    "",
                    f"[ResourcePart_{token}_Position]",
                    "type = Buffer",
                    "format = R32_FLOAT",
                    f"filename = Meshes\\{buffers['position']}",
                    "",
                    f"[ResourcePart_{token}_PositionVB]",
                    "type = Buffer",
                    "stride = 12",
                    f"filename = Meshes\\{buffers['position']}",
                    "",
                    f"[ResourcePart_{token}_Blend]",
                    "type = StructuredBuffer",
                    "stride = 8",
                    f"filename = Meshes\\{buffers['blend']}",
                    "",
                    f"[ResourcePart_{token}_BlendTyped]",
                    "type = Buffer",
                    "format = R32_UINT",
                    f"filename = Meshes\\{buffers['blend']}",
                    "",
                    f"[ResourcePart_{token}_Normal]",
                    "type = Buffer",
                    "format = R8G8B8A8_SNORM",
                    f"filename = Meshes\\{buffers['normal']}",
                    "",
                    f"[ResourcePart_{token}_Texcoord]",
                    "type = Buffer",
                    "format = R16G16_FLOAT",
                    f"filename = Meshes\\{buffers['texcoord']}",
                    "",
                    f"[ResourcePart_{token}_OutlineParam]",
                    "type = Buffer",
                    "format = R8G8B8A8_UNORM",
                    f"filename = Meshes\\{buffers['outline']}",
                    "",
                ])

    def _append_collector(self, lines: list[str], source_suffix: str, drawib_drawibmodel_dict: dict):
        """Write the Collector section for bone matrix gathering.

        Uses CB4Hash and CategoryHash from the import metadata where available.
        Values that require FrameAnalysis data are marked with comments.
        """
        lines.append("; MARK: Skin dispatch. Collector gathers BoneAtlas pieces, builds RuntimeGlobalT0, then runs skin.")
        lines.append(f"[CollectorSkinPart_{source_suffix}]")

        # Derive collector config from available metadata
        collector_config = self._derive_collector_config(drawib_drawibmodel_dict)
        lines.append(f"group = {collector_config['group']}")
        if collector_config.get("match_cs_t0_hash"):
            lines.append(f"match_cs_t0_hash = {collector_config['match_cs_t0_hash']}")
        lines.append(f"match_cs_u0_hash = {collector_config['match_cs_u0_hash']}")
        lines.append(f"match_cs_u1_hash = {collector_config['match_cs_u1_hash']}")
        lines.append(f"collect = write, cs-t0, {collector_config['collect_key']}")
        lines.append(f"build = {_NTMI_CORE_GLOBAL_T0_RESOURCE}")

        for drawib_model in self.drawib_model_list:
            for part_index, submesh_model in enumerate(drawib_model.submesh_model_list):
                part_name = self._part_name(drawib_model, part_index, submesh_model)
                token = ExportNTEMI._resource_token(part_name)
                lines.append(
                    f"map = "
                    f"cs-u1:ResourcePart_{token}_RuntimeSkinnedPosition, "
                    f"cs-u1:ResourcePart_{token}_RuntimeSkinnedPositionVB, "
                    f"cs-u0:ResourcePart_{token}_RuntimeSkinnedNormal"
                )

        lines.append(f"run = CommandList_SkinParts_{source_suffix}")
        lines.append("")

    def _derive_collector_config(self, drawib_drawibmodel_dict: dict) -> dict:
        """Derive collector configuration from import metadata."""
        config = {
            "group": "u0",
            "match_cs_t0_hash": "",
            "match_cs_u0_hash": "",
            "match_cs_u1_hash": "",
            "collect_key": "",
        }

        for drawib_model in self.drawib_model_list:
            import_dict = getattr(drawib_model, 'import_json_dict', None) or {}
            if not config["match_cs_t0_hash"]:
                config["match_cs_t0_hash"] = import_dict.get("CB4Hash", "")
            if not config["collect_key"]:
                # Use the first submesh's combined hash as collect key
                cat_hash = import_dict.get("CategoryHash", {})
                if cat_hash:
                    config["collect_key"] = list(cat_hash.values())[0] if isinstance(cat_hash, dict) else str(cat_hash)
            # cs-u0/u1 hashes typically come from FrameAnalysis. Without it,
            # use CategoryHash entries as best guess.
            if not config["match_cs_u0_hash"] or not config["match_cs_u1_hash"]:
                cat_hash = import_dict.get("CategoryHash", {})
                if isinstance(cat_hash, dict):
                    hashes = list(cat_hash.values())
                    if len(hashes) >= 2:
                        if not config["match_cs_u0_hash"]:
                            config["match_cs_u0_hash"] = str(hashes[0])
                        if not config["match_cs_u1_hash"]:
                            config["match_cs_u1_hash"] = str(hashes[1])
                    elif len(hashes) == 1:
                        if not config["match_cs_u0_hash"]:
                            config["match_cs_u0_hash"] = str(hashes[0])
                        if not config["match_cs_u1_hash"]:
                            config["match_cs_u1_hash"] = str(hashes[0])

        return config

    def _append_skin_commandlist(self, lines: list[str], source_suffix: str, drawib_drawibmodel_dict: dict):
        lines.append(f"[CommandList_SkinParts_{source_suffix}]")
        lines.append(f"{_NTMI_SKIN_T_GLOBAL_T0} = {_NTMI_CORE_GLOBAL_T0_RESOURCE}")
        lines.append("")

        for drawib_model in self.drawib_model_list:
            for part_index, submesh_model in enumerate(drawib_model.submesh_model_list):
                part_name = self._part_name(drawib_model, part_index, submesh_model)
                token = _resource_token(part_name)

                lines.extend([
                    f"{_NTMI_SKIN_T_PALETTE} = ResourcePalette_{token}",
                    f"{_NTMI_CORE_VERTEX_COUNT} = {self._get_vertex_count(submesh_model)}",
                    f"{_NTMI_SKIN_T_BLEND} = ResourcePart_{token}_BlendTyped",
                    f"{_NTMI_SKIN_T_FRAME} = ResourcePart_{token}_Normal",
                    f"{_NTMI_SKIN_T_POSITION} = ResourcePart_{token}_Position",
                    f"{_NTMI_SKIN_U_NORMAL} = ResourcePart_{token}_RuntimeSkinnedNormal_UAV",
                    f"{_NTMI_SKIN_U_POSITION} = ResourcePart_{token}_RuntimeSkinnedPosition_UAV",
                    f"run = {_NTMI_CORE_SKIN_COMMAND}",
                    f"ResourcePart_{token}_RuntimeSkinnedPosition = copy ResourcePart_{token}_RuntimeSkinnedPosition_UAV",
                    f"ResourcePart_{token}_RuntimeSkinnedPositionVB = copy ResourcePart_{token}_RuntimeSkinnedPosition_UAV",
                    f"ResourcePart_{token}_RuntimeSkinnedNormal = copy ResourcePart_{token}_RuntimeSkinnedNormal_UAV",
                    "",
                ])

        # Null all bindings after skinning
        lines.extend([
            f"{_NTMI_SKIN_T_GLOBAL_T0} = null",
            f"{_NTMI_SKIN_T_PALETTE} = null",
            f"{_NTMI_SKIN_T_BLEND} = null",
            f"{_NTMI_SKIN_T_FRAME} = null",
            f"{_NTMI_SKIN_T_POSITION} = null",
            f"{_NTMI_SKIN_T_SHAPEKEY_STATIC} = null",
            f"{_NTMI_SKIN_T_SHAPEKEY_RUNTIME} = null",
            f"{_NTMI_SKIN_U_NORMAL} = null",
            f"{_NTMI_SKIN_U_POSITION} = null",
            "",
        ])

    def _append_draw_overrides(self, lines: list[str], drawib_drawibmodel_dict: dict,
                                draw_ib_active_index_dict: dict, source_suffix: str):
        lines.append("; MARK: Draw replacement")
        lines.append("")

        for drawib_model in self.drawib_model_list:
            draw_ib = drawib_model.draw_ib
            active_index = draw_ib_active_index_dict.get(draw_ib, 0)

            # Resolve match hashes from import metadata
            import_dict = getattr(drawib_model, 'import_json_dict', None) or {}
            category_hash = import_dict.get("CategoryHash", {})
            texcoord_hash = str(category_hash.get("Texcoord", "")) if isinstance(category_hash, dict) else ""
            position_hash = str(category_hash.get("Position", "")) if isinstance(category_hash, dict) else ""
            outline_hash = str(category_hash.get("Color", "")) if isinstance(category_hash, dict) else ""

            # Total index count for the region
            total_index_count = sum(
                sm.match_index_count for sm in drawib_model.submesh_model_list
                if sm.match_index_count > 0
            )
            if total_index_count == 0:
                total_index_count = drawib_model.index_count

            first_index = 0
            if drawib_model.submesh_model_list:
                first_indices = [sm.match_first_index for sm in drawib_model.submesh_model_list if sm.match_first_index >= 0]
                if first_indices:
                    first_index = min(first_indices)

            lines.extend([
                f"[TextureOverride_IB_{draw_ib}_{total_index_count}_{first_index}]",
                f"hash = {draw_ib}",
            ])
            if first_index > 0:
                lines.append(f"match_first_index = {first_index}")
            lines.extend([
                f"match_index_count = {total_index_count}",
                "handling = skip",
                f"collector = CollectorSkinPart_{source_suffix}, vb0",
            ])

            for part_index, submesh_model in enumerate(drawib_model.submesh_model_list):
                part_name = self._part_name(drawib_model, part_index, submesh_model)
                token = ExportNTEMI._resource_token(part_name)

                lines.extend([
                    f"; [part:{part_name}] [vertex_count:{self._get_vertex_count(submesh_model)}]",
                    f"ib = ResourcePart_{token}_IB",
                    f"match = vb, dynamic, ResourcePart_{token}_RuntimeSkinnedPositionVB",
                    f"match = vs, dynamic_prev, ResourcePart_{token}_RuntimePrevSkinnedPosition",
                ])
                if texcoord_hash:
                    lines.append(f"match = vs, {texcoord_hash}, ResourcePart_{token}_Texcoord")
                if position_hash:
                    lines.append(f"match = vs, {position_hash}, ResourcePart_{token}_Position")
                lines.append(f"match = vs, dynamic, ResourcePart_{token}_RuntimeSkinnedNormal")
                if outline_hash:
                    lines.append(f"match = vs, {outline_hash}, ResourcePart_{token}_OutlineParam")

                # Texture bindings
                if not GlobalProperties.forbid_auto_texture_ini():
                    texture_markup_info_list = drawib_model.get_submesh_texture_markup_info_list(submesh_model)
                    for tmi in texture_markup_info_list:
                        if getattr(tmi, "mark_type", "") not in ("Slot", "SharedSlot"):
                            continue
                        lines.append(f"{tmi.mark_slot} = {tmi.get_resource_name()}")

                # Draw commands
                for draw_model in submesh_model.drawcall_model_list:
                    index_count = draw_model.index_count
                    first_idx = draw_model.index_offset
                    lines.append(f"; [mesh:{draw_model.obj_name}] [vertex_count:{draw_model.vertex_count}]")
                    lines.append(f"drawindexed = {index_count},{first_idx},0")

                if len(self.blueprint_model.keyname_mkey_dict.keys()) != 0:
                    lines.append(f"$active{active_index} = 1")

            lines.append("")

    def _append_texture_resources(self, lines: list[str], drawib_drawibmodel_dict: dict):
        """Append texture resource sections when auto-texture is enabled."""
        if GlobalProperties.forbid_auto_texture_ini():
            return

        appended: set[str] = set()
        tex_lines: list[str] = []

        for drawib_model in self.drawib_model_list:
            for idx, submesh_model in enumerate(drawib_model.submesh_model_list):
                for tmi in drawib_model.get_submesh_texture_markup_info_list(submesh_model):
                    if getattr(tmi, "mark_type", "") != "Slot":
                        continue
                    rn = tmi.get_resource_name()
                    if rn in appended:
                        continue
                    appended.add(rn)
                    slot_filename = M_IniHelper._get_slot_style_texture_filename(drawib_model, idx, tmi)
                    tex_lines.extend([
                        f"[{rn}]",
                        f"filename = Textures\\{slot_filename}",
                        "",
                    ])

        if tex_lines:
            lines.append("; MARK: Texture resources")
            lines.append("")
            lines.extend(tex_lines)

    def _build_branch_key_lines(self) -> list[str]:
        lines: list[str] = []
        for key_name, mkey_list in self.blueprint_model.keyname_mkey_dict.items():
            lines.append(f"[Key_{key_name}]")
            for mkey in mkey_list:
                lines.append(f"key = {mkey}")
            lines.append("")
        return lines

    def _build_gui_lines(self) -> list[str]:
        if not GlobalProperties.generate_branch_mod_gui():
            return []
        lines: list[str] = []
        lines.append("[Present]")
        lines.append("post $ActiveCharacter = 1")
        lines.append("")
        return lines

    # 鈹€鈹€ helpers 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

    def _get_vertex_count(self, submesh_model) -> int:
        """Get the number of vertex rows in the pre-CS buffers from the Position category stride."""
        pos_bytes = submesh_model.category_buffer_dict.get("Position")
        if pos_bytes is not None and submesh_model.d3d11_game_type:
            stride = submesh_model.d3d11_game_type.CategoryStrideDict.get("Position", 0)
            if stride > 0:
                return len(pos_bytes) // stride
        return submesh_model.vertex_count

    def _palette_filename(self, submesh_model) -> str:
        draw_ib = submesh_model.match_draw_ib
        index_count = submesh_model.match_index_count
        chunk_index = submesh_model.match_first_index
        return f"{draw_ib}-{index_count}-{chunk_index}-Palette.buf"

    def _write_ini(self, filepath: str, lines: list[str]):
        content = "\n".join(lines)
        # Add SHA256 for change detection
        sha256 = hashlib.sha256(content.encode('utf-8')).hexdigest()
        content += "\n;sha256=" + sha256 + "\n"

        # Check if existing INI has the same hash
        existing_sha = ""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                for line in f:
                    stripped = line.strip()
                    if stripped.startswith(";sha256="):
                        existing_sha = stripped[len(";sha256="):].strip()
                        break
        except FileNotFoundError:
            pass

        if existing_sha != sha256:
            print("Write new mod ini because sha256 is not same.")
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
        else:
            print("Skip write mod ini because sha256 is same.")

    # 鈹€鈹€ iter helpers 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

    def _iter_all_submesh_models(self):
        for drawib_model in self.drawib_model_list:
            for submesh_model in drawib_model.submesh_model_list:
                yield submesh_model

    def export(self):
        self.generate_buffer_files()
        self.generate_ini_file()
