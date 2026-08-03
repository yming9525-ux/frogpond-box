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

    @classmethod
    def poll(cls, context):
        return context.selected_objects and context.mode == "OBJECT"

    def execute(self, context):
        sel = [o for o in context.selected_objects if o.type in
               {"MESH", "CURVE", "SURFACE", "META", "FONT"}]
        if not sel:
            self.report({"WARNING"}, "所选里没有带几何的物体")
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
