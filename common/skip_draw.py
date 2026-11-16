"""
Shared helpers for the blueprint "Skip Draw" switch.

A ticked object marks its whole Submesh: the generated INI keeps the game's
own draw skipped and never re-issues it, so the Submesh disappears while the
mod is enabled.  The state has to look identical to several readers, so it
lives here instead of being re-implemented per preset:

- the blueprint parser stores one flag on every DrawCallModel,
- SubMeshModel and the WWMI Submesh views aggregate those flags,
- every game exporter asks is_submesh_skipped() and writes one of the two
  INI layouts below,
- validate_skip_draw() rejects the combinations the INI cannot express.

The module also owns the per-Submesh match identity line every override
needs: append_match_index_count() is the single guarded writer of
"match_index_count = N", so no preset can emit an unknown (-1 or 0) index
count and no preset can forget the line either.

The module deliberately imports nothing at module scope: several test
harnesses load the addon by file path without the addon package, so an
import-time dependency would make every one of them stub this file.
"""


# Comment written into every hidden Submesh section. Kept ASCII on purpose:
# the INI is parsed by 3Dmigoto on Windows and must never depend on the
# Blender UI language or on a modder's object names.
SKIP_DRAW_COMMENT = "; Skip Draw:"


def get_submesh_display_name(submesh_model) -> str:
    """Return the printable Submesh name for comments and error messages.

    SubMeshModel exposes display_str (alias aware) while the WWMI Submesh
    views only carry submesh_name, so both are accepted.
    """
    display_str = str(getattr(submesh_model, "display_str", "") or "").strip()
    if display_str:
        return display_str
    return str(getattr(submesh_model, "submesh_name", "") or "").strip()


def aggregate_skip_draw(drawcall_model_list):
    """Fold the per-object Skip Draw flags of one Submesh into one state.

    Returns (skip_draw, marked_owner_list, unmarked_owner_list).

    The INI acts per Submesh (one hash plus one match_first_index), so a
    single marked object hides the whole Submesh.  The two owner name lists
    keep the export warning precise instead of hiding other objects silently.
    """
    marked_owner_list = []
    unmarked_owner_list = []

    for drawcall_model in drawcall_model_list:
        # Plain attribute access keeps this usable with the WWMI Submesh views,
        # which are SimpleNamespace objects, and with older DrawCallModels.
        owner_name = str(getattr(drawcall_model, "obj_name", "") or "")
        if bool(getattr(drawcall_model, "skip_draw", False)):
            marked_owner_list.append(owner_name)
        else:
            unmarked_owner_list.append(owner_name)

    return bool(marked_owner_list), marked_owner_list, unmarked_owner_list


def is_submesh_skipped(submesh_model) -> bool:
    """Return True when the blueprint hides this Submesh.

    One predicate for every exporter, so a preset can never disagree with the
    blueprint about what "Skip Draw" means.
    """
    return bool(getattr(submesh_model, "skip_draw", False))


def append_skip_draw_comment(section, submesh_model):
    """Append the explanation line of an already open hidden section.

    The caller closes the section itself because some presets need an extra
    endif (YYSLS wraps every Submesh in "if $costume_mods").
    """
    section.append(
        SKIP_DRAW_COMMENT
        + " "
        + get_submesh_display_name(submesh_model)
        + " is not drawn by this mod"
    )


def normalize_match_index_count(match_index_count) -> int:
    """Return the recorded index count as a positive int, or 0 when unknown.

    The import side stores -1 (and occasionally 0) for "this Submesh has no
    resolved IndexCount": SubMeshModel.match_index_count starts at -1 and is
    only corrected when the workspace can resolve the value.  A 3Dmigoto
    override can never match such a value, so both are normalized to 0 here
    and every caller must read 0 as "do not write the line".
    """
    # Strings arrive from blueprint object names and from imported JSON, so
    # one normalizer keeps every preset on the same definition of "unknown".
    try:
        match_index_count = int(match_index_count)
    except (TypeError, ValueError):
        return 0
    if match_index_count <= 0:
        return 0
    return match_index_count


def append_match_index_count_value(section, match_index_count):
    """Append "match_index_count = N" when the Submesh's count is known.

    3Dmigoto matches a draw by both first index and index count, so writing
    the count makes the override hit exactly the draw range it replaces
    instead of every draw that happens to start at the same first index.
    Unknown counts (see normalize_match_index_count) write nothing, which
    keeps the historical first-index-only matching for those Submeshes.

    Callers that hold a plain number (the IdentityV Submesh dictionary)
    use this variant; everything else calls append_match_index_count().
    """
    match_index_count = normalize_match_index_count(match_index_count)
    # A zero count is the 3Dmigoto default meaning "filter not set", and a
    # real draw never has IndexCount 0, so writing it would disable the match.
    if match_index_count > 0:
        section.append("match_index_count = " + str(match_index_count))


