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


# Collaboration status is an observation, never a promise of game acceptance.
# The real desktop panel and MCP clients read the same retained job journal.
add_action("state.inspect", "Inspect current-scene collaboration tasks, progress, errors and retained recovery observations.")

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

# Source discovery is read-only and exposes ambiguous native type candidates.
# Import requests are cooperative jobs, not long blocking UI operator wrappers.
# Work directories contain new session records, never rewritten source buffers.
# Type maps use explicit native Submesh identities from workspace.inspect.
# The source revision detects changes between inspection and submission.
# Native component steps additionally check dependency file stats before reads.
add_action("workspace.inspect", "Inspect explicit native workspace components, type choices and buffer dependencies.", {
    "source": string_schema("Absolute read-only workspace directory"),
    "offset": {"type": "integer", "minimum": 0},
    "limit": {"type": "integer", "minimum": 1, "maximum": 200},
}, ("source",))
add_action("workspace.import", "Start a visible cooperative native workspace import into the current user scene.", {
    "source": string_schema("Absolute read-only source workspace directory"),
    "source_revision": string_schema("Optional inspected source revision token"),
    "logic": string_schema("Registered game exporter logic identifier"),
    "workspace_name": string_schema("Workspace identity used by native model bindings"),
    "name": string_schema("Unique blueprint/collection name for the imported result"),
    "work_directory": string_schema("Absolute working root outside the source workspace"),
    "types": {"type": "object", "additionalProperties": string_schema("Explicit native data type")},
    "settings": {"type": "object", "additionalProperties": {}},
    "present": {"type": "boolean"},
}, ("source", "logic", "name", "work_directory"), mutates=True)

# A queued/running status is not a successful workflow result.
# Polling observes state only; timers own progress on the visible main thread.
# Cancellation retains already committed/visible artifacts for manual recovery.
add_action("job.inspect", "Read a cooperative job's actual progress, error or terminal result.", {
    "job": string_schema("Exact returned workflow job identifier"),
}, ("job",))
add_action("job.cancel", "Cancel future steps of a visible workflow while retaining partial user-visible work.", {
    "job": string_schema("Exact returned workflow job identifier"),
}, ("job",), mutates=True)

# Existing user geometry can be handed to AI without another import pass.
# Binding creates a new recoverable graph version and private type record.
add_action("workspace.bind", "Bind a partially edited user blueprint to explicit read-only native workspace data.", {
    "tree": string_schema("Existing user blueprint name"),
    "revision": string_schema("Fresh graph revision token"),
    "name": string_schema("Optional new bound blueprint version name"),
    "source": string_schema("Absolute source workspace directory"),
    "logic": string_schema("Registered native game exporter logic"),
    "workspace_name": string_schema("Native workspace identity"),
    "work_directory": string_schema("Absolute isolated working root"),
    "types": {"type": "object", "additionalProperties": string_schema("Explicit data type")},
    "settings": {"type": "object", "additionalProperties": {}},
    "present": {"type": "boolean"},
}, ("tree", "revision", "source", "logic", "work_directory"), mutates=True)

# Export is a visible cooperative job, not an in-game validation claim.
# Output directories must be new and outside source assets.
# Native conversion and generation use the tree's own persisted source context.
# Artifact hashes establish local files, not correct in-game rendering.
# Manual Generate Mod routes bound trees through this same job contract.
# Source-binding changes are covered by the graph revision token.
# A user edit during preparation interrupts rather than updating old output.
add_action("mod.export", "Generate a native Mod into a new directory and independently audit files/scene preservation.", {
    "tree": string_schema("Exact bound blueprint name"),
    "revision": string_schema("Current graph revision token"),
    "output_node": string_schema("Output node identity; required for multiple outputs"),
    "output_directory": string_schema("Absolute new Mod directory outside source assets"),
    "settings": {"type": "object", "additionalProperties": {}},
}, ("tree", "revision", "output_directory"), mutates=True)
add_action("mod.audit", "Read-only offline INI/resource-file closure and artifact hash audit; does not run a game.", {
    "output_directory": string_schema("Absolute generated Mod directory"),
}, ("output_directory",))

