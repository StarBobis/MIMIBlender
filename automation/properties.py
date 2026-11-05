"""Typed RNA edits for explicit automation targets.

Read the real property's constraints instead of guessing accepted enum values.
No caller string is evaluated as code, an expression, or an attribute path.
Graph edits use these helpers only on a newly staged tree. Direct settings edits
preflight all scalar assignments and retain a rollback snapshot of the owner.
"""
# Property contract:
# - Unknown field names are errors rather than silently ignored typos.
# - Standard node sockets and links are edited by graph actions, not setattr.
# - Read-only fields cannot be assigned through the generic edit endpoint.
# - Integer RNA rejects boolean JSON values explicitly.
# - Float RNA accepts finite integer and floating-point JSON numbers.
# - Numeric hard limits are validated before Blender can clamp them.
# - Numeric arrays must have the declared RNA length.
# - String values remain literal data, never Python expressions.
# - Ordinary enums use their current exact registered identifiers.
# - Dynamic enums are resolved from the add-on's deferred property declaration.
# - Unresolved dynamic enum metadata causes an error, not unrestricted input.
# - Enum flags are JSON arrays and become sets only at the bpy boundary.
# - Datablock pointer values use exact names and declared RNA target types.
# - Null pointers are explicit; a missing name cannot silently become null.
# - PropertyGroup pointers use nested value dictionaries.
# - Collections use complete replacement row lists on staged graph nodes.
# - Collection rows are validated through their actual allocated RNA owner.
# - Object List replacement preserves the node's mirrored row/socket contract.
# - No collection helper removes a user object or a physical file.
# - A direct settings update does not support collection replacement.
# - Settings callbacks can update sibling fields, so the snapshot includes them.
# - A failed settings assignment restores all captured writable scalar fields.
# - A successful result reports actual post-callback values.
# - Sanitization by an existing callback is not claimed as literal equality.
# - Custom source binding fields are data but still need graph validation.
# - Numeric precision is Blender's native precision, not arbitrary decimal JSON.
# - Scene settings are in-memory changes and are never implicitly saved.
# - Pointer references do not authorize editing their referenced datablocks.
# - Recursive custom groups must be rejected by the blueprint validation layer.
# - Reusable helpers must not choose an active node, object, or editor area.
# - Their caller owns transaction boundaries and disposable staged datablocks.
import bpy

from .contract import AutomationError, validate
from .inspection import addon_classes, json_value


# Only these standard presentation fields may accompany custom node settings.
# Node identity, links, ownership and parent frames have separate graph fields.
# This avoids accidentally editing internal bpy metadata with an open JSON map.
NODE_PRESENTATION = {"label", "location", "width", "hide", "mute", "color", "use_custom_color"}


def enum_identifiers(owner, name, prop):
    """Resolve static or add-on-declared dynamic enum values in current context."""
    values = [item.identifier for item in prop.enum_items]
    if values:
        return values
    # Blender's static RNA list is empty for callback-based enums.
    # Inspect the registered Python declaration rather than hardcoding choices.
    cls = next((value for value, kind in addon_classes() if value.__name__ == owner.bl_rna.identifier), type(owner))
    for base in cls.__mro__:
        declaration = getattr(base, "__annotations__", {}).get(name)
        keywords = getattr(declaration, "keywords", {})
        items = keywords.get("items")
        if items is not None:
            entries = items(owner, bpy.context) if callable(items) else items
            return [entry[0] for entry in entries if entry is not None and entry[0]]
    raise AutomationError("CONTEXT_REQUIRED", "Dynamic enum values could not be resolved", {"property": name})


def datablock_pointer(value, prop):
    """Find an exact named ID of the property's declared RNA type."""
    if value is None:
        return None
    validate(value, {"type": "string", "minLength": 1})
    # No arbitrary bpy.data attribute is selected from client input.
    # A custom NodeTree subclass is accepted through its RNA ancestry.
    containers = (bpy.data.objects, bpy.data.images, bpy.data.materials,
                  bpy.data.node_groups, bpy.data.collections, bpy.data.actions)
    expected = prop.fixed_type.identifier
    for container in containers:
        item = container.get(value)
        if item is None:
            continue
        rna = item.bl_rna
        while rna is not None:
            if rna.identifier == expected:
                return item
            rna = rna.base
    raise AutomationError("NOT_FOUND", "Named datablock has no matching RNA target type",
                          {"name": value, "expected_type": expected})


def prepared_value(owner, name, value, allowed=None):
    """Validate one writable scalar/ID-pointer assignment without mutating it."""
    prop = owner.bl_rna.properties.get(name)
    if prop is None or name == "rna_type" or (allowed is not None and name not in allowed):
        raise AutomationError("INVALID_PROPERTY", "Property is not editable on this target", {"property": name})
    if prop.is_readonly:
        raise AutomationError("READ_ONLY_PROPERTY", "Property is read-only", {"property": name})
    kinds = {"BOOLEAN": "boolean", "INT": "integer", "FLOAT": "number", "STRING": "string"}
    if prop.type in kinds:
        schema = {"type": kinds[prop.type]}
        if prop.type in {"INT", "FLOAT"}:
            schema.update(minimum=prop.hard_min, maximum=prop.hard_max)
        if getattr(prop, "array_length", 0):
            length = prop.array_length
            schema = {"type": "array", "items": schema, "minItems": length, "maxItems": length}
        validate(value, schema, "properties." + name)
        return tuple(value) if isinstance(value, list) else value
    if prop.type == "ENUM":
        values = enum_identifiers(owner, name, prop)
        schema = {"type": "string", "enum": values}
        if prop.is_enum_flag:
            validate(value, {"type": "array", "items": schema}, "properties." + name)
            return set(value)
        validate(value, schema, "properties." + name)
        return value
    if prop.type == "POINTER" and issubclass(getattr(bpy.types, prop.fixed_type.identifier, bpy.types.ID), bpy.types.ID):
        return datablock_pointer(value, prop)
    raise AutomationError("UNSUPPORTED_PROPERTY", "This property needs a dedicated structured edit",
                          {"property": name, "type": prop.type})


