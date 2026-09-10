"""Check i18n coverage: every tr() msgid must exist in the zh_CN dictionary.

This script runs with plain Python (no Blender required). It walks the addon
source tree, parses every .py file with the ``ast`` module, and collects:

1. Every literal passed to ``tr(...)`` (implicit multi-line string
   concatenation is already folded into a single constant by the parser).
2. Every ``bl_label = "..."`` / ``bl_description = "..."`` class attribute,
   because those literals are used as translation keys by the @translatable
   decorator and by I18nOperator.
3. Simple module-level string constants referenced as ``tr(NAME)`` (for
   example ``tr(_INSTALL_HELP_TEXT)``).

It then imports ``i18n/zh_cn.py`` and reports:
- MISSING: keys used in code but absent from the dictionary.
- UNUSED: dictionary keys that no code references (likely stale).

Usage:
    python tools/check_i18n.py
    python tools/check_i18n.py --dump   # also print every collected msgid
"""

import ast
import importlib.util
import os
import sys

# Directories whose files are never part of the addon UI surface.
_EXCLUDED_DIRS = {"__pycache__", ".git", "tools", "node_modules"}

# Files that define the translation machinery itself (they contain example
# strings such as the language names, which are handled separately).
_EXCLUDED_FILES = {"i18n_experiment.py"}


def _iter_python_files(root_dir):
    """Yield every addon .py file that participates in the UI."""
    for current_dir, dir_names, file_names in os.walk(root_dir):
        dir_names[:] = [d for d in dir_names if d not in _EXCLUDED_DIRS]
        for file_name in file_names:
            if not file_name.endswith(".py"):
                continue
            if file_name in _EXCLUDED_FILES:
                continue
            yield os.path.join(current_dir, file_name)


def _literal_string(node):
    """Return the string value of a literal/concatenated constant, else None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _collect_module_constants(tree):
    """Collect module-level ``NAME = "literal"`` assignments."""
    constants = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                value = _literal_string(node.value)
                if value is not None:
                    constants[target.id] = value
    return constants


def _is_tr_call(node):
    """Whether an ast.Call node is a call to a function named ``tr``."""
    if not isinstance(node, ast.Call) or len(node.args) != 1:
        return False
    func = node.func
    if isinstance(func, ast.Name) and func.id == "tr":
        return True
    if isinstance(func, ast.Attribute) and func.attr == "tr":
        return True
    return False


def _collect_msgids_from_file(file_path):
    """Collect all translation keys used by a single source file."""
    # utf-8-sig transparently strips the BOM present in a few source files.
    with open(file_path, "r", encoding="utf-8-sig") as handle:
        source = handle.read()
    tree = ast.parse(source, filename=file_path)
    constants = _collect_module_constants(tree)
    msgids = set()

    for node in ast.walk(tree):
        # 1. tr("literal") and tr(CONSTANT_NAME) calls.
        if _is_tr_call(node):
            argument = node.args[0]
            value = _literal_string(argument)
            if value is None and isinstance(argument, ast.Name):
                value = constants.get(argument.id)
            if value:
                msgids.add(value)
            continue

        # 2. bl_label = "..." / bl_description = "..." class attributes.
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Name)
                    and target.id in ("bl_label", "bl_description")
                ):
                    value = _literal_string(node.value)
                    if value:
                        msgids.add(value)
            continue

        # 3. AnnAssign variants such as ``bl_label: str = "..."``.
        if isinstance(node, ast.AnnAssign):
            target = node.target
            if (
                isinstance(target, ast.Name)
                and target.id in ("bl_label", "bl_description")
            ):
                value = _literal_string(node.value)
                if value:
                    msgids.add(value)

    return msgids


def _load_translations(root_dir):
    """Import i18n/zh_cn.py with plain Python and return the dict."""
    zh_cn_path = os.path.join(root_dir, "i18n", "zh_cn.py")
    spec = importlib.util.spec_from_file_location("zh_cn", zh_cn_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return dict(getattr(module, "TRANSLATIONS_ZH_CN", {}))


def main():
    # The repository root is the parent directory of this tools script.
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dump_mode = "--dump" in sys.argv

    msgids = set()
    for file_path in _iter_python_files(root_dir):
        try:
            msgids |= _collect_msgids_from_file(file_path)
        except SyntaxError as error:
            print("SYNTAX ERROR in {}: {}".format(file_path, error))
            return 1

    translations = _load_translations(root_dir)

    missing = sorted(msgids - set(translations))
    unused = sorted(set(translations) - msgids)

    if dump_mode:
        print("=== {} msgids collected ===".format(len(msgids)))
        for msgid in sorted(msgids):
            print(repr(msgid))
        print()

    print("=== {} keys MISSING from zh_cn ===".format(len(missing)))
    for key in missing:
        print(repr(key))
    print()
    print("=== {} UNUSED keys in zh_cn ===".format(len(unused)))
    for key in unused:
        print(repr(key))

    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
