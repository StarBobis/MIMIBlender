"""Bounded, file-stamped thumbnails for the global Hash replacement node."""
import os
from collections import OrderedDict

import bpy
import bpy.utils.previews

# Preview collections do not add Image datablocks to the user's blend file.
# Keep only a small working set, since a workspace can contain many textures.
_collection = None
_stamps = OrderedDict()
_LIMIT = 128


def clear_previews():
    """Release thumbnails on refresh and addon shutdown."""
    global _collection
    if _collection is not None:
        bpy.utils.previews.remove(_collection)
        _collection = None
    _stamps.clear()


def texture_icon(file_path):
    """Return a thumbnail icon, or zero for missing/unsupported images."""
    global _collection
    if not file_path:
        return 0
    path = os.path.normcase(os.path.abspath(bpy.path.abspath(file_path)))
    try:
        stat = os.stat(path)
        stamp = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        return 0

    if _collection is None:
        _collection = bpy.utils.previews.new()
    if path in _stamps and _stamps[path] == stamp:
        # Reuse icons between redraws without re-reading the image contents.
        # Failed loads are cached too, avoiding repeated decoder errors.
        _stamps.move_to_end(path)
        preview = _collection.get(path)
        return preview.icon_id if preview else 0

    if path in _collection:
        del _collection[path]
    _stamps[path] = stamp
    _stamps.move_to_end(path)
    while len(_stamps) > _LIMIT:
        oldest, _ = _stamps.popitem(last=False)
        if oldest in _collection:
            del _collection[oldest]
    try:
        return _collection.load(path, path, 'IMAGE', force_reload=True).icon_id
    except Exception as error:
        print("Hash texture preview unavailable: " + path + ": " + str(error))
        # A decoder failure must not prevent choosing or exporting a texture.
        # The node shows a placeholder while retaining the original file path.
        return 0
