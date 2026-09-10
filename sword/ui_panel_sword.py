import bpy
import os
from bpy.props import StringProperty, CollectionProperty, IntProperty, BoolProperty, EnumProperty
from bpy.types import Operator, Panel, PropertyGroup, UIList
from bpy_extras.io_utils import ImportHelper
import bpy.utils.previews

from .mesh_import_helper import MigotoBinaryFile, MeshImportHelper
from ..common.global_config import GlobalConfig
from ..common.ssmt_import_helper import SSMTImportHelper
from ..i18n.i18n import I18nOperator, tr, translatable

from ..utils.collection_utils import CollectionUtils,CollectionColor
from ..utils.material_texture_utils import apply_image_texture_to_material

# Store the preview image collection
preview_collections = {}
sword_reversed_workspace_items_cache = []


def _get_sword_reversed_workspace_items(self, context):
    global sword_reversed_workspace_items_cache

    try:
        # MIMITools reverse panel reads MMT toolchain only, never the SSMT cache folder.
        reversed_root = GlobalConfig.path_mimitools_reversed_root()
        if not reversed_root or not os.path.isdir(reversed_root):
            sword_reversed_workspace_items_cache = [
                ("", tr("No Reversed Workspace Available"), tr("Please make sure a Reversed folder exists under the MMT / MIMITools cache folder"))
            ]
            return sword_reversed_workspace_items_cache

        folder_names = sorted(
            [entry.name for entry in os.scandir(reversed_root) if entry.is_dir()]
        )
        if not folder_names:
            sword_reversed_workspace_items_cache = [
                ("", tr("No Reversed Workspace Available"), tr("No subfolders were found under the Reversed folder"))
            ]
            return sword_reversed_workspace_items_cache

        sword_reversed_workspace_items_cache = [(name, name, "") for name in folder_names]
        return sword_reversed_workspace_items_cache
    except Exception:
        sword_reversed_workspace_items_cache = [
            ("", tr("No Reversed Workspace Available"), tr("Failed to read the Reversed folder"))
        ]
        return sword_reversed_workspace_items_cache

# Define the image list item
class MIMISword_ImportTexture_ImageListItem(PropertyGroup):
    name: StringProperty(name=tr("Image Name")) # type: ignore
    filepath: StringProperty(name=tr("File Path")) # type: ignore

