"""Bounded artifact acceptance for newly generated Mod directories.

This audit verifies actual files, INI section/conditional framing and resource
filename closure. It does not execute a game, certify shaders or prove runtime
resource bindings. External symbolic APIs remain a separate dependency layer.
"""
# Artifact rules:
# - Audit only the explicit new output root, never installed user Mods folders.
# - INI filenames resolve relative to their owning INI, matching 3Dmigoto.
# - A filename cannot leave the generated directory through .. or a symlink.
# - Existing files are hashed; operator success strings are not evidence.
# - Empty/missing INIs cannot count as successful generation.
# - Duplicate section identities within an INI are actionable failures.
# - Conditional blocks must terminate without unmatched endif statements.
# - Comments and the top-level namespace declaration are not section entries.
# - External namespaced Resource references are reported, not fabricated as files.
# - The result explicitly labels its offline artifact-only acceptance scope.
# - No audit modifies, renames or deletes a generated file.
# - Failed output directories stay available for user/developer inspection.
# - File and INI population bounds prevent unbounded UI work.
# - SHA256 evidence is per file, not a claim of publisher authenticity.
import hashlib
from pathlib import Path
import re

from .contract import AutomationError
from .paths import absolute_path, contained


MAX_INI_BYTES = 8 * 1024 * 1024


def file_hash(path):
    """Hash a file in bounded chunks rather than loading an entire vertex buffer."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_ini(path, root):
    """Read one inert INI and validate its framing and declared filename closure."""
    if path.stat().st_size > MAX_INI_BYTES:
        raise AutomationError("ARTIFACT_TOO_LARGE", "Generated INI exceeds its byte bound")
    with path.open("rb") as handle:
        encoded = handle.read(MAX_INI_BYTES + 1)
    if len(encoded) > MAX_INI_BYTES:
        raise AutomationError("ARTIFACT_TOO_LARGE", "Generated INI grew beyond its byte bound")
    try:
        text = encoded.decode("utf-8-sig")
    except UnicodeError as error:
        raise AutomationError("INVALID_INI", "Generated INI is not valid UTF-8") from error
    sections, references, external, errors = [], [], [], []  # Keep local files separate from external symbolic APIs.
    seen = set()  # Section identities are case-insensitive for duplicate detection.
    stack = []  # Native conditional nesting must terminate in the same section.
    current = None  # Top-level namespace is allowed before the first section.
    for number, raw in enumerate(text.splitlines(), 1):  # Preserve line numbers for client repair diagnostics.
        line = raw.strip()  # Indented control-flow lines have the same meaning.
        if not line or line.startswith((";", "#")):  # Comments are not executable INI entries.
            continue  # Ignore whitespace-only or documentation lines.
        if line.startswith("[") and line.endswith("]"):  # Read actual section framing, not copied source labels.
            current = line[1:-1].strip()  # Retain the section name for offline evidence.
            if not current or current.casefold() in seen:  # Empty or duplicate identities are invalid artifacts.
                errors.append({"code": "DUPLICATE_OR_EMPTY_SECTION", "line": number, "section": current})
            seen.add(current.casefold())
            sections.append(current)
            if stack:
                errors.append({"code": "UNTERMINATED_CONDITIONAL", "line": number})
                stack.clear()
            continue
        value = line.split(";", 1)[0].strip()
        if current is None and not value.lower().startswith("namespace"):
            errors.append({"code": "ENTRY_OUTSIDE_SECTION", "line": number})
        if value.lower().startswith("if "):
            stack.append(number)
        elif value.lower() == "endif":
            if not stack:
                errors.append({"code": "UNMATCHED_ENDIF", "line": number})
            else:
                stack.pop()
        if "=" not in value:
            continue
        key, item = (part.strip() for part in value.split("=", 1))
        if key.casefold() == "filename":
            relative = item.strip('"')
            target = (path.parent / relative.replace("\\", "/")).resolve()
            if not contained(target, root):
                errors.append({"code": "OUTPUT_PATH_ESCAPE", "line": number, "filename": relative})
            elif not target.is_file():
                errors.append({"code": "MISSING_RESOURCE_FILE", "line": number, "filename": relative})
            else:
                references.append(str(target.relative_to(root)))
        # A namespaced symbolic API is not a local artifact filename.
        for match in re.findall(r"\bResource\\[^\s;]+", item):
            external.append(match)
    if stack:
        errors.append({"code": "UNTERMINATED_CONDITIONAL", "lines": stack})
    if not sections:
        errors.append({"code": "EMPTY_INI"})
    return {"path": str(path.relative_to(root)), "sections": sections,
            "resource_files": sorted(set(references)), "external_symbols": sorted(set(external)), "errors": errors}


def audit_directory(output):
    """Require real generated INIs/resources and return reproducible file evidence."""
    root = absolute_path(output, "directory")
    paths = sorted(path for path in root.rglob("*") if path.is_file())
    if len(paths) > 10000:
        raise AutomationError("ARTIFACT_TOO_LARGE", "Generated directory exceeds the file bound")
    escaped = [str(path) for path in paths if not contained(path.resolve(), root)]
    if escaped:
        raise AutomationError("OUTPUT_PATH_ESCAPE", "Output contains files outside its declared root", {"paths": escaped})
    inis = [inspect_ini(path, root) for path in paths if path.suffix.casefold() == ".ini"]
    if not inis or any(item["errors"] for item in inis):
        raise AutomationError("INVALID_ARTIFACTS", "Generated Mod failed INI/resource-file acceptance", {"inis": inis})
    files = [{"path": str(path.relative_to(root)), "bytes": path.stat().st_size, "sha256": file_hash(path)} for path in paths]
    return {"output": str(root), "files": files, "inis": inis,
            "scope": "offline_ini_framing_and_resource_file_closure",
            "in_game_verified": False}
