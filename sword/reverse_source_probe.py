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
- Only the deeper diagnostic search is capped. Direct import groups are never
  silently omitted from the verdict or counts.
"""
import os
import json

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
    """Count markers without mistaking folders for data files.

    Scandir and entry stat calls can both fail when a folder disappears or loses
    permissions. Keep the context manager open while reading entry metadata.
    """
    json_count = fmt_count = buffer_count = 0
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
                elif extension == _FMT_EXT:
                    fmt_count += 1
                    names.append(stem)
                elif extension in _BUFFER_EXTS:
                    buffer_count += 1
    except OSError:
        # A disappearing or unreadable child contributes no candidates.
        return 0, 0, 0, []
    return json_count, fmt_count, buffer_count, names


def _usable_candidates(folder_path, extension):
    """Check the actual buffer references, not merely any sibling buffer.

    This is a preflight, not a promise about vertex layout or rendered quality.
    JSON must carry nonempty IB/category tables with existing nonempty files.
    Legacy FMT follows its prefix and the importer-compatible VB suffix lookup.
    No buffer payload is loaded during the check.
    """
    usable = 0
    try:
        with os.scandir(folder_path) as entries:
            files = {entry.name: entry.path for entry in entries if entry.is_file()}
        for name, path in files.items():
            if not name.lower().endswith(extension):
                continue
            try:
                if extension == _JSON_EXT:
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
                else:
                    # Explicit prefixes can differ from the FMT filename.
                    prefix = os.path.splitext(name)[0]
                    with open(path, encoding='utf-8-sig') as handle:
                        for line in handle:
                            key, separator, value = line.partition(':')
                            if separator and key.strip() == 'prefix' and value.strip():
                                prefix = value.strip()
                    ib = os.path.join(folder_path, prefix + '.ib')
                    vb = [file_path for file_name, file_path in files.items()
                          if file_name.lower().startswith((prefix + '.vb').lower())]
                    valid = os.path.isfile(ib) and os.path.getsize(ib) > 0
                    valid = valid and any(os.path.getsize(file_path) > 0 for file_path in vb)
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
        "format_stats": {},
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
    stats = {SSMT_FMT: {'groups': 0, 'types': 0, 'incomplete': []},
             IB_VB_FMT: {'groups': 0, 'types': 0, 'incomplete': []}}
    raw_json = raw_fmt = 0
    for child in child_directories:
        json_count, fmt_count, _buffers, _names = _scan_folder_files(child.path)
        raw_json += json_count
        raw_fmt += fmt_count
        for output_format, extension, count in (
                (SSMT_FMT, _JSON_EXT, json_count), (IB_VB_FMT, _FMT_EXT, fmt_count)):
            if count <= 0:
                continue
            usable = _usable_candidates(child.path, extension)
            stats[output_format]['types'] += usable
            if usable:
                stats[output_format]['groups'] += 1
                if child.name not in result['group_names']:
                    result['group_names'].append(child.name)
            if usable < count:
                stats[output_format]['incomplete'].append(child.name)

    result['json_count'] = raw_json
    result['fmt_count'] = raw_fmt
    result['format_stats'] = stats
    if raw_json or raw_fmt:
        # Prefer current SSMT only when it has usable descriptors. A stale global
        # format marker must never override the actual selected folder.
        output_format = SSMT_FMT if stats[SSMT_FMT]['types'] else IB_VB_FMT
        selected = stats[output_format]
        result['format'] = output_format
        result['group_count'] = selected['groups']
        result['data_type_count'] = selected['types']
        result['incomplete_groups'] = selected['incomplete']
        result['status'] = STATUS_OK if selected['types'] else STATUS_NO_BUFFER
        if not selected['types']:
            result['incomplete_groups'] = sorted(set(
                stats[SSMT_FMT]['incomplete'] + stats[IB_VB_FMT]['incomplete']))
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
