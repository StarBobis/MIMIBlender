import bpy
import os
from bpy.props import StringProperty, CollectionProperty, IntProperty, BoolProperty, EnumProperty
from bpy.types import Operator, Panel, PropertyGroup, UIList
from bpy_extras.io_utils import ImportHelper
import bpy.utils.previews

from .mesh_import_helper import MigotoBinaryFile, MeshImportHelper
from ..common.global_config import GlobalConfig
from ..common.mmt_import_helper import MMTImportHelper
from ..i18n.i18n import I18nOperator, tr, translatable, get_language
from ..workspace.submesh_json import SubmeshJson

# Folder check shared with the Mod Reverse panel: it tells the user whether the
# selected folder can be imported before the import runs.
from .reverse_source_probe import (
    IB_VB_FMT,
    STATUS_MISSING,
    STATUS_NO_BUFFER,
    STATUS_NO_DATA,
    STATUS_NO_PATH,
    STATUS_OK,
    STATUS_TOO_DEEP,
    STATUS_TOO_SHALLOW,
    STATUS_UNREADABLE,
    normalize_folder_path,
    probe_reverse_folder,
)

from ..utils.collection_utils import CollectionUtils,CollectionColor
from ..utils.material_texture_utils import apply_image_texture_to_material

# Store the preview image collection
preview_collections = {}
sword_reversed_workspace_items_cache = []

# Cached result of the last reverse folder check. The panel is redrawn on every
# mouse move, so the folder is checked once per selected path, not per redraw.
_sword_reverse_probe_cache = {"folder_path": None, "probe": None}

# Cached folder resolution for the panel. Resolving the folder reads the MMT
# global configuration files, which the panel must not do on every redraw.
_sword_reverse_source_cache = {"key": None, "folder_path": "", "error_message": ""}


def clear_sword_reverse_probe_cache():
    """Forget the cached folder check (the selected folder may have changed)."""
    _sword_reverse_probe_cache["folder_path"] = None
    _sword_reverse_probe_cache["probe"] = None
    _sword_reverse_source_cache["key"] = None
    _sword_reverse_source_cache["folder_path"] = ""
    _sword_reverse_source_cache["error_message"] = ""


def _on_sword_reverse_source_changed(self, context):
    """Property update callback: the folder selection changed, so re-check it."""
    clear_sword_reverse_probe_cache()


def resolve_sword_reverse_source_folder(scene):
    """Return the (folder_path, error_message) of the current import mode.

    The Mod Reverse panel and the import operator both use this function, so the
    hint always describes the very folder the import will read.

    error_message is already translated and is empty when a folder was
    resolved. A path that cannot be resolved is handed back unchanged so the
    panel can still show it.
    """
    source_mode = scene.mimi_sword_reverse_source_mode

    if source_mode == "SPECIFIC":
        selected_workspace_name = str(scene.mimi_sword_specific_reversed_workspace_name or "").strip()
        if not selected_workspace_name:
            return "", tr("No specific workspace selected, please select a subfolder under Reversed first")
        # MIMITools reverse panel reads MMT toolchain only, never the legacy SSMT cache folder.
        reversed_root = GlobalConfig.path_mimitools_reversed_root()
        if not reversed_root:
            return "", tr("MMT Reversed folder not found, please run the one-click reverse in MMT first")
        return os.path.join(reversed_root, selected_workspace_name), ""

    if source_mode == "CUSTOM":
        # Resolve Blender's // paths relative to the blend file before normpath
        # can turn them into an unrelated UNC or process-relative path.
        raw_path = str(scene.mimi_sword_custom_reverse_output_folder_path or '').strip()
        raw_path = raw_path.strip('"').strip("'").strip()
        custom_folder_path = normalize_folder_path(bpy.path.abspath(raw_path)) if raw_path else ""
        if not custom_folder_path:
            return "", tr("Custom folder is empty, please select a folder first")
        return custom_folder_path, ""

    latest_folder_path = normalize_folder_path(
        GlobalConfig.path_mimitools_reverse_output_folder() or GlobalConfig.path_reverse_output_folder()
    )
    if not latest_folder_path:
        return "", tr("No latest reverse output folder was recorded, please run the one-click reverse in MMT first")
    return latest_folder_path, ""


