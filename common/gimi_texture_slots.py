"""Name-driven GIMI texture API helpers, independent of Blender.

MarkName is the contract: the captured physical slot is not the runtime
slot for known textures. Unknown names keep their explicit physical slot.
No filename guessing or additional workspace metadata is required.
"""

# Exact aliases preserve existing MMT marks and gui_collect's Diffuse name.
# Keep this table aligned with MMT's gimi_texture_slots service.
GIMI_TEXTURE_SLOTS = {
    "diffusemap": r"Resource\GIMI\Diffuse",
    "diffuse": r"Resource\GIMI\Diffuse",
    "normalmap": r"Resource\GIMI\NormalMap",
    "lightmap": r"Resource\GIMI\Lightmap",
    "natlanglow": r"Resource\GIMI\NatlanGlow",
    "natlantattoo": r"Resource\GIMI\NatlanTattoo",
}
GIMI_SET_TEXTURES = r"run = CommandList\GIMI\SetTextures"


def get_gimi_texture_slot(mark_name):
    """Return the logical API resource, or None for a physical mark."""
    return GIMI_TEXTURE_SLOTS.get(str(mark_name or "").strip().casefold())


def texture_binding_key(binding, is_gimi=False):
    """Merge GIMI MARK rows by semantic; other rows still merge by slot.

    This preserves the closest-node-wins rule without confusing two
    captured slots that happen to carry the same logical texture.
    """
    if is_gimi and binding.get("source_type") == "MARK":
        logical_slot = get_gimi_texture_slot(binding.get("mark_name"))
        if logical_slot:
            return logical_slot
    return str(binding.get("slot", "")).strip().lower()


def collect_gimi_texture_bindings(markup_list):
    """Return logical resources and physical fallback lines for one draw.

    Different images for one logical slot cannot be selected safely.
    Reject that ambiguity rather than silently using the last mark.
    Hash marks stay entirely outside this per-draw binding pipeline.
    """
    logical = {}
    physical = []
    for mark in markup_list:
        if mark.mark_type not in ("Slot", "SharedSlot"):
            continue
        resource = mark.get_resource_name()
        target = get_gimi_texture_slot(mark.mark_name)
        if target:
            previous = logical.get(target)
            if previous is not None and previous != resource:
                raise ValueError("GIMI texture slot has conflicting resources: " + target)
            logical[target] = resource
        else:
            # Physical fallbacks run after the API so their explicit intent wins.
            line = mark.mark_slot + " = " + resource
            if line not in physical:
                physical.append(line)
    return logical, physical


def gimi_texture_lines(logical, physical):
    """Submit all effective semantics, then apply explicit physical fallbacks.

    SetTextures clears its logical resources. A subsequent object must
    submit its complete effective set again, not only its overrides.
    """
    lines = [target + " = ref " + resource for target, resource in logical.items()]
    if logical:
        lines.append(GIMI_SET_TEXTURES)
    return lines + physical
