# 关键帧错开：一串骨骼的关键帧按顺序依次延后，做披风、头发、尾巴的跟随
# （面板在 ui/pond/panels/keyoffset.py）
import re

import bpy


def _depth(pb):
    """骨骼在链上的深度，根为 0"""
    d, p = 0, pb.parent
    while p is not None:
        d += 1
        p = p.parent
    return d


def _numkey(name):
    """名字里第一串数字，Cloak_9_1 取 9；没数字算 0"""
    m = re.search(r"\d+", name)
    return int(m.group()) if m else 0


def _fcurves_for(ob):
    """取物体当前动作里属于它那个槽的曲线。
    5.x 的分层动作要走 layers/strips/channelbags，老工程的动作还挂在 fcurves 上
    """
    ad = ob.animation_data
    act = ad.action if ad else None
    if act is None:
        return []
    handle = getattr(ad, "action_slot_handle", None)
    out = []
    for layer in getattr(act, "layers", ()):
        for strip in layer.strips:
            for cb in getattr(strip, "channelbags", ()):
                if handle is not None and getattr(cb, "slot_handle", None) != handle:
                    continue
                out.extend(cb.fcurves)
    if not out:
        out = list(getattr(act, "fcurves", ()) or ())
    return out


def _sorted_bones(bones, order):
    """层级模式先按链上深度，同深度用名字里的数字兜底"""
    if order == "NAME":
        return sorted(bones, key=lambda b: (_numkey(b.name), b.name))
    return sorted(bones, key=lambda b: (_depth(b), _numkey(b.name), b.name))


class POND_OT_key_offset(bpy.types.Operator):
    """选中的一串骨骼，关键帧从根到梢依次延后，做出跟随的波浪"""
    bl_idname = "pond.key_offset"
    bl_label = "关键帧错开"
    bl_options = {"REGISTER", "UNDO"}

    step: bpy.props.IntProperty(
        name="步长",
        default=1,
        soft_min=-10, soft_max=10,
        description="每根骨骼比前一根晚几帧。填负数就是往回收，"
                    "可以把错开过头的收回来",
    )

    reverse: bpy.props.BoolProperty(
        name="反向",
        default=False,
        description="改成从末梢往根部传，用在甩回来的动作上",
    )

    only_selected: bpy.props.BoolProperty(
        name="只动选中的帧",
        default=True,
        description="摄影表里选中了关键帧就只错开那些，前后的动作留在原地。"
                    "一个都没选时自动改成整条动画一起错开",
    )

    order: bpy.props.EnumProperty(
        name="顺序",
        items=[
            ("HIERARCHY", "按层级", "顺着骨骼的父子链，从根排到梢，一般用这个"),
            ("NAME", "按名字", "按名字里的数字排。骨骼不是一条链、"
                               "或者层级排出来不对时用"),
        ],
        default="HIERARCHY",
    )

    @classmethod
    def poll(cls, context):
        ob = context.object
        return bool(ob and ob.type == "ARMATURE" and context.mode == "POSE")

    def execute(self, context):
        ob = context.object
        curves = _fcurves_for(ob)
        if not curves:
            self.report({"WARNING"}, "这个骨架还没有动画，先 K 几帧再来错开")
            return {"CANCELLED"}

        # 5.2 起选中状态挂在 PoseBone 上，不在 Bone 上
        bones = list(context.selected_pose_bones or [])
        if not bones:
            bones = [b for b in ob.pose.bones if b.select and not b.hide]
        if len(bones) < 2:
            self.report({"WARNING"}, "至少选两根骨骼，一根没什么可错开的")
            return {"CANCELLED"}
        if self.step == 0:
            self.report({"WARNING"}, "步长是 0，什么都没动")
            return {"CANCELLED"}

        bones = _sorted_bones(bones, self.order)
        if self.reverse:
            bones.reverse()

        # 摄影表里一个关键帧都没选时，「只动选中的」自动让位，免得点了没反应
        has_sel = any(kp.select_control_point
                      for fc in curves for kp in fc.keyframe_points)
        use_sel = self.only_selected and has_sel
        before_total = sum(len(fc.keyframe_points) for fc in curves)

        moved_keys = 0
        moved_bones = 0
        no_key = 0
        for i, pb in enumerate(bones):
            shift = i * self.step
            if shift == 0:
                continue
            # 前缀带着闭合的引号和方括号，Cloak_1 不会误伤 Cloak_10
            prefix = 'pose.bones["%s"]' % pb.name
            hit = False
            for fc in curves:
                if not fc.data_path.startswith(prefix):
                    continue
                hit = True
                for kp in fc.keyframe_points:
                    if use_sel and not kp.select_control_point:
                        continue
                    kp.co.x += shift
                    kp.handle_left.x += shift
                    kp.handle_right.x += shift
                    moved_keys += 1
                fc.update()
            if hit:
                moved_bones += 1
            else:
                no_key += 1

        if moved_keys == 0:
            if use_sel:
                self.report({"WARNING"},
                            "这些骨骼身上没有选中的关键帧，去摄影表里把要错开的"
                            "那几帧框上，或者把「只动选中的帧」取消")
            else:
                self.report({"WARNING"},
                            "选中的骨骼身上没有关键帧，先给它们 K 上动作")
            return {"CANCELLED"}

        # update() 会把撞到同一帧的关键帧并掉，这里如实报出来
        lost = before_total - sum(len(fc.keyframe_points) for fc in curves)

        span = abs(self.step) * (len(bones) - 1)
        msg = "%d 根骨骼错开了 %d 个关键帧，首尾差 %d 帧" % (
            moved_bones, moved_keys, span)
        if use_sel:
            msg += "（只动了选中的那些）"
        elif self.only_selected:
            msg += "（没选中任何帧，整条一起错开了）"
        if no_key:
            msg += "；有 %d 根没有关键帧，跳过了" % no_key
        if lost > 0:
            self.report({"WARNING"}, msg +
                        "；有 %d 个关键帧错到了别的帧头上被并掉了，"
                        "Ctrl+Z 可以还原" % lost)
        else:
            self.report({"INFO"}, msg)
        return {"FINISHED"}


_classes = (
    POND_OT_key_offset,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)
    wm = bpy.types.WindowManager
    wm.pond_keyoff_step = bpy.props.IntProperty(
        name="步长", default=1, soft_min=-10, soft_max=10,
        description="每根骨骼比前一根晚几帧，负数往回收")
    wm.pond_keyoff_reverse = bpy.props.BoolProperty(
        name="反向", default=False,
        description="从末梢往根部传")
    wm.pond_keyoff_only_sel = bpy.props.BoolProperty(
        name="只动选中的帧", default=True,
        description="摄影表里选中了关键帧就只错开那些，一个都没选时整条一起错开")
    wm.pond_keyoff_order = bpy.props.EnumProperty(
        name="顺序",
        items=[
            ("HIERARCHY", "按层级", "顺着父子链从根排到梢"),
            ("NAME", "按名字", "按名字里的数字排"),
        ],
        default="HIERARCHY")


def unregister():
    wm = bpy.types.WindowManager
    for k in ("pond_keyoff_step", "pond_keyoff_reverse", "pond_keyoff_order",
              "pond_keyoff_only_sel"):
        if hasattr(wm, k):
            delattr(wm, k)
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
