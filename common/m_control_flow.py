"""Helpers for writing conditional INI control flow."""


class M_ControlFlow:
    @staticmethod
    def append_drawindexed_with_slot_lines(
        section,
        ordered_draw_obj_model_list,
        slot_line_provider,
        obj_name_draw_offset_dict=None,
    ):
        """Write texture bindings and drawindexed lines under conditions.

        ``section`` only needs to provide ``append``, so the control-flow
        semantics work with any INI section instead of relying on a specific
        section-name prefix.
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
                section.append(indent + draw_line)

            if condition_str:
                section.append("endif")
            section.append("")