# Custom UI list showing images and thumbnails
class MIMISWORD_UL_FastImportTextureList(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        pcoll = preview_collections["main"]
        
        if self.layout_type in {'DEFAULT', 'Expand'}:
            # Try to get the preview icon
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

# Folder selection operator
class Sword_ImportTexture_WM_OT_SelectImageFolder(I18nOperator, ImportHelper):
    bl_idname = "mimi.select_image_folder"
    bl_label = "Select Preview Texture Folder"
    
    directory: StringProperty(subtype='DIR_PATH') # type: ignore
    filter_folder: BoolProperty(default=True, options={'HIDDEN'}) # type: ignore
    filter_image: BoolProperty(default=False, options={'HIDDEN'}) # type: ignore

    def execute(self, context):
        # Clear the previous list
        context.scene.mimi_sword_image_list.clear()
        
        # Clear the preview collection
        pcoll = preview_collections["main"]
        pcoll.clear()
        
        # Supported image formats
        image_extensions = ('.jpg', '.jpeg', '.png', '.tiff', '.bmp', '.tga', '.exr', '.hdr','.dds')
        
        # Walk the folder and collect image files
        image_count = 0
        for filename in os.listdir(self.directory):
            if filename.lower().endswith(image_extensions):
                full_path = os.path.join(self.directory, filename)
                if os.path.isfile(full_path):
                    item = context.scene.mimi_sword_image_list.add()
                    item.name = filename
                    item.filepath = full_path
                    
                    # Load the preview image
                    try:
                        thumb = pcoll.load(filename, full_path, 'IMAGE')
                        image_count += 1
                    except Exception as e:
                        print(f"Could not load preview for {filename}: {e}")
        
        self.report({'INFO'}, tr("Scanned {count} image(s).").format(count=image_count))
        return {'FINISHED'}
    

def reload_textures_from_folder(picture_folder_path:str):
    # Clear the previous list and previews
    bpy.context.scene.mimi_sword_image_list.clear()
    pcoll = preview_collections["main"]
    pcoll.clear()
    
    # Supported image formats
    image_extensions = ('.jpg', '.jpeg', '.png', '.tiff', '.bmp', '.tga', '.exr', '.hdr', '.dds')
    
    # Walk the folder and collect image files
    image_count = 0
    for filename in os.listdir(picture_folder_path):
        if filename.lower().endswith(image_extensions):
            full_path = os.path.join(picture_folder_path, filename)
            if os.path.isfile(full_path):
                item = bpy.context.scene.mimi_sword_image_list.add()
                item.name = filename
                item.filepath = full_path
                
                # Load the preview image
                try:
                    thumb = pcoll.load(filename, full_path, 'IMAGE')
                    image_count += 1
                except Exception as e:
                    print(f"Could not load preview for {filename}: {e}")


# Auto-detect and set the DedupedTextures_jpg folder
class Sword_ImportTexture_WM_OT_AutoDetectTextureFolder(I18nOperator):
    bl_idname = "mimi.auto_detect_texture_folder_wm"
    bl_label = "Auto Detect Extracted Texture Folder"
    
    def execute(self, context):
        selected_objects = context.selected_objects
        if not selected_objects:
            self.report({'ERROR'}, tr("No objects selected!"))
            return {'CANCELLED'}
        
        # Take the first selected object
        obj = selected_objects[0]
        obj_name = obj.name 
        
        # Build the path
        selected_drawib_folder_path = os.path.join(GlobalConfig.path_workspace_folder(),  obj_name.split("-")[0] + "\\"  )
        
        deduped_textures_jpg_folder_path = os.path.join(selected_drawib_folder_path, "DedupedTextures_jpg\\")
        deduped_textures_png_folder_path = os.path.join(selected_drawib_folder_path, "DedupedTextures_png\\")
        deduped_textures_tga_folder_path = os.path.join(selected_drawib_folder_path, "DedupedTextures_tga\\")

        deduped_textures_jpg_exists = os.path.exists(deduped_textures_jpg_folder_path)
        deduped_textures_png_exists = os.path.exists(deduped_textures_png_folder_path)
        deduped_textures_tga_exists = os.path.exists(deduped_textures_tga_folder_path)

        
        # Check whether the path exists
        if not deduped_textures_jpg_exists and not deduped_textures_png_exists and not deduped_textures_tga_exists:
            self.report({'ERROR'}, tr("Could not find the DedupedTextures folder for DrawIB {name}. Please make sure this IB has been extracted correctly in the current workspace.").format(name=obj_name.split('-')[0]))
            return {'CANCELLED'}
        
        # Clear the previous list and previews
        context.scene.mimi_sword_image_list.clear()
        pcoll = preview_collections["main"]
        pcoll.clear()
        
        # Supported image formats
        image_extensions = ('.jpg', '.jpeg', '.png', '.tiff', '.bmp', '.tga', '.exr', '.hdr','.dds')
        
        # Walk the folder and collect image files
        image_count = 0
        for filename in os.listdir(deduped_textures_jpg_folder_path):
            if filename.lower().endswith(image_extensions):
                full_path = os.path.join(deduped_textures_jpg_folder_path, filename)
                if os.path.isfile(full_path):
                    item = context.scene.mimi_sword_image_list.add()
                    item.name = filename
                    item.filepath = full_path
                    
                    # Load the preview image
                    try:
                        thumb = pcoll.load(filename, full_path, 'IMAGE')
                        image_count += 1
                    except Exception as e:
                        print(f"Could not load preview for {filename}: {e}")
        
        self.report({'INFO'}, tr("Auto-detected and loaded {count} image(s) from the DedupedTextures_jpg folder.").format(count=image_count))
        return {'FINISHED'}



# Apply the image to the materials of the selected objects
class Sword_ImportTexture_WM_OT_ApplyImageToMaterial(I18nOperator):
    bl_idname = "mimi.apply_image_to_material_wm"
    bl_label = "Apply Texture to Selected Objects"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        scene = context.scene
        selected_index = scene.mimi_sword_image_list_index
        
        if selected_index < 0 or selected_index >= len(scene.mimi_sword_image_list):
            self.report({'ERROR'}, tr("No image selected in the list."))
            return {'CANCELLED'}
        
        selected_image = scene.mimi_sword_image_list[selected_index]
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

                # If the first slot is empty (None), create a new material and fill it in
                if mat is None:
                    mat = bpy.data.materials.new(name=f"Mat_{selected_image.name}")
                    obj.data.materials[0] = mat
            
            # Reuse the existing shader nodes and wire the picked image in.
            # The shared helper finds nodes by bl_idname (never by the
            # localised name), so it works in every interface language.
            apply_image_texture_to_material(mat, image_data)

            applied_count += 1
        
        self.report({'INFO'}, tr("Applied {name} to {count} object(s).").format(name=selected_image.name, count=applied_count))
        return {'FINISHED'}


class SwordImportAllReversed(I18nOperator):
    bl_idname = "mimi.import_all_reverse"
    bl_label = "Import All Reversed Models"
    bl_description = "Import all models generated by the last one-click reverse pass into Blender, then you can manually filter and delete incorrect data types for a smoother workflow. Supports both the ib_vb_fmt and ssmt_fmt reverse output formats."
    bl_options = {'REGISTER', 'UNDO'}

    def _resolve_reverse_output_folder_path(self, context):
        # Reversed paths come from MMT settings only, no SSMT config needed.
        source_mode = context.scene.mimi_sword_reverse_source_mode
        if source_mode == "SPECIFIC":
            selected_workspace_name = context.scene.mimi_sword_specific_reversed_workspace_name
            if not selected_workspace_name:
                self.report({"ERROR"}, tr("No specific workspace selected, please select a subfolder under Reversed first"))
                return ""
            # MIMITools reverse panel reads MMT toolchain only, never the SSMT cache folder.
            reversed_root = GlobalConfig.path_mimitools_reversed_root()
            if not reversed_root:
                self.report({"ERROR"}, tr("MMT Reversed folder not found, please run the one-click reverse in MMT first"))
                return ""
            return os.path.join(reversed_root, selected_workspace_name)

        if source_mode == "CUSTOM":
            custom_folder_path = str(context.scene.mimi_sword_custom_reverse_output_folder_path).strip()
            if not custom_folder_path:
                self.report({"ERROR"}, tr("Custom folder is empty, please select a folder first"))
                return ""
            return custom_folder_path

        return GlobalConfig.path_mimitools_reverse_output_folder() or GlobalConfig.path_reverse_output_folder()

    def execute(self, context):
        reverse_output_folder_path = self._resolve_reverse_output_folder_path(context)
        if not reverse_output_folder_path:
            return {'FINISHED'}

        if not os.path.exists(reverse_output_folder_path) or not os.path.isdir(reverse_output_folder_path):
            self.report({"ERROR"}, tr("The folder recorded for the latest reverse result does not exist, please run the reverse again"))
            return {'FINISHED'}
        print("Test import")

        # After a successful MMT reverse, the ReverseOutputFormat key is written (symmetric to ReverseOutputFolder)
        # ib_vb_fmt goes through the old .fmt parsing import, ssmt_fmt goes through the SSMT Json import
        # If the key cannot be found, it is treated as the ib_vb_fmt format
        reverse_output_format = GlobalConfig.reverse_output_format()
        if reverse_output_format == "ssmt_fmt":
            return self._import_ssmt_fmt(context, reverse_output_folder_path)
        return self._import_ib_vb_fmt(context, reverse_output_folder_path)

    def _import_ssmt_fmt(self, context, reverse_output_folder_path):
        '''
        ssmt_fmt format import:
        Walk all subfolders of the reverse output folder. Each subfolder may contain several Json files,
        and the file name of each Json file is its data type. Create a drawib_<data type> collection
        for each Json file and import it.
        '''
        total_folder_name = os.path.basename(reverse_output_folder_path)

        reverse_collection = CollectionUtils.create_new_collection(collection_name=total_folder_name,color_tag=CollectionColor.Red)
        bpy.context.scene.collection.children.link(reverse_collection)

        # Get all subfolders
        subfolder_path_list = [f.path for f in os.scandir(reverse_output_folder_path) if f.is_dir()]
        if not subfolder_path_list:
            self.report({"ERROR"}, tr("No importable subfolders found in the target folder"))
            return {'FINISHED'}

        imported_count = 0
        for subfolder_path in subfolder_path_list:

            # Get all .json files; the file name of each Json file is its data type
            json_files = []
            for file in os.listdir(subfolder_path):
                if file.endswith('.json'):
                    json_files.append(os.path.join(subfolder_path, file))

            for json_filepath in json_files:
                # Get the file name including the extension
                filename_with_extension = os.path.basename(json_filepath)
                # Remove the extension to get the data type name
                datatype_name = os.path.splitext(filename_with_extension)[0]

                # Create a drawib_<data type> collection from the name of each Json file
                datatype_collection = CollectionUtils.create_new_collection(collection_name="drawib_" + datatype_name,color_tag=CollectionColor.White, link_to_parent_collection_name=reverse_collection.name)

                try:
                    # Call the SSMT format import function
                    SSMTImportHelper.create_mesh_from_json(json_file_path=json_filepath, import_collection=datatype_collection)
                    imported_count += 1
                except Exception as e:
                    error_msg = tr("Import failed, skipped: {path} | Error: {error}").format(path=json_filepath, error=e)
                    print(error_msg)
                    self.report({'WARNING'}, error_msg)
                    continue

        if imported_count == 0:
            self.report({"ERROR"}, tr("No Json files were imported from the ssmt_fmt reverse result"))
            return {'FINISHED'}

        # Then point the image path to the current path
        reload_textures_from_folder(reverse_output_folder_path)

        return {'FINISHED'}

    def _import_ib_vb_fmt(self, context, reverse_output_folder_path):
        total_folder_name = os.path.basename(reverse_output_folder_path)

        reverse_collection = CollectionUtils.create_new_collection(collection_name=total_folder_name,color_tag=CollectionColor.Red)
        bpy.context.scene.collection.children.link(reverse_collection)

        # Get all subfolders
        subfolder_path_list = [f.path for f in os.scandir(reverse_output_folder_path) if f.is_dir()]
        if not subfolder_path_list:
            self.report({"ERROR"}, tr("No importable subfolders found in the target folder"))
            return {'FINISHED'}

        for subfolder_path in subfolder_path_list:
            
            datatype_folder_name = os.path.basename(subfolder_path)

            datatype_collection = CollectionUtils.create_new_collection(collection_name=datatype_folder_name,color_tag=CollectionColor.White, link_to_parent_collection_name=reverse_collection.name)

            # Get all .fmt files
            fmt_files = []
            for file in os.listdir(subfolder_path):
                if file.endswith('.fmt'):
                    fmt_files.append(os.path.join(subfolder_path, file))

            for fmt_filepath in fmt_files:
                # Get the file name including the extension
                filename_with_extension = os.path.basename(fmt_filepath)
                # Remove the extension
                filename_without_extension = os.path.splitext(filename_with_extension)[0]
                try:
                    # Call the import function
                    mbf = MigotoBinaryFile(fmt_path=fmt_filepath, mesh_name=filename_without_extension)
                    MeshImportHelper.create_mesh_obj_from_mbf(mbf=mbf, import_collection=datatype_collection)
                except Exception as e:
                    error_msg = tr("Import failed, skipped: {path} | Error: {error}").format(path=fmt_filepath, error=e)
                    print(error_msg)
                    self.report({'WARNING'}, error_msg)
                    continue

                
                # Nico: note that after reversing Wuthering Waves Mod models, normals may be incorrect.
                # This should not be handled automatically; the user should handle it manually,
                # since some models have the issue and others do not.
                # Forcing a fix may make the normals incorrect.



        # Then point the image path to the current path
        reload_textures_from_folder(reverse_output_folder_path)

        return {'FINISHED'}


class SWORD4RefreshReversedWorkspaceList(I18nOperator):
    bl_idname = "mimi.sword_refresh_reversed_workspace_list"
    bl_label = "Refresh Reversed Workspace List"
    bl_description = "Refresh the subfolder list under the Reversed folder of the current MMT / MIMITools cache folder"

    def execute(self, context):
        # Reversed workspace list comes from MMT settings only.
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                area.tag_redraw()

        self.report({'INFO'}, tr("Reversed workspace list refreshed"))
        return {'FINISHED'}


# Panel UI layout
@translatable
class MIMISword_ImageMaterialPanel(Panel):
    bl_label = "Mod Reverse Panel"
    bl_idname = "mimi.PT_image_material_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'MIMITools'
    # bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        layout.prop(scene, "mimi_sword_reverse_source_mode", text=tr("Import Mode"))
        if scene.mimi_sword_reverse_source_mode == "SPECIFIC":
            reversed_workspace_row = layout.row(align=True)
            reversed_workspace_row.prop(scene, "mimi_sword_specific_reversed_workspace_name", text=tr("Specified Workspace"))
            reversed_workspace_row.operator(SWORD4RefreshReversedWorkspaceList.bl_idname, text="", icon='FILE_REFRESH')
        elif scene.mimi_sword_reverse_source_mode == "CUSTOM":
            layout.prop(scene, "mimi_sword_custom_reverse_output_folder_path", text=tr("Custom Folder"))

        # One-click import of the reverse result button
        layout.operator("mimi.import_all_reverse", text=tr("Import All Reversed Models"), icon='IMPORT')

        # Folder selection button
        row = layout.row()
        row.operator("mimi.select_image_folder", text=tr("Select Preview Texture Folder"), icon='FILE_FOLDER')
        
        # Show the image count
        if scene.mimi_sword_image_list:
            layout.label(text=tr("Found {count} image(s)").format(count=len(scene.mimi_sword_image_list)))
        
        # Show the image list
        if scene.mimi_sword_image_list:
            row = layout.row()
            row.template_list(
                "MIMISWORD_UL_FastImportTextureList",  # Correct class name
                "Image List", 
                scene, 
                "mimi_sword_image_list", 
                scene, 
                "mimi_sword_image_list_index",
                rows=6
            )
        else:
            layout.label(text=tr("No images found. Select a folder first."))
        
        # Apply material button
        row = layout.row()
        row.operator("mimi.apply_image_to_material_wm", text=tr("Apply Texture to Selected Objects"), icon='MATERIAL_DATA')
        
        # Show the preview of the currently selected image
        if scene.mimi_sword_image_list and scene.mimi_sword_image_list_index >= 0 and scene.mimi_sword_image_list_index < len(scene.mimi_sword_image_list):
            selected_item = scene.mimi_sword_image_list[scene.mimi_sword_image_list_index]
            pcoll = preview_collections["main"]
            
            if selected_item.name in pcoll:
                box = layout.box()
                box.label(text=tr("Preview:"))
                box.template_icon(icon_value=pcoll[selected_item.name].icon_id, scale=10.0)


@translatable
class MIMISword_SplitModel_Panel(Panel):
    bl_label = "Split Model by DrawIndexed After Manual Reverse"
    bl_idname = "mimi.PT_Sword_SplitModel_By_DrawIndexed_Panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'MIMITools'
    # bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        layout.prop(scene, "mimi_submesh_start", text=tr("Start Index"))
        layout.prop(scene, "mimi_submesh_count", text=tr("Index Count"))
        
        op = layout.operator("mimi.extract_submesh", text=tr("Split Model by DrawIndexed Values"))
        op.start_index = scene.mimi_submesh_start
        op.index_count = scene.mimi_submesh_count

def _get_sword_reverse_source_mode_items(self, context):
    # Dynamic items callback so the dropdown entries follow the UI language.
    return [
        ("LAST", tr("Latest Reverse Output"), tr("Use the last reverse output folder recorded in the global configuration")),
        ("SPECIFIC", tr("Specified Workspace"), tr("Use the specified subfolder under Reversed in the MMT / MIMITools cache folder")),
        ("CUSTOM", tr("Custom Folder"), tr("Use the folder you specify manually")),
    ]


def register():
    # Register the preview image collection
    pcoll = bpy.utils.previews.new()
    preview_collections["main"] = pcoll

    bpy.utils.register_class(MIMISword_ImportTexture_ImageListItem)
    bpy.utils.register_class(MIMISWORD_UL_FastImportTextureList)
    bpy.utils.register_class(MIMISword_ImageMaterialPanel)
    bpy.utils.register_class(Sword_ImportTexture_WM_OT_ApplyImageToMaterial)
    bpy.utils.register_class(Sword_ImportTexture_WM_OT_SelectImageFolder)
    bpy.utils.register_class(SwordImportAllReversed)
    bpy.utils.register_class(SWORD4RefreshReversedWorkspaceList)
    bpy.utils.register_class(MIMISword_SplitModel_Panel)

    bpy.types.Scene.mimi_sword_image_list = CollectionProperty(type=MIMISword_ImportTexture_ImageListItem)
    bpy.types.Scene.mimi_sword_image_list_index = IntProperty(default=0)
    bpy.types.Scene.mimi_sword_reverse_source_mode = EnumProperty(
        name=tr("Import Mode"),
        description=tr("Controls the folder source used when importing reverse results in one click"),
        items=_get_sword_reverse_source_mode_items,
        # Dynamic items only allow integer (0-based) defaults; the first item
        # ("LAST") is the intended default, so the argument is omitted.
    )
    bpy.types.Scene.mimi_sword_specific_reversed_workspace_name = EnumProperty(
        name=tr("Specified Workspace"),
        description=tr("Subfolders under Reversed in the current MMT / MIMITools cache folder"),
        items=_get_sword_reversed_workspace_items,
    )
    bpy.types.Scene.mimi_sword_custom_reverse_output_folder_path = StringProperty(
        name=tr("Custom Folder"),
        description=tr("Manually specify the folder used for the one-click import of reverse results"),
        default="",
        subtype='DIR_PATH',
    )

def unregister():
    try:
        del bpy.types.Scene.mimi_sword_image_list
        del bpy.types.Scene.mimi_sword_image_list_index
        del bpy.types.Scene.mimi_sword_reverse_source_mode
        del bpy.types.Scene.mimi_sword_specific_reversed_workspace_name
        del bpy.types.Scene.mimi_sword_custom_reverse_output_folder_path
    except Exception:
        pass

    # Remove the preview image collection
    for pcoll in preview_collections.values():
        try:
            bpy.utils.previews.remove(pcoll)
        except Exception:
            pass
    preview_collections.clear()

    bpy.utils.unregister_class(MIMISword_SplitModel_Panel)
    bpy.utils.unregister_class(SwordImportAllReversed)
    bpy.utils.unregister_class(Sword_ImportTexture_WM_OT_SelectImageFolder)
    bpy.utils.unregister_class(Sword_ImportTexture_WM_OT_ApplyImageToMaterial)
    bpy.utils.unregister_class(MIMISword_ImageMaterialPanel)
    bpy.utils.unregister_class(SWORD4RefreshReversedWorkspaceList)
    bpy.utils.unregister_class(MIMISWORD_UL_FastImportTextureList)
    bpy.utils.unregister_class(MIMISword_ImportTexture_ImageListItem)
                
