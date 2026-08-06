# Pond —— 蛙灾的池塘工具箱
# N 面板「池塘」页，四抽屉：🧹整理 / 🔨制作 / 💡灯渲 / 🎞动画
bl_info = {
    "name": "Pond（池塘）",
    "category": "3D View",
    "author": "蛙灾",
    "blender": (5, 2, 0),  # 仅支持 Blender 5.2
    "location": "View3D > Sidebar（N 面板）",
    "description": "蛙灾的池塘工具箱：整理 / 制作 / 灯渲 / 动画",
    "version": (1, 2, 2),
}

import bpy

# ── 开发期热重载（禁用/启用或 F8 时子模块一并刷新） ──
import importlib
import sys


def _reload_submodules():
    pkg = __name__
    mods = sorted((m for m in sys.modules if m.startswith(pkg + ".")),
                  reverse=True)
    for name in mods:
        try:
            importlib.reload(sys.modules[name])
        except Exception as e:
            print(f"[pond] reload {name} 失败: {e}")


# 顶层模块被 Blender 重新导入时（F8 / 重新勾选），刷新所有子模块
if "_addon_loaded" in globals():
    _reload_submodules()
_addon_loaded = True

from . import prefs as _prefs
from . import core as _core
from . import ui as _ui


def register():
    _prefs.register()
    _core.register()
    _ui.register()


def unregister():
    _ui.unregister()
    _core.unregister()
    _prefs.unregister()
