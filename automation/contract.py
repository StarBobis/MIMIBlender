"""Blender-independent validation for the structured automation protocol.

Requests contain data, never Python source. Every action publishes the same
JSON Schema that validates its parameters before any Blender state is touched.
Keep this module free of bpy so clients and ordinary unittest can load it.
"""
# Protocol ownership:
# - This module owns request validation, not Blender scene selection.
# - A transport must forward the action dictionary without interpreting it.
# - A handler must not accept fields that its published schema rejects.
# - The API version is independent of the add-on release version.
# - The request ID belongs to the caller and is only a correlation value.
# - Missing request IDs are legal and appear as null in responses.
# - Missing params mean an empty object, not inferred scene configuration.
# - An unknown action is different from malformed action parameters.
# - Messages are explanatory; stable error codes are the client contract.
# - Error details name the failing field so an agent can repair its request.
# - A failed request never returns a successful result alongside its error.
# - Warnings do not change the envelope shape.
# - JSON values are the only values allowed across the transport boundary.
# - Python instances must not be serialized through repr or pickle.
# - Finite JSON numbers avoid platform-specific NaN interpretation.
# - Booleans are not integers even though Python makes them int subclasses.
# - Numeric limits apply before Blender could clamp an out-of-range value.
# - Unknown parameter keys are rejected instead of ignored.
# - Required keys are checked before recursively validating child values.
# - Enum values preserve exact identifiers instead of case normalization.
# - Strings may contain Unicode scene names but cannot contain a NUL byte.
# - String schemas explicitly decide whether an empty value is meaningful.
# - Array length limits bound the work of one individual action.
# - Nesting limits also cover JSON values with intentionally open schemas.
# - The byte limit measures UTF-8 bytes, not Python character count.
# - JSON string requests and dictionary requests share the same validator.
# - An oversized request is rejected before parsing its complete document.
# - Caller-supplied schema keywords are not part of a request.
# - Schemas below come only from the implementation's action registry.
# - Schema helpers return new dictionaries for every definition.
# - The validator implements only the keywords the registry publishes.
# - Adding a new schema keyword requires corresponding regression tests.
# - Open object schemas are reserved for explicitly typed property payloads.
# - Property payload validation still occurs in the RNA mutation layer.
# - This generic layer never evaluates a string as a Python expression.
# - The error class holds JSON diagnostics rather than Blender references.
# - Blender availability is not required to inspect or test these helpers.
# - Validation failure is ordinary client feedback, not an internal traceback.
# - Unexpected implementation errors are handled by the dispatcher.
# - Transport adapters should not replace these errors with UI operator status.
# - Future job APIs must use the same envelope and version semantics.
# - Validation is not a substitute for source/output path containment checks.
# - Validation is not a substitute for real generated-artifact acceptance.
# - Those workflow-specific checks belong in their action handlers.
import json
import math


API_VERSION = 1
MAX_REQUEST_BYTES = 1024 * 1024
MAX_DEPTH = 16


class AutomationError(Exception):
    """A stable, machine-readable failure rather than a UI-only report."""

    def __init__(self, code, message, details=None):
        # Error details are plain JSON and must not hold Blender datablocks.
        super().__init__(message)
        self.code = code
        self.details = details or {}

    def as_dict(self):
        # Clients should branch on code, not a translated message string.
        return {"code": self.code, "message": str(self), "details": self.details}


def object_schema(properties=None, required=()):
    """Build a strict object schema with no silently ignored arguments."""
    return {"type": "object", "properties": properties or {},
            "required": list(required), "additionalProperties": False}


def string_schema(description="", enum=None):
    """Identifiers and paths must be nonempty; descriptions stay in English."""
    schema = {"type": "string", "minLength": 1, "maxLength": 4096,
              "description": description}
    if enum is not None:
        schema["enum"] = list(enum)
    return schema


