"""Blender-facing service for exact replacement texture formats.

Three jobs live here, all of which need bpy or the workspace:

1. **Original lookup** - given a node row (slot, mark name or texture hash),
   find the captured DDS and parse its format. Results are cached per
   workspace stamp so drawing a node never re-reads the Submesh JSON.
2. **Job collection** - walk a blueprint tree (including nested groups) and
   describe every enabled replacement that must be converted.
3. **Background conversion** - run the Blender-free texconv pipeline on a
   worker thread, poll it from a ``bpy.app.timers`` callback, and expose a
   progress state plus a cancel switch. The UI thread only copies values.

Nothing here writes into the workspace or the generated Mod: converted files
live in the content-addressed cache and are copied by the export stage.
"""
import os
import threading
import time

import bpy

from ..i18n.i18n import tr
from ..texcomb.core import dds_match
from ..texcomb.core.conversion_cache import ConversionCache
from .global_config import GlobalConfig
from .mimi_global_properties import MIMIGlobalProperties

# Folder under %LOCALAPPDATA% holding one subfolder per workspace.
CACHE_FOLDER_NAME = "MIMIBlenderTextureCache"

# Poll interval of the main-thread timer while a batch is running.
TIMER_INTERVAL = 0.15

# Shared cache instance; recreated when the workspace or folder changes.
_CACHE = None
_CACHE_ROOT = ""

# Cached original lookups, keyed by the row selector. The stored stamp is the
# Submesh JSON modification time, so a re-extracted workspace invalidates it.
_ORIGINAL_CACHE = {}
_ORIGINAL_CACHE_LIMIT = 512

# One conversion batch at a time. The lock protects the plain dict state that
# the worker thread writes and the timer reads.
_STATE_LOCK = threading.Lock()
_STATE = {
    "running": False,
    "total": 0,
    "done": 0,
    "current": "",
    "cancelled": False,
    "errors": [],
    "finished_message": "",
}
_CANCEL = threading.Event()
_WORKER = None
_ON_DONE = [None]

# Job states reported by the node UI.
STATE_RESOLVED = "resolved"
STATE_MISSING = "missing"
STATE_CONFLICT = "conflict"

# The four nodes that can replace a game texture with a user image.
ADDRESSABLE_NODE_IDS = (
    'MIMINode_Texture_Bind',
    'MIMINode_Hash_Texture_Bind',
    'MIMINode_Hash_Texture_Global',
    'MIMINode_Texture_Global',
)


def _scene_texconv_path():
    """Return the texconv.exe path configured in the texture combiner settings."""
    try:
        return str(getattr(bpy.context.scene, "mimi_smc_texconv_path", "") or "")
    except Exception:
        # No scene (background mode) or the property is not registered yet.
        return ""


def _cache_folder_override():
    """Return the user-configured cache folder, or an empty string."""
    try:
        value = str(bpy.context.scene.mimi_global_properties.texture_format_cache_folder or "")
    except Exception:
        # Older property groups and background mode have no such field yet.
        value = ""
    return bpy.path.abspath(value) if value else ""


def cache_root():
    """Return the folder holding this workspace's converted textures."""
    override = _cache_folder_override()
    if override:
        return override
    try:
        appdata = GlobalConfig.path_appdata_local()
    except Exception:
        appdata = os.path.join(os.path.expanduser("~"), "AppData", "Local")
    workspace = str(GlobalConfig.get_workspace_name() or "").strip() or "default"
    # Workspace names are already filesystem safe; keep the folder readable.
    return os.path.join(appdata, CACHE_FOLDER_NAME, workspace)


def get_cache():
    """Return the shared conversion cache for the current workspace."""
    global _CACHE, _CACHE_ROOT
    root = cache_root()
    if _CACHE is None or root != _CACHE_ROOT:
        _CACHE = ConversionCache(root)
        _CACHE_ROOT = root
    return _CACHE


def ensure_configured():
    """Push the cache and texconv path into the Blender-free core module."""
    cache = get_cache()
    dds_match.set_default_cache(cache)
    dds_match.set_default_texconv_path(_scene_texconv_path())
    return cache