def append_match_index_count(section, submesh_model):
    """Write the match_index_count line of one Submesh override.

    Every game exporter calls this right after its match_first_index line,
    so no preset can forget the line and no preset can disagree about the
    guard.  The value comes from SubMeshModel.match_index_count, which the
    import side fills from SubMeshJson.IndexCount.

    getattr keeps the Blender-free test stand-ins working: a stand-in that
    only carries the identity fields it uses is treated as "count unknown".
    """
    append_match_index_count_value(section, getattr(submesh_model, "match_index_count", 0))


def append_hidden_submesh_section(section, draw_ib, section_name_suffix, first_index, submesh_model):
    """Write one complete hidden Submesh section and close it.

    Used by presets whose per-Submesh section does not open with
    handling = skip, because they already skip the whole DrawIB once.  The
    section keeps only what the game needs to match the draw and skip it;
    index buffer, texture slots and draw calls are omitted on purpose.
    """
    section.append("[TextureOverride_" + str(section_name_suffix) + "]")
    section.append("hash = " + str(draw_ib))
    section.append("match_first_index = " + str(first_index))
    # Hiding a Submesh needs the same exact match as replacing it, otherwise
    # a neighboring draw with the same first index could be hidden by mistake.
    append_match_index_count(section, submesh_model)
    section.append("handling = skip")
    append_skip_draw_comment(section, submesh_model)
    section.new_line()


def validate_skip_draw(drawib_model_list):
    """Check the Skip Draw state of every DrawIB before any file is written.

    Two behaviours, both intentional:

    - a warning when only some objects of a hidden Submesh are marked, because
      the whole Submesh disappears while those objects still ship data,
    - a hard error when the hidden Submesh takes part in a feature that cannot
      be expressed without its draw (Position.buf animation frames, or the
      cross-IB rendering that captures VB backups in the guest section).

    Raising here keeps the export silent-free: no half-hidden mod is written.
    """
    # Imported lazily: this module must stay importable without the addon's
    # logging stack (several Blender-free test harnesses load it by path).
    from ..utils.log_utils import LOG

    # Cross-IB relations are derived from the parsed draw calls, so the check
    # also covers a host Submesh that another DrawIB draws into.
    guest_submesh_name_set = set()
    host_submesh_name_set = set()
    frame_submesh_name_set = set()

    for drawib_model in drawib_model_list:
        for submesh_model in getattr(drawib_model, "submesh_model_list", []):
            # Minimal Submesh stand-ins used by tests and by presets that build
            # their own views may not carry a draw call list at all.
            for drawcall_model in getattr(submesh_model, "drawcall_model_list", []):
                host_submesh_name = str(getattr(drawcall_model, "cross_render_at_submesh", "") or "")
                if host_submesh_name:
                    # This draw leaves its own section and is issued in the host
                    # section, which needs the VB backup captured here.
                    guest_submesh_name_set.add(str(getattr(submesh_model, "submesh_name", "") or ""))
                    host_submesh_name_set.add(host_submesh_name)

        # Time Position Switch frames: {timeline variable: {frame: [draw, ...]}}.
        for frame_dict in getattr(drawib_model, "time_pos_frame_groups", {}).values():
            for frame_drawcall_model_list in frame_dict.values():
                for frame_drawcall_model in frame_drawcall_model_list:
                    frame_submesh_name_set.add(str(getattr(frame_drawcall_model, "match_submesh_name", "") or ""))

    for drawib_model in drawib_model_list:
        draw_ib = str(getattr(drawib_model, "draw_ib", "") or "")

        for submesh_model in getattr(drawib_model, "submesh_model_list", []):
            if not is_submesh_skipped(submesh_model):
                continue

            submesh_name = str(getattr(submesh_model, "submesh_name", "") or "")

            if submesh_name in frame_submesh_name_set:
                raise ValueError(
                    "Skip Draw: Submesh '" + submesh_name + "' of DrawIB " + draw_ib
                    + " is used by a Position.buf Based Dynamic Mod frame; "
                    + "turn Skip Draw off for it, or use the DrawIndex Based Dynamic Mod node"
                )

            if submesh_name in guest_submesh_name_set or submesh_name in host_submesh_name_set:
                raise ValueError(
                    "Skip Draw: Submesh '" + submesh_name + "' of DrawIB " + draw_ib
                    + " is used by Cross-IB rendering; "
                    + "remove that cross-IB pair, or turn Skip Draw off for it"
                )

            # Mixed marks: the whole Submesh is hidden, so tell the user which
            # objects of it were not marked. Object names may be non-ASCII, so
            # they only go into the log and never into the INI.
            # SubMeshModel precomputes the list; the WWMI views and the test
            # stand-ins do not, so the fallback keeps both paths working.
            unmarked_owner_list = getattr(submesh_model, "skip_draw_unmarked_owner_list", None)
            if unmarked_owner_list is None:
                unmarked_owner_list = [
                    str(drawcall_model.obj_name)
                    for drawcall_model in getattr(submesh_model, "drawcall_model_list", [])
                    if not bool(getattr(drawcall_model, "skip_draw", False))
                ]
            if unmarked_owner_list:
                LOG.warning(
                    "Skip Draw: the whole Submesh '" + submesh_name + "' of DrawIB " + draw_ib
                    + " is hidden, but these objects of it are not marked: "
                    + ", ".join(unmarked_owner_list)
                )
