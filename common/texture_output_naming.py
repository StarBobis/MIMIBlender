"""File names of the texture files written into the generated Mod.

Every generated texture file has exactly one name: it is the name the exporter
writes into the ``Textures`` folder and also the name the generated INI
references.  The four Texture Bind blueprint nodes display that name in their
UI, so the naming rule lives in exactly one place: this module.  Both the
export pass and the node UI call these helpers, which is what makes the
displayed name trustworthy instead of a second, slowly drifting guess.

Three kinds of values are handled here:

1. Default names built from data the exporter already has (DrawIB, object
   name, texture hash, mark role).  Their spelling is kept exactly as the
   previous versions produced it, so existing mods stay compatible.
2. A user alias.  When a row carries an alias, it replaces the whole default
   name; only the image format suffix is kept, because the copied file keeps
   the exact bytes of the source image and must therefore keep its suffix.
3. Display placeholders (``<DrawIB>``, ``<Object>``, ``<N>``).  The node UI
   shows them for parts that only become final during export, so the UI never
   pretends to know something it cannot know.

Nothing in this module imports bpy: it is imported by the model layer, by the
insensitive INI helper and by the node UI, and every one of them has to get
the same answer.
"""
import locale
import os
import re

# Characters a Windows file name must never contain.  A path separator is
# included because an alias is only a file name, never a folder.
_INVALID_FILENAME_CHARS = '<>:"/\\|?*'

# Image formats the export pipeline accepts as a texture source.
TEXTURE_FILE_SUFFIXES = (".dds", ".png", ".jpg", ".jpeg", ".bmp", ".tga")

# Suffix used when a source path has no recognizable image suffix.
DEFAULT_TEXTURE_SUFFIX = ".dds"

# Markers shown by the node UI in front of an export-time decision.
DRAW_IB_PLACEHOLDER = "<DrawIB>"
OBJECT_PLACEHOLDER = "<Object>"
INDEX_PLACEHOLDER = "<N>"

# Longest accepted alias stem.  Keeps the final path well below the classic
# Windows path limit even when the mod folder itself is deeply nested.
_MAX_ALIAS_STEM_LENGTH = 96

# Device names Windows reserves; such a file cannot be created there.
_RESERVED_FILE_STEMS = {
    "con", "prn", "aux", "nul",
    *("com" + str(number) for number in range(1, 10)),
    *("lpt" + str(number) for number in range(1, 10)),
}

# Control characters (including tab/newline) break an INI line.
_CONTROL_CHAR_PATTERN = re.compile(r"[\x00-\x1f\x7f]")


def object_resource_slug(text, limit=24):
    """Turn an arbitrary name into a safe ASCII resource/file name fragment.

    The result is intentionally restricted to ``[A-Za-z0-9_]``: resource names
    and default file names must stay readable for the game and for every INI
    parser, no matter what an object or Submesh happens to be called.
    """
    slug = re.sub(r"[^A-Za-z0-9_]", "_", str(text or ""))
    # Repeated separators only make the name longer without adding meaning.
    slug = re.sub(r"_+", "_", slug).strip("_")
    return (slug or "obj")[:limit]


def _slug_or_placeholder(text, limit):
    """Slug one name fragment, but keep a node display placeholder intact.

    The export pass never passes a placeholder here, so its output is
    unchanged; the node UI uses the same builder with placeholders to show a
    name pattern without inventing a DrawIB or object name.
    """
    value = str(text or "").strip()
    if value in (DRAW_IB_PLACEHOLDER, OBJECT_PLACEHOLDER, INDEX_PLACEHOLDER):
        return value
    return object_resource_slug(value, limit)


def file_resource_stem(draw_ib, object_name, slug_token):
    """Return the generated stem shared by a file resource and its file.

    The slot binding node copies one external image per object, so the stem
    carries the DrawIB scope (split-INI exporters need it) and the object name
    (two objects may bind different images on the same slot).
    """
    return (
        "ResourceTex_"
        + _slug_or_placeholder(draw_ib, 16)
        + "_"
        + _slug_or_placeholder(object_name, 24)
        + "_"
        + str(slug_token or "texture")
    )


