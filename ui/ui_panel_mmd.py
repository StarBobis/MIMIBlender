"""MMD model cleanup controls for the MIMITools sidebar.

Only the active mesh's own import hierarchy is inspected. Names are a fallback
for scenes saved without mmd_tools; no optional add-on import is necessary.

Cleanup contract:
- The active object must be a selected mesh in Object Mode.
- A skeleton ancestor distinguishes model geometry from physics meshes.
- Explicit MMD root metadata takes precedence over container names.
- Legacy scenes use exact physics-container names as a fallback.
- Blender-generated numeric suffixes are accepted for repeated imports.
- Traversal stops at the nearest verified model root.
- An enclosing scene organizer is not treated as another model root.
- Only this root and its direct physics branches are deletion targets.
- Physics descendants are removed regardless of viewport visibility.
- Unexpected skeletons or nested models cancel the complete operation.
- Read-only deletion or reparent targets also cancel before any mutation.
- Other retained root children are reconnected rather than discarded.
- Their world transforms are copied before the hierarchy is modified.
- Mesh children remain parented to the original retained armature.
- No mesh, shape-key, material or armature data is explicitly purged.
- Global physics collections are left alone for other imported models.
- Unused-material cleanup touches every selected editable mesh at once.
- Slot removal remaps polygon material indices; shared data is isolated.
- Invalid shape keys are relative keys that no remaining vertex still uses.
- Live Blender undo restores the destructive operation as one step.
"""
import re

import bpy
import numpy as np

from ..i18n.i18n import I18nOperator, tr, translatable
from ..utils.material_cleanup import (
    collect_used_slot_indices,
    remove_unused_material_slots,
)


# Blender adds numeric suffixes when several MMD models share group names.
# Match whole names, never arbitrary substrings such as "my_rigidbodies_mesh".
_PHYSICS_NAMES = re.compile(r"^(joints|rigidbodies)(\.\d+)?$", re.IGNORECASE)
_PHYSICS_TYPES = {'JOINT_GRP', 'RIGID_GRP'}


def _mmd_type(obj):
    # mmd_tools RNA is available only while that optional add-on is enabled.
    # ID properties also cover imported scenes after mmd_tools is disabled.
    return getattr(obj, 'mmd_type', None) or obj.get('mmd_type', 'NONE')


def _is_physics_group(obj):
    # Restrict the name fallback to containers, not visible model geometry.
    return obj.type == 'EMPTY' and (
        _mmd_type(obj) in _PHYSICS_TYPES or _PHYSICS_NAMES.fullmatch(obj.name)
    )


def find_mmd_root(mesh):
    """Find the nearest verified model root, without relying on character names."""
    if mesh is None or mesh.type != 'MESH':
        return None
    # Physics meshes must not enable the main-model cleanup action.
    if _mmd_type(mesh) in {'RIGID_BODY', 'JOINT'}:
        return None
    parent = mesh.parent
    has_armature = False
    while parent is not None:
        # The main mesh must belong to the skeleton branch, not physics groups.
        if _is_physics_group(parent):
            return None
        has_armature = has_armature or parent.type == 'ARMATURE'
        if parent.type == 'EMPTY' and _mmd_type(parent) == 'ROOT':
            return parent if has_armature else None
        # Without metadata, require both a skeleton ancestor and a direct
        # physics container. An ordinary mesh under an empty is not sufficient.
        if parent.type == 'EMPTY' and has_armature:
            if any(_is_physics_group(child) for child in parent.children):
                return parent
        parent = parent.parent
    return None


