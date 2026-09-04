'''
Texture 节点相关的导出辅助函数。
所有贴图 INI 段落与文件复制均从蓝图 SSMTNode_Texture 节点驱动。
'''
import os
import stat
import hashlib
import shutil
import struct
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import bpy

from .m_ini_builder import M_IniBuilder, M_IniSection, M_SectionType
from .global_config import GlobalConfig
from .texture_naming import (
    default_texture_filename,
    default_texture_resource_name,
    normalize_texture_filename,
    normalize_texture_resource_name,
)


@dataclass
class HashTextureBinding:
    """Hash 贴图节点在蓝图中的一次引用及其生效条件。"""

    texture_node: object
    work_key_list: list = field(default_factory=list)

    def get_condition_str(self) -> str:
        return " && ".join(
            f"{work_key.key_name} == {work_key.tmp_value}"
            for work_key in self.work_key_list
        )


class M_TextureHelper:
    """负责把蓝图中的 Texture 节点转换成 3Dmigoto INI 段并复制贴图文件。"""

    # 常见 DXGI 格式 -> 可作为 texconv -f 参数的字符串
    _KNOWN_FORMATS = {
        'BC7_UNORM', 'BC7_UNORM_SRGB', 'R8G8B8A8_UNORM', 'R8G8B8A8_UNORM_SRGB',
        'R10G10B10A2_UNORM', 'R11G11B10_FLOAT', 'BC5_UNORM', 'BC5_SNORM',
        'BC1_UNORM', 'BC1_UNORM_SRGB', 'BC3_UNORM', 'BC3_UNORM_SRGB',
    }
    _FORMAT_ALIASES = {
        'BC7_SRGB': 'BC7_UNORM_SRGB',
        'BC7_Linear': 'BC7_UNORM',
    }
    _resolved_texture_names: dict[int, tuple[str, str]] = {}
    _resolved_texture_nodes: dict[int, object] = {}

    @classmethod
    def prepare_texture_names(cls, texture_node_list) -> None:
        """Resolve export names once, adding stable suffixes for node collisions."""
        cls._resolved_texture_names = {}
        cls._resolved_texture_nodes = {}
        used_resources: set[str] = set()
        used_filenames: set[str] = set()
        resolved_by_texture: dict[tuple, tuple[str, str]] = {}
        nodes = list(dict.fromkeys(id(node) for node in texture_node_list))
        node_by_id = {id(node): node for node in texture_node_list}
        for ordinal, node_id in enumerate(nodes):
            node = node_by_id[node_id]
            tex_hash = cls._node_hash(node)
            raw_resource = str(getattr(node, "resource_name", "") or "").strip()
            raw_filename = str(getattr(node, "texture_filename", "") or "").strip()
            resource = normalize_texture_resource_name(raw_resource) or default_texture_resource_name(
                tex_hash, getattr(node, "mark_name", "")
            )
            filename = normalize_texture_filename(raw_filename) or default_texture_filename(
                tex_hash, getattr(node, "mark_name", "")
            )
            source_path = str(getattr(node, "texture_filepath", "") or "").strip()
            if source_path:
                source_path = os.path.normcase(os.path.abspath(bpy.path.abspath(source_path)))
            target_format = cls._node_target_format(node)
            # Imported/copied blueprint trees can contain several node objects
            # representing the exact same texture.  They must share one INI
            # ResourceTexture.  A collision is split only when the underlying
            # source/format is actually different.
            texture_identity = (
                tex_hash.casefold(),
                source_path or filename.casefold(),
                target_format.casefold(),
            )
            existing_names = resolved_by_texture.get(texture_identity)
            if existing_names is not None:
                cls._resolved_texture_names[node_id] = existing_names
                cls._resolved_texture_nodes[node_id] = node
                continue
            seed = "\0".join((
                str(getattr(node, "name", "") or ""), tex_hash,
                str(getattr(node, "mark_name", "") or ""), raw_resource,
                raw_filename, str(getattr(node, "texture_filepath", "") or ""),
                str(ordinal),
            ))
            suffix = hashlib.blake2s(seed.encode("utf-8"), digest_size=4).hexdigest()
            if resource.casefold() in used_resources:
                resource = f"{resource}_{suffix}"
                counter = 2
                while resource.casefold() in used_resources:
                    resource = f"{resource}_{counter}"
                    counter += 1
            if filename.casefold() in used_filenames:
                stem, extension = os.path.splitext(filename)
                filename = f"{stem}_{suffix}{extension}"
                counter = 2
                while filename.casefold() in used_filenames:
                    filename = f"{stem}_{suffix}_{counter}{extension}"
                    counter += 1
            used_resources.add(resource.casefold())
            used_filenames.add(filename.casefold())
            cls._resolved_texture_names[node_id] = (resource, filename)
            cls._resolved_texture_nodes[node_id] = node
            resolved_by_texture[texture_identity] = (resource, filename)

    @classmethod
    def _get_texconv_path(cls) -> str:
        """查找内置 texconv.exe 路径。"""
        # 优先 TheHerta4 自身 resources
        addon_dir = Path(__file__).parent.parent.resolve()
        candidates = [
            addon_dir / 'resources' / 'texconv.exe',
            addon_dir / '..' / 'resources' / 'texconv.exe',
        ]
        # 其次 SSMT4 工作空间常见位置
        ssmt_candidates = [
            Path('D:/Dev/ssmt4/src-tauri/resources/texconv.exe'),
            Path('D:/Dev/ssmt4/src-tauri/target/debug/resources/texconv.exe'),
        ]
        for p in candidates + ssmt_candidates:
            if p.exists():
                return str(p)
        # 最后尝试 PATH
        for path_env in os.environ.get('PATH', '').split(os.pathsep):
            p = Path(path_env) / 'texconv.exe'
            if p.exists():
                return str(p)
        return ''

    @classmethod
    def detect_dds_format(cls, dds_path: str) -> str:
        """Return a stable DDS source-format identity.

        Known values use texconv-compatible DXGI names.  Valid but uncommon
        DDS layouts deliberately return a stable ``DXGI_FORMAT_<n>`` or
        ``DDS_LEGACY_*`` identity instead of an empty string: an imported
        Texture node can then retain and copy the exact source file even when
        this add-on does not have a conversion name for that layout.
        """
        try:
            with open(dds_path, 'rb') as f:
                data = f.read(148)
            if len(data) < 128 or data[:4] != b'DDS ':
                return ''
            # pixel format fourcc at offset 84
            pf_fourcc = struct.unpack_from('<I', data, 84)[0]
            fourcc = pf_fourcc.to_bytes(4, 'little')
            legacy_format_map = {
                b'DXT1': 'BC1_UNORM',
                b'DXT3': 'BC2_UNORM',
                b'DXT5': 'BC3_UNORM',
                b'ATI1': 'BC4_UNORM',
                b'BC4U': 'BC4_UNORM',
                b'BC4S': 'BC4_SNORM',
                b'ATI2': 'BC5_UNORM',
                b'BC5U': 'BC5_UNORM',
                b'BC5S': 'BC5_SNORM',
            }
            if fourcc != b'DX10':
                compressed_format = legacy_format_map.get(fourcc)
                if compressed_format:
                    return compressed_format

                # A number of SSMT workspace DDS files use the original DDS
                # RGB header rather than the DX10 extension.  They are still
                # perfectly valid uncompressed RGBA textures.  Without this
                # branch the caller sees an unknown source format and invokes
                # texconv to convert R8G8B8A8_UNORM into itself.
                pf_flags, _fourcc, rgb_bit_count, r_mask, g_mask, b_mask, a_mask = struct.unpack_from(
                    '<7I', data, 80
                )
                if (
                    (pf_flags & 0x40)  # DDPF_RGB
                    and rgb_bit_count == 32
                    and (r_mask, g_mask, b_mask, a_mask) == (
                        0x000000FF, 0x0000FF00, 0x00FF0000, 0xFF000000,
                    )
                ):
                    return 'R8G8B8A8_UNORM'
                if (pf_flags & 0x40) and rgb_bit_count:
                    return (
                        f"DDS_LEGACY_RGB{rgb_bit_count}_"
                        f"{r_mask:08X}_{g_mask:08X}_{b_mask:08X}_{a_mask:08X}"
                    )
                if fourcc != b'\0\0\0\0':
                    return f"DDS_LEGACY_FOURCC_{fourcc.hex().upper()}"
                return 'DDS_LEGACY_UNKNOWN'
            dxgi_format = struct.unpack_from('<I', data, 128)[0]
            format_map = {
                28: 'R8G8B8A8_UNORM',
                29: 'R8G8B8A8_UNORM_SRGB',
                24: 'R10G10B10A2_UNORM',
                26: 'R11G11B10_FLOAT',
                98: 'BC7_UNORM',
                99: 'BC7_UNORM_SRGB',
                80: 'BC4_UNORM',
                81: 'BC4_SNORM',
                83: 'BC5_UNORM',
                84: 'BC5_SNORM',
                71: 'BC1_UNORM',
                72: 'BC1_UNORM_SRGB',
                77: 'BC3_UNORM',
                78: 'BC3_UNORM_SRGB',
            }
            return format_map.get(dxgi_format, f'DXGI_FORMAT_{dxgi_format}')
        except Exception as e:
            print(f"[M_TextureHelper] 解析 DDS 格式失败: {dds_path}, {e}")
            return ''

    @classmethod
    def convert_texture_with_texconv(cls, source_path: str, target_path: str, target_format: str) -> bool:
        """调用 texconv 将源贴图转换为目标格式。成功返回 True。"""
        target_format = cls._FORMAT_ALIASES.get(
            target_format.strip().upper(), target_format.strip().upper()
        )
        if not target_format:
            return False
        texconv = cls._get_texconv_path()
        if not texconv:
            print("[M_TextureHelper] 未找到 texconv.exe，跳过格式转换")
            return False
        if not os.path.exists(source_path):
            return False

        try:
            print(f"[M_TextureHelper] 转换贴图: {source_path} -> {target_format}")
            target_dir = os.path.dirname(target_path)
            os.makedirs(target_dir, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="theherta4_texconv_") as temp_dir:
                args = [
                    texconv, '-ft', 'dds', '-f', target_format,
                    '-o', temp_dir, '-y', '--', source_path,
                ]
                result = subprocess.run(
                    args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, check=False,
                )
                if result.returncode != 0:
                    details = (result.stderr or result.stdout or "未知错误").strip()
                    raise RuntimeError(f"texconv 返回 {result.returncode}: {details}")

                converted_path = os.path.join(
                    temp_dir, os.path.splitext(os.path.basename(source_path))[0] + '.dds'
                )
                if not os.path.isfile(converted_path):
                    raise RuntimeError("texconv 未生成预期的 DDS 文件")
                actual_format = cls.detect_dds_format(converted_path)
                if actual_format != target_format:
                    raise RuntimeError(
                        f"转换结果格式不正确，期望 {target_format}，实际 {actual_format or '无法识别'}"
                    )
                # A previous export may have left a read-only DDS (for
                # example after unpacking an archive).  Windows refuses to
                # replace it even though texconv produced a valid temporary
                # file.  Clear only the file's read-only bit before replacing.
                if os.path.isfile(target_path):
                    os.chmod(target_path, stat.S_IWRITE | stat.S_IREAD)
                os.replace(converted_path, target_path)
            return True
        except Exception as e:
            print(f"[M_TextureHelper] texconv 调用异常: {e}")
            return False

    @staticmethod
    def _node_hash(texture_node):
        return str(getattr(texture_node, "texture_hash", "") or "").strip()

    @staticmethod
    def _node_resource_name(texture_node):
        resolved = M_TextureHelper._resolved_texture_names.get(id(texture_node))
        if M_TextureHelper._resolved_texture_nodes.get(id(texture_node)) is not texture_node:
            resolved = None
        if resolved is not None:
            return resolved[0]
        if hasattr(texture_node, "get_resource_name"):
            return normalize_texture_resource_name(texture_node.get_resource_name())
        return default_texture_resource_name(
            M_TextureHelper._node_hash(texture_node),
            getattr(texture_node, "mark_name", ""),
        )

    @staticmethod
    def _node_uses_default_resource_name(texture_node) -> bool:
        return not str(getattr(texture_node, "resource_name", "") or "").strip()

    @staticmethod
    def _node_texture_filename(texture_node):
        resolved = M_TextureHelper._resolved_texture_names.get(id(texture_node))
        if M_TextureHelper._resolved_texture_nodes.get(id(texture_node)) is not texture_node:
            resolved = None
        if resolved is not None:
            return resolved[1]
        if hasattr(texture_node, "get_texture_filename"):
            return normalize_texture_filename(texture_node.get_texture_filename())
        return default_texture_filename(
            M_TextureHelper._node_hash(texture_node),
            getattr(texture_node, "mark_name", ""),
        )

    @staticmethod
    def _normalize_hash_texture_binding(binding) -> HashTextureBinding:
        """兼容旧的纯节点列表，统一为带条件的 Hash 贴图引用。"""
        if isinstance(binding, HashTextureBinding):
            return binding
        if isinstance(binding, tuple) and len(binding) == 2:
            return HashTextureBinding(binding[0], list(binding[1] or []))
        return HashTextureBinding(binding)

    @staticmethod
    def _get_existing_resource_definitions(ini_builder: M_IniBuilder) -> dict[str, str]:
        definitions = {}
        resource_section_types = {
            M_SectionType.ResourceTexture,
            M_SectionType.ResourceAndTextureOverride_Texture,
        }
        for section in getattr(ini_builder, "ini_section_list", []):
            if section.SectionType not in resource_section_types:
                continue
            current_name = ""
            for line in section.SectionLineList:
                if line.startswith("[") and line.endswith("]"):
                    current_name = line[1:-1]
                elif current_name and line.startswith("filename = "):
                    definitions[current_name] = line[len("filename = "):]
        return definitions

    @classmethod
    def _validate_resource_definitions(cls, ini_builder, definitions):
        existing = cls._get_existing_resource_definitions(ini_builder)
        for resource_name, filename in definitions.items():
            previous = existing.get(resource_name)
            normalized_previous = str(previous or "").replace("\\", "/")
            normalized_filename = str(filename or "").replace("\\", "/")
            if normalized_previous.startswith("Textures/"):
                normalized_previous = normalized_previous[len("Textures/"):]
            if normalized_filename.startswith("Textures/"):
                normalized_filename = normalized_filename[len("Textures/"):]
            if previous is not None and normalized_previous != normalized_filename:
                raise ValueError(
                    f"贴图资源名 '{resource_name}' 指向了多个文件: {previous}, {filename}"
                )
        return existing

    @staticmethod
    def _node_source_path(texture_node):
        path = str(getattr(texture_node, "texture_filepath", "") or "").strip()
        if path:
            path = os.path.abspath(bpy.path.abspath(path))
        return path

    @classmethod
    def _node_target_format(cls, texture_node) -> str:
        """获取节点上配置的目标格式，优先使用 effective_texture_format 属性。"""
        if hasattr(texture_node, "effective_texture_format"):
            fmt = str(texture_node.effective_texture_format or "").strip()
            if fmt:
                return cls._FORMAT_ALIASES.get(fmt.upper(), fmt.upper())
        fmt = str(getattr(texture_node, "texture_format", "") or "").strip().upper()
        if fmt == 'AUTO':
            return ''
        return cls._FORMAT_ALIASES.get(fmt, fmt)

    @classmethod
    def copy_texture_files(cls, texture_node_list, output_texture_folder):
        """把 Texture 节点指定的源文件拷贝/转换到生成目录的 Textures 文件夹。"""
        texture_node_list = list(texture_node_list)
        cls.prepare_texture_names(texture_node_list)
        if not os.path.exists(output_texture_folder):
            os.makedirs(output_texture_folder, exist_ok=True)

        for texture_node in texture_node_list:
            source_path = cls._node_source_path(texture_node)
            if not source_path or not os.path.exists(source_path):
                print(f"[M_TextureHelper] 源贴图文件不存在，跳过: {source_path}")
                continue

            target_filename = cls._node_texture_filename(texture_node)
            target_path = os.path.join(output_texture_folder, target_filename)
            if os.path.exists(target_path) and cls.detect_dds_format(target_path):
                continue

            target_format = cls._node_target_format(texture_node)
            source_ext = os.path.splitext(source_path)[1].lower()
            source_format = ''
            if source_ext == '.dds':
                source_format = cls.detect_dds_format(source_path)

            converted = False
            conversion_required = source_ext != '.dds' or bool(
                target_format and source_format != target_format
            )
            if conversion_required and not target_format:
                raise RuntimeError(
                    f"贴图 '{source_path}' 不是 DDS，请在贴图节点中选择目标 DDS 格式"
                )
            if conversion_required:
                converted = cls.convert_texture_with_texconv(source_path, target_path, target_format)
                if not converted:
                    raise RuntimeError(
                        f"贴图转换失败: {source_path} -> {target_path} ({target_format})"
                    )

            if not converted:
                try:
                    shutil.copy2(source_path, target_path)
                    print(f"[M_TextureHelper] 复制贴图: {source_path} -> {target_path}")
                except Exception as e:
                    raise RuntimeError(
                        f"贴图复制失败: {source_path} -> {target_path}: {e}"
                    ) from e

    @classmethod
    def generate_hash_texture_sections(cls, texture_node_list, ini_builder: M_IniBuilder):
        """为 Hash 出口生成资源和带蓝图条件的 TextureOverride 绑定。

        资源声明本身不受分支影响，以便所有分支都能引用它；``this`` 则在
        每条蓝图条件下写入。这样同一个 Hash 可以在不同分支绑定到不同资源。
        """
        texture_node_list = list(texture_node_list)
        hash_nodes = [
            cls._normalize_hash_texture_binding(item).texture_node
            for item in texture_node_list
        ]
        if any(cls._resolved_texture_nodes.get(id(node)) is not node for node in hash_nodes):
            cls.prepare_texture_names(hash_nodes)
        section = M_IniSection(M_SectionType.ResourceAndTextureOverride_Texture)
        resource_filename_dict = {}
        hash_binding_dict = {}
        seen_bindings = set()

        for raw_binding in texture_node_list:
            binding = cls._normalize_hash_texture_binding(raw_binding)
            texture_node = binding.texture_node
            tex_hash = cls._node_hash(texture_node)
            if not tex_hash:
                continue

            resource_name = cls._node_resource_name(texture_node) or default_texture_resource_name(
                tex_hash, getattr(texture_node, "mark_name", "")
            )
            filename = cls._node_texture_filename(texture_node) or default_texture_filename(
                tex_hash, getattr(texture_node, "mark_name", "")
            )
            resource_filename_dict[resource_name] = filename

            condition_str = binding.get_condition_str()
            binding_key = (tex_hash, resource_name, condition_str)
            if binding_key in seen_bindings:
                continue
            seen_bindings.add(binding_key)
            hash_binding_dict.setdefault(tex_hash, []).append((binding, resource_name))

        existing_resources = cls._validate_resource_definitions(
            ini_builder, resource_filename_dict
        )
        for resource_name, filename in resource_filename_dict.items():
            if resource_name in existing_resources:
                continue
            section.append(f"[{resource_name}]")
            section.append(f"filename = Textures/{filename}")
            section.new_line()

        for tex_hash, bindings in hash_binding_dict.items():
            section.append(f"[TextureOverride_{tex_hash}]")
            first_mark_name = str(getattr(bindings[0][0].texture_node, "mark_name", "") or "").strip()
            if first_mark_name:
                section.append(f"; {first_mark_name}")
            section.append(f"hash = {tex_hash}")
            section.append("match_priority = 0")

            # 无条件绑定是默认值，须在分支绑定之前写入，才能被命中的分支覆盖。
            ordered_bindings = sorted(bindings, key=lambda item: bool(item[0].get_condition_str()))
            for binding, resource_name in ordered_bindings:
                condition_str = binding.get_condition_str()
                if condition_str:
                    section.append(f"if {condition_str}")
                    section.append(f"  this = {resource_name}")
                    section.append("endif")
                else:
                    section.append(f"this = {resource_name}")
            section.new_line()

        if resource_filename_dict or hash_binding_dict:
            ini_builder.append_section(section)

    @classmethod
    def get_slot_texture_lines_for_submesh(cls, submesh_model) -> list[str]:
        """返回该 SubMesh 下所有 slot texture 节点对应的 INI 行（聚合去重）。"""
        lines = []
        seen_keys = set()
        for slot_item, texture_node in submesh_model.get_slot_texture_node_list():
            tex_hash = cls._node_hash(texture_node)
            if not tex_hash:
                continue
            resource_name = cls._node_resource_name(texture_node) or default_texture_resource_name(
                tex_hash, getattr(texture_node, "mark_name", "")
            )
            slot_key = getattr(slot_item, "effective_slot_key", f"ps-t{slot_item.slot_index}") if slot_item else "ps-t0"
            key = (slot_key, resource_name)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            value_prefix = "" if slot_key.startswith("ps-t") else "ref "
            lines.append(f"{slot_key} = {value_prefix}{resource_name}")
        return lines

    @classmethod
    def collect_all_texture_nodes(cls, blueprint_model, drawib_model_list) -> list:
        """收集当前生成范围内所有被引用的 Texture 节点（Hash + Slot），按 id 去重。"""
        seen_ids = set()
        result = []
        for raw_binding in getattr(blueprint_model, "hash_texture_node_list", []):
            texture_node = cls._normalize_hash_texture_binding(raw_binding).texture_node
            node_id = id(texture_node)
            if node_id in seen_ids:
                continue
            seen_ids.add(node_id)
            result.append(texture_node)
        for drawib_model in drawib_model_list:
            for submesh_model in getattr(drawib_model, "submesh_model_list", []):
                for slot_item, texture_node in submesh_model.get_slot_texture_node_list():
                    node_id = id(texture_node)
                    if node_id in seen_ids:
                        continue
                    seen_ids.add(node_id)
                    result.append(texture_node)
        return result

    @classmethod
    def generate_slot_texture_resource_sections(cls, drawib_model, blueprint_model, ini_builder: M_IniBuilder):
        """为所有被 Slot 方式引用的 Texture 节点生成 [Resource_...] 段。"""
        section = M_IniSection(M_SectionType.ResourceTexture)
        resource_definitions = {}

        slot_nodes = [
            texture_node
            for submesh_model in drawib_model.submesh_model_list
            for _slot_item, texture_node in submesh_model.get_slot_texture_node_list()
        ]
        if any(cls._resolved_texture_nodes.get(id(node)) is not node for node in slot_nodes):
            cls.prepare_texture_names(slot_nodes)

        # 从所有 SubMesh 的 slot texture 节点中收集
        for submesh_model in drawib_model.submesh_model_list:
            for slot_item, texture_node in submesh_model.get_slot_texture_node_list():
                tex_hash = cls._node_hash(texture_node)
                if not tex_hash:
                    continue
                resource_name = cls._node_resource_name(texture_node) or default_texture_resource_name(
                    tex_hash, getattr(texture_node, "mark_name", "")
                )
                filename = cls._node_texture_filename(texture_node) or default_texture_filename(
                    tex_hash, getattr(texture_node, "mark_name", "")
                )
                resource_definitions[resource_name] = filename


        # Hash 出口的 Texture 节点由 generate_hash_texture_sections 统一生成 [Resource_...] 与 [TextureOverride_...]，
        # 这里只负责 Slot 方式的资源段，避免重复。

        existing_resources = cls._validate_resource_definitions(ini_builder, resource_definitions)
        for resource_name, filename in resource_definitions.items():
            if resource_name in existing_resources:
                continue
            section.append(f"[{resource_name}]")
            section.append(f"filename = Textures/{filename}")
            section.new_line()

        if resource_definitions and any(name not in existing_resources for name in resource_definitions):
            ini_builder.append_section(section)

    @classmethod
    def get_slot_texture_lines_for_drawcall(cls, drawcall_model) -> list[str]:
        """返回单个 DrawCallModel 对应的 slot texture INI 行。

        用于在每次 drawindexed 调用前单独设置槽位。
        """
        lines = []
        seen_keys = set()
        for slot_item, texture_node in getattr(drawcall_model, "slot_texture_node_list", []):
            tex_hash = cls._node_hash(texture_node)
            if not tex_hash:
                continue
            resource_name = cls._node_resource_name(texture_node) or default_texture_resource_name(
                tex_hash, getattr(texture_node, "mark_name", "")
            )
            slot_key = getattr(slot_item, "effective_slot_key", f"ps-t{slot_item.slot_index}") if slot_item else f"ps-t{0}"
            key = (slot_key, resource_name)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            value_prefix = "" if slot_key.startswith("ps-t") else "ref "
            lines.append(f"{slot_key} = {value_prefix}{resource_name}")
        return lines

    @classmethod
    def drawcall_has_normal_map(cls, drawcall_model) -> bool:
        """判断 DrawCall 的 Slot 贴图是否包含 NormalMap 语义。

        不能依赖生成后的资源名：用户可以把 NormalMap 资源重命名为任意字符串。
        """
        for slot_item, texture_node in getattr(drawcall_model, "slot_texture_node_list", []):
            slot_key = str(getattr(slot_item, "effective_slot_key", "") or "").lower()
            slot_type = str(getattr(slot_item, "slot_type", "") or "").lower()
            mark_name = str(getattr(texture_node, "mark_name", "") or "").lower()
            resource_name = str(cls._node_resource_name(texture_node) or "").lower()
            filename = str(cls._node_texture_filename(texture_node) or "").lower()
            if any("normal" in value for value in (slot_key, slot_type, mark_name, resource_name, filename)):
                return True
        return False
