"""Check the Traditional Chinese dictionary against the Simplified one.

Run with plain Python (no Blender required):
    python tools/test_zh_tw_translations.py

The addon uses the English source text as the translation key, so both Chinese
dictionaries have to describe exactly the same keys. This test enforces that
parity plus the mechanical properties that a bad translation usually breaks:

- the key sets are identical, so switching language never falls back to
  English because of a missing row;
- no value is empty, and the surrounding spaces match the Simplified value
  (the code appends some of them in front of a value);
- every {placeholder} and every line break survives, so a formatted message
  cannot raise or lose its variable;
- the value is not left in English when the Simplified row was translated;
- no Simplified-only character is left over.

It also prints a warning for mainland software terms whose characters are
shared with Traditional Chinese, which the character scan cannot catch. Those
are warnings, not failures, because a reader can still understand them; the
translator is expected to fix them by hand.

Exits with code 0 when every check passes and 1 otherwise.
"""

import importlib.util
import os
import re
import sys

# The repository root is the parent directory of this tools script.
_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The two dictionaries that must describe the same keys.
_SIMPLIFIED = ("zh_cn", "TRANSLATIONS_ZH_CN")
_TRADITIONAL = ("zh_tw", "TRANSLATIONS_ZH_TW")

# Characters that exist only in Simplified Chinese. The list deliberately
# leaves out characters that are also valid in Traditional text (里, 后, 台,
# 干, 只, 面, 系, 松, 谷, 采, 准, 征, 划, 斗, 叶, 温, 脉, 强, 晋, 于, 范, 几,
# 别, 却, 决, 况, 净, 凉, 删, 匀, 吴, 叙, 咸), because flagging one of those
# would be a false positive that stops a correct translation.
_SIMPLIFIED_ONLY_CHARACTERS = (
    # Communication and documents.
    "设这说认识调变计论证评访询误读写译试诗诚话诞该详语请诸诺课谁谅谈谊谋"
    "谎谐谓谜谢谣谦谨谱许论训议讯记讲词记订讨让贝负贡财责贤败账货贩贪贫购"
    "贯贱贴贵贷贸费贺贼资赋赌赏赔赖赚赛赞赠赢"
    # Computing and structure.
    "个们关开时点线击项级质间问题团园围国场坏块坚报担拥择挂挡挤挥损换据摄"
    "摆数断无旧显术机杀杂权条来极构标样树检楼欧残毁网罗罚罢职联聪"
    # Pointers, shapes and places.
    "气汇汉汤沟没泽洁测济浓涂润涨渐湾湿满滤滨滚灭灯灵灾炉炼烂烟热焕爱爷牵"
    "状犹独狱猎献环现玛画畅疗盖盘码础确碍礼祷禅离种积称稳穷"
    # Writing, clothing and the body.
    "竞笔笼筑简签篮类粮紧纠红约纪纯纳纵纷纸纹练组织终经结绕绘给络绝统继绩"
    "绪续维综绿缓编缘缩肠肤肿胀胁胶脑脓脸腊腻腾舱艰节荐荣药莱莲获莹莺萝营"
    "萧萨虏虑虫虽蚀蚁蚕蛮蜕蜡蝇蝉补衬袭装"
    # Seeing, speaking and money again in one block keeps the list compact.
    "见观规视览觉誉鉴针钉钓钝钞钟钠钢钥钦钩钮钱铁铃铅铜铭银铸链销锁锅锋错"
    "键锯锥锦镇镜"
    # Transport, gates and weather.
    "长门闪闭闯闲闷闹闻阀阁阅队阳阴阵阶际陆陈险隐难雾静韦韧韩页顶顺须顽顾"
    "顿预领颇颈频颗额风飘飞车转轮软轰轴轻载较辅辆辈辉辑输辞边辽达迁过运还"
    "进远违连迟迹适选逊递逻遗邮邻释"
    # Food, animals and the last corners of the vocabulary.
    "饥饭饮饰饱饲饼饿馆驰驱驳驻驼验骂骄骆骗骡体驾驶骑骤鱼鲁鲜鲤鲨鲸鳄鸟鸡"
    "鸣鸥鸦鸭鸽鸿鹅鹰麦黄齐齿龄龙龟"
)

# Mainland software terms whose characters are shared with Traditional
# Chinese. The character scan cannot see them, so they are reported alone.
_MAINLAND_TERMS = ("文件夹", "文件", "保存", "支持", "信息")

# Matches one {placeholder} including format specs such as {seconds:.2f}.
_PLACEHOLDER_PATTERN = re.compile(r"\{[^{}]*\}")

_FAILURES = []
_WARNINGS = []


def check(label, condition):
    """Record one hard assertion and print it immediately."""
    status = "PASS" if condition else "FAIL"
    print("[ZH_TW {}] {}".format(status, label))
    if not condition:
        _FAILURES.append(label)


def warn(label):
    """Record one soft finding that needs a human decision."""
    print("[ZH_TW WARN] {}".format(label))
    _WARNINGS.append(label)