def remove_redundant_parts(context, mesh):
    """Delete one model's physics branches and reconnect retained children.

    Build and validate the complete deletion set before changing anything.
    Reparenting preserves world transforms, skeleton links and mesh data.
    Shared meshes/materials and global rigid-body collections are never purged.
    """
    root = find_mmd_root(mesh)
    if root is None:
        raise ValueError(tr("Select the main mesh of an imported MMD model"))

    # Only direct physics containers of this root belong to this operation.
    # Iterative traversal handles large imports without Python recursion limits.
    removed = {root}
    pending = [child for child in root.children if _is_physics_group(child)]
    while pending:
        obj = pending.pop()
        # Reject unexpected nested models rather than deleting their skeletons.
        if obj == mesh or obj.type == 'ARMATURE' or _mmd_type(obj) == 'ROOT':
            raise ValueError(tr("Unexpected model inside an MMD physics group; cleanup cancelled"))
        removed.add(obj)
        pending.extend(obj.children)

    # Retained children are reconnected to the nearest surviving ancestor.
    # Usually this unparents the armature; an external parent is kept intact.
    retained = []
    for obj in removed:
        for child in obj.children:
            if child not in removed:
                parent = obj.parent
                while parent in removed:
                    parent = parent.parent
                retained.append((child, parent))

    # Linked/read-only objects cannot be safely deleted or reparented.
    # Refuse the entire operation before any object has been modified.
    touched = removed | {child for child, parent in retained}
    if any(not obj.is_editable for obj in touched):
        raise ValueError(tr("MMD cleanup requires editable local objects"))

    # Read evaluated transforms only after updating the dependency graph.
    # Copy matrices because Blender's mathutils values are live references.
    context.view_layer.update()
    transforms = [(child, parent, child.matrix_world.copy()) for child, parent in retained]
    for child, parent, world in transforms:
        child.parent = parent
        child.parent_type = 'OBJECT'
        child.parent_bone = ''
        child.matrix_parent_inverse.identity()
        child.matrix_world = world

    # One data-API removal avoids selection-dependent operators and hundreds
    # of slow individual dependency-graph updates on physics-heavy models.
    count = len(removed)
    bpy.data.batch_remove(ids=removed)
    context.view_layer.update()
    return count


class MIMI_OT_remove_mmd_redundant_parts(I18nOperator):
    # REGISTER/UNDO makes this destructive action reversible in the live UI.
    bl_idname = 'mimi.remove_mmd_redundant_parts'
    bl_label = 'Delete Redundant Parts'
    bl_description = 'Remove this MMD model\'s joints, rigidbodies and root empty; keep meshes and armature'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        # Object mode prevents editing a mesh while its ancestors are removed.
        mesh = context.active_object
        if context.mode != 'OBJECT' or mesh is None or not mesh.select_get():
            cls.poll_message_set(tr("Select the main MMD mesh in Object Mode"))
            return False
        if find_mmd_root(mesh) is None:
            cls.poll_message_set(tr("Select the main mesh of an imported MMD model"))
            return False
        return True

    def execute(self, context):
        # Validation failures report a useful message without partial deletion.
        try:
            count = remove_redundant_parts(context, context.active_object)
        except ValueError as error:
            self.report({'WARNING'}, str(error))
            return {'CANCELLED'}
        self.report({'INFO'}, tr("Removed {count} MMD redundant objects; meshes and armature preserved").format(count=count))
        return {'FINISHED'}


def _poll_any_editable_mesh(cls, context):
    # The multi-object material cleanup works on every selected editable
    # mesh, so at least one selected mesh must permit local data edits.
    if context.mode == 'OBJECT':
        for obj in context.selected_objects:
            if obj.type == 'MESH' and obj.is_editable and obj.data.is_editable:
                return True
    cls.poll_message_set(tr('Select a mesh in Object Mode'))
    return False


class MIMI_OT_remove_mmd_unused_materials(I18nOperator):
    # Delete slots that no polygon references, on every selected mesh at once.
    # Partial model deletion leaves such stale slots behind on the mesh data.
    bl_idname = 'mimi.remove_mmd_unused_materials'
    bl_label = 'Delete Unused Materials'
    bl_description = 'Remove material slots that no face uses from all selected meshes'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        # Any single editable mesh in the selection is enough to proceed.
        return _poll_any_editable_mesh(cls, context)

    def execute(self, context):
        removed = 0
        for obj in context.selected_objects:
            # Non-mesh and read-only objects simply keep their slots.
            if obj.type != 'MESH' or not obj.is_editable or not obj.data.is_editable:
                continue
            data = obj.data
            used = collect_used_slot_indices(obj)
            # Fast path: every slot is still referenced by some polygon.
            if all(index in used for index in range(len(data.materials))):
                continue
            # Slots live on the mesh datablock; isolate shared data first so
            # linked duplicates keep their original material assignments.
            _make_mesh_single_user(obj)
            removed += remove_unused_material_slots(obj)
        self.report({'INFO'}, tr('Removed {count} unused material slots').format(count=removed))
        return {'FINISHED'}


