"""UI panel for the main Material Combiner interface.

This module provides the primary UI panel for the Material Combiner addon,
displaying the material list, atlas property controls, and action buttons.
It also handles the Pillow installation interface when the library is not
available.
"""

import bpy

from ...i18n.i18n import tr, translatable
from .. import globs
from ..core import texconv
from ..operators.combiner.size_distribution import distribution_ready

_DISCORD_CONTACT_URL = "https://discordapp.com/users/275608234595713024"
# Kept as a plain English constant; it is translated at the draw site below.
_INSTALL_HELP_TEXT = (
    "After clicking \"Install Pillow\", the addon uses Blender's built-in pip to "
    "install Pillow into the addon's own libs directory; no administrator privileges are required."
)


def format_tile_count(value: float) -> str:
    """Format one sampling window axis without noisy trailing decimals.

    Whole repeats read as "2"; fractional ones keep up to two decimals so a
    1.02 overshoot is visibly small instead of looking like a whole tile.
    """
    text = "{:.2f}".format(value)
    return text.rstrip("0").rstrip(".")


def distribution_repeat_summary(scene: bpy.types.Scene):
    """Return (tiled_rows, largest_u, largest_v) from cached row values only.

    Drawing must stay cheap: this reads two floats per row and never touches
    materials, meshes or shader nodes. It only explains why the atlas is
    larger than one copy per source texture.
    """
    tiled = 0
    largest_u = 1.0
    largest_v = 1.0
    for entry in scene.mimi_smc_distribution:
        # A flat color has no tile detail and no repeated texture cost.
        if entry.preview_solid:
            continue
        if entry.uv_repeat_u > 1.0 or entry.uv_repeat_v > 1.0:
            tiled += 1
        largest_u = max(largest_u, entry.uv_repeat_u)
        largest_v = max(largest_v, entry.uv_repeat_v)
    return tiled, largest_u, largest_v


def draw_remove_unused_button(
    scn: bpy.types.Scene, layout: bpy.types.UILayout
) -> None:
    """Draw the one-click cleanup button while unused slots are listed.

    Unused slots are leftover materials that no face references, listed
    below the valid materials of each object. The button only appears while
    at least one such entry exists, keeping the UI clean otherwise.

    Args:
        scn: Current Blender scene.
        layout: UILayout to draw the button in.
    """
    unused_count = sum(
        1
        for item in scn.mimi_smc_ob_data
        if item.type == globs.CombineListTypes.MATERIAL and item.unused
    )
    if not unused_count:
        # Nothing to clean up: hide the button entirely.
        return
    row = layout.row(align=True)
    row.scale_y = 1.2
    row.operator(
        "mimi.remove_unused_materials",
        text=tr("Remove Unused Materials ({count})").format(count=unused_count),
        icon="TRASH",
    )