def get_sword_reverse_probe(folder_path, force=False):
    """Return the folder check result, reading the folder only when needed.

    force=True re-checks the folder even when the cached result belongs to the
    same path; the panel uses the cache, the import operator always re-checks.
    """
    cache = _sword_reverse_probe_cache
    if not force and cache["folder_path"] == folder_path and cache["probe"] is not None:
        return cache["probe"]

    probe = probe_reverse_folder(folder_path)
    cache["folder_path"] = folder_path
    cache["probe"] = probe
    return probe


def _sword_reverse_source_selection_key(scene):
    """Return the values that decide which folder the panel checks."""
    return (
        str(scene.mimi_sword_reverse_source_mode or ""),
        str(scene.mimi_sword_specific_reversed_workspace_name or ""),
        str(scene.mimi_sword_custom_reverse_output_folder_path or ""),
        bpy.data.filepath,
        get_language(),
    )


def get_sword_reverse_source(scene):
    """Resolve the folder to check, reading the MMT config only when needed.

    The panel is redrawn very often, and resolving the folder reads the MMT
    global configuration files, so the result is cached until the user changes
    the import mode, the workspace or the custom folder.
    """
    cache = _sword_reverse_source_cache
    selection_key = _sword_reverse_source_selection_key(scene)
    if cache["key"] == selection_key:
        return cache["folder_path"], cache["error_message"]

    folder_path, error_message = resolve_sword_reverse_source_folder(scene)
    cache["key"] = selection_key
    cache["folder_path"] = folder_path
    cache["error_message"] = error_message
    return folder_path, error_message


def sword_reverse_probe_message(probe, source_mode=""):
    """Turn one folder check result into a short, translated reason.

    Every branch calls tr() with a literal string: the i18n checker collects
    translation keys from literals only, so no message may come from a table.
    """
    status = probe["status"]
    if status == STATUS_NO_PATH:
        return tr("Please select the reverse output folder first")
    if status == STATUS_MISSING:
        if source_mode == "LAST":
            return tr("The folder recorded for the latest reverse result does not exist, please run the reverse again")
        return tr("The folder does not exist, please check the path")
    if status == STATUS_UNREADABLE:
        return tr("The folder cannot be read, please check the folder permission")
    if status == STATUS_TOO_DEEP:
        return tr("The selected folder is a DrawIB folder itself, please select its parent folder")
    if status == STATUS_TOO_SHALLOW:
        return tr("The selected folder holds reverse workspaces, please select one of its subfolders")
    if status == STATUS_NO_BUFFER:
        return tr("No usable reverse descriptors with complete, nonempty referenced buffers were found")
    if status == STATUS_NO_DATA:
        return tr("No .json (ssmt_fmt) or .fmt (ib_vb_fmt) reverse data was found in its subfolders")
    return tr("The folder can be imported")


def remove_objects_created_since(collection, objects_before):
    """Delete every object a collection gained since it was last measured.

    Used to roll back a half-imported data type: a failing import must not leave
    half-built meshes behind in the outliner.
    """
    for imported_obj in list(bpy.data.objects):
        if imported_obj not in objects_before:
            bpy.data.objects.remove(imported_obj, do_unlink=True)


def remove_collection_tree(collection):
    """Remove a collection together with every child collection.

    Called when an import produced nothing: the empty reverse collection used to
    stay in the outliner and looked like a successful but empty import.
    """
    for child_collection in list(collection.children):
        remove_collection_tree(child_collection)
    bpy.data.collections.remove(collection)


def prune_empty_collections(collection):
    """Remove child collections that hold no object and no child collection.

    A parent collection is meant to stay empty (the meshes live in the leaf
    collections), so only truly empty leaves are removed, for example a DrawIB
    collection whose every data type failed to import.
    """
    for child_collection in list(collection.children):
        prune_empty_collections(child_collection)
        if len(child_collection.objects) == 0 and len(child_collection.children) == 0:
            bpy.data.collections.remove(child_collection)


