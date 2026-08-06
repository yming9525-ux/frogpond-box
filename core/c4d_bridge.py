# C4D 互导：集合转 Empty 组长导 FBX（C4D 只认父子层级不认集合）
# 导出全程在当前数据上临时打组、导完还原，不动工程本身
# 材质清单：Principled 槽位 → JSON + 贴图包，给 C4D 侧重建 Octane 材质用
# Alembic 顶点缓存：绑骨角色动画去 C4D 渲染用，逐帧网格所见即所得
# （合并自 Pond/c4d_bridge.py：逻辑层；面板在 ui/pond/panels/c4d_bridge.py）
import json
import os
import shutil
import time
import bpy

from bpy_extras.io_utils import ExportHelper


def _build_group_empties(scene):
    """集合结构 → 临时 Empty 组长（C4D 只认父子层级不认集合）。
    返回 (created, moved) 给 _restore_group_empties 还原"""
    created = []   # 临时组长 Empty
    moved = []     # (obj, 原parent, 原世界矩阵)

    def build(col, parent_empty):
        empty = bpy.data.objects.new(col.name, None)
        scene.collection.objects.link(empty)
        created.append(empty)
        if parent_empty:
            empty.parent = parent_empty
        for o in col.objects:
            if o.parent is None:  # 有父级的跟着父级走，不重复挂
                moved.append((o, o.parent, o.matrix_world.copy()))
                o.parent = empty
                o.matrix_world = moved[-1][2]
        for sub in col.children:
            build(sub, empty)

    for col in scene.collection.children:
        build(col, None)
    return created, moved


def _restore_group_empties(created, moved):
    """还原现场：先还对象，再删临时组长"""
    for o, parent, mw in moved:
        o.parent = parent
        o.matrix_world = mw
    for e in created:
        bpy.data.objects.remove(e)


class POND_OT_export_c4d(bpy.types.Operator, ExportHelper):
    """按集合结构打组导出 FBX 给 C4D（贴图一并打包）"""
    bl_idname = "pond.export_c4d"
    bl_label = "导出 C4D 分组 FBX"
    filename_ext = ".fbx"
    filter_glob: bpy.props.StringProperty(default="*.fbx", options={"HIDDEN"})

    def invoke(self, context, event):
        blend = bpy.path.basename(bpy.data.filepath)
        stem = os.path.splitext(blend)[0] if blend else "未命名"
        self.filepath = f"{stem}_分组.fbx"
        return super().invoke(context, event)

    def execute(self, context):
        scene = context.scene
        created, moved = [], []
        try:
            created, moved = _build_group_empties(scene)
            bpy.ops.export_scene.fbx(
                filepath=self.filepath,
                use_selection=False,
                object_types={"EMPTY", "MESH", "ARMATURE", "LIGHT", "CAMERA", "OTHER"},
                path_mode="COPY",
                embed_textures=False,
            )
        except Exception as e:
            self.report({"ERROR"}, f"导出失败：{e}")
            return {"CANCELLED"}
        finally:
            _restore_group_empties(created, moved)

        self.report({"INFO"}, f"导出完成：{self.filepath}")
        return {"FINISHED"}


# abc 里有意义的类型：能出几何的 + 摄像机；其余（灯光/骨架/空物体…）只会变成空 Null
_ABC_KEEP_TYPES = {"MESH", "CURVE", "SURFACE", "META", "FONT",
                   "CURVES", "POINTCLOUD", "VOLUME", "CAMERA"}