def clear_lookup_cache():
    """Forget every cached original lookup (called by refresh operators)."""
    _ORIGINAL_CACHE.clear()


# Cache size is only a display value; walking a large folder on every redraw
# would be slow, so the measured value is reused for a couple of seconds.
_SIZE_STAMP = {"time": 0.0, "value": 0}


def cache_size():
    """Return the current cache size in bytes, throttled for UI redraws."""
    now = time.time()
    if now - _SIZE_STAMP["time"] < 2.0:
        return int(_SIZE_STAMP["value"])
    value = get_cache().total_size()
    _SIZE_STAMP["time"] = now
    _SIZE_STAMP["value"] = value
    return value


# ----------------------------------------------------------------------
# Original texture lookup
# ----------------------------------------------------------------------
def _submesh_json_path(submesh_name):
    """Return the active Submesh JSON path, or "" when it cannot be resolved."""
    try:
        from ..workspace.mmt_workspace import MMTWorkSpace
        return str(MMTWorkSpace.check_and_get_submesh_json_path(submesh_name) or "")
    except Exception:
        return ""


def _workspace_stamp(submesh_name):
    """Cheap invalidation stamp for one Submesh JSON (path + mtime + size)."""
    if not submesh_name:
        return ("", 0, 0)
    path = _submesh_json_path(submesh_name)
    if not path:
        return ("", 0, 0)
    try:
        stat = os.stat(path)
        return (os.path.normcase(path), stat.st_mtime_ns, stat.st_size)
    except OSError:
        return (os.path.normcase(path), 0, 0)


def _mark_dicts(submesh_name):
    """Load the texture marks of one Submesh through the node helper."""
    if not submesh_name:
        return []
    try:
        from ..blueprint.blueprint_node_texture import _load_submesh_mark_dicts
        return _load_submesh_mark_dicts(submesh_name, dedupe_names=False)
    except Exception:
        # A missing workspace must never break drawing.
        return []


def _workspace_original_paths(submesh_name, slot="", mark_name="", texture_hash=""):
    """Return every captured DDS path that matches one selector."""
    paths = []
    wanted_slot = str(slot or "").strip().lower()
    wanted_name = str(mark_name or "").strip().lower()
    wanted_hash = str(texture_hash or "").strip().lower()
    if not (wanted_slot or wanted_name or wanted_hash):
        return paths
    try:
        from ..blueprint.blueprint_node_hash_texture import _find_global_mark_source_path
    except Exception:
        _find_global_mark_source_path = None
    for mark in _mark_dicts(submesh_name):
        if wanted_name:
            if mark.get("name", "").lower() != wanted_name:
                continue
        elif wanted_slot:
            if mark.get("slot", "").lower() != wanted_slot:
                continue
        elif mark.get("hash", "").lower() != wanted_hash:
            continue
        if _find_global_mark_source_path is not None:
            path = _find_global_mark_source_path(submesh_name, mark.get("filename", ""))
            if path:
                paths.append(path)
    if not paths and wanted_hash:
        # Global hash rows can point at a capture of any Submesh.
        try:
            from ..blueprint.blueprint_node_hash_texture import _load_global_hash_mark_entries
            for entry in _load_global_hash_mark_entries():
                if entry["hash"] == wanted_hash and entry["source_path"]:
                    paths.append(entry["source_path"])
        except Exception:
            pass
    return paths


