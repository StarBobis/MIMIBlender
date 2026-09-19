"""Read-only upstream object traversal for blueprint previews and UI lookups.

Export keeps its own condition-aware traversal. This helper deliberately visits
all switch states, but still respects object-list and custom-group output ports.
"""


def iter_object_sources(root):
    """Yield Object Info nodes or enabled Object List rows in wire order."""
    # Use an active path rather than a global visited set. Shared nodes may
    # legitimately appear through distinct group instances or output ports.
    # The caller can deduplicate objects if its UI displays a set of meshes.
    active = set()

    def visit(node, output=None, instances=()):
        if node is None or getattr(node, "mute", False):
            return
        # Shared child datablocks can appear in several sequential instances.
        # Instance context distinguishes that valid reuse from a wire cycle.
        key = (node.as_pointer(), output.as_pointer() if output else 0,
               tuple(instance.as_pointer() for instance in instances))
        if key in active:
            # A preview must remain responsive even for an invalid graph.
            # The exporter reports cycles as errors instead of skipping them.
            return
        active.add(key)
        try:
            kind = node.bl_idname
            if kind == 'MIMINode_Object_Info':
                yield node
                return
            if kind == 'MIMINode_Object_List':
                rows = list(node.object_items)
                if output is not None:
                    sockets = list(node.outputs)
                    if output not in sockets:
                        return
                    index = sockets.index(output)
                    if index:
                        rows = rows[index - 1:index]
                # Disabled rows retain their wires but contribute no objects.
                for row in rows:
                    if row.enabled:
                        yield row
                return
            if kind == 'SSMTBlueprintGroupNode':
                tree = node.node_tree
                if tree is None or any(instance.node_tree == tree for instance in instances):
                    # Ignore corrupt recursive group references in preview.
                    return
                # Only the connected group output belongs to this path.
                index = list(node.outputs).index(output) if output is not None else None
                from .blueprint_node_group import get_group_output_node
                child = get_group_output_node(tree)
                if child is not None:
                    sockets = list(child.inputs)
                    if index is not None:
                        sockets = sockets[index:index + 1]
                    yield from links(sockets, instances + (node,))
                return
            if kind == 'NodeGroupInput':
                if not instances or output is None:
                    return
                index = list(node.outputs).index(output)
                parent = instances[-1]
                # Cross back to the parent instance context for nested groups.
                yield from links(list(parent.inputs)[index:index + 1], instances[:-1])
                return
            # Output nodes are composition boundaries, except the preview root.
            if node != root and kind in {'MIMINode_Result_Output', 'MIMINode_Face_Mod_Export'}:
                return
            yield from links(node.inputs, instances)
        finally:
            active.remove(key)

    def links(sockets, instances):
        # Plain groups, switch states, reroutes and texture binds all pass
        # upstream data through their input links for preview purposes.
        for socket in sockets:
            for link in socket.links:
                yield from visit(link.from_node, link.from_socket, instances)

    yield from visit(root)
