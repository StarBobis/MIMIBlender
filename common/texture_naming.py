"""Texture 节点的默认命名规则。"""

import re


def normalize_texture_resource_name(resource_name: str) -> str:
    """Return an INI resource name with the required ``Resource`` prefix."""
    name = str(resource_name or "").strip()
    # ``[Resource]`` is effectively a bare/invalid section name.  Treat a
    # prefix-only value exactly like an omitted value so callers fall back to
    # the hash-bearing default name.
    if not name or name.casefold() == "resource":
        return ""
    return name if name.lower().startswith("resource") else f"Resource{name}"


def normalize_texture_filename(filename: str) -> str:
    """Return a generated texture filename with a .dds suffix."""
    name = str(filename or "").strip()
    if not name or name.casefold() == ".dds":
        return ""
    return name if name.lower().endswith(".dds") else f"{name}.dds"


def normalize_texture_role(mark_name: str) -> str:
    role = re.sub(r"[^A-Za-z0-9]+", "_", str(mark_name or "").strip()).strip("_")
    return role or "Texture"


def default_texture_resource_name(texture_hash: str, mark_name: str = "") -> str:
    return normalize_texture_resource_name(
        f"Resource_{normalize_texture_role(mark_name)}_{texture_hash or 'unnamed'}"
    )


def default_texture_filename(texture_hash: str, mark_name: str = "") -> str:
    return normalize_texture_filename(
        f"{texture_hash or 'unnamed'}_{normalize_texture_role(mark_name)}"
    )
