"""Global constants and configuration for the Material Combiner addon.

This module contains version detection logic, global constants, and configuration
variables used throughout the addon. It provides consistent access to version-specific
features and establishes addon-wide settings.
"""

import importlib.util
import os
import site
import sys

import bpy

# 插件自带依赖目录：pip --target 安装到这里，避免 Blender 禁用 user site 的问题
_ADDON_DIR = os.path.dirname(os.path.abspath(__file__))
PILLOW_LIB_PATH = os.path.join(_ADDON_DIR, "libs")

if PILLOW_LIB_PATH not in sys.path:
    sys.path.insert(0, PILLOW_LIB_PATH)

_user_site = site.getusersitepackages()
if _user_site and _user_site not in sys.path:
    sys.path.insert(0, _user_site)

pil_available = all(
    importlib.util.find_spec(module) is not None
    for module in ("PIL", "PIL.Image", "PIL.ImageChops")
)

pil_install_attempted = False
pil_install_success = False
pil_install_error_message = ""


def refresh_pil_availability() -> bool:
    """Refresh the Pillow availability status.

    This function re-checks if Pillow is available in the current environment,
    and updates the global pil_available flag. It's useful after installation
    attempts without requiring a restart.

    Returns:
        True if Pillow is available after refresh, False otherwise.
    """
    global pil_available, pil_install_success, pil_install_error_message

    # 重新检查 PIL 是否可用
    try:
        # 刷新 site 目录
        import importlib
        if 'site' in sys.modules:
            importlib.reload(sys.modules['site'])

        # 确保插件自带依赖目录在路径中
        if PILLOW_LIB_PATH not in sys.path:
            sys.path.insert(0, PILLOW_LIB_PATH)

        # 添加 user site packages 到路径（避免重复添加）
        user_site = site.getusersitepackages()
        if user_site and user_site not in sys.path:
            sys.path.insert(0, user_site)

        # 检查各个模块
        for module in ("PIL", "PIL.Image", "PIL.ImageChops"):
            # 先清除可能已经加载的旧模块
            if module in sys.modules:
                del sys.modules[module]

        pil_available = all(
            importlib.util.find_spec(module) is not None
            for module in ("PIL", "PIL.Image", "PIL.ImageChops")
        )

        # 如果可用，更新安装状态
        if pil_available:
            pil_install_success = True
            pil_install_error_message = ""

        return pil_available
    except Exception:
        # 如果刷新过程出错，保持原样
        return pil_available

is_blender_legacy = False
is_blender_modern = True
is_blender_2_92_plus = True
is_blender_3_plus = True

ICON_OBJECT = "META_CUBE" if is_blender_modern else "VIEW3D"
ICON_PROPERTIES = "PREFERENCES" if is_blender_modern else "SCRIPT"
ICON_DROPDOWN = "THREE_DOTS" if is_blender_modern else "DOWNARROW_HLT"


class CombineListTypes:
    """Constants for material combination list entry types.

    These constants are used to identify the type of entry in the
    material combination list UI. They determine how entries are
    displayed, processed, and interacted with.
    """

    OBJECT = 0
    MATERIAL = 1
    SEPARATOR = 2
