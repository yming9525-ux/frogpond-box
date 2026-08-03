# 池塘 AddonPreferences：模块开关 + 预设库路径。
# bl_idname = __package__，模块开关名单只维护一份（ui/pond/prefs.py 的 MODULES）。
import bpy
from bpy.types import AddonPreferences
from bpy.props import BoolProperty, StringProperty

from .ui.pond.prefs import MODULES


class PondPreferences(AddonPreferences):
    bl_idname = __package__

    # ── 预设库 ──
    preset_lib_root: StringProperty(
        name="预设库路径",
        description="预设库的保存根目录（几何节点/材质预设都存这里面）",
        subtype="DIR_PATH",
        default=r"I:\Blender资产\预设库",
    )

    def draw(self, context):
        layout = self.layout
        box = layout.box()
        box.label(text="池塘模块开关（关掉的模块不在「池塘」页显示）",
                  icon='PREFERENCES')
        grid = box.grid_flow(row_major=True, columns=4, even_columns=True,
                             even_rows=True, align=True)
        for key, label in MODULES:
            grid.prop(self, key, text=label, toggle=True)
        box = layout.box()
        box.prop(self, "preset_lib_root")


# 模块开关动态挂到偏好类上（名单只维护 ui/pond/prefs.py 一份）
for _key, _label in MODULES:
    PondPreferences.__annotations__[_key] = BoolProperty(
        name=_label, default=True)


def register():
    bpy.utils.register_class(PondPreferences)


def unregister():
    bpy.utils.unregister_class(PondPreferences)
