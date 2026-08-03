# 高模烘低模面板（逻辑在 core/hilow.py）
import bpy

from ..prefs import module_enabled


class POND_PT_hilow(bpy.types.Panel):
    bl_label = "高模烘低模"
    bl_idname = "POND_PT_hilow"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "池塘"
    bl_parent_id = "POND_PT_sec_make"
    bl_order = 7
    bl_options = {"DEFAULT_CLOSED"}
    poll = module_enabled("show_hilow")

    def draw(self, context):
        wm = context.window_manager
        layout = self.layout
        row = layout.row(align=True)
        row.prop(wm, "pond_hilow_res", text="")
        row.prop(wm, "pond_hilow_margin")
        row = layout.row(align=True)
        row.prop(wm, "pond_hilow_extrude")
        row.prop(wm, "pond_hilow_raydist")
        row = layout.row(align=True)
        row.prop(wm, "pond_hilow_normal", text="法线", toggle=True)
        row.prop(wm, "pond_hilow_ao", text="AO", toggle=True)
        row = layout.row(align=True)
        row.prop(wm, "pond_hilow_color", text="基础色", toggle=True)
        row.prop(wm, "pond_hilow_rough", text="糙度", toggle=True)
        layout.operator("pond.hilow_bake", icon="RENDER_STILL")
        row = layout.row(align=True)
        row.operator("pond.bakemap_use_baked", icon="TEXTURE")
        row.operator("pond.bakemap_use_orig", icon="LOOP_BACK")
        layout.label(text="先选高模, Ctrl再点低模(低模要亮)", icon="INFO")
        layout.label(text="穿模发黑就加大挤出距离", icon="INFO")


_classes = (
    POND_PT_hilow,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
