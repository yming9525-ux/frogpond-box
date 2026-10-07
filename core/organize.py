# 原点吸附：批量把所选物体原点吸到包围盒某一侧
# （原 Pond/organize.py 一键整理；面板在 ui/pond/panels/organize.py）
import bpy

from mathutils import Vector


# 各方向：包围盒该侧面的中心（世界空间）
# (轴索引, 取min还是max)
_SIDES = {
    "TOP":    (2, max),
    "BOTTOM": (2, min),
    "LEFT":   (0, min),
    "RIGHT":  (0, max),
}


class POND_OT_origin_to_side(bpy.types.Operator):
    """所选物体原点批量吸附到包围盒某一侧的中心"""
    bl_idname = "pond.origin_to_side"
    bl_label = "原点吸附"
    bl_options = {"REGISTER", "UNDO"}

    side: bpy.props.EnumProperty(
        name="方向",
        items=[
            ("TOP", "顶部", "原点到包围盒顶面中心"),
            ("BOTTOM", "底部", "原点到包围盒底面中心（落地摆放用）"),
            ("LEFT", "左部", "原点到包围盒左面中心（-X）"),
            ("RIGHT", "右部", "原点到包围盒右面中心（+X）"),
        ],
        default="BOTTOM",
    )

    unlink_shared: bpy.props.BoolProperty(
        name="断开关联复制",
        default=False,
        description="关联复制(Alt+D)的物体共用一份网格，动原点会连累其他复制体。"
                    "默认跳过它们；勾上=给所选的那些各复制一份网格再吸附，"
                    "复制体之间从此互不影响",
    )

    @classmethod
    def poll(cls, context):
        return context.selected_objects and context.mode == "OBJECT"

    def execute(self, context):
        sel = [o for o in context.selected_objects if o.type in
               {"MESH", "CURVE", "SURFACE", "META", "FONT"}]
        if not sel:
            self.report({"WARNING"}, "所选里没有带几何的物体")
            return {"CANCELLED"}

        # 共用网格的物体：动原点会平移网格数据本身，没选中的复制体跟着跑位
        shared = [o for o in sel if o.data and o.data.users > 1]
        unlinked = 0
        if shared:
            if self.unlink_shared:
                for o in shared:
                    o.data = o.data.copy()
                    unlinked += 1
            else:
                names = {o.name for o in shared}
                sel = [o for o in sel if o.name not in names]
                if not sel:
                    self.report({"WARNING"},
                                "所选都是关联复制体，动原点会连累其他复制体，"
                                "全跳过了。真要吸就在下面勾「断开关联复制」")
                    return {"CANCELLED"}

        axis, pick = _SIDES[self.side]

        cursor = context.scene.cursor
        cursor_backup = cursor.location.copy()
        active_backup = context.view_layer.objects.active
        selected_backup = list(context.selected_objects)

        try:
            for o in sel:
                corners = [o.matrix_world @ Vector(c) for c in o.bound_box]
                target = Vector((
                    sum(c.x for c in corners) / 8.0,
                    sum(c.y for c in corners) / 8.0,
                    sum(c.z for c in corners) / 8.0,
                ))
                target[axis] = pick(c[axis] for c in corners)
                bpy.ops.object.select_all(action="DESELECT")
                o.select_set(True)
                context.view_layer.objects.active = o
                cursor.location = target
                bpy.ops.object.origin_set(type="ORIGIN_CURSOR")
        finally:
            cursor.location = cursor_backup
            bpy.ops.object.select_all(action="DESELECT")
            for o in selected_backup:
                o.select_set(True)
            context.view_layer.objects.active = active_backup
        if unlinked:
            self.report({"INFO"},
                        "%d 件断开了关联复制（各自复制了一份网格）" % unlinked)
        elif shared:
            self.report({"WARNING"},
                        "%d 件是关联复制体，跳过了（动它们会连累其他复制体，"
                        "真要吸就在下面勾「断开关联复制」）" % len(shared))
        return {"FINISHED"}


_classes = (
    POND_OT_origin_to_side,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
