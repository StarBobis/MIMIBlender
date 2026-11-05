"""Explicit DiffuseMap result discovery without guessing from image names."""
import os

import bpy

# Custom Image properties survive blend saves and renamed atlas datablocks.
# Other generated PBR maps are tagged too, but are never diffuse candidates.
ROLE_KEY = "mimi_atlas_role"
ID_KEY = "mimi_atlas_id"


def mark_atlas_image(image, role, atlas_id):
    """Record the actual generated plane role at the creation boundary."""
    image[ROLE_KEY] = str(role)
    image[ID_KEY] = str(atlas_id)
    # Keep a generated image selectable even if the material is later replaced.
    image.use_fake_user = True


def diffuse_results():
    """Return unique existing albedo result files from this Blender session."""
    results = []
    seen = set()
    # Discovery is cheap metadata work; do not decode pixels in a UI callback.
    for image in bpy.data.images:
        if image.get(ROLE_KEY) != "albedo":
            continue
        path = os.path.normpath(bpy.path.abspath(image.filepath)) if image.filepath else ""
        key = os.path.normcase(path)
        if not path or key in seen or not os.path.isfile(path):
            continue
        seen.add(key)
        results.append((image.name, path))
    return sorted(results, key=lambda result: result[0].casefold())


def result_path(image_name):
    """Revalidate at execution time instead of trusting a stale popup list."""
    for name, path in diffuse_results():
        if name == image_name:
            return path
    return ""
