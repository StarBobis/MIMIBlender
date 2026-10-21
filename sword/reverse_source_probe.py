"""Check a reverse output folder before the one-click import consumes it.

The Mod Reverse panel imports from three kinds of folders:

- the folder MMT recorded after the last reverse (Import Mode: Latest);
- one workspace under the Reversed root of the MMT cache folder (Specified);
- any folder the user picks by hand (Custom).

Only the first kind is guaranteed to match what MMT wrote. A hand-picked
folder can point one level too high (the Reversed root holds one subfolder per
workspace, not per DrawIB), one level too deep (a DrawIB folder itself), at an
empty folder, or at a copy that lost its .buf / .ib buffers. Today such a
folder is imported anyway: every data file fails, and the user is left with an
empty collection in the outliner and no explanation.

This module answers one question for the panel and for the import operator:

    "Can this folder be imported, which reverse format does it hold, and how
     many DrawIB groups / data types does it contain?"

Only the current ``ssmt_fmt`` output is imported. The older ``ib_vb_fmt``
layout (a .fmt descriptor per data type) is no longer produced by MMT and its
importer was deleted; such a folder is still recognised and refused with a
clear reason, so a user who picks an old result learns what happened instead of
reading "nothing to import".

Design rules:

- No Blender import at all, so the check can also run in plain Python tests and
  can never break the add-on when bpy is missing.
- Never raise: an unreadable or missing folder is reported as a status value.
- Read as little as possible: one scandir per folder, plus one extra level only
  when the first level holds no data at all (to explain what went wrong).
- Only the deeper diagnostic search is capped. Direct import groups are never
  silently omitted from the verdict or counts.
"""
import os
import json

# The only reverse output format the importer still understands.
# ssmt_fmt: <DrawIB>/<DataType>.json + the .buf / .ib buffers it references.
SSMT_FMT = "ssmt_fmt"

# Status values returned by probe_reverse_folder().
# ok            : importable, at least one DrawIB group carries usable data
# no_path       : the caller did not provide any folder yet
# missing       : the folder does not exist (or is a file, not a folder)
# unreadable    : the folder exists but could not be listed (permissions)
# no_data       : no reverse data files anywhere near the selected folder
# no_buffer     : data files exist, but not a single one has complete buffers
# too_deep      : the selected folder is a DrawIB folder, not the output root
# too_shallow   : the selected folder holds workspaces, not DrawIB folders
# legacy_format : an old ib_vb_fmt result; the importer no longer supports it
STATUS_OK = "ok"
STATUS_NO_PATH = "no_path"
STATUS_MISSING = "missing"
STATUS_UNREADABLE = "unreadable"
STATUS_NO_DATA = "no_data"
STATUS_NO_BUFFER = "no_buffer"
STATUS_TOO_DEEP = "too_deep"
STATUS_TOO_SHALLOW = "too_shallow"
STATUS_LEGACY_FORMAT = "legacy_format"

# File extensions of the data files. Only .json is imported now; .fmt is still
# scanned so an old reverse output can be reported as legacy instead of empty.
_JSON_EXT = ".json"
_LEGACY_FMT_EXT = ".fmt"

# Hard limits for one check. The panel runs the check again whenever the
# selected folder changes, so the work per check must stay small even when the
# user points at a folder holding thousands of entries.
_MAX_SCANNED_NESTED_GROUPS = 200
# How many workspace names the "too shallow" hint lists (the rest is counted).
MAX_SUGGESTED_FOLDERS = 3


def normalize_folder_path(raw_path):
    """Turn a typed or pasted folder path into a plain filesystem path.

    Explorer's "Copy as path" wraps the path in double quotes, and a manual
    paste often keeps a trailing quote or space, which made the old check
    report "folder does not exist" for a path that is perfectly fine.
    """
    text = str(raw_path or "").strip()
    # Strip every layer of quotes, e.g. '"D:\\out"' or "'D:\\out'".
    while len(text) >= 2 and text[0] in ("'", '"') and text[-1] in ("'", '"'):
        text = text[1:-1].strip()
    if not text:
        return ""
    # normpath also converts forward slashes and removes a trailing separator.
    return os.path.normpath(text)


def _scan_folder_files(folder_path):
    """Count the data descriptors of one folder without loading any of them.

    Scandir and entry stat calls can both fail when a folder disappears or loses
    permissions. Keep the context manager open while reading entry metadata.
    """
    json_count = 0
    fmt_count = 0
    names = []
    try:
        with os.scandir(folder_path) as entries:
            for entry in entries:
                if not entry.is_file():
                    continue
                stem, extension = os.path.splitext(entry.name)
                extension = extension.lower()
                if extension == _JSON_EXT:
                    json_count += 1
                    names.append(stem)
                elif extension == _LEGACY_FMT_EXT:
                    fmt_count += 1
                    names.append(stem)
    except OSError:
        # A disappearing or unreadable child contributes no candidates.
        return 0, 0, []
    return json_count, fmt_count, names


