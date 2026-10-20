"""Blender integration coverage for exact replacement texture formats.

Run with:
  blender -b --factory-startup --python-exit-code 1 --python this_file

The test loads the checkout through the real addon entry point, so every new
operator and RNA property is registered exactly as shipped. It checks the four
node panels, the original-format lookup and one real background conversion.
"""
# The addon is imported through its real package name, not a synthetic stub.
# A fake layout records what the node panels would draw, without an editor.
# The conversion is verified by parsing the produced DDS header, not the name.
# The disk cache is cleared at the end so no user cache is left behind.
import importlib
import os
from pathlib import Path
import sys
import tempfile
import time

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
addon = importlib.import_module(ROOT.name)
addon.register()

from MIMIBlender.blueprint import blueprint_node_base as base
from MIMIBlender.blueprint import texture_format_widgets as widgets
from MIMIBlender.common import texture_format_service as service
from MIMIBlender.texcomb.core import dds_match, texconv


class LayoutRecorder:
    """Record node controls; every layout call returns this same recorder."""

    def __init__(self):
        self.labels = []
        self.operators = []
        self.properties = []
        self.texts = []

    def _record(self, kind, args, kwargs):
        text = kwargs.get("text", "")
        if text:
            self.texts.append(str(text))
        return self

    def label(self, *args, **kwargs):
        self.labels.append(kwargs.get("text", str(args[0]) if args else ""))
        return self._record("label", args, kwargs)

    def operator(self, *args, **kwargs):
        self.operators.append(args[0] if args else kwargs.get("idname", ""))
        return self._record("operator", args, kwargs)

    def prop(self, *args, **kwargs):
        self.properties.append(args[1] if len(args) > 1 else "")
        return self._record("prop", args, kwargs)

    def __getattr__(self, name):
        def call(*args, **kwargs):
            return self._record(name, args, kwargs)
        return call


def make_dds(tmp_dir, name, pixel_format, size=(64, 64)):
    """Create one genuine captured DDS with the bundled texconv."""
    source = os.path.join(tmp_dir, name + ".png")
    image = bpy.data.images.new(name + "_src", width=size[0], height=size[1], alpha=True)
    image.generated_color = (40 / 255.0, 80 / 255.0, 120 / 255.0, 1.0)
    image.filepath_raw = source
    image.file_format = 'PNG'
    image.save()
    bpy.data.images.remove(image)
    header = "-dx10" if "BC7" in pixel_format or "BC5" in pixel_format else "-dx9"
    texconv._run_texconv(["-f", pixel_format, header, "-m", "0", "-y", "-o", tmp_dir, source])
    return os.path.join(tmp_dir, name + ".dds")


def make_png(tmp_dir, name, size=(32, 32)):
    """Create one replacement PNG with a different size than the capture."""
    path = os.path.join(tmp_dir, name + ".png")
    image = bpy.data.images.new(name + "_img", width=size[0], height=size[1], alpha=True)
    image.generated_color = (70 / 255.0, 20 / 255.0, 90 / 255.0, 1.0)
    image.filepath_raw = path
    image.file_format = 'PNG'
    image.save()
    bpy.data.images.remove(image)
    return path