def resolve_original(submesh_name="", slot="", mark_name="", texture_hash="", original_path=""):
    """Resolve the capture that a node row replaces.

    Returns ``(metadata, state, detail, agreed_path)``:
    - metadata: a DDSMetadata, or None when nothing readable was found;
    - state: resolved / missing / conflict;
    - detail: human readable conflict list (usually empty);
    - agreed_path: the capture that supplied the metadata.

    The result is cached per Submesh JSON stamp, so node drawing stays cheap.
    """
    key = (
        str(submesh_name or ""),
        str(slot or "").lower(),
        str(mark_name or ""),
        str(texture_hash or "").lower(),
        str(original_path or ""),
    )
    stamp = _workspace_stamp(submesh_name)
    cached = _ORIGINAL_CACHE.get(key)
    if cached is not None and cached[0] == stamp:
        return cached[1]

    paths = []
    if original_path:
        paths.append(original_path)
    paths.extend(_workspace_original_paths(
        submesh_name, slot=slot, mark_name=mark_name, texture_hash=texture_hash,
    ))
    metadata, conflict, agreed_path = dds_match.agree_on_metadata(paths)
    if conflict:
        formats = set()
        for path in paths:
            try:
                formats.add(dds_match.describe_format(dds_match.read_dds_metadata(path)))
            except Exception:
                continue
        result = (None, STATE_CONFLICT, ", ".join(sorted(formats)), "")
    elif metadata is None:
        result = (None, STATE_MISSING, "", "")
    else:
        result = (metadata, STATE_RESOLVED, "", agreed_path)

    if len(_ORIGINAL_CACHE) >= _ORIGINAL_CACHE_LIMIT:
        # Bounded cache: a workspace with thousands of marks must not grow
        # without limit while the node editor keeps drawing.
        _ORIGINAL_CACHE.clear()
    _ORIGINAL_CACHE[key] = (stamp, result)
    return result


# ----------------------------------------------------------------------
# Job collection
# ----------------------------------------------------------------------
def node_rows(node):
    """Return the full replacement row collection of one texture node."""
    node_id = getattr(node, "bl_idname", "")
    if node_id == 'MIMINode_Texture_Bind':
        return list(getattr(node, "texture_slot_items", []) or [])
    if node_id == 'MIMINode_Texture_Global':
        # The socketless slot manager keeps its rows in a plain 'items' list.
        return list(getattr(node, "items", []) or [])
    return list(getattr(node, "texture_hash_items", []) or [])


def enabled_rows(node):
    """Return only the enabled replacement rows of one texture node."""
    return [item for item in node_rows(node) if getattr(item, "enabled", True)]


def _row_file_path(item):
    """Return the absolute replacement path of one row, or "".

    A MARK row can own an image too (the per-object replacement of a marked
    slot). It is converted exactly like an external file, so both fields are
    read here instead of only ``file_path``.
    """
    attribute = "mark_file_path" if str(getattr(item, "source_type", "") or "") == 'MARK' else "file_path"
    path = str(getattr(item, attribute, "") or "").strip()
    if not path:
        return ""
    try:
        return os.path.normpath(bpy.path.abspath(path))
    except Exception:
        return os.path.normpath(path)


def upstream_submesh(node):
    """Return the Submesh of the object chain feeding a connected node."""
    try:
        from ..blueprint.blueprint_node_texture import _resolve_upstream_submesh_name
        return str(_resolve_upstream_submesh_name(node) or "")
    except Exception:
        return ""


def upstream_submeshes(node):
    """Return every Submesh feeding a connected node, in wire order.

    A texture node with several channels can feed objects of several Submeshes.
    Each Submesh resolves its own captured original, so the pre-conversion has
    to cover all of them; the content-addressed cache then turns identical
    products into a single lookup.
    """
    try:
        from ..blueprint.texture_output_widgets import upstream_submesh_names
        return [
            str(name or "").strip()
            for name in upstream_submesh_names(node)
            if str(name or "").strip()
        ]
    except Exception:
        # A half-built graph must not break job collection.
        return []


def _row_label(node, source):
    """Short caption used by the progress text and by error messages."""
    label = getattr(node, "label", "") or getattr(node, "name", "")
    return _job_label(label, os.path.basename(source))


def _mark_row_name(item):
    """Return the picked mark name of a mark row, or "" when none is picked.

    Imported lazily: the node module imports this service, so a module level
    import would close the cycle.
    """
    try:
        from ..blueprint.blueprint_node_texture import mark_name_of
        return str(mark_name_of(item) or "")
    except Exception:
        return ""


