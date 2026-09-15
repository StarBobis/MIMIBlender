"""
Shared NTMIv1 part helpers.

Both the buffer writer and the INI section builders need the same part
names and resource tokens, so they live in this tiny module to keep the
other two modules free of circular imports.
"""


def resource_token(name: str) -> str:
    """Sanitize a name into a valid INI resource token."""
    return name.replace("-", "_").replace(" ", "_").replace(".", "_")


def part_name(drawib_model, part_index: int, submesh_model) -> str:
    """Build the NTMIv1 part name: {draw_ib}_part{index:02d}"""
    return f"{drawib_model.draw_ib}_part{part_index:02d}"
