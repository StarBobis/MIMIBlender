"""Pytest bootstrap for the texcomb core tests.

Two problems are solved here:

1. The repository root must be on sys.path so ``import texcomb.core...``
   works no matter how pytest was invoked.

2. pytest imports the ANCESTOR packages of a test file by their full dotted
   name (here: "MIMIBlender.texcomb") when they contain an __init__.py. The
   repository-root package "MIMIBlender" is the Blender addon entry point and
   its __init__.py requires a real Blender bpy, so that import would crash
   outside Blender. We pre-seed sys.modules with a stub for the root package
   and with the real (bpy-safe) texcomb package, so the import machinery
   finds everything already loaded and never executes the addon's __init__.
"""

import os
import sys
import types

# texcomb/tests/ -> texcomb/ -> repo root (two levels up from this file).
_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), os.pardir, os.pardir)
)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# The root package name equals the repository directory name.
_ROOT_PACKAGE_NAME = os.path.basename(_REPO_ROOT)

if _ROOT_PACKAGE_NAME not in sys.modules:
    # Stub module standing in for the repo-root Blender addon package.
    # Its __path__ points at the real directory, so submodule imports
    # (e.g. "MIMIBlender.texcomb") resolve to real, bpy-safe files.
    _stub = types.ModuleType(_ROOT_PACKAGE_NAME)
    _stub.__path__ = [_REPO_ROOT]
    sys.modules[_ROOT_PACKAGE_NAME] = _stub

# Import the bpy-safe texcomb package (its __init__ skips registration when
# no real bpy exists) and alias it under the full dotted name pytest uses.
import texcomb  # noqa: E402

sys.modules.setdefault(_ROOT_PACKAGE_NAME + ".texcomb", texcomb)