def _usable_json_candidates(folder_path):
    """Count Json files whose declared buffers really exist and are nonempty.

    This is a preflight, not a promise about vertex layout or rendered quality.
    A Json must carry nonempty IB and category tables, and every referenced
    buffer file must exist and hold data. No buffer payload is loaded.
    """
    usable = 0
    try:
        with os.scandir(folder_path) as entries:
            files = {entry.name: entry.path for entry in entries if entry.is_file()}
        for name, path in files.items():
            if not name.lower().endswith(_JSON_EXT):
                continue
            try:
                with open(path, encoding='utf-8-sig') as handle:
                    data = json.load(handle)
                if not isinstance(data, dict):
                    continue
                indices = data.get('IndexBufferList', [])
                categories = data.get('CategoryBufferList', [])
                if not isinstance(indices, list) or not indices:
                    continue
                if not isinstance(categories, list) or not categories:
                    continue
                references = indices + categories
                valid = all(
                    isinstance(item, dict) and isinstance(item.get('FileName'), str)
                    and bool(item['FileName'])
                    and os.path.isfile(os.path.join(folder_path, item['FileName']))
                    and os.path.getsize(os.path.join(folder_path, item['FileName'])) > 0
                    for item in references
                )
                if valid:
                    usable += 1
            except (OSError, ValueError, TypeError):
                # One malformed descriptor must not hide valid siblings.
                continue
    except OSError:
        return 0
    return usable


def _sorted_child_directories(folder_path):
    """Return the child folders of folder_path, sorted by name.

    Raises OSError when the folder cannot be listed, so callers can tell a
    permission problem apart from an empty folder.
    """
    with os.scandir(folder_path) as entries:
        children = [entry for entry in entries if entry.is_dir()]
    children.sort(key=lambda entry: entry.name.lower())
    return children


def probe_reverse_folder(folder_path):
    """Inspect one reverse output folder and report whether import can work.

    The result is a plain dict, so callers can cache it and print it as-is:

        status           one of the STATUS_* values above
        folder_path      the normalized path that was checked
        format           SSMT_FMT / "" when nothing importable was detected
        group_count      DrawIB folders that carry usable data files
        data_type_count  usable .json files inside those DrawIB folders
        json_count       .json files found in the DrawIB folders
        fmt_count        .fmt files found in the DrawIB folders (legacy output)
        incomplete_groups DrawIB folder names that hold data but no buffers
        suggested_folders workspace names worth selecting (too_shallow only)
        suggested_total  how many workspaces hold data (too_shallow only)
        group_names      DrawIB folder names (used by hints and tests)
    """
    normalized_path = normalize_folder_path(folder_path)
    result = {
        "status": STATUS_NO_PATH,
        "folder_path": normalized_path,
        "format": "",
        "group_count": 0,
        "data_type_count": 0,
        "json_count": 0,
        "fmt_count": 0,
        "incomplete_groups": [],
        "suggested_folders": [],
        "suggested_total": 0,
        "group_names": [],
    }
    if not normalized_path:
        return result
    if not os.path.isdir(normalized_path):
        result["status"] = STATUS_MISSING
        return result

    try:
        child_directories = _sorted_child_directories(normalized_path)
    except OSError:
        result["status"] = STATUS_UNREADABLE
        return result

    # Inspect every direct group: silently truncating after 200 directories
    # could refuse a valid folder or show counts different from the import.
    # Only the deeper diagnostic search is capped; it never controls import.
    groups = 0
    data_types = 0
    incomplete = []
    json_total = 0
    fmt_total = 0
    for child in child_directories:
        json_count, fmt_count, _names = _scan_folder_files(child.path)
        json_total += json_count
        fmt_total += fmt_count
        if json_count <= 0:
            continue
        usable = _usable_json_candidates(child.path)
        data_types += usable
        if usable:
            groups += 1
            if child.name not in result["group_names"]:
                result["group_names"].append(child.name)
        if usable < json_count:
            incomplete.append(child.name)

    result["json_count"] = json_total
    result["fmt_count"] = fmt_total
    if json_total:
        # The current format describes its buffers inside the Json, so a copy
        # that lost them is reported instead of being imported as empty meshes.
        result["format"] = SSMT_FMT
        result["group_count"] = groups
        result["data_type_count"] = data_types
        result["incomplete_groups"] = incomplete
        result["status"] = STATUS_OK if data_types else STATUS_NO_BUFFER
        return result
    if fmt_total:
        # Old ib_vb_fmt output. The importer no longer handles it, but the panel
        # must say why instead of claiming there is nothing to import.
        result["status"] = STATUS_LEGACY_FORMAT
        return result

    # No DrawIB group was found. Explain why, so the user can fix the pick
    # instead of staring at an empty collection.
    own_json, own_fmt, _own_names = _scan_folder_files(normalized_path)
    if own_json > 0 or own_fmt > 0:
        # The selected folder itself holds the data files: it is one DrawIB
        # folder, so its parent folder is the reverse output root.
        result["status"] = STATUS_TOO_DEEP
        return result

    # Look one level deeper: the user may have picked a folder that holds one
    # subfolder per reverse workspace (the Reversed root behaves like this).
    scanned_nested = 0
    suggested = []
    for child in child_directories:
        if scanned_nested >= _MAX_SCANNED_NESTED_GROUPS:
            break
        try:
            nested_directories = _sorted_child_directories(child.path)
        except OSError:
            continue
        for nested in nested_directories:
            if scanned_nested >= _MAX_SCANNED_NESTED_GROUPS:
                break
            scanned_nested += 1
            nested_json, nested_fmt, _names = _scan_folder_files(nested.path)
            if nested_json > 0 or nested_fmt > 0:
                suggested.append(child.name)
                break

    if suggested:
        result["status"] = STATUS_TOO_SHALLOW
        result["suggested_folders"] = suggested[:MAX_SUGGESTED_FOLDERS]
        result["suggested_total"] = len(suggested)
        return result

    result["status"] = STATUS_NO_DATA
    return result