def main():
    """Run every Blender-side check and return a process exit code."""
    failures = []

    def check(name, condition, extra=""):
        print(("PASS " if condition else "FAIL ") + name + ((" :: " + str(extra)) if extra else ""))
        if not condition:
            failures.append(name)

    # 1. Registration: operators, RNA settings and enum callbacks.
    check("convert operator registered", hasattr(bpy.ops.mimi, "texture_format_convert"))
    check("cancel operator registered", hasattr(bpy.ops.mimi, "texture_format_cancel"))
    check("clear cache operator registered", hasattr(bpy.ops.mimi, "texture_format_clear_cache"))
    properties = bpy.context.scene.mimi_global_properties
    check("switch property registered", hasattr(properties, "exact_texture_format"))
    check("filter property registered", hasattr(properties, "exact_texture_resize_filter"))
    check("cache folder property registered", hasattr(properties, "texture_format_cache_folder"))
    items = widgets.manual_format_items(None, bpy.context)
    names = [item[0] for item in items]
    check("manual format list contains BC7", "BC7_UNORM_SRGB" in names, len(names))

    # 2. Original lookup by an explicit capture path.
    if texconv.is_available():
        tmp_dir = tempfile.mkdtemp(prefix="mimi_texfmt_blender_")
        original = make_dds(tmp_dir, "capture", "BC7_UNORM_SRGB")
        replacement = make_png(tmp_dir, "replacement")
        metadata, state, _detail, agreed = service.resolve_original(original_path=original)
        check("original resolved", state == service.STATE_RESOLVED, state)
        check("original format detected", metadata is not None and metadata.format == "BC7_UNORM_SRGB", metadata)
        check("agreed path returned", agreed == original, agreed)

        # 3. Both global nodes must draw their new controls without an editor.
        tree = bpy.data.node_groups.new("texfmt_tree", base.MIMIBlueprintTree.bl_idname)
        slot_node = tree.nodes.new('MIMINode_Texture_Global')
        row = slot_node.items.add()
        row.submesh = "94517393-0"
        row.slot = "ps-t0"
        row.mark_name = "DiffuseMap"
        row.original_path = original
        row.file_path = replacement
        layout = LayoutRecorder()
        slot_node.draw_buttons(bpy.context, layout)
        check("slot node drew a status", any("convert" in text.lower() for text in layout.texts), layout.texts)
        check("convert all operator drawn", "mimi.texture_format_convert" in layout.operators)

        hash_node = tree.nodes.new('MIMINode_Hash_Texture_Global')
        hash_row = hash_node.texture_hash_items.add()
        hash_row.texture_hash = "0123abcd"
        hash_row.global_detected = True
        hash_row.source_type = 'FILE'
        hash_row.mark_source_submesh = "94517393-0"
        hash_row.mark_source_name = "HairMark"
        hash_row.mark_source_file_path = original
        hash_row.file_path = replacement
        hash_layout = LayoutRecorder()
        hash_node.draw_buttons(bpy.context, hash_layout)
        check("hash node drew a status", any("convert" in text.lower() for text in hash_layout.texts), hash_layout.texts)

        # 4. One real background conversion through the service.
        job = {
            "source": replacement,
            "original_path": original,
            "manual_format": "",
            "force_original_size": False,
            "resize_filter": dds_match.DEFAULT_RESIZE_FILTER,
            "label": "blender check",
        }
        started = service.start_conversion([job])
        check("conversion started", started == 1, started)
        deadline = time.time() + 120
        while service.is_running() and time.time() < deadline:
            time.sleep(0.05)
        snapshot = service.progress_snapshot()
        check("conversion finished", not snapshot["running"], snapshot)
        check("conversion had no errors", not snapshot["errors"], snapshot["errors"])
        cached = service.get_cache().lookup(replacement)
        check("cache index knows the source", cached is not None, cached)
        if cached:
            produced = dds_match.read_dds_metadata(cached["path"])
            check("cached format matches the capture", produced.format == "BC7_UNORM_SRGB", produced.format)
            # The replacement keeps its own 32x32 size, so the chain has 6 levels.
            check("cached shape follows the replacement", (produced.width, produced.height) == (32, 32),
                  (produced.width, produced.height))
        check("cache size is reported", service.cache_size() > 0, service.cache_size())

        # 5. Clearing the cache removes the product and the index entry.
        service.get_cache().clear()
        service.clear_lookup_cache()
        check("cache cleared", service.get_cache().lookup(replacement) is None)
    else:
        print("SKIP: bundled texconv.exe is not available")

    addon.unregister()
    if failures:
        print("FAILED CHECKS: " + ", ".join(failures))
        return 1
    print("ALL TEXTURE FORMAT BLENDER TESTS PASSED")
    return 0


sys.exit(main())
