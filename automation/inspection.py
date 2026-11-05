"""Read-only Blender inspection behind the transport-independent AI contract.

Queries reacquire live datablocks on every call. They do not rely on a prior
Python execution namespace, a selected editor, or remembered UI node identity.
Pagination and unreadable values are explicit rather than silent omissions.
"""
# Inspection contract:
# - The active scene is reported explicitly in every scene response.
# - Queries never pick a different scene based on a remembered workspace.
# - Object names identify targets within the active scene, not all datablocks.
# - A missing object name is an actionable NOT_FOUND response.
# - Datablock identity remains case-sensitive, matching Blender itself.
# - Name filters preserve the caller's ordering.
# - Unfiltered object enumeration has deterministic name ordering.
# - Offset and limit apply to the filtered population.
# - total_objects describes that population rather than the current page.
# - next_offset is null only when the population is exhausted.
# - A query never changes active-object or selection state.
# - The filepath distinguishes unsaved scenes from saved user projects.
# - The current frame is observed without advancing an animation.
# - Matrix values use explicit rows rather than string formatting.
# - World matrices and local location/scale values are both available.
# - Parent identities are reported without expanding their descendants.
# - Collection memberships identify organizational state without editing it.
# - Viewport and render hiding are independent properties.
# - Material slots retain empty slots as null entries.
# - Modifier identity is visible without evaluating or applying modifiers.
# - Mesh vertex and polygon counts are inventory, not topology acceptance.
# - Vertex-group names are identity data, not a claim that weights are valid.
# - Shape-key values and mute state are observed without changing the basis.
# - UV names do not claim a particular texture-channel convention.
# - Armature bone counts do not certify bind-pose or hierarchy equivalence.
# - More detailed geometry acceptance belongs in focused workflow tests.
# - Generic queries never allocate a full list of mesh vertex coordinates.
# - Large property collections have explicit truncation metadata.
# - The collection reader consumes at most the published item bound.
# - Nested values have a separate depth bound.
# - ID pointers become datablock names and RNA types, not memory addresses.
# - Nonfinite observed numbers have explicit unavailable markers.
# - Unsupported RNA values have explicit type markers.
# - One context-dependent property cannot hide all other readable properties.
# - PropertyGroup pointers are inspected through declared RNA fields.
# - Custom object properties remain separate from ordinary object state.
# - This layer does not invent game semantics for unknown custom properties.
# - Registered type discovery uses the currently loaded add-on module tree.
# - Class aliases are deduplicated by Python class identity.
# - Imported external classes do not become add-on-owned capabilities.
# - Abstract bases without registration are not reported as callable types.
# - UI panels and menus are visible but their draw callbacks are not executed.
# - Add-on preferences are discoverable without saving user preferences.
# - A capability response does not enable optional asset-generation services.
# - The exporter list comes from the real current registry.
# - No copied list of game presets is maintained in this module.
# - Exporter availability is separate from a workspace being importable.
# - Registered operators may still require specialized invocation context.
# - RNA description is not equivalent to invoking every listed operator.
# - Operator lookup is restricted to the discovered add-on-owned classes.
# - A built-in quit or save operator is not an add-on capability.
# - Operator namespaces are resolved only after registered identity matching.
# - Node description does not instantiate a node in the user's blueprint.
# - Stable RNA identifiers are used instead of localized captions.
# - Read-only flags tell the editing layer which fields cannot be assigned.
# - Numeric hard limits are metadata, not silently clamped defaults.
# - Pointer and collection target types are exposed for typed property edits.
# - Enum flags are distinguished from ordinary one-value enums.
# - Empty static enum metadata is marked context-dependent.
# - Dynamic enum validity must be resolved before a future edit action.
# - Scene settings are discovered through ownership and declared types.
# - Legacy getter configuration refreshes are restored before returning.
# - Querying settings never persists an Import.json selection record.
# - Blueprint tree identity is required even when a node editor is active.
# - A different selected tree cannot substitute for a missing requested tree.
# - Blueprint pages preserve exact node names and node type identifiers.
# - Parent-frame identity is reported separately from local node location.
# - Custom node properties are separate from standard Node RNA fields.
# - Socket identifiers disambiguate equal localized socket names.
# - Socket indices permit deterministic later connection requests.
# - Socket linkage is visible without adding or removing a graph edge.
# - Edges identify both endpoint nodes and their exact socket identifiers.
# - Graph inspection is not a proof of acyclicity or exporter reachability.
# - A future blueprint validator must establish those stronger properties.
# - No current query deletes datablocks or invokes cleanup operators.
# - No current query opens folders or changes foreground editor areas.
# - Every result must be representable as finite JSON for transport clients.
import inspect
from itertools import islice
from copy import deepcopy
import math
import sys

