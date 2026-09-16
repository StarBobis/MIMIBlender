"""Headless test for the dynamic mod node titles and the title migration.

Run with Blender 5.2:
    "C:\\Program Files\\Blender Foundation\\Blender 5.2\\blender.exe" ^
        -b --factory-startup --python-exit-code 1 --python tools/test_dynamic_mod_titles.py

The test:
1. Enables the addon and creates one node of each dynamic mod type.
2. Checks the English titles, the node width and the untouched identifiers.
3. Checks that the load_post migration rewrites the titles written by older
   versions, in both languages, without touching a user-chosen title.
4. Switches to Simplified Chinese and checks every renamed UI string.

Exits with code 0 on success and 1 on the first failed check.
"""

import os
import sys

# Make the addon package importable: the repo root is the package itself, so
# its parent directory must be on sys.path (same as Blender's addon folder).
_REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PARENT_DIR = os.path.dirname(_REPO_DIR)
if _PARENT_DIR not in sys.path:
    sys.path.insert(0, _PARENT_DIR)

import bpy  # noqa: E402

_FAILURES = []

# Titles that the three nodes must show in the UI. The dictionary keys are the
# English source texts the addon uses as translation keys.
_TITLES = (
    ("MIMINode_TimeSwitch", "DrawIndex Based Dynamic Mod", "基于DrawIndexed切换的动态Mod"),
    ("MIMINode_TimePosSwitch", "Position.buf Based Dynamic Mod", "基于Position.buf切换的动态Mod"),
    ("MIMINode_TimeShapeKey", "ShapeKey Real-time Based Dynamic Mod", "基于ShapeKey实时计算的动态Mod"),
)

# Titles an older version wrote into freshly created nodes. They must still be
# recognised, because a node title is stored inside the blend file.
_LEGACY_TITLES = (
    ("MIMINode_TimeSwitch", "Time Switch", "时间切换"),
    ("MIMINode_TimePosSwitch", "Time Position Switch", "时间位置切换"),
    ("MIMINode_TimeShapeKey", "Time Shape Key", "时间形态键"),
)


def check(label, condition):
    """Record one check result and print it immediately."""
    status = "PASS" if condition else "FAIL"
    print("[TITLE {}] {}".format(status, label))
    if not condition:
        _FAILURES.append(label)


def main():
    import MIMIBlender
    from MIMIBlender.i18n import i18n
    from MIMIBlender.blueprint.blueprint_node_base import migrate_legacy_node_titles

    # 1. Enable the addon the same way the add-on preferences page does.
    bpy.ops.preferences.addon_enable(module="MIMIBlender")
    check("addon_enable completed", True)

    tree = bpy.data.node_groups.new(name="TitleTest", type="MIMIBlueprintTreeType")
    nodes = {node_type: tree.nodes.new(node_type) for node_type, _, _ in _TITLES}

    # 2. English titles and layout. Identifiers must stay untouched so existing
    # blueprints keep loading.
    for node_type, english_title, _ in _TITLES:
        node = nodes[node_type]
        check("title (en): " + node_type, node.label == english_title)
        check("type title (en): " + node_type, type(node).bl_label == english_title)
        check("bl_idname kept: " + node_type, node.bl_idname == node_type)
        # The new titles are longer than the old ones, so the node has to grow
        # instead of truncating the name in the header.
        check(
            "node width fits the title: " + node_type,
            node.width >= node.calculate_text_width(node.label),
        )

    # 3. Migration. A title the user typed by hand must never be replaced.
    nodes["MIMINode_TimeShapeKey"].label = "My own title"
    check("migration keeps a user title", migrate_legacy_node_titles() == 0)
    check("user title unchanged", nodes["MIMINode_TimeShapeKey"].label == "My own title")

    for node_type, legacy_title, _ in _LEGACY_TITLES:
        nodes[node_type].label = legacy_title
    check("migration rewrites every legacy title", migrate_legacy_node_titles() == len(_LEGACY_TITLES))
    for node_type, english_title, _ in _TITLES:
        check("migrated title (en): " + node_type, nodes[node_type].label == english_title)
    # A second run must find nothing left to do.
    check("migration is idempotent", migrate_legacy_node_titles() == 0)

    # 4. Simplified Chinese. The translated spelling was written by a node that
    # was created while Chinese was active, so it must migrate as well.
    preferences = i18n.get_preferences()
    check("preferences object available", preferences is not None)
    preferences.ui_language = "zh"
    for _, english_title, chinese_title in _TITLES:
        check("title (zh): " + english_title, i18n.tr(english_title) == chinese_title)

    for node_type, _, legacy_title in _LEGACY_TITLES:
        nodes[node_type].label = legacy_title
    check("migration rewrites the Chinese legacy titles", migrate_legacy_node_titles() == len(_LEGACY_TITLES))
    for node_type, _, chinese_title in _TITLES:
        check("migrated title (zh): " + node_type, nodes[node_type].label == chinese_title)

    # A node created now must use the language that is active now.
    fresh_node = tree.nodes.new("MIMINode_TimeSwitch")
    check("new node follows the active language", fresh_node.label == _TITLES[0][2])

    # Every renamed report and dialog text must be translated too, otherwise a
    # Chinese user would see English error messages.
    for english_text, chinese_text in (
        ("Please run this from a DrawIndex Based or Position.buf Based Dynamic Mod node",
         "请从基于DrawIndexed切换或基于Position.buf切换的动态Mod节点上运行此功能"),
        ("Target dynamic mod node not found", "未找到目标动态Mod节点"),
        ("Baked {count} frames and wired them into this node", "已烘焙 {count} 帧并连线到此节点"),
        ("Please run this from a ShapeKey Real-time Based Dynamic Mod node",
         "请从基于ShapeKey实时计算的动态Mod节点上运行此功能"),
        ("Target ShapeKey Real-time Based Dynamic Mod node not found",
         "未找到目标基于ShapeKey实时计算的动态Mod节点"),
        ("Baked {count} weight frames into the ShapeKey Real-time Based Dynamic Mod node",
         "已烘焙 {count} 个权重帧到基于ShapeKey实时计算的动态Mod节点"),
    ):
        check("translated report: " + english_text, i18n.tr(english_text) == chinese_text)

    # 5. Back to English, then a clean unload.
    preferences.ui_language = "en"
    check("language restored to English", i18n.tr("DrawIndex Based Dynamic Mod") == "DrawIndex Based Dynamic Mod")
    check("load_post handler registered", migrate_legacy_node_titles in bpy.app.handlers.load_post)

    bpy.ops.preferences.addon_disable(module="MIMIBlender")
    check("addon_disable completed", True)
    check("load_post handler removed", migrate_legacy_node_titles not in bpy.app.handlers.load_post)

    if _FAILURES:
        print("[TITLE] {} check(s) FAILED".format(len(_FAILURES)))
        sys.exit(1)
    print("[TITLE] all checks passed")
    sys.exit(0)


main()