class POND_OT_export_c4d_abc(bpy.types.Operator, ExportHelper):
    """导出 Alembic 顶点缓存给 C4D 渲染：绑骨/约束/物理全烘成逐帧网格，摄像机一起走。
到那边不可再编辑，要继续调动作的角色别走这条"""
    bl_idname = "pond.export_c4d_abc"
    bl_label = "导出 Alembic 顶点缓存"
    filename_ext = ".abc"
    filter_glob: bpy.props.StringProperty(default="*.abc", options={"HIDDEN"})

    only_selected: bpy.props.BoolProperty(name="仅选中物体", default=False)
    flatten: bpy.props.BoolProperty(
        name="压平层级（不要任何组）", default=False,
        description="默认保留分组：集合和父级会变成 C4D 里的组长 Null。"
                    "勾上则全部平铺，一个空节点都不留")
    frame_start: bpy.props.IntProperty(name="起始帧", default=1)
    frame_end: bpy.props.IntProperty(name="结束帧", default=250)
    samples: bpy.props.IntProperty(
        name="每帧采样数", default=1, min=1, max=8,
        description="C4D/Octane 里要运动模糊就开 2 以上")
    apply_subdiv: bpy.props.BoolProperty(
        name="烘进细分", default=True,
        description="按渲染设置把细分烘进网格，所见即所得；嫌文件大就关掉，去 C4D 再细分")
    global_scale: bpy.props.FloatProperty(
        name="缩放", default=100.0,
        description="C4D 按厘米读数值，100 = 米转厘米，和分组 FBX 的尺寸一致")

    def invoke(self, context, event):
        blend = bpy.path.basename(bpy.data.filepath)
        stem = os.path.splitext(blend)[0] if blend else "未命名"
        self.filepath = f"{stem}_顶点缓存.abc"
        self.frame_start = context.scene.frame_start
        self.frame_end = context.scene.frame_end
        return super().invoke(context, event)

    def execute(self, context):
        scene = context.scene
        # 所见即所得：几何只导视图里看得见的；摄像机 = 可见的 + 当前激活相机（藏着也带）
        pool = context.selected_objects if self.only_selected else list(scene.objects)

        def vis(o):
            try:
                return o.visible_get()
            except RuntimeError:
                return False

        targets = []
        for o in pool:
            if o.type not in _ABC_KEEP_TYPES:
                continue
            if o.type == "CAMERA":
                if vis(o) or o == scene.camera:
                    targets.append(o)
            elif vis(o):
                targets.append(o)
        if not targets:
            self.report({"ERROR"}, "没有可导出的几何或摄像机")
            return {"CANCELLED"}

        kwargs = dict(
            filepath=self.filepath,
            start=self.frame_start,
            end=self.frame_end,
            xsamples=self.samples,
            gsamples=self.samples,
            selected=True,
            visible_objects_only=False,
            flatten=self.flatten,
            uvs=True,
            normals=True,
            face_sets=True,   # 材质分面组带过去，C4D 里按材质名对回
            apply_subdiv=self.apply_subdiv,
            use_instancing=True,
            global_scale=self.global_scale,
            evaluation_mode="RENDER",
        )
        # 跨版本保险：参数名有变动就丢弃不识别的，别整个导出挂掉
        avail = bpy.ops.wm.alembic_export.get_rna_type().properties.keys()
        kwargs = {k: v for k, v in kwargs.items() if k in avail}

        prev_sel = list(context.selected_objects)
        prev_active = context.view_layer.objects.active

        # 目标必须可见可选、且渲染评估里能逐帧采样：
        # 视图/渲染/集合的隐藏全部临时解除，导完还原
        obj_restore = []
        for o in targets:
            try:
                hidden = o.hide_get()
            except RuntimeError:
                hidden = False
            obj_restore.append((o, hidden, o.hide_viewport, o.hide_render))
            try:
                o.hide_set(False)
            except RuntimeError:
                pass
            o.hide_viewport = False
            o.hide_render = False
        col_restore = [(c, c.hide_viewport, c.hide_render) for c in bpy.data.collections]
        for c, _, _ in col_restore:
            c.hide_viewport = False
            c.hide_render = False
        context.view_layer.update()

        # 保留分组时：集合转临时 Empty 组长（导出器会把父链写成组节点）
        created, moved = [], []
        bridged = []   # 父链被骨架等不可导类型卡断的对象，临时桥到组长
        if not self.flatten:
            created, moved = _build_group_empties(scene)
            # 绑骨角色的 mesh 挂在 armature 下，armature 会被 abc 导出器
            # 整个吞掉，父链在它那里断，mesh 平铺到根级。
            # Empty 父链是安全的（导出器必写 xform），只有骨架这类才算断点。
            # 断链对象桥到断点上方最近的安全祖先（Empty/组长/其他导出对象），
            # 世界矩阵不动；abc 逐帧采样相对变换，对象级动画不丢。
            created_set = set(created)
            target_set = set(targets)
            boned = 0
            for o in targets:
                # 骨骼挂载的对象(相机摇臂等)运动全在父级骨骼上——
                # 桥接会把它的世界矩阵冻在当前帧,动画就没了。
                # 不桥,让它平铺到根级:导出器对无父级对象逐帧写世界矩阵,动画不丢
                if o.parent_type == "BONE":
                    boned += 1
                    continue
                anc = o.parent
                crossed_bad = False
                dest = None
                while anc is not None:
                    if anc in created_set or anc in target_set or anc.type == "EMPTY":
                        dest = anc
                        break
                    crossed_bad = True   # armature/lattice 等会被导出器吞的
                    anc = anc.parent
                if crossed_bad and dest is not None:
                    bridged.append((o, o.parent, o.matrix_world.copy()))
                    o.parent = dest
                    o.matrix_world = bridged[-1][2]
            self._boned = boned

        selected_ok = []
        unreachable = 0
        try:
            for o in context.view_layer.objects:
                try:
                    o.select_set(False)
                except RuntimeError:
                    pass
            for o in targets:
                try:
                    o.select_set(True)
                    selected_ok.append(o)
                except RuntimeError:
                    unreachable += 1  # 不在视图层里（被排除的集合），选不中
            bpy.ops.wm.alembic_export(**kwargs)
        except Exception as e:
            self.report({"ERROR"}, f"导出失败：{e}")
            return {"CANCELLED"}
        finally:
            for o in context.view_layer.objects:
                try:
                    o.select_set(False)
                except RuntimeError:
                    pass
            for o in prev_sel:
                try:
                    o.select_set(True)
                except RuntimeError:
                    pass
            context.view_layer.objects.active = prev_active
            for o, parent, mw in bridged:   # 先拆桥，再还组长
                o.parent = parent
                o.matrix_world = mw
            _restore_group_empties(created, moved)
            for c, hv, hr in col_restore:
                c.hide_viewport = hv
                c.hide_render = hr
            for o, hs, hv, hr in obj_restore:
                try:
                    o.hide_set(hs)
                except RuntimeError:
                    pass
                o.hide_viewport = hv
                o.hide_render = hr

        n_cam = sum(1 for o in selected_ok if o.type == "CAMERA")
        n_geo = len(selected_ok) - n_cam
        # abc7 是版本印记：提示里看不到它 = Blender 加载的还是旧代码
        msg = f"[abc7] 导出完成：几何 {n_geo}、摄像机 {n_cam}，{self.frame_start}-{self.frame_end} 帧"
        if bridged:
            msg += f"；{len(bridged)} 个对象的断链父级已桥到组长"
        if getattr(self, "_boned", 0):
            msg += f"；{self._boned} 个骨骼挂载对象平铺到根级(保动画)"
        warn = False
        if n_cam == 0 and any(o.type == "CAMERA" for o in scene.objects):
            msg += "；场景里有摄像机但没导上（看看它是否在被排除的集合里）"
            warn = True
        if unreachable:
            msg += f"；{unreachable} 个对象在被排除的集合里没导上"
            warn = True
        self.report({"WARNING" if warn else "INFO"}, msg)
        return {"FINISHED"}