class MIMISMC_UL_SizeDistribution(bpy.types.UIList):
    """Draw only visible allocation rows in Blender's bounded scroll list.

    A plain layout loop created controls for every material on every redraw.
    UIList clips offscreen rows and keeps the sidebar height independent of
    material count. Drawing one row reads RNA only, never model geometry.
    Width and height remain editable directly without an extra popup.
    The fixed checkbox retains the original automatic-lock behavior.
    """

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        # Visible rows share a compact horizontal control layout.
        # Blender handles clipping, scrolling and active-row selection.
        # Explicit split factors align columns independently of text/icon widths.
        # Identity takes 40%, Fixed takes 16%, and dimensions take 22% each.
        columns = layout.split(factor=0.40, align=True)
        identity = columns.row(align=True)
        controls = columns.split(factor=0.16 / 0.60, align=True)
        fixed = controls.row(align=True)
        dimensions = controls.split(factor=0.5, align=True)
        width = dimensions.row(align=True)
        height = dimensions.row(align=True)
        # Every row reserves the same thumbnail and shared-count columns.
        # Empty count cells prevent single materials from shifting names/controls.
        identity_columns = identity.split(factor=0.15, align=True)
        thumbnail = identity_columns.row(align=True)
        names = identity_columns.split(factor=0.78, align=True)
        name_cell = names.row(align=True)
        count_cell = names.row(align=True)
        image = item.preview_image
        preview = image.preview if image else None
        icon_id = preview.icon_id if preview else 0
        if item.preview_solid:
            # Read cached color only; no source-material lookup during redraw.
            thumbnail.enabled = False
            thumbnail.prop(item, "preview_color", text="")
        elif icon_id:
            thumbnail.label(text="", icon_value=icon_id)
        else:
            thumbnail.label(text="", icon="MATERIAL")
        name_text = item.mat.name if item.mat else tr("Missing Material")
        # A flat color has no tile detail, so it never shows a repeat marker.
        if not item.preview_solid and (item.uv_repeat_u > 1.0 or item.uv_repeat_v > 1.0):
            # Tiled rows bake the source more than once; show the cost inline
            # so a larger atlas is explained before the merge runs.
            name_text += "  [{}x{}]".format(
                format_tile_count(item.uv_repeat_u),
                format_tile_count(item.uv_repeat_v),
            )
        name_cell.label(text=name_text)
        count_cell.label(text="×{}".format(len(item.members)) if len(item.members) > 1 else "")
        # Separate dimension cells always have equal width on every visible row.
        fixed.prop(item, "locked", text=tr("Fixed"))
        width.prop(item, "width", text=tr("Width"))
        height.prop(item, "height", text=tr("Height"))


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
    bl_region_type = "UI"
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
        self._create_action_controls(context.scene, layout)

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

        # Offer one-click cleanup whenever the scan found unused slots.
        draw_remove_unused_button(scene, list_column)

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
        uniform_row.prop(scene, "mimi_smc_uniform_size", text=tr("Maximum Individual Texture Size"))
        if scene.mimi_smc_uniform_size:
            uniform_row.prop(scene, "mimi_smc_uniform_size_value", text="")
        # The game's original dimensions affect only the canvas, not sources.
        layout.prop(scene, "mimi_smc_original_size", text=tr("Original Game Texture Size"))
        if scene.mimi_smc_original_size:
            original_row = layout.row(align=True)
            original_row.prop(scene, "mimi_smc_original_width", text=tr("Width"))
            original_row.prop(scene, "mimi_smc_original_height", text=tr("Height"))
        # Total budget lowers content resolution instead of exceeding output limits.
        layout.prop(scene, "mimi_smc_total_size", text=tr("Total Maximum Texture Size"))
        if scene.mimi_smc_total_size:
            total_row = layout.row(align=True)
            total_row.prop(scene, "mimi_smc_total_width", text=tr("Width"))
            total_row.prop(scene, "mimi_smc_total_height", text=tr("Height"))
        layout.prop(scene, "mimi_smc_crop", text=tr("Crop to UV Bounds"))
        layout.prop(scene, "mimi_smc_pixel_art", text=tr("Disable Anti-Aliasing Scaling"))
        layout.prop(scene, "mimi_smc_include_extra_textures", text=tr("Atlas PBR Textures"))

    def _add_packing_section(
        self, layout: bpy.types.UILayout, scene: bpy.types.Scene
    ) -> None:
        """Add packing settings: size, gaps, and algorithm.

        Args:
            layout: The layout to draw into.
            scene: The current scene containing property values.
        """
        # Maximum-size mode always budgets 32x32 for color-only materials.
        solid_layout = layout.column()
        solid_layout.enabled = not (scene.mimi_smc_uniform_size or scene.mimi_smc_total_size)
        self._create_property_row(solid_layout, scene, "mimi_smc_diffuse_size", tr("Solid Texture Size:"))
        self._create_property_row(layout, scene, "mimi_smc_gaps", tr("Texture Gap:"))
        # Tight packing chooses the smallest canvas automatically. Legacy
        # size/packer overrides apply only when maximum-size mode is disabled.
        legacy_layout = layout.column()
        legacy_layout.enabled = not (scene.mimi_smc_uniform_size or scene.mimi_smc_original_size or scene.mimi_smc_total_size)
        legacy_layout.prop(scene, "mimi_smc_size", text=tr("Atlas Size"))
        if scene.mimi_smc_size in {"CUST", "STRICTCUST"}:
            size_col = legacy_layout.column(align=True)
            size_col.scale_y = 1.2
            size_col.prop(scene, "mimi_smc_size_width", text=tr("Width"))
            size_col.prop(scene, "mimi_smc_size_height", text=tr("Height"))
        legacy_layout.prop(scene, "mimi_smc_packer_type", text=tr("Packing Algorithm"))
        layout.prop(scene, "mimi_smc_image_format", text=tr("Output Format"))
        if scene.mimi_smc_image_format == "DDS":
            self._add_dds_section(layout, scene)

    @staticmethod
    def _add_dds_section(
        layout: bpy.types.UILayout, scene: bpy.types.Scene
    ) -> None:
        """Add the DDS-specific options shown when the output format is DDS.

        DDS conversion is done by texconv.exe; the section always shows
        whether a usable exe was found so a failed combine never surprises.
        """
        dds_col = layout.column(align=True)
        dds_col.prop(scene, "mimi_smc_dds_format", text=tr("DDS Pixel Format"))
        dds_col.prop(scene, "mimi_smc_dds_mipmaps", text=tr("Generate Mipmaps"))
        dds_col.prop(scene, "mimi_smc_texconv_path", text=tr("texconv.exe Path"))
        if texconv.is_available(scene.mimi_smc_texconv_path):
            dds_col.label(text=tr("texconv.exe found"), icon="CHECKMARK")
        else:
            dds_col.label(
                text=tr("texconv.exe not found; DDS output unavailable"),
                icon="ERROR",
            )

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
    def _create_action_controls(scene: bpy.types.Scene, layout: bpy.types.UILayout) -> None:
        """Create main action buttons for atlas generation.

        Adds buttons for initiating the atlas generation process.

        Args:
            layout: The layout to draw into.
        """
        # Planning stays available even when no valid merge can run yet.
        row = layout.row(align=True)
        row.operator("mimi.generate_size_distribution", text=tr("Generate Size Distribution"))
        recalculate = row.row(align=True)
        recalculate.enabled = bool(scene.mimi_smc_distribution)
        recalculate.operator("mimi.generate_size_distribution", text=tr("Recalculate Size Distribution")).recalculate = True
        # Redraws must not synchronize edit meshes or hash millions of UVs.
        # Both combiner entry points still request the full source check.
        ready = distribution_ready(scene, check_sources=False)
        if scene.mimi_smc_distribution:
            box = layout.box()
            box.prop(scene, "mimi_smc_distribution_expanded", text=tr("Size Distribution"),
                     icon="TRIA_DOWN" if scene.mimi_smc_distribution_expanded else "TRIA_RIGHT", emboss=False)
            if scene.mimi_smc_distribution_expanded:
                box.label(text=tr("Edit dimensions to lock; uncheck Fixed to restore automatic sizing"))
                # A bounded UIList creates editable controls for visible rows only.
                # Large material collections no longer produce a huge panel tree.
                box.template_list("MIMISMC_UL_SizeDistribution", "size_distribution", scene,
                                  "mimi_smc_distribution", scene, "mimi_smc_distribution_index",
                                  rows=6, maxrows=8)
                # Tiled rows bake their source image more than once. Explain
                # that cost next to the list instead of hiding it in the atlas.
                tiled_rows, largest_u, largest_v = distribution_repeat_summary(scene)
                if tiled_rows:
                    box.label(
                        text=tr("Tiled textures: {count}, up to {u} x {v} tiles").format(
                            count=tiled_rows,
                            u=format_tile_count(largest_u),
                            v=format_tile_count(largest_v)),
                        icon="INFO",
                    )
                # The selected row gets a larger preview below the scroll list.
                # This keeps every row compact while making textures recognizable.
                index = scene.mimi_smc_distribution_index
                if 0 <= index < len(scene.mimi_smc_distribution):
                    entry = scene.mimi_smc_distribution[index]
                    image = entry.preview_image
                    preview = image.preview if image else None
                    if len(entry.members) > 1:
                        box.prop(entry, "members_expanded",
                                 text=tr("Shared Materials ({count})").format(count=len(entry.members)),
                                 icon="TRIA_DOWN" if entry.members_expanded else "TRIA_RIGHT", emboss=False)
                        if entry.members_expanded:
                            # Member names use cached pointers, not material graph scans.
                            # Only the selected group expands, keeping redraws bounded.
                            for member in entry.members:
                                box.label(text=member.mat.name if member.mat else tr("Missing Material"), icon="MATERIAL")
                    if entry.preview_solid:
                        # The selected solid row gets the same larger color preview.
                        # Keep it non-editable so users change the source material.
                        details = box.row(align=True)
                        swatch = details.column(align=True)
                        swatch.ui_units_x = 5
                        swatch.scale_y = 3
                        swatch.enabled = False
                        swatch.prop(entry, "preview_color", text="")
                        names = details.column(align=True)
                        names.label(text=entry.mat.name if entry.mat else tr("Missing Material"))
                        names.label(text=tr("Solid Color"), icon="MATERIAL")
                    elif preview and preview.icon_id:
                        details = box.row(align=True)
                        details.template_icon(icon_value=preview.icon_id, scale=5.0)
                        names = details.column(align=True)
                        names.label(text=entry.mat.name if entry.mat else tr("Missing Material"))
                        names.label(text=image.name, icon="IMAGE_DATA")
        if ready:
            layout.label(text=tr("Valid distribution: {width} x {height}").format(
                width=scene.mimi_smc_distribution_width, height=scene.mimi_smc_distribution_height), icon="CHECKMARK")
        else:
            # Any edit or source change blocks export until another successful run.
            layout.label(text=tr("Generate or recalculate a valid size distribution before combining"), icon="ERROR")
            if scene.mimi_smc_distribution_message:
                layout.label(text=scene.mimi_smc_distribution_message, icon="INFO")
        col = layout.column()
        col.enabled = ready
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
