"""Weight audit panel: detect skinning seams and stray weight clusters.

The heavy lifting lives in ``utils/weight_audit_utils.py`` and returns plain
Python dictionaries; this module only turns a report into short panel lines and
registers the buttons the user clicks. Keeping the split means the algorithms
can be tested in headless Blender without registering a single operator.

The panel is placed inside the MIMITools category next to the Model Processing
panel, because the feature belongs to the same workflow: fix the mesh, bind the
skeleton, then make sure the weights still follow the surface.
"""

import bpy
from bpy.props import BoolProperty, FloatProperty, IntProperty, StringProperty

from ..i18n.i18n import I18nOperator, tr, translatable
from ..utils.weight_audit_utils import WeightAuditSettings, WeightAuditUtils


def selected_mesh_objects(context):
    """Return the selected mesh objects, one per unique mesh data block.

    Two objects can share one mesh datablock (a linked duplicate). Weights live
    on the mesh, not on the object, so processing the same data twice would
    smooth it twice and clean it twice; the pointer set keeps every datablock
    in the list exactly once.
    """
    result = []
    seen = set()
    for obj in context.selected_objects:
        if obj.type != "MESH":
            continue
        pointer = obj.data.as_pointer()
        if pointer in seen:
            continue
        seen.add(pointer)
        result.append(obj)
    return result


def scene_settings(scene):
    """Copy the scene level thresholds into a plain settings object.

    The algorithm module never imports bpy, so every value is passed in from
    here. One place to read the scene keeps the three operators consistent.
    """
    return WeightAuditSettings(
        seam_threshold=scene.mimi_weight_seam_threshold,
        smooth_angle_degrees=scene.mimi_weight_smooth_angle,
        island_weight_threshold=scene.mimi_weight_cluster_threshold,
        island_min_vertices=scene.mimi_weight_cluster_min_size,
        max_influences=scene.mimi_weight_max_influences,
        min_weight=scene.mimi_weight_min_weight,
    )


def format_report(results):
    """Turn the per-object report dictionaries into panel report lines.

    The first line is a compact summary of the whole selection; every object
    with a finding then gets one or two lines. Clean objects are counted in the
    summary instead of taking a line each, because a multi-object selection can
    otherwise push the real findings out of the visible sidebar area. Short
    lines are deliberate: the sidebar label clips long text, and a clipped
    report hides exactly the number the user is looking for.
    """
    total_seams = 0
    total_clusters = 0
    total_issues = 0
    for result in results:
        total_seams += len(result["seam_edges"])
        total_clusters += len(result["clusters"])
        total_issues += len(result["issue_vertices"])
    lines = [
        tr(
            "Checked {objects} object(s): {seams} seam(s), {clusters} cluster(s), {issues} issue vertex/vertices"
        ).format(
            objects=len(results),
            seams=total_seams,
            clusters=total_clusters,
            issues=total_issues,
        )
    ]
    clean_count = 0
    for result in results:
        name = result["object"]
        # A mesh without vertex groups cannot hold a weight defect; saying so
        # is clearer than a zero line that looks like a clean result.
        if not result["has_groups"]:
            lines.append(tr("{name}: no vertex groups").format(name=name))
            continue
        if not result["has_issues"] and result["small_weight_count"] == 0:
            clean_count += 1
            continue
        lines.append(
            tr("{name}: {seams} seam(s), {clusters} cluster(s)").format(
                name=name,
                seams=len(result["seam_edges"]),
                clusters=len(result["clusters"]),
            )
        )
        lines.append(
            tr(
                "zero-weight {zero}, over-influence {over}, unnormalized {unnormalized}, small weights {small}"
            ).format(
                zero=len(result["zero_weight_vertices"]),
                over=len(result["over_influence_vertices"]),
                unnormalized=len(result["unnormalized_vertices"]),
                small=result["small_weight_count"],
            )
        )
    if clean_count:
        lines.append(tr("{count} object(s) clean").format(count=clean_count))
    return lines


