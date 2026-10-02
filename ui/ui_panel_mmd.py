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
- Live Blender undo restores the destructive operation as one step.
"""
import re

import bpy

from ..i18n.i18n import I18nOperator, tr, translatable


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
        # Keep separate actions so users may retain expressions or MMD helpers.
        self.layout.operator(
            MIMI_OT_remove_mmd_shape_keys.bl_idname,
            text=tr('Delete All Shape Keys'), icon='TRASH',
        )
        # This button targets the two named importer groups, not bone groups.
        self.layout.operator(
            MIMI_OT_remove_mmd_invalid_vertex_groups.bl_idname,
            text=tr('Delete Invalid Vertex Groups'), icon='TRASH',
        )


# Register every operator before the panel that draws their buttons.
_CLASSES = (
    MIMI_OT_remove_mmd_redundant_parts,
    MIMI_OT_remove_mmd_shape_keys,
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