import bpy

from .contract import AutomationError, API_VERSION
from .registry import tools


PACKAGE = __package__.split(".")[0]


def addon_classes():
    """Find registered live classes without trusting source-only declarations."""
    seen = set()
    result = []
    # Include UI types for visibility, but never execute their draw callbacks.
    bases = (bpy.types.Operator, bpy.types.Node, bpy.types.NodeTree,
             bpy.types.NodeSocket, bpy.types.Panel, bpy.types.PropertyGroup,
             bpy.types.AddonPreferences, bpy.types.UIList, bpy.types.Menu)
    for name, module in list(sys.modules.items()):
        if not (name == PACKAGE or name.startswith(PACKAGE + ".")) or module is None:
            continue
        for value in vars(module).values():
            if not inspect.isclass(value) or id(value) in seen:
                continue
            if not value.__module__.startswith(PACKAGE + "."):
                continue
            seen.add(id(value))
            kind = next((base.__name__ for base in bases if issubclass(value, base)), None)
            if kind and getattr(value, "is_registered", False):
                result.append((value, kind))
    return sorted(result, key=lambda item: (item[1], item[0].__name__))


def json_value(value, depth=0):
    """Read bounded RNA values, marking data that needs a focused query.

    Mesh vertex buffers are deliberately not expanded in generic state reads.
    Pointer values identify their datablock rather than recursively dumping it.
    """
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else {"unavailable": "nonfinite_number"}
    if isinstance(value, set):
        return sorted(value)
    if isinstance(value, bpy.types.ID):
        return {"name": value.name, "rna_type": value.bl_rna.identifier}
    if depth >= 4:
        return {"truncated": True, "reason": "depth_limit"}
    if isinstance(value, dict):
        return {str(key): json_value(item, depth + 1) for key, item in value.items()}
    if isinstance(value, bpy.types.PropertyGroup):
        return property_values(value, depth + 1)
    if hasattr(value, "__len__") and hasattr(value, "__iter__"):
        total = len(value)
        # Explicit metadata distinguishes a small collection from a partial one.
        items = [json_value(item, depth + 1) for item in islice(value, 128)]
        if total > 128:
            return {"items": items, "total": total, "truncated": True}
        return items
    return {"unavailable": "unsupported_value", "type": type(value).__name__}


def property_values(owner, depth=0, custom_only=False):
    """Read properties individually so one missing context cannot hide the rest."""
    result = {}
    base = set(bpy.types.Node.bl_rna.properties.keys()) if custom_only else set()
    for prop in owner.bl_rna.properties:
        if prop.identifier == "rna_type" or prop.identifier in base:
            continue
        try:
            result[prop.identifier] = json_value(getattr(owner, prop.identifier), depth)
        except Exception as error:
            result[prop.identifier] = {"unavailable": "context_required", "message": str(error)}
    return result


def property_schema(prop):
    """Expose exact RNA constraints for typed edits and operator arguments."""
    result = {"identifier": prop.identifier, "type": prop.type,
              "description": prop.description, "readonly": prop.is_readonly,
              "array_length": getattr(prop, "array_length", 0)}
    # Dynamic enum callbacks sometimes have no static RNA item list.
    # Clients must not mistake that empty list for an unrestricted string.
    if prop.type == "ENUM":
        result["enum"] = [item.identifier for item in prop.enum_items]
        result["enum_flag"] = prop.is_enum_flag
        result["context_dependent"] = not bool(result["enum"])
    if prop.type in {"INT", "FLOAT"}:
        result["minimum"] = prop.hard_min
        result["maximum"] = prop.hard_max
    if prop.type in {"POINTER", "COLLECTION"}:
        result["value_type"] = prop.fixed_type.identifier
    return result


