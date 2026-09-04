import os
from dataclasses import dataclass, field

from .submesh_json import SubmeshJson
from .ssmt_workspace import SSMTWorkSpace


@dataclass
class TextureMarkUpInfo:
    mark_name:str = field(default="",init=False)
    mark_type:str = field(default="",init=False)
    mark_hash:str = field(default="",init=False)
    mark_slot:str = field(default="",init=False)
    mark_filename:str = field(default="",init=False)

    def get_resource_name(self):
        return "Resource-" + self.mark_filename.split(".")[0]

    def get_hash_style_filename(self):
        return self.mark_hash + "_" + self.mark_name + ".dds"


class TextureMetadataResolver:
    @staticmethod
    def find_texture(texture_prefix, texture_suffix, directory):
        '''
        查找目标目录下，满足指定后缀和前缀的贴图文件
        '''
        normalized_prefix = str(texture_prefix).casefold()
        normalized_suffix = str(texture_suffix).casefold()
        for root, dirs, files in os.walk(directory):
            for file in files:
                normalized_file = file.casefold()
                if normalized_file.endswith(normalized_suffix) and normalized_file.startswith(normalized_prefix):
                    texture_path = os.path.join(root, file)
                    return texture_path
        return None

    @staticmethod
    def _get_texture_markup_info_identity(texture_info) -> tuple:
        return (
            getattr(texture_info, "mark_name", ""),
            getattr(texture_info, "mark_type", ""),
            getattr(texture_info, "mark_hash", ""),
            getattr(texture_info, "mark_slot", ""),
            getattr(texture_info, "mark_filename", ""),
        )

    @staticmethod
    def _dedupe_texture_markup_info_list(texture_info_list: list) -> list:
        deduped_texture_info_list = []
        seen_identities = set()

        for texture_info in texture_info_list:
            identity = TextureMetadataResolver._get_texture_markup_info_identity(texture_info)
            if identity in seen_identities:
                continue
            seen_identities.add(identity)
            deduped_texture_info_list.append(texture_info)

        return deduped_texture_info_list

    @staticmethod
    def normalize_texture_markup_info_list(texture_info_list: list) -> list:
        normalized_texture_info_list = []

        for texture_info in texture_info_list:
            if isinstance(texture_info, TextureMarkUpInfo):
                normalized_texture_info_list.append(texture_info)
                continue

            if not isinstance(texture_info, dict):
                continue

            markup_info = TextureMarkUpInfo()
            markup_info.mark_name = texture_info.get("MarkName", texture_info.get("mark_name", ""))
            markup_info.mark_type = texture_info.get("MarkType", texture_info.get("mark_type", ""))
            markup_info.mark_hash = texture_info.get("MarkHash", texture_info.get("mark_hash", ""))
            markup_info.mark_slot = texture_info.get("MarkSlot", texture_info.get("mark_slot", ""))
            markup_info.mark_filename = texture_info.get("MarkFileName", texture_info.get("mark_filename", ""))
            normalized_texture_info_list.append(markup_info)

        return normalized_texture_info_list

    @staticmethod
    def normalize_texture_markup_info_dict(raw_texture_info_dict: dict) -> dict:
        normalized_texture_info_dict = {}

        for part_name, texture_info_list in raw_texture_info_dict.items():
            normalized_texture_info_dict[part_name] = TextureMetadataResolver.normalize_texture_markup_info_list(texture_info_list)

        return normalized_texture_info_dict

    @staticmethod
    def get_submesh_texturemarkinfolist_dict(draw_ib_model) -> dict:
        texture_info_dict = getattr(draw_ib_model, "submesh_texturemarkinfolist_dict", None)
        if texture_info_dict is None:
            return {}

        return {
            submesh_name: TextureMetadataResolver.normalize_texture_markup_info_list(texture_info_list)
            for submesh_name, texture_info_list in texture_info_dict.items()
        }

    @staticmethod
    def get_part_name_for_submesh(draw_ib_model, submesh_model) -> str:
        return submesh_model.submesh_name

    @staticmethod
    def load_texture_markup_info_for_submesh(draw_ib_model, submesh_model) -> tuple[str, list]:
        submesh_name = submesh_model.submesh_name

        try:
            submesh_json = SubmeshJson(SSMTWorkSpace.check_and_get_submesh_json_path(submesh_name))
        except Exception as ex:
            print("TextureMetadataResolver: 跳过贴图标记读取，无法解析 SubmeshJson: " + submesh_name + "，错误: " + str(ex))
            return submesh_name, []

        print(
            "TextureMetadataResolver: 读取贴图标记，submesh_name: "
            + submesh_name
            + "，submesh_json: "
            + submesh_json.JsonFilePath
        )

        texture_markup_info_list = TextureMetadataResolver.normalize_texture_markup_info_list(
            submesh_json.TextureMarkUpInfoList
        )
        texture_markup_info_list = TextureMetadataResolver._dedupe_texture_markup_info_list(texture_markup_info_list)

        if not texture_markup_info_list:
            print("TextureMetadataResolver: 当前 submesh 没有贴图标记: " + submesh_name)
            return submesh_name, []

        if texture_markup_info_list:
            print(
                "TextureMetadataResolver: 当前 submesh 已匹配到贴图标记，submesh_name: "
                + submesh_name
                + "，数量: "
                + str(len(texture_markup_info_list))
            )

        return submesh_name, texture_markup_info_list

    @staticmethod
    def load_submesh_texture_markup_info_from_all_submeshes(draw_ib_model, workspace_import_json: dict | None = None) -> dict:
        submesh_texture_markup_info_dict = {}

        for submesh_model in draw_ib_model.submesh_model_list:
            _, texture_markup_info_list = TextureMetadataResolver.load_texture_markup_info_for_submesh(
                draw_ib_model=draw_ib_model,
                submesh_model=submesh_model,
            )
            if texture_markup_info_list:
                submesh_texture_markup_info_dict[submesh_model.submesh_name] = texture_markup_info_list

        return submesh_texture_markup_info_dict

    @staticmethod
    def load_texture_markup_info_from_all_submeshes(draw_ib_model, workspace_import_json: dict | None = None) -> dict:
        merged_texture_markup_info_dict = {}

        for submesh_model in draw_ib_model.submesh_model_list:
            part_name, texture_markup_info_list = TextureMetadataResolver.load_texture_markup_info_for_submesh(
                draw_ib_model=draw_ib_model,
                submesh_model=submesh_model,
            )

            if not part_name or not texture_markup_info_list:
                continue

            merged_texture_markup_info_dict[part_name] = TextureMetadataResolver._dedupe_texture_markup_info_list(
                merged_texture_markup_info_dict.get(part_name, []) + texture_markup_info_list
            )
            print(
                "TextureMetadataResolver: 已合并贴图标记到 Part "
                + part_name
                + "，数量: "
                + str(len(merged_texture_markup_info_dict[part_name]))
            )

        return merged_texture_markup_info_dict