# These are importer helper groups, not bone weights. Locking is irrelevant:
# ordinary bone groups may also be locked and must always be retained.
_INVALID_VERTEX_GROUPS = ('mmd_edge_scale', 'mmd_vertex_order')


def _poll_editable_mesh(cls, context):
    # Mesh cleanup remains available after the MMD root has been deleted.
    # Operate only on the active selected object, never all selected models.
    mesh = context.active_object
    if context.mode != 'OBJECT' or mesh is None or mesh.type != 'MESH' or not mesh.select_get():
        cls.poll_message_set(tr('Select a mesh in Object Mode'))
        return False
    # Both the object and its mesh data must permit destructive local edits.
    # No implicit library override is created by these simple cleanup tools.
    if not mesh.is_editable or not mesh.data.is_editable:
        cls.poll_message_set(tr('Mesh cleanup requires editable local objects and mesh data'))
        return False
    return True


def _make_mesh_single_user(mesh):
    # Shape keys and vertex weight indices live on shared mesh data.
    # Copy only when necessary to avoid modifying other linked duplicates.
    # Object-level armature links, transforms and vertex-group names survive.
    if mesh.data.users > 1:
        mesh.data = mesh.data.copy()


class MIMI_OT_remove_mmd_shape_keys(I18nOperator):
    # Use Blender's native all-key removal, including Basis and locked keys.
    # UNDO exposes one reversible step in the user's live Blender session.
    bl_idname = 'mimi.remove_mmd_shape_keys'
    bl_label = 'Delete All Shape Keys'
    bl_description = 'Delete all shape keys, including Basis, from the active mesh only'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        # Absence of an MMD root is intentional, not an invalid selection.
        return _poll_editable_mesh(cls, context)

    def execute(self, context):
        # Count before deletion; the Key datablock becomes invalid afterward.
        mesh = context.active_object
        keys = mesh.data.shape_keys
        count = len(keys.key_blocks) if keys else 0
        if count:
            # Single-user copying also duplicates attached shape-key data.
            # The other object's keys and current deformation stay untouched.
            _make_mesh_single_user(mesh)
            mesh.shape_key_clear()
        # Zero-key meshes are harmless no-ops without a needless data copy.
        self.report({'INFO'}, tr('Removed {count} shape keys').format(count=count))
        return {'FINISHED'}


def _collect_invalid_shape_keys(mesh):
    """Return key blocks whose effect vanished together with deleted vertices.

    A relative key block is invalid when every remaining vertex stores the
    same coordinate as its reference key: the block can no longer change the
    mesh. This happens after partial model deletion, which also deletes the
    moved vertices from every key block. The Basis block and absolute
    (non-relative) key blocks are never candidates.
    """
    keys = mesh.data.shape_keys
    if keys is None or not keys.use_relative:
        return []
    vertex_count = len(mesh.data.vertices)
    if vertex_count == 0:
        return []
    # Reference arrays are cached by name because almost every block uses
    # the shared Basis block as its reference.
    reference_arrays = {}
    invalid = []
    for block in keys.key_blocks:
        reference = block.relative_key
        if block == reference:
            # The Basis block is its own reference and must always stay.
            continue
        ref_co = reference_arrays.get(reference.name)
        if ref_co is None:
            ref_co = np.empty(vertex_count * 3, dtype=np.float32)
            reference.data.foreach_get('co', ref_co)
            reference_arrays[reference.name] = ref_co
        block_co = np.empty(vertex_count * 3, dtype=np.float32)
        block.data.foreach_get('co', block_co)
        # The tiny epsilon absorbs float noise from import conversions.
        if np.allclose(block_co, ref_co, rtol=0, atol=1e-6):
            invalid.append(block.name)
    return invalid


