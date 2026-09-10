'''
Blueprint file drop support:
- Dropping a .ib/.buf/.txt creates an object info node (SSMTNode_Object_Info) at the drop
  position, parsing submesh_name from the filename when possible (the new DrawIB-Component
  format, old-format long names, and names with a LOD prefix are all handled).

Files dropped from the OS into the Node Editor are handled through bpy.types.FileHandler;
it only takes effect while the current node tree is SSMTBlueprintTreeType and does not
affect other editors.
'''
import os

import bpy

from ..i18n.i18n import I18nOperator, tr, translatable
from ..workspace.ssmt_workspace import WorkSpaceModel


MESH_EXTENSIONS = {".ib", ".buf", ".txt"}

DROP_STACK_OFFSET_Y = 60.0


def is_ssmt_blueprint_context(context) -> bool:
    '''Whether the current context is a node editor showing an SSMT Blueprint.'''
    area = getattr(context, "area", None)
    if not area or area.type != 'NODE_EDITOR':
        return False
    region = getattr(context, "region", None)
    if not region or region.type != 'WINDOW':
        return False
    space = getattr(context, "space_data", None)
    tree = getattr(space, "node_tree", None) if space else None
    return bool(tree) and getattr(tree, "bl_idname", "") == 'SSMTBlueprintTreeType'


def parse_mesh_filename(filepath: str) -> str:
    '''Parse submesh_name from a .ib/.buf/.txt filename when possible.

    Returns the normalized new-format name (e.g. LOD0.94517393-0) when
    recognized, otherwise falls back to the raw filename (without extension).
    '''
    base_name = os.path.splitext(os.path.basename(filepath))[0]
    try:
        ws_model = WorkSpaceModel()
        parsed = ws_model.parse_any_format_name(base_name)
    except Exception:
        parsed = None
    if parsed and parsed.get("draw_ib"):
        submesh_name = f"{parsed['draw_ib']}-{parsed['component']}"
        lod_name = str(parsed.get("lod") or "")
        if lod_name:
            submesh_name = f"{lod_name}.{submesh_name}"
        return submesh_name
    return base_name


class SSMT_OT_BlueprintFileDrop(I18nOperator):
    '''Drop files onto the SSMT Blueprint, creating matching nodes at the release position'''
    bl_idname = "ssmt.blueprint_file_drop"
    bl_label = "Drop Files onto the SSMT Blueprint"
    bl_options = {'UNDO'}

    # FileHandler writes a single file into filepath; to receive multiple files,
    # both directory and files must be declared (names and types are part of Blender's convention).
    filepath: bpy.props.StringProperty(  # type: ignore
        subtype='FILE_PATH',
        options={'HIDDEN', 'SKIP_SAVE'},
    )
    directory: bpy.props.StringProperty(  # type: ignore
        subtype='DIR_PATH',
        options={'HIDDEN', 'SKIP_SAVE'},
    )
    files: bpy.props.CollectionProperty(  # type: ignore
        type=bpy.types.OperatorFileListElement,
        options={'HIDDEN', 'SKIP_SAVE'},
    )

    def _filepaths(self):
        '''Return all file paths Blender passed in for this drop.'''
        if self.directory and len(self.files) > 0:
            return [
                os.path.join(self.directory, file_element.name)
                for file_element in self.files
                if file_element.name
            ]
        return [self.filepath] if self.filepath else []

    def _create_mesh_info_node(self, tree, location, filepath):
        node = tree.nodes.new(type='SSMTNode_Object_Info')
        node.location = location
        node.submesh_name = parse_mesh_filename(filepath)
        return node

    def invoke(self, context, event):
        space = getattr(context, "space_data", None)
        tree = getattr(space, "node_tree", None) if space else None
        if tree is None or getattr(tree, "bl_idname", "") != 'SSMTBlueprintTreeType':
            return {'CANCELLED'}

        # FileHandler's poll_drop is restricted to the WINDOW region, so the
        # mouse_region_x/y here are the canvas area coordinates at release time.
        region = getattr(context, "region", None)
        if region is None or region.type != 'WINDOW':
            return {'CANCELLED'}

        # Do not call region.view2d.region_to_view directly: node coordinates
        # must also account for Blender's UI_SCALE_FAC. This SpaceNodeEditor
        # method performs the exact same conversion as the native NODE_OT_add_file.
        space.cursor_location_from_region(
            event.mouse_region_x,
            event.mouse_region_y,
        )
        base_location = tuple(space.cursor_location)

        filepaths = self._filepaths()
        if not filepaths:
            return {'CANCELLED'}

        for other_node in tree.nodes:
            other_node.select = False

        created_nodes = []
        for stack_index, filepath in enumerate(filepaths):
            location = (
                base_location[0],
                base_location[1] - stack_index * DROP_STACK_OFFSET_Y,
            )
            extension = os.path.splitext(filepath)[1].lower()
            if extension not in MESH_EXTENSIONS:
                continue
            node = self._create_mesh_info_node(tree, location, filepath)
            node.select = True
            created_nodes.append(node)

        if not created_nodes:
            return {'CANCELLED'}

        tree.nodes.active = created_nodes[0]

        if len(created_nodes) == 1:
            message = tr("Created node from file: {name}").format(
                name=os.path.basename(filepaths[0]),
            )
        else:
            message = tr("Created {count} nodes from files").format(
                count=len(created_nodes),
            )
        self.report({'INFO'}, message)
        return {'FINISHED'}


classes = [SSMT_OT_BlueprintFileDrop]

@translatable
class SSMT_FH_BlueprintFileDrop(bpy.types.FileHandler):
    '''Handle files dropped from the OS into the SSMT Blueprint editor'''
    bl_idname = "SSMT_FH_BlueprintFileDrop"
    bl_label = "Drop Files onto the SSMT Blueprint"
    bl_import_operator = "ssmt.blueprint_file_drop"
    bl_file_extensions = ".ib;.buf;.txt"

    @classmethod
    def poll_drop(cls, context):
        return is_ssmt_blueprint_context(context)

classes.append(SSMT_FH_BlueprintFileDrop)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
