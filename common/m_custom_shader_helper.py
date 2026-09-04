'''Export support for CustomShader nodes connected to Object Info nodes.'''


class M_CustomShaderHelper:
    _node_to_base_section = {}
    _binding_to_section = {}
    _base_section_to_node = {}
    _section_to_definition = {}

    @classmethod
    def begin_export(cls):
        cls._node_to_base_section = {}
        cls._binding_to_section = {}
        cls._base_section_to_node = {}
        cls._section_to_definition = {}

    @classmethod
    def _node_key(cls, node):
        try:
            return ('rna', node.as_pointer())
        except (AttributeError, ReferenceError):
            return ('python', id(node))

    @staticmethod
    def _node_body(node):
        get_body = getattr(node, 'get_body', None)
        if callable(get_body):
            return str(get_body() or '')
        return str(getattr(node, 'body', '') or '')

    @classmethod
    def _is_active_node(cls, node):
        """Only active, configured nodes may replace an object's draw call.

        A CustomShader node is attached through a side input rather than the
        object-flow links.  Treating an empty or muted side node as a command
        list would otherwise replace ``drawindexed`` with an empty section and
        make the mesh disappear.  This is especially easy to encounter while
        building switch branches incrementally.
        """
        return not getattr(node, 'mute', False) and bool(cls._node_body(node).strip())

    @classmethod
    def _base_section_name(cls, node):
        key = cls._node_key(node)
        section_name = cls._node_to_base_section.get(key)
        if section_name:
            return section_name

        mark_name = str(getattr(node, 'mark_name', '') or '').strip()
        if not mark_name:
            index = 0
            used = set(cls._node_to_base_section.values())
            while 'CustomShader' + str(index) in used:
                index += 1
            mark_name = str(index)

        if any(char in mark_name for char in '[]\r\n'):
            raise ValueError('CustomShader MarkName 不能包含 [] 或换行符: ' + mark_name)

        section_name = 'CustomShader' + mark_name
        existing_node_key = cls._base_section_to_node.get(section_name)
        if existing_node_key is not None and existing_node_key != key:
            raise ValueError('CustomShader MarkName 重复: ' + mark_name)

        cls._node_to_base_section[key] = section_name
        cls._base_section_to_node[section_name] = key
        return section_name

    @classmethod
    def _section_name_for_draw(cls, node, draw_line):
        node_key = cls._node_key(node)
        base_section_name = cls._base_section_name(node)
        body = cls._node_body(node)

        # Bodies without the draw macro are inherently reusable. Bodies with
        # {{drawindexed}} need one section per concrete draw call so branches
        # cannot overwrite each other's replacement text.
        binding_key = (node_key, draw_line) if '{{drawindexed}}' in body else (node_key, None)
        existing_section_name = cls._binding_to_section.get(binding_key)
        if existing_section_name:
            return existing_section_name

        section_name = base_section_name
        suffix = 2
        while section_name in cls._section_to_definition:
            section_name = base_section_name + '_' + str(suffix)
            suffix += 1

        cls._binding_to_section[binding_key] = section_name
        cls._section_to_definition[section_name] = {
            'node_key': node_key,
            'node': node,
            'draw_line': draw_line if '{{drawindexed}}' in body else None,
        }
        return section_name

    @classmethod
    def get_draw_lines(cls, drawcall_model, draw_line):
        nodes = getattr(drawcall_model, 'custom_shader_node_list', []) or []
        if not nodes:
            return [draw_line]

        result = []
        for node in nodes:
            if not cls._is_active_node(node):
                continue
            section_name = cls._section_name_for_draw(node, draw_line)
            result.append('run = ' + section_name)

        # The Object Info sockets are dynamically extensible, so a newly
        # created or muted CustomShader node can legitimately be present in
        # the collected list.  It must not suppress the original draw.
        return result or [draw_line]

    @classmethod
    def append_sections(cls, ini_builder):
        if not cls._section_to_definition:
            return
        if getattr(ini_builder, '_custom_shader_sections_appended', False):
            return

        from .m_ini_builder import M_IniSection, M_SectionType

        for section_name, definition in cls._section_to_definition.items():
            node = definition['node']
            body = cls._node_body(node)
            draw_line = definition['draw_line']
            if draw_line is not None:
                body = body.replace('{{drawindexed}}', draw_line)

            section = M_IniSection(M_SectionType.CustomShader)
            section.append('[' + section_name + ']')
            for line in body.splitlines():
                section.append(line)
            section.new_line()
            ini_builder.append_section(section)

        ini_builder._custom_shader_sections_appended = True
