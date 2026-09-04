"""INI 控制流写出辅助器。"""


class M_ControlFlow:
    @staticmethod
    def append_drawindexed_with_slot_lines(
        section,
        ordered_draw_obj_model_list,
        slot_line_provider,
        obj_name_draw_offset_dict=None,
    ):
        """按条件写出贴图绑定和 drawindexed。

        ``section`` 只需提供 ``append``，因此控制流语义可用于任何 INI
        section，而非依赖某个特定的 section 名称前缀。
        """
        condition_str_obj_model_list_dict = {}
        for obj_model in ordered_draw_obj_model_list:
            condition_str = obj_model.get_condition_str()
            condition_str_obj_model_list_dict.setdefault(condition_str, []).append(obj_model)

        for condition_str, obj_model_list in condition_str_obj_model_list_dict.items():
            if condition_str:
                section.append("if " + condition_str)
                indent = "  "
            else:
                indent = ""

            for obj_model in obj_model_list:
                display_name = str(
                    getattr(obj_model, 'obj_name', '')
                    or getattr(obj_model, 'display_name', '')
                    or ''
                )
                section.append(
                    indent + "; [mesh:" + display_name + "] [vertex_count:"
                    + str(obj_model.vertex_count) + "]"
                )
                for line in slot_line_provider(obj_model):
                    section.append(indent + line)
                draw_line = obj_model.get_drawindexed_str(obj_name_draw_offset_dict)
                from .m_custom_shader_helper import M_CustomShaderHelper
                for line in M_CustomShaderHelper.get_draw_lines(obj_model, draw_line):
                    section.append(indent + line)

            if condition_str:
                section.append("endif")
            section.append("")
