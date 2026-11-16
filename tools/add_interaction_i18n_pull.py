"""Update the interaction translations after the pull semantics changed.

The pull is now measured against the distance a region can be pulled
safely, so the texts that described it as a fraction of the model size
have to change.  The script rewrites the existing keys and adds the new
ones.
"""

import io
import os
import sys


UPDATED_ZH_CN = {
    "Pull direction and strength; the length is a fraction of the model size":
        "拉伸方向与强度；长度是模型尺寸的比例",
    "Pull direction and strength; the length is a fraction of the distance this region can be pulled safely":
        "拉伸方向与强度；长度是该区域可安全拉伸距离的比例",
    "The pull length is a fraction of the model size":
        "拉伸长度是模型尺寸的比例",
    "The pull strength is a fraction of the safe distance":
        "拉伸强度是安全拉伸距离的比例",
    "A narrow control group can only be pulled a little":
        "控制组越窄，能拉伸的距离越短",
}

UPDATED_ZH_TW = {
    "Pull direction and strength; the length is a fraction of the model size":
        "拉伸方向與強度；長度是模型尺寸的比例",
    "Pull direction and strength; the length is a fraction of the distance this region can be pulled safely":
        "拉伸方向與強度；長度是該區域可安全拉伸距離的比例",
    "The pull length is a fraction of the model size":
        "拉伸長度是模型尺寸的比例",
    "The pull strength is a fraction of the safe distance":
        "拉伸強度是安全拉伸距離的比例",
    "A narrow control group can only be pulled a little":
        "控制組越窄，能拉伸的距離越短",
}


def replace_entries(path, dictionary):
    """Replace the given keys in one language file."""
    with io.open(path, "r", encoding="utf-8") as source_file:
        lines = source_file.read().splitlines()

    replaced = 0
    added = 0
    output = []
    for line in lines:
        replaced_line = line
        for key, value in dictionary.items():
            if '"' + key + '":' not in replaced_line:
                continue
            indent = replaced_line[:len(replaced_line) - len(replaced_line.lstrip())]
            escaped_value = value.replace("\\", "\\\\").replace('"', '\\"')
            replaced_line = indent + '"' + key + '": "' + escaped_value + '",'
            replaced += 1
            break
        output.append(replaced_line)

    text = "\n".join(output) + "\n"

    # The new keys are added before the closing brace.
    closing = text.rstrip().rfind("}")
    missing = []
    for key, value in dictionary.items():
        if ('"' + key + '"') in text:
            continue
        missing.append('    "' + key + '": "' + value.replace("\\", "\\\\").replace('"', '\\"') + '",')
    if missing:
        head = text[:closing].rstrip()
        if not head.endswith(","):
            head = head + ","
        text = head + "\n" + "\n".join(missing) + "\n}\n"
        added = len(missing)

    with io.open(path, "w", encoding="utf-8", newline="") as target_file:
        target_file.write(text)

    print(path + ": replaced " + str(replaced) + ", added " + str(added))


def main():
    addon_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    replace_entries(os.path.join(addon_root, "i18n", "zh_cn.py"), UPDATED_ZH_CN)
    replace_entries(os.path.join(addon_root, "i18n", "zh_tw.py"), UPDATED_ZH_TW)
    return 0


if __name__ == "__main__":
    sys.exit(main())
