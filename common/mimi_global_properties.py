import bpy
import os

from ..i18n.i18n import tr


_blueprint_enum_items_cache = []


def _get_blueprint_enum_items(self, context):
    global _blueprint_enum_items_cache

    try:
        from ..blueprint.blueprint_export_helper import BlueprintExportHelper
        _blueprint_enum_items_cache = BlueprintExportHelper.get_blueprint_enum_items(context=context)
    except Exception:
        _blueprint_enum_items_cache = [
            ("__NONE__", tr("No blueprints available"), tr("No blueprint available. Please open the blueprint editor or run one-click import first.")),
        ]

    return _blueprint_enum_items_cache


def _get_workspace_enum_items(self, context):
    try:
        from .global_config import GlobalConfig

        GlobalConfig.read_from_main_json()
        workspace_root = GlobalConfig.path_current_game_total_workspace_folder()
        if not workspace_root or not os.path.isdir(workspace_root):
            return [("", tr("No workspace available"), tr("No workspace found for the current game configuration"))]

        workspace_names = sorted(
            [entry.name for entry in os.scandir(workspace_root) if entry.is_dir()]
        )
        if not workspace_names:
            return [("", tr("No workspace available"), tr("No workspace found for the current game configuration"))]

        return [(name, name, "") for name in workspace_names]
    except Exception:
        return [("", tr("No workspace available"), tr("No workspace found for the current game configuration"))]


def _get_workspace_source_mode_items(self, context):
    # Dynamic items callback so the dropdown entries follow the UI language.
    # Only the display name/description are translated; identifiers stay fixed.
    return [
        ("SYNC", tr("Sync with MMT Option"), tr("Use the workspace currently synced in the MMT configuration file")),
        ("SPECIFIC", tr("Use Specified Workspace"), tr("Manually select from the workspace list of the current game configuration")),
        ("CUSTOM", tr("Use Custom Folder"), tr("Directly use the workspace folder you specified")),
    ]


def _get_import_merged_vgmap_items(self, context):
    # Dynamic items callback so the dropdown entries follow the UI language.
    return [
        ('MERGED', tr('Merged'), tr('Imports the merged unified vertex groups; uses ComputeShader runtime mapping on export')),
        ('PER_COMPONENT', tr('PerComponent'), tr('Imports vertex groups independently per component')),
        ('UNICOMPONENT', tr('UniComponent'), tr('Merged import; on export, automatically splits by Submesh and restores local vertex groups')),
    ]


def _get_mirror_workflow_items(self, context):
    # The first entry is intentionally the default to preserve the historical
    # 3Dmigoto mirrored orientation for existing users and saved scenes.
    return [
        (
            "MIRRORED",
            tr("Mirrored Workflow"),
            tr("Keep the historical 3Dmigoto mirrored model orientation"),
        ),
        (
            "NON_MIRRORED",
            tr("Non-Mirrored Workflow"),
            tr("Bake a perfect left/right mirror on import and restore it on export"),
        ),
    ]


def _update_mirror_workflow_mode(self, context):
    # Mirror the new enum into the hidden legacy field so old callers and old
    # saved scenes continue to receive a consistent boolean value.
    try:
        self.use_mirror_workflow = self.mirror_workflow_mode == "NON_MIRRORED"
    except Exception:
        pass


