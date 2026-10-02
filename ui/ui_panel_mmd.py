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


# Register the operator before the panel that draws its button.
_CLASSES = (MIMI_OT_remove_mmd_redundant_parts, MIMI_PT_mmd_model)


def register():
    # Keep this small feature independent of the optional mmd_tools add-on.
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    # Reverse registration order so no panel references a removed operator.
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