def row_selectors(node, item):
    """Return the original-lookup selectors of one row, without the Submesh.

    The four nodes store their detection fields in different places, so this
    mapping lives next to the job builder instead of inside the draw code.
    """
    node_id = getattr(node, "bl_idname", "")
    if node_id == 'MIMINode_Texture_Bind':
        # A mark row resolves its original by mark name; the slot is the
        # fallback for external files, which have no mark.
        mark_name = ""
        if str(getattr(item, "source_type", "") or "") == 'MARK':
            mark_name = _mark_row_name(item)
        return {
            "slot": str(getattr(item, "slot", "") or ""),
            "mark_name": mark_name,
        }
    if node_id == 'MIMINode_Hash_Texture_Bind':
        return {
            "slot": str(getattr(item, "mark_source_slot", "") or ""),
            "mark_name": _hash_row_mark_name(item),
            "texture_hash": str(getattr(item, "texture_hash", "") or ""),
        }
    if node_id == 'MIMINode_Hash_Texture_Global':
        return {
            "slot": str(getattr(item, "mark_source_slot", "") or ""),
            "mark_name": str(getattr(item, "mark_source_name", "") or ""),
            "texture_hash": str(getattr(item, "texture_hash", "") or ""),
            "original_path": str(getattr(item, "mark_source_file_path", "") or ""),
        }
    # The socketless slot manager already stores its captured original path.
    return {"original_path": str(getattr(item, "original_path", "") or "")}


def row_submesh(node, item):
    """Return the Submesh used to resolve one row's original texture."""
    node_id = getattr(node, "bl_idname", "")
    if node_id == 'MIMINode_Hash_Texture_Global':
        return str(getattr(item, "mark_source_submesh", "") or "")
    if node_id == 'MIMINode_Texture_Global':
        return str(getattr(item, "submesh", "") or "")
    return upstream_submesh(node)


def job_for_row(node, item, submesh=""):
    """Build the conversion job of one row, or None when it does not convert.

    This is the single place that knows which RNA fields describe the
    original texture for each of the four replacement nodes.
    """
    node_id = getattr(node, "bl_idname", "")
    source = _row_file_path(item)
    if node_id in ('MIMINode_Texture_Bind', 'MIMINode_Hash_Texture_Bind'):
        source_type = str(getattr(item, "source_type", "") or "")
        if source_type == 'MARK':
            # A mark row only converts when it picked its own image; a copied
            # mark capture already has the game's bytes and format.
            if not str(getattr(item, "mark_file_path", "") or "").strip():
                return None
        elif source_type != 'FILE':
            return None
    if node_id not in (
        'MIMINode_Texture_Bind', 'MIMINode_Hash_Texture_Bind',
        'MIMINode_Hash_Texture_Global', 'MIMINode_Texture_Global',
    ):
        return None
    return _make_job(
        source=source, item=item, submesh=submesh or row_submesh(node, item),
        label=_row_label(node, source), **row_selectors(node, item),
    )


def _hash_row_mark_name(item):
    """Return the selected mark name of a hash row in either row style."""
    detected_name = str(getattr(item, "mark_source_name", "") or "").strip()
    if detected_name:
        return detected_name
    try:
        from ..blueprint.blueprint_node_texture import mark_name_of
        return str(mark_name_of(item) or "")
    except Exception:
        return ""


def collect_tree_jobs(tree):
    """Return one job dict per enabled replacement row of this blueprint tree.

    Nested group trees are visited too, because a texture node inside a group
    still owns its rows. Muted nodes and muted groups contribute nothing.
    """
    jobs = []
    visited = set()

    def visit(current):
        if current is None or id(current) in visited:
            return
        visited.add(id(current))
        for node in getattr(current, "nodes", []):
            if getattr(node, "mute", False):
                continue
            node_id = getattr(node, "bl_idname", "")
            if node_id == 'SSMTBlueprintGroupNode':
                visit(getattr(node, "node_tree", None))
                continue
            if node_id not in ADDRESSABLE_NODE_IDS:
                continue
            # Walk upstream only for nodes that actually own replacement rows.
            submesh = upstream_submesh(node)
            # A Slot Texture Bind node with several channels can feed objects of
            # several Submeshes; each resolves a different captured original, so
            # every one of them needs a pre-conversion. Hash rows carry their
            # own Submesh, and the global slot node stores it per row, so those
            # keep the single lookup.
            submesh_targets = [submesh]
            if node_id == 'MIMINode_Texture_Bind':
                submesh_targets = upstream_submeshes(node) or [submesh]
            for item in enabled_rows(node):
                for target_submesh in submesh_targets:
                    job = job_for_row(node, item, target_submesh)
                    if job:
                        jobs.append(job)

    visit(tree)
    return jobs


