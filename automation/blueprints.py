"""Noninteractive blueprint authoring with copy-on-write graph versions.

The caller identifies nodes, properties and socket indices explicitly.
A successful build creates a new tree; an existing base tree is never edited.
Failed builds remove only their disposable staged tree and restore UUID metadata
that legacy Object Info callbacks may have added to referenced source objects.
"""
# Graph transaction rules:
# - name identifies a new version and must not already exist.
# - base_tree is optional and always remains unchanged.
# - Copy-on-write includes custom PropertyGroup collection data.
# - Existing source objects and mesh datablocks are never removed.
# - Only a newly allocated failed staging tree is discarded.
# - A new tree is retained with a fake user so Blender can save it later.
# - Building does not select a different editor or active scene.
# - Frame parent names are resolved after all requested nodes exist.
# - Node types must be registered add-on types or explicit graph primitives.
# - Node identifiers never become arbitrary Python attribute paths.
# - Properties are typed by the real registered RNA declaration.
# - Row collections remain native PropertyGroups, not opaque JSON strings.
# - Object List rows retain their mirrored output sockets.
# - Additional input/output names create only native object-flow sockets.
# - A requested socket count cannot shrink existing linked sockets silently.
# - Link indices are checked after node properties and row lists are applied.
# - Duplicate links and accidental occupied-input replacement are errors.
# - replace_links explicitly clears only the staged copy's previous edges.
# - remove_nodes removes only staged nodes, retaining the original base version.
# - Every graph edge must connect compatible registered sockets.
# - Direct data-flow cycles are invalid even when Blender permits the link.
# - Custom group recursion is checked separately from direct graph cycles.
# - Frame-parent recursion is invalid even though frames have no flow sockets.
# - A strict build requires an output or a custom-group output.
# - Draft builds are possible only with strict explicitly disabled.
# - A draft reports its validation errors rather than pretending to be complete.
# - Validation never refreshes or rewrites Object Info references.
# - Object UUID resolution uses the add-on's existing identity policy.
# - Validation includes all source nodes, not only selected editor nodes.
# - Disconnected ordinary nodes are warnings, not an implicit deletion request.
# - Socketless global texture nodes are valid without object-flow links.
# - Game-format binding and artifact validation remain export-layer checks.
# - A structurally valid graph does not certify a supported shader layout.
# - Nested validation has a depth and population limit.
# - Missing targets fail deterministically instead of falling back to selection.
# - Object binding metadata may be added on success by native callbacks.
# - Failed calls restore that metadata so partial staging is not retained.
# - No physical file is generated, overwritten or deleted by graph actions.
import bpy

from .contract import AutomationError
from .inspection import addon_classes, blueprint_inspect, require_tree
from .properties import set_node_properties


# These Blender graph primitives are deliberately allowed in custom blueprints.
# Every other node type must originate in the registered MIMIBlender classes.
# Group interface sockets remain the same custom object-flow socket type.
GRAPH_PRIMITIVES = {"NodeFrame", "NodeGroupInput", "NodeGroupOutput"}
OUTPUT_TYPES = {"MIMINode_Result_Output", "MIMINode_Face_Mod_Export", "NodeGroupOutput"}


