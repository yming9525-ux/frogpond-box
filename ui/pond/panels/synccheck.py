# 视图渲染同步面板（逻辑在 core/synccheck.py）
import bpy

from ..prefs import module_enabled
from ....core.synccheck import _CATS, _GRP_COL, _collapsed


class POND_PT_synccheck(bpy.types.Panel):
    bl_label = "视图渲染同步"
    bl_idname = "POND_PT_synccheck"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "池塘"
    bl_parent_id = "POND_PT_sec_look"
    bl_order = 2
    bl_options = {"DEFAULT_CLOSED"}
    poll = module_enabled("show_synccheck")

    def draw(self, context):
        wm = context.window_manager
        layout = self.layout
        layout.operator("pond.sync_scan", icon="VIEWZOOM")

        if not wm.pond_sync_scanned:
            return
        items = wm.pond_sync_items
        if not items:
            layout.label(text="视图和渲染完全一致", icon="CHECKMARK")
            return

        # 先分大类（模型 / 修改器），类里再按集合分组（保持扫描顺序，「集合本身」垫底）
        cats = {c: ([], {}) for c, _ in _CATS}
        for i, it in enumerate(items):
            order, groups = cats["MOD" if it.kind == "MOD" else "MODEL"]
            if it.group not in groups:
                groups[it.group] = []
                order.append(it.group)
            groups[it.group].append(i)

        for cat, cat_name in _CATS:
            order, groups = cats[cat]
            if not order:
                continue
            if _GRP_COL in order:
                order.remove(_GRP_COL)
                order.append(_GRP_COL)
            total = sum(len(v) for v in groups.values())
            cat_box = layout.box()
            cat_fold = f"{cat}|" in _collapsed
            head = cat_box.row(align=True)
            op = head.operator("pond.sync_fold", text="",
                               icon="TRIA_RIGHT" if cat_fold else "TRIA_DOWN",
                               emboss=False)
            op.group = f"{cat}|"
            head.label(text=f"{cat_name} ({total})",
                       icon="MODIFIER" if cat == "MOD" else "OBJECT_DATA")
            self._align_buttons(head, cat, "")
            if cat_fold:
                continue

            for gname in order:
                idxs = groups[gname]
                key = f"{cat}|{gname}"
                box = cat_box.box()
                head = box.row(align=True)
                fold = key in _collapsed
                op = head.operator("pond.sync_fold", text="",
                                   icon="TRIA_RIGHT" if fold else "TRIA_DOWN",
                                   emboss=False)
                op.group = key
                head.label(text=f"{gname} ({len(idxs)})",
                           icon="OUTLINER_COLLECTION" if gname != _GRP_COL else "GROUP")
                self._align_buttons(head, cat, gname)
                if fold:
                    continue
                for i in idxs:
                    it = items[i]
                    row = box.row(align=True)
                    op = row.operator("pond.sync_select", text=it.label,
                                      icon="RESTRICT_SELECT_OFF", emboss=False)
                    op.index = i
                    row.label(text=it.detail)

        col = layout.column(align=True)
        op = col.operator("pond.sync_apply", text="全部：以渲染为准",
                          icon="RESTRICT_VIEW_OFF")
        op.direction = "TO_RENDER"
        op.group = ""
        op.category = ""
        op = col.operator("pond.sync_apply", text="全部：以视图为准",
                          icon="RESTRICT_RENDER_OFF")
        op.direction = "TO_VIEWPORT"
        op.group = ""
        op.category = ""
        col.label(text="组头小按钮=只对齐那一组", icon="INFO")

    @staticmethod
    def _align_buttons(row, cat, group):
        for icon, direction in (("RESTRICT_VIEW_OFF", "TO_RENDER"),
                                ("RESTRICT_RENDER_OFF", "TO_VIEWPORT")):
            op = row.operator("pond.sync_apply", text="", icon=icon)
            op.direction = direction
            op.category = cat
            op.group = group


_classes = (
    POND_PT_synccheck,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