def _get_sword_reversed_workspace_items(self, context):
    global sword_reversed_workspace_items_cache

    try:
        # MIMITools reverse panel reads MMT toolchain only, never the legacy SSMT cache folder.
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

    def execute(self, context):
        # Resolve the folder exactly like the Mod Reverse panel does, so the
        # on-screen hint and the import always talk about the same folder.
        reverse_output_folder_path, error_message = resolve_sword_reverse_source_folder(context.scene)
        if error_message:
            self.report({"ERROR"}, error_message)
            return {'FINISHED'}

        # Check the folder BEFORE creating any collection. An importable check
        # result is also what decides the format, so a hand-picked folder of the
        # other format is imported correctly instead of silently importing
        # nothing (that used to leave an empty collection behind).
        folder_probe = get_sword_reverse_probe(reverse_output_folder_path, force=True)
        if folder_probe["status"] != STATUS_OK:
            self.report(
                {"ERROR"},
                sword_reverse_probe_message(folder_probe, context.scene.mimi_sword_reverse_source_mode),
            )
            return {'FINISHED'}

        if folder_probe["format"] == IB_VB_FMT:
            return self._import_ib_vb_fmt(context, folder_probe)
        return self._import_ssmt_fmt(context, folder_probe)

    @staticmethod
    def _build_match_component_map(json_files: list) -> dict:
        '''
        Build the DrawIB-level Component numbering shared by every data type.

        Every Json of one DrawIB folder describes the same index buffers with
        a different candidate vertex layout, so the recorded match ranges
        (IndexOffset, IndexCount) are identical across the files; unioning
        them is only a safeguard. A complete MatchComponentList preserves
        source Component numbers, including entries with no draw segment.
        Older JSON files fall back to range-size ordering.
        Returns a dict mapping (IndexOffset, IndexCount) -> component index.
        '''
        # Ranges from per-segment match identities (single-IB multi-component
        # groups such as WWMI, where one IB entry can only hold one
        # whole-buffer range) and from per-IB-entry identities (multi-IB
        # groups such as GIMI). Per-segment identities win when present.
        # New WWMI outputs provide the complete source table, including empty
        # Component sections. It is authoritative when available.
        declared_component_ranges = {}
        segment_ranges = set()
        entry_ranges_all = set()
        top_level_ranges = set()
        for json_filepath in json_files:
            try:
                submesh_json = SubmeshJson(json_filepath)
            except Exception as e:
                # A Json that cannot even be parsed simply contributes no
                # ranges; the import loop reports its own failure later.
                print("Component map: failed to read " + json_filepath + ": " + str(e))
                continue

            for match_component in submesh_json.MatchComponentList:
                if match_component.MatchIndexCount > 0:
                    declared_component_ranges[
                        (match_component.MatchFirstIndex, match_component.MatchIndexCount)
                    ] = match_component.ComponentIndex

            for draw_call_segment in submesh_json.DrawCallSegmentList:
                if draw_call_segment.MatchIndexCount > 0:
                    segment_ranges.add((draw_call_segment.MatchFirstIndex, draw_call_segment.MatchIndexCount))

            for index_buffer in submesh_json.IndexBufferList:
                if index_buffer.IndexCount > 0:
                    entry_ranges_all.add((index_buffer.IndexOffset, index_buffer.IndexCount))
            if submesh_json.IndexCount > 0:
                top_level_ranges.add((submesh_json.IndexOffset, submesh_json.IndexCount))

        if declared_component_ranges:
            # Empty source Components are intentionally present in this map;
            # they receive a number but never produce an imported mesh object.
            return declared_component_ranges

        if segment_ranges:
            # Segments carry their own component identity: the IB entry only
            # describes the shared buffer file, so it must not become a
            # "component" of its own.
            match_ranges = segment_ranges
        elif entry_ranges_all:
            match_ranges = entry_ranges_all
        else:
            match_ranges = top_level_ranges

        # Smallest draw range first: Component 0 is the tiniest part of the
        # DrawIB, the last Component is the big main body. The offset is the
        # tie-breaker so equal-sized ranges still get a deterministic order.
        ordered_ranges = sorted(match_ranges, key=lambda match_range: (match_range[1], match_range[0]))
        return {match_range: component_index for component_index, match_range in enumerate(ordered_ranges)}

    def _import_ssmt_fmt(self, context, folder_probe):
        '''
        ssmt_fmt format import:
        Walk all subfolders of the reverse output folder. Each subfolder is named
        after its DrawIB (e.g. 1fbe8217, 056da8f3) and may contain several Json
        files (one per candidate data type, e.g. GPU_P12_N12_..._.json), because
        the reverse pass cannot know which vertex layout is the original one.

        For every subfolder one parent collection named after the DrawIB itself
        is created; inside it, each Json data type gets its own child collection
        named after the Json file stem. Every candidate data type therefore
        lands in a separate collection, so wrong candidates can be toggled or
        deleted collection by collection instead of picking single objects out
        of one big pile of identically named meshes.
        Meshes are named {DrawIB}-Component {N}.{Alias}: newer WWMI JSON
        preserves the source Component table, including empty entries; older
        JSON falls back to range-size ordering. Segments without an alias fall
        back to the classic numeric draw-range suffix.

        folder_probe is the checked folder result of the Mod Reverse panel; it
        carries the normalized path already, so the import never re-guesses it.
        '''
        reverse_output_folder_path = folder_probe["folder_path"]
        total_folder_name = os.path.basename(reverse_output_folder_path)

        # Recheck root readability before creating scene data: the directory
        # may disappear between preflight and import (removable/network disks).
        try:
            with os.scandir(reverse_output_folder_path) as entries:
                subfolder_path_list = [entry.path for entry in entries if entry.is_dir()]
        except OSError as error:
            self.report({'ERROR'}, tr("Folder cannot be read, skipped: {path} | Error: {error}").format(
                path=reverse_output_folder_path, error=error))
            return {'CANCELLED'}
        reverse_collection = CollectionUtils.create_new_collection(collection_name=total_folder_name,color_tag=CollectionColor.Red)
        context.scene.collection.children.link(reverse_collection)
        if not subfolder_path_list:
            # Nothing to import: remove the just created collection again, so an
            # empty reverse collection never stays in the outliner.
            remove_collection_tree(reverse_collection)
            self.report({"ERROR"}, tr("No importable subfolders found in the target folder"))
            return {'FINISHED'}

        imported_data_type_count = 0
        for subfolder_path in subfolder_path_list:

            # The subfolder name is the DrawIB this group of meshes belongs to
            drawib_folder_name = os.path.basename(subfolder_path)

            # Get all .json files first; skip subfolders without any Json file
            # so we never create empty drawib collections. The extension check
            # ignores case, exactly like the folder check of the panel does.
            json_files = []
            try:
                folder_file_names = os.listdir(subfolder_path)
            except OSError as list_error:
                # An unreadable DrawIB folder must not abort the whole import.
                list_error_msg = tr("Folder cannot be read, skipped: {path} | Error: {error}").format(path=subfolder_path, error=list_error)
                print(list_error_msg)
                self.report({'WARNING'}, list_error_msg)
                continue

            for file in folder_file_names:
                if file.lower().endswith('.json'):
                    json_files.append(os.path.join(subfolder_path, file))

            if not json_files:
                continue

            # Create one parent collection per DrawIB subfolder, named directly
            # after the DrawIB folder (no extra prefix; the Json data-type file
            # names only show up on the child collections below).
            drawib_collection = CollectionUtils.create_new_collection(collection_name=drawib_folder_name,color_tag=CollectionColor.White, link_to_parent_collection_name=reverse_collection.name)

            # Compute the DrawIB-level Component numbering once; every data
            # type of this folder shares it, so "Component N" refers to the
            # same IB partition in every child collection.
            match_component_map = SwordImportAllReversed._build_match_component_map(json_files)

            # Every Json file holds one candidate data type. Sort them so the
            # outliner order stays deterministic, and give each candidate its
            # own child collection named after the Json file stem (the stem is
            # the data-type name, so the collection shows it directly).
            for json_filepath in sorted(json_files):
                datatype_name = os.path.splitext(os.path.basename(json_filepath))[0]

                # Link under the DrawIB parent via the parent's resolved name;
                # repeat imports may carry a Blender .001 suffix.
                datatype_collection = CollectionUtils.create_new_collection(
                    collection_name=datatype_name,
                    color_tag=CollectionColor.White,
                    link_to_parent_collection_name=drawib_collection.name,
                )

                # The collection is brand new, so every object inside it belongs
                # to this data type; counting them tells whether the data type
                # produced a usable mesh.
                objects_before = set(bpy.data.objects)
                try:
                    # Call the ssmt_fmt format import function; the DrawIB folder
                    # name is passed as the classic Submesh naming prefix and the
                    # Component map, so the imported objects are named
                    # {DrawIB}-Component {N}.{Alias}.
                    MMTImportHelper.create_mesh_from_json(json_file_path=json_filepath, import_collection=datatype_collection, submesh_name_prefix=drawib_folder_name, match_component_map=match_component_map)
                except Exception as e:
                    # Roll back the failed candidate: drop any partially created
                    # objects together with the now useless child collection, so
                    # a broken data type never litters the outliner.
                    remove_objects_created_since(datatype_collection, objects_before)
                    bpy.data.collections.remove(datatype_collection)

                    error_msg = tr("Import failed, skipped: {path} | Error: {error}").format(path=json_filepath, error=e)
                    print(error_msg)
                    self.report({'WARNING'}, error_msg)
                    continue

                if len(datatype_collection.objects) <= 0:
                    # The data type imported without an error but built nothing:
                    # drop its collection instead of leaving an empty one.
                    bpy.data.collections.remove(datatype_collection)
                    empty_msg = tr("No mesh was created for this data type, skipped: {path}").format(path=json_filepath)
                    print(empty_msg)
                    self.report({'WARNING'}, empty_msg)
                    continue

                imported_data_type_count += 1

        if imported_data_type_count == 0:
            # Every data type failed. Remove the empty collection tree that the
            # import created, otherwise the outliner keeps an empty "reverse
            # result" collection and the user cannot tell what went wrong.
            remove_collection_tree(reverse_collection)
            self.report({"ERROR"}, tr("No Json files were imported from the ssmt_fmt reverse result"))
            return {'FINISHED'}

        # A DrawIB whose every data type failed only has empty children left.
        prune_empty_collections(reverse_collection)

        # Summarize the result so the user knows every candidate data type was
        # imported into its own collection and can now compare them one by one.
        self.report({'INFO'}, tr("Imported {count} data type(s); each one is in its own collection named after the data type, grouped under collections named after their DrawIB.").format(count=imported_data_type_count))

        # Then point the image path to the current path
        reload_textures_from_folder(reverse_output_folder_path)

        return {'FINISHED'}

    def _import_ib_vb_fmt(self, context, folder_probe):
        '''
        Legacy ib_vb_fmt import: every subfolder of the reverse output folder is
        one data type folder holding <prefix>.fmt plus its .ib / .vb buffers.

        The import works on the checked folder result of the Mod Reverse panel
        (folder_probe), so the path and the format were already verified before
        the first collection is created: a folder that cannot be imported no
        longer leaves an empty collection behind.
        '''
        reverse_output_folder_path = folder_probe["folder_path"]
        total_folder_name = os.path.basename(reverse_output_folder_path)

        # Recheck root readability before creating scene data: the directory
        # may disappear between preflight and import (removable/network disks).
        try:
            with os.scandir(reverse_output_folder_path) as entries:
                subfolder_path_list = [entry.path for entry in entries if entry.is_dir()]
        except OSError as error:
            self.report({'ERROR'}, tr("Folder cannot be read, skipped: {path} | Error: {error}").format(
                path=reverse_output_folder_path, error=error))
            return {'CANCELLED'}
        reverse_collection = CollectionUtils.create_new_collection(collection_name=total_folder_name,color_tag=CollectionColor.Red)
        context.scene.collection.children.link(reverse_collection)
        if not subfolder_path_list:
            # Nothing to import: remove the just created collection again, so an
            # empty reverse collection never stays in the outliner.
            remove_collection_tree(reverse_collection)
            self.report({"ERROR"}, tr("No importable subfolders found in the target folder"))
            return {'FINISHED'}

        imported_object_count = 0
        for subfolder_path in subfolder_path_list:

            datatype_folder_name = os.path.basename(subfolder_path)

            # Get all .fmt files. The extension check ignores case, exactly like
            # the folder check of the panel does.
            fmt_files = []
            try:
                folder_file_names = os.listdir(subfolder_path)
            except OSError as list_error:
                # An unreadable data type folder must not abort the whole import.
                list_error_msg = tr("Folder cannot be read, skipped: {path} | Error: {error}").format(path=subfolder_path, error=list_error)
                print(list_error_msg)
                self.report({'WARNING'}, list_error_msg)
                continue

            for file in folder_file_names:
                if file.lower().endswith('.fmt'):
                    fmt_files.append(os.path.join(subfolder_path, file))

            if not fmt_files:
                # A subfolder without .fmt files is not a data type folder (a
                # Textures folder, a leftover folder, ...). It used to become an
                # empty collection; now it is skipped completely.
                continue

            datatype_collection = CollectionUtils.create_new_collection(collection_name=datatype_folder_name,color_tag=CollectionColor.White, link_to_parent_collection_name=reverse_collection.name)

            datatype_object_count = 0
            for fmt_filepath in fmt_files:
                # Get the file name including the extension
                filename_with_extension = os.path.basename(fmt_filepath)
                # Remove the extension
                filename_without_extension = os.path.splitext(filename_with_extension)[0]
                # One .fmt may create several objects (per draw-indexed slice);
                # remember what was already there to roll this file back alone.
                objects_before = set(bpy.data.objects)
                try:
                    # Call the import function
                    mbf = MigotoBinaryFile(fmt_path=fmt_filepath, mesh_name=filename_without_extension)
                    MeshImportHelper.create_mesh_obj_from_mbf(mbf=mbf, import_collection=datatype_collection)
                except Exception as e:
                    # Drop whatever this half-finished file created, so a broken
                    # data type never litters the outliner.
                    remove_objects_created_since(datatype_collection, objects_before)

                    error_msg = tr("Import failed, skipped: {path} | Error: {error}").format(path=fmt_filepath, error=e)
                    print(error_msg)
                    self.report({'WARNING'}, error_msg)
                    continue

                datatype_object_count = len(datatype_collection.objects)

                # Nico: note that after reversing Wuthering Waves Mod models, normals may be incorrect.
                # This should not be handled automatically; the user should handle it manually,
                # since some models have the issue and others do not.
                # Forcing a fix may make the normals incorrect.

            if datatype_object_count <= 0:
                # No file of this data type produced a mesh: drop the empty
                # collection instead of leaving it in the outliner.
                bpy.data.collections.remove(datatype_collection)
                continue

            imported_object_count += datatype_object_count

        if imported_object_count == 0:
            # Every .fmt file failed. Remove the empty collection tree that the
            # import created, otherwise the outliner keeps an empty "reverse
            # result" collection and the user cannot tell what went wrong.
            remove_collection_tree(reverse_collection)
            self.report({"ERROR"}, tr("No fmt files were imported from the ib_vb_fmt reverse result"))
            return {'FINISHED'}

        prune_empty_collections(reverse_collection)

        self.report({'INFO'}, tr("Imported {count} mesh object(s) from the ib_vb_fmt reverse result.").format(count=imported_object_count))

        # Then point the image path to the current path
        reload_textures_from_folder(reverse_output_folder_path)

        return {'FINISHED'}