def graph_errors(tree, ancestors=(), budget=None):
    """Return structural errors/warnings without changing graph or object state."""
    from ..blueprint.blueprint_node_obj import ObjectPersistentIdManager
    errors, warnings = [], []
    budget = budget if budget is not None else [0]
    if tree.as_pointer() in ancestors or len(ancestors) >= 32:
        return [{"code": "GROUP_RECURSION", "tree": tree.name}], []
    budget[0] += len(tree.nodes)
    if budget[0] > 10000:
        return [{"code": "GRAPH_TOO_LARGE", "tree": tree.name}], []
    # Kahn's algorithm detects directed cycles without recursive node walking.
    # Frames have no edges, so parent cycles need their own independent check.
    nodes = list(tree.nodes)  # Freeze the population during this read-only check.
    incoming = {node.name: 0 for node in nodes}  # Count every incoming flow edge.
    outgoing = {node.name: [] for node in nodes}  # Preserve each directed successor.
    for link in tree.links:  # Native link validity supplements cycle detection.
        incoming[link.to_node.name] += 1  # Parallel edges are counted independently.
        outgoing[link.from_node.name].append(link.to_node.name)  # Direction is semantic.
        if not link.is_valid:  # Blender may retain a physically incompatible edge.
            errors.append({"code": "INVALID_LINK", "tree": tree.name,
                           "from_node": link.from_node.name, "to_node": link.to_node.name})
    queue = [name for name, count in incoming.items() if count == 0]  # Start at all roots.
    processed = 0  # Nodes that remain unprocessed belong to a cycle or its descendants.
    while queue:
        name = queue.pop()  # An explicit queue avoids Python recursion depth failures.
        processed += 1
        for target in outgoing[name]:  # Remove only the processed root's outgoing edges.
            incoming[target] -= 1  # Each counted edge is removed exactly once.
            if incoming[target] == 0:
                queue.append(target)  # A newly unblocked node is now another root.
    if processed != len(nodes):
        errors.append({"code": "GRAPH_CYCLE", "tree": tree.name,
                       "nodes": sorted(name for name, count in incoming.items() if count)})
    outputs = [node for node in nodes if node.bl_idname in OUTPUT_TYPES]
    if not outputs:
        errors.append({"code": "MISSING_OUTPUT", "tree": tree.name})
    # Parent traversal is bounded by the tree population, not arbitrary recursion.
    # A frame cycle would otherwise hang both layout and saved-tree inspection.
    for node in nodes:
        parent, seen = node.parent, {node.as_pointer()}
        while parent is not None:
            if parent.as_pointer() in seen:
                errors.append({"code": "FRAME_RECURSION", "tree": tree.name, "node": node.name})
                break
            seen.add(parent.as_pointer())
            parent = parent.parent
        if node.bl_idname == "MIMINode_Object_Info":
            obj = ObjectPersistentIdManager.resolve_node_target(node)
            if obj is None or obj.type != "MESH":
                errors.append({"code": "INVALID_OBJECT_REFERENCE", "tree": tree.name, "node": node.name})
        elif node.bl_idname == "MIMINode_Object_List":
            seen_objects = set()
            for index, item in enumerate(node.object_items):
                obj = item.object_ref or bpy.data.objects.get(item.object_name)
                if obj is None or obj.type != "MESH":
                    errors.append({"code": "INVALID_OBJECT_REFERENCE", "tree": tree.name,
                                   "node": node.name, "row": index})
                elif obj.as_pointer() in seen_objects:
                    errors.append({"code": "DUPLICATE_OBJECT_REFERENCE", "tree": tree.name,
                                   "node": node.name, "object": obj.name})
                else:
                    seen_objects.add(obj.as_pointer())
            if len(node.outputs) != len(node.object_items) + 1:
                errors.append({"code": "OBJECT_LIST_SOCKET_MISMATCH", "tree": tree.name, "node": node.name})
        elif node.bl_idname == "SSMTBlueprintGroupNode":
            child = node.node_tree
            if child is None or child.bl_idname != "MIMIBlueprintTreeType":
                errors.append({"code": "INVALID_GROUP_REFERENCE", "tree": tree.name, "node": node.name})
            else:
                child_errors, child_warnings = graph_errors(child, ancestors + (tree.as_pointer(),), budget)
                errors.extend(child_errors)
                warnings.extend(child_warnings)
        if node.inputs or node.outputs:
            if node.bl_idname not in GRAPH_PRIMITIVES and not any(socket.is_linked for socket in list(node.inputs) + list(node.outputs)):
                warnings.append({"code": "DISCONNECTED_NODE", "tree": tree.name, "node": node.name})
    return errors, warnings


