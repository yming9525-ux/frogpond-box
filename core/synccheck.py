# 视图渲染同步：揪出「视图可见性(小眼睛/临时隐藏)」和「渲染禁用」不一致的物体/集合/修改器
# v2: 只看视图(小眼睛) vs 渲染(显示器那层不管,蛙灾定的);按集合分组收展;可只对齐某一组
# （合并自 Pond/synccheck.py：逻辑层；面板在 ui/pond/panels/synccheck.py）
import bpy

_GRP_COL = "集合本身"
_CATS = (("MODEL", "模型"), ("MOD", "修改器"))   # 面板两大类：物体+集合 / 修改器
_collapsed = set()      # 收起的组（会话内记住），键=「大类|组名」
_undo_stack = []        # 对齐撤回栈: 每层=[(kind,name,extra,视口原值,渲染原值)],最多留10层


class PondSyncItem(bpy.types.PropertyGroup):
    kind: bpy.props.StringProperty()        # OBJ / COL / MOD
    obj_name: bpy.props.StringProperty()    # 物体名（COL 时=集合名）
    extra: bpy.props.StringProperty()       # MOD 时=修改器名
    label: bpy.props.StringProperty()       # 面板显示
    detail: bpy.props.StringProperty()      # 视口x 渲染√ 这类说明
    group: bpy.props.StringProperty()       # 所属集合（分组用）


def _fmt(viewport_on, render_on):
    def mark(b):
        return "开" if b else "关"
    return f"视图{mark(viewport_on)} / 渲染{mark(render_on)}"


def _lc_map(view_layer):
    """集合 -> 它在当前视图层里的 layer_collection（视图可见性住这儿）"""
    out = {}

    def walk(lc):
        for ch in lc.children:
            if not ch.exclude:
                out.setdefault(ch.collection, ch)
            walk(ch)

    walk(view_layer.layer_collection)
    return out


def _cat_of(kind):
    return "MOD" if kind == "MOD" else "MODEL"


def _obj_group(o):
    return o.users_collection[0].name if o.users_collection else "场景根"


def _scan(context):
    """返回 [(kind, obj_name, extra, label, detail, group)]"""
    found = []
    for o in context.scene.objects:
        try:
            eye_off = o.hide_get()
        except RuntimeError:
            continue        # 不在当前视图层，跳过
        if eye_off != o.hide_render:
            found.append(("OBJ", o.name, "", o.name,
                          _fmt(not eye_off, not o.hide_render), _obj_group(o)))
        for m in o.modifiers:
            if m.show_viewport != m.show_render:
                found.append(("MOD", o.name, m.name, f"{o.name} ▸ {m.name}",
                              _fmt(m.show_viewport, m.show_render),
                              _obj_group(o)))
    for col, lc in _lc_map(context.view_layer).items():
        if lc.hide_viewport != col.hide_render:
            found.append(("COL", col.name, "", f"[集合] {col.name}",
                          _fmt(not lc.hide_viewport, not col.hide_render), _GRP_COL))
    return found


def _fill_items(context):
    wm = context.window_manager
    wm.pond_sync_items.clear()
    for kind, obj_name, extra, label, detail, group in _scan(context):
        it = wm.pond_sync_items.add()
        it.kind, it.obj_name, it.extra = kind, obj_name, extra
        it.label, it.detail, it.group = label, detail, group
    wm.pond_sync_scanned = True
    return len(wm.pond_sync_items)


from bpy.app.handlers import persistent


@persistent
def _resync_after_undo(_scene, _dg=None):
    """她按 Ctrl+Z 后列表自动重扫，不用再点开始体检"""
    try:
        ctx = bpy.context
        if getattr(ctx.window_manager, "pond_sync_scanned", False):
            _fill_items(ctx)
    except Exception:
        pass


class POND_OT_sync_scan(bpy.types.Operator):
    """扫描全场景：物体和集合的视图可见性、修改器开关是否与渲染一致"""
    bl_idname = "pond.sync_scan"
    bl_label = "开始体检"

    def execute(self, context):
        n = _fill_items(context)
        self.report({"INFO"}, f"发现 {n} 处不同步" if n else "干干净净，视图和渲染完全一致")
        return {"FINISHED"}


class POND_OT_sync_fold(bpy.types.Operator):
    """收起/展开这一组的问题清单"""
    bl_idname = "pond.sync_fold"
    bl_label = "收展"

    group: bpy.props.StringProperty()   # 「大类|组名」

    def execute(self, context):
        if self.group in _collapsed:
            _collapsed.discard(self.group)
        else:
            _collapsed.add(self.group)
        return {"FINISHED"}


class POND_OT_sync_select(bpy.types.Operator):
    """在场景里选中这一条对应的物体"""
    bl_idname = "pond.sync_select"
    bl_label = "跳选"

    index: bpy.props.IntProperty()

    def execute(self, context):
        wm = context.window_manager
        if self.index >= len(wm.pond_sync_items):
            return {"CANCELLED"}
        it = wm.pond_sync_items[self.index]
        if it.kind == "COL":
            self.report({"INFO"}, "集合请在大纲里找，场景里选不了")
            return {"CANCELLED"}
        obj = context.scene.objects.get(it.obj_name)
        if not obj:
            self.report({"WARNING"}, "物体已经不在了，重新体检一下")
            return {"CANCELLED"}
        bpy.ops.object.select_all(action="DESELECT")
        try:
            obj.select_set(True)
            context.view_layer.objects.active = obj
        except RuntimeError:
            self.report({"WARNING"}, f"「{obj.name}」在视口里被禁选了")
        return {"FINISHED"}


