# 关键帧错开面板（逻辑在 core/keyoffset.py）
import bpy

from ..prefs import module_enabled


class POND_PT_keyoffset(bpy.types.Panel):
    bl_label = "关键帧错开"
    bl_idname = "POND_PT_keyoffset"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "池塘"
    bl_parent_id = "POND_PT_sec_ship"
    bl_order = 2
    bl_options = {"DEFAULT_CLOSED"}
    poll = module_enabled("show_keyoffset")

    def draw(self, context):
        wm = context.window_manager
        col = self.layout.column(align=True)

        row = col.row(align=True)
        row.prop(wm, "pond_keyoff_step")
        row.prop(wm, "pond_keyoff_reverse", toggle=True)
        col.prop(wm, "pond_keyoff_order", text="")
        col.prop(wm, "pond_keyoff_only_sel")

        col.separator()
        op = col.operator("pond.key_offset", text="错开", icon="IPO_EASE_IN_OUT")
        op.step = wm.pond_keyoff_step
        op.reverse = wm.pond_keyoff_reverse
        op.order = wm.pond_keyoff_order
        op.only_selected = wm.pond_keyoff_only_sel

        col.separator()
        col.label(text="姿态模式选中一串骨骼，从根到梢依次延后", icon="INFO")
        col.label(text="摄影表里框住几帧，就只错开那几帧", icon="BLANK1")
        col.label(text="步长填负数可以把错开过头的收回来", icon="BLANK1")


_classes = (
    POND_PT_keyoffset,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