class MIMIGlobalProperties(bpy.types.PropertyGroup):
    selected_blueprint_name: bpy.props.EnumProperty(
        name=tr("Current Blueprint"),
        description=tr("Select the blueprint to open or to quickly generate a Mod"),
        items=_get_blueprint_enum_items,
    ) # type: ignore

    open_mod_folder_after_generate_mod: bpy.props.BoolProperty(
        name=tr("Open Mod Folder After Generating Mod"),
        description=tr("When enabled, the Mod folder is opened automatically once Mod generation is complete"),
        default=True,
    ) # type: ignore

    zzz_use_slot_fix: bpy.props.BoolProperty(
        name=tr("Use SlotFix for Slot-Style Textures"),
        description=tr("Only applies to slot-style textures. When enabled, textures marked with specific names will use the SlotFix style, which can to some extent solve the problem of slot-style textures crossing slots. Crossing a Pixel slot means a texture is ps-t3 in the previous DrawCall but becomes ps-t5 in the next DrawCall. However, since the people responsible for maintaining it are also lazy, this is not reliable"),
        default=True,
    ) # type: ignore

    gimi_use_orfix: bpy.props.BoolProperty(
        name=tr("Use ORFix for Slot-Style Textures"),
        description=tr("When enabled, if you use slot-style texture markers but are too lazy to manually maintain fixes for texture corruption caused by texture slot changes, you can enable this option and let the ORFix maintainer solve the problem. GIMI only\nNote: if you do not understand how ORFix and NNFix work, do not uncheck this option, because unchecking it generates the texture part of the ini strictly according to the texture markers, and you are then expected to write conditional fix statements in the ini yourself to replace the functionality of ORFix and NNFix"),
        default=True,
    ) # type: ignore

    recalculate_tangent: bpy.props.BoolProperty(
        name=tr("Store Vector-Normalized Normals into TANGENT (Global)"),
        description=tr("Recomputes the TANGENT of all models using vector-sum normalization. When enabled, you cannot precisely control whether a specific model is processed; it is the lazy option. When unchecked, the option marked in the right-click menu is used by default.\nUses:\n1. Generally used to fix outline lines on GI, HI3 1.0 and HSR characters.\n2. Used to fix black patches on models caused by incorrect TANGENT values; thin HSR skirts may show this problem, for example."),
        default=False,
    ) # type: ignore

    recalculate_color: bpy.props.BoolProperty(
        name=tr("Store Arithmetic-Mean-Normalized Normals into COLOR (Global)"),
        description=tr("Recomputes the COLOR of all models using arithmetic-mean normalization. When enabled, you cannot precisely control whether a specific model is processed; it is the lazy option. When unchecked, the option marked in the right-click menu is used by default. Only used to fix outline lines on HI3 2.0 characters"),
        default=False,
    ) # type: ignore

    use_specific_generate_mod_folder_path: bpy.props.BoolProperty(
        name=tr("Generate Mod to Specified Folder"),
        description=tr("When enabled, the Mod is generated into the folder you specified"),
        default=False,
    ) # type: ignore

    generate_mod_folder_path: bpy.props.StringProperty(
        name=tr("Mod Generation Folder Path"),
        description=tr("The selected folder path for Mod generation"),
        default="",
        subtype='DIR_PATH',
    ) # type: ignore

    workspace_source_mode: bpy.props.EnumProperty(
        name=tr("Workspace Mode"),
        description=tr("Controls the source of the workspace currently in use"),
        items=_get_workspace_source_mode_items,
        # Dynamic items only allow integer (0-based) defaults; the first item
        # ("SYNC") is the intended default, so the argument is omitted.
    ) # type: ignore

    specific_workspace_name: bpy.props.EnumProperty(
        name=tr("Specified Workspace"),
        description=tr("List of selectable workspaces for the current game configuration"),
        items=_get_workspace_enum_items,
    ) # type: ignore

    custom_workspace_folder_path: bpy.props.StringProperty(
        name=tr("Custom Workspace Folder"),
        description=tr("Manually specify the workspace folder path"),
        default="",
        subtype='DIR_PATH',
    ) # type: ignore

    mirror_workflow_mode: bpy.props.EnumProperty(
        name=tr("Mirror Workflow"),
        description=tr("Choose whether imported 3Dmigoto models keep their historical mirrored orientation"),
        items=_get_mirror_workflow_items,
        update=_update_mirror_workflow_mode,
        # Dynamic enum callbacks use the first item as the default.  This keeps
        # new scenes compatible with the historical mirrored workflow.
    ) # type: ignore

    # Keep the old RNA field so opening a file saved by earlier releases does
    # not lose its stored value.  New code reads mirror_workflow_mode instead.
    use_mirror_workflow: bpy.props.BoolProperty(
        name=tr("Legacy Non-Mirrored Workflow"),
        description=tr("Compatibility field from the old mirror workflow"),
        default=False,
        options={'HIDDEN'},
    ) # type: ignore

    gimi_high_fidelity_rendering: bpy.props.BoolProperty(
        name=tr("Genshin High-Fidelity Rendering"),
        description=tr("Only available for GIMI / GenshinImpact workspaces. When enabled, imported characters get a preview material built from LightMap, Body Ramp, MatCap and edge-light node groups."),
        default=False,
    ) # type: ignore

    align_face_on_import: bpy.props.BoolProperty(
        name=tr("Align Face"),
        description=tr("On import, rotate and translate face objects according to the SubMeshRole Face/Neck marker; only object transforms are modified, vertices are not"),
        default=False,
    ) # type: ignore

    gimi_body_outline_enabled: bpy.props.BoolProperty(
        name=tr("GIMI Body Black Outline"),
        description=tr("Creates a black inverted-hull outline when a high-fidelity GIMI Body is imported"),
        default=True,
    ) # type: ignore

    gimi_body_outline_width_ratio: bpy.props.FloatProperty(
        name=tr("GIMI Outline Relative Width"),
        default=0.0008,
        min=0.00001,
        max=0.01,
        precision=6,
    ) # type: ignore

    import_merged_vgmap: bpy.props.EnumProperty(
        name=tr("Vertex Group Mode"),
        description=tr("Merged: import the merged unified vertex groups (used by Unreal's merged vertex group technique). Wuthering Waves Mods generally choose this to reduce the complexity of making Mods\nPerComponent: import independent vertex groups per component\nUniComponent: merged import; automatically split back into component-level vertex groups on export"),
        items=_get_import_merged_vgmap_items,
        # Dynamic items only allow integer (0-based) defaults; the first item
        # ("MERGED") is the intended default, so the argument is omitted.
    ) # type: ignore

    ignore_muted_shape_keys: bpy.props.BoolProperty(
        name=tr("Ignore Disabled Shape Keys"),
        description=tr("When enabled, shape keys that are not enabled are ignored during Mod generation; enabled shape keys are included in the Mod"),
        default=True,
    ) # type: ignore

    apply_all_modifiers: bpy.props.BoolProperty(
        name=tr("Apply All Modifiers"),
        description=tr("When enabled, all modifiers are automatically applied to objects before the Mod is generated"),
        default=False,
    ) # type: ignore

    import_skip_empty_vertex_groups: bpy.props.BoolProperty(
        name=tr("Skip Empty Vertex Groups"),
        description=tr("When enabled, empty vertex groups are skipped during import"),
        default=True,
    ) # type: ignore

    export_add_missing_vertex_groups: bpy.props.BoolProperty(
        name=tr("Add Missing Vertex Groups During Export"),
        description=tr("When enabled, Mod generation automatically reorders vertex groups and fills the gaps between numbered vertex groups"),
        default=True,
    ) # type: ignore

    simulate_xxmi_tail_comments: bpy.props.BoolProperty(
        name=tr("Simulate XXMI Tail Comments"),
        description=tr("When enabled, the generated INI ends with the same closing comments that XXMI Tools writes, so the file looks like one produced by that tool; the sha256 line stays the last line"),
        default=False,
    ) # type: ignore

    @classmethod
    def _instance(cls):
        return bpy.context.scene.mimi_global_properties

    @classmethod
    def open_mod_folder_after_generate_mod(cls):
        return cls._instance().open_mod_folder_after_generate_mod

    @classmethod
    def zzz_use_slot_fix(cls):
        return cls._instance().zzz_use_slot_fix

    @classmethod
    def gimi_use_orfix(cls):
        return cls._instance().gimi_use_orfix

    @classmethod
    def forbid_auto_texture_ini(cls) -> bool:
        """The old auto-texture pipeline has been removed. This method is kept only as a compatibility shim and always returns False."""
        return False

    @classmethod
    def recalculate_tangent(cls):
        return cls._instance().recalculate_tangent

    @classmethod
    def recalculate_color(cls):
        return cls._instance().recalculate_color

    @classmethod
    def use_specific_generate_mod_folder_path(cls):
        return cls._instance().use_specific_generate_mod_folder_path

    @classmethod
    def simulate_xxmi_tail_comments(cls) -> bool:
        """Whether generated INIs end with the simulated XXMI tail comments."""
        return bool(cls._instance().simulate_xxmi_tail_comments)

    @classmethod
    def generate_mod_folder_path(cls):
        return cls._instance().generate_mod_folder_path

    @classmethod
    def get_mirror_workflow_mode(cls):
        # Return a stable value even while a newly registered scene is still
        # receiving its dynamic enum defaults from Blender.
        instance = cls._instance()
        mode = str(getattr(instance, "mirror_workflow_mode", "MIRRORED"))
        if mode not in {"MIRRORED", "NON_MIRRORED"}:
            mode = "MIRRORED"
        # Files saved before the dropdown existed may only contain the old
        # boolean.  Treat that explicit legacy value as non-mirrored until the
        # user picks a new dropdown entry, whose update callback synchronizes
        # the compatibility field again.
        if mode == "MIRRORED" and bool(getattr(instance, "use_mirror_workflow", False)):
            return "NON_MIRRORED"
        return mode

    @classmethod
    def use_mirror_workflow(cls):
        # Keep the old method name for callers outside this module.  The new
        # dropdown is the single source of truth for the workflow choice.
        return cls.get_mirror_workflow_mode() == "NON_MIRRORED"

    @classmethod
    def workspace_source_mode(cls):
        return cls._instance().workspace_source_mode

    @classmethod
    def specific_workspace_name(cls):
        return cls._instance().specific_workspace_name

    @classmethod
    def custom_workspace_folder_path(cls):
        return cls._instance().custom_workspace_folder_path

    @classmethod
    def gimi_high_fidelity_rendering(cls):
        return cls._instance().gimi_high_fidelity_rendering

    @classmethod
    def align_face_on_import(cls):
        return cls._instance().align_face_on_import

    @classmethod
    def gimi_body_outline_enabled(cls):
        return cls._instance().gimi_body_outline_enabled

    @classmethod
    def gimi_body_outline_width_ratio(cls):
        return cls._instance().gimi_body_outline_width_ratio

    @classmethod
    def import_merged_vgmap(cls) -> str:
        """Returns 'MERGED' / 'PER_COMPONENT' / 'UNICOMPONENT'"""
        return cls._instance().import_merged_vgmap

    @classmethod
    def is_unico_component(cls) -> bool:
        return cls._instance().import_merged_vgmap == 'UNICOMPONENT'

    @classmethod
    def is_merged_mode(cls) -> bool:
        """Both MERGED and UNICOMPONENT use VGMap merging on import"""
        return cls._instance().import_merged_vgmap in ('MERGED', 'UNICOMPONENT')

    @classmethod
    def ignore_muted_shape_keys(cls):
        return cls._instance().ignore_muted_shape_keys

    @classmethod
    def apply_all_modifiers(cls):
        return cls._instance().apply_all_modifiers

    @classmethod
    def import_skip_empty_vertex_groups(cls):
        return cls._instance().import_skip_empty_vertex_groups

    @classmethod
    def export_add_missing_vertex_groups(cls):
        return cls._instance().export_add_missing_vertex_groups

    @classmethod
    def selected_blueprint_name(cls):
        return cls._instance().selected_blueprint_name


def register():
    try:
        bpy.utils.register_class(MIMIGlobalProperties)
    except ValueError:
        pass
    if not hasattr(bpy.types.Scene, "mimi_global_properties"):
        bpy.types.Scene.mimi_global_properties = bpy.props.PointerProperty(type=MIMIGlobalProperties)


def unregister():
    if hasattr(bpy.types.Scene, "mimi_global_properties"):
        del bpy.types.Scene.mimi_global_properties
    try:
        bpy.utils.unregister_class(MIMIGlobalProperties)
    except (ValueError, RuntimeError):
        pass