def describe_rna(owner):
    """Return only JSON metadata, never a pointer into Blender memory."""
    rna = owner if hasattr(owner, "properties") and hasattr(owner, "identifier") else owner.bl_rna
    return {"identifier": rna.identifier,
            "properties": [property_schema(prop) for prop in rna.properties if prop.identifier != "rna_type"]}


def settings_owners():
    """Find scene-owned MIMIBlender settings through their declared RNA types."""
    result = {}
    scene = bpy.context.scene
    own_types = {value.__name__ for value, kind in addon_classes() if kind == "PropertyGroup"}
    for prop in scene.bl_rna.properties:
        if prop.identifier.startswith("mimi_") or (prop.type == "POINTER" and prop.fixed_type.identifier in own_types):
            result[prop.identifier] = prop
    return result


def system_capabilities(params):
    """Inventory the loaded build and explicitly state what acceptance excludes."""
    from ..games import _LOGIC_EXPORTER_DICT
    addon = sys.modules[PACKAGE]
    classes = [{"class": value.__name__, "kind": kind,
                "identifier": getattr(value, "bl_idname", ""),
                "module": value.__module__} for value, kind in addon_classes()]
    return {"api_version": API_VERSION, "addon_version": list(addon.bl_info["version"]),
            "blender_version": bpy.app.version_string, "actions": tools(),
            "types": classes, "exporters": sorted(_LOGIC_EXPORTER_DICT),
            "limits": ["Game-process capture is external to this API.",
                       "Successful file generation does not certify in-game rendering.",
                       "Source-only unregistered classes are not callable capabilities."]}


def object_state(obj):
    """Describe editable identity and mesh/rig state without reading full buffers."""
    result = {"name": obj.name, "type": obj.type, "selected": obj.select_get(),
              "location": list(obj.location), "rotation_mode": obj.rotation_mode,
              "scale": list(obj.scale), "matrix_world": [list(row) for row in obj.matrix_world],
              "parent": obj.parent.name if obj.parent else None,
              "collections": [item.name for item in obj.users_collection],
              "hidden_viewport": obj.hide_viewport, "hidden_render": obj.hide_render,
              "custom_properties": {key: json_value(obj[key]) for key in obj.keys()},
              "materials": [slot.material.name if slot.material else None for slot in obj.material_slots],
              "modifiers": [{"name": item.name, "type": item.type} for item in obj.modifiers]}
    if obj.type == "MESH":
        mesh = obj.data
        keys = mesh.shape_keys.key_blocks if mesh.shape_keys else []
        result["mesh"] = {"name": mesh.name, "vertices": len(mesh.vertices),
                          "polygons": len(mesh.polygons), "uv_layers": [layer.name for layer in mesh.uv_layers],
                          "vertex_groups": [group.name for group in obj.vertex_groups],
                          "shape_keys": [{"name": key.name, "value": key.value, "mute": key.mute} for key in keys]}
    elif obj.type == "ARMATURE":
        result["armature"] = {"name": obj.data.name, "bones": len(obj.data.bones)}
    return result


def scene_inspect(params):
    """Name-filtered or paginated state with a total and an explicit next offset."""
    names = params.get("objects")
    objects = sorted(bpy.context.scene.objects, key=lambda obj: obj.name)
    if names is not None:
        # Never silently ignore a mistyped target that later mutations depend on.
        by_name = {obj.name: obj for obj in objects}
        missing = [name for name in names if name not in by_name]
        if missing:
            raise AutomationError("NOT_FOUND", "Scene objects were not found", {"objects": missing})
        objects = [by_name[name] for name in names]
    offset, limit = params.get("offset", 0), params.get("limit", 50)
    scene = bpy.context.scene
    end = min(offset + limit, len(objects))
    return {"scene": scene.name, "filepath": bpy.data.filepath, "mode": bpy.context.mode,
            "active_object": bpy.context.active_object.name if bpy.context.active_object else None,
            "frame": scene.frame_current, "total_objects": len(objects),
            "objects": [object_state(obj) for obj in objects[offset:end]],
            "next_offset": end if end < len(objects) else None,
            "blueprints": sorted(tree.name for tree in bpy.data.node_groups if tree.bl_idname == "MIMIBlueprintTreeType")}


