from ..utils.ssmt_error_utils import SSMTErrorUtils
from ..common.m_key import M_Key

from dataclasses import dataclass, field
from typing import Optional

@dataclass
class DrawCallModel:
    obj_name:str
    submesh_name:str = ""

    # 传入obj_name后，解析出这些属性，方便后续使用
    match_draw_ib:str = field(init=False,repr=False,default="") # 用于匹配的DrawIB
    match_index_count:str = field(init=False,repr=False,default="") # 用于匹配的IndexCount
    match_first_index:str = field(init=False,repr=False,default="") # 用于匹配的FirstIndex
    match_submesh_name:str = field(init=False,repr=False,default="") # 用于工作空间目录匹配的submesh标识
    comment_alias_name:str = field(init=False,repr=False,default="") # 用于显示在注释中的自定义名称

    # 生效条件，在BlueprintModel解析的时候得到
    work_key_list:list[M_Key] = field(init=False,repr=False,default_factory=list)

    # 通过蓝图 Texture 节点的 Slot 出口连接上来的贴图
    slot_texture_node_list:list = field(init=False,repr=False,default_factory=list)

    # 通过 Object Info 的 CustomShader 输入连接上来的自定义命令列表
    custom_shader_node_list:list = field(init=False,repr=False,default_factory=list)

    # 在SubMeshModel层级计算得到这些属性，用于ini写出
    index_count:int = field(init=False,repr=False,default=0)
    vertex_count:int = field(init=False,repr=False,default=0)
    index_offset:int = field(init=False,repr=False,default=0)


    def __post_init__(self) -> None:
        objname_parse_error_tips = (
            "Obj名称规则（新格式）: DrawIB-ComponentIndex.AliasName, "
            "例如[94517393-0.头发]第一个.前面的内容要符合规则,后面出现的内容是可以自定义的\n"
            "Obj名称规则（旧格式）: DrawIB-IndexCount-FirstIndex.AliasName, "
            "例如[67f829fc-2653-0.头发]"
        )

        submesh_parse_result = self._try_parse_name(self.submesh_name)
        if submesh_parse_result is not None:
            self.match_draw_ib, self.match_index_count, self.match_first_index, self.match_submesh_name, self.comment_alias_name = submesh_parse_result
            return

        # submesh_name 解析失败，退而解析 obj_name
        obj_name_parse_result = self._try_parse_name(self.obj_name)
        if obj_name_parse_result is not None:
            self.match_draw_ib, self.match_index_count, self.match_first_index, self.match_submesh_name, self.comment_alias_name = obj_name_parse_result
            return

        obj_name_total_split = self.obj_name.split(".") if self.obj_name else []
        self.comment_alias_name = ".".join(obj_name_total_split[1:]) if len(obj_name_total_split) > 1 else ""

        if "." not in self.obj_name:
            SSMTErrorUtils.raise_fatal("Obj名称解析错误: " + self.obj_name + "  不包含'.'分隔符\n" + objname_parse_error_tips)

        obj_name_total_split = self.obj_name.split(".")
        obj_name_split = obj_name_total_split[0].split("-")

        if len(obj_name_total_split) < 2:
            SSMTErrorUtils.raise_fatal("Obj名称解析错误: " + self.obj_name + "  不包含'.'分隔符\n" + objname_parse_error_tips)
        if len(obj_name_split) < 2:
            SSMTErrorUtils.raise_fatal(
                "Obj名称解析错误: " + self.obj_name + "  '-'分隔符数量不足，至少需要1个\n" + objname_parse_error_tips
            )

        self.match_draw_ib = obj_name_split[0]

        if len(obj_name_split) == 2:
            # 新格式: DrawIB-ComponentIndex（2 段）
            # match_index_count 为空，match_first_index 暂存 Component 序号
            # 后续由 WorkSpaceModel 修正 match_index_count / match_first_index
            self.match_index_count = ""
            self.match_first_index = obj_name_split[1]
        else:
            # 旧格式: DrawIB-IndexCount-FirstIndex（>=3 段）
            self.match_index_count = obj_name_split[1]
            self.match_first_index = obj_name_split[2]

        self.match_submesh_name = self.match_draw_ib + "-" + self.match_first_index

    def _try_parse_name(self, name: str):
        normalized_name = str(name or "").strip()
        if not normalized_name:
            return None

        # 检测并剥离 LOD 前缀（如 "LOD0."）
        lod_prefix = ""
        temp = normalized_name
        if temp.upper().startswith("LOD") and "." in temp:
            dot_idx = temp.index(".")
            potential_lod = temp[:dot_idx]
            if potential_lod[3:].isdigit():
                lod_prefix = potential_lod + "."
                temp = temp[dot_idx + 1:]  # 去掉 LOD0. 前缀后的部分

        name_prefix, _, alias_suffix = temp.partition(".")
        name_split = name_prefix.split("-")

        if len(name_split) < 2:
            return None

        lod_submesh_name = lod_prefix + name_prefix if lod_prefix else name_prefix

        if len(name_split) == 2:
            # 新格式: DrawIB-ComponentIndex（2 段）
            # match_index_count 为空，match_first_index 暂存 Component 序号
            return name_split[0], "", name_split[1], lod_submesh_name, alias_suffix
        elif len(name_split) >= 3:
            # 旧格式: DrawIB-IndexCount-FirstIndex（>=3 段）
            return name_split[0], name_split[1], name_split[2], lod_submesh_name, alias_suffix

        return None
    
    def get_submesh_name(self) -> str:
        # 返回这个 DrawCall 所属 submesh 的名称
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
        
 
