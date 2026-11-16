"""Source-texture identity shared by the atlas planner and the merger.

A texture atlas must never paste one source picture twice. The combiner
therefore needs to know which materials really use the same source texture.
A Blender Image datablock is not a reliable answer on its own: importing one
model creates one material per SubMesh, and each material can load its own
datablock for the same file on disk. The atlas then sees several unrelated
images and copies the picture once per material.

This module holds the identity rule only. It imports no bpy, so plain pytest
can cover the decision logic outside Blender. The thin Blender adapter lives
in texcomb/utils/source_identity.py.

Identity rules:
- A file-backed image is identified by its normalized path plus a content
  digest. The same path and the same bytes are one source.
- The same path with different bytes stays two sources. A replaced texture
  file must never be merged with the old picture.
- Cross-path copies stay two sources. Copying a file is a deliberate act and
  must not be undone silently.
- A generated image without a file path falls back to the datablock pointer,
  because it has no stable file identity.
"""

import os

# Identity kinds. They are strings so a saved plan or a log stays readable.
PATH_KIND = "path"
PACKED_KIND = "packed"
IMAGE_KIND = "image"
MATERIAL_KIND = "material"


def normalize_texture_path(path):
    """Return a case-folded absolute path, or an empty string when unusable.

    Blender may report a relative path ("//textures/a.png"), a path with
    mixed separators, or a different letter case than the same file on
    another material. Comparing raw strings would miss those duplicates.
    """
    if not path:
        return ""
    # normpath removes ".." segments; abspath anchors the result; normcase
    # makes Windows comparisons case-insensitive and unifies separators.
    return os.path.normcase(os.path.abspath(os.path.normpath(path)))


def build_source_identity(path, content_digest, image_pointer):
    """Build the identity tuple for one image datablock.

    path: absolute file path reported by Blender, or "" for generated images.
    content_digest: hash of the packed bytes, or "" when unavailable.
    image_pointer: stable integer pointer of the datablock, used as a fallback.

    An empty digest for a valid path still counts as the same file. The
    digest is only a guard against a file that changed between two loads.
    Without a digest the two datablocks cannot be proven different, and
    treating one file as one source is the rule this module exists to keep.
    """
    normalized = normalize_texture_path(path)
    if normalized:
        # Keep the digest separate so two contents at one path never merge.
        return (PATH_KIND, normalized, content_digest or "")
    if content_digest:
        # Generated images have no file identity. Equal packed bytes mean
        # equal pixels, so sharing one atlas region is still correct.
        return (PACKED_KIND, content_digest)
    # No path and no bytes: the datablock itself is the only stable identity.
    return (IMAGE_KIND, int(image_pointer))


def material_identity(material_pointer):
    """Identity for a material that has no image texture at all.

    Solid-color materials bake from their color, not from an image. They must
    never share a texture family with each other, because the planner links
    sampling windows only inside a real image family.
    """
    return (MATERIAL_KIND, int(material_pointer))
