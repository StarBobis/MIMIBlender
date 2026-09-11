"""UI panel for the main Material Combiner interface.

This module provides the primary UI panel for the Material Combiner addon,
displaying the material list, atlas property controls, and action buttons.
It also handles the Pillow installation interface when the library is not
available.
"""

import bpy

from ...i18n.i18n import tr, translatable
from .. import globs

_DISCORD_CONTACT_URL = "https://discordapp.com/users/275608234595713024"
# Kept as a plain English constant; it is translated at the draw site below.
_INSTALL_HELP_TEXT = (
    "After clicking \"Install Pillow\", the addon uses Blender's built-in pip to "
    "install Pillow into the addon's own libs directory; no administrator privileges are required."
)


@translatable
class MIMIMaterialCombinerPanel(bpy.types.Panel):
    """Main panel for the Material Combiner addon.

    This class implements the primary UI panel for the Material Combiner addon,
    providing access to the material list, atlas properties settings, and
    action buttons. It also handles different states based on Pillow
    installation status.
    """

    bl_label = "Texture Combiner"
    bl_idname = "MIMI_PT_texcomb_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI" if globs.is_blender_modern else "TOOLS"
    bl_category = "MIMITools"
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

        list_column.label(text=tr("Materials to Combine:"))

        list_box = list_column.box()
        list_box.template_list(
            "MIMISMC_UL_Combine_List",
            "combine_list",
            scene,
            "mimi_smc_ob_data",
            scene,
            "mimi_smc_ob_data_id",
            rows=8,
        )

        refresh_row = list_column.row(align=True)
        refresh_row.scale_y = 1.2
        action_text = (
            tr("Refresh Material List")
            if scene.mimi_smc_ob_data
            else tr("Generate Material List")
        )
        refresh_row.operator(
            "mimi.refresh_ob_data",
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
        uniform_row.prop(scene, "mimi_smc_uniform_size", text=tr("Uniform Texture Size"))
        if scene.mimi_smc_uniform_size:
            uniform_row.prop(scene, "mimi_smc_uniform_size_value", text="")
        layout.prop(scene, "mimi_smc_crop", text=tr("Crop to UV Bounds"))
        layout.prop(scene, "mimi_smc_pixel_art", text=tr("Disable Anti-Aliasing Scaling"))
        if globs.is_blender_modern:
            layout.prop(scene, "mimi_smc_include_extra_textures", text=tr("Atlas PBR Textures"))

    def _add_packing_section(
        self, layout: bpy.types.UILayout, scene: bpy.types.Scene
    ) -> None:
        """Add packing settings: size, gaps, and algorithm.

        Args:
            layout: The layout to draw into.
            scene: The current scene containing property values.
        """
        self._create_property_row(layout, scene, "mimi_smc_diffuse_size", tr("Solid Texture Size:"))
        self._create_property_row(layout, scene, "mimi_smc_gaps", tr("Texture Gap:"))
        layout.prop(scene, "mimi_smc_size", text=tr("Atlas Size"))
        if scene.mimi_smc_size in {"CUST", "STRICTCUST"}:
            size_col = layout.column(align=True)
            size_col.scale_y = 1.2
            size_col.prop(scene, "mimi_smc_size_width", text=tr("Width"))
            size_col.prop(scene, "mimi_smc_size_height", text=tr("Height"))
        layout.prop(scene, "mimi_smc_packer_type", text=tr("Packing Algorithm"))
        layout.prop(scene, "mimi_smc_image_format", text=tr("Output Format"))

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
            "mimi.combiner",
            text=tr("Combine Textures"),
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
        MIMIMaterialCombinerPanel._render_install_header(box)
        MIMIMaterialCombinerPanel._render_install_actions(box)
        MIMIMaterialCombinerPanel._render_install_troubleshooting(box, context)

    @staticmethod
    def _render_install_header(layout: bpy.types.UILayout) -> None:
        """Render the installation header with a warning message.

        Args:
            layout: The layout to draw into.
        """
        col = layout.column(align=True)
        col.label(text=tr("Python Imaging Library (Pillow) is required"), icon="ERROR")
        col.separator()

    @staticmethod
    def _render_install_actions(layout: bpy.types.UILayout) -> None:
        """Render the installation action buttons for Pillow installation.

        Args:
            layout: The layout to draw into.
        """
        row = layout.row()
        row.scale_y = 1.5
        row.operator("mimi.get_pillow", text=tr("Install Pillow"), icon="IMPORT")

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
        layout.label(text=tr(_INSTALL_HELP_TEXT))

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
        box.label(text=tr("Installation Complete"), icon="CHECKMARK")
        box.label(
            text=tr("Pillow has been installed, restart Blender to use it"), icon="FILE_TICK"
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
        box.label(text=tr("Installation failed"), icon="ERROR")
        box.separator()

        # Display the error message
        if globs.pil_install_error_message:
            error_box = box.box()
            error_col = error_box.column()
            error_col.label(text=tr("Error details:"), icon="INFO")
            # Display the error message in wrapped lines
            error_msg = globs.pil_install_error_message
            # Wrap after roughly 60 characters per line
            import textwrap
            for line in textwrap.wrap(error_msg, width=60):
                error_col.label(text=line)
            box.separator()

        # Display help information
        help_col = box.column()
        help_col.label(text=tr("Possible solutions:"), icon="HELP")
        help_col.label(text=tr("1. Retry the installation (Tsinghua mirror by default, falls back to the official source on failure)"))
        help_col.label(text=tr("2. Check the network connection and firewall settings"))
        help_col.label(text=tr("3. To install manually, run the following in a command line:"))
        help_col.label(text="   python -m pip install --target \"{}\" Pillow -i https://pypi.tuna.tsinghua.edu.cn/simple".format(globs.PILLOW_LIB_PATH))
        box.separator()

        # Button row
        row = box.row(align=True)
        row.scale_y = 1.2
        row.operator("mimi.get_pillow", text=tr("Retry Installation"), icon="FILE_REFRESH")
        row.operator("mimi.check_pillow", text=tr("Check Installation"), icon="FILE_TICK")