class SWORD4CheckReverseSource(I18nOperator):
    bl_idname = "mimi.sword_check_reverse_source"
    bl_label = "Check Reverse Folder"
    bl_description = "Check again whether the folder selected in the Mod Reverse panel can be imported"

    def execute(self, context):
        # Check the folder again from disk: the folder content can change while
        # the selected path stays the same (for example after a new reverse).
        clear_sword_reverse_probe_cache()
        folder_path, error_message = resolve_sword_reverse_source_folder(context.scene)
        if error_message:
            self.report({'ERROR'}, error_message)
            return {'FINISHED'}

        folder_probe = get_sword_reverse_probe(folder_path, force=True)
        if folder_probe["status"] != STATUS_OK:
            self.report(
                {'ERROR'},
                sword_reverse_probe_message(folder_probe, context.scene.mimi_sword_reverse_source_mode),
            )
            return {'FINISHED'}

        self.report({'INFO'}, tr("This folder can be imported normally: {groups} DrawIB folder(s), {types} data type(s)").format(
            groups=folder_probe["group_count"],
            types=folder_probe["data_type_count"],
        ))
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


def draw_sword_reverse_source_status(layout, context):
    """Draw the "this folder can / cannot be imported" hint.

    The hint follows the current import mode: it checks the folder MMT recorded,
    the selected workspace, or the folder the user picked by hand. The result is
    cached per folder path, so drawing the panel stays cheap.
    """
    scene = context.scene
    folder_path, error_message = get_sword_reverse_source(scene)
    folder_probe = get_sword_reverse_probe(folder_path)

    source_box = layout.box()

    # Header: the plain yes / no answer plus a button to check again, because
    # the folder content can change while the selected path stays the same.
    header_row = source_box.row(align=True)
    if folder_probe["status"] == STATUS_OK:
        header_row.label(text=tr("This folder can be imported normally"), icon='CHECKMARK')
    else:
        header_row.label(text=tr("This folder cannot be imported normally"), icon='ERROR')
    header_row.operator(SWORD4CheckReverseSource.bl_idname, text="", icon='FILE_REFRESH')

    if error_message:
        # The folder could not even be resolved (no workspace selected, empty
        # custom path, ...): that message explains more than the folder check.
        source_box.label(text=error_message)
        return

    if folder_probe["status"] == STATUS_OK:
        source_box.label(text=tr("{groups} DrawIB folder(s), {types} data type(s)").format(
            groups=folder_probe["group_count"],
            types=folder_probe["data_type_count"],
        ))
        if folder_probe["incomplete_groups"]:
            # These groups would import nothing; saying so avoids the surprise.
            source_box.label(
                text=tr("{count} DrawIB folder(s) contain invalid descriptors or missing buffers").format(
                    count=len(folder_probe["incomplete_groups"]),
                ),
                icon='ERROR',
            )
        return

    source_box.label(text=sword_reverse_probe_message(folder_probe, scene.mimi_sword_reverse_source_mode))
    if folder_probe["status"] == STATUS_TOO_SHALLOW and folder_probe["suggested_folders"]:
        # Naming the workspaces is the fastest way out of this mistake.
        source_box.label(text=tr("Its subfolders do hold reverse results, for example:"))
        for folder_name in folder_probe["suggested_folders"]:
            source_box.label(text="    " + folder_name)
        if folder_probe["suggested_total"] > len(folder_probe["suggested_folders"]):
            source_box.label(text=tr("... and {count} more").format(
                count=folder_probe["suggested_total"] - len(folder_probe["suggested_folders"]),
            ))


