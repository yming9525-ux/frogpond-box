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


def _release_children(obj):
    """释放 obj 的下级：有上级则转给上级，否则放到世界层级"""
    for ch in get_children(obj):
        ch.select_set(True)
        bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')
        if obj.parent:
            bpy.context.view_layer.objects.active = obj.parent
            bpy.ops.object.parent_no_inverse_set(keep_transform=True)
        ch.select_set(False)


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
        bpy.ops.object.select_all(action="DESELECT")
        for p in parents:
            p.select_set(True)
        context.view_layer.objects.active = next(iter(parents))
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
