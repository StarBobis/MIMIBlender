"""Pillow dependency installation for Material Combiner.

This module installs the Pillow (PIL) library into the addon's own
``libs`` folder using ``pip --target``. Blender's bundled Python disables
user site-packages, so ``pip install --user`` is not available; this
addon-local approach works without administrator rights and without
modifying Blender's installation.

Usage example:
    bpy.ops.mimi.get_pillow()
    bpy.ops.mimi.check_pillow()
"""

import importlib.util
import os
import subprocess
import sys
from typing import Set, Tuple

import bpy

from ...i18n.i18n import I18nOperator, tr
from .. import globs

# Default to the Tsinghua PyPI mirror; the official PyPI often times out and fails to install
PIP_INDEX_URL = "https://pypi.tuna.tsinghua.edu.cn/simple"
PIP_FALLBACK_INDEX_URL = "https://pypi.org/simple"


def _refresh_combiner_pillow_cache() -> bool:
    """Refresh cached Pillow globals used by the combiner module."""
    try:
        from .combiner import combiner_ops

        return combiner_ops.initialize_pillow()
    except Exception as e:
        globs.pil_install_error_message = tr("Failed to refresh the cached Pillow module: {error}").format(error=e)
        return False


class InstallPIL(I18nOperator):
    """Installs Pillow into the addon-local libs directory.

    Uses Blender's bundled pip with ``--target``, so it works even though
    Blender disables user site-packages, and no administrator rights are
    needed.
    """

    bl_idname = "mimi.get_pillow"
    bl_label = "Install PIL"
    bl_description = "Click to install the Pillow library (installed into the addon's own directory, no administrator rights required)."

    def execute(self, context: bpy.types.Context) -> Set[str]:
        """Execute the Pillow installation process.

        Returns:
            Set containing "FINISHED" on success or "CANCELLED" on failure.
        """
        globs.pil_install_error_message = ""

        has_pil = all(
            self._module_exists(module)
            for module in ("PIL", "PIL.Image", "PIL.ImageChops")
        )

        if has_pil:
            globs.pil_install_attempted = True
            globs.pil_install_success = _refresh_combiner_pillow_cache()
            globs.pil_available = globs.pil_install_success
            if not globs.pil_install_success:
                self.report({"ERROR"}, globs.pil_install_error_message)
                return {"CANCELLED"}
            self.report({"INFO"}, tr("Pillow is ready to use!"))
            return {"FINISHED"}

        success = self._install_pillow()

        globs.pil_install_attempted = True
        globs.pil_install_success = success
        globs.pil_available = success

        if success:
            # Blender may keep import state that prevents loading a package just
            # installed by pip. Wait for restart so the add-on initializes
            # Pillow from a clean import state.
            globs.pil_install_success = True
            globs.pil_available = False
            globs.pil_install_error_message = ""

        self.report(
            {"INFO" if success else "ERROR"},
            tr("Pillow installation complete, please restart Blender") if success else tr("Installation failed"),
        )
        return {"FINISHED"} if success else {"CANCELLED"}

    @staticmethod
    def _module_exists(module_name: str) -> bool:
        """Return True if a module can be imported from the current paths."""
        return importlib.util.find_spec(module_name) is not None

    def _run_pip_install(self, args: list) -> Tuple[int, str]:
        """Run pip with the Tsinghua mirror first, falling back to PyPI.

        Returns:
            Tuple of (return code, stderr/stdout on failure).
        """
        last_code = -1
        last_error = "Unknown error"

        for index_url in (PIP_INDEX_URL, PIP_FALLBACK_INDEX_URL):
            try:
                process = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "pip",
                        "install",
                        "--disable-pip-version-check",
                        "--no-input",
                        "--timeout",
                        "30",
                        "--retries",
                        "2",
                    ]
                    + args
                    + ["-i", index_url],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    check=False,
                    timeout=180,
                )
            except subprocess.TimeoutExpired:
                return -2, tr("pip install timed out (over 180 seconds), please check your network and retry")
            except OSError as e:
                return -3, tr("Could not start pip: {error}").format(error=e)
            last_code = process.returncode
            if last_code == 0:
                return 0, ""
            last_error = (
                (process.stderr or process.stdout or "").strip()
                or "Unknown error"
            )

        return last_code, last_error

    def _install_pillow(self) -> bool:
        """Install Pillow into the addon-local libs directory."""
        try:
            lib_path = globs.PILLOW_LIB_PATH
            os.makedirs(lib_path, exist_ok=True)
            if lib_path not in sys.path:
                sys.path.insert(0, lib_path)

            code, error = self._run_pip_install(
                ["--target", lib_path, "--upgrade", "Pillow"]
            )
            if code != 0:
                error_msg = tr("Pillow installation failed (error code: {code}): {error}").format(
                    code=code, error=error
                )
                self.report({"ERROR"}, error_msg)
                globs.pil_install_error_message = error_msg
                return False

            return True
        except Exception as e:
            error_msg = tr("An error occurred while installing Pillow: {error}").format(error=e)
            self.report({"ERROR"}, error_msg)
            globs.pil_install_error_message = error_msg
            return False


class CheckPillow(I18nOperator):
    """Checks if Pillow is installed and refreshes the status.

    This operator re-checks the Pillow installation status and updates
    the global flags accordingly. Useful after manual installation or
    to refresh the UI without restarting Blender.
    """

    bl_idname = "mimi.check_pillow"
    bl_label = "Check Pillow"
    bl_description = "Re-check whether the Pillow library is installed; refreshes the status without a restart."

    def execute(self, context: bpy.types.Context) -> Set[str]:
        """Execute the Pillow status check.

        Returns:
            Set containing "FINISHED".
        """
        success = globs.refresh_pil_availability()

        if success:
            success = _refresh_combiner_pillow_cache()
            if success:
                self.report({"INFO"}, tr("Pillow is installed and ready to use!"))
                # Clear the previous error state
                globs.pil_install_success = True
                globs.pil_available = True
                globs.pil_install_error_message = ""
            else:
                globs.pil_install_success = False
                globs.pil_available = False
                self.report({"ERROR"}, globs.pil_install_error_message)
        else:
            self.report({"ERROR"}, tr("Pillow is still not installed. Try reinstalling it or install it manually."))

        return {"FINISHED"}
