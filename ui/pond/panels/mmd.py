# MMD 刚体关节面板（逻辑在 core/mmd.py）
import bpy

from ..prefs import module_enabled


class POND_PT_mmd(bpy.types.Panel):
    bl_label = "MMD 刚体关节"
    bl_idname = "POND_PT_mmd"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "池塘"
    bl_parent_id = "POND_PT_sec_tidy"
    bl_order = 4
    bl_options = {"DEFAULT_CLOSED"}
    poll = module_enabled("show_mmd")

    def draw(self, context):
        col = self.layout.column(align=True)
        row = col.row(align=True)
        row.operator("pond.mmd_physics_vis", text="藏起来",
                     icon="HIDE_ON").show = False
        row.operator("pond.mmd_physics_vis", text="放出来",
                     icon="HIDE_OFF").show = True
        col.separator()
        col.label(text="选中模型就只动它，没选就全场景", icon="INFO")


_classes = (
    POND_PT_mmd,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
