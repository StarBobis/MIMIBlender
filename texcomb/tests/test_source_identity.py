"""Pure tests for the source-texture identity rule.

The identity decides when two materials share one atlas region. A mistake
here either pastes one picture twice or merges two different pictures, so
every branch needs an explicit test. These tests import no bpy and run with
plain pytest, which keeps the rule independent of Blender's datablock state.
"""

import os

from texcomb.core import source_identity


def test_normalize_makes_one_file_comparable():
    """Absolute, relative and mixed-case spellings must normalize equal.

    This is the comparison the importer and the atlas planner share. A
    different answer here means one file becomes two atlas sources before any
    grouping logic can help.
    """
    absolute = os.path.abspath(os.path.join("textures", "diffuse.png"))
    assert source_identity.normalize_texture_path(absolute) == \
        source_identity.normalize_texture_path(absolute.upper())
    assert source_identity.normalize_texture_path("") == ""


def test_same_path_and_bytes_share_identity():
    """Two datablocks loaded from one unchanged file are one source.

    The two pointers differ on purpose: the test proves identity does not
    depend on a datablock pointer when a valid path exists.
    """
    absolute = os.path.abspath("diffuse.png")
    first = source_identity.build_source_identity(absolute, "digest-a", 1)
    second = source_identity.build_source_identity(absolute, "digest-a", 2)
    assert first == second


def test_same_path_different_bytes_stay_distinct():
    """A replaced file must never merge with the picture loaded earlier.

    This is the guard that lets the planner hash only paths that appear more
    than once: the hash exists exactly to tell these two cases apart.
    """
    absolute = os.path.abspath("diffuse.png")
    first = source_identity.build_source_identity(absolute, "digest-a", 1)
    second = source_identity.build_source_identity(absolute, "digest-b", 2)
    assert first != second


def test_same_path_without_digest_still_shares():
    """Unreadable bytes cannot prove two datablocks different."""
    absolute = os.path.abspath("diffuse.png")
    first = source_identity.build_source_identity(absolute, "", 1)
    second = source_identity.build_source_identity(absolute, "", 2)
    assert first == second


def test_cross_path_copies_stay_distinct():
    """A copied file is a deliberate duplicate, not one source.

    Copying is often how a user keeps two editable variants. Undoing that
    silently would be a worse surprise than a slightly larger atlas.
    """
    first = source_identity.build_source_identity(os.path.abspath("a.png"), "same", 1)
    second = source_identity.build_source_identity(os.path.abspath("b.png"), "same", 2)
    assert first != second


def test_generated_images_compare_by_content():
    """Generated images have no path; equal bytes bake equal pixels."""
    first = source_identity.build_source_identity("", "same-bytes", 1)
    second = source_identity.build_source_identity("", "same-bytes", 2)
    different = source_identity.build_source_identity("", "other-bytes", 3)
    assert first == second
    assert first != different


def test_generated_images_without_bytes_use_the_pointer():
    """No path and no bytes leaves the datablock as the only identity.

    Two unrelated generated images may look alike by accident; without bytes
    there is no evidence that sharing them is safe.
    """
    first = source_identity.build_source_identity("", "", 11)
    same = source_identity.build_source_identity("", "", 11)
    other = source_identity.build_source_identity("", "", 12)
    assert first == same
    assert first != other


def test_solid_materials_never_share():
    """Solid-color materials must stay independent texture families."""
    assert source_identity.material_identity(1) != source_identity.material_identity(2)
    assert source_identity.material_identity(7) == source_identity.material_identity(7)
