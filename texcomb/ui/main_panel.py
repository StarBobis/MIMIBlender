"""UI panel for the main Material Combiner interface.

This module provides the primary UI panel for the Material Combiner addon,
displaying the material list, atlas property controls, and action buttons.
It also handles the Pillow installation interface when the library is not
available.
"""

import bpy

from .. import globs

_DISCORD_CONTACT_URL = "https://discordapp.com/users/275608234595713024"
_INSTALL_HELP_TEXT = (
    "点击“安装 Pillow”后，插件会使用 Blender 自带的 pip 把 Pillow "
    "安装到插件自身的 libs 目录，不需要管理员权限。"
)


class MaterialCombinerPanel(bpy.types.Panel):
    """Main panel for the Material Combiner addon.

    This class implements the primary UI panel for the Material Combiner addon,
    providing access to the material list, atlas properties settings, and
    action buttons. It also handles different states based on Pillow
    installation status.
    """

    bl_label = "贴图合并"
    bl_idname = "SMC_PT_Main_Panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI" if globs.is_blender_modern else "TOOLS"
    bl_category = "TheHerta4"
    bl_order = 10

    def draw(self, context: bpy.types.Context) -> None:
        """Draw the panel interface based on Pillow installation status.

        Renders different panel states depending on whether Pillow is installed,
        installation is in progress, or installation needs to be initiated.

        Args:
            context: The current Blender context.
        """
        layout = self.layout

        if globs.pil_available:
            self._render_main_interface(context, layout)
        elif globs.pil_install_attempted:
            if globs.pil_install_success:
                self.render_install_success(layout)
            else:
                self.render_install_failure(layout)
        else:
            self.draw_pillow_installer(context, layout)

    def _render_main_interface(
        self, context: bpy.types.Context, layout: bpy.types.UILayout
    ) -> None:
        """Render the main interface when Pillow is installed.

        Creates the complete UI with material list, properties section,
        and action controls for atlas generation.

        Args:
            context: The current Blender context.
            layout: The layout to draw into.
        """
        self._create_materials_list(context, layout)
        self._create_properties_section(context.scene, layout)
        self._create_action_controls(layout)

    @staticmethod
    def _create_materials_list(
        context: bpy.types.Context, layout: bpy.types.UILayout
    ) -> None:
        """Create the material list section with filtering options.

        Displays a list of available materials with related controls
        for selecting, filtering, and refreshing the list.

        Args:
            context: The current Blender context.
            layout: The layout to draw into.
        """
        scene = context.scene
        list_column = layout.column(align=True)

        list_column.label(text="待合并的材质:")

        list_box = list_column.box()
        list_box.template_list(
            "SMC_UL_Combine_List",
            "combine_list",
            scene,
            "smc_ob_data",
            scene,
            "smc_ob_data_id",
            rows=8,
        )

        refresh_row = list_column.row(align=True)
        refresh_row.scale_y = 1.2
        action_text = (
            "更新材质列表"
            if scene.smc_ob_data
            else "生成材质列表"
        )
        refresh_row.operator(
            "smc.refresh_ob_data",
            text=action_text,
        )

    def _create_properties_section(
        self, scene: bpy.types.Scene, layout: bpy.types.UILayout
    ) -> None:
        """Create atlas properties section with all configuration options.

        Args:
            scene: The current scene containing property values.
            layout: The layout to draw into.
        """
        self._add_option_toggles(layout, scene)
        self._add_packing_section(layout, scene)

    @staticmethod
    def _add_option_toggles(
        layout: bpy.types.UILayout, scene: bpy.types.Scene
    ) -> None:
        """Add all toggle/checkbox settings.

        Args:
            layout: The layout to draw into.
            scene: The current scene containing property values.
        """
        uniform_row = layout.row()
        uniform_row.prop(scene, "smc_uniform_size", text="统一贴图尺寸")
        if scene.smc_uniform_size:
            uniform_row.prop(scene, "smc_uniform_size_value", text="")
        layout.prop(scene, "smc_crop", text="根据UV边界裁剪")
        layout.prop(scene, "smc_pixel_art", text="禁用抗锯齿缩放")
        if globs.is_blender_modern:
            layout.prop(scene, "smc_include_extra_textures", text="图集PBR贴图")

    def _add_packing_section(
        self, layout: bpy.types.UILayout, scene: bpy.types.Scene
    ) -> None:
        """Add packing settings: size, gaps, and algorithm.

        Args:
            layout: The layout to draw into.
            scene: The current scene containing property values.
        """
        self._create_property_row(layout, scene, "smc_diffuse_size", "纯色纹理尺寸:")
        self._create_property_row(layout, scene, "smc_gaps", "纹理间距:")
        layout.prop(scene, "smc_size", text="图集尺寸")
        if scene.smc_size in {"CUST", "STRICTCUST"}:
            size_col = layout.column(align=True)
            size_col.scale_y = 1.2
            size_col.prop(scene, "smc_size_width", text="宽度")
            size_col.prop(scene, "smc_size_height", text="高度")
        layout.prop(scene, "smc_packer_type", text="打包算法")
        layout.prop(scene, "smc_image_format", text="输出格式")

    @staticmethod
    def _create_property_row(
        layout: bpy.types.UILayout,
        scene: bpy.types.Scene,
        prop: str,
        label: str,
    ) -> None:
        """Create a property row with label and value input.

        Creates a two-column layout with label on the left and
        value input on the right.

        Args:
            layout: The layout to draw into.
            scene: The current scene containing property values.
            prop: The property name to create controls for.
            label: The display label for the property.
        """
        row = layout.row()
        col = row.column()
        col.scale_y = 1.2
        col.label(text=label)
        col = row.column()
        col.scale_x = 0.75
        col.scale_y = 1.2
        col.alignment = "RIGHT"
        col.prop(scene, prop, text="")

    @staticmethod
    def _create_action_controls(layout: bpy.types.UILayout) -> None:
        """Create main action buttons for atlas generation.

        Adds buttons for initiating the atlas generation process.

        Args:
            layout: The layout to draw into.
        """
        col = layout.column()
        col.scale_y = 1.5
        col.operator(
            "smc.combiner",
            text="合并贴图",
            icon="EXPORT",
        ).cats = False



    @staticmethod
    def draw_pillow_installer(
        context: bpy.types.Context, layout: bpy.types.UILayout
    ) -> None:
        """Draw the Pillow installation interface when Pillow is not installed.

        Creates UI elements for installing Pillow and displaying
        help information.

        Args:
            context: The current Blender context.
            layout: The layout to draw into.
        """
        box = layout.box()
        MaterialCombinerPanel._render_install_header(box)
        MaterialCombinerPanel._render_install_actions(box)
        MaterialCombinerPanel._render_install_troubleshooting(box, context)

    @staticmethod
    def _render_install_header(layout: bpy.types.UILayout) -> None:
        """Render the installation header with a warning message.

        Args:
            layout: The layout to draw into.
        """
        col = layout.column(align=True)
        col.label(text="需要安装 Python Imaging Library (Pillow)", icon="ERROR")
        col.separator()

    @staticmethod
    def _render_install_actions(layout: bpy.types.UILayout) -> None:
        """Render the installation action buttons for Pillow installation.

        Args:
            layout: The layout to draw into.
        """
        row = layout.row()
        row.scale_y = 1.5
        row.operator("smc.get_pillow", text="安装 Pillow", icon="IMPORT")

    @staticmethod
    def _render_install_troubleshooting(
        layout: bpy.types.UILayout, context: bpy.types.Context
    ) -> None:
        """Render installation troubleshooting help with external links.

        Provides information and links for getting help with
        installation issues.

        Args:
            layout: The layout to draw into.
            context: The current Blender context.
        """
        layout.separator()
        layout.label(text=_INSTALL_HELP_TEXT)

        help_col = layout.column(align=True)
        help_col.scale_y = 1.2
 

    @staticmethod
    def render_install_success(layout: bpy.types.UILayout) -> None:
        """Render an installation success message prompting for restart.

        Displays a message indicating that the Pillow installation is complete
        and the Blender needs to be restarted.

        Args:
            layout: The layout to draw into.
        """
        box = layout.box().column()
        box.label(text="安装完成", icon="CHECKMARK")
        box.label(
            text="Pillow 已安装，请重启 Blender 后使用", icon="FILE_TICK"
        )

    @staticmethod
    def render_install_failure(layout: bpy.types.UILayout) -> None:
        """Render an installation failure message with error details.

        Displays a message indicating that the Pillow installation failed,
        shows any error details if available, and provides options to retry.

        Args:
            layout: The layout to draw into.
        """
        box = layout.box().column()
        box.label(text="安装失败", icon="ERROR")
        box.separator()

        # 显示错误信息
        if globs.pil_install_error_message:
            error_box = box.box()
            error_col = error_box.column()
            error_col.label(text="错误详情:", icon="INFO")
            # 把错误信息分段显示
            error_msg = globs.pil_install_error_message
            # 每80个字符左右换行
            import textwrap
            for line in textwrap.wrap(error_msg, width=60):
                error_col.label(text=line)
            box.separator()

        # 显示帮助信息
        help_col = box.column()
        help_col.label(text="可能的解决方案:", icon="HELP")
        help_col.label(text="1. 重试安装（默认使用清华镜像，失败后自动切换官方源）")
        help_col.label(text="2. 检查网络连接与防火墙设置")
        help_col.label(text="3. 如需手动安装，在命令行执行:")
        help_col.label(text="   python -m pip install --target \"{}\" Pillow -i https://pypi.tuna.tsinghua.edu.cn/simple".format(globs.PILLOW_LIB_PATH))
        box.separator()

        # 按钮行
        row = box.row(align=True)
        row.scale_y = 1.2
        row.operator("smc.get_pillow", text="重试安装", icon="FILE_REFRESH")
        row.operator("smc.check_pillow", text="检查安装", icon="FILE_TICK")
