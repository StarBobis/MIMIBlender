"""Main combiner operator for the Material Combiner addon.

This module provides the primary operator class for the Material Combiner addon.
It orchestrates the entire material combining process, from selecting materials
to generating the final atlas and updating UV coordinates. The Combiner operator
manages the main workflow and delegates specific tasks to specialized functions.

Usage example:
    bpy.ops.mimi.combiner(directory=r'/path/to/save/directory')
"""

import os
from typing import Set

import bpy
from bpy.props import BoolProperty, StringProperty

from ....i18n.i18n import I18nOperator, tr
from ...core import texconv
from ...output_settings import default_output_directory, remember_output_directory
from .combiner_ops import (
    align_uvs,
    assign_comb_mats,
    clear_mats,
    collect_texture_diagnostics,
    get_atlas,
    get_comb_mats,
    set_ob_mode,
    validate_ob_data,
)

from .size_distribution import apply_distribution, distribution_ready, prepare_sources

MAX_ATLAS_SIZE = 20000


class Combiner(I18nOperator):
    """Main operator for combining materials into a texture atlas.

    This operator manages the complete workflow for texture atlas generation:
    1. Validating user selections.
    2. Analyzing materials and textures.
    3. Detecting and handling duplicates.
    4. Generating the texture atlas.
    5. Adjusting UV coordinates.
    6. Assigning new materials.
    7. Cleaning up unneeded materials.
    """

    bl_idname = "mimi.combiner"
    bl_label = "Create Atlas"
    bl_description = "Combine multiple materials into a texture atlas"
    bl_options = {"UNDO", "INTERNAL"}

    directory: StringProperty(
        description=tr("Directory for saving the atlas"),
        maxlen=1024,
        default="",
        subtype="DIR_PATH",
        # Remembered operator arguments must not override a newly chosen default.
        options={"HIDDEN", "SKIP_SAVE"},
    )
    filter_glob: StringProperty(default="", options={"HIDDEN"})
    cats: BoolProperty(
        description=tr("Enable the special Cats workflow mode"), default=False
    )
    data = None
    mats_uv = None
    structure = None

    def execute(self, context: bpy.types.Context) -> Set[str]:
        """Execute the material combining operation.

        This method handles the final stages of the combining process:
        1. Packing textures using bin packing algorithm.
        2. Calculating appropriate atlas dimensions.
        3. Generating atlas images for all texture types.
        4. Remapping UV coordinates.
        5. Creating and assigning new materials.
        6. Cleaning up unused materials.

        Args:
            context: Current Blender context.

        Returns:
            Set containing operation status.
        """
        scn = context.scene
        # Validate the folder before planning or touching live UV coordinates.
        # Explicit programmatic paths do not overwrite persistent user defaults.
        self.directory = self.directory or default_output_directory(context)
        if not self.directory:
            self.report({"ERROR"}, tr("No save directory selected"))
            return {"CANCELLED"}
        self.directory = os.path.normpath(bpy.path.abspath(self.directory))
        if not os.path.isdir(self.directory):
            self.report({"ERROR"}, tr("Please select an existing output folder"))
            return {"CANCELLED"}
        # Recheck after browsing: sources and settings may have changed meanwhile.
        if not self._ensure_distribution(context):
            return {"CANCELLED"}

        # DDS output is produced by texconv.exe; refuse early with a clear
        # message instead of crashing halfway through the pipeline.
        if scn.mimi_smc_image_format == "DDS" and not texconv.is_available(
            scn.mimi_smc_texconv_path
        ):
            return self._return_with_message(
                "ERROR",
                tr(
                    "DDS output requires texconv.exe, but it could not be found. Set the texconv.exe path in the Output Format settings or the TEXCONV_PATH environment variable."
                ),
            )

        scn.mimi_smc_save_path = self.directory
        # Fresh live vectors avoid stale references after the file picker.
        # Approval is already checked before any UV alignment occurs.
        set_ob_mode(context.view_layer, scn.mimi_smc_ob_data)
        self.data, self.mats_uv, self.structure = prepare_sources(scn, read_only=False)
        atlas_size = apply_distribution(scn, self.structure)
        size = atlas_size
        sized_structure = self.structure
        self._reported_texture_diagnostics = set()
        self._report_texture_diagnostics(sized_structure)
        # All packing was approved in the distribution step. Repacking here
        # could shrink a locked texture or change its promised pixel dimensions.

        if max(atlas_size, default=0) > MAX_ATLAS_SIZE:
            self.report(
                {"ERROR"},
                tr("Output image size {width}x{height}px is too large").format(
                    width=atlas_size[0], height=atlas_size[1]
                ),
            )
            return {"FINISHED"}

        atlases = get_atlas(scn, self.structure, atlas_size)
        self._report_texture_diagnostics(self.structure)
        align_uvs(scn, self.structure, atlas_size, size)
        # Keep approved orientation: rotation would swap manual width/height.
        # In particular, rectangular locks retain the exact requested axes.
        comb_mats = get_comb_mats(scn, atlases, self.mats_uv)
        assign_comb_mats(scn, self.data, comb_mats)
        clear_mats(scn, self.mats_uv)
        bpy.ops.mimi.refresh_ob_data()
        # A first interactive merge also remembers the selected destination.
        # Failure to save preferences must not misreport a completed merge.
        if getattr(self, "_remember_directory", False):
            try:
                remember_output_directory(context, self.directory)
            except (ValueError, RuntimeError, OSError) as error:
                self.report({"WARNING"}, str(error))
        self.report({"INFO"}, tr("Materials combined successfully"))
        return {"FINISHED"}

    def invoke(
        self, context: bpy.types.Context, event: bpy.types.Event
    ) -> Set[str]:
        """Initialize the combiner and validate inputs.

        This method performs the initial setup and validation:
        1. Refreshing object data.
        2. Validating selected objects and materials.
        3. Setting up special options for specific workflows.
        4. Preparing material and UV data.
        5. Detecting and handling duplicate materials.

        Args:
            context: Current Blender context.
            event: Triggered event.

        Returns:
            Set containing operation status.
        """
        scn = context.scene
        bpy.ops.mimi.refresh_ob_data()
        # Automatic planning is read-only; impossible locks still stop the merge.
        if not self._ensure_distribution(context):
            return {"CANCELLED"}

        validation_result = validate_ob_data(scn.mimi_smc_ob_data)
        if validation_result:
            return self._return_with_message(
                "ERROR", tr("No valid object selected")
            )

        # Opening the file picker remains read-only. Mode changes and live
        # UV alignment are deferred until the execution-time approval check.
        self.data, self.mats_uv, self.structure = prepare_sources(scn)

        # Check if we're only dealing with duplicate materials
        total_unique_mats = len(self.structure)
        has_duplicates = any(
            len(item["dup"]) > 0 for item in self.structure.values()
        )

        # Validate material requirements
        if total_unique_mats == 0:
            return self._return_with_message("ERROR", tr("No material selected"))

        if total_unique_mats == 1 and not has_duplicates:
            return self._return_with_message(
                "ERROR",
                tr("Only one unique material was selected; no merging needed"),
            )

        # Skip the browser whenever the caller or preferences supply a folder.
        self.directory = self.directory or default_output_directory(context)
        if self.directory:
            return self.execute(context)
        if event is None:
            self.report({"ERROR"}, tr("No save directory selected"))
            return {"CANCELLED"}
        self._remember_directory = True
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def _ensure_distribution(self, context):
        """Generate missing defaults or recalculate existing manual locks."""
        scene = context.scene
        if distribution_ready(scene):
            return True
        try:
            # Recalculation preserves the artist's locked dimensions. Never
            # fall back to fresh defaults when those constraints cannot fit.
            result = bpy.ops.mimi.generate_size_distribution(
                recalculate=bool(scene.mimi_smc_distribution))
        except RuntimeError as error:
            self.report({"ERROR"}, str(error))
            return False
        return result == {"FINISHED"} and distribution_ready(scene)

    def draw(self, context: bpy.types.Context) -> None:
        """Draw the operator UI.

        This method is called to draw the operator UI.

        Args:
            context: Current Blender context.
        """
        pass

    def _return_with_message(self, message_type: str, message: str) -> Set[str]:
        """Return with a message to the user.

        Helper method to display a message to the user and refresh the object data.

        Args:
            message_type: Type of message (INFO, ERROR, WARNING).
            message: Message content to display.

        Returns:
            Set containing operation status.
        """
        bpy.ops.mimi.refresh_ob_data()
        self.report({message_type}, message)
        return {"FINISHED"}

    def _report_texture_diagnostics(self, structure) -> None:
        """Report materials that will fall back to color-only output."""
        diagnostics = collect_texture_diagnostics(structure)
        reported = getattr(self, "_reported_texture_diagnostics", set())
        new_diagnostics = [
            message for message in diagnostics if message not in reported
        ]
        if not new_diagnostics:
            return

        for message in new_diagnostics[:5]:
            print("MMT TextureCombiner:", message)
            self.report({"WARNING"}, message)
            reported.add(message)

        remaining = len(new_diagnostics) - 5
        if remaining > 0:
            print(
                "MMT TextureCombiner: {} more material diagnostics hidden".format(
                    remaining
                )
            )
            self.report(
                {"WARNING"},
                tr("{count} more materials will be treated as solid color; see the material settings for details.").format(
                    count=remaining
                ),
            )
        self._reported_texture_diagnostics = reported
