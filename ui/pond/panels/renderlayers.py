# 分层渲染面板（逻辑在 core/renderlayers.py）
import bpy

from ..prefs import module_enabled
from ....core.renderlayers import NG_NAME


class POND_PT_renderlayers(bpy.types.Panel):
    bl_label = "分层渲染"
    bl_idname = "POND_PT_renderlayers"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "池塘"
    bl_parent_id = "POND_PT_sec_look"
    bl_order = 5
    bl_options = {"DEFAULT_CLOSED"}
    poll = module_enabled("show_renderlayers")

    def draw(self, context):
        col = self.layout.column(align=True)
        col.operator("pond.exr_passes_setup", icon="RENDERLAYERS")
        col.operator("pond.exr_passes_clear", icon="X")
        if bpy.data.node_groups.get(NG_NAME):
            self.layout.label(text="通道EXR已接好", icon="CHECKMARK")
        self.layout.label(text="渲染一次，EXR带全部通道", icon="INFO")
        self.layout.label(text="输出路径在文件输出节点上改", icon="INFO")


_classes = (
    POND_PT_renderlayers,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
