"""Shared image datablock loading for model imports.

`bpy.data.images.load(path)` creates a new Image datablock every time it is
called. The model importer creates one material per SubMesh, so the same
texture file becomes several Image datablocks. The texture combiner groups
materials by source identity, and a plain datablock pointer cannot tell those
datablocks apart: the same picture is then pasted once per SubMesh.

Loading every imported texture through this helper keeps one datablock per
normalized file path. The combiner then sees one source and produces one
atlas region. The helper only reuses a datablock; it never renames, moves or
repacks an image.

Color space is part of the reuse key on purpose. The same file can be read as
color data for Base Color and as raw data for a normal map. Reusing one
datablock across those two uses would let the last writer change the color
space of the other material, which is a data corruption, not a merge win.
"""

import os

import bpy


def normalize_image_path(path):
    """Return a case-folded absolute path, or "" for an unusable path.

    Blender reports relative paths ("//textures/a.dds") and may preserve the
    case used by the file system. Comparing raw strings would miss the same
    file reported in two different spellings, so the comparison normalizes
    both sides the same way.
    """
    if not path:
        return ""
    try:
        absolute = bpy.path.abspath(path)
    except (AttributeError, RuntimeError, ValueError):
        absolute = path
    return os.path.normcase(os.path.abspath(os.path.normpath(absolute)))


def _image_colorspace(image):
    """Return the Blender color-space name of an image, or ""."""
    try:
        return image.colorspace_settings.name
    except (AttributeError, RuntimeError):
        return ""


def find_loaded_image(path, colorspace=None):
    """Return the existing Image datablock for a file path, or None.

    Generated images and packed images without a filepath are skipped: they
    have no file identity to match. A packed image that kept its filepath
    still matches, so packing a source does not create a second datablock.

    When colorspace is given, only a datablock already using that color space
    is reused. A different color space means a different interpretation of
    the bytes and must stay a separate source.
    """
    normalized = normalize_image_path(path)
    if not normalized:
        return None
    for image in bpy.data.images:
        if normalize_image_path(getattr(image, "filepath", "")) != normalized:
            continue
        if colorspace is not None and _image_colorspace(image) != colorspace:
            continue
        return image
    return None


def load_shared_image(path, colorspace=None):
    """Load a texture file once and reuse that datablock on later calls.

    The first call loads the file normally. Later calls with the same path and
    color space return the same datablock, so materials that use one texture
    share one Image. An empty path keeps Blender's own error: callers relied
    on it and must not receive a silent None instead.
    """
    if not path:
        # bpy.data.images.load("") raises the same RuntimeError callers
        # handled before this helper existed.
        return bpy.data.images.load(path)
    existing = find_loaded_image(path, colorspace)
    if existing is not None:
        return existing
    # check_existing must stay False: Blender matches only the path and would
    # hand back a datablock using another color space.
    image = bpy.data.images.load(path, check_existing=False)
    if colorspace is not None:
        try:
            image.colorspace_settings.name = colorspace
        except (AttributeError, TypeError, ValueError):
            # A format without a color-space setting must not abort an import.
            pass
    return image
