"""Check i18n coverage: every tr() msgid must exist in every dictionary.

This script runs with plain Python (no Blender required). It walks the addon
source tree, parses every .py file with the ``ast`` module, and collects:

1. Every literal passed to ``tr(...)`` (implicit multi-line string
   concatenation is already folded into a single constant by the parser).
2. Every ``bl_label = "..."`` / ``bl_description = "..."`` class attribute,
   because those literals are used as translation keys by the @translatable
   decorator and by I18nOperator.
3. Simple module-level string constants referenced as ``tr(NAME)`` (for
   example ``tr(_INSTALL_HELP_TEXT)``).

It then imports every dictionary listed in ``_LANGUAGE_DICTIONARIES`` and
reports, per language:
- MISSING: keys used in code but absent from that dictionary.
- UNUSED: dictionary keys that no code references (likely stale).

Finally it compares the languages with each other: a key translated in one
language has to be translated in all of them, otherwise switching the language
silently falls back to English.

Usage:
    python tools/check_i18n.py
    python tools/check_i18n.py --dump   # also print every collected msgid
"""

import ast
import importlib.util
import os
import sys

# Directories whose files are never part of the addon UI surface. "tmp" holds
# scratch copies (packed releases, baseline checkouts) that .gitignore already
# excludes; scanning them reported stale keys of older versions as missing.
_EXCLUDED_DIRS = {"__pycache__", ".git", "tools", "node_modules", "tmp"}

# Files that define the translation machinery itself (they contain example
# strings such as the language names, which are handled separately).
_EXCLUDED_FILES = {"i18n_experiment.py"}

# One row per translated language: the module below i18n/ and the dictionary
# variable it exports. Adding a language to i18n/i18n.py only needs one new row
# here; the rest of this script walks the table.
_LANGUAGE_DICTIONARIES = (
    ("zh_cn", "TRANSLATIONS_ZH_CN"),
    ("zh_tw", "TRANSLATIONS_ZH_TW"),
)


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


def _load_dictionary(root_dir, module_name, variable_name):
    """Import i18n/<module_name>.py with plain Python and return its dict."""
    module_path = os.path.join(root_dir, "i18n", module_name + ".py")
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return dict(getattr(module, variable_name, {}))


def _report_language(module_name, translations, msgids):
    """Print the missing and unused keys of one language and return a count."""
    missing = sorted(msgids - set(translations))
    unused = sorted(set(translations) - msgids)
    print(
        "=== {}: {} keys MISSING, {} UNUSED ===".format(
            module_name, len(missing), len(unused)
        )
    )
    for key in missing:
        print("MISSING {}".format(repr(key)))
    for key in unused:
        print("UNUSED  {}".format(repr(key)))
    print()
    # Only a missing key breaks the UI; an unused key is a maintenance hint.
    return len(missing)


def _report_parity(dictionaries):
    """Print keys that one language has and another language lacks."""
    every_key = set()
    for translations in dictionaries.values():
        every_key.update(translations)
    problems = 0
    for module_name, translations in dictionaries.items():
        absent = sorted(every_key - set(translations))
        if not absent:
            continue
        problems += len(absent)
        print(
            "=== {}: {} keys missing compared with other languages ===".format(
                module_name, len(absent)
            )
        )
        for key in absent:
            print("PARITY  {}".format(repr(key)))
        print()
    return problems


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

    if dump_mode:
        print("=== {} msgids collected ===".format(len(msgids)))
        for msgid in sorted(msgids):
            print(repr(msgid))
        print()

    dictionaries = {}
    problems = 0
    for module_name, variable_name in _LANGUAGE_DICTIONARIES:
        translations = _load_dictionary(root_dir, module_name, variable_name)
        dictionaries[module_name] = translations
        problems += _report_language(module_name, translations, msgids)
    problems += _report_parity(dictionaries)

    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