def blueprint_validate(params):
    """Validate an explicitly named graph, without claiming game-format proof."""
    from .presentation import desktop_window
    desktop_window()
    tree = require_tree(params["tree"])
    errors, warnings = graph_errors(tree)
    return {"tree": tree.name, "valid": not errors, "errors": errors, "warnings": warnings,
            "outputs": [node.name for node in tree.nodes if node.bl_idname in OUTPUT_TYPES],
            "scope": "structural_graph_and_object_references"}


def ensure_sockets(node, direction, names):
    """Add explicitly named object-flow sockets without destroying prior edges."""
    sockets = node.inputs if direction == "inputs" else node.outputs
    if len(names) < len(sockets):
        raise AutomationError("INVALID_ARGUMENT", "Socket lists cannot shrink in a build patch",
                              {"node": node.name, "direction": direction})
    # Nodes with native group interfaces own their socket synchronization.
    # Manual growth must not diverge from a referenced child group's interface.
    if node.bl_idname in {"SSMTBlueprintGroupNode", "NodeGroupInput", "NodeGroupOutput"}:
        if len(names) != len(sockets):
            raise AutomationError("INVALID_ARGUMENT", "Group sockets are owned by their interface", {"node": node.name})
    for index, name in enumerate(names):
        if index == len(sockets):
            sockets.new("MIMISocketObject", name)
        else:
            sockets[index].name = name


def add_interface(tree, entries):
    """Create declared custom-group interface sockets on the new tree only."""
    # Read Blender's actual direction identifiers before passing one to its API.
    # The client schema advertises directions but Blender is still authoritative.
    directions = [item.identifier for item in bpy.types.NodeTreeInterfaceSocket.bl_rna.properties["in_out"].enum_items]
    for entry in entries:
        if entry["direction"] not in directions:
            raise AutomationError("INVALID_ARGUMENT", "Blender does not support this interface direction")
        tree.interface.new_socket(entry["name"], in_out=entry["direction"], socket_type="MIMISocketObject")


