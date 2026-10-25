"""Content-addressed disk cache for converted replacement textures.

Why a disk cache instead of a per-export temporary folder:

- One replacement texture is often needed by several objects and by the
  global and per-object sections of the same export, which previously
  converted the same bytes twice.
- A background conversion finishes long before the user presses Generate
  Mod, so the export itself only copies finished files.
- Unchanged sources keep hitting the same entry across Blender sessions.

The cache deliberately lives outside the addon (updates replace it) and
outside the generated Mod (it must never be shipped). The caller passes the
root folder; this module stays free of bpy so it can be unit tested.
"""
import hashlib
import json
import os
import shutil
import threading
import time

from .dds_match import read_dds_metadata

# Bump this whenever conversion flags or the key composition change, so a
# previous release's cached files can never be mistaken for current output.
# 2: colour-space flags are now derived per plan (they used to be fixed).
CACHE_VERSION = 2

# One megabyte per read keeps hashing fast without huge allocations.
_CHUNK_SIZE = 1024 * 1024

# The index is a small JSON document; keeping the name explicit avoids a
# collision with any future per-entry sidecar file.
INDEX_FILE_NAME = 'index.json'


def source_digest(path):
    """Return the SHA-256 of a file's bytes, read in bounded chunks."""
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        while True:
            chunk = stream.read(_CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def source_identity(path):
    """Cheap path/size/mtime identity used by the UI index (no content read).

    The index is only a display helper: a stale entry is detected because the
    cached file must still parse and match the requested metadata, and the
    conversion path always re-hashes the real bytes before trusting a hit.
    """
    stat = os.stat(path)
    return '|'.join((
        os.path.normcase(os.path.abspath(path)),
        str(stat.st_size),
        str(stat.st_mtime_ns),
    ))


class ConversionCache:
    """Persistent store for one workspace's converted replacement textures."""

    def __init__(self, root, version=CACHE_VERSION):
        # abspath keeps keys stable when the addon is loaded from a relative
        # path and the cache root is built from the current working directory.
        self.root = os.path.abspath(root)
        self.version = int(version)
        self.index_path = os.path.join(self.root, INDEX_FILE_NAME)
        # The reentrant lock allows nested helpers such as record() -> _save().
        self._lock = threading.RLock()
        self._index = None

    # ------------------------------------------------------------------
    # Key composition
    # ------------------------------------------------------------------
    def key(self, plan, digest=None):
        """Return the cache key for one conversion plan.

        ``digest`` may be supplied when the caller already hashed the source,
        which saves a full re-read on repeated exports.
        """
        if plan is None:
            return ''
        if digest is None:
            digest = source_digest(plan.source)
        # Storage key covers format, header style, topology and alpha mode.
        # Dimensions and mip count cover the output shape policy.
        # The resize filter changes pixels without changing the header.
        # The colour-space flags change the pixel values too, so two rows that
        # share one source but interpret it differently must not share a key.
        parts = (
            str(self.version),
            digest,
            '|'.join(str(value) for value in plan.storage_key),
            str(plan.width), str(plan.height), str(plan.mips),
            plan.format,
            plan.resize_filter or '',
            'srgb-in=' + str(int(bool(getattr(plan, 'srgb_in', False)))),
            'srgb-out=' + str(int(bool(getattr(plan, 'srgb_out', False)))),
            'ignore-srgb=' + str(int(bool(getattr(plan, 'ignore_srgb', False)))),
        )
        return hashlib.sha256('~'.join(parts).encode('utf-8')).hexdigest()

    def path_for(self, key):
        """Return the two-level path of a cached conversion product."""
        # Two characters of fan-out keep directories small on large workspaces.
        return os.path.join(self.root, key[:2], key + '.dds')

    # ------------------------------------------------------------------
    # Read / write
    # ------------------------------------------------------------------
    def get(self, key, plan):
        """Return a validated cached file path, or "" when it must convert.

        A file that exists but no longer matches the requested metadata is
        treated as a miss: a half-written or foreign file must never be used.
        """
        if not key:
            return ''
        path = self.path_for(key)
        if not os.path.isfile(path):
            return ''
        try:
            actual = read_dds_metadata(path)
        except Exception:
            # Corrupt entries are ignored here and overwritten by put().
            return ''
        if actual.storage_key != plan.storage_key:
            return ''
        if (actual.width, actual.height, actual.mip_count) != (plan.width, plan.height, plan.mips):
            return ''
        return path

    def put(self, key, produced_path, plan=None):
        """Copy one verified conversion product into the cache atomically."""
        target = self.path_for(key)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        # A unique partial name allows two Blender instances to convert the
        # same content at once; the last rename wins and both files are equal.
        partial = target + '.' + str(os.getpid()) + '.partial'
        try:
            shutil.copyfile(produced_path, partial)
            os.replace(partial, target)
        finally:
            if os.path.isfile(partial):
                try:
                    os.remove(partial)
                except OSError:
                    pass
        if plan is not None:
            self.record(plan, key)
        return target

    # ------------------------------------------------------------------
    # UI index (display only, never used for correctness)
    # ------------------------------------------------------------------
    def _load_index(self):
        """Load the index once per process, tolerating a missing file."""
        with self._lock:
            if self._index is None:
                self._index = self._read_index()
            return self._index

    def _read_index(self):
        try:
            with open(self.index_path, 'r', encoding='utf-8') as stream:
                data = json.load(stream)
            return data if isinstance(data, dict) else {}
        except Exception:
            # A missing or unreadable index only loses display hints.
            return {}

    def _save_index(self):
        """Write the index atomically; a failure never breaks conversion."""
        try:
            os.makedirs(self.root, exist_ok=True)
            temporary = self.index_path + '.' + str(os.getpid()) + '.tmp'
            with open(temporary, 'w', encoding='utf-8') as stream:
                json.dump(self._index, stream, ensure_ascii=False)
            os.replace(temporary, self.index_path)
        except Exception as error:
            print('ConversionCache: index write failed: ' + str(error))

    def record(self, plan, key):
        """Remember which source produced which cache key, for the node UI."""
        try:
            identity = source_identity(plan.source)
        except OSError:
            return
        with self._lock:
            index = self._load_index()
            index[identity] = {
                'key': key,
                'format': plan.format,
                'width': plan.width,
                'height': plan.height,
                'mips': plan.mips,
                'time': int(time.time()),
            }
            self._save_index()

    def lookup(self, source_path):
        """Return display info for an already converted source, or None."""
        try:
            identity = source_identity(source_path)
        except OSError:
            return None
        with self._lock:
            entry = self._load_index().get(identity)
        if not isinstance(entry, dict):
            return None
        path = self.path_for(str(entry.get('key', '')))
        if not os.path.isfile(path):
            return None
        result = dict(entry)
        result['path'] = path
        return result

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------
    def total_size(self):
        """Return the number of bytes currently stored in this cache."""
        total = 0
        for folder, _dirs, files in os.walk(self.root):
            for name in files:
                try:
                    total += os.path.getsize(os.path.join(folder, name))
                except OSError:
                    pass
        return total

    def clear(self):
        """Delete every cached product and the display index.

        Only files this cache owns are removed: the root folder itself may be
        shared with other workspaces, so it is never deleted recursively.
        """
        with self._lock:
            self._index = {}
            for folder, _dirs, files in os.walk(self.root):
                for name in files:
                    if not name.lower().endswith('.dds') and name != INDEX_FILE_NAME:
                        continue
                    try:
                        os.remove(os.path.join(folder, name))
                    except OSError:
                        pass
            self._save_index()
