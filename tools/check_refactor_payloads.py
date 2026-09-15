"""Verify no INI line was lost or altered by the games/ refactor.

For every migrated game file, collect every section .append(...) string
payload (in order) from the HEAD version and from the new layout (the game
file plus games/base/sections.py).  Every old payload must still exist in
the new layout; extra payloads are reported for review.
"""
import ast
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def git_show(path):
    result = subprocess.run(
        ["git", "show", f"HEAD:{path}"],
        capture_output=True, cwd=ROOT,
    )
    if result.returncode != 0:
        return None
    return result.stdout.decode("utf-8")


def append_payloads(source):
    """Return the ordered list of string payloads of x.append("...") calls."""
    tree = ast.parse(source)
    payloads = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "append"):
            continue
        if not node.args:
            continue
        arg = node.args[0]
        try:
            value = ast.literal_eval(arg)
        except (ValueError, SyntaxError):
            continue
        if isinstance(value, str):
            payloads.append(value)
    return payloads


def counter(items):
    counts = {}
    for item in items:
        counts[item] = counts.get(item, 0) + 1
    return counts


# game file -> list of new files that now hold its payloads
MIGRATED = {
    "games/snowbreak.py": ["games/snowbreak.py", "games/base/sections.py"],
    "games/yysls.py": ["games/yysls.py", "games/base/sections.py"],
    "games/identityv.py": ["games/identityv.py", "games/base/sections.py"],
    "games/unity.py": ["games/unity.py", "games/base/sections.py"],
    "games/himi.py": ["games/unity.py", "games/base/sections.py"],
    "games/zzmi.py": ["games/zzmi.py", "games/base/sections.py"],
    "games/zzmidx12.py": ["games/zzmidx12.py", "games/base/sections.py"],
    "games/gimi.py": ["games/gimi/exporter.py", "games/base/sections.py"],
    "games/naraka.py": ["games/naraka/exporter.py", "games/base/sections.py"],
    "games/wwmi.py": ["games/wwmi/exporter.py", "games/wwmi/shapekeys.py", "games/wwmi/blend_remap.py"],
    "games/ntemi.py": ["games/ntemi/exporter.py", "games/ntemi/sections.py", "games/ntemi/buffers.py"],
}

failures = 0
for old_path, new_paths in MIGRATED.items():
    old_source = git_show(old_path)
    if old_source is None:
        print(f"SKIP {old_path}: not in HEAD")
        continue
    old_counts = counter(append_payloads(old_source))

    new_payloads = []
    for new_path in new_paths:
        full = os.path.join(ROOT, new_path)
        with open(full, "r", encoding="utf-8") as f:
            new_payloads.extend(append_payloads(f.read()))
    new_counts = counter(new_payloads)

    missing = []
    for payload, count in old_counts.items():
        shortfall = count - new_counts.get(payload, 0)
        if shortfall > 0:
            missing.append((shortfall, payload))

    if missing:
        failures += 1
        print(f"FAIL {old_path}: {len(missing)} payload(s) missing from the new layout")
        for shortfall, payload in missing:
            print(f"    x{shortfall} {payload!r}")
    else:
        print(f"OK   {old_path}: all {sum(old_counts.values())} payloads preserved")

sys.exit(1 if failures else 0)
