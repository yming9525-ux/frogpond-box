# 父子级面板（逻辑在 core/hierarchy.py）
import bpy

from ..prefs import module_enabled


class POND_PT_hierarchy(bpy.types.Panel):
    bl_label = "父子级"
    bl_idname = "POND_PT_hierarchy"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "池塘"
    bl_parent_id = "POND_PT_sec_tidy"
    bl_order = 1
    bl_options = {"DEFAULT_CLOSED"}
    poll = module_enabled("show_hierarchy")

    def draw(self, context):
        col = self.layout.column(align=True)
        col.operator("pond.group_to_parent", text="所选打组", icon="LINKED")
        col.separator()
        col.operator("object.solo_pick_visn", text="单个拎出", icon="EXPORT")
        col.operator("pond.extract", text="全部拎出", icon="UNLINKED")
        col.separator()
        col.operator("pond.select_parents", text="选择所有父级", icon="RESTRICT_SELECT_OFF")


_classes = (
    POND_PT_hierarchy,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
