'''
Quick preview texture application
Shows preview textures directly from the DedupedTextures folder,
then applies the selected texture to objects quickly.
This flow is not part of the automatic texture ini workflow.
It is for preview display only.
'''

import bpy
import os
import shutil
from bpy.props import StringProperty, CollectionProperty, IntProperty, BoolProperty, EnumProperty
from bpy.types import Operator, Panel, PropertyGroup, UIList
from bpy_extras.io_utils import ImportHelper
import bpy.utils.previews

from ..common.global_config import GlobalConfig
from ..i18n.i18n import I18nOperator, tr, translatable

from ..utils.json_utils import JsonUtils
from ..utils.collection_utils import CollectionUtils,CollectionColor
from ..utils.material_texture_utils import apply_image_texture_to_material

# Stores the preview image collection
fast_preview_collections = {}

# LOD enum cache
_lod_enum_cache: list[tuple[str, str, str]] = []


def _get_lod_enum_items(self, context):
    global _lod_enum_cache
    return _lod_enum_cache


def _refresh_lod_enum_cache():
    global _lod_enum_cache
    _lod_enum_cache.clear()
    try:
        from ..workspace.ssmt_workspace import SSMTWorkSpace
        lod_folder_paths = SSMTWorkSpace.get_lod_folderpath_list()
        if lod_folder_paths:
            _lod_enum_cache = [
                (os.path.basename(p), os.path.basename(p), "")
                for p in lod_folder_paths
            ]
        else:
            _lod_enum_cache = [("", tr("No LOD folder"), tr("No LOD folder found under the current workspace"))]
    except Exception as e:
        print(f"Failed to refresh LOD list: {e}")
        _lod_enum_cache = [("", tr("No LOD folder"), tr("Refresh failed"))]


def get_workspace_preview_texture_folder(lod_name: str = ""):
    GlobalConfig.read_from_main_json_ssmt4()

    workspace_folder_path = GlobalConfig.path_workspace_folder()
    folder_name = "DedupedTextures"

    # If an LOD is specified, look under that LOD folder
    if lod_name:
        preview_folder_path = os.path.join(workspace_folder_path, lod_name, folder_name + "\\")
        if os.path.exists(preview_folder_path):
            return preview_folder_path, folder_name

    # Fallback: search the workspace root directly
    preview_folder_path = os.path.join(workspace_folder_path, folder_name + "\\")
    if os.path.exists(preview_folder_path):
        return preview_folder_path, folder_name

    return "", folder_name

# Defines the image list item
class MIMIImportTexture_ImageListItem(PropertyGroup):
    name: StringProperty(name="Image Name") # type: ignore
    filepath: StringProperty(name="File Path") # type: ignore

# Custom UI list that displays images and thumbnails
class MIMIUL_FastImportTextureList(UIList):
    # Explicit idname that follows the Blender "_UL_" naming convention;
    # otherwise the name derived from the class triggers a register warning.
    bl_idname = "MIMI_UL_fast_import_texture_list"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        pcoll = fast_preview_collections["main"]
        
        if self.layout_type in {'DEFAULT', 'Expand'}:
            # Try to fetch the preview icon
            if item.name in pcoll:
                layout.template_icon(icon_value=pcoll[item.name].icon_id, scale=1.0)
            else:
                layout.label(text="", icon='IMAGE_DATA')
            
            layout.label(text=item.name)
            
        elif self.layout_type in {'GRID'}:
            layout.alignment = 'CENTER'
            if item.name in pcoll:
                layout.template_icon(icon_value=pcoll[item.name].icon_id, scale=6.0)
            else:
                layout.label(text="", icon='IMAGE_DATA')


# Refresh LOD list
class SSMT_ImportTexture_WM_OT_RefreshLODList(I18nOperator):
    bl_idname = "mimi.refresh_lod_list"
    bl_label = "Refresh LOD List"
    bl_description = "Rescan the LOD folders under the current workspace"

    def execute(self, context):
        _refresh_lod_enum_cache()
        # If an LOD exists and none is currently selected, default to the first one
        if _lod_enum_cache and _lod_enum_cache[0][0]:
            if not context.scene.mimi_fast_texture_lod or context.scene.mimi_fast_texture_lod not in [e[0] for e in _lod_enum_cache]:
                context.scene.mimi_fast_texture_lod = _lod_enum_cache[0][0]
        self.report({'INFO'}, tr("LOD list refreshed, found {count} LOD folders.").format(count=len([e for e in _lod_enum_cache if e[0]])))
        return {'FINISHED'}