def _resize_filter():
    """Return the configured resize filter name."""
    getter = getattr(MIMIGlobalProperties, "exact_texture_resize_filter_name", None)
    try:
        value = str(getter() or "") if callable(getter) else ""
    except Exception:
        value = ""
    return value or dds_match.DEFAULT_RESIZE_FILTER


def _job_label(label, filename):
    """Build the short progress caption shown while converting."""
    node_label = str(label or "").strip()
    return (node_label + ": " if node_label else "") + filename


def _make_job(source, item, submesh="", slot="", mark_name="", texture_hash="",
              original_path="", label=""):
    """Build one job dict, or None when the row has nothing to convert."""
    if not source or not os.path.isfile(source):
        return None
    mode = str(getattr(item, "format_mode", "AUTO") or "AUTO").strip().upper()
    manual_format = str(getattr(item, "manual_format", "") or "").strip()
    metadata, state, _detail, agreed_path = resolve_original(
        submesh_name=submesh, slot=slot, mark_name=mark_name,
        texture_hash=texture_hash, original_path=original_path,
    )
    if state == STATE_CONFLICT:
        # The export keeps the raw copy; the node shows the conflict instead.
        return None
    if metadata is None and not (mode == 'MANUAL' and manual_format):
        return None
    return {
        "source": source,
        # The agreed capture is what the conversion must match; a manual
        # format has no capture at all, which is why the field stays empty.
        "original_path": "" if metadata is None else (original_path or agreed_path or ""),
        "manual_format": "" if metadata is not None else manual_format,
        "force_original_size": bool(getattr(item, "force_original_size", False)),
        "resize_filter": _resize_filter(),
        "label": _job_label(label, os.path.basename(source)),
        # Per-row colour-space override plus the role hint used by AUTO.
        "color_mode": str(getattr(item, "color_space", "AUTO") or "AUTO").upper(),
        "data_hint": " ".join(part for part in (
            str(mark_name or ""), str(slot or ""), os.path.basename(source or ""),
        ) if part),
    }


def plan_for_job(job):
    """Return the conversion plan of one job, or None for a byte passthrough.

    Raises ValueError with the exact reason when the replacement cannot be
    converted, so the node can show it before the export runs.
    """
    source = job["source"]
    if job.get("original_path"):
        metadata = dds_match.read_dds_metadata(job["original_path"])
    else:
        width, height = dds_match.image_dimensions(source)
        metadata = dds_match.metadata_for_format(job["manual_format"], width, height)
    return dds_match.build_conversion_plan(
        source, metadata,
        force_original_size=bool(job.get("force_original_size", False)),
        resize_filter=job.get("resize_filter", dds_match.DEFAULT_RESIZE_FILTER),
        color_mode=job.get("color_mode", "AUTO"),
        data_hint=job.get("data_hint", ""),
    )


# ----------------------------------------------------------------------
# Background runner
# ----------------------------------------------------------------------
def is_running():
    """Return True while a conversion batch is active."""
    with _STATE_LOCK:
        return bool(_STATE["running"])


def progress_snapshot():
    """Return a copy of the progress state for the node panels."""
    with _STATE_LOCK:
        return dict(_STATE)


def cancel_conversion():
    """Ask the worker to stop after the current texture."""
    _CANCEL.set()


def _tag_node_editors():
    """Redraw every node editor so the in-node progress text updates."""
    try:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'NODE_EDITOR':
                    area.tag_redraw()
    except Exception:
        # A missing window must not interrupt the batch bookkeeping.
        pass


def _progress_begin(total):
    """Show the status bar progress bar when a window is available."""
    try:
        bpy.context.window_manager.progress_begin(0, max(1, total))
    except Exception:
        pass


def _progress_update(done):
    """Advance the status bar progress bar."""
    try:
        bpy.context.window_manager.progress_update(int(done))
    except Exception:
        pass


def _progress_end():
    """Remove the status bar progress bar."""
    try:
        bpy.context.window_manager.progress_end()
    except Exception:
        pass


