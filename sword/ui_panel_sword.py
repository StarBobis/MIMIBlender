import bpy
import os
import shutil
from bpy.props import StringProperty, CollectionProperty, IntProperty, BoolProperty, EnumProperty
from bpy.types import Operator, Panel, PropertyGroup, UIList
from bpy_extras.io_utils import ImportHelper
import bpy.utils.previews

from ..utils.obj_utils import ObjUtils

from .mesh_import_helper import MigotoBinaryFile, MeshImportHelper
from ..common.global_config import GlobalConfig
from ..common.ssmt_import_helper import SSMTImportHelper
from ..ui.ui_func_import_ssmt import SSMT4ImportRaw

from ..utils.translate_utils import iface_, rpt_
from ..utils.json_utils import JsonUtils
from ..utils.collection_utils import CollectionUtils,CollectionColor

# 存储预览图集合
preview_collections = {}
sword_reversed_workspace_items_cache = []


def _get_sword_reversed_workspace_items(self, context):
    global sword_reversed_workspace_items_cache

    try:
        # Sword4 panel reads MMT toolchain only, never the SSMT cache folder.
        reversed_root = GlobalConfig.path_mimitools_reversed_root()
        if not reversed_root or not os.path.isdir(reversed_root):
            sword_reversed_workspace_items_cache = [
                ("", "当前没有可用逆向工作空间", "请确认 MMT / MIMITools 缓存目录下存在 Reversed 文件夹")
            ]
            return sword_reversed_workspace_items_cache

        folder_names = sorted(
            [entry.name for entry in os.scandir(reversed_root) if entry.is_dir()]
        )
        if not folder_names:
            sword_reversed_workspace_items_cache = [
                ("", "当前没有可用逆向工作空间", "Reversed 文件夹下未找到子文件夹")
            ]
            return sword_reversed_workspace_items_cache

        sword_reversed_workspace_items_cache = [(name, name, "") for name in folder_names]
        return sword_reversed_workspace_items_cache
    except Exception:
        sword_reversed_workspace_items_cache = [
            ("", "当前没有可用逆向工作空间", "读取 Reversed 文件夹失败")
        ]
        return sword_reversed_workspace_items_cache

# 定义图片列表项
class Sword_ImportTexture_ImageListItem(PropertyGroup):
    name: StringProperty(name="图片名称") # type: ignore
    filepath: StringProperty(name="文件路径") # type: ignore

