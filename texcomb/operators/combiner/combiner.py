"""Main combiner operator for the Material Combiner addon.

This module provides the primary operator class for the Material Combiner addon.
It orchestrates the entire material combining process, from selecting materials
to generating the final atlas and updating UV coordinates. The Combiner operator
manages the main workflow and delegates specific tasks to specialized functions.

Usage example:
    bpy.ops.smc.combiner(directory=r'/path/to/save/directory')
"""

from typing import Set

import bpy
from bpy.props import BoolProperty, StringProperty

from ... import globs
from ...utils.packers import pack
from .combiner_ops import (
    align_uvs,
    assign_comb_mats,
    calculate_adjusted_size,
    clear_empty_mats,
    clear_mats,
    collect_texture_diagnostics,
    get_atlas,
    get_atlas_size,
    get_comb_mats,
    get_data,
    get_duplicates,
    get_mats_uv,
    get_size,
    get_structure,
    set_ob_mode,
    validate_ob_data,
)

MAX_ATLAS_SIZE = 20000


class Combiner(bpy.types.Operator):
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

    bl_idname = "smc.combiner"
    bl_label = "创建图集"
    bl_description = "将多个材质合并为纹理图集"
    bl_options = {"UNDO", "INTERNAL"}

    directory: StringProperty(
        description="图集保存目录",
        maxlen=1024,
        default="",
        subtype="FILE_PATH",
        options={"HIDDEN"},
    )
    filter_glob: StringProperty(default="", options={"HIDDEN"})
    cats: BoolProperty(
        description="启用特殊的 Cats 工作流模式", default=False
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
        if not self.data:
            self.invoke(context, None)
        scn = context.scene

        if not self.directory:
            return self._return_with_message("ERROR", "未选择保存目录")

        scn.smc_save_path = self.directory
        sized_structure = get_size(scn, self.structure)
        self._reported_texture_diagnostics = set()
        self._report_texture_diagnostics(sized_structure)
        self.structure = pack(sized_structure, scn.smc_packer_type)

        size = get_atlas_size(self.structure)
        atlas_size = calculate_adjusted_size(scn, size)

        if max(atlas_size, default=0) > MAX_ATLAS_SIZE:
            self.report(
                {"ERROR"},
                "输出图片尺寸 {}x{}px 过大".format(
                    *atlas_size
                ),
            )
            return {"FINISHED"}

        atlases = get_atlas(scn, self.structure, atlas_size)
        self._report_texture_diagnostics(self.structure)
        align_uvs(scn, self.structure, atlas_size, size)
        comb_mats = get_comb_mats(scn, atlases, self.mats_uv)
        assign_comb_mats(scn, self.data, comb_mats)
        clear_mats(scn, self.mats_uv)
        bpy.ops.smc.refresh_ob_data()
        self.report({"INFO"}, "材质合并完成")
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
        bpy.ops.smc.refresh_ob_data()

        validation_result = validate_ob_data(scn.smc_ob_data)
        if validation_result:
            return self._return_with_message(
                "ERROR", "未选择有效的物体"
            )

        if self.cats:
            scn.smc_size = "PO2"
            scn.smc_gaps = 0

        set_ob_mode(
            context.view_layer if globs.is_blender_modern else scn,
            scn.smc_ob_data,
        )
        self.data = get_data(scn.smc_ob_data)

        if not self.data:
            return self._return_with_message("ERROR", "未选择材质")

        self.mats_uv = get_mats_uv(scn, self.data)
        clear_empty_mats(scn, self.data, self.mats_uv)
        get_duplicates(self.mats_uv)
        self.structure = get_structure(scn, self.data, self.mats_uv)

        if globs.is_blender_legacy:
            context.space_data.viewport_shade = "MATERIAL"

        # Check if we're only dealing with duplicate materials
        total_unique_mats = len(self.structure)
        has_duplicates = any(
            len(item["dup"]) > 0 for item in self.structure.values()
        )

        # Validate material requirements
        if total_unique_mats == 0:
            return self._return_with_message("ERROR", "未选择材质")

        if total_unique_mats == 1 and not has_duplicates:
            return self._return_with_message(
                "ERROR",
                "只有一个唯一材质被选中，无需合并",
            )

        if event is not None:
            context.window_manager.fileselect_add(self)

        return {"RUNNING_MODAL"}

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
        bpy.ops.smc.refresh_ob_data()
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
            print("SSMT TextureCombiner:", message)
            self.report({"WARNING"}, message)
            reported.add(message)

        remaining = len(new_diagnostics) - 5
        if remaining > 0:
            print(
                "SSMT TextureCombiner: {} more material diagnostics hidden".format(
                    remaining
                )
            )
            self.report(
                {"WARNING"},
                "还有 {} 个材质会按纯色处理，请在材质设置中查看详情。".format(
                    remaining
                ),
            )
        self._reported_texture_diagnostics = reported
