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

Design rules:

- No Blender import at all, so the check can also run in plain Python tests and
  can never break the add-on when bpy is missing.
- Never raise: an unreadable or missing folder is reported as a status value.
- Read as little as possible: one scandir per folder, plus one extra level only
  when the first level holds no data at all (to explain what went wrong).
- Scans are capped, so pointing the panel at a huge folder (for example a whole
  drive) cannot freeze the Blender UI.
"""
import os

# The two reverse output formats MMT knows about.
# ssmt_fmt: <DrawIB>/<DataType>.json + the .buf / .ib buffers (current output).
# ib_vb_fmt: <DrawIB>/<DataType>.fmt + the .ib / .vb buffers (legacy output).
SSMT_FMT = "ssmt_fmt"
IB_VB_FMT = "ib_vb_fmt"

# Status values returned by probe_reverse_folder().
# ok           : importable, at least one DrawIB group carries data files
# no_path      : the caller did not provide any folder yet
# missing      : the folder does not exist (or is a file, not a folder)
# unreadable   : the folder exists but could not be listed (permissions)
# no_data      : no reverse data files anywhere near the selected folder
# no_buffer    : data files exist, but not a single buffer file came with them
# too_deep     : the selected folder is a DrawIB folder, not the output root
# too_shallow  : the selected folder holds workspaces, not DrawIB folders
STATUS_OK = "ok"
STATUS_NO_PATH = "no_path"
STATUS_MISSING = "missing"
STATUS_UNREADABLE = "unreadable"
STATUS_NO_DATA = "no_data"
STATUS_NO_BUFFER = "no_buffer"
STATUS_TOO_DEEP = "too_deep"
STATUS_TOO_SHALLOW = "too_shallow"

# File extensions of the data files and of the buffer files they need.
_JSON_EXT = ".json"
_FMT_EXT = ".fmt"
# ssmt_fmt buffers are copied per category plus the index buffer; legacy
# ib_vb_fmt keeps one .ib / .vb pair per data type.
_BUFFER_EXTS = (".buf", ".ib", ".vb")

# Hard limits for one check. The panel runs the check again whenever the
# selected folder changes, so the work per check must stay small even when the
# user points at a folder holding thousands of entries.
_MAX_SCANNED_GROUPS = 200
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
    """Count the data and buffer files directly inside one folder.

    Returns (json_count, fmt_count, buffer_count, data_type_names) where
    data_type_names are the stems of the .json / .fmt files, used only for
    human readable hints.
    """
    json_count = 0
    fmt_count = 0
    buffer_count = 0
    data_type_names = []
    try:
        entries = list(os.scandir(folder_path))
    except OSError:
        # An unreadable child folder simply contributes no file.
        return json_count, fmt_count, buffer_count, data_type_names
    for entry in entries:
        if not entry.is_file():
            continue
        stem, extension = os.path.splitext(entry.name)
        extension = extension.lower()
        if extension == _JSON_EXT:
            json_count += 1
            data_type_names.append(stem)
        elif extension == _FMT_EXT:
            fmt_count += 1
            data_type_names.append(stem)
        elif extension in _BUFFER_EXTS:
            buffer_count += 1
    return json_count, fmt_count, buffer_count, data_type_names


def _sorted_child_directories(folder_path):
    """Return the child folders of folder_path, sorted by name.

    Raises OSError when the folder cannot be listed, so callers can tell a
    permission problem apart from an empty folder.
    """
    children = [entry for entry in os.scandir(folder_path) if entry.is_dir()]
    children.sort(key=lambda entry: entry.name.lower())
    return children


def probe_reverse_folder(folder_path):
    """Inspect one reverse output folder and report whether import can work.

    The result is a plain dict, so callers can cache it and print it as-is:

        status           one of the STATUS_* values above
        folder_path      the normalized path that was checked
        format           SSMT_FMT / IB_VB_FMT / "" when nothing was detected
        group_count      DrawIB folders that carry data files
        data_type_count  .json / .fmt files inside those DrawIB folders
        json_count       .json files found in the DrawIB folders
        fmt_count        .fmt files found in the DrawIB folders
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
        child_directories = _sorted_child_directories(normalized_path)[:_MAX_SCANNED_GROUPS]
    except OSError:
        result["status"] = STATUS_UNREADABLE
        return result

    # One reverse output folder holds one subfolder per DrawIB group, and every
    # group folder holds the data files of the reverse format plus the buffers
    # those data files reference.
    json_total = 0
    fmt_total = 0
    for child in child_directories:
        json_count, fmt_count, buffer_count, _names = _scan_folder_files(child.path)
        if json_count <= 0 and fmt_count <= 0:
            # A folder without data files is not a DrawIB group (a Textures
            # folder, a leftover folder, ...); it must not become a collection.
            continue
        result["group_count"] += 1
        result["group_names"].append(child.name)
        json_total += json_count
        fmt_total += fmt_count
        if buffer_count <= 0:
            # Data without buffers can never be imported: the importer resolves
            # buffer file names inside the same folder.
            result["incomplete_groups"].append(child.name)

    if result["group_count"] > 0:
        result["data_type_count"] = json_total + fmt_total
        result["json_count"] = json_total
        result["fmt_count"] = fmt_total
        if len(result["incomplete_groups"]) == result["group_count"]:
            # Every group holds data files without a single buffer file: the
            # importer resolves buffer names inside the same folder, so no data
            # type of this folder can ever be imported.
            result["status"] = STATUS_NO_BUFFER
            return result
        # A folder normally carries one format only. When both are present the
        # caller decides with the format MMT recorded; ssmt_fmt is the current
        # output format, so it is the safe default here.
        result["format"] = SSMT_FMT if json_total >= fmt_total else IB_VB_FMT
        result["status"] = STATUS_OK
        return result

    # No DrawIB group was found. Explain why, so the user can fix the pick
    # instead of staring at an empty collection.
    own_json, own_fmt, _own_buffers, _own_names = _scan_folder_files(normalized_path)
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
            nested_json, nested_fmt, _buffers, _names = _scan_folder_files(nested.path)
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
