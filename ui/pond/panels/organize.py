# 原点吸附面板（逻辑在 core/organize.py）
import bpy

from ..prefs import module_enabled


class POND_PT_organize(bpy.types.Panel):
    bl_label = "原点吸附"
    bl_idname = "POND_PT_organize"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "池塘"
    bl_parent_id = "POND_PT_sec_tidy"
    bl_order = 2
    bl_options = {"DEFAULT_CLOSED"}
    poll = module_enabled("show_organize")

    def draw(self, context):
        col = self.layout.column(align=True)
        row = col.row(align=True)
        row.operator("pond.origin_to_side", text="顶部", icon="TRIA_UP_BAR").side = "TOP"
        row.operator("pond.origin_to_side", text="底部", icon="TRIA_DOWN_BAR").side = "BOTTOM"
        row = col.row(align=True)
        row.operator("pond.origin_to_side", text="左部", icon="TRIA_LEFT_BAR").side = "LEFT"
        row.operator("pond.origin_to_side", text="右部", icon="TRIA_RIGHT_BAR").side = "RIGHT"


_classes = (
    POND_PT_organize,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