class POND_OT_sync_apply(bpy.types.Operator):
    """把不同步的项对齐（category 选大类：模型/修改器，留空=两类都算；
    group 留空=全场景，填组名=只对齐这一组）"""
    bl_idname = "pond.sync_apply"
    bl_label = "一键对齐"
    bl_options = {"REGISTER", "UNDO"}

    direction: bpy.props.EnumProperty(items=[
        ("TO_RENDER", "以渲染为准", "以渲染开关为准，改视图可见性"),
        ("TO_VIEWPORT", "以视图为准", "以视图可见性为准，改渲染开关"),
    ])
    group: bpy.props.StringProperty(default="")
    category: bpy.props.StringProperty(default="")

    def execute(self, context):
        to_render = self.direction == "TO_RENDER"
        lc_by_col = {c.name: lc for c, lc in _lc_map(context.view_layer).items()}
        n = 0
        changed = []
        for kind, obj_name, extra, _label, _detail, group in _scan(context):
            if self.category and _cat_of(kind) != self.category:
                continue
            if self.group and group != self.group:
                continue
            if kind == "OBJ":
                o = context.scene.objects.get(obj_name)
                if not o:
                    continue
                try:
                    changed.append(("OBJ", obj_name, "", o.hide_get(), o.hide_render))
                    if to_render:
                        o.hide_set(o.hide_render)
                    else:
                        o.hide_render = o.hide_get()
                    n += 1
                except RuntimeError:
                    changed.pop()
            elif kind == "MOD":
                o = context.scene.objects.get(obj_name)
                m = o.modifiers.get(extra) if o else None
                if not m:
                    continue
                changed.append(("MOD", obj_name, extra, m.show_viewport, m.show_render))
                if to_render:
                    m.show_viewport = m.show_render
                else:
                    m.show_render = m.show_viewport
                n += 1
            elif kind == "COL":
                col = bpy.data.collections.get(obj_name)
                lc = lc_by_col.get(obj_name)
                if not col or not lc:
                    continue
                changed.append(("COL", obj_name, "", lc.hide_viewport, col.hide_render))
                if to_render:
                    lc.hide_viewport = col.hide_render
                else:
                    col.hide_render = lc.hide_viewport
                n += 1
        if changed:
            _undo_stack.append(changed)
            del _undo_stack[:-10]
        bpy.ops.pond.sync_scan()
        cat = dict(_CATS).get(self.category, "")
        where = "".join(f"「{w}」" for w in (cat, self.group) if w)
        self.report({"INFO"}, f"对齐了{where} {n} 处")
        return {"FINISHED"}


class POND_OT_sync_undo(bpy.types.Operator):
    """撤回上一次对齐（只回滚那次改过的开关），列表同步刷新"""
    bl_idname = "pond.sync_undo"
    bl_label = "撤回上次对齐"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return bool(_undo_stack)

    def execute(self, context):
        entries = _undo_stack.pop()
        lc_by_col = {c.name: lc for c, lc in _lc_map(context.view_layer).items()}
        n = 0
        for kind, name, extra, prev_vp, prev_rd in entries:
            if kind == "OBJ":
                o = context.scene.objects.get(name)
                if not o:
                    continue
                try:
                    o.hide_set(prev_vp)
                except RuntimeError:
                    continue
                o.hide_render = prev_rd
                n += 1
            elif kind == "MOD":
                o = context.scene.objects.get(name)
                m = o.modifiers.get(extra) if o else None
                if not m:
                    continue
                m.show_viewport = prev_vp
                m.show_render = prev_rd
                n += 1
            elif kind == "COL":
                col = bpy.data.collections.get(name)
                lc = lc_by_col.get(name)
                if not col or not lc:
                    continue
                lc.hide_viewport = prev_vp
                col.hide_render = prev_rd
                n += 1
        _fill_items(context)
        self.report({"INFO"}, f"撤回了 {n} 处")
        return {"FINISHED"}


_classes = (
    PondSyncItem,
    POND_OT_sync_scan,
    POND_OT_sync_fold,
    POND_OT_sync_select,
    POND_OT_sync_apply,
    POND_OT_sync_undo,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)
    bpy.types.WindowManager.pond_sync_items = bpy.props.CollectionProperty(type=PondSyncItem)
    bpy.types.WindowManager.pond_sync_scanned = bpy.props.BoolProperty(default=False)
    bpy.types.WindowManager.pond_sync_tab = bpy.props.EnumProperty(
        name="分类", items=[(c, n, "") for c, n in _CATS], default="MODEL")
    for hl in (bpy.app.handlers.undo_post, bpy.app.handlers.redo_post):
        if _resync_after_undo not in hl:
            hl.append(_resync_after_undo)


def unregister():
    for hl in (bpy.app.handlers.undo_post, bpy.app.handlers.redo_post):
        if _resync_after_undo in hl:
            hl.remove(_resync_after_undo)
    del bpy.types.WindowManager.pond_sync_tab
    del bpy.types.WindowManager.pond_sync_scanned
    del bpy.types.WindowManager.pond_sync_items
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
