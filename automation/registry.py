"""Explicit automation actions and MCP-compatible tool descriptions.

Keep the public contract independent of Blender and transport implementations.
Only implemented actions belong here; discovery must not advertise future work.
"""
# Tool names are stable action identities, not translated labels.
# Descriptions are instructions for clients, not executable code.
# inputSchema is shared by discovery and runtime validation.
# All schema objects are copied before leaving the registry.
# A client cannot widen validation by changing a manifest response.
# The mutation flag is an execution annotation, not user authorization.
# Source code registration and protocol action registration are distinct.
# New handlers must be tested before their tools are advertised.
# Query tools deliberately omit implicit workspace/output selection.
# Transport adapters may map these names to their own tool name convention.
from copy import deepcopy

from .contract import object_schema, string_schema


ACTIONS = {}


def add_action(name, description, properties=None, required=(), mutates=False):
    """Register one action and reject duplicate identities during development."""
    if name in ACTIONS:
        raise ValueError("Duplicate automation action: " + name)
    # Handlers are resolved lazily so ordinary clients can inspect the schemas.
    ACTIONS[name] = {"name": name, "description": description,
                     "inputSchema": object_schema(properties, required),
                     "mutates": bool(mutates)}


def tools():
    """Return independent tool dictionaries; callers cannot edit the registry."""
    return [deepcopy(ACTIONS[name]) for name in sorted(ACTIONS)]


# Query actions never save host configuration or silently choose an export.
# Larger scenes are paginated instead of being claimed complete after truncation.
# RNA descriptions use stable identifiers rather than localized UI captions.
add_action("system.capabilities", "Discover implemented actions, registered add-on types and supported game exporters.")
add_action("scene.inspect", "Inspect the active scene and paginated object state without editing it.", {
    "offset": {"type": "integer", "minimum": 0},
    "limit": {"type": "integer", "minimum": 1, "maximum": 200},
    "objects": {"type": "array", "items": string_schema("Exact object name"), "maxItems": 200},
})
add_action("settings.inspect", "Read the current scene's MIMIBlender settings and schemas.")
add_action("rna.describe", "Describe a registered operator, blueprint node or settings property group.", {
    "kind": string_schema("RNA owner kind", ("operator", "node", "settings")),
    "identifier": string_schema("Operator bl_idname, node bl_idname, or scene settings attribute"),
}, ("kind", "identifier"))
add_action("blueprint.inspect", "Inspect one explicitly named blueprint, its nodes, properties, sockets and links.", {
    "tree": string_schema("Exact blueprint datablock name"),
    "offset": {"type": "integer", "minimum": 0},
    "limit": {"type": "integer", "minimum": 1, "maximum": 200},
}, ("tree",))