def blueprint_build(params):
    """Build a new graph version, discarding only an invalid disposable stage."""
    from ..blueprint.blueprint_node_obj import OBJECT_PERSISTENT_ID_KEY
    from .presentation import desktop_window, present_tree
    from .revisions import blueprint_revision
    desktop_window()
    name = params["name"]
    if bpy.data.node_groups.get(name) is not None:
        raise AutomationError("ALREADY_EXISTS", "Blueprint version name already exists", {"tree": name})
    base = require_tree(params["base_tree"]) if params.get("base_tree") else None
    if base is not None:
        actual_revision = blueprint_revision(base)
        if params.get("base_revision") != actual_revision:
            raise AutomationError("STALE_REVISION", "User graph changed or its current revision was not supplied",
                                  {"tree": base.name, "current_revision": actual_revision})
    types = GRAPH_PRIMITIVES | {getattr(value, "bl_idname", "") for value, kind in addon_classes() if kind == "Node"}
    names = [entry["name"] for entry in params["nodes"]]
    if len(names) != len(set(names)):
        raise AutomationError("INVALID_ARGUMENT", "Build request contains duplicate node names")
    for entry in params["nodes"]:
        if entry["type"] not in types:
            raise AutomationError("INVALID_NODE_TYPE", "Node type is not an allowed registered blueprint type", {"type": entry["type"]})
    # Native Object Info callbacks create UUIDs. Capture only that metadata.
    # Geometry, material bindings, weights and source objects are never edited.
    metadata = {obj: (OBJECT_PERSISTENT_ID_KEY in obj, obj.get(OBJECT_PERSISTENT_ID_KEY)) for obj in bpy.data.objects}
    tree = base.copy() if base else bpy.data.node_groups.new(name, "MIMIBlueprintTreeType")
    tree.name = name
    tree.use_fake_user = True
    try:
        if tree.name != name:
            raise AutomationError("INVALID_NAME", "Blender could not retain the requested exact tree name", {"actual": tree.name})
        if params.get("replace_links", False):
            tree.links.clear()
        for node_name in params.get("remove_nodes", []):
            node = tree.nodes.get(node_name)
            if node is None:
                raise AutomationError("NOT_FOUND", "Node to remove was not found in the staged copy", {"node": node_name})
            tree.nodes.remove(node)
        add_interface(tree, params.get("interface", []))
        for entry_index, entry in enumerate(params["nodes"]):
            node = tree.nodes.get(entry["name"])
            if node is not None and node.bl_idname != entry["type"]:
                raise AutomationError("TYPE_MISMATCH", "Existing staged node has a different type", {"node": node.name})
            if node is None:
                node = tree.nodes.new(entry["type"])
                node.name = entry["name"]
                node.location = (entry_index * 520.0, 0.0)
                if node.name != entry["name"]:
                    raise AutomationError("INVALID_NAME", "Blender could not retain the exact node name", {"actual": node.name})
            set_node_properties(node, entry.get("properties", {}))
            node.select = False
            for direction in ("inputs", "outputs"):
                if direction in entry:
                    ensure_sockets(node, direction, entry[direction])
        # Parent resolution is separate from property assignment to avoid a
        # node-order dependency when a frame appears later in the request.
        for entry in params["nodes"]:
            if "parent" in entry:
                parent = tree.nodes.get(entry["parent"]) if entry["parent"] else None
                if entry["parent"] and (parent is None or parent.bl_idname != "NodeFrame"):
                    raise AutomationError("INVALID_PARENT", "Parent must identify a frame in this blueprint")
                tree.nodes[entry["name"]].parent = parent
        for edge in params.get("links", []):
            source, target = tree.nodes.get(edge["from_node"]), tree.nodes.get(edge["to_node"])
            if source is None or target is None:
                raise AutomationError("NOT_FOUND", "Link endpoint node was not found", {"link": edge})
            if edge["from_socket"] >= len(source.outputs) or edge["to_socket"] >= len(target.inputs):
                raise AutomationError("INVALID_SOCKET", "Link socket index is out of range", {"link": edge})
            output, input_socket = source.outputs[edge["from_socket"]], target.inputs[edge["to_socket"]]
            if input_socket.is_linked and not input_socket.is_multi_input:
                raise AutomationError("INPUT_OCCUPIED", "Link would silently replace an existing input edge", {"link": edge})
            tree.links.new(output, input_socket)
        validation = blueprint_validate({"tree": tree.name})
        if params.get("strict", True) and not validation["valid"]:
            raise AutomationError("INVALID_BLUEPRINT", "Staged blueprint failed structural validation", validation)
        tree["mimi_ai_base_tree"] = base.name if base else ""
        revision = blueprint_revision(tree)
        presentation = present_tree(tree) if params.get("present", True) else {"visible": False, "deferred": True}
        return {"tree": tree.name, "base_tree": base.name if base else None, "revision": revision,
                "presentation": presentation,
                "validation": validation, "graph": blueprint_inspect({"tree": tree.name, "limit": 200})}
    except Exception as error:
        # Rollback discards only the newly created, unsaved staging datablock.
        # Original trees and user objects remain available for a corrected retry.
        bpy.data.node_groups.remove(tree)
        for obj, (existed, previous) in metadata.items():
            if existed:
                obj[OBJECT_PERSISTENT_ID_KEY] = previous
            elif OBJECT_PERSISTENT_ID_KEY in obj:
                del obj[OBJECT_PERSISTENT_ID_KEY]
        if isinstance(error, AutomationError):
            raise
        raise AutomationError("BUILD_FAILED", str(error)) from error


# The handler map names actual implementations, never arbitrary attribute paths.
# Registering these handlers does not instantiate a graph or save a scene.
HANDLERS = {"blueprint.build": blueprint_build, "blueprint.validate": blueprint_validate}