def scalar_snapshot(owner):
    """Capture writable scalars, including sibling values changed by callbacks."""
    result = {}  # Retain the pre-edit values, not serialized display strings.
    for prop in owner.bl_rna.properties:  # Include callback-owned sibling fields.
        if prop.is_readonly or prop.type not in {"BOOLEAN", "INT", "FLOAT", "STRING", "ENUM"}:
            continue  # Native ownership fields must not be restored through setattr.
        try:
            value = getattr(owner, prop.identifier)  # Observe the current native value.
            result[prop.identifier] = tuple(value) if getattr(prop, "array_length", 0) else value  # Copy mutable numeric arrays.
        except Exception:  # A context-dependent unrelated field can be unavailable.
            # Missing dynamic-enum context is exposed by the assignment path.
            # It must not prevent changing unrelated, fully typed settings.
            continue
    return result


def restore_scalars(owner, snapshot):
    """Best-effort rollback with explicit diagnostics instead of silent loss."""
    errors = []
    for name, value in snapshot.items():
        try:
            current = getattr(owner, name)
            prop = owner.bl_rna.properties[name]
            if getattr(prop, "array_length", 0):
                current = tuple(current)
            # Unchanged dynamic enum values can be unavailable for assignment.
            # Do not turn an unrelated rollback into a spurious enum failure.
            if current != value:
                setattr(owner, name, value)
        except Exception as error:
            errors.append({"property": name, "message": str(error)})
    if errors:
        raise AutomationError("ROLLBACK_FAILED", "Settings rollback could not restore every field", {"errors": errors})


def set_node_properties(node, values):
    """Set custom properties on a staged node, preserving native row callbacks."""
    base = set(bpy.types.Node.bl_rna.properties.keys())
    allowed = (set(node.bl_rna.properties.keys()) - base) | NODE_PRESENTATION
    # Property callbacks are intentionally retained; they own display and IDs.
    # The node's caller rolls back the entire staged graph if a field fails.
    for name, value in values.items():
        prop = node.bl_rna.properties.get(name)
        if name not in allowed or prop is None:
            raise AutomationError("INVALID_PROPERTY", "Node property is not editable", {"property": name})
        if prop.type == "COLLECTION":
            replace_collection(node, name, value)
        else:
            setattr(node, name, prepared_value(node, name, value, allowed))


def replace_collection(owner, name, rows):
    """Replace rows only on a disposable staged graph, never a source object."""
    validate(rows, {"type": "array", "items": {"type": "object"}, "maxItems": 512}, "properties." + name)
    collection = getattr(owner, name)
    if not hasattr(collection, "add") or not hasattr(collection, "clear"):
        raise AutomationError("UNSUPPORTED_PROPERTY", "Collection is not an editable PropertyGroup list", {"property": name})
    object_list = owner.bl_idname == "MIMINode_Object_List" and name == "object_items"
    if object_list:
        # The existing helpers own the paired output socket for every row.
        # Removing only rows would leave stale object-flow sockets in the graph.
        from ..blueprint.blueprint_node_object_list import _append_object_list_item, _remove_object_list_item
        while len(collection):
            _remove_object_list_item(owner, len(collection) - 1)
    else:
        collection.clear()
    for row in rows:
        item = _append_object_list_item(owner, row.get("object_name", "")) if object_list else collection.add()
        for field, value in row.items():
            setattr(item, field, prepared_value(item, field, value))


def settings_update(params):
    """Preflight an explicit scalar setting batch and rollback failed callbacks."""
    from .inspection import settings_owners
    from .presentation import desktop_window, redraw
    window = desktop_window()
    name = params["owner"]
    if name not in settings_owners():
        raise AutomationError("NOT_FOUND", "Scene settings owner was not found", {"owner": name})
    scene = bpy.context.scene
    owner = getattr(scene, name)
    # A root scalar uses the key value; PropertyGroups use their field names.
    # Never interpret a dotted client string as an arbitrary attribute path.
    if not isinstance(owner, bpy.types.PropertyGroup):
        if set(params["values"]) != {"value"}:
            raise AutomationError("INVALID_ARGUMENT", "Scalar scene settings require exactly the value field")
        value = prepared_value(scene, name, params["values"]["value"], set(settings_owners()))
        previous = getattr(scene, name)
        try:
            setattr(scene, name, value)
        except Exception as error:
            setattr(scene, name, previous)
            raise AutomationError("ASSIGNMENT_FAILED", str(error), {"property": name}) from error
        redraw(window)
        return {"owner": name, "value": json_value(getattr(scene, name))}
    prepared = {field: prepared_value(owner, field, value) for field, value in params["values"].items()}
    snapshot = scalar_snapshot(owner)
    try:
        for field, value in prepared.items():
            setattr(owner, field, value)
    except Exception as error:
        restore_scalars(owner, snapshot)
        raise AutomationError("ASSIGNMENT_FAILED", str(error)) from error
    redraw(window)
    return {"owner": name, "values": {field: json_value(getattr(owner, field)) for field in prepared}, "persisted": False}
