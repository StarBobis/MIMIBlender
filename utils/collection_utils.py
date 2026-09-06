import bpy

from ..common.global_config import GlobalConfig

class CollectionColor:
    '''
    WorkSpaceCollectionColor (Workspace Collection)
    DrawIBCollectionColor (DrawIB Collection)
    ComponentCollectionColor (Component Collection)
    
    GroupCollection (Group Collection)
    ToggleCollection (Toggle Collection)
    SwitchCollection (Switch Collection)

    '''
    White = "NONE"
    Red = "COLOR_01"
    Orange = "COLOR_02"
    Yellow = "COLOR_03"
    Green = "COLOR_04"
    Blue = "COLOR_05"
    Purple = "COLOR_06"
    Pink = "COLOR_07"
    Brown = "COLOR_08"

    WorkSpaceCollectionColor = "COLOR_01"
    DrawIBCollectionColor = "COLOR_07"
    ComponentCollectionColor = "COLOR_05"

    GroupCollection = "NONE"
    ToggleCollection = "COLOR_03" 
    SwitchCollection = "COLOR_04"
    

class CollectionUtils:
    @staticmethod
    def get_collection_by_name(collection_name:str):
        """
        Get the collection object with the given name.

        :param collection_name: The name of the collection to get
        :return: The found collection object, or None if not found
        """
        # Try to get the collection with the given name from bpy.data.collections
        if collection_name in bpy.data.collections:
            return bpy.data.collections[collection_name]
        else:
            print(f"Collection named '{collection_name}' not found")
            return None
    
    # Recursive select every object in a collection and it's sub collections.
    @staticmethod
    def select_collection_objects(collection):
        def recurse_collection(col):
            for obj in col.objects:
                obj.select_set(True)
            for subcol in col.children_recursive:
                recurse_collection(subcol)

        recurse_collection(collection)

    @staticmethod
    def deselect_collection_objects(collection):
        """Clear selection introduced by an import without touching other objects."""
        objects = tuple(collection.all_objects)
        for obj in objects:
            obj.select_set(False)

        active_object = bpy.context.view_layer.objects.active
        if active_object in objects:
            bpy.context.view_layer.objects.active = None

    @staticmethod
    def find_layer_collection(view_layer, collection_name):
        def recursive_search(layer_collections, collection_name):
            for layer_collection in layer_collections:
                if layer_collection.collection.name == collection_name:
                    return layer_collection
                found = recursive_search(layer_collection.children, collection_name)
                if found:
                    return found
            return None

        return recursive_search(view_layer.layer_collection.children, collection_name)

    @staticmethod
    def get_collection_properties(collection_name:str):
        # Nico: Blender Gacha: 
        # Can't get collection's property by bpy.context.collection or it's children or any of children's children.
        # Can only get it's property by search it recursively in bpy.context.view_layer  

        # Get the currently active view layer
        view_layer = bpy.context.view_layer

        # Find the collection with the given name
        collection1 = bpy.data.collections.get(collection_name,None)
        
        if not collection1:
            print(f"Collection '{collection_name}' does not exist")
            return None

        # Recursively find the collection's layer collection in the current view layer
        layer_collection = CollectionUtils.find_layer_collection(view_layer, collection_name)

        if not layer_collection:
            print(f"Collection '{collection_name}' is not in the current view layer")
            return None

        # Get the collection's actual properties
        hide_viewport = layer_collection.hide_viewport
        exclude = layer_collection.exclude

        return {
            'name': collection1.name,
            'hide_viewport': hide_viewport,
            'exclude': exclude
        }
    
    @staticmethod
    def is_collection_visible(collection_name:str):
        '''
        Check whether the collection is visible: it is visible only when not hidden and not excluded
        '''
        collection_property = CollectionUtils.get_collection_properties(collection_name)

        if collection_property is not None:
            if collection_property["hide_viewport"]:
                return False
            if collection_property["exclude"]:
                return False
            else:
                return True
        else:
            return False
    
    @staticmethod
    # get_collection_name_without_default_suffix
    def get_clean_collection_name(collection_name:str):
        if "." in collection_name:
            new_collection_name = collection_name.split(".")[0]
            return new_collection_name
        else:
            return collection_name

    
    @staticmethod
    def create_new_collection(collection_name:str,color_tag:CollectionColor=CollectionColor.White,link_to_parent_collection_name:str = ""):
        '''
        Create a new collection and optionally link it to a parent collection
        :param collection_name: The collection name
        :param color_tag: The color tag of the collection  defaults to white when not specified
        :param link_to_parent_collection_name: If not empty, links the newly created collection to the specified parent collection
        '''
        new_collection = bpy.data.collections.new(collection_name)
        new_collection.color_tag = color_tag
        
        if link_to_parent_collection_name:
            parent_collection = CollectionUtils.get_collection_by_name(link_to_parent_collection_name)
            if parent_collection:
                parent_collection.children.link(new_collection)
        
        return new_collection
    
    @staticmethod
    def is_valid_ssmt_workspace_collection(workspace_collection) -> str:
        '''
        After the Generate Mod button is pressed, verify whether the selected collection is a workspace collection and provide an error message if not
        The check is done here: return the corresponding error message if there is a problem, otherwise return an empty string
        The caller receives the result: report and return if it is not an empty string; execution may continue only when it is an empty string.
        '''
        if len(workspace_collection.children) == 0:
            return "The currently selected collection has no child collections, so it is not a valid workspace collection"

        for draw_ib_collection in workspace_collection.children:
            # Skip hide collection.
            if not CollectionUtils.is_collection_visible(draw_ib_collection.name):
                continue

            # get drawib
            draw_ib_alias_name = CollectionUtils.get_clean_collection_name(draw_ib_collection.name)
            if "_" not in draw_ib_alias_name:
                return "A DrawIB collection in the selected collection was renamed unexpectedly, so the DrawIB can no longer be recognized\n1.Do not rename collections named after the drawib_aliasname at import time\n2.Please confirm that you selected the workspace collection correctly."
        
            # If the current collection has no child collections, it is not a valid branch Mod
            if len(draw_ib_collection.children) == 0:
                return "The selected collection is not a standard branch model collection. Please check whether the model was imported as branch collections: " + draw_ib_collection.name + " which has no child collections detected"
            
        return ""
    
    @staticmethod
    def is_valid_ssmt_workspace_collection_v2(workspace_collection) -> str:
        '''
        After the Generate Mod button is pressed, verify whether the selected collection is a workspace collection and provide an error message if not
        The check is done here: return the corresponding error message if there is a problem, otherwise return an empty string
        The caller receives the result: report and return if it is not an empty string; execution may continue only when it is an empty string.
        '''
        clean_workspace_collection_name = CollectionUtils.get_clean_collection_name(workspace_collection.name)

        if clean_workspace_collection_name != GlobalConfig.get_workspace_name():

            msg = (
                "The selected collection's name is not the workspace collection name. Please check whether you selected the workspace collection correctly.\nSelected collection name: " 
                + clean_workspace_collection_name  + "\n"
                + "A valid workspace collection should use the current workspace name " + GlobalConfig.get_workspace_name() + " as its name prefix" + "\n"
                + "1.The workspace collection is the red, workspace-named collection obtained from the one-click import after extracting a model in the SSMT workbench" + "\n"
                + "2.The workspace collection's color is fixed to red; please check whether you selected the wrong one" + "\n"
                + "3.You must manually select the workspace collection so the system knows which collection's contents you want to generate a Mod for"
            )

            return msg
            
        return ""

    @staticmethod
    def get_selected_collections() -> list[bpy.types.Collection]:
        """
        Return all collections currently selected in the Outliner
        """
        return [item for item in bpy.context.selected_ids if isinstance(item, bpy.types.Collection)]
    
