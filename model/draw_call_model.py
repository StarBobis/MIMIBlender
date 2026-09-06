from ..utils.ssmt_error_utils import SSMTErrorUtils
from ..common.m_key import M_Key

from dataclasses import dataclass, field
from typing import Optional

@dataclass
class DrawCallModel:
    obj_name:str
    submesh_name:str = ""

    # After obj_name is passed in, resolve these attributes for later use
    match_draw_ib:str = field(init=False,repr=False,default="") # DrawIB used for matching
    match_index_count:str = field(init=False,repr=False,default="") # IndexCount used for matching
    match_first_index:str = field(init=False,repr=False,default="") # FirstIndex used for matching
    match_submesh_name:str = field(init=False,repr=False,default="") # Submesh identifier used for workspace directory matching
    comment_alias_name:str = field(init=False,repr=False,default="") # Custom name displayed in the comment

    # Effective conditions, resolved when BlueprintModel is parsed
    work_key_list:list[M_Key] = field(init=False,repr=False,default_factory=list)

    # Custom command list connected via the CustomShader input of Object Info
    custom_shader_node_list:list = field(init=False,repr=False,default_factory=list)

    # These attributes are computed at the SubMeshModel level and used for ini output
    index_count:int = field(init=False,repr=False,default=0)
    vertex_count:int = field(init=False,repr=False,default=0)
    index_offset:int = field(init=False,repr=False,default=0)


    def __post_init__(self) -> None:
        objname_parse_error_tips = (
            "Obj naming rule (new format): DrawIB-ComponentIndex.AliasName, "
            "e.g. [94517393-0.Hair] Content before the first . must follow the rule; content after it can be customized\n"
            "Obj naming rule (old format): DrawIB-IndexCount-FirstIndex.AliasName, "
            "e.g. [67f829fc-2653-0.Hair]"
        )

        submesh_parse_result = self._try_parse_name(self.submesh_name)
        if submesh_parse_result is not None:
            self.match_draw_ib, self.match_index_count, self.match_first_index, self.match_submesh_name, self.comment_alias_name = submesh_parse_result
            return

        # submesh_name parsing failed, fall back to parsing obj_name
        obj_name_parse_result = self._try_parse_name(self.obj_name)
        if obj_name_parse_result is not None:
            self.match_draw_ib, self.match_index_count, self.match_first_index, self.match_submesh_name, self.comment_alias_name = obj_name_parse_result
            return

        obj_name_total_split = self.obj_name.split(".") if self.obj_name else []
        self.comment_alias_name = ".".join(obj_name_total_split[1:]) if len(obj_name_total_split) > 1 else ""

        if "." not in self.obj_name:
            SSMTErrorUtils.raise_fatal("Object name parsing error: " + self.obj_name + "  does not contain a '.' separator\n" + objname_parse_error_tips)

        obj_name_total_split = self.obj_name.split(".")
        obj_name_split = obj_name_total_split[0].split("-")

        if len(obj_name_total_split) < 2:
            SSMTErrorUtils.raise_fatal("Object name parsing error: " + self.obj_name + "  does not contain a '.' separator\n" + objname_parse_error_tips)
        if len(obj_name_split) < 2:
            SSMTErrorUtils.raise_fatal(
                "Object name parsing error: " + self.obj_name + "  '-' separator count is insufficient, at least 1 is required\n" + objname_parse_error_tips
            )

        self.match_draw_ib = obj_name_split[0]

        if len(obj_name_split) == 2:
            # New format: DrawIB-ComponentIndex (2 segments)
            # match_index_count stays empty; match_first_index temporarily stores the Component index
            # match_index_count / match_first_index are corrected later by WorkSpaceModel
            self.match_index_count = ""
            self.match_first_index = obj_name_split[1]
        else:
            # Old format: DrawIB-IndexCount-FirstIndex (>= 3 segments)
            self.match_index_count = obj_name_split[1]
            self.match_first_index = obj_name_split[2]

        self.match_submesh_name = self.match_draw_ib + "-" + self.match_first_index

    def _try_parse_name(self, name: str):
        normalized_name = str(name or "").strip()
        if not normalized_name:
            return None

        # Detect and strip the LOD prefix (e.g. "LOD0.")
        lod_prefix = ""
        temp = normalized_name
        if temp.upper().startswith("LOD") and "." in temp:
            dot_idx = temp.index(".")
            potential_lod = temp[:dot_idx]
            if potential_lod[3:].isdigit():
                lod_prefix = potential_lod + "."
                temp = temp[dot_idx + 1:]  # part after removing the LOD0. prefix

        name_prefix, _, alias_suffix = temp.partition(".")
        name_split = name_prefix.split("-")

        if len(name_split) < 2:
            return None

        lod_submesh_name = lod_prefix + name_prefix if lod_prefix else name_prefix

        if len(name_split) == 2:
            # New format: DrawIB-ComponentIndex (2 segments)
            # match_index_count stays empty; match_first_index temporarily stores the Component index
            return name_split[0], "", name_split[1], lod_submesh_name, alias_suffix
        elif len(name_split) >= 3:
            # Old format: DrawIB-IndexCount-FirstIndex (>= 3 segments)
            return name_split[0], name_split[1], name_split[2], lod_submesh_name, alias_suffix

        return None
    
    def get_submesh_name(self) -> str:
        # Return the name of the submesh that this DrawCall belongs to
        return self.match_submesh_name

    def get_condition_str(self) -> str:
        if len(self.work_key_list) == 0:
            return ""

        condition_str_list = []
        for work_key in self.work_key_list:
            condition_str_list.append(work_key.key_name + " == " + str(work_key.tmp_value))

        return " && ".join(condition_str_list)

    def get_drawindexed_str(self, obj_name_draw_offset_dict: Optional[dict[str, int]] = None) -> str:
        draw_offset = self.index_offset if obj_name_draw_offset_dict is None else obj_name_draw_offset_dict.get(self.obj_name, self.index_offset)
        return f"drawindexed = {self.index_count},{draw_offset},0"

    def get_drawindexed_instanced_str(self, obj_name_draw_offset_dict: Optional[dict[str, int]] = None) -> str:
        draw_offset = self.index_offset if obj_name_draw_offset_dict is None else obj_name_draw_offset_dict.get(self.obj_name, self.index_offset)
        return f"drawindexedinstanced = {self.index_count},INSTANCE_COUNT,{draw_offset},0,FIRST_INSTANCE"
        
 