def validate(value, schema, path="params", depth=0):
    """Validate our published JSON Schema subset without a new dependency.

    Reject bool-as-integer, nonfinite numbers and excessive nesting explicitly.
    Fail before mutation instead of relying on Blender's coercion or clamping.
    """
    if depth > MAX_DEPTH:
        raise AutomationError("INVALID_ARGUMENT", "Request nesting is too deep", {"path": path})
    if "oneOf" in schema:
        # Union schemas must validate exactly one branch before handler import.
        # Failed branches are observations, not partial mutations or coercions.
        # Each branch retains the same numeric, depth and collection bounds.
        matches = 0
        for choice in schema["oneOf"]:
            try:
                validate(value, choice, path, depth)
                matches += 1
            except AutomationError:
                pass
        if matches != 1:
            raise AutomationError("INVALID_ARGUMENT", "Argument must match exactly one schema branch", {"path": path})
        return
    kind = schema.get("type")
    valid = {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "boolean": isinstance(value, bool),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "null": value is None,
    }
    if kind and not valid.get(kind, False):
        raise AutomationError("INVALID_ARGUMENT", "Argument has the wrong type",
                              {"path": path, "expected": kind})
    if isinstance(value, float) and not math.isfinite(value):
        raise AutomationError("INVALID_ARGUMENT", "Numbers must be finite", {"path": path})
    if "enum" in schema and value not in schema["enum"]:
        raise AutomationError("INVALID_ARGUMENT", "Argument is not an allowed value",
                              {"path": path, "allowed": schema["enum"]})
    if kind == "object":
        # Unknown keys usually indicate an agent typo or a stale tool schema.
        properties = schema.get("properties", {})
        missing = [key for key in schema.get("required", []) if key not in value]
        unknown = [key for key in value if key not in properties]
        if missing or (unknown and schema.get("additionalProperties") is False):
            raise AutomationError("INVALID_ARGUMENT", "Object keys do not match the schema",
                                  {"path": path, "missing": missing, "unknown": unknown})
        for key, item in value.items():
            child = properties.get(key, schema.get("additionalProperties", {}))
            validate(item, child if isinstance(child, dict) else {}, path + "." + key, depth + 1)
    elif kind == "array":
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", 10000):
            raise AutomationError("INVALID_ARGUMENT", "Array length is outside the allowed range", {"path": path})
        for index, item in enumerate(value):
            validate(item, schema.get("items", {}), path + "[" + str(index) + "]", depth + 1)
    elif kind == "string":
        if "\x00" in value or len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", MAX_REQUEST_BYTES):
            raise AutomationError("INVALID_ARGUMENT", "String length or contents are invalid", {"path": path})
    elif kind in {"integer", "number"}:
        if value < schema.get("minimum", -math.inf) or value > schema.get("maximum", math.inf):
            raise AutomationError("INVALID_ARGUMENT", "Number is outside the allowed range", {"path": path})
    elif kind is None:
        # Free-form JSON values still need the same depth and numeric guards.
        if isinstance(value, dict):
            if not all(isinstance(key, str) for key in value):
                raise AutomationError("INVALID_ARGUMENT", "JSON object keys must be strings", {"path": path})
            for key, item in value.items():
                validate(item, {}, path + "." + key, depth + 1)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                validate(item, {}, path + "[" + str(index) + "]", depth + 1)
        elif not isinstance(value, (str, int, float, bool, type(None))):
            raise AutomationError("INVALID_ARGUMENT", "Argument is not a JSON value", {"path": path})


def parse_request(request):
    """Accept either a JSON string or a dictionary, with identical validation."""
    try:
        # Round-tripping rejects arbitrary Python objects passed by local code.
        encoded = request if isinstance(request, str) else json.dumps(request, allow_nan=False)
        if len(encoded.encode("utf-8")) > MAX_REQUEST_BYTES:
            raise AutomationError("REQUEST_TOO_LARGE", "Request exceeds the byte limit")
        value = json.loads(encoded)
    except (ValueError, TypeError, RecursionError) as error:
        raise AutomationError("INVALID_REQUEST", "Request must be finite, valid JSON") from error
    schema = object_schema({
        "api_version": {"type": "integer", "enum": [API_VERSION]},
        "request_id": string_schema("Caller correlation identifier"),
        "action": string_schema("Published automation action"),
        "params": {"type": "object", "additionalProperties": {}},
    }, ("action",))
    validate(value, schema, "request")
    return value


def response(request_id, result=None, error=None, warnings=None):
    """Always return the same envelope, including on validation failures."""
    return {"api_version": API_VERSION, "request_id": request_id,
            "ok": error is None, "result": result if error is None else None,
            "error": error.as_dict() if error else None, "warnings": warnings or []}