def locked_group_warning(objects):
    """Whether any selected mesh has a locked vertex group.

    Blender's ``lock_weight`` flag only blocks manual edits in the UI; the
    Python API still writes the group. The repair operators warn instead of
    silently changing weights the user believed were protected.
    """
    for obj in objects:
        for group in obj.vertex_groups:
            if group.lock_weight:
                return True
    return False


class WeightOperatorBase(I18nOperator):
    """Shared poll: at least one selected mesh and Object Mode.

    Weight editing is a mesh level operation and Blender's vertex group API is
    unreliable while Edit Mode owns the mesh, so the buttons disable themselves
    instead of half-applying a change the user cannot undo in one step.
    """

    @classmethod
    def poll(cls, context):
        if context.mode != "OBJECT":
            return False
        return any(obj.type == "MESH" for obj in context.selected_objects)


class WeightDetectOperator(WeightOperatorBase):
    """Scan the selected meshes and write the report plus vertex marks."""

    bl_idname = "mimi.weight_detect"
    bl_label = "Detect Weight Issues"
    bl_description = (
        "Scan the selected meshes for weight seams and stray weight clusters"
    )
    bl_options = {"REGISTER", "UNDO"}

    # The property lives on the operator so the redo panel (F9) offers it right
    # after the click. Turning it off and re-running simply performs the scan
    # again without replacing the user's current vertex selection.
    mark_issues: BoolProperty(
        name="Mark Issues in Viewport",
        description=(
            "Select the vertices that failed a check so they can be inspected in Edit Mode; the previous vertex selection is cleared"
        ),
        default=True,
    )  # type: ignore

    def execute(self, context):
        objects = selected_mesh_objects(context)
        if not objects:
            self.report({"ERROR"}, tr("No mesh object selected."))
            return {"CANCELLED"}
        settings = scene_settings(context.scene)
        results = [WeightAuditUtils.analyse(obj, settings) for obj in objects]
        lines = format_report(results)
        # Every run redraws the marks, including clearing them when the mesh is
        # now clean; otherwise a stale selection from the previous run could be
        # mistaken for the current result. The hint line only appears when
        # there is something to look at.
        if self.mark_issues:
            for obj, result in zip(objects, results):
                WeightAuditUtils.mark_vertices(obj, result["issue_vertices"])
            if any(result["issue_vertices"] for result in results):
                lines.append(
                    tr("Detected vertices are selected; enter Edit Mode to see them")
                )
        # The full report goes into the scene so the panel can draw it after
        # the operator returns; the popup report only shows the summary.
        context.scene.mimi_weight_report = "\n".join(lines)
        total_seams = sum(len(result["seam_edges"]) for result in results)
        total_clusters = sum(len(result["clusters"]) for result in results)
        total_issues = sum(len(result["issue_vertices"]) for result in results)
        self.report(
            {"INFO"},
            tr(
                "Checked {objects} object(s): {seams} seam(s), {clusters} cluster(s), {issues} issue vertex/vertices"
            ).format(
                objects=len(results),
                seams=total_seams,
                clusters=total_clusters,
                issues=total_issues,
            ),
        )
        return {"FINISHED"}


class WeightSmoothOperator(WeightOperatorBase):
    """Repair every detected seam by blending the vertices around it."""

    bl_idname = "mimi.weight_smooth"
    bl_label = "Smooth Detected Seams"
    bl_description = (
        "Blend the vertices around each detected weight seam so the skin deforms smoothly"
    )
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        objects = selected_mesh_objects(context)
        if not objects:
            self.report({"ERROR"}, tr("No mesh object selected."))
            return {"CANCELLED"}
        settings = scene_settings(context.scene)
        # Both values are clamped here instead of trusting the UI: a scene
        # saved with an extreme number must not freeze the blend or write
        # negative weights.
        iterations = max(1, int(context.scene.mimi_weight_smooth_iterations))
        factor = max(0.05, min(1.0, float(context.scene.mimi_weight_smooth_factor)))
        updated = 0
        for obj in objects:
            result = WeightAuditUtils.analyse(obj, settings)
            if not result["seam_vertices"]:
                continue
            # One extra ring gives the blend a band to spread over; smoothing
            # only the two ends would move the seam one edge outward.
            targets = WeightAuditUtils.expand_vertices(
                obj.data, set(result["seam_vertices"]), 1
            )
            updated += WeightAuditUtils.smooth_vertices(
                obj, targets, iterations, factor
            )
        if updated == 0:
            self.report(
                {"INFO"},
                tr("Smoothing skipped: no weight seam detected (run Detect Weight Issues first)"),
            )
            return {"FINISHED"}
        self.report(
            {"INFO"},
            tr("Smoothing finished: {count} vertex/vertices updated").format(count=updated),
        )
        # The lock flag is a UI guard only, so tell the user when a value they
        # protected on purpose was rewritten by this button.
        if locked_group_warning(objects):
            self.report(
                {"WARNING"},
                tr("Warning: locked vertex groups are also edited; Blender's lock only blocks manual edits"),
            )
        return {"FINISHED"}