def _worker(jobs, cache):
    """Convert a batch of jobs on a background thread (no bpy calls)."""
    completed = 0
    errors = []
    try:
        # One stage keeps a single temporary folder for the whole batch; every
        # product is copied into the cache, so the folder can be dropped later.
        with dds_match.DDSReplacementStage(cache=cache) as stage:
            for index, job in enumerate(jobs):
                if _CANCEL.is_set():
                    break
                with _STATE_LOCK:
                    _STATE["current"] = job["label"]
                    _STATE["done"] = index
                try:
                    dds_match.prepare_replacement_job(stage, job["source"], job)
                except Exception as error:
                    # One bad image must not stop the rest of the batch.
                    errors.append(job["label"] + ": " + str(error))
                    print("TextureFormat: conversion failed for " + job["source"] + ": " + str(error))
                completed = index + 1
    finally:
        with _STATE_LOCK:
            _STATE["done"] = completed
            _STATE["cancelled"] = bool(_CANCEL.is_set() and completed < len(jobs))
            _STATE["errors"].extend(errors)
            _STATE["running"] = False


def _timer_tick():
    """Main-thread poll: update progress, detect completion, finalise the UI."""
    with _STATE_LOCK:
        running = bool(_STATE["running"])
        done = int(_STATE["done"])
        total = int(_STATE["total"])
        cancelled = bool(_STATE["cancelled"])
        errors = list(_STATE["errors"])
    if running:
        _progress_update(done)
        _tag_node_editors()
        return TIMER_INTERVAL

    # The worker has finished: finalise the UI exactly once.
    _progress_end()
    _tag_node_editors()
    if cancelled:
        message = tr("Texture format conversion cancelled")
    elif errors:
        message = tr("Texture format conversion finished with {count} error(s)").format(count=len(errors))
    else:
        message = tr("Texture format conversion finished")
    with _STATE_LOCK:
        _STATE["current"] = ""
        _STATE["finished_message"] = message
    callback = _ON_DONE[0]
    _ON_DONE[0] = None
    if callable(callback):
        try:
            callback(bool(cancelled), list(errors))
        except Exception as error:
            print("TextureFormat: completion callback failed: " + str(error))
    return None


def last_message():
    """Return the last finished message without clearing it (node panels)."""
    with _STATE_LOCK:
        return str(_STATE.get("finished_message", "") or "")


def start_conversion(jobs, on_done=None):
    """Start converting the given jobs; returns the number of planned jobs.

    Jobs whose source already matches the original are skipped, so pressing
    Convert twice is harmless. Returns 0 when nothing needs conversion.
    """
    global _WORKER
    if is_running():
        return 0
    ensure_configured()
    cache = get_cache()
    prepared = []
    plan_errors = []
    for job in jobs or []:
        try:
            if plan_for_job(job) is None:
                # Byte-identical DDS: nothing to convert or cache.
                continue
        except Exception as error:
            plan_errors.append(str(job.get("label", "")) + ": " + str(error))
            continue
        prepared.append(job)
    if not prepared:
        if plan_errors:
            with _STATE_LOCK:
                _STATE["errors"] = plan_errors
        return 0

    _CANCEL.clear()
    with _STATE_LOCK:
        _STATE.update({
            "running": True,
            "total": len(prepared),
            "done": 0,
            "current": "",
            "cancelled": False,
            "errors": list(plan_errors),
            "finished_message": "",
        })
    _ON_DONE[0] = on_done
    _progress_begin(len(prepared))
    _WORKER = threading.Thread(
        target=_worker, args=(prepared, cache), name="MIMITextureFormat", daemon=True,
    )
    _WORKER.start()
    # Prefer the live registration check: a file load can purge timers, and a
    # stale local flag would then silently stop future progress updates.
    if not bpy.app.timers.is_registered(_timer_tick):
        bpy.app.timers.register(_timer_tick, first_interval=TIMER_INTERVAL, persistent=True)
    return len(prepared)


def start_conversion_for_tree(tree, on_done=None):
    """Collect and convert every replacement row of one blueprint tree."""
    return start_conversion(collect_tree_jobs(tree), on_done=on_done)