# Auto-detect and set the DedupedTextures folder
class SSMT_ImportTexture_WM_OT_AutoDetectTextureFolder(I18nOperator):
    bl_idname = "mimi.auto_detect_texture_folder"
    bl_label = "Load DedupedTextures"
    
    def execute(self, context):
        lod_name = context.scene.mimi_fast_texture_lod
        deduped_textures_folder_path, folder_name = get_workspace_preview_texture_folder(lod_name=lod_name)

        if not deduped_textures_folder_path:
            msg = tr("Could not find the {folder} folder in the current workspace").format(folder=folder_name)
            if lod_name:
                msg += tr(" (LOD: {lod})").format(lod=lod_name)
            self.report({'ERROR'}, msg)
            return {'CANCELLED'}
        
        # Clear the previous list and previews
        bpy.context.scene.mimi_image_list.clear()
        pcoll = fast_preview_collections["main"]
        pcoll.clear()
        
        # Supported image formats
        image_extensions = ('.dds', '.jpg', '.jpeg', '.png', '.tga', '.bmp', '.tiff', '.exr', '.hdr')
        
        # Walk the folder and collect image files
        image_count = 0
        for filename in os.listdir(deduped_textures_folder_path):
            if filename.lower().endswith(image_extensions):
                full_path = os.path.join(deduped_textures_folder_path, filename)
                if os.path.isfile(full_path):
                    item = bpy.context.scene.mimi_image_list.add()
                    item.name = filename
                    item.filepath = full_path
                    
                    # Load the preview image
                    try:
                        thumb = pcoll.load(filename, full_path, 'IMAGE')
                        image_count += 1
                    except Exception as e:
                        print(f"Could not load preview for {filename}: {e}")

        lod_info = tr(" (LOD: {lod})").format(lod=lod_name) if lod_name else ""
        self.report({'INFO'}, tr("Loaded {count} images from the {folder} folder in the current workspace.").format(count=image_count, folder=folder_name) + lod_info)

        return {'FINISHED'}
    

# Operator that applies an image to materials
class SSMT_ImportTexture_WM_OT_ApplyImageToMaterial(I18nOperator):
    bl_idname = "mimi.apply_image_to_material"
    bl_label = "Apply Texture to Selected Objects"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        scene = context.scene
        selected_index = scene.mimi_image_list_index
        
        if selected_index < 0 or selected_index >= len(scene.mimi_image_list):
            self.report({'ERROR'}, tr("No image selected in the list."))
            return {'CANCELLED'}
        
        selected_image = scene.mimi_image_list[selected_index]
        image_path = selected_image.filepath
        
        # Get or create the image data block
        image_data = bpy.data.images.load(image_path, check_existing=True)
        
        selected_objects = context.selected_objects
        if not selected_objects:
            self.report({'ERROR'}, tr("No objects selected!"))
            return {'CANCELLED'}
        
        applied_count = 0
        for obj in selected_objects:
            if obj.type != 'MESH':
                continue  # Skip non-mesh objects
            
            # Make sure the object has a material data block
            if not obj.data.materials:
                mat = bpy.data.materials.new(name=f"Mat_{selected_image.name}")
                obj.data.materials.append(mat)
            else:
                # Use the first material slot
                mat = obj.data.materials[0]
                # If the first slot is empty (None), create a new material and assign it
                if mat is None:
                    mat = bpy.data.materials.new(name=f"Mat_{selected_image.name}")
                    obj.data.materials[0] = mat
            
            # Reuse the existing shader nodes and wire the picked image in.
            # The shared helper finds nodes by bl_idname (never by the
            # localised name), so it works in every interface language.
            apply_image_texture_to_material(mat, image_data)

            applied_count += 1
        
        self.report({'INFO'}, tr("Applied {image_name} to {count} objects.").format(image_name=selected_image.name, count=applied_count))
        return {'FINISHED'}