class POND_OT_import_c4d_restore(bpy.types.Operator):
    """把选中的 Empty 组长还原成 Collection：只转选中的这一层，
里面的子 Empty 组保持原样（想一起转就把它们也选上）"""
    bl_idname = "pond.import_c4d_restore"
    bl_label = "Empty 组还原成集合"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return any(o.type == "EMPTY" and o.children for o in context.selected_objects)

    def execute(self, context):
        roots = [o for o in context.selected_objects if o.type == "EMPTY" and o.children]
        # 外层的先转，一起选中的子组随后自然嵌进外层新集合
        def depth(o):
            d = 0
            p = o.parent
            while p:
                d += 1
                p = p.parent
            return d
        roots.sort(key=depth)
        n = 0

        def move_subtree(o, col):
            for uc in list(o.users_collection):
                uc.objects.unlink(o)
            col.objects.link(o)
            for c in o.children:
                move_subtree(c, col)

        for root in roots:
            parent_col = root.users_collection[0] if root.users_collection \
                else context.scene.collection
            col = bpy.data.collections.new(root.name)
            parent_col.children.link(col)
            n += 1
            for child in list(root.children):
                mw = child.matrix_world.copy()
                child.parent = None
                child.matrix_world = mw
                move_subtree(child, col)
            bpy.data.objects.remove(root)

        self.report({"INFO"}, f"还原了 {n} 个集合")
        return {"FINISHED"}


# ── 材质清单导出（Blender Principled → Octane 翻译层的 B 侧） ──