# Incremental model edits keep the same object identity for user/AI handoff.
# Every mutation requires a fresh revision and returns an independent checkpoint.
# Coordinate data is local-space and finite; no caller expressions are evaluated.
# The scene object retains its identity so existing blueprints still target it.
# Shared mesh data is copied before local edits or sparse weight updates.
# Checkpoints are independently retained meshes, not mutable references to originals.
# A failed visible presentation also rolls back the newly assigned mesh data.
# Native UV loop indices are distinct from mesh vertex indices.
# Named shape keys are explicit targets; generic vertices do not imply Basis.
# Locked vertex groups are not silently unlocked by the AI edit.
# Restore itself checkpoints current work before changing the object again.
# A missing or spoofed checkpoint marker cannot select unrelated user data.
# User Edit/Pose/Paint mode prevents starting a new mutation transaction.
# Topology replacement never infers weights or missing raw game channels.
VECTOR3 = {"type": "array", "items": {"type": "number", "minimum": -1e20, "maximum": 1e20}, "minItems": 3, "maxItems": 3}
VECTOR2 = {"type": "array", "items": {"type": "number", "minimum": -1e20, "maximum": 1e20}, "minItems": 2, "maxItems": 2}
VERTEX_EDIT = object_schema({"index": {"type": "integer", "minimum": 0}, "value": VECTOR3}, ("index", "value"))
UV_EDIT = object_schema({"index": {"type": "integer", "minimum": 0}, "value": VECTOR2}, ("index", "value"))
add_action("mesh.inspect", "Inspect an editable current-scene mesh, local vertices/weights and recoverable history.", {
    "object": string_schema("Exact current-scene mesh object name"),
    "offset": {"type": "integer", "minimum": 0},
    "limit": {"type": "integer", "minimum": 1, "maximum": 200},
}, ("object",))

# Topology replacement is explicit and cannot silently erase source channels.
# Existing raw attributes/shape keys require acknowledged replacement.
# UVs and weights are required for replacement of existing textured/skinned data.
add_action("mesh.patch", "Stage typed geometry, weights, UVs, shape keys or transforms and commit visibly with a checkpoint.", {
    "object": string_schema("Exact target mesh object"), "revision": string_schema("Current mesh revision token"),
    "vertices": {"type": "array", "items": VERTEX_EDIT, "maxItems": 10000},
    "weights": {"type": "array", "maxItems": 512, "items": object_schema({
        "group": string_schema("Named native vertex group"),
        "values": {"type": "array", "maxItems": 10000, "items": object_schema({
            "index": {"type": "integer", "minimum": 0}, "weight": {"type": "number", "minimum": 0, "maximum": 1},
        }, ("index", "weight"))},
    }, ("group", "values"))},
    "uvs": {"type": "array", "maxItems": 16, "items": object_schema({
        "layer": string_schema("Exact UV layer name"), "create": {"type": "boolean"},
        "values": {"type": "array", "items": UV_EDIT, "maxItems": 10000},
    }, ("layer", "values"))},
    "shape_keys": {"type": "array", "maxItems": 256, "items": object_schema({
        "name": string_schema("Basis or exact named shape key"), "create": {"type": "boolean"},
        "vertices": {"type": "array", "items": VERTEX_EDIT, "maxItems": 10000},
        "value": {"type": "number"}, "mute": {"type": "boolean"},
    }, ("name",))},
    "transform": object_schema({"location": VECTOR3, "rotation_euler": VECTOR3, "scale": VECTOR3}),
    "geometry": object_schema({
        "positions": {"type": "array", "items": VECTOR3, "minItems": 1, "maxItems": 20000},
        "faces": {"type": "array", "maxItems": 50000, "items": {"type": "array", "minItems": 3, "maxItems": 64,
                  "items": {"type": "integer", "minimum": 0}}},
    }, ("positions", "faces")),
    "drop_shape_keys": {"type": "boolean"}, "drop_raw_attributes": {"type": "boolean"},
    "present": {"type": "boolean"},
}, ("object", "revision"), mutates=True)

# Restore is a versioned transaction, not a destructive return to stale data.
# The current user version receives its own checkpoint before older data is used.
add_action("mesh.restore", "Restore an independent checkpoint after verifying current mesh revision, preserving current work too.", {
    "object": string_schema("Current mesh object name"), "revision": string_schema("Fresh current mesh revision"),
    "checkpoint": string_schema("Exact returned independent checkpoint ID"), "present": {"type": "boolean"},
}, ("object", "revision", "checkpoint"), mutates=True)

# Reverse outputs retain their native candidate/segment component identities.
# They are not silently converted into a normal extraction workspace.
# Export needs an explicit original-workspace binding after review/editing.
# Candidate choice is made per original DrawIB, not scene collection ordering.
# Partial/cancelled reverse imports keep visible data for user recovery.
# Source hashes/stats are observations rather than proof of game rendering.
add_action("reverse.inspect", "Inspect native ssmt_fmt DrawIB candidates and source dependency framing.", {
    "source": string_schema("Absolute read-only reverse output directory"),
    "offset": {"type": "integer", "minimum": 0}, "limit": {"type": "integer", "minimum": 1, "maximum": 200},
}, ("source",))
add_action("reverse.import", "Import one chosen native reverse layout per DrawIB cooperatively into the visible user scene.", {
    "source": string_schema("Absolute read-only reverse output root"),
    "source_revision": string_schema("Optional fresh reverse inspection revision"),
    "name": string_schema("New result collection name"), "logic": string_schema("Native source game preset"),
    "work_directory": string_schema("Absolute isolated working root outside source"),
    "types": {"type": "object", "additionalProperties": string_schema("Chosen native candidate type per DrawIB")},
    "settings": {"type": "object", "additionalProperties": {}}, "present": {"type": "boolean"},
}, ("source", "name", "logic", "work_directory"), mutates=True)