def texture_source_suffix(source_path):
    """Return the lower-case image suffix of a source path (default .dds)."""
    suffix = os.path.splitext(str(source_path or "").strip())[1].lower()
    return suffix if suffix in TEXTURE_FILE_SUFFIXES else DEFAULT_TEXTURE_SUFFIX


def normalize_alias_stem(alias):
    """Turn a user alias into a file name stem, or return "" when unused.

    The rules follow what Windows accepts and what an INI line can survive:

    - only the last path component is kept (``a/b/c`` becomes ``c``),
    - a typed image suffix is dropped, because the real suffix has to match
      the copied bytes,
    - characters Windows forbids and control characters become ``_``,
    - leading/trailing spaces and dots are removed (Windows drops a trailing
      dot on its own, which would silently rename the file),
    - reserved device names are prefixed so the file can exist at all.
    """
    text = str(alias or "").strip()
    if not text:
        return ""

    # An alias is a file name, so a pasted path must not create folders.
    text = text.replace("\\", "/").rsplit("/", 1)[-1].strip()

    # Drop a suffix the user typed; ``texture_source_suffix`` decides the real
    # one from the source image, so "hair.dds" and "hair" behave identically.
    stem = text
    while True:
        lowered = stem.lower()
        matched = next((item for item in TEXTURE_FILE_SUFFIXES if lowered.endswith(item)), "")
        # One pass is not enough for a typo like "hair.png.dds"; loop until
        # no known suffix is left (bounded by the suffix list length).
        if not matched:
            break
        stem = stem[: -len(matched)].strip()

    # Forbidden and control characters would make the file impossible to
    # create or would break the INI line that references it.
    stem = _CONTROL_CHAR_PATTERN.sub("_", stem)
    for character in _INVALID_FILENAME_CHARS:
        stem = stem.replace(character, "_")

    # Windows strips trailing dots and spaces from a file name.  Removing them
    # here means the INI and the file on disk always show the same name.
    stem = stem.strip(" .")
    # Collapse a run of underscores the replacements may have produced, but
    # keep the user's own single underscores untouched.
    stem = re.sub(r"_+", "_", stem) if "_" in stem else stem
    stem = stem[:_MAX_ALIAS_STEM_LENGTH].strip(" .")

    if not stem:
        return ""
    if stem.casefold() in _RESERVED_FILE_STEMS:
        stem = "_" + stem
    return stem


def alias_output_filename(alias, source_path):
    """Return the alias as a file name that matches the source image bytes.

    ``source_path`` only supplies the image suffix, so a PNG replacement keeps
    its ``.png`` suffix instead of being announced as a DDS file.
    """
    return alias_output_filename_with_suffix(alias, texture_source_suffix(source_path))


def alias_output_filename_with_suffix(alias, suffix):
    """Return the alias as a file name with an already decided suffix.

    The export pass knows the suffix before the name is needed (a converted
    replacement is always ``.dds``, a raw copy keeps the source suffix), so the
    suffix is passed in instead of being re-derived from a path.
    """
    stem = normalize_alias_stem(alias)
    if not stem:
        return ""
    normalized_suffix = str(suffix or "").lower()
    if normalized_suffix not in TEXTURE_FILE_SUFFIXES:
        normalized_suffix = DEFAULT_TEXTURE_SUFFIX
    return stem + normalized_suffix


def slot_mark_output_filename(draw_ib, submesh_index, mark_name):
    """Return the automatic Slot-mark file name of one marked texture.

    Matches ``M_IniHelper._get_slot_style_texture_filename``; the Submesh index
    is part of the name because the same mark may exist in several Submeshes
    of one DrawIB.
    """
    return str(draw_ib or "DrawIB") + "-" + str(submesh_index) + "-" + str(mark_name or "Texture") + ".dds"