# 清单键 → Principled 输入名（兼容 4.x 前后的改名）
_SLOTS = (
    ("base_color", ("Base Color",)),
    ("metallic", ("Metallic",)),
    ("roughness", ("Roughness",)),
    ("ior", ("IOR",)),
    ("alpha", ("Alpha",)),
    ("transmission", ("Transmission Weight", "Transmission")),
    ("emission_color", ("Emission Color", "Emission")),
    ("emission_strength", ("Emission Strength",)),
    ("normal", ("Normal",)),
)
# 允许穿透的颜色处理节点：往上游继续找贴图
_PASSTHROUGH = {"NORMAL_MAP", "MIX", "MIX_RGB", "HUE_SAT", "BRIGHTCONTRAST",
                "CURVE_RGB", "GAMMA", "INVERT", "SEPARATE_COLOR", "SEPCOLOR"}


def _upstream_image(socket, depth=0):
    """顺着链接往上找图像纹理，穿过常见的颜色处理节点"""
    if not socket or not socket.links or depth > 5:
        return None
    node = socket.links[0].from_node
    if node.type == "TEX_IMAGE":
        return node.image
    if node.type in _PASSTHROUGH:
        for inp in node.inputs:
            img = _upstream_image(inp, depth + 1)
            if img:
                return img
    return None


def _slot_entry(inp, textures):
    """一个槽位 → {'tex': 相对路径} / {'value': ...} / {'procedural': 节点类型}"""
    if inp.links:
        img = _upstream_image(inp)
        if img is not None:
            return {"tex": textures.claim(img)}
        return {"procedural": inp.links[0].from_node.type}
    v = inp.default_value
    try:
        return {"value": [round(x, 5) for x in v]}
    except TypeError:
        return {"value": round(float(v), 5)}


class _TextureBag:
    """把用到的贴图收进 textures/，同名去重"""

    def __init__(self, outdir):
        self.dir = os.path.join(outdir, "textures")
        self.claimed = {}   # image.name -> 相对路径
        self.jobs = {}      # 目标绝对路径 -> image
        self.taken = set()

    def claim(self, img):
        if img.name in self.claimed:
            return self.claimed[img.name]
        src = bpy.path.abspath(img.filepath) if img.filepath else ""
        base = os.path.basename(src) if src else img.name + ".png"
        name = base
        n = 1
        while name in self.taken:
            name = f"{os.path.splitext(base)[0]}_{n}{os.path.splitext(base)[1]}"
            n += 1
        self.taken.add(name)
        rel = "textures/" + name
        self.claimed[img.name] = rel
        self.jobs[os.path.join(self.dir, name)] = (img, src)
        return rel

    def flush(self):
        copied, baked, missing = 0, 0, []
        if self.jobs:
            os.makedirs(self.dir, exist_ok=True)
        for dest, (img, src) in self.jobs.items():
            if src and os.path.isfile(src):
                shutil.copy2(src, dest)
                copied += 1
            elif img.packed_file or img.has_data:
                try:  # 打包/生成的图落一份盘
                    img.save_render(dest)
                    baked += 1
                except Exception:
                    missing.append(img.name)
            else:
                missing.append(img.name)
        return copied, baked, missing


