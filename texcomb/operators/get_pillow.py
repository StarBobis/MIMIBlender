"""Pillow dependency installation for Material Combiner.

This module installs the Pillow (PIL) library into the addon's own
``libs`` folder using ``pip --target``. Blender's bundled Python disables
user site-packages, so ``pip install --user`` is not available; this
addon-local approach works without administrator rights and without
modifying Blender's installation.

Usage example:
    bpy.ops.smc.get_pillow()
    bpy.ops.smc.check_pillow()
"""

import importlib.util
import os
import subprocess
import sys
from typing import Set, Tuple

import bpy

from .. import globs

# 默认走清华 PyPI 镜像，官方 PyPI 在国内经常超时导致安装失败
PIP_INDEX_URL = "https://pypi.tuna.tsinghua.edu.cn/simple"
PIP_FALLBACK_INDEX_URL = "https://pypi.org/simple"


def _refresh_combiner_pillow_cache() -> bool:
    """Refresh cached Pillow globals used by the combiner module."""
    try:
        from .combiner import combiner_ops

        return combiner_ops.initialize_pillow()
    except Exception as e:
        globs.pil_install_error_message = "刷新 Pillow 模块缓存失败: {}".format(e)
        return False


class InstallPIL(bpy.types.Operator):
    """Installs Pillow into the addon-local libs directory.

    Uses Blender's bundled pip with ``--target``, so it works even though
    Blender disables user site-packages, and no administrator rights are
    needed.
    """

    bl_idname = "smc.get_pillow"
    bl_label = "安装 PIL"
    bl_description = "点击安装 Pillow 库（安装到插件自身目录，无需管理员权限）。"

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
            self.report({"INFO"}, "Pillow 已经可以使用了！")
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
            "Pillow 安装完成，请重启 Blender" if success else "安装失败",
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
        last_error = "未知错误"

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
                return -2, "pip 安装超时（超过 180 秒），请检查网络后重试"
            except OSError as e:
                return -3, "无法启动 pip: {}".format(e)
            last_code = process.returncode
            if last_code == 0:
                return 0, ""
            last_error = (
                (process.stderr or process.stdout or "").strip()
                or "未知错误"
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
                error_msg = "Pillow 安装失败 (错误代码: {}): {}".format(
                    code, error
                )
                self.report({"ERROR"}, error_msg)
                globs.pil_install_error_message = error_msg
                return False

            return True
        except Exception as e:
            error_msg = "Pillow 安装过程中出错: {}".format(e)
            self.report({"ERROR"}, error_msg)
            globs.pil_install_error_message = error_msg
            return False


class CheckPillow(bpy.types.Operator):
    """Checks if Pillow is installed and refreshes the status.

    This operator re-checks the Pillow installation status and updates
    the global flags accordingly. Useful after manual installation or
    to refresh the UI without restarting Blender.
    """

    bl_idname = "smc.check_pillow"
    bl_label = "检查 Pillow"
    bl_description = "重新检查 Pillow 库是否已安装，可以在不重启的情况下刷新状态。"

    def execute(self, context: bpy.types.Context) -> Set[str]:
        """Execute the Pillow status check.

        Returns:
            Set containing "FINISHED".
        """
        success = globs.refresh_pil_availability()

        if success:
            success = _refresh_combiner_pillow_cache()
            if success:
                self.report({"INFO"}, "Pillow 已安装，可以使用！")
                # 清除之前的错误状态
                globs.pil_install_success = True
                globs.pil_available = True
                globs.pil_install_error_message = ""
            else:
                globs.pil_install_success = False
                globs.pil_available = False
                self.report({"ERROR"}, globs.pil_install_error_message)
        else:
            self.report({"ERROR"}, "Pillow 仍未安装，请尝试重新安装或手动安装。")

        return {"FINISHED"}
