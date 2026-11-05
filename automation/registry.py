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


# Mutation actions name their complete targets rather than relying on selection.
# Settings edits are in-memory; saving a scene is a separate explicit action.
# Graph edits always create a new version, with no overwrite option.
add_action("settings.update", "Apply a typed in-memory batch to an explicit scene settings owner.", {
    "owner": string_schema("Exact scene settings attribute"),
    "values": {"type": "object", "additionalProperties": {}},
}, ("owner", "values"), mutates=True)

# Node properties are open JSON only at the contract boundary.
# The implementation checks every field against actual editable RNA metadata.
# Socket indices are nonnegative; missing or out-of-range sockets are errors.
NODE_SPEC = object_schema({
    "name": string_schema("Exact node name in the new graph version"),
    "type": string_schema("Registered node bl_idname"),
    "properties": {"type": "object", "additionalProperties": {}},
    "inputs": {"type": "array", "items": string_schema("Input socket name"), "maxItems": 512},
    "outputs": {"type": "array", "items": string_schema("Output socket name"), "maxItems": 512},
    "parent": {"type": "string", "maxLength": 4096},
}, ("name", "type"))
LINK_SPEC = object_schema({
    "from_node": string_schema("Source node name"),
    "from_socket": {"type": "integer", "minimum": 0},
    "to_node": string_schema("Target node name"),
    "to_socket": {"type": "integer", "minimum": 0},
}, ("from_node", "from_socket", "to_node", "to_socket"))

# Custom groups expose native object-flow interfaces, not arbitrary shaders.
# A base-tree patch can add nodes, replace properties and remove staged nodes.
# strict=false makes a draft explicit and retains its validation diagnostics.
# base_revision protects edits made by the user after an AI state query.
# A missing revision is not treated as permission to use the latest graph.
# Successful builds return a new token for the next collaborative step.
# present defaults to true and updates a real visible editor.
# Disabling presentation still requires an interactive Blender desktop.
# Presentation is navigation state, not proof that an exporter ran.
add_action("blueprint.build", "Create a validated copy-on-write blueprint version from explicit node and link data.", {
    "name": string_schema("New unique blueprint version name"),
    "base_tree": string_schema("Optional existing tree to copy without modifying it"),
    "base_revision": string_schema("Current revision token required when base_tree is provided"),
    "present": {"type": "boolean", "description": "Show the successful graph in the real editor; defaults to true"},
    "nodes": {"type": "array", "items": NODE_SPEC, "maxItems": 2000},
    "links": {"type": "array", "items": LINK_SPEC, "maxItems": 5000},
    "remove_nodes": {"type": "array", "items": string_schema("Node removed only from the staged copy"), "maxItems": 2000},
    "replace_links": {"type": "boolean"},
    "strict": {"type": "boolean"},
    "interface": {"type": "array", "maxItems": 512, "items": object_schema({
        "name": string_schema("Native interface socket name"),
        "direction": string_schema("Interface direction", ("INPUT", "OUTPUT")),
    }, ("name", "direction"))},
}, ("name", "nodes"), mutates=True)
add_action("blueprint.validate", "Validate graph cycles, group recursion, output presence and object references without edits.", {
    "tree": string_schema("Exact blueprint datablock name"),
}, ("tree",))

# Presentation changes actual current-window editor/selection state.
# It never launches a background process or opens a different saved scene.
add_action("scene.present", "Show an explicit blueprint or object set in the user's real Blender desktop.", {
    "tree": string_schema("Exact blueprint tree name"),
    "objects": {"type": "array", "items": string_schema("Exact scene object name"), "minItems": 1, "maxItems": 200},
    "focus": {"type": "boolean"},
}, mutates=True)