class POND_OT_export_mat_manifest(bpy.types.Operator, ExportHelper):
    """导出材质槽位清单 JSON + 贴图包，给 C4D 侧重建 Octane 材质"""
    bl_idname = "pond.export_mat_manifest"
    bl_label = "导出材质清单"
    filename_ext = ".json"
    filter_glob: bpy.props.StringProperty(default="*.json", options={"HIDDEN"})
    only_selected: bpy.props.BoolProperty(name="仅选中物体", default=False)

    def invoke(self, context, event):
        blend = bpy.path.basename(bpy.data.filepath)
        stem = os.path.splitext(blend)[0] if blend else "未命名"
        self.filepath = f"{stem}_材质清单.json"
        return super().invoke(context, event)

    def execute(self, context):
        objs = context.selected_objects if self.only_selected else context.scene.objects
        outdir = os.path.dirname(self.filepath)
        textures = _TextureBag(outdir)
        materials, objects, procedural = {}, {}, {}

        for obj in objs:
            mats = [s.material for s in getattr(obj, "material_slots", []) if s.material]
            if mats:
                objects[obj.name] = [m.name for m in mats]
            for mat in mats:
                if mat.name in materials:
                    continue
                entry = {}
                bsdf = None
                if mat.use_nodes:
                    bsdf = next((n for n in mat.node_tree.nodes
                                 if n.type == "BSDF_PRINCIPLED"), None)
                if bsdf is None:
                    entry["note"] = "无Principled节点,只给了漫射色"
                    entry["base_color"] = {"value": list(mat.diffuse_color)}
                else:
                    for key, names in _SLOTS:
                        inp = next((bsdf.inputs[n] for n in names if n in bsdf.inputs), None)
                        if inp is None:
                            continue
                        if key == "normal" and not inp.links:
                            continue  # 法线没接东西就不记
                        entry[key] = _slot_entry(inp, textures)
                    # 置换走材质输出节点
                    out_node = next((n for n in mat.node_tree.nodes
                                     if n.type == "OUTPUT_MATERIAL" and n.is_active_output), None)
                    if out_node and out_node.inputs["Displacement"].links:
                        img = _upstream_image(out_node.inputs["Displacement"])
                        if img:
                            entry["displacement"] = {"tex": textures.claim(img)}
                bad = [k for k, v in entry.items()
                       if isinstance(v, dict) and "procedural" in v]
                if bad:
                    procedural[mat.name] = bad
                materials[mat.name] = entry

        copied, baked, missing = textures.flush()
        manifest = {
            "source": bpy.path.basename(bpy.data.filepath) or "未保存",
            "exported": time.strftime("%Y-%m-%d %H:%M"),
            "materials": materials,
            "objects": objects,
            "procedural_slots": procedural,
            "missing_images": missing,
        }
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=1)

        msg = f"{len(materials)} 材质 / 贴图复制{copied} 落盘{baked}"
        if procedural:
            msg += f" / {len(procedural)} 个材质有程序化槽位待烘焙"
        if missing:
            msg += f" / {len(missing)} 张图丢失"
        self.report({"WARNING" if (procedural or missing) else "INFO"}, msg)
        return {"FINISHED"}


# 一条龙生成的 C4D 侧重建脚本模板。Octane ID 来自 I:\Shoal\c4d_scripts\octane_material_ids.md 实测表
_C4D_REBUILD_TEMPLATE = '''# -*- coding: utf-8 -*-
# {stem} · Octane 材质一键重建(池塘一条龙自动生成)
# 用法: C4D 导入 {stem}_c4d.abc 后, 脚本管理器载入本文件执行
import c4d
import json
import os

MANIFEST = r"{manifest}"
OC_MATERIAL = 1029501
OC_IMAGETEX = 1029508
TEX_PATH_ID = 1100
LINKS = {{"basecolor": 2517, "roughness": 2533, "normal": 2542,
         "alpha": 2545, "emission": 2557}}
# metallic 槽位实测表标"待定", 不自动接, 结尾弹窗提示手动


def main():
    doc = c4d.documents.GetActiveDocument()
    if not os.path.exists(MANIFEST):
        c4d.gui.MessageDialog("找不到清单:\\n" + MANIFEST)
        return
    with open(MANIFEST, "r", encoding="utf-8") as f:
        data = json.load(f)
    tex_dir = os.path.join(os.path.dirname(MANIFEST), data.get("textures_dir", "textures_c4d"))
    made, skipped_metal, missing = [], [], []
    doc.StartUndo()
    existing = {{m.GetName(): m for m in doc.GetMaterials()}}
    for mat_name, channels in data.get("materials", {{}}).items():
        if mat_name in existing:
            continue
        mat = c4d.BaseMaterial(OC_MATERIAL)
        mat.SetName(mat_name)
        for key, spec in channels.items():
            if "tex" not in spec:
                continue
            path = os.path.join(tex_dir, spec["tex"])
            if not os.path.exists(path):
                missing.append(mat_name + " : " + spec["tex"])
                continue
            if key == "metallic":
                skipped_metal.append(mat_name)
                continue
            if key in LINKS:
                sh = c4d.BaseShader(OC_IMAGETEX)
                sh[TEX_PATH_ID] = path
                mat.InsertShader(sh)
                mat[LINKS[key]] = sh
        doc.InsertMaterial(mat)
        doc.AddUndo(c4d.UNDOTYPE_NEWOBJ, mat)
        made.append(mat_name)
    # 按对象名把材质赋上去, 多材质对象用同名选集做限制
    mat_by_name = {{m.GetName(): m for m in doc.GetMaterials()}}
    obj_map = data.get("objects", {{}})

    def walk(op):
        while op:
            yield op
            if op.GetDown():
                for x in walk(op.GetDown()):
                    yield x
            op = op.GetNext()

    assigned, no_obj = 0, set(obj_map.keys())
    for op in walk(doc.GetFirstObject()):
        mats = obj_map.get(op.GetName())
        if not mats:
            continue
        no_obj.discard(op.GetName())
        existing_tags = set()
        sel_names = set()
        for t in op.GetTags():
            if t.GetType() == c4d.Ttexture and t.GetMaterial():
                existing_tags.add(t.GetMaterial().GetName())
            elif t.GetType() == c4d.Tpolygonselection:
                sel_names.add(t.GetName())
        for mn in mats:
            if mn in existing_tags:
                continue
            mat = mat_by_name.get(mn)
            if not mat:
                continue
            tag = op.MakeTag(c4d.Ttexture)
            tag.SetMaterial(mat)
            tag[c4d.TEXTURETAG_PROJECTION] = c4d.TEXTURETAG_PROJECTION_UVW
            if len(mats) > 1 and mn in sel_names:
                tag[c4d.TEXTURETAG_RESTRICTION] = mn
            doc.AddUndo(c4d.UNDOTYPE_NEWOBJ, tag)
            assigned += 1

    doc.EndUndo()
    c4d.EventAdd()
    lines = ["建好 %d 个 Octane 材质, 赋给对象 %d 处" % (len(made), assigned)]
    if no_obj:
        lines.append("场景里没找到的对象(先导入 abc 再跑我): " + ", ".join(sorted(no_obj)[:6]))
    if skipped_metal:
        lines.append("金属度需手动接: " + ", ".join(sorted(set(skipped_metal))))
    if missing:
        lines.append("缺贴图: " + "; ".join(missing[:6]))
    c4d.gui.MessageDialog("\\n".join(lines))


if __name__ == "__main__":
    main()
'''


