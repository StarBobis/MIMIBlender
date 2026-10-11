"""Resolve Submesh defaults after connected Slot and Hash resolution.

Every physical default captures and restores the incoming resource per draw.
The shared draw writer places defaults below local overrides for all exporters.
"""
from .gimi_texture_slots import get_gimi_texture_slot
from .global_config import GlobalConfig
from ..texcomb.core.dds_match import DDSReplacementStage


def collect_global_slots(tree):
    """Collect globals in nested groups once, including unconnected nodes."""
    from ..blueprint.blueprint_node_global_slot import scan_slot_marks
    # Rescan at export time because the workspace may have changed since refresh.
    # Group traversal includes nodes that have no links to the object chain.
    # Pointer identity prevents cycles and duplicate visits to shared groups.
    # Muted groups withdraw every default inside them.
    marks = scan_slot_marks()
    rows, visited = [], set()

    def visit(current):
        if current is None or current.as_pointer() in visited:
            return
        visited.add(current.as_pointer())
        for node in current.nodes:
            if node.mute:
                continue
            if node.bl_idname == 'MIMINode_Texture_Global':
                for item in node.items:
                    # Untouched, cleared and disabled rows do not own a layer.
                    # Validate against live marks, not just the last UI refresh.
                    if not item.enabled or not item.file_path:
                        continue
                    if item.identity not in marks:
                        raise ValueError('Global Slot: stale target ' + item.name)
                    # Read target metadata from the live scan, not editable display fields.
                    # The configured file still comes from the saved user choice.
                    # Relative Blender paths are resolved before filesystem validation.
                    submesh, mark, original = marks[item.identity]
                    rows.append(dict(submesh=submesh, slot=mark['slot'], mark_name=mark['name'],
                                     original_path=original, file_path=__import__('bpy').path.abspath(item.file_path),
                                     force_original_size=item.force_original_size))
            if node.bl_idname == 'SSMTBlueprintGroupNode':
                visit(getattr(node, 'node_tree', None))
    visit(tree)
    return rows


def apply_global_slots(model, rows):
    """Build separate resources for each Submesh/slot, never SharedSlot hashes."""
    # Each DrawIB consumes only rows belonging to its selected Submeshes.
    # Global manager scope must not spread a SharedSlot by texture hash.
    # Jobs are attached to this model for the later staged texture-copy pass.
    # Explicit bindings work even when automatic texture output is disabled.
    selected = [row for row in rows if any(sm.submesh_name == row['submesh'] for sm in model.submesh_model_list)]
    model.exact_texture_jobs = {}
    # Preflight every image before registering any generated file or resource.
    # Copying happens later through the same exporter-local namespace pipeline.
    with DDSReplacementStage() as stage:
        for row in selected:
            stage.prepare(row['file_path'], row['original_path'], row['force_original_size'])
    # GIMI aliases are normalized before checking duplicate ownership.
    # Two labels for one semantic input still conflict within one Submesh.
    # Physical slots use the validated register spelling as their ownership key.
    # Other Submeshes may independently own the same physical slot.
    seen = set()
    for index, row in enumerate(selected):
        logical = get_gimi_texture_slot(row['mark_name']) if GlobalConfig.logic_name == 'GIMI' else None
        key = (row['submesh'], logical or row['slot'])
        if key in seen:
            raise ValueError('Global Slot: conflicting defaults for ' + str(key))
        seen.add(key)
        from ..model.drawib_model import OBJECT_TEXTURE_SLOT_PATTERN
        if not logical and OBJECT_TEXTURE_SLOT_PATTERN.match(row['slot']) is None:
            raise ValueError('Global Slot: invalid physical slot ' + row['slot'])
        # Resource identity includes the DrawIB and Submesh target. Shared hashes
        # on two Submeshes can therefore receive two independent replacements.
        # Resource names are generated rather than copied from source basenames.
        # Names carry DrawIB scope to survive split-INI exporters.
        # Every generated target is DDS, regardless of replacement extension.
        # The copy stage uses the original metadata recorded in the job.
        resource = 'ResourceGlobalSlot_' + model._object_texture_resource_slug(model.draw_ib, 16) + '_' + str(index)
        filename = resource + '.dds'
        model.object_texture_binding_resource_list.append((resource, filename))
        model.object_texture_binding_file_list.append((resource, row['file_path'], filename))
        model.exact_texture_jobs[resource] = row
        for submesh in model.submesh_model_list:
            if submesh.submesh_name != row['submesh']:
                continue
            for draw in submesh.drawcall_model_list:
                if logical:
                    # The semantic adapter merges these defaults with local MARK
                    # overrides before calling GIMI SetTextures once per draw.
                    defaults = getattr(draw, 'global_gimi_texture_defaults', {})
                    defaults[logical] = resource
                    draw.global_gimi_texture_defaults = defaults
                    continue
                # Draws execute sequentially, so this holder can be reused per target.
                # Capture happens before any local override for this draw.
                # Reverse restoration unwinds local state before global default state.
                # Empty declarations are reference holders, not file-backed textures.
                # No replacement remains bound when the next Submesh starts drawing.
                backup = resource + '_Backup'
                # Declare the reference holder in the same INI namespace.
                model.object_texture_binding_resource_list.append((backup, ''))
                defaults = getattr(draw, 'global_texture_slot_lines', [])
                defaults.extend([backup + ' = ref ' + row['slot'], row['slot'] + ' = ' + resource])
                draw.global_texture_slot_lines = defaults
                restores = getattr(draw, 'global_texture_slot_restore_lines', [])
                restores.insert(0, row['slot'] + ' = ' + backup)
                draw.global_texture_slot_restore_lines = restores