def load_dictionary(module_name, variable_name):
    """Import i18n/<module_name>.py with plain Python and return its dict."""
    module_path = os.path.join(_ROOT_DIR, "i18n", module_name + ".py")
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return dict(getattr(module, variable_name, {}))


def report_mismatches(label, keys, detail_by_key):
    """Print one line per affected key, capped so the log stays readable."""
    if not keys:
        return
    print("  {}: {} key(s)".format(label, len(keys)))
    for key in sorted(keys)[:10]:
        print("    {!r}: {}".format(key, detail_by_key[key]))
    if len(keys) > 10:
        print("    ... and {} more".format(len(keys) - 10))


def main():
    simplified = load_dictionary(*_SIMPLIFIED)
    traditional = load_dictionary(*_TRADITIONAL)

    # 1. Structural parity: same keys, so no language silently falls back.
    check("zh_cn dictionary is not empty", len(simplified) > 1000)
    check("zh_tw dictionary is not empty", len(traditional) > 1000)
    only_simplified = set(simplified) - set(traditional)
    only_traditional = set(traditional) - set(simplified)
    check(
        "both dictionaries describe the same keys",
        not only_simplified and not only_traditional,
    )
    report_mismatches(
        "missing in zh_tw",
        only_simplified,
        {key: repr(simplified[key])[:60] for key in only_simplified},
    )
    report_mismatches(
        "not in zh_cn",
        only_traditional,
        {key: repr(traditional[key])[:60] for key in only_traditional},
    )

    # 2. Values must be usable strings with the same literal shape.
    empty = [key for key, value in traditional.items() if not value.strip()]
    check("no empty zh_tw value", not empty)
    report_mismatches("empty", empty, {key: "" for key in empty})

    untranslated = [
        key
        for key, value in traditional.items()
        if key in simplified and simplified[key] != key and value == key
    ]
    check("no zh_tw row left in English", not untranslated)
    report_mismatches("left in English", untranslated, {key: key for key in untranslated})

    placeholder_problems = {}
    newline_problems = {}
    space_problems = {}
    for key, simplified_value in simplified.items():
        traditional_value = traditional.get(key)
        if traditional_value is None:
            continue
        if _PLACEHOLDER_PATTERN.findall(simplified_value) != _PLACEHOLDER_PATTERN.findall(
            traditional_value
        ):
            placeholder_problems[key] = "{!r} vs {!r}".format(
                _PLACEHOLDER_PATTERN.findall(simplified_value),
                _PLACEHOLDER_PATTERN.findall(traditional_value),
            )
        if simplified_value.count("\n") != traditional_value.count("\n"):
            newline_problems[key] = "{!r} vs {!r}".format(
                simplified_value, traditional_value
            )
        if (simplified_value[:1] == " ") != (traditional_value[:1] == " ") or (
            simplified_value[-1:] == " "
        ) != (traditional_value[-1:] == " "):
            space_problems[key] = "{!r} vs {!r}".format(
                simplified_value, traditional_value
            )

    check("every {placeholder} is preserved", not placeholder_problems)
    report_mismatches("placeholder changed", placeholder_problems, placeholder_problems)
    check("every line break is preserved", not newline_problems)
    report_mismatches("line break changed", newline_problems, newline_problems)
    check("surrounding spaces match zh_cn", not space_problems)
    report_mismatches("space changed", space_problems, space_problems)

    # 3. No Simplified character may survive in a Traditional value.
    simplified_only = frozenset(_SIMPLIFIED_ONLY_CHARACTERS)
    leftover = {}
    for key, value in traditional.items():
        found = sorted(set(value) & simplified_only)
        if found:
            leftover[key] = "{!r} in {!r}".format("".join(found), value[:60])
    check("no Simplified-only character left in zh_tw", not leftover)
    report_mismatches("leftover Simplified character", leftover, leftover)

    # 4. Soft report: mainland software terms that share every character with
    # Traditional Chinese and therefore pass the scan above.
    for term in _MAINLAND_TERMS:
        hits = [key for key, value in traditional.items() if term in value]
        if hits:
            warn("{} used in {} row(s), prefer a Taiwan term".format(term, len(hits)))
            for key in hits[:5]:
                print("    {!r}: {!r}".format(key, traditional[key][:60]))

    # 5. The dictionary module must stay importable without Blender, because
    # the coverage checker loads it with plain Python.
    traditional_source = open(
        os.path.join(_ROOT_DIR, "i18n", _TRADITIONAL[0] + ".py"), encoding="utf-8"
    ).read()
    check("zh_tw module does not import bpy", "import bpy" not in traditional_source)

    # 6. Summary. Warnings alone still exit successfully.
    print()
    if _WARNINGS:
        print("[ZH_TW] {} warning(s) need a human decision".format(len(_WARNINGS)))
    if _FAILURES:
        print("[ZH_TW] {} check(s) FAILED".format(len(_FAILURES)))
        return 1
    print("[ZH_TW] all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
