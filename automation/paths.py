"""Explicit filesystem boundaries for AI workspace sessions.

The API accepts absolute paths, resolves links before containment checks, and
never derives a write destination from an untrusted source buffer filename.
Session directories are exclusive new children of the caller's working root.
"""
# Path invariants:
# - Relative paths and Blender // paths are not implicit automation targets.
# - The caller must name a source root and a separate working root.
# - Resolved paths, not raw string prefixes, determine containment.
# - Existing source buffers and JSON documents are opened read-only.
# - Workspace descriptions have a bounded JSON byte size.
# - Missing source files produce explicit machine-readable failures.
# - Buffer references may move within the declared source root, not escape it.
# - Symlinks that leave that source root are rejected as path escapes.
# - No failed session is removed with a recursive filesystem delete.
# - Session allocation never overwrites an existing directory.
# - A working directory cannot be placed inside the source resource tree.
# - An output directory must be a new path outside the source tree as well.
# - Case and separator handling comes from native pathlib resolution.
# - Source-root identity is retained in persisted workflow metadata.
# - Extension labels do not substitute for JSON content validation.
# - Metadata parsing does not execute source scripts or load a game process.
import json
from pathlib import Path

from .contract import AutomationError


MAX_METADATA_BYTES = 4 * 1024 * 1024


def absolute_path(value, kind=None):
    """Resolve an explicit native absolute path and validate its current type."""
    path = Path(value)  # A caller string is a filesystem path, never an expression.
    if not path.is_absolute():  # Avoid implicit dependence on a different session's cwd.
        raise AutomationError("ABSOLUTE_PATH_REQUIRED", "Automation paths must be absolute", {"path": value})
    path = path.resolve()
    if kind == "directory" and not path.is_dir():
        raise AutomationError("NOT_FOUND", "Directory was not found", {"path": str(path)})
    if kind == "file" and not path.is_file():
        raise AutomationError("NOT_FOUND", "File was not found", {"path": str(path)})
    return path


def contained(path, root):
    """Use canonical ancestor relationships instead of ambiguous string starts."""
    return path == root or root in path.parents


def source_reference(directory, filename, root):
    """Resolve one source-declared dependency without letting it leave the root."""
    if not isinstance(filename, str) or not filename or "\x00" in filename:
        raise AutomationError("INVALID_SOURCE", "Source dependency filename is invalid")
    path = (directory / filename).resolve()
    if not contained(path, root):
        raise AutomationError("SOURCE_PATH_ESCAPE", "Source dependency leaves its declared root", {"path": str(path)})
    if not path.is_file():
        raise AutomationError("MISSING_SOURCE_FILE", "Source dependency was not found", {"path": str(path)})
    return path


def read_metadata(path):
    """Read an inert bounded JSON object, keeping malformed files non-successful."""
    if path.stat().st_size > MAX_METADATA_BYTES:
        raise AutomationError("SOURCE_TOO_LARGE", "Workspace JSON exceeds the metadata byte bound", {"path": str(path)})
    try:
        with path.open("rb") as handle:
            encoded = handle.read(MAX_METADATA_BYTES + 1)
        if len(encoded) > MAX_METADATA_BYTES:
            raise AutomationError("SOURCE_TOO_LARGE", "Workspace JSON grew beyond the metadata byte bound")
        result = json.loads(encoded.decode("utf-8-sig"))
    except (ValueError, OSError) as error:
        raise AutomationError("INVALID_SOURCE", "Source JSON could not be read", {"path": str(path)}) from error
    if not isinstance(result, dict):
        raise AutomationError("INVALID_SOURCE", "Submesh metadata must be a JSON object", {"path": str(path)})
    return result


def safe_workspace_name(value):
    """Require one safe filename stem for later native INI generation."""
    if not isinstance(value, str) or not value or value in {".", ".."} or value != value.strip():
        raise AutomationError("INVALID_WORKSPACE_NAME", "Workspace identity must be one nonempty filename stem")
    if any(char in '<>:"/\\|?*' or ord(char) < 32 for char in value) or value.endswith("."):
        raise AutomationError("INVALID_WORKSPACE_NAME", "Workspace identity contains unsafe filename characters")
    reserved = {"CON", "PRN", "AUX", "NUL"} | {"COM" + str(i) for i in range(1, 10)} | {"LPT" + str(i) for i in range(1, 10)}
    if value.split(".")[0].upper() in reserved:
        raise AutomationError("INVALID_WORKSPACE_NAME", "Workspace identity is a reserved Windows filename")
    return value


def create_session_directory(work_root, source_root, identifier):
    """Create one exclusive session folder without writing into source assets."""
    root = absolute_path(work_root)
    if contained(root, source_root):
        raise AutomationError("SOURCE_WRITE_FORBIDDEN", "Working root cannot be inside the source workspace")
    root.mkdir(parents=True, exist_ok=True)
    path = root / identifier
    path.mkdir(exist_ok=False)
    return path
