"""Static import verification for the games/ refactor.

Resolves every relative import in the addon against the file tree and
checks that imported names exist at the target module's top level.
Third-party modules (bpy, numpy, ...) are skipped.
"""
import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# The addon package name is the folder name; relative imports resolve inside it.
ADDON_PKG = os.path.basename(ROOT)

errors = []


def module_file(package_parts):
    """Return the file path of a module given its package parts, or None."""
    path = os.path.join(ROOT, *package_parts)
    if os.path.isfile(path + ".py"):
        return path + ".py"
    init = os.path.join(path, "__init__.py")
    if os.path.isfile(init):
        return init
    return None


def top_level_names(filepath):
    """Collect every top-level name a module defines (class/def/assign/import)."""
    with open(filepath, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filepath)
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names.add(alias.asname or alias.name)
    return names


def check_file(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filepath)

    # package parts of the module's own package (relative import anchor)
    rel = os.path.relpath(filepath, ROOT)
    parts = rel.split(os.sep)
    if parts[-1] == "__init__.py":
        own_pkg = parts[:-1]
    else:
        own_pkg = parts[:-1]

    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.level == 0:
            continue
        # Resolve the relative import against the module's package.
        base = list(own_pkg)
        for _ in range(node.level - 1):
            if base:
                base.pop()
        target_parts = base + (node.module.split(".") if node.module else [])
        target_file = module_file(target_parts)
        target_dir = os.path.join(ROOT, *target_parts)
        if target_file is None and not os.path.isdir(target_dir):
            errors.append(f"{rel}:{node.lineno} cannot resolve module '{'..'* (node.level-1)}.{node.module}' -> {'/'.join(target_parts)}")
            continue
        # A plain directory works as a namespace package (Python 3), which
        # some addon folders (blueprint/, sword/) rely on.
        target_names = top_level_names(target_file) if target_file else set()
        target_is_pkg = (target_file is not None and target_file.endswith("__init__.py")) or os.path.isdir(target_dir)
        for alias in node.names:
            if alias.name == "*":
                continue
            if alias.name in target_names:
                continue
            # Maybe a submodule: check pkg/submodule.py
            if target_is_pkg and module_file(target_parts + [alias.name]) is not None:
                continue
            errors.append(f"{rel}:{node.lineno} name '{alias.name}' not found in {'/'.join(target_parts)}")


count = 0
for dirpath, dirnames, filenames in os.walk(ROOT):
    dirnames[:] = [d for d in dirnames if d not in ("__pycache__", ".git", ".pytest_cache", "libs")]
    for filename in filenames:
        if filename.endswith(".py"):
            count += 1
            check_file(os.path.join(dirpath, filename))

print(f"checked {count} files")
if errors:
    print(f"{len(errors)} import problem(s):")
    for err in errors:
        print("  " + err)
    sys.exit(1)
print("ALL LOCAL IMPORTS RESOLVE")
