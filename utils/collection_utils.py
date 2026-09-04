import bpy

from ..common.global_config import GlobalConfig

class CollectionColor:
    '''
    WorkSpaceCollectionColor 【工作空间集合】
    DrawIBCollectionColor 【DrawIB集合】
    ComponentCollectionColor 【Component集合】
    
    GroupCollection 【组集合】
    ToggleCollection 【按键开关集合】
    SwitchCollection 【按键切换集合】

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
        根据集合名称获取集合对象。

        :param collection_name: 要获取的集合名称
        :return: 返回找到的集合对象，如果未找到则返回 None
        """
        # 尝试从 bpy.data.collections 获取指定名称的集合
        if collection_name in bpy.data.collections:
            return bpy.data.collections[collection_name]
        else:
            print(f"未找到名称为 '{collection_name}' 的集合")
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

        # 获取当前活动的视图层
        view_layer = bpy.context.view_layer

        # 查找指定名称的集合
        collection1 = bpy.data.collections.get(collection_name,None)
        
        if not collection1:
            print(f"集合 '{collection_name}' 不存在")
            return None

        # 递归查找集合在当前视图层中的层集合对象
        layer_collection = CollectionUtils.find_layer_collection(view_layer, collection_name)

        if not layer_collection:
            print(f"集合 '{collection_name}' 不在当前视图层中")
            return None

        # 获取集合的实际属性
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
        判断collection是否可见，可见的状态是不隐藏且勾选上
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
        创建一个新的集合，并且可以选择是否链接到父集合
        :param collection_name: 集合名称
        :param color_tag: 集合颜色标签  不填则默认为白色
        :param link_to_parent_collection_name: 如果不为空，则将新创建的集合链接到指定的父集合
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
        按下生成Mod按钮之后，要判断当前选中的集合是否为工作空间集合，并且给出报错信息
        所以在这里进行校验，如果有问题就返回对应的报错信息，如果没有就返回空字符串
        在外面接收结果，判断如果不是空字符串就report然后返回，是空字符串才能继续执行。
        '''
        if len(workspace_collection.children) == 0:
            return "当前选中的集合没有任何子集合，不是正确的工作空间集合"

        for draw_ib_collection in workspace_collection.children:
            # Skip hide collection.
            if not CollectionUtils.is_collection_visible(draw_ib_collection.name):
                continue

            # get drawib
            draw_ib_alias_name = CollectionUtils.get_clean_collection_name(draw_ib_collection.name)
            if "_" not in draw_ib_alias_name:
                return "当前选中集合中的DrawIB集合名称被意外修改导致无法识别到DrawIB\n1.请不要修改导入时以drawib_aliasname为名称的集合\n2.请确认您是否正确选中了工作空间集合."
        
            # 如果当前集合没有子集合，说明不是一个合格的分支Mod
            if len(draw_ib_collection.children) == 0:
                return "当前选中集合不是一个标准的分支模型集合，请检查您是否以分支集合方式导入了模型: " + draw_ib_collection.name + " 未检测到任何子集合"
            
        return ""
    
    @staticmethod
    def is_valid_ssmt_workspace_collection_v2(workspace_collection) -> str:
        '''
        按下生成Mod按钮之后，要判断当前选中的集合是否为工作空间集合，并且给出报错信息
        所以在这里进行校验，如果有问题就返回对应的报错信息，如果没有就返回空字符串
        在外面接收结果，判断如果不是空字符串就report然后返回，是空字符串才能继续执行。
        '''
        clean_workspace_collection_name = CollectionUtils.get_clean_collection_name(workspace_collection.name)

        if clean_workspace_collection_name != GlobalConfig.get_workspace_name():

            msg = (
                "当前选中的集合名称不是工作空间集合名称，请检查您是否正确选中了工作空间集合.\n当前选中集合名称: " 
                + clean_workspace_collection_name  + "\n"
                + "正确的工作空间集合应该以当前工作空间名称 " + GlobalConfig.get_workspace_name() + " 作为名称前缀" + "\n"
                + "1.工作空间集合指的是在SSMT工作台提取模型后，一键导入后的红色的以工作空间为名称的集合" + "\n"
                + "2.工作空间集合的颜色固定是红色的，请检查是否选择错误" + "\n"
                + "3.您必须手动选中工作空间集合，系统才能知道您要为哪个集合下的内容生成Mod"
            )

            return msg
            
        return ""

    @staticmethod
    def get_selected_collections() -> list[bpy.types.Collection]:
        """
        返回 Outliner 里当前被选中的所有集合
        """
        return [item for item in bpy.context.selected_ids if isinstance(item, bpy.types.Collection)]
    