def shared_slot_output_filename(mark_hash, mark_name):
    """Return the automatic SharedSlot-method file name of one marked texture."""
    return str(mark_hash or "00000000") + "_" + str(mark_name or "Texture") + ".dds"


def hash_output_stem(texture_hash, role, draw_ib="", object_scoped=False):
    """Return the generated stem of a Hash Texture Bind row.

    ``object_scoped`` rows bind inside one object's draw call and need their
    own file, so the DrawIB scope is part of the name (exactly like the export
    pass in ``DrawIBModel.resolve_hash_texture_bindings``).
    """
    stem = str(texture_hash or "00000000") + "_" + str(role or "Texture")
    if object_scoped:
        stem = stem + "_" + _slug_or_placeholder(draw_ib, 16)
    return stem


def hash_output_filename(texture_hash, role, draw_ib, suffix, object_scoped):
    """Return the generated file name of a Hash Texture Bind row."""
    return hash_output_stem(texture_hash, role, draw_ib, object_scoped) + str(suffix or DEFAULT_TEXTURE_SUFFIX)


def hash_mark_output_filename(texture_hash, mark_name):
    """Return the familiar generated name of a marked Hash-style texture."""
    return str(texture_hash or "00000000") + "_" + str(mark_name or "Texture") + ".dds"


def global_slot_output_filename(draw_ib, index):
    """Return the generated file name of one Global Slot Texture Bind row.

    The copy stage always converts the replacement to DDS, so this name always
    ends with ``.dds`` even when the chosen file is a PNG.
    """
    return "ResourceGlobalSlot_" + _slug_or_placeholder(draw_ib, 16) + "_" + str(index) + ".dds"


def ensure_ini_encodable(filename, description):
    """Reject a generated name the generated INI file could not store.

    The INI is written with the system encoding of the machine that exports
    the mod (Python's default text mode).  An alias with characters outside
    that encoding would otherwise fail deep inside the INI writer with a hard
    to understand ``UnicodeEncodeError``.  Raising here names the node row
    instead and tells the user how to fix it.
    """
    text = str(filename or "")
    if not text:
        return filename
    encoding = locale.getpreferredencoding(False) or "utf-8"
    try:
        text.encode(encoding)
    except UnicodeEncodeError:
        raise ValueError(
            description + ": the texture file name '" + text
            + "' contains characters the generated INI cannot store with the system encoding '"
            + encoding + "'. Use letters, digits, spaces, `_`, `-` or `.` in the alias."
        )
    if text.isascii():
        return filename
    # Non-ASCII names are allowed on purpose (Chinese users name their files in
    # Chinese), but the game must also read the INI with the same code page.
    print(
        "Texture output name: '" + text + "' contains non-ASCII characters. "
        "It is written with the system encoding '" + encoding + "'; "
        "use ASCII letters if the game shows a broken file name."
    )
    return filename


class TextureOutputNameClaims:
    """Track which generated file name belongs to which source image.

    All generated textures of one Mod share a single ``Textures`` folder, so
    two different images must never be written under one name: the last copy
    would silently win and one object would show the wrong picture.  Default
    names already contain a hash or a DrawIB, but a user alias is free text, so
    a duplicate alias has to be reported instead of accepted.

    The same image under the same name is allowed and keeps the file shared.
    """

    def __init__(self):
        self._owner_by_name = {}

    def claim(self, filename, source_key, description):
        """Reserve one generated file name; raise on a real conflict."""
        text = str(filename or "").strip()
        if not text:
            return ""
        key = text.casefold()
        previous = self._owner_by_name.get(key)
        if previous is None:
            self._owner_by_name[key] = (str(source_key or ""), str(description or ""))
            return text
        if previous[0] == str(source_key or ""):
            # The same image feeds several rows: sharing one file is correct.
            return text
        raise ValueError(
            "Texture file name conflict: '" + text + "' is generated for both "
            + (previous[1] or "another row") + " and " + (str(description) or "another row")
            + ". Give one of them a different alias."
        )
