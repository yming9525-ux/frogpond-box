# 父子级：打组/拎出/释放/选择父级（合并核心）
#
# 重要更正（合并核查发现，已更新进 合并对照清单.md 第 4 节）：
# 两项目的「父子级」工具大部分**语义不同**，并非同一功能的两种实现：
#   - Pond「所选打组」= 直接挂到激活物体下；Bekkan「到上级」= 新建空物体包裹
#   - Pond「拎出」= 保子树摘自己；Bekkan「拎出」= 孩子先释放给上级、再摘自己
#   - Pond「拎出并删除」= 删原父级链；Bekkan「拎出并删除」= 删所选物体自己
# 因此除「选择父级」（语义等价，采用 Pond 实现）外，两边 op 全部保留、忠实移植。
# Bekkan 独有 op 保留原 bl_idname（_visn / camera.*），Pond op 保留 pond.*。
# （合并自 Pond/hierarchy.py + Bekkan/STOOL_part/ParentsOps.py；
#   面板在 ui/pond/panels/hierarchy.py 与 ui/bekkan/panels.py）
import bpy


# ── 共享助手（源自 Bekkan/ParentsOps.py，core/stage.py 也引用） ──

def centro(sel):
    """所选物体的局部坐标中心"""
    return tuple(sum(o.location[i] for o in sel) / len(sel) for i in range(3))


def centro_global(sel):
    """所选物体的世界坐标中心"""
    return tuple(sum(o.matrix_world.translation[i] for o in sel) / len(sel) for i in range(3))


def get_children(obj):
    return [ob for ob in bpy.data.objects if ob.parent == obj]


def _checked_objs(op, context):
    """公共检查：无选中则报错返回 None，并尝试切回物体模式"""
    objs = context.selected_objects
    if not objs:
        op.report({'WARNING'}, "没有选中的物体")
        return None
    try:
        bpy.ops.object.mode_set()
    except Exception:
        pass
    return objs


def _in_view_layer(obj, context=None):
    """在不在当前视图层：集合被排除的物体 select_set 会抛异常。
    visible_get 对这类物体不报错(探不出来), 得直接查视图层的物体表"""
    vl = (context or bpy.context).view_layer
    return vl.objects.get(obj.name) is obj


def _release_children(obj):
    """释放 obj 的下级：有上级则转给上级，否则放到世界层级
    小眼睛藏着的子级 select_set 会静默失败, 临时点亮再藏回去;
    不在当前视图层的(集合被排除)选不了, 直接改父级兜底"""
    for ch in get_children(obj):
        if not _in_view_layer(ch):
            # 选不了就不走操作符, 直接改父级并保住世界变换
            with _Ctx(ch):
                ch.parent = obj.parent
            continue
        was_hidden = ch.hide_get()
        if was_hidden:
            ch.hide_set(False)
        try:
            ch.select_set(True)
            bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')
            if obj.parent:
                bpy.context.view_layer.objects.active = obj.parent
                bpy.ops.object.parent_no_inverse_set(keep_transform=True)
            ch.select_set(False)
        finally:
            if was_hidden:
                ch.hide_set(True)


class _Ctx:
    """改父级时保持世界矩阵不变：with _Ctx(obj): obj.parent = xxx（源自 Pond）"""

    def __init__(self, obj):
        self._obj = obj
        self._m = None

    def __enter__(self):
        self._m = self._obj.matrix_world.copy()
        return self._obj

    def __exit__(self, *a):
        self._obj.matrix_world = self._m


def _active_parent(context):
    parent = context.active_object
    children = [o for o in context.selected_objects if o != parent]
    if not parent or not children:
        return None, None
    return parent, children


# ══════════════════════════════════════════════════════════
# Pond 原版 op（忠实平移）
# ══════════════════════════════════════════════════════════

class POND_OT_group_to_parent(bpy.types.Operator):
    """把其他所选物体挂到激活物体下面（世界变换不变）"""
    bl_idname = "pond.group_to_parent"
    bl_label = "所选打组"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        p, c = _active_parent(context)
        return p is not None

    def execute(self, context):
        parent, children = _active_parent(context)
        for child in children:
            with _Ctx(child):
                child.parent = parent
        self.report({"INFO"}, f"{len(children)} 个 → 「{parent.name}」")
        return {"FINISHED"}


def _is_ancestor(maybe_ancestor, obj):
    """maybe_ancestor 是不是 obj 的祖先。挂之前得查，不然会绕成环，Blender 会炸"""
    p = obj.parent
    while p:
        if p == maybe_ancestor:
            return True
        p = p.parent
    return False


