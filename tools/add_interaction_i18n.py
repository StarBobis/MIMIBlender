"""Add the interaction deformation translations to the language dictionaries.

The script inserts the new keys right before the closing brace of the
dictionary, so the existing entries keep their order and the diff stays
readable.  Keys that already exist are left alone.
"""

import io
import os
import sys


TRANSLATIONS_ZH_CN = {
    "Add Interaction Region": "添加交互区域",
    "Add at least one enabled region before exporting": "导出前请至少添加一个启用的区域",
    "Choose a mesh that is already part of the normal Mod output": "选择已包含在常规 Mod 输出中的网格",
    "Choose an existing mesh object": "请选择一个已存在的网格对象",
    "Control Vertex Group": "控制顶点组",
    "Control groups must not use a numbered bone group name": "控制组不能使用数字骨骼组名称",
    "Create Interaction Region": "创建交互区域",
    "Create Region from Selected Vertices": "从选中顶点创建区域",
    "Created the control group {name}": "已创建控制组 {name}",
    "Enable Interaction Deformation": "启用交互形变",
    "Enable Region": "启用区域",
    "Feather Rings": "羽化环数",
    "Independent settings; keep the existing output links": "独立设置；请保留已有的输出连线",
    "Interaction Deformation": "交互形变",
    "Interaction Regions (Up to 2)": "交互区域（最多 2 个）",
    "Pull": "拉伸",
    "Pull direction and strength; the length is a fraction of the model size": "拉伸方向与强度；长度是模型尺寸的比例",
    "Region Name": "区域名称",
    "Region Object": "区域对象",
    "Region {number}": "区域 {number}",
    "Remove Interaction Region": "移除交互区域",
    "Select at least one vertex first": "请先至少选择一个顶点",
    "Select mesh vertices in Edit Mode first": "请先在编辑模式下选中网格顶点",
    "Select one mesh and enter Edit Mode first": "请先选择一个网格并进入编辑模式",
    "The interaction node lost its region row": "交互节点已失去该区域行",
    "The pull length is a fraction of the model size": "拉伸长度是模型尺寸的比例",
    "The selection did not produce any weight": "所选顶点没有产生任何权重",
    "The vertex group weights decide how far each vertex is pulled": "顶点组权重决定每个顶点被拉伸多远",
    "This preset does not provide the interaction deformation": "当前预设不支持交互形变",
    "This version supports at most two interaction regions": "此版本最多支持两个交互区域",
}

TRANSLATIONS_ZH_TW = {
    "Add Interaction Region": "新增互動區域",
    "Add at least one enabled region before exporting": "匯出前請至少新增一個啟用的區域",
    "Choose a mesh that is already part of the normal Mod output": "選擇已包含在一般 Mod 輸出中的網格",
    "Choose an existing mesh object": "請選擇一個已存在的網格物件",
    "Control Vertex Group": "控制頂點群組",
    "Control groups must not use a numbered bone group name": "控制群組不能使用數字骨骼群組名稱",
    "Create Interaction Region": "建立互動區域",
    "Create Region from Selected Vertices": "從選取頂點建立區域",
    "Created the control group {name}": "已建立控制群組 {name}",
    "Enable Interaction Deformation": "啟用互動形變",
    "Enable Region": "啟用區域",
    "Feather Rings": "羽化環數",
    "Independent settings; keep the existing output links": "獨立設定；請保留既有的輸出連線",
    "Interaction Deformation": "互動形變",
    "Interaction Regions (Up to 2)": "互動區域（最多 2 個）",
    "Pull": "拉伸",
    "Pull direction and strength; the length is a fraction of the model size": "拉伸方向與強度；長度是模型尺寸的比例",
    "Region Name": "區域名稱",
    "Region Object": "區域物件",
    "Region {number}": "區域 {number}",
    "Remove Interaction Region": "移除互動區域",
    "Select at least one vertex first": "請先至少選取一個頂點",
    "Select mesh vertices in Edit Mode first": "請先在編輯模式下選取網格頂點",
    "Select one mesh and enter Edit Mode first": "請先選取一個網格並進入編輯模式",
    "The interaction node lost its region row": "互動節點已失去該區域列",
    "The pull length is a fraction of the model size": "拉伸長度是模型尺寸的比例",
    "The selection did not produce any weight": "所選頂點沒有產生任何權重",
    "The vertex group weights decide how far each vertex is pulled": "頂點群組權重決定每個頂點被拉伸多遠",
    "This preset does not provide the interaction deformation": "目前預設不支援互動形變",
    "This version supports at most two interaction regions": "此版本最多支援兩個互動區域",
}


def insert_entries(path, dictionary):
    """Insert the entries into the dictionary of one language file."""
    with io.open(path, "r", encoding="utf-8") as source_file:
        text = source_file.read()

    closing = text.rstrip().rfind("}")
    if closing < 0:
        raise RuntimeError("no dictionary found in " + path)

    lines = []
    added = 0
    for key in sorted(dictionary.keys()):
        if ('"' + key + '"') in text:
            continue
        value = dictionary[key].replace("\\", "\\\\").replace('"', '\\"')
        lines.append('    "' + key + '": "' + value + '",')
        added += 1

    if not lines:
        print(path + ": nothing to add")
        return 0

    head = text[:closing].rstrip()
    if not head.endswith(","):
        head = head + ","
    updated = head + "\n" + "\n".join(lines) + "\n}\n"

    with io.open(path, "w", encoding="utf-8", newline="") as target_file:
        target_file.write(updated)

    print(path + ": added " + str(added) + " entries")
    return added


def main():
    addon_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    total = 0
    total += insert_entries(os.path.join(addon_root, "i18n", "zh_cn.py"), TRANSLATIONS_ZH_CN)
    total += insert_entries(os.path.join(addon_root, "i18n", "zh_tw.py"), TRANSLATIONS_ZH_TW)
    if total == 0:
        print("no translation entry was added")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
