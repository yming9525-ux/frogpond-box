# MMD 刚体关节：一键关掉 joints / rigidbodies 的视图显示，开关集合后不会再冒出来
import bpy

# mmd_tools 挂在物体上的类型标记
_ROOT = "ROOT"
_GRP = ("RIGID_GRP_OBJ", "JOINT_GRP_OBJ")     # joints / rigidbodies 两个组空物体
_ITEM = ("RIGID_BODY", "JOINT")               # 组底下一颗颗的刚体和关节


def _mmd_type(ob):
    return getattr(ob, "mmd_type", "NONE")


def _root_of(ob):
    """从任意物体往上找 MMD 模型根"""
    while ob is not None:
        if ob.type == "EMPTY" and _mmd_type(ob) == _ROOT:
            return ob
        ob = ob.parent
    return None


def _pick_roots(context):
    """选中了就只动选中的那些模型，什么都没选就动全场景"""
    picked = {}
    for ob in context.selected_objects:
        r = _root_of(ob)
        if r is not None:
            picked[r.name] = r
    if picked:
        return list(picked.values()), True
    return [ob for ob in context.scene.objects
            if ob.type == "EMPTY" and _mmd_type(ob) == _ROOT], False


def _physics_objects(root):
    """根下所有刚体和关节，连两个组空物体一起收上来。
    父级的显示器图标不会传给子级，所以每一个都得单独设
    """
    out = []
    stack = list(root.children)
    while stack:
        o = stack.pop()
        stack.extend(o.children)
        if _mmd_type(o) in _GRP or _mmd_type(o) in _ITEM:
            out.append(o)
    return out


class POND_OT_mmd_physics_vis(bpy.types.Operator):
    """关掉 MMD 的 joints 和 rigidbodies 视图显示。
    用显示器图标(hide_viewport)，状态存在物体上跟着工程走，
    集合的复选框开开关关也不会把它们放出来（小眼睛会被重置，所以不用小眼睛）
    """
    bl_idname = "pond.mmd_physics_vis"
    bl_label = "MMD 刚体关节显示"
    bl_options = {"REGISTER", "UNDO"}

    show: bpy.props.BoolProperty(name="显示出来", default=False)

    def execute(self, context):
        if not hasattr(bpy.types.Object, "mmd_type"):
            self.report({"ERROR"}, "没检测到 mmd_tools，去偏好设置里把它打开再用")
            return {"CANCELLED"}

        roots, from_sel = _pick_roots(context)
        if not roots:
            self.report({"WARNING"}, "场景里没有 MMD 模型，要先用 mmd_tools 导入一个")
            return {"CANCELLED"}

        n = 0
        for root in roots:
            for o in _physics_objects(root):
                o.hide_viewport = not self.show
                n += 1
            # 跟 mmd_tools 自己那两个开关对齐，免得它面板上还亮着
            mr = getattr(root, "mmd_root", None)
            if mr is not None:
                mr.show_rigid_bodies = self.show
                mr.show_joints = self.show

        if n == 0:
            self.report({"WARNING"}, "这些模型里没有刚体和关节，没什么可关的")
            return {"CANCELLED"}

        where = "选中的 %d 个模型" % len(roots) if from_sel else "全场景 %d 个模型" % len(roots)
        self.report({"INFO"}, "%s，%d 个刚体/关节已%s"
                    % (where, n, "放出来" if self.show else "藏起来"))
        return {"FINISHED"}


_classes = (
    POND_OT_mmd_physics_vis,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
