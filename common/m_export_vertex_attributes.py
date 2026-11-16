"""Collect per-vertex attributes while the temporary export mesh exists.

Some runtime effects need a value that only exists on the temporary export
copy of a mesh.  The exported vertex order does not match the Blender
vertex order: the export splits vertices at hard edges and UV seams, so a
per-vertex control weight has to be sampled through the export's own loop
mapping instead of by copying the Blender vertex list.

The export deletes the temporary merged mesh as soon as it produced the
vertex and index buffers, so a collector has to run inside that narrow
window.  This module provides that window without dragging feature code
into the model layer: the model only knows about the registry below, and
each feature registers its own collector.

A collector is called with the merged temporary object and the submesh it
belongs to.  It returns a dictionary, or None when it has nothing to add.
The dictionary is stored on the submesh model under the collector's own
key, so two features never overwrite each other.
"""

# The registered collectors.  Each entry is a callable that returns the
# data it wants to attach to a submesh, keyed by its own name.
_COLLECTOR_LIST = []


def register_collector(collector):
    """Register a collector callable and return it.

    The callable is used as the key of the data it returns, so it should
    carry a stable name attribute.
    """
    if collector not in _COLLECTOR_LIST:
        _COLLECTOR_LIST.append(collector)
    return collector


def unregister_collector(collector):
    """Remove a collector callable; unknown collectors are ignored."""
    if collector in _COLLECTOR_LIST:
        _COLLECTOR_LIST.remove(collector)


def get_collector_name(collector):
    """Return the storage key of a collector callable."""
    return getattr(collector, "collector_name", collector.__name__)


def run_collectors(merged_obj, submesh_model):
    """Run every registered collector on the temporary export mesh.

    A collector that fails must not break the export: the problem is
    reported on the console and the submesh keeps whatever the other
    collectors produced.
    """
    for collector in list(_COLLECTOR_LIST):
        try:
            result = collector(merged_obj, submesh_model)
        except Exception as error:
            print("Export vertex attribute collector " + get_collector_name(collector)
                  + " failed: " + str(error))
            continue
        if not result:
            continue
        submesh_model.export_vertex_attribute_dict[get_collector_name(collector)] = result
