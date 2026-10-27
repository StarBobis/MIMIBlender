"""Refresh every texture replacement node of a blueprint in one pass.

The node editor offers a single "Refresh Blueprint" entry in its context menu
and users expect that entry to make the whole blueprint current.  It used to
rebuild the Submesh list and re-resolve the object nodes only, so every
texture replacement node kept the mark list, the generated file names and the
conversion state it had when it was created.  After a re-extract, a re-mark or
a workspace switch the only way to make such a row current was to open the
node and press its own refresh / convert button, which is one click per node.

This module closes that gap.  It never writes a texture file and never starts
a conversion: it only re-reads stored detection data, rebuilds the row labels
and lets the caller decide whether the now-known pending replacements should
be converted in the background.
"""
from .blueprint_node_group import GROUP_NODE_IDNAME

# Node identifiers of the four replacement nodes.  The same list exists in
# common.texture_format_service.ADDRESSABLE_NODE_IDS; keeping the strings here
# as plain literals avoids importing that service (and bpy) from this module.
SLOT_BIND_IDNAME = 'MIMINode_Texture_Bind'
HASH_BIND_IDNAME = 'MIMINode_Hash_Texture_Bind'
HASH_GLOBAL_IDNAME = 'MIMINode_Hash_Texture_Global'
GLOBAL_SLOT_IDNAME = 'MIMINode_Texture_Global'

# Every node type this module knows how to refresh.
TEXTURE_NODE_IDNAMES = (
    SLOT_BIND_IDNAME,
    HASH_BIND_IDNAME,
    HASH_GLOBAL_IDNAME,
    GLOBAL_SLOT_IDNAME,
)


def refresh_slot_bind_rows(node):
    """Rebuild the mark identity and the list label of every slot row.

    A row stores its mark as a durable name (``mark_name_value``), but a file
    saved by an older release still carries the old enum index.  Reading the
    name through ``mark_name_of`` migrates such a row, so the refresh also
    repairs rows instead of only re-drawing them.
    """
    # Imported inside the function: the node module imports widgets that in
    # turn import shared helpers, so a module level import could close a cycle.
    from .blueprint_node_texture import _texture_slot_item_refresh_display, mark_name_of

    rows = list(getattr(node, "texture_slot_items", []) or [])
    for item in rows:
        # mark_name_of() writes the durable name back on the first read.
        mark_name_of(item)
        # The label shows slot, mark name, replacement image and alias.
        _texture_slot_item_refresh_display(item)
    return len(rows)


def refresh_hash_rows(node):
    """Re-scan the workspace marks one hash node can reach.

    The scan keeps every replacement choice a row already has and only
    updates the detected fields, so refreshing is safe to repeat.
    """
    from .blueprint_node_hash_texture import _refresh_global_hash_rows

    _refresh_global_hash_rows(node)
    return len(list(getattr(node, "texture_hash_items", []) or []))


def refresh_global_slot_rows(node):
    """Re-scan the Submesh slot marks of one global slot node."""
    from .blueprint_node_global_slot import refresh_global_slot_rows as refresh_rows

    return refresh_rows(node)


def refresh_texture_node(node):
    """Refresh one texture node and return how many rows it owns.

    A node type this module does not know returns 0, so a blueprint that
    contains future node types still refreshes instead of failing.
    """
    node_id = str(getattr(node, "bl_idname", "") or "")
    if node_id == SLOT_BIND_IDNAME:
        return refresh_slot_bind_rows(node)
    if node_id in (HASH_BIND_IDNAME, HASH_GLOBAL_IDNAME):
        return refresh_hash_rows(node)
    if node_id == GLOBAL_SLOT_IDNAME:
        return refresh_global_slot_rows(node)
    return 0


def refresh_tree_texture_nodes(tree):
    """Refresh every texture node of one blueprint, nested groups included.

    Returns ``{"node_count": int, "row_count": int}`` so the caller can report
    one number instead of staying silent.  A group tree is shared by all of its
    instances, so ``visited`` prevents re-scanning the same nodes twice.
    """
    summary = {"node_count": 0, "row_count": 0}
    visited = set()

    def visit(current_tree):
        if current_tree is None or id(current_tree) in visited:
            return
        visited.add(id(current_tree))
        for node in list(getattr(current_tree, "nodes", []) or []):
            node_id = str(getattr(node, "bl_idname", "") or "")
            if node_id == GROUP_NODE_IDNAME:
                # A group node owns its own tree; only that tree is shared.
                visit(getattr(node, "node_tree", None))
                continue
            if node_id not in TEXTURE_NODE_IDNAMES:
                continue
            try:
                summary["row_count"] += refresh_texture_node(node)
                summary["node_count"] += 1
            except Exception as error:
                # One broken node must not stop the rest of the blueprint.
                print(
                    "TextureNodeRefresh: " + str(getattr(node, "name", "?"))
                    + ": " + str(error)
                )

    visit(tree)
    return summary
