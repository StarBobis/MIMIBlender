import os
import shutil

from .m_ini_builder import *
from .m_control_flow import M_ControlFlow
from .m_key import M_Key
from .texture_naming import default_texture_resource_name
from ..model.draw_call_model import DrawCallModel
from ..model.drawib_model import DrawIBModel
from ..utils.json_utils import JsonUtils
from ..utils.format_utils import Fatal
from .global_config import GlobalConfig
from .global_properties import GlobalProperties
from ..workspace.ssmt_workspace import SSMTWorkSpace
from ..blueprint.blueprint_export_helper import BlueprintExportHelper
from ..workspace.texture_metadata_helper import TextureMetadataResolver, TextureMarkUpInfo

class M_IniHelper:
    @staticmethod
    def _count_marked_textures(draw_ib_model: DrawIBModel, mark_type: str | None = None) -> int:
        count = 0
        for submesh_model in getattr(draw_ib_model, "submesh_model_list", []):
            texture_info_list = draw_ib_model.get_submesh_texture_markup_info_list(submesh_model)
            for texture_info in texture_info_list:
                if mark_type is not None and getattr(texture_info, "mark_type", "") != mark_type:
                    continue
                count += 1
        return count

    @staticmethod
    def _get_extract_gametype_folder_path(draw_ib_model: DrawIBModel) -> str:
        primary_submesh_metadata = getattr(draw_ib_model, "primary_submesh_metadata", None)
        if primary_submesh_metadata is not None:
            extract_gametype_folder_path = getattr(primary_submesh_metadata, "extract_gametype_folder_path", "")
            if extract_gametype_folder_path:
                return extract_gametype_folder_path

        submesh_model_list = getattr(draw_ib_model, "submesh_model_list", [])
        if submesh_model_list:
            first_submesh_model = submesh_model_list[0]
            submesh_name = getattr(first_submesh_model, "submesh_name", "")
            d3d11_game_type = getattr(first_submesh_model, "d3d11_game_type", None)
            if submesh_name and d3d11_game_type is not None:
                return os.path.join(
                    SSMTWorkSpace.get_submesh_folder_path(submesh_name),
                    "TYPE_" + d3d11_game_type.GameTypeName,
                    "",
                )

        d3d11_game_type = getattr(draw_ib_model, "d3d11_game_type", None)
        if d3d11_game_type is None:
            return ""

        return GlobalConfig.path_extract_gametype_folder(
            draw_ib=draw_ib_model.draw_ib,
            gametype_name=d3d11_game_type.GameTypeName,
        )

    @staticmethod
    def _get_part_extract_gametype_folder_path(draw_ib_model: DrawIBModel, part_name: str) -> str:
        part_name_submesh_dict = getattr(draw_ib_model, "part_name_submesh_dict", {})
        submesh_model = part_name_submesh_dict.get(part_name)
        if submesh_model is None:
            return ""

        d3d11_game_type = getattr(submesh_model, "d3d11_game_type", None)
        if d3d11_game_type is None:
            d3d11_game_type = getattr(draw_ib_model, "d3d11_game_type", None)
        submesh_name = getattr(submesh_model, "submesh_name", "")
        if d3d11_game_type is None or submesh_name == "":
            return ""

        submesh_folder = SSMTWorkSpace.get_submesh_folder_path(submesh_name)
        return os.path.join(submesh_folder, "TYPE_" + d3d11_game_type.GameTypeName, "")

    @classmethod
    def _get_slot_texture_source_path(cls, draw_ib_model: DrawIBModel, part_name: str, texture_markup_info) -> str:
        # 策略1: 通过 part_name 精确定位
        extract_gametype_folder_path = cls._get_part_extract_gametype_folder_path(draw_ib_model, part_name)
        if extract_gametype_folder_path:
            source_path = extract_gametype_folder_path + texture_markup_info.mark_filename
            if os.path.exists(source_path):
                return source_path

        # 策略2: 遍历所有 submesh 的 TYPE_<gametype> 目录
        for submesh_model in getattr(draw_ib_model, "submesh_model_list", []):
            d3d11_game_type = getattr(submesh_model, "d3d11_game_type", None)
            if d3d11_game_type is None:
                d3d11_game_type = getattr(draw_ib_model, "d3d11_game_type", None)
            submesh_name = getattr(submesh_model, "submesh_name", "")
            if d3d11_game_type is None or submesh_name == "":
                continue

            candidate_source_path = os.path.join(
                SSMTWorkSpace.get_submesh_folder_path(submesh_name),
                "TYPE_" + d3d11_game_type.GameTypeName,
                texture_markup_info.mark_filename,
            )
            if os.path.exists(candidate_source_path):
                return candidate_source_path

        return ""

    @staticmethod
    def _get_part_submesh_folder_name(draw_ib_model: DrawIBModel, part_name: str) -> str:
        part_name_submesh_dict = getattr(draw_ib_model, "part_name_submesh_dict", {})
        submesh_model = part_name_submesh_dict.get(part_name)
        if submesh_model is None:
            print("M_IniHelper: part_name 未匹配到 submesh，DrawIB: " + draw_ib_model.draw_ib + "，Part: " + str(part_name))
            return ""

        submesh_folder_name = getattr(submesh_model, "submesh_name", "")
        print("M_IniHelper: Part " + str(part_name) + " 对应 submesh_name: " + submesh_folder_name)
        return submesh_folder_name

    @staticmethod
    def _get_hash_deduped_texture_info(draw_ib_model: DrawIBModel, mark_hash: str):
        for submesh_model in getattr(draw_ib_model, "submesh_model_list", []):
            submesh_folder_name = getattr(submesh_model, "submesh_name", "")
            if not submesh_folder_name:
                continue

            hash_deduped_texture_info_dict = SSMTWorkSpace.get_hash_deduped_texture_info_dict(submesh_folder_name=submesh_folder_name)
            deduped_texture_info = hash_deduped_texture_info_dict.get(mark_hash, None)
            if deduped_texture_info is not None:
                print(
                    "M_IniHelper: 在 submesh_name "
                    + submesh_folder_name
                    + " 中找到 Hash 去重信息，Hash: "
                    + mark_hash
                )
                return deduped_texture_info

        print("M_IniHelper: 当前 DrawIB 的所有 submesh_name 中都未找到 Hash 去重信息，Hash: " + mark_hash)
        return None

    @staticmethod
    def get_drawindexed_str_list(
        ordered_draw_obj_model_list: list[DrawCallModel],
        obj_name_draw_offset_dict: dict[str, int] | None = None,
    ) -> list[str]:
        # 传统的使用DrawIndexed方式调用这个
        # 在输出之前，我们需要根据condition对obj_model进行分组
        condition_str_obj_model_list_dict:dict[str,list[DrawCallModel]] = {}
        for obj_model in ordered_draw_obj_model_list:
            condition_str = obj_model.get_condition_str()

            obj_model_list = condition_str_obj_model_list_dict.get(condition_str,[])
            
            obj_model_list.append(obj_model)
            condition_str_obj_model_list_dict[condition_str] = obj_model_list
        
        drawindexed_str_list:list[str] = []
        for condition_str, obj_model_list in condition_str_obj_model_list_dict.items():
            if condition_str != "":
                drawindexed_str_list.append("if " + condition_str)
                for obj_model in obj_model_list:
                    display_name = str(getattr(obj_model, 'obj_name', '') or getattr(obj_model, 'display_name', '') or '')
                    drawindexed_str_list.append("  ; [mesh:" + display_name + "] [vertex_count:" + str(obj_model.vertex_count) + "]" )
                    draw_line = obj_model.get_drawindexed_str(obj_name_draw_offset_dict)
                    from .m_custom_shader_helper import M_CustomShaderHelper
                    drawindexed_str_list.extend(
                        "  " + line
                        for line in M_CustomShaderHelper.get_draw_lines(obj_model, draw_line)
                    )
                drawindexed_str_list.append("endif")
            else:
                for obj_model in obj_model_list:
                    display_name = str(getattr(obj_model, 'obj_name', '') or getattr(obj_model, 'display_name', '') or '')
                    drawindexed_str_list.append("; [mesh:" + display_name + "] [vertex_count:" + str(obj_model.vertex_count) + "]" )
                    draw_line = obj_model.get_drawindexed_str(obj_name_draw_offset_dict)
                    from .m_custom_shader_helper import M_CustomShaderHelper
                    drawindexed_str_list.extend(
                        M_CustomShaderHelper.get_draw_lines(obj_model, draw_line)
                    )
            drawindexed_str_list.append("")

        return drawindexed_str_list

    @staticmethod
    def append_drawindexed_with_slot_lines(
        section,
        ordered_draw_obj_model_list: list[DrawCallModel],
        slot_line_provider,
        obj_name_draw_offset_dict: dict[str, int] | None = None,
    ):
        """按条件输出 drawindexed，并在每次 drawindexed 前插入 Slot 行。"""
        M_ControlFlow.append_drawindexed_with_slot_lines(
            section=section,
            ordered_draw_obj_model_list=ordered_draw_obj_model_list,
            slot_line_provider=slot_line_provider,
            obj_name_draw_offset_dict=obj_name_draw_offset_dict,
        )
    
    @staticmethod
    def get_drawindexed_instanced_str_list(
        ordered_draw_obj_model_list: list[DrawCallModel],
        obj_name_draw_offset_dict: dict[str, int] | None = None,
    ) -> list[str]:
        # 使用DrawIndexedInstanced方式调用这个
        # 在输出之前，我们需要根据condition对obj_model进行分组
        condition_str_obj_model_list_dict:dict[str,list[DrawCallModel]] = {}
        for obj_model in ordered_draw_obj_model_list:
            condition_str = obj_model.get_condition_str()

            obj_model_list = condition_str_obj_model_list_dict.get(condition_str,[])
            
            obj_model_list.append(obj_model)
            condition_str_obj_model_list_dict[condition_str] = obj_model_list
        
        drawindexed_str_list:list[str] = []
        for condition_str, obj_model_list in condition_str_obj_model_list_dict.items():
            if condition_str != "":
                drawindexed_str_list.append("if " + condition_str)
                for obj_model in obj_model_list:
                    display_name = str(getattr(obj_model, 'obj_name', '') or getattr(obj_model, 'display_name', '') or '')
                    drawindexed_str_list.append("  ; [mesh:" + display_name + "] [vertex_count:" + str(obj_model.vertex_count) + "]" )
                    draw_line = obj_model.get_drawindexed_instanced_str(obj_name_draw_offset_dict)
                    from .m_custom_shader_helper import M_CustomShaderHelper
                    drawindexed_str_list.extend(
                        "  " + line
                        for line in M_CustomShaderHelper.get_draw_lines(obj_model, draw_line)
                    )
                drawindexed_str_list.append("endif")
            else:
                for obj_model in obj_model_list:
                    display_name = str(getattr(obj_model, 'obj_name', '') or getattr(obj_model, 'display_name', '') or '')
                    drawindexed_str_list.append("; [mesh:" + display_name + "] [vertex_count:" + str(obj_model.vertex_count) + "]" )
                    draw_line = obj_model.get_drawindexed_instanced_str(obj_name_draw_offset_dict)
                    from .m_custom_shader_helper import M_CustomShaderHelper
                    drawindexed_str_list.extend(
                        M_CustomShaderHelper.get_draw_lines(obj_model, draw_line)
                    )
            drawindexed_str_list.append("")

        return drawindexed_str_list

    @classmethod
    def generate_hash_style_texture_ini(cls, ini_builder: M_IniBuilder, drawib_drawibmodel_dict: dict[str, DrawIBModel]):
        """
        Hash 风格贴图：生成贴图配置段（Resource_Texture + TextureOverride），并复制贴图文件。
        整体流程：遍历 DrawIB → 遍历 SubMesh → 逐张贴图处理。
        """

        # ═══════════════════════════════════════════════════
        # 步骤1: 检查全局开关，禁止时跳过全部处理
        # ═══════════════════════════════════════════════════
        if GlobalProperties.forbid_auto_texture_ini():
            print("[TRACE] generate_hash_style_texture_ini: forbid_auto_texture_ini=True, 跳过!")
            return

        # ═══════════════════════════════════════════════════
        # 步骤2: 初始化去重列表，遍历每个 DrawIB 处理 Hash 贴图
        # ═══════════════════════════════════════════════════
        repeat_hash_list: list[str] = []

        for draw_ib, draw_ib_model in drawib_drawibmodel_dict.items():
            submesh_list = getattr(draw_ib_model, "submesh_model_list", [])
            print("M_IniHelper: DrawIB " + draw_ib + " Hash 标记数: "
                  + str(cls._count_marked_textures(draw_ib_model, mark_type="Hash"))
                  + "，SubMesh 数: " + str(len(submesh_list)))

            for submesh_model in submesh_list:
                texture_markup_info_list = draw_ib_model.get_submesh_texture_markup_info_list(submesh_model)
                if not texture_markup_info_list:
                    continue

                part_name = draw_ib_model.get_submesh_part_name(submesh_model)
                submesh_folder_name = getattr(submesh_model, "submesh_name", "")
                if not submesh_folder_name:
                    print("M_IniHelper: 跳过 Hash 贴图处理，未找到 submesh_name，Part: " + str(part_name))
                    continue

                # 读取该 SubMesh 的 Hash 去重信息字典
                hash_deduped_texture_info_dict = SSMTWorkSpace.get_hash_deduped_texture_info_dict(
                    submesh_folder_name=submesh_folder_name,
                )

                for texture_markup_info in texture_markup_info_list:
                    # ── 类型过滤 —— 仅处理 Hash 类型标记 ──
                    if texture_markup_info.mark_type != "Hash":
                        continue

                    # ── 去重检查 —— 同一 Hash 只处理一次 ──
                    if texture_markup_info.mark_hash in repeat_hash_list:
                        continue
                    repeat_hash_list.append(texture_markup_info.mark_hash)

                    # ── 查找源贴图文件路径 ──
                    original_texture_file_path = cls._get_slot_texture_source_path(
                        draw_ib_model=draw_ib_model,
                        part_name=part_name,
                        texture_markup_info=texture_markup_info,
                    )
                    if not original_texture_file_path or not os.path.exists(original_texture_file_path):
                        continue

                    # ── 构造输出文件名 ──
                    #  新格式: "{mark_hash}_{mark_name}_{format}.dds"
                    hash_style_texture_filename = ""

                    #  查找 Hash 去重信息，优先使用当前 SubMesh 的，失败时查询所有 SubMesh
                    deduped_texture_info = hash_deduped_texture_info_dict.get(
                        texture_markup_info.mark_hash, None,
                    )
                    if deduped_texture_info is None:
                        for sm in getattr(draw_ib_model, "submesh_model_list", []):
                            sm_folder = getattr(sm, "submesh_name", "")
                            if not sm_folder:
                                continue
                            sm_deduped_dict = SSMTWorkSpace.get_hash_deduped_texture_info_dict(
                                submesh_folder_name=sm_folder,
                            )
                            deduped_texture_info = sm_deduped_dict.get(
                                texture_markup_info.mark_hash, None,
                            )
                            if deduped_texture_info is not None:
                                break

                    hash_style_texture_filename = (
                        texture_markup_info.mark_hash + "_"
                        + texture_markup_info.mark_name
                        + ".dds"
                    )
                    hash_style_resource_name = default_texture_resource_name(
                        texture_markup_info.mark_hash,
                        texture_markup_info.mark_name,
                    )

                    # ── 组装目标路径 ──
                    target_texture_file_path = (
                        GlobalConfig.path_generatemod_texture_folder(draw_ib=draw_ib)
                        + hash_style_texture_filename
                    )

                    # ── 生成 INI 配置段（Resource_Texture + TextureOverride）──
                    resource_texture_section = M_IniSection(
                        M_SectionType.ResourceAndTextureOverride_Texture,
                    )
                    resource_texture_section.append(
                        "[" + hash_style_resource_name + "]",
                    )
                    resource_texture_section.append(
                        "filename = Textures/" + hash_style_texture_filename,
                    )
                    resource_texture_section.new_line()
                    resource_texture_section.append(
                        "[TextureOverride_" + texture_markup_info.mark_hash + "]",
                    )
                    resource_texture_section.append(
                        "; " + texture_markup_info.mark_filename,
                    )
                    resource_texture_section.append(
                        "hash = " + texture_markup_info.mark_hash,
                    )
                    resource_texture_section.append("match_priority = 0")
                    resource_texture_section.append(
                        "this = " + hash_style_resource_name,
                    )
                    resource_texture_section.new_line()
                    ini_builder.append_section(resource_texture_section)

                    # ── 复制贴图文件（不覆盖已有，保留手动替换）──
                    if not os.path.exists(target_texture_file_path):
                        shutil.copy2(original_texture_file_path, target_texture_file_path)

    @classmethod
    def generate_shared_slot_style_texture_ini(cls, ini_builder: M_IniBuilder, drawib_drawibmodel_dict: dict[str, DrawIBModel]):
        """
        生成 Shared Slot 风格的贴图 INI 配置。
        逻辑混合 Hash 和 Slot 风格：
          - 去重和文件命名 = Hash 风格（按 mark_hash 去重，结构化文件名）
          - INI 输出 = Slot 风格（写 [Resource-XXX] 段，不写 TextureOverride 段）
        文件拷贝按 Hash 风格去重（同一 hash 只拷贝一次）。
        """
        if GlobalProperties.forbid_auto_texture_ini():
            print("[TRACE] generate_shared_slot_style_texture_ini: forbid_auto_texture_ini=True, 跳过!")
            return

        repeat_hash_list: list[str] = []
        appended_resource_names: set[str] = set()
        # 缓存: mark_hash → hash_style_filename，跨所有 DrawIB 共享，确保同一 hash 只拷贝一次
        hash_filename_cache: dict[str, str] = {}

        for draw_ib, draw_ib_model in drawib_drawibmodel_dict.items():
            submesh_list = getattr(draw_ib_model, "submesh_model_list", [])
            print("M_IniHelper: DrawIB " + draw_ib + " SharedSlot 标记数: "
                  + str(cls._count_marked_textures(draw_ib_model, mark_type="SharedSlot"))
                  + "，SubMesh 数: " + str(len(submesh_list)))

            has_shared_slot = False
            shared_slot_resource_section = M_IniSection(M_SectionType.ResourceTexture)

            for submesh_model in submesh_list:
                texture_markup_info_list = draw_ib_model.get_submesh_texture_markup_info_list(submesh_model)
                if not texture_markup_info_list:
                    continue

                part_name = draw_ib_model.get_submesh_part_name(submesh_model)
                submesh_folder_name = getattr(submesh_model, "submesh_name", "")
                if not submesh_folder_name:
                    print("M_IniHelper: 跳过 SharedSlot 贴图处理，未找到 submesh_name，Part: " + str(part_name))
                    continue

                hash_deduped_texture_info_dict = SSMTWorkSpace.get_hash_deduped_texture_info_dict(
                    submesh_folder_name=submesh_folder_name,
                )

                for texture_markup_info in texture_markup_info_list:
                    # ── 类型过滤 —— 仅处理 SharedSlot 类型标记 ──
                    if texture_markup_info.mark_type != "SharedSlot":
                        continue

                    # ── 文件拷贝 + 文件名构造（按 hash 去重）──
                    hash_style_texture_filename: str | None = hash_filename_cache.get(texture_markup_info.mark_hash)
                    if hash_style_texture_filename is None:
                        # 首次遇到该 hash：查找源文件、构造文件名、拷贝
                        original_texture_file_path = cls._get_slot_texture_source_path(
                            draw_ib_model=draw_ib_model,
                            part_name=part_name,
                            texture_markup_info=texture_markup_info,
                        )
                        if not original_texture_file_path or not os.path.exists(original_texture_file_path):
                            continue

                        hash_style_texture_filename = ""

                        deduped_texture_info = hash_deduped_texture_info_dict.get(
                            texture_markup_info.mark_hash, None,
                        )
                        if deduped_texture_info is None:
                            for sm in getattr(draw_ib_model, "submesh_model_list", []):
                                sm_folder = getattr(sm, "submesh_name", "")
                                if not sm_folder:
                                    continue
                                sm_deduped_dict = SSMTWorkSpace.get_hash_deduped_texture_info_dict(
                                    submesh_folder_name=sm_folder,
                                )
                                deduped_texture_info = sm_deduped_dict.get(
                                    texture_markup_info.mark_hash, None,
                                )
                                if deduped_texture_info is not None:
                                    break

                        hash_style_texture_filename = (
                            texture_markup_info.mark_hash + "_"
                            + texture_markup_info.mark_name
                            + ".dds"
                        )

                        # ── 拷贝文件（去重）──
                        target_texture_file_path = (
                            GlobalConfig.path_generatemod_texture_folder(draw_ib=draw_ib)
                            + hash_style_texture_filename
                        )
                        if not os.path.exists(target_texture_file_path):
                            shutil.copy2(original_texture_file_path, target_texture_file_path)

                        hash_filename_cache[texture_markup_info.mark_hash] = hash_style_texture_filename
                        repeat_hash_list.append(texture_markup_info.mark_hash)
                    else:
                        # 已处理过的 hash —— 跳过文件拷贝，但仍需写入 Resource 段
                        pass

                    # ── 生成 Slot 风格的 Resource 段（按 resource name 去重）──
                    has_shared_slot = True
                    resource_name = texture_markup_info.get_resource_name()
                    if resource_name not in appended_resource_names:
                        appended_resource_names.add(resource_name)
                        shared_slot_resource_section.append("[" + resource_name + "]")
                        shared_slot_resource_section.append("filename = Textures/" + hash_style_texture_filename)
                        shared_slot_resource_section.new_line()

            if has_shared_slot:
                ini_builder.append_section(shared_slot_resource_section)

    @staticmethod
    def _get_slot_style_texture_filename(draw_ib_model: DrawIBModel, submesh_index: int, texture_markup_info) -> str:
        """
        生成 Slot 风格贴图文件名。
        格式: {别名或DrawIB}-{Submesh序号}-{标记名称}.dds
        """
        prefix = draw_ib_model.draw_ib_alias or draw_ib_model.draw_ib
        return f"{prefix}-{submesh_index}-{texture_markup_info.mark_name}.dds"

    @classmethod
    def move_slot_style_textures(cls,draw_ib_model:DrawIBModel):
        '''
        Move all textures from extracted game type folder to generate mod Texture folder.
        Only works in default slot style texture.
        '''
        print("=" * 60)
        print("[TRACE] move_slot_style_textures() 入口 - DrawIB: " + draw_ib_model.draw_ib)
        print("=" * 60)

        if GlobalProperties.forbid_auto_texture_ini():
            print("[TRACE] move_slot_style_textures: forbid_auto_texture_ini=True, 跳过所有贴图复制!")
            return

        marked_slot_count = cls._count_marked_textures(draw_ib_model, mark_type="Slot")
        print("M_IniHelper: 开始复制 Slot 贴图，DrawIB: " + draw_ib_model.draw_ib + "，Slot 标记数量: " + str(marked_slot_count))

        submesh_model_list = getattr(draw_ib_model, "submesh_model_list", [])
        print("[TRACE] move_slot_style_textures: submesh_model_list 数量 = " + str(len(submesh_model_list)))

        slot_copied = 0
        slot_skipped_exists = 0
        slot_skipped_no_source = 0
        slot_skipped_non_slot = 0

        for idx, submesh_model in enumerate(submesh_model_list):
            texture_markup_info_list = draw_ib_model.get_submesh_texture_markup_info_list(submesh_model)
            submesh_name = getattr(submesh_model, "submesh_name", "<无>")
            print("[TRACE] submesh[" + str(idx) + "] submesh_name=" + submesh_name + ", 贴图标记数=" + str(len(texture_markup_info_list)))

            if not texture_markup_info_list:
                print("[TRACE] submesh[" + str(idx) + "] 无贴图标记，跳过")
                continue

            part_name = draw_ib_model.get_submesh_part_name(submesh_model) or submesh_model.submesh_name
            for ti, texture_markup_info in enumerate(texture_markup_info_list):
                print("[TRACE]   贴图[" + str(ti) + "]: mark_type=" + texture_markup_info.mark_type
                      + ", mark_filename=" + texture_markup_info.mark_filename
                      + ", mark_hash=" + str(getattr(texture_markup_info, "mark_hash", "<无>")))

                if texture_markup_info.mark_type != "Slot":
                    print("[TRACE]   贴图[" + str(ti) + "]: mark_type 不是 Slot (实际=" + texture_markup_info.mark_type + ")，跳过")
                    slot_skipped_non_slot += 1
                    continue

                texture_output_folder = GlobalConfig.path_generatemod_texture_folder(draw_ib=draw_ib_model.draw_ib)
                print("M_IniHelper: Slot 贴图输出目录: " + texture_output_folder)
                print("[TRACE] Slot 贴图输出目录是否存在: " + str(os.path.exists(texture_output_folder)))

                slot_texture_filename = cls._get_slot_style_texture_filename(draw_ib_model, idx, texture_markup_info)
                print("[TRACE] Slot 贴图新文件名: " + slot_texture_filename)

                target_path = GlobalConfig.path_generatemod_texture_folder(draw_ib=draw_ib_model.draw_ib) + slot_texture_filename
                source_path = cls._get_slot_texture_source_path(draw_ib_model, part_name, texture_markup_info)
                print("[TRACE] Slot 贴图 source_path 解析结果: '" + source_path + "'")
                print("[TRACE] Slot 贴图 target_path: '" + target_path + "'")
                print("[TRACE] source_path 存在: " + str(os.path.exists(source_path) if source_path else "N/A (空字符串)"))
                print("[TRACE] target_path 存在: " + str(os.path.exists(target_path)))

                if os.path.exists(target_path):
                    print("[TRACE] Slot 贴图目标已存在，跳过复制: " + target_path)
                    slot_skipped_exists += 1
                else:
                    if source_path == "":
                        print("[TRACE] Slot 贴图 source_path 为空字符串，跳过! mark_filename=" + texture_markup_info.mark_filename)
                        slot_skipped_no_source += 1
                        continue
                    if not os.path.exists(source_path):
                        print("[TRACE] Slot 贴图 source_path 文件不存在，跳过! source_path=" + source_path)
                        slot_skipped_no_source += 1
                        continue
                    print("[TRACE] >>> 执行 shutil.copy2: " + source_path + " -> " + target_path)
                    try:
                        shutil.copy2(source_path,target_path)
                        print("[TRACE] <<< shutil.copy2 成功: " + target_path)
                        slot_copied += 1
                    except Exception as e:
                        print("[TRACE] <<< shutil.copy2 失败! 异常: " + str(e))

        print("[TRACE] move_slot_style_textures() 汇总 - DrawIB: " + draw_ib_model.draw_ib)
        print("[TRACE]   Slot 复制成功: " + str(slot_copied))
        print("[TRACE]   Slot 跳过(目标已存在): " + str(slot_skipped_exists))
        print("[TRACE]   Slot 跳过(源文件缺失): " + str(slot_skipped_no_source))
        print("[TRACE]   Slot 跳过(非Slot类型): " + str(slot_skipped_non_slot))
        print("=" * 60)
    
    @staticmethod
    def add_shapekey_ini_sections(ini_builder:M_IniBuilder,drawib_drawibmodel_dict:dict[str,DrawIBModel]):
        shapekeyname_mkey_dict = BlueprintExportHelper.get_current_shapekeyname_mkey_dict()
        if len(shapekeyname_mkey_dict.keys()) == 0:
            return

        import shutil
        addon_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        src = os.path.join(addon_root, "resources", "Shapes.hlsl")
        dst_dir = os.path.join(GlobalConfig.path_generate_mod_folder(), "res")
        os.makedirs(dst_dir, exist_ok=True)
        shutil.copy2(src, os.path.join(dst_dir, "Shapes.hlsl"))

        # [Constants]
        constants_section = M_IniSection(M_SectionType.Constants)
        constants_section.append("[Constants]")
        constants_section.append("global persist $shapekey_first_run = 1")

        for shapekey_name, m_key in shapekeyname_mkey_dict.items():
            constants_section.append("; ShapeKey: " + shapekey_name)
            constants_section.append("global persist " + m_key.key_name + " = " + str(m_key.initialize_value))
            constants_section.new_line()

        ini_builder.append_section(constants_section)

        # [Present]
        present_section = M_IniSection(M_SectionType.Present)
        present_section.append("[Present]")
        present_section.append("if $shapekey_first_run")

        ib_number = 1
        for drawib, drawib_model in drawib_drawibmodel_dict.items():
            shapekey_buffer_dict = getattr(drawib_model, "shapekey_name_bytelist_dict", {})

            # 如果当前DrawIB没有生成形态键数据，则跳过不处理
            if not shapekey_buffer_dict:
                continue

            original_position_buffer_resource_name ="Resource" + drawib + "Position"     
            duplicated_position_buffer_resource_name = "Resource" + drawib + "Position.1"

            present_section.append("  " + original_position_buffer_resource_name + " = copy " + duplicated_position_buffer_resource_name)
            present_section.append("  run = CustomShaderComputeShapes" + str(ib_number))

            ib_number += 1
        
        present_section.append("  $shapekey_first_run = 0")
        present_section.append("endif")

        ib_number = 1
        for drawib, drawib_model in drawib_drawibmodel_dict.items():
            shapekey_buffer_dict = getattr(drawib_model, "shapekey_name_bytelist_dict", {})

            # 如果当前DrawIB没有生成形态键数据，则跳过不处理
            if not shapekey_buffer_dict:
                continue

            present_section.append("  run = CustomShaderComputeShapes" + str(ib_number))
            ib_number += 1

        ini_builder.append_section(present_section)
        
        # [CustomShaderComputeShapes]
        customshader_section = M_IniSection(M_SectionType.CommandList)

        ib_number = 1
        for drawib, drawib_model in drawib_drawibmodel_dict.items():
            shapekey_buffer_dict = getattr(drawib_model, "shapekey_name_bytelist_dict", {})
            d3d11_game_type = getattr(drawib_model, "d3d11_game_type", None)
            draw_number = getattr(drawib_model, "draw_number", getattr(drawib_model, "vertex_count", 0))

            # 如果当前DrawIB没有生成形态键数据，则跳过不处理
            if not shapekey_buffer_dict or d3d11_game_type is None:
                continue

            customshader_section.append("[CustomShaderComputeShapes" + str(ib_number) + "]")
            customshader_section.append("cs = ./res/Shapes.hlsl")
            customshader_section.append("cs-u5 = copy " + "Resource" + drawib + "Position.1")
            customshader_section.new_line()

            # 对于每个形态键buffer都进行计算
            for shapekey_name, m_key in shapekeyname_mkey_dict.items():
                # 这里很显然有问题，如果一个DrawIB有这个形态键，另一个DrawIB没有这个形态键呢？
                # 那这里就会导致游戏内没有这个形态键的模型出现异常
                # 所以如果这个DrawIB内没有这个形态键的话，就不需要生成它的计算代码
                if shapekey_buffer_dict.get(shapekey_name, None) is None:
                    continue

                customshader_section.append("x88 = " + m_key.key_name)
                customshader_section.append("cs-t50 = copy " + "Resource" + drawib + "Position.1")
                customshader_section.append("cs-t51 = copy " + "Resource" + drawib + "Position." + shapekey_name)
                customshader_section.append("Resource" + drawib + "Position = ref cs-u5")
                customshader_section.append("Dispatch = " + str(draw_number) + " ,1 ,1")
                customshader_section.new_line()

            ib_number += 1

            customshader_section.append("cs-u5 = null")
            customshader_section.append("cs-t50 = null")
            customshader_section.append("cs-t51 = null")

        ini_builder.append_section(customshader_section)

        # [Resources]
        resource_section = M_IniSection(M_SectionType.ResourceBuffer)


        ib_number = 1
        for drawib, drawib_model in drawib_drawibmodel_dict.items():
            shapekey_buffer_dict = getattr(drawib_model, "shapekey_name_bytelist_dict", {})
            d3d11_game_type = getattr(drawib_model, "d3d11_game_type", None)

            # 如果当前DrawIB没有生成形态键数据，则跳过不处理
            if not shapekey_buffer_dict or d3d11_game_type is None:
                continue

            # 原本的Buffer
            resource_section.append("[Resource" + drawib + "Position.1]")
            resource_section.append("type = buffer")
            resource_section.append("stride = " + str(d3d11_game_type.CategoryStrideDict["Position"]))
            resource_section.append("filename = Meshes\\" + drawib + "-" + "Position.buf")
            resource_section.new_line()

            # 各个形态键的Buffer
            for shapekey_name, m_key in shapekeyname_mkey_dict.items():
                # 这里很显然有问题，如果一个DrawIB有这个形态键，另一个DrawIB没有这个形态键呢？
                # 那这里就会导致游戏内没有这个形态键的模型出现异常
                # 所以如果这个DrawIB内没有这个形态键的话，就不需要生成它的计算代码
                if shapekey_buffer_dict.get(shapekey_name, None) is None:
                    continue
                
                resource_section.append("[Resource" + drawib + "Position." + shapekey_name + "]")
                resource_section.append("type = buffer")
                resource_section.append("stride = " + str(d3d11_game_type.CategoryStrideDict["Position"]))
                resource_section.append("filename = Meshes\\" + drawib + "-" + "Position." + shapekey_name + ".buf")
                resource_section.new_line()

            ib_number += 1
        
        ini_builder.append_section(resource_section)

        # [Key]
        # 用于按下测试的Key，也可以作为在没有面板时的按键切换形态键快捷键
        key_section = M_IniSection(M_SectionType.Key)
        for shapekey_name, m_key in shapekeyname_mkey_dict.items():
            if m_key.initialize_vk_str != "":
                key_section.append("[Key_ShapeKey_" +shapekey_name + "]")
                
                # 添加备注信息
                comment = getattr(m_key, 'comment', '')
                if comment:
                    key_section.append("; " + comment)
                
                key_section.append("key = " + m_key.initialize_vk_str)
                key_section.append("type = cycle")
                key_section.append(m_key.key_name + " = 0,0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8,0.9,1")
                key_section.new_line()

        ini_builder.append_section(key_section)



    @staticmethod
    def add_branch_key_sections(ini_builder:M_IniBuilder,key_name_mkey_dict:dict[str,M_Key]):

        if len(key_name_mkey_dict.keys()) != 0:
            constants_section = M_IniSection(M_SectionType.Constants)
            constants_section.SectionName = "Constants"

            for i in range(GlobalConfig.generated_mod_number):
                constants_section.append("global $active" + str(i))

            for mkey in key_name_mkey_dict.values():
                key_str = "global persist " + mkey.key_name + " = " + str(mkey.initialize_value)
                constants_section.append(key_str) 

            ini_builder.append_section(constants_section)


        if len(key_name_mkey_dict.keys()) != 0:
            present_section = M_IniSection(M_SectionType.Present)
            present_section.SectionName = "Present"

            for i in range(GlobalConfig.generated_mod_number):
                present_section.append("post $active" + str(i) + " = 0")
            ini_builder.append_section(present_section)
        
        key_number = 0
        if len(key_name_mkey_dict.keys()) != 0:

            for mkey in key_name_mkey_dict.values():
                key_section = M_IniSection(M_SectionType.Key)
                key_section.append("[KeySwap_" + str(key_number) + "]")
                
                # 添加备注信息
                comment = getattr(mkey, 'comment', '')
                if comment:
                    key_section.append("; " + comment)
                
                # key_section.append("condition = $active" + str(key_number) + " == 1")

                # XXX 这里由于有BUG，我们固定用$active0来检测激活，不搞那么复杂了。
                key_section.append("condition = $active0 == 1")

                if mkey.initialize_vk_str != "":
                    key_section.append("key = " + mkey.initialize_vk_str)
                else:
                    key_section.append("key = " + mkey.key_value)
                key_section.append("type = cycle")

                key_cycle_str = ",".join(str(i) for i in range(len(mkey.value_list)))
                key_section.append(mkey.key_name + " = " + key_cycle_str)
                key_section.new_line()
                ini_builder.append_section(key_section)

                key_number = key_number + 1