# 自定义UI列表显示图片和缩略图
class SWORD_UL_FastImportTextureList(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        pcoll = preview_collections["main"]
        
        if self.layout_type in {'DEFAULT', 'Expand'}:
            # 尝试获取预览图标
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

# 选择文件夹操作符
class Sword_ImportTexture_WM_OT_SelectImageFolder(Operator, ImportHelper):
    bl_idname = "wm.select_image_folder"
    bl_label = "选择预览贴图所在的文件夹位置"
    
    directory: StringProperty(subtype='DIR_PATH') # type: ignore
    filter_folder: BoolProperty(default=True, options={'HIDDEN'}) # type: ignore
    filter_image: BoolProperty(default=False, options={'HIDDEN'}) # type: ignore

    def execute(self, context):
        # 清空之前的列表
        context.scene.sword_image_list.clear()
        
        # 清空预览集合
        pcoll = preview_collections["main"]
        pcoll.clear()
        
        # 支持的图片格式
        image_extensions = ('.jpg', '.jpeg', '.png', '.tiff', '.bmp', '.tga', '.exr', '.hdr','.dds')
        
        # 遍历文件夹，收集图片文件
        image_count = 0
        for filename in os.listdir(self.directory):
            if filename.lower().endswith(image_extensions):
                full_path = os.path.join(self.directory, filename)
                if os.path.isfile(full_path):
                    item = context.scene.sword_image_list.add()
                    item.name = filename
                    item.filepath = full_path
                    
                    # 加载预览图
                    try:
                        thumb = pcoll.load(filename, full_path, 'IMAGE')
                        image_count += 1
                    except Exception as e:
                        print(f"Could not load preview for {filename}: {e}")
        
        self.report({'INFO'}, rpt_("已扫描 {count} 张图片。").format(count=image_count))
        return {'FINISHED'}
    

def reload_textures_from_folder(picture_folder_path:str):
    # 清空之前的列表和预览
    bpy.context.scene.sword_image_list.clear()
    pcoll = preview_collections["main"]
    pcoll.clear()
    
    # 支持的图片格式
    image_extensions = ('.jpg', '.jpeg', '.png', '.tiff', '.bmp', '.tga', '.exr', '.hdr', '.dds')
    
    # 遍历文件夹，收集图片文件
    image_count = 0
    for filename in os.listdir(picture_folder_path):
        if filename.lower().endswith(image_extensions):
            full_path = os.path.join(picture_folder_path, filename)
            if os.path.isfile(full_path):
                item = bpy.context.scene.sword_image_list.add()
                item.name = filename
                item.filepath = full_path
                
                # 加载预览图
                try:
                    thumb = pcoll.load(filename, full_path, 'IMAGE')
                    image_count += 1
                except Exception as e:
                    print(f"Could not load preview for {filename}: {e}")


# 自动检测并设置DedupedTextures_jpg文件夹
class Sword_ImportTexture_WM_OT_AutoDetectTextureFolder(Operator):
    bl_idname = "wm.auto_detect_texture_folder"
    bl_label = "自动检测提取的贴图文件夹"
    
    def execute(self, context):
        selected_objects = context.selected_objects
        if not selected_objects:
            self.report({'ERROR'}, rpt_("没有选中的对象！"))
            return {'CANCELLED'}
        
        # 获取第一个选中的对象
        obj = selected_objects[0]
        obj_name = obj.name 
        
        # 构建路径
        selected_drawib_folder_path = os.path.join(GlobalConfig.path_workspace_folder(),  obj_name.split("-")[0] + "\\"  )
        
        deduped_textures_jpg_folder_path = os.path.join(selected_drawib_folder_path, "DedupedTextures_jpg\\")
        deduped_textures_png_folder_path = os.path.join(selected_drawib_folder_path, "DedupedTextures_png\\")
        deduped_textures_tga_folder_path = os.path.join(selected_drawib_folder_path, "DedupedTextures_tga\\")

        deduped_textures_jpg_exists = os.path.exists(deduped_textures_jpg_folder_path)
        deduped_textures_png_exists = os.path.exists(deduped_textures_png_folder_path)
        deduped_textures_tga_exists = os.path.exists(deduped_textures_tga_folder_path)

        
        # 检查路径是否存在
        if not deduped_textures_jpg_exists and not deduped_textures_png_exists and not deduped_textures_tga_exists:
            self.report({'ERROR'}, rpt_("未找到当前DrawIB: {draw_ib}的DedupedTextures转换后的贴图文件夹，请确保此IB在当前工作空间中已经正常提取出来了").format(draw_ib=obj_name.split("-")[0]))
            return {'CANCELLED'}
        
        # 清空之前的列表和预览
        context.scene.sword_image_list.clear()
        pcoll = preview_collections["main"]
        pcoll.clear()
        
        # 支持的图片格式
        image_extensions = ('.jpg', '.jpeg', '.png', '.tiff', '.bmp', '.tga', '.exr', '.hdr','.dds')
        
        # 遍历文件夹，收集图片文件
        image_count = 0
        for filename in os.listdir(deduped_textures_jpg_folder_path):
            if filename.lower().endswith(image_extensions):
                full_path = os.path.join(deduped_textures_jpg_folder_path, filename)
                if os.path.isfile(full_path):
                    item = context.scene.sword_image_list.add()
                    item.name = filename
                    item.filepath = full_path
                    
                    # 加载预览图
                    try:
                        thumb = pcoll.load(filename, full_path, 'IMAGE')
                        image_count += 1
                    except Exception as e:
                        print(f"Could not load preview for {filename}: {e}")
        
        self.report({'INFO'}, rpt_("已自动检测并从 DedupedTextures_jpg 文件夹加载 {count} 张图片。").format(count=image_count))
        return {'FINISHED'}



# 应用图片到材质操作符
class Sword_ImportTexture_WM_OT_ApplyImageToMaterial(Operator):
    bl_idname = "wm.apply_image_to_material"
    bl_label = "应用贴图到选中的物体"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        scene = context.scene
        selected_index = scene.sword_image_list_index
        
        if selected_index < 0 or selected_index >= len(scene.sword_image_list):
            self.report({'ERROR'}, rpt_("列表中未选择任何图片。"))
            return {'CANCELLED'}
        
        selected_image = scene.sword_image_list[selected_index]
        image_path = selected_image.filepath
        
        # 获取或创建图像数据块
        image_data = bpy.data.images.load(image_path, check_existing=True)
        
        selected_objects = context.selected_objects
        if not selected_objects:
            self.report({'ERROR'}, rpt_("没有选中的对象！"))
            return {'CANCELLED'}
        
        applied_count = 0
        for obj in selected_objects:
            if obj.type != 'MESH':
                continue  # 跳过非网格对象
            
            # 确保对象有材质数据块
            if not obj.data.materials:
                mat = bpy.data.materials.new(name=f"Mat_{selected_image.name}")
                obj.data.materials.append(mat)
            else:
                # 使用第一个材质槽
                mat = obj.data.materials[0]

                # 如果第一个槽位是空的(None)，创建一个新材质并填入
                if mat is None:
                    mat = bpy.data.materials.new(name=f"Mat_{selected_image.name}")
                    obj.data.materials[0] = mat
            
            # 确保材质使用节点
            mat.use_nodes = True
            nodes = mat.node_tree.nodes
            links = mat.node_tree.links
            
            # 查找或创建Principled BSDF节点
            bsdf_node = nodes.get("Principled BSDF")
            if not bsdf_node:
                # 这里是根据名称获取，所以中英文都要添加支持
                print("疑似英文Principled BSDF无法获取，尝试获取中文的原理化 BSDF")
                bsdf_node = nodes.get("原理化 BSDF")
            
            # 3.6的原理化没有空格，他娘滴，每个版本还不一样
            if not bsdf_node:
                # 这里是根据名称获取，所以中英文都要添加支持
                print("疑似英文Principled BSDF无法获取，尝试获取中文的原理化 BSDF")
                bsdf_node = nodes.get("原理化BSDF")

            if not bsdf_node:
                print("BSDF not exists ,ready to create one.")
                bsdf_node = nodes.new(type='ShaderNodeBsdfPrincipled')
                bsdf_node.location = (0, 0)
                
                # 获取材质输出节点
                output_node = nodes.get("Material Output")
                if not output_node:
                    output_node = nodes.new(type='ShaderNodeOutputMaterial')
                    output_node.location = (400, 0)
                
                # 连接到输出
                links.new(bsdf_node.outputs['BSDF'], output_node.inputs['Surface'])
            
            # 创建图像纹理节点
            tex_image = nodes.new('ShaderNodeTexImage')
            tex_image.image = image_data
            tex_image.location = (-300, 0)
            
            # 将图像纹理节点的Color输出连接到BSDF的Base Color输入
            links.new(tex_image.outputs['Color'], bsdf_node.inputs['Base Color'])
            links.new(tex_image.outputs['Alpha'], bsdf_node.inputs['Alpha'])

            applied_count += 1
        
        self.report({'INFO'}, rpt_("已将 {image_name} 应用到 {count} 个物体。").format(image_name=selected_image.name, count=applied_count))
        return {'FINISHED'}


class SwordImportAllReversed(bpy.types.Operator):
    bl_idname = "ssmt.import_all_reverse"
    bl_label = "一键导入逆向出来的全部模型"
    bl_description = "把上一次一键逆向出来的所有模型全部导入到Blender，然后你可以手动筛选并删除错误的数据类型，流程上更加方便。支持 ib_vb_fmt 和 ssmt_fmt 两种逆向输出格式。"
    bl_options = {'REGISTER', 'UNDO'}

    def _resolve_reverse_output_folder_path(self, context):
        # Reversed paths come from MMT settings only, no SSMT config needed.
        source_mode = context.scene.sword_reverse_source_mode
        if source_mode == "SPECIFIC":
            selected_workspace_name = context.scene.sword_specific_reversed_workspace_name
            if not selected_workspace_name:
                self.report({"ERROR"}, "当前未选择指定工作空间，请先选择 Reversed 下的子文件夹")
                return ""
            # Sword4 panel reads MMT toolchain only, never the SSMT cache folder.
            reversed_root = GlobalConfig.path_mimitools_reversed_root()
            if not reversed_root:
                self.report({"ERROR"}, "未找到 MMT 的 Reversed 目录，请先在 MMT 中运行一键逆向")
                return ""
            return os.path.join(reversed_root, selected_workspace_name)

        if source_mode == "CUSTOM":
            custom_folder_path = str(context.scene.sword_custom_reverse_output_folder_path).strip()
            if not custom_folder_path:
                self.report({"ERROR"}, "自定义目录为空，请先选择目录")
                return ""
            return custom_folder_path

        return GlobalConfig.path_mimitools_reverse_output_folder() or GlobalConfig.path_reverse_output_folder()

    def execute(self, context):
        reverse_output_folder_path = self._resolve_reverse_output_folder_path(context)
        if not reverse_output_folder_path:
            return {'FINISHED'}

        if not os.path.exists(reverse_output_folder_path) or not os.path.isdir(reverse_output_folder_path):
            self.report({"ERROR"},"当前一键逆向结果中标注的文件夹位置不存在，请重新运行一键逆向")
            return {'FINISHED'}
        print("测试导入")

        # MMT 逆向成功后会写入 ReverseOutputFormat 键值（与 ReverseOutputFolder 对称）
        # ib_vb_fmt 走旧的 .fmt 解析导入，ssmt_fmt 走 SSMT Json 导入
        # 找不到该键值时直接视为 ib_vb_fmt 格式
        reverse_output_format = GlobalConfig.reverse_output_format()
        if reverse_output_format == "ssmt_fmt":
            return self._import_ssmt_fmt(context, reverse_output_folder_path)
        return self._import_ib_vb_fmt(context, reverse_output_folder_path)

    def _import_ssmt_fmt(self, context, reverse_output_folder_path):
        '''
        ssmt_fmt 格式导入：
        遍历逆向输出文件夹下的所有子文件夹，每个子文件夹内可能有多个Json文件，
        Json文件的名称就是它的数据类型，对每个Json文件创建 drawib_数据类型名称 的集合并导入。
        '''
        total_folder_name = os.path.basename(reverse_output_folder_path)

        reverse_collection = CollectionUtils.create_new_collection(collection_name=total_folder_name,color_tag=CollectionColor.Red)
        bpy.context.scene.collection.children.link(reverse_collection)

        # 获取所有子文件夹
        subfolder_path_list = [f.path for f in os.scandir(reverse_output_folder_path) if f.is_dir()]
        if not subfolder_path_list:
            self.report({"ERROR"}, "目标目录下未找到可导入的子文件夹")
            return {'FINISHED'}

        imported_count = 0
        for subfolder_path in subfolder_path_list:

            # 获取所有.json文件，Json文件的名称就是它的数据类型
            json_files = []
            for file in os.listdir(subfolder_path):
                if file.endswith('.json'):
                    json_files.append(os.path.join(subfolder_path, file))

            for json_filepath in json_files:
                # 获取带后缀的文件名
                filename_with_extension = os.path.basename(json_filepath)
                # 去掉后缀即为数据类型名称
                datatype_name = os.path.splitext(filename_with_extension)[0]

                # 对每个Json文件的名称创建 drawib_数据类型名称 的集合
                datatype_collection = CollectionUtils.create_new_collection(collection_name="drawib_" + datatype_name,color_tag=CollectionColor.White, link_to_parent_collection_name=reverse_collection.name)

                try:
                    # 调用SSMT格式导入功能
                    SSMTImportHelper.create_mesh_from_json(json_file_path=json_filepath, import_collection=datatype_collection)
                    imported_count += 1
                except Exception as e:
                    error_msg = f"导入失败，已跳过: {json_filepath} | 错误: {e}"
                    print(error_msg)
                    self.report({'WARNING'}, error_msg)
                    continue

        if imported_count == 0:
            self.report({"ERROR"}, "SSMT格式逆向结果中未成功导入任何Json文件")
            return {'FINISHED'}

        # 随后把图片路径指定为当前路径
        reload_textures_from_folder(reverse_output_folder_path)

        return {'FINISHED'}

    def _import_ib_vb_fmt(self, context, reverse_output_folder_path):
        total_folder_name = os.path.basename(reverse_output_folder_path)

        reverse_collection = CollectionUtils.create_new_collection(collection_name=total_folder_name,color_tag=CollectionColor.Red)
        bpy.context.scene.collection.children.link(reverse_collection)

        # 获取所有子文件夹
        subfolder_path_list = [f.path for f in os.scandir(reverse_output_folder_path) if f.is_dir()]
        if not subfolder_path_list:
            self.report({"ERROR"}, "目标目录下未找到可导入的子文件夹")
            return {'FINISHED'}

        for subfolder_path in subfolder_path_list:
            
            datatype_folder_name = os.path.basename(subfolder_path)

            datatype_collection = CollectionUtils.create_new_collection(collection_name=datatype_folder_name,color_tag=CollectionColor.White, link_to_parent_collection_name=reverse_collection.name)

            # 获取所有.fmt文件
            fmt_files = []
            for file in os.listdir(subfolder_path):
                if file.endswith('.fmt'):
                    fmt_files.append(os.path.join(subfolder_path, file))

            for fmt_filepath in fmt_files:
                # 获取带后缀的文件名
                filename_with_extension = os.path.basename(fmt_filepath)
                # 去掉后缀
                filename_without_extension = os.path.splitext(filename_with_extension)[0]
                try:
                    # 调用导入功能
                    mbf = MigotoBinaryFile(fmt_path=fmt_filepath, mesh_name=filename_without_extension)
                    MeshImportHelper.create_mesh_obj_from_mbf(mbf=mbf, import_collection=datatype_collection)
                except Exception as e:
                    error_msg = f"导入失败，已跳过: {fmt_filepath} | 错误: {e}"
                    print(error_msg)
                    self.report({'WARNING'}, error_msg)
                    continue

                
                # Nico: 注意，鸣潮Mod逆向的模型导入后，可能会出现法线不正确的问题
                # 此时不应该自动处理，而是用户手动处理，因为部分模型有部分模型没有
                # 强行清除可能会导致法线不正确



        # 随后把图片路径指定为当前路径
        reload_textures_from_folder(reverse_output_folder_path)

        return {'FINISHED'}


class SWORD4RefreshReversedWorkspaceList(bpy.types.Operator):
    bl_idname = "ssmt4.sword_refresh_reversed_workspace_list"
    bl_label = "刷新逆向工作空间列表"
    bl_description = "刷新当前 MMT / MIMITools 缓存目录下 Reversed 文件夹的子文件夹列表"

    def execute(self, context):
        # Reversed workspace list comes from MMT settings only.
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                area.tag_redraw()

        self.report({'INFO'}, iface_("已刷新逆向工作空间列表"))
        return {'FINISHED'}


class Import3DMigotoRaw(bpy.types.Operator, ImportHelper):
    """Import raw 3DMigoto vertex and index buffers"""
    bl_idname = "import_mesh.migoto_raw_buffers_mmt"
    bl_label = "导入.fmt .ib .vb格式模型"
    bl_description = "导入3Dmigoto格式的 .ib .vb .fmt文件，只需选择.fmt文件即可"
    bl_options = {'REGISTER','UNDO'}

    # 我们只需要选择fmt文件即可，因为其它文件都是根据fmt文件的前缀来确定的。
    # 所以可以实现一个.ib 和 .vb文件存在多个数据类型描述的.fmt文件的导入。
    filename_ext = '.fmt'

    filter_glob: bpy.props.StringProperty(
        default='*.fmt',
        options={'HIDDEN'},
    ) # type: ignore

    files: bpy.props.CollectionProperty(
        name="File Path",
        type=bpy.types.OperatorFileListElement,
    ) # type: ignore

    def execute(self, context):
        # 我们需要添加到一个新建的集合里，方便后续操作
        # 这里集合的名称需要为当前文件夹的名称
        dirname = os.path.dirname(self.filepath)

        collection_name = os.path.basename(dirname)
        collection = bpy.data.collections.new(collection_name)
        bpy.context.scene.collection.children.link(collection)

        # 如果用户不选择任何fmt文件，则默认返回读取所有的fmt文件。
        import_filename_list = []
        if len(self.files) == 1:
            if str(self.filepath).endswith(".fmt"):
                import_filename_list.append(self.filepath)
            else:
                for filename in os.listdir(self.filepath):
                    if filename.endswith(".fmt"):
                        import_filename_list.append(filename)
        else:
            for fmt_file in self.files:
                import_filename_list.append(fmt_file.name)

        # 逐个fmt文件导入
        for fmt_file_name in import_filename_list:
            fmt_file_path = os.path.join(dirname, fmt_file_name)
            mbf = MigotoBinaryFile(fmt_path=fmt_file_path)
            MeshImportHelper.create_mesh_obj_from_mbf(mbf=mbf,import_collection=collection)

        # Select all objects under collection (因为用户习惯了导入后就是全部选中的状态). 
        CollectionUtils.select_collection_objects(collection)

        return {'FINISHED'}


# 面板UI布局
class Sword_ImportTexture_VIEW3D_PT_ImageMaterialPanel(Panel):
    bl_label = "3Dmigoto-Sword面板"
    bl_idname = "VIEW3D_PT_image_material_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Sword4'
    # bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        layout.prop(scene, "sword_reverse_source_mode")
        if scene.sword_reverse_source_mode == "SPECIFIC":
            reversed_workspace_row = layout.row(align=True)
            reversed_workspace_row.prop(scene, "sword_specific_reversed_workspace_name", text=iface_("指定工作空间"))
            reversed_workspace_row.operator(SWORD4RefreshReversedWorkspaceList.bl_idname, text="", icon='FILE_REFRESH')
        elif scene.sword_reverse_source_mode == "CUSTOM":
            layout.prop(scene, "sword_custom_reverse_output_folder_path", text=iface_("自定义目录"))

        # 一键导入逆向结果按钮
        layout.operator("ssmt.import_all_reverse",icon='IMPORT')
        
        # 导入 ib vb fmt格式文件
        layout.operator(Import3DMigotoRaw.bl_idname,icon='IMPORT')

        # 手动导入SSMT格式模型（与TheHerta4面板中的按钮相同）
        layout.operator(SSMT4ImportRaw.bl_idname,icon='IMPORT')

        # 自动检测按钮
        row = layout.row()

        # 文件夹选择按钮
        row = layout.row()
        row.operator("wm.select_image_folder", icon='FILE_FOLDER')
        
        # 显示图片数量信息
        if scene.sword_image_list:
            layout.label(text=iface_("已找到 {count} 张图片").format(count=len(scene.sword_image_list)))
        
        # 显示图片列表
        if scene.sword_image_list:
            row = layout.row()
            row.template_list(
                "SWORD_UL_FastImportTextureList",  # 修正为正确的类名
                iface_("图片列表"), 
                scene, 
                "sword_image_list", 
                scene, 
                "sword_image_list_index",
                rows=6
            )
        else:
            layout.label(text=iface_("未找到图片，请先选择文件夹。"))
        
        # 应用材质按钮
        row = layout.row()
        row.operator("wm.apply_image_to_material", icon='MATERIAL_DATA')
        
        # 显示当前选中图片的预览
        if scene.sword_image_list and scene.sword_image_list_index >= 0 and scene.sword_image_list_index < len(scene.sword_image_list):
            selected_item = scene.sword_image_list[scene.sword_image_list_index]
            pcoll = preview_collections["main"]
            
            if selected_item.name in pcoll:
                box = layout.box()
                box.label(text=iface_("预览:"))
                box.template_icon(icon_value=pcoll[selected_item.name].icon_id, scale=10.0)


class Sword_SplitModel_By_DrawIndexed_Panel(Panel):
    bl_label = "手动逆向后根据DrawIndexed值分割模型"
    bl_idname = "VIEW3D_PT_Sword_SplitModel_By_DrawIndexed_Panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Sword4'
    # bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        layout.prop(scene, "submesh_start")
        layout.prop(scene, "submesh_count")
        
        op = layout.operator("mesh.extract_submesh")
        op.start_index = scene.submesh_start
        op.index_count = scene.submesh_count

def register():
    # 注册预览图集合
    pcoll = bpy.utils.previews.new()
    preview_collections["main"] = pcoll

    bpy.utils.register_class(Import3DMigotoRaw)
    bpy.utils.register_class(Sword_ImportTexture_ImageListItem)
    bpy.utils.register_class(SWORD_UL_FastImportTextureList)
    bpy.utils.register_class(Sword_ImportTexture_VIEW3D_PT_ImageMaterialPanel)
    bpy.utils.register_class(Sword_ImportTexture_WM_OT_ApplyImageToMaterial)
    bpy.utils.register_class(Sword_ImportTexture_WM_OT_SelectImageFolder)
    bpy.utils.register_class(SwordImportAllReversed)
    bpy.utils.register_class(SWORD4RefreshReversedWorkspaceList)
    bpy.utils.register_class(Sword_SplitModel_By_DrawIndexed_Panel)

    bpy.types.Scene.sword_image_list = CollectionProperty(type=Sword_ImportTexture_ImageListItem)
    bpy.types.Scene.sword_image_list_index = IntProperty(default=0)
    bpy.types.Scene.sword_reverse_source_mode = EnumProperty(
        name="导入模式",
        description="控制一键导入逆向结果时的目录来源",
        items=[
            ("LAST", "上次逆向结果", "使用全局配置中记录的上次逆向输出目录"),
            ("SPECIFIC", "指定工作空间", "使用 MMT / MIMITools 缓存目录下 Reversed 中指定的子文件夹"),
            ("CUSTOM", "自定义目录", "使用你手动指定的目录"),
        ],
        default="LAST",
    )
    bpy.types.Scene.sword_specific_reversed_workspace_name = EnumProperty(
        name="指定工作空间",
        description="当前 MMT / MIMITools 缓存目录下 Reversed 的子文件夹列表",
        items=_get_sword_reversed_workspace_items,
    )
    bpy.types.Scene.sword_custom_reverse_output_folder_path = StringProperty(
        name="自定义目录",
        description="手动指定用于一键导入逆向结果的目录",
        default="",
        subtype='DIR_PATH',
    )

def unregister():
    try:
        del bpy.types.Scene.sword_image_list
        del bpy.types.Scene.sword_image_list_index
        del bpy.types.Scene.sword_reverse_source_mode
        del bpy.types.Scene.sword_specific_reversed_workspace_name
        del bpy.types.Scene.sword_custom_reverse_output_folder_path
    except Exception:
        pass

    # 移除预览图集合
    for pcoll in preview_collections.values():
        try:
            bpy.utils.previews.remove(pcoll)
        except Exception:
            pass
    preview_collections.clear()

    bpy.utils.unregister_class(Sword_SplitModel_By_DrawIndexed_Panel)
    bpy.utils.unregister_class(SwordImportAllReversed)
    bpy.utils.unregister_class(Sword_ImportTexture_WM_OT_SelectImageFolder)
    bpy.utils.unregister_class(Sword_ImportTexture_WM_OT_ApplyImageToMaterial)
    bpy.utils.unregister_class(Sword_ImportTexture_VIEW3D_PT_ImageMaterialPanel)
    bpy.utils.unregister_class(SWORD4RefreshReversedWorkspaceList)
    bpy.utils.unregister_class(SWORD_UL_FastImportTextureList)
    bpy.utils.unregister_class(Sword_ImportTexture_ImageListItem)
    bpy.utils.unregister_class(Import3DMigotoRaw)
                