class POND_OT_export_c4d_full(bpy.types.Operator):
    """一条龙导出给 C4D：解包贴图(文件名规范化) + 材质清单 + abc 顶点缓存 + 生成 Octane 重建脚本。
产物全落在工程同目录, 工程本身不动"""
    bl_idname = "pond.export_c4d_full"
    bl_label = "一条龙导出(abc+贴图+材质)"

    _IMG_EXTS = (".png", ".jpg", ".jpeg", ".tga", ".tif", ".tiff", ".bmp", ".exr", ".webp")
    _CHANNELS = {"Base Color": "basecolor", "Roughness": "roughness", "Metallic": "metallic",
                 "Alpha": "alpha", "Normal": "normal", "Emission Color": "emission"}

    @classmethod
    def poll(cls, context):
        return bool(bpy.data.filepath)

    @classmethod
    def _norm_name(cls, img_name):
        """Blender 图名转 C4D 认得出的文件名, xx.png.004 改成 xx_004.png"""
        import re
        n = re.sub(r'[\\/:*?"<>|]', "_", img_name)
        n = re.sub(r"\.(\d{3})$", r"_\1", n)
        stem, ext = os.path.splitext(n)
        if ext.lower() not in cls._IMG_EXTS:
            m = re.match(r"(.+?)\.(png|jpe?g|tga|tiff?|bmp|exr|webp)(.*)$", n, re.I)
            if m:
                stem = m.group(1) + m.group(3).replace(".", "_")
                ext = "." + m.group(2)
            else:
                stem, ext = n, ".png"
        return stem + ext

    @classmethod
    def _trace_image(cls, socket, depth=0):
        """顺着链接找图像节点, 允许穿过 NormalMap/Mix 这类中间节点"""
        if not socket.is_linked or depth > 3:
            return None
        node = socket.links[0].from_node
        if node.type == "TEX_IMAGE":
            return node.image
        for inp in node.inputs:
            r = cls._trace_image(inp, depth + 1)
            if r:
                return r
        return None

    def execute(self, context):
        import json
        import shutil
        proj_dir = os.path.dirname(bpy.data.filepath)
        stem = os.path.splitext(os.path.basename(bpy.data.filepath))[0]
        tex_dir = os.path.join(proj_dir, "textures_c4d")
        os.makedirs(tex_dir, exist_ok=True)

        # 1. 收集可见网格的 Principled 通道, 顺便记对象用了哪些材质(C4D 侧按名赋回)
        mapping, manifest, used_imgs, obj_map = {}, {}, {}, {}
        tex_refs = []      # (清单里的通道字典, 图像数据块名), 去重改名后按这个回填
        for o in bpy.data.objects:
            if o.type != "MESH" or not o.visible_get():
                continue
            slot_names = [s.material.name for s in o.material_slots if s.material]
            if slot_names:
                obj_map[o.name] = slot_names
            for slot in o.material_slots:
                m = slot.material
                if not m or m.name in manifest or not m.use_nodes:
                    continue
                bsdf = next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
                entry = {}
                if bsdf:
                    for sock_name, key in self._CHANNELS.items():
                        sock = bsdf.inputs.get(sock_name)
                        if not sock:
                            continue
                        img = self._trace_image(sock)
                        if img:
                            fn = mapping.setdefault(img.name, self._norm_name(img.name))
                            used_imgs[img.name] = img
                            entry[key] = {"tex": fn}
                            tex_refs.append((entry[key], img.name))
                        elif sock_name in ("Base Color", "Emission Color"):
                            entry[key] = {"value": [round(v, 4) for v in list(sock.default_value)[:3]]}
                        elif sock_name in ("Roughness", "Metallic", "Alpha"):
                            entry[key] = {"value": round(float(sock.default_value), 4)}
                        # Normal 没接贴图时是向量默认值, 不进清单
                manifest[m.name] = entry

        # 文件名冲突兜底。清单里记的是去重前的名字, 改完要同步回去,
        # 不然两张不同的图在清单里指向同一个文件名, C4D 那边会贴错
        seen, renamed = set(), {}
        for k in list(mapping):
            v = mapping[k]
            if v in seen:
                s2, ext = os.path.splitext(v)
                i = 2
                while "%s_%d%s" % (s2, i, ext) in seen:
                    i += 1
                mapping[k] = "%s_%d%s" % (s2, i, ext)
                renamed[k] = mapping[k]
            seen.add(mapping[k])
        for ch, img_name in tex_refs:      # 按收集时记下的出处回填
            ch["tex"] = mapping[img_name]

        # 2. 贴图落盘(打包图写副本, 磁盘图复制, 不动工程)
        saved, missing = [], []
        for name, img in used_imgs.items():
            dst = os.path.join(tex_dir, mapping[name])
            try:
                if img.packed_file:
                    img.save_render(dst)
                elif img.filepath and os.path.exists(bpy.path.abspath(img.filepath)):
                    shutil.copy2(bpy.path.abspath(img.filepath), dst)
                else:
                    missing.append(name)
                    continue
                saved.append(mapping[name])
            except Exception as e:
                missing.append("%s(%s)" % (name, str(e)[:40]))

        # 3. 清单落盘
        manifest_path = os.path.join(proj_dir, stem + "_材质清单.json")
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump({"textures_dir": "textures_c4d", "materials": manifest,
                       "objects": obj_map}, f, ensure_ascii=False, indent=1)

        # 4. abc 导出, 返回值必须查, 静默取消要大声说
        abc_path = os.path.join(proj_dir, stem + "_c4d.abc")
        sc = context.scene
        r = bpy.ops.pond.export_c4d_abc(filepath=abc_path,
                                        frame_start=sc.frame_start, frame_end=sc.frame_end)
        if "FINISHED" not in r or not os.path.exists(abc_path):
            self.report({"ERROR"}, "abc 导出没有完成, 本次产物只有贴图和清单, 看控制台找原因")
            return {"CANCELLED"}

        # 5. 生成配套 C4D 重建脚本
        script_path = os.path.join(proj_dir, stem + "_c4d材质重建.py")
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(_C4D_REBUILD_TEMPLATE.format(stem=stem, manifest=manifest_path))

        abc_mb = os.path.getsize(abc_path) // (1024 * 1024)
        msg = "一条龙完成: 贴图 %d 张, 材质 %d 个, abc %dMB, C4D 脚本已生成" % (
            len(saved), len(manifest), abc_mb)
        if missing:
            msg += "; 贴图缺失 %d 张: %s" % (len(missing), ", ".join(missing[:4]))
        self.report({"WARNING" if missing else "INFO"}, msg)
        return {"FINISHED"}


_classes = (
    POND_OT_export_c4d,
    POND_OT_export_c4d_abc,
    POND_OT_import_c4d_restore,
    POND_OT_export_mat_manifest,
    POND_OT_export_c4d_full,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
