import ast
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", ".venv", "__pycache__", ".mypy_cache", ".pytest_cache", "node_modules"}


def iter_py_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for filename in filenames:
            if filename.endswith(".py"):
                yield Path(dirpath) / filename


def get_decorators(node):
    names = set()
    for deco in node.decorator_list:
        if isinstance(deco, ast.Name):
            names.add(deco.id)
    return names


def get_loaded_names(node):
    loaded = set()

    class Visitor(ast.NodeVisitor):
        def visit_Name(self, name_node):
            if isinstance(name_node.ctx, ast.Load):
                loaded.add(name_node.id)

    Visitor().visit(node)
    return loaded


def main():
    issues = []

    for path in iter_py_files(ROOT):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except Exception:
            continue

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue

            decorators = get_decorators(node)
            if "staticmethod" not in decorators and "classmethod" not in decorators:
                continue

            argnames = {arg.arg for arg in getattr(node.args, "posonlyargs", [])}
            argnames.update(arg.arg for arg in node.args.args)
            argnames.update(arg.arg for arg in node.args.kwonlyargs)
            if node.args.vararg:
                argnames.add(node.args.vararg.arg)
            if node.args.kwarg:
                argnames.add(node.args.kwarg.arg)

            loaded = get_loaded_names(node)
            if "staticmethod" in decorators:
                if "cls" in loaded and "cls" not in argnames:
                    issues.append(f"{path}:{node.lineno}: staticmethod uses cls: {node.name}")
                if "self" in loaded and "self" not in argnames:
                    issues.append(f"{path}:{node.lineno}: staticmethod uses self: {node.name}")
            if "classmethod" in decorators and "self" in loaded and "self" not in argnames:
                issues.append(f"{path}:{node.lineno}: classmethod uses self: {node.name}")

    if issues:
        for issue in issues:
            print(issue)
        return 1

    print("No staticmethod/classmethod misuse found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