# Panel UI layout
@translatable
class MIMISword_ImageMaterialPanel(Panel):
    bl_label = "Mod Reverse Panel"
    bl_idname = "MIMI_PT_image_material"
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

        # Tell the user whether the selected folder can be imported at all, so a
        # wrong pick (wrong level, empty folder, buffers not copied) shows up
        # before the import runs instead of ending in an empty collection.
        draw_sword_reverse_source_status(layout, context)

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
    bl_idname = "MIMI_PT_sword_split_model_by_draw_indexed"
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
    bpy.utils.register_class(SWORD4CheckReverseSource)
    bpy.utils.register_class(MIMISword_SplitModel_Panel)

    bpy.types.Scene.mimi_sword_image_list = CollectionProperty(type=MIMISword_ImportTexture_ImageListItem)
    bpy.types.Scene.mimi_sword_image_list_index = IntProperty(default=0)
    bpy.types.Scene.mimi_sword_reverse_source_mode = EnumProperty(
        name=tr("Import Mode"),
        description=tr("Controls the folder source used when importing reverse results in one click"),
        items=_get_sword_reverse_source_mode_items,
        # Any change of the folder source invalidates the cached folder check.
        update=_on_sword_reverse_source_changed,
        # Dynamic items only allow integer (0-based) defaults; the first item
        # ("LAST") is the intended default, so the argument is omitted.
    )
    bpy.types.Scene.mimi_sword_specific_reversed_workspace_name = EnumProperty(
        name=tr("Specified Workspace"),
        description=tr("Subfolders under Reversed in the current MMT / MIMITools cache folder"),
        items=_get_sword_reversed_workspace_items,
        update=_on_sword_reverse_source_changed,
    )
    bpy.types.Scene.mimi_sword_custom_reverse_output_folder_path = StringProperty(
        name=tr("Custom Folder"),
        description=tr("Manually specify the folder used for the one-click import of reverse results"),
        default="",
        subtype='DIR_PATH',
        # Permit Blender-relative file browser paths; resolve them at import.
        options={'PATH_SUPPORTS_BLEND_RELATIVE'},
        # Fires right after the user picks a folder, so the yes / no hint under
        # the field follows the new selection immediately.
        update=_on_sword_reverse_source_changed,
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
    bpy.utils.unregister_class(SWORD4CheckReverseSource)
    bpy.utils.unregister_class(MIMISWORD_UL_FastImportTextureList)
    bpy.utils.unregister_class(MIMISword_ImportTexture_ImageListItem)
    clear_sword_reverse_probe_cache()
                
