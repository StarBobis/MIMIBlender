"""
Per-DrawIB symbol scoping for the WWMI preset.

Why this module exists
----------------------
WWMI exports one INI per DrawIB, but 3Dmigoto loads every INI of a mod into
ONE global namespace:

* ``[Constants]`` globals are collected across all files and a repeated name is
  dropped with "WARNING: Redeclaration of ..." (IniHandler.cpp, the
  ``command_list_globals.emplace`` branch).  Only the first declaration wins.
* Sections are stored in a case insensitive map keyed by their name, so a
  duplicated ``[ResourceX]`` section is only read once - the first parsed copy
  wins and every reference in the mod then points at that copy.  (Duplicate
  ``[TextureOverride...]`` sections are the exception: those are collected per
  hash, which is why the mod can override several draw ranges.)
* Files are parsed in case insensitive alphabetical order of their file name,
  so without scoping the "winner" is just the alphabetically first DrawIB.

A DrawIB that loses that race binds its draw calls to another DrawIB's vertex
buffers and shape key resources.  Giving every draw-range specific symbol a
per-DrawIB suffix removes the race completely.

What must NOT be scoped
-----------------------
``$\\WWMIv1\\...`` variables and ``Resource\\WWMIv1\\...`` resources belong to
the WWMI runtime itself.  The runtime reads them by those exact names, so they
are the one thing a mod is not allowed to rename.
"""

# The WWMI runtime namespace. Names under it are dictated by the installed
# WWMI package and must stay untouched by the scoping helpers below.
WWMI_RUNTIME_NAMESPACE = "\\WWMIv1\\"

# The runtime version the generated mod asks for. WWMI disables a mod and shows
# a notification when the installed runtime is older than this value, which is
# the safe behaviour: an older runtime is missing part of the API used here.
# Keep it in sync with the WWMI package release the generator is tested with.
WWMI_REQUIRED_RUNTIME_VERSION = "1.00"


def scoped_name(name: str, draw_ib: str) -> str:
    """Return a WWMI symbol name that is unique for one DrawIB.

    Used for 3Dmigoto section names and global variables. The suffix is the
    DrawIB itself, which is what the user already sees in the generated file
    names, so an INI stays readable.
    """
    return str(name) + "_" + str(draw_ib)


def scoped_global(name: str, draw_ib: str) -> str:
    """Return a ``global`` variable line head that is unique for one DrawIB.

    ``global`` / ``global persist`` declarations are written by the caller; this
    helper only builds the variable name so both stay consistent.
    """
    return "$" + scoped_name(name, draw_ib)


def scoped_section(name: str, draw_ib: str) -> str:
    """Return a ``[SectionName]`` header that is unique for one DrawIB."""
    return "[" + scoped_name(name, draw_ib) + "]"


def is_runtime_symbol(name: str) -> bool:
    """Whether a symbol belongs to the WWMI runtime and must not be scoped.

    Kept as a guard for tests: a mistake that renames a runtime symbol makes
    the mod look correct in Blender and fail silently in the game.
    """
    text = str(name or "")
    return "WWMIv1" in text