class WeightCleanOperator(WeightOperatorBase):
    """Remove tiny weights, cap the influence count and normalize."""

    bl_idname = "mimi.weight_clean"
    bl_label = "Clean Weights"
    bl_description = (
        "Remove tiny weights, cap the influence count and normalize the selected meshes"
    )
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        objects = selected_mesh_objects(context)
        if not objects:
            self.report({"ERROR"}, tr("No mesh object selected."))
            return {"CANCELLED"}
        settings = scene_settings(context.scene)
        changed = 0
        for obj in objects:
            # A mesh without vertex groups has nothing to clean; skipping it
            # keeps a mixed selection from stopping on the first empty object.
            if not obj.vertex_groups:
                continue
            changed += WeightAuditUtils.clean_weights(
                obj, settings.min_weight, settings.max_influences
            )
        if changed == 0:
            self.report({"INFO"}, tr("Cleaning skipped: nothing to clean"))
            return {"FINISHED"}
        self.report(
            {"INFO"},
            tr("Cleaning finished: {count} vertex/vertices updated").format(count=changed),
        )
        # The lock flag is a UI guard only, so tell the user when a value they
        # protected on purpose was rewritten by this button.
        if locked_group_warning(objects):
            self.report(
                {"WARNING"},
                tr("Warning: locked vertex groups are also edited; Blender's lock only blocks manual edits"),
            )
        return {"FINISHED"}


@translatable
class MIMIPanelWeight(bpy.types.Panel):
    """Sidebar panel for the weight audit and repair buttons."""

    bl_label = "Weight Processing Panel"
    bl_idname = "MIMI_PT_weight_process"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "MIMITools"
    # Collapsed by default like the other advanced panels, so beginners see a
    # short sidebar and still find the feature when they need it.
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        # -- Detection ---------------------------------------------------
        box = layout.box()
        box.label(text=tr("Weight Quality Check"))
        box.operator(
            WeightDetectOperator.bl_idname,
            text=tr(WeightDetectOperator.bl_label),
        )
        column = box.column(align=True)
        column.prop(scene, "mimi_weight_seam_threshold", text=tr("Seam Threshold"))
        column.prop(scene, "mimi_weight_smooth_angle", text=tr("Smooth Angle"))
        column.prop(
            scene, "mimi_weight_cluster_min_size", text=tr("Min Cluster Size")
        )
        column.prop(
            scene, "mimi_weight_cluster_threshold", text=tr("Cluster Weight")
        )

        # -- Repair ------------------------------------------------------
        box = layout.box()
        box.label(text=tr("Weight Optimization"))
        box.operator(
            WeightSmoothOperator.bl_idname,
            text=tr(WeightSmoothOperator.bl_label),
        )
        column = box.column(align=True)
        column.prop(
            scene, "mimi_weight_smooth_iterations", text=tr("Iterations")
        )
        column.prop(scene, "mimi_weight_smooth_factor", text=tr("Strength"))
        box.operator(
            WeightCleanOperator.bl_idname,
            text=tr(WeightCleanOperator.bl_label),
        )
        column = box.column(align=True)
        column.prop(scene, "mimi_weight_min_weight", text=tr("Min Weight"))
        column.prop(
            scene, "mimi_weight_max_influences", text=tr("Max Influences")
        )

        # -- Last report -------------------------------------------------
        report = scene.mimi_weight_report
        if report:
            box = layout.box()
            box.label(text=tr("Last Report"))
            column = box.column(align=True)
            lines = report.split("\n")
            # The sidebar clips anything past the visible height, so a long
            # multi-object report is capped and the hidden part is counted.
            # Clean objects are already summed into one line by format_report,
            # so only a selection with many real findings can reach the cap.
            shown = 20
            for line in lines[:shown]:
                column.label(text=line)
            if len(lines) > shown:
                column.label(
                    text=tr("... {count} more line(s)").format(count=len(lines) - shown)
                )