def settings_inspect(params):
    """Return current values as well as property-level edit constraints."""
    scene = bpy.context.scene
    result = {}
    for name, prop in settings_owners().items():
        owner = getattr(scene, name)
        result[name] = {"schema": property_schema(prop), "value": json_value(owner)}
        if isinstance(owner, bpy.types.PropertyGroup):
            result[name]["properties"] = describe_rna(owner)["properties"]
    return result


def rna_describe(params):
    """Restrict discovery to the registered add-on, not arbitrary bpy operators."""
    identifier, kind = params["identifier"], params["kind"]
    if kind == "settings":
        if identifier not in settings_owners():
            raise AutomationError("NOT_FOUND", "Settings owner was not found", {"identifier": identifier})
        owner = getattr(bpy.context.scene, identifier)
        if not isinstance(owner, bpy.types.PropertyGroup):
            return property_schema(settings_owners()[identifier])
        return describe_rna(owner)
    expected = "Operator" if kind == "operator" else "Node"
    found = next((value for value, category in addon_classes()
                  if category == expected and getattr(value, "bl_idname", "") == identifier), None)
    if found is None:
        raise AutomationError("NOT_FOUND", "Registered add-on type was not found", {"identifier": identifier})
    if kind == "operator":
        namespace, opname = identifier.split(".", 1)
        return describe_rna(getattr(getattr(bpy.ops, namespace), opname).get_rna_type())
    return describe_rna(found)


def require_tree(name):
    """Every blueprint action must identify its tree explicitly."""
    tree = bpy.data.node_groups.get(name)
    if tree is None or tree.bl_idname != "MIMIBlueprintTreeType":
        raise AutomationError("NOT_FOUND", "Blueprint was not found", {"tree": name})
    return tree


def blueprint_inspect(params):
    """Expose graph identities and exact socket identifiers, not editor captions."""
    tree = require_tree(params["tree"])
    nodes = sorted(tree.nodes, key=lambda node: node.name)
    offset, limit = params.get("offset", 0), params.get("limit", 50)
    end = min(offset + limit, len(nodes))
    result = []
    for node in nodes[offset:end]:
        # Socket index and identifier disambiguate repeated display names.
        sockets = lambda values: [{"index": index, "identifier": socket.identifier,
                                   "name": socket.name, "type": socket.bl_idname,
                                   "linked": socket.is_linked} for index, socket in enumerate(values)]
        result.append({"name": node.name, "type": node.bl_idname, "label": node.label,
                       "location": list(node.location), "parent": node.parent.name if node.parent else None,
                       "properties": property_values(node, custom_only=True),
                       "inputs": sockets(node.inputs), "outputs": sockets(node.outputs)})
    return {"tree": tree.name, "total_nodes": len(nodes), "nodes": result,
            "next_offset": end if end < len(nodes) else None,
            "links": [{"from_node": link.from_node.name, "from_socket": link.from_socket.identifier,
                       "to_node": link.to_node.name, "to_socket": link.to_socket.identifier} for link in tree.links]}


def read_only(handler):
    """Restore config fields that existing dynamic enum callbacks may refresh.

    Some legacy property getters consult host JSON and update GlobalConfig.
    Inspection may read those values, but must not retain their global changes.
    This wrapper does not monkeypatch getters or hide their real enum metadata.
    """
    def guarded(params):
        from ..common.global_config import GlobalConfig
        types = (str, int, float, bool, dict, list, tuple, type(None))
        # Snapshot configuration data only, not classmethods or service objects.
        # Deepcopy protects mutable containers as well as scalar field values.
        snapshot = {name: deepcopy(value) for name, value in vars(GlobalConfig).items()
                    if not name.startswith("_") and isinstance(value, types)}
        try:
            return handler(params)
        finally:
            for name, value in snapshot.items():
                setattr(GlobalConfig, name, value)
    return guarded


# An explicit handler map prevents an action name from becoming arbitrary getattr.
# Later mutation modules extend the dispatch map through their own public actions.
# Keeping queries separate makes read-only capability checks easy to test.
HANDLERS = {name: read_only(handler) for name, handler in {
    "system.capabilities": system_capabilities, "scene.inspect": scene_inspect,
    "settings.inspect": settings_inspect, "rna.describe": rna_describe,
    "blueprint.inspect": blueprint_inspect,
}.items()}