# Panel UI layout
@translatable
class MIMIMT_ImageMaterialPanel(Panel):
    bl_label = "Quick Preview Texture"
    bl_idname = "MIMI_PT_fast_preview_texture"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'MIMITools'
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        # LOD selection row
        box = layout.box()
        row = box.row(align=True)
        row.label(text=tr("LOD:"))
        row.prop(scene, "mimi_fast_texture_lod", text="")
        row.operator("mimi.refresh_lod_list", text="", icon='FILE_REFRESH')

        # Auto-detect button
        row = layout.row()
        row.operator("mimi.auto_detect_texture_folder", text=tr("Load DedupedTextures"))
        
        # Show the image count
        if scene.mimi_image_list:
            layout.label(text=tr("Found {count} images").format(count=len(scene.mimi_image_list)))
        
        # Show the image list
        if scene.mimi_image_list:
            row = layout.row()
            row.template_list(
                MIMIUL_FastImportTextureList.bl_idname,
                "Image List", 
                scene, 
                "mimi_image_list", 
                scene, 
                "mimi_image_list_index",
                rows=6
            )
        else:
            layout.label(text=tr("No images found. Select a folder first."))
        
        # Apply material button
        row = layout.row()
        row.operator("mimi.apply_image_to_material", text=tr("Apply Texture to Selected Objects"), icon='MATERIAL_DATA')

        
        # Show the preview of the currently selected image
        if scene.mimi_image_list and scene.mimi_image_list_index >= 0 and scene.mimi_image_list_index < len(scene.mimi_image_list):
            selected_item = scene.mimi_image_list[scene.mimi_image_list_index]
            pcoll = fast_preview_collections["main"]
            
            if selected_item.name in pcoll:
                box = layout.box()
                box.label(text=tr("Preview:"))
                box.template_icon(icon_value=pcoll[selected_item.name].icon_id, scale=10.0)



def register():
    # Register the preview image collection
    fast_pcoll = bpy.utils.previews.new()
    fast_preview_collections["main"] = fast_pcoll

    bpy.utils.register_class(MIMIImportTexture_ImageListItem)
    bpy.utils.register_class(MIMIUL_FastImportTextureList)
    bpy.utils.register_class(SSMT_ImportTexture_WM_OT_ApplyImageToMaterial)
    bpy.utils.register_class(SSMT_ImportTexture_WM_OT_RefreshLODList)
    bpy.utils.register_class(SSMT_ImportTexture_WM_OT_AutoDetectTextureFolder)
    bpy.utils.register_class(MIMIMT_ImageMaterialPanel)

    bpy.types.Scene.mimi_image_list = CollectionProperty(type=MIMIImportTexture_ImageListItem)
    bpy.types.Scene.mimi_image_list_index = IntProperty(default=0)
    bpy.types.Scene.mimi_fast_texture_lod = EnumProperty(
        name=tr("LOD"),
        description=tr("Select an LOD folder to load its DedupedTextures"),
        items=_get_lod_enum_items,
    )

    # Refresh the LOD list on startup
    _refresh_lod_enum_cache()

def unregister():
    try:
        del bpy.types.Scene.mimi_image_list
        del bpy.types.Scene.mimi_image_list_index
        del bpy.types.Scene.mimi_fast_texture_lod
    except Exception:
        pass

    # Remove the preview image collections
    for pcoll in fast_preview_collections.values():
        try:
            bpy.utils.previews.remove(pcoll)
        except Exception:
            pass
    fast_preview_collections.clear()

    bpy.utils.unregister_class(MIMIMT_ImageMaterialPanel)
    bpy.utils.unregister_class(SSMT_ImportTexture_WM_OT_AutoDetectTextureFolder)
    bpy.utils.unregister_class(SSMT_ImportTexture_WM_OT_RefreshLODList)
    bpy.utils.unregister_class(SSMT_ImportTexture_WM_OT_ApplyImageToMaterial)
    bpy.utils.unregister_class(MIMIUL_FastImportTextureList)
    bpy.utils.unregister_class(MIMIImportTexture_ImageListItem)