class MIMI_OT_remove_mmd_invalid_shape_keys(I18nOperator):
    # Only no-op keys are removed; every key that still moves a vertex,
    # locked or not, stays untouched. UNDO keeps the cleanup reversible.
    bl_idname = 'mimi.remove_mmd_invalid_shape_keys'
    bl_label = 'Delete Invalid Shape Keys'
    bl_description = 'Delete shape keys that no longer move any remaining vertex; keep Basis'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        # The same active-mesh guard as the other shape-key cleanup action.
        return _poll_editable_mesh(cls, context)

    def execute(self, context):
        # Names are collected first: removing blocks shifts the key list.
        mesh = context.active_object
        invalid_names = _collect_invalid_shape_keys(mesh)
        if invalid_names:
            # Shape-key data lives on the shared mesh datablock; isolate it
            # so linked duplicates keep their original keys.
            _make_mesh_single_user(mesh)
            key_blocks = mesh.data.shape_keys.key_blocks
            for name in invalid_names:
                # The single-user copy replaced the datablock, so look the
                # blocks up by name instead of reusing stale references.
                block = key_blocks.get(name)
                if block is not None:
                    mesh.shape_key_remove(block)
        self.report({'INFO'}, tr('Removed {count} invalid shape keys').format(count=len(invalid_names)))
        return {'FINISHED'}


class MIMI_OT_remove_mmd_invalid_vertex_groups(I18nOperator):
    # Match the two exact fixed names; do not delete all locked/empty groups.
    # This intentionally excludes names such as mmd_edge_scale_backup.
    bl_idname = 'mimi.remove_mmd_invalid_vertex_groups'
    bl_label = 'Delete Invalid Vertex Groups'
    bl_description = 'Delete only mmd_edge_scale and mmd_vertex_order from the active mesh; keep other groups'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        # The same selection/editability guards apply to both mesh actions.
        return _poll_editable_mesh(cls, context)

    def execute(self, context):
        # Gather names before removal because group indices change on deletion.
        mesh = context.active_object
        names = [name for name in _INVALID_VERTEX_GROUPS if mesh.vertex_groups.get(name) is not None]
        if names:
            # Removing a group remaps vertex weight indices on the mesh data.
            # Isolate shared data first so another object's bone weights survive.
            _make_mesh_single_user(mesh)
            for name in names:
                group = mesh.vertex_groups.get(name)
                mesh.vertex_groups.remove(group)
        # Group locking does not prevent the explicit data-API removal.
        # No matching names means no mutation and an informative zero count.
        self.report({'INFO'}, tr('Removed {count} MMD helper vertex groups').format(count=len(names)))
        return {'FINISHED'}


@translatable
class MIMI_PT_mmd_model(bpy.types.Panel):
    # Explicit order places this panel after Texture Combiner (10) and before
    # Version Update (99), independent of module registration order.
    bl_label = 'MMD Model Processing'
    bl_idname = 'MIMI_PT_mmd_model'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'MIMITools'
    bl_order = 11
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        # Button captions follow the add-on's language switch immediately.
        self.layout.operator(
            MIMI_OT_remove_mmd_redundant_parts.bl_idname,
            text=tr('Delete Redundant Parts'), icon='TRASH',
        )
        # Stale slots appear after deleting parts of a model's mesh.
        self.layout.operator(
            MIMI_OT_remove_mmd_unused_materials.bl_idname,
            text=tr('Delete Unused Materials'), icon='TRASH',
        )
        # Keep separate actions so users may retain expressions or MMD helpers.
        self.layout.operator(
            MIMI_OT_remove_mmd_shape_keys.bl_idname,
            text=tr('Delete All Shape Keys'), icon='TRASH',
        )
        # Only no-op keys are removed; keys that still move vertices stay.
        self.layout.operator(
            MIMI_OT_remove_mmd_invalid_shape_keys.bl_idname,
            text=tr('Delete Invalid Shape Keys'), icon='TRASH',
        )
        # This button targets the two named importer groups, not bone groups.
        self.layout.operator(
            MIMI_OT_remove_mmd_invalid_vertex_groups.bl_idname,
            text=tr('Delete Invalid Vertex Groups'), icon='TRASH',
        )


# Register every operator before the panel that draws their buttons.
# The draw order above must mirror this order; a test asserts the pairing.
_CLASSES = (
    MIMI_OT_remove_mmd_redundant_parts,
    MIMI_OT_remove_mmd_unused_materials,
    MIMI_OT_remove_mmd_shape_keys,
    MIMI_OT_remove_mmd_invalid_shape_keys,
    MIMI_OT_remove_mmd_invalid_vertex_groups,
    MIMI_PT_mmd_model,
)


def register():
    # Keep this small feature independent of the optional mmd_tools add-on.
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    # Reverse registration order so no panel references a removed operator.
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