class POND_OT_join_group(bpy.types.Operator):
    """把其他所选物体加进激活物体所在的那个组，跟它做兄弟（世界变换不变）。
    跟「所选打组」的区别：那个是挂到激活物体下面，这个是挂到激活物体的父级下面，
    所以在视图里点组里随便哪个成员就行，不用去大纲里翻那个空物体
    """
    bl_idname = "pond.join_group"
    bl_label = "加入所在组"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        act = context.active_object
        if not act or not act.parent:
            return False
        return any(o != act for o in context.selected_objects)

    def execute(self, context):
        act = context.active_object
        if not act or not act.parent:
            self.report({"WARNING"}, "激活物体没有父级，它不在任何组里。"
                                     "要新建组请用「所选打组」")
            return {"CANCELLED"}
        parent = act.parent

        moved, already, looped = 0, 0, []
        for obj in context.selected_objects:
            if obj == act or obj == parent:
                continue
            if obj.parent == parent:      # 本来就在这个组里
                already += 1
                continue
            if _is_ancestor(obj, parent):  # 它是父级的祖先，挂上去会绕成环
                looped.append(obj.name)
                continue
            with _Ctx(obj):
                obj.parent = parent
            moved += 1

        if looped:
            self.report({"WARNING"},
                        "%d 个加进「%s」；%s 是这个组的上级，挂上去会绕成环，跳过了"
                        % (moved, parent.name, "、".join(looped[:3])))
        elif moved:
            tail = "，另有 %d 个本来就在组里" % already if already else ""
            self.report({"INFO"}, "%d 个 → 「%s」%s" % (moved, parent.name, tail))
        else:
            self.report({"WARNING"}, "没有可加的物体（都已经在「%s」里了）" % parent.name)
            return {"CANCELLED"}
        return {"FINISHED"}


class POND_OT_select_parents(bpy.types.Operator):
    """选中所有所选物体的直接父级（语义与 Bekkan SelectParent 等价，采用本实现）"""
    bl_idname = "pond.select_parents"
    bl_label = "选择所有父级"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        parents = {o.parent for o in context.selected_objects if o.parent}
        if not parents:
            self.report({"WARNING"}, "所选都没有父级")
            return {"CANCELLED"}
        # 先筛掉选不了的(集合被排除),够不着就别清空用户的选择
        reachable = [p for p in parents if _in_view_layer(p, context)]
        skipped = len(parents) - len(reachable)
        if not reachable:
            self.report({"ERROR"},
                        "父级都在被排除的集合里，选不了。"
                        "去大纲把那个集合的勾选打开再来")
            return {"CANCELLED"}
        bpy.ops.object.select_all(action="DESELECT")
        hidden = 0
        for p in reachable:
            if p.hide_get():          # 小眼睛藏着的选不上, 点亮才选得中
                p.hide_set(False)
                hidden += 1
            p.select_set(True)
        context.view_layer.objects.active = reachable[0]
        msg = []
        if skipped:
            msg.append("%d 个父级在被排除的集合里，跳过了" % skipped)
        if hidden:
            msg.append("%d 个父级原本藏着，帮你点亮了" % hidden)
        if msg:
            self.report({"WARNING"}, "，".join(msg))
        return {"FINISHED"}


class POND_OT_extract(bpy.types.Operator):
    """把所选物体连同子树整体拎出所有层级，回到场景根"""
    bl_idname = "pond.extract"
    bl_label = "拎出(带全家)"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return any(o.parent for o in context.selected_objects)

    def execute(self, context):
        for obj in context.selected_objects:
            if obj.parent:
                with _Ctx(obj):
                    obj.parent = None
        return {"FINISHED"}


# ══════════════════════════════════════════════════════════
# Bekkan 原版 op（忠实平移，保留原 bl_idname）
# ══════════════════════════════════════════════════════════

class SoloPick(bpy.types.Operator):
    # 断开所选物体的所有上下级关系，捡出来放在世界层级，下级归更上一层上级管。
    bl_idname = "object.solo_pick_visn"
    bl_label = "拎出"
    bl_description = "断开所有选择物体的上下级"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        objs = _checked_objs(self, context)
        if objs is None:
            return {'CANCELLED'}
        for obj in objs:
            obj.select_set(False)
        for obj in objs:
            _release_children(obj)
        for obj in objs:
            obj.select_set(True)
            bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')
            obj.select_set(False)
        for obj in objs:
            obj.select_set(True)
        return {'FINISHED'}


_classes = (
    # Pond
    POND_OT_group_to_parent,
    POND_OT_join_group,
    POND_OT_select_parents,
    POND_OT_extract,
    # 拎出核心（源自别馆 SoloPick，池塘「单个拎出」使用）
    SoloPick,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