def register():
    """Register the three operators, the panel and the scene properties."""
    bpy.utils.register_class(WeightDetectOperator)
    bpy.utils.register_class(WeightSmoothOperator)
    bpy.utils.register_class(WeightCleanOperator)
    bpy.utils.register_class(MIMIPanelWeight)

    # Thresholds live on the scene so the panel can draw them and every
    # operator reads the same value. Like every registered custom property the
    # values are stored inside the .blend, so a shared Mod file remembers the
    # tuning of the machine that saved it; that is harmless for these knobs and
    # avoids a second settings surface in the add-on preferences.
    bpy.types.Scene.mimi_weight_seam_threshold = FloatProperty(
        name="Seam Threshold",
        description=(
            "Minimum weight difference between two neighbours that counts as a seam"
        ),
        default=1.0,
        min=0.1,
        max=2.0,
    )
    bpy.types.Scene.mimi_weight_smooth_angle = FloatProperty(
        name="Smooth Angle",
        description=(
            "Faces meeting at a sharper angle are treated as a hard edge and skipped by the seam check"
        ),
        default=60.0,
        min=1.0,
        max=89.0,
    )
    bpy.types.Scene.mimi_weight_cluster_min_size = IntProperty(
        name="Min Cluster Size",
        description=(
            "Isolated weight clusters smaller than this vertex count are reported"
        ),
        default=8,
        min=1,
        max=10000,
    )
    bpy.types.Scene.mimi_weight_cluster_threshold = FloatProperty(
        name="Cluster Weight",
        description=(
            "Weight above which a group counts as present when looking for isolated clusters"
        ),
        default=0.05,
        min=0.0,
        max=1.0,
    )
    bpy.types.Scene.mimi_weight_smooth_iterations = IntProperty(
        name="Iterations",
        description="How many smoothing passes to run",
        default=3,
        min=1,
        max=20,
    )
    bpy.types.Scene.mimi_weight_smooth_factor = FloatProperty(
        name="Strength",
        description="How much of the neighbour average is mixed into each pass",
        default=0.5,
        min=0.05,
        max=1.0,
    )
    bpy.types.Scene.mimi_weight_min_weight = FloatProperty(
        name="Min Weight",
        description="Weights below this value are removed by Clean Weights",
        default=0.01,
        min=0.0,
        max=0.5,
    )
    bpy.types.Scene.mimi_weight_max_influences = IntProperty(
        name="Max Influences",
        description=(
            "Maximum number of bones per vertex; the game exporter keeps four"
        ),
        default=4,
        min=1,
        max=8,
    )
    bpy.types.Scene.mimi_weight_report = StringProperty(
        name="Weight Report",
        description="Report written by the Detect Weight Issues button",
        default="",
    )


def unregister():
    """Unregister the panel, then the operators, then drop the properties."""
    bpy.utils.unregister_class(MIMIPanelWeight)
    bpy.utils.unregister_class(WeightCleanOperator)
    bpy.utils.unregister_class(WeightSmoothOperator)
    bpy.utils.unregister_class(WeightDetectOperator)

    del bpy.types.Scene.mimi_weight_report
    del bpy.types.Scene.mimi_weight_max_influences
    del bpy.types.Scene.mimi_weight_min_weight
    del bpy.types.Scene.mimi_weight_smooth_factor
    del bpy.types.Scene.mimi_weight_smooth_iterations
    del bpy.types.Scene.mimi_weight_cluster_threshold
    del bpy.types.Scene.mimi_weight_cluster_min_size
    del bpy.types.Scene.mimi_weight_smooth_angle
    del bpy.types.Scene.mimi_weight_seam_threshold
