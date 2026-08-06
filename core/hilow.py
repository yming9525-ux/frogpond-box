# core/hilow.py — 高模烘低模（逻辑层，面板在 ui/pond/panels/hilow.py）
# 选中高模、激活低模，走 selected_to_active 把高模细节烘到低模贴图上：
# 法线(切线空间)/AO/基础色/糙度，挤出距离防穿插。
# 图落在工程旁 textures/；法线自动接进低模现有材质（法线口被占则不动）；
# 另搭一份「烘焙材质」，切换按钮与烘焙贴图共用（pond.bakemap_use_baked/orig）。
import json
import os

import bpy

from .bakemap import RES_ITEMS, _build_baked_mat


def _active_mesh(context):
    obj = context.active_object
    return obj if obj and obj.type == "MESH" else None


def _high_meshes(context):
    act = context.active_object
    return [o for o in context.selected_objects
            if o.type == "MESH" and o is not act]


def _bake_one(context, base, mats, suffix, size, margin,
              bake_kwargs, non_color, extrude, ray_dist):
    """建图→低模每个材质塞临时图片节点→高转低烘焙→存盘→拆节点"""
    name = f"烘焙_{base}_{suffix}"
    img = bpy.data.images.get(name)
    if img and tuple(img.size) != (size, size):
        bpy.data.images.remove(img)
        img = None
    if img is None:
        img = bpy.data.images.new(name, size, size, alpha=False)
    if non_color:
        for cs in ("Non-Color", "Raw"):
            try:
                img.colorspace_settings.name = cs
                break
            except Exception:
                continue
    temp_nodes = []
    for mat in mats:
        tree = mat.node_tree
        node = tree.nodes.new("ShaderNodeTexImage")
        node.name = "池塘烘焙目标"
        node.image = img
        for n in tree.nodes:
            n.select = False
        node.select = True
        tree.nodes.active = node
        temp_nodes.append((tree, node))
    try:
        bpy.ops.object.bake(margin=margin, use_clear=True,
                            use_selected_to_active=True,
                            cage_extrusion=extrude,
                            max_ray_distance=ray_dist,
                            **bake_kwargs)
    finally:
        for tree, node in temp_nodes:
            tree.nodes.remove(node)
    d = os.path.join(os.path.dirname(bpy.data.filepath), "textures")
    os.makedirs(d, exist_ok=True)
    img.filepath_raw = os.path.join(d, name + ".png")
    img.file_format = "PNG"
    img.save()
    return img


def _plug_normal(mats, img, uv_name):
    """烘好的法线图接进低模材质：贴图节点+法线贴图节点挂到原理化BSDF法线口
    法线口已被别的连线占着就不动，返回 (接好数, 占用数)"""
    done = busy = 0
    for mat in mats:
        nt = mat.node_tree
        bsdf = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if bsdf is None:
            continue
        nm = nt.nodes.get("池塘高低法线")
        sock = bsdf.inputs["Normal"]
        # 比对用名字，bpy 的节点引用过一次撤销栈就不可靠
        if sock.is_linked and sock.links[0].from_node.name != "池塘高低法线":
            busy += 1
            continue
        tex = nt.nodes.get("池塘高低法线图")
        if tex is None:
            tex = nt.nodes.new("ShaderNodeTexImage")
            tex.name = tex.label = "池塘高低法线图"
            tex.location = (bsdf.location.x - 620, bsdf.location.y - 560)
        tex.image = img
        if nm is None:
            nm = nt.nodes.new("ShaderNodeNormalMap")
            nm.name = nm.label = "池塘高低法线"
            nm.location = (bsdf.location.x - 300, bsdf.location.y - 560)
        if uv_name:
            nm.uv_map = uv_name
            # 贴图也要指定同一层。不接的话采样走渲染层,
            # 低模有两套UV且选中的不是渲染层时, 烘焙落点和采样对不上, 法线会花
            uvn = nt.nodes.get("池塘高低法线UV")
            if uvn is None:
                uvn = nt.nodes.new("ShaderNodeUVMap")
                uvn.name = uvn.label = "池塘高低法线UV"
                uvn.location = (bsdf.location.x - 840, bsdf.location.y - 560)
            uvn.uv_map = uv_name
            nt.links.new(uvn.outputs["UV"], tex.inputs["Vector"])
        nt.links.new(tex.outputs["Color"], nm.inputs["Color"])
        nt.links.new(nm.outputs["Normal"], sock)
        done += 1
    return done, busy


class POND_OT_hilow_bake(bpy.types.Operator):
    """选中高模、最后点低模(活动物体)，把高模细节烘到低模贴图上"""
    bl_idname = "pond.hilow_bake"
    bl_label = "高模烘到低模"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _active_mesh(context) is not None

    def execute(self, context):
        wm = context.window_manager
        low = _active_mesh(context)
        highs = _high_meshes(context)
        if not bpy.data.filepath:
            self.report({"ERROR"}, "先保存一下工程，贴图要落在工程旁的 textures/ 里")
            return {"CANCELLED"}
        if not highs:
            self.report({"ERROR"},
                        "只选了一个物体。先选高模，再按住Ctrl点低模(低模要亮)")
            return {"CANCELLED"}
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        # 低模的UV是贴图落点，没有就帮忙展一份
        if low.data.uv_layers.active is None:
            bpy.ops.object.select_all(action="DESELECT")
            low.select_set(True)
            context.view_layer.objects.active = low
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.mesh.select_all(action="SELECT")
            bpy.ops.uv.smart_project(island_margin=0.02)
            bpy.ops.object.mode_set(mode="OBJECT")
            self.report({"INFO"}, "低模没有UV，帮你智能展开了一份")
        uv_name = low.data.uv_layers.active.name

        # 原材质记录要在动手之前拍（低模可能连材质都没有）
        if "pond_bake_orig" not in low:
            low["pond_bake_orig"] = json.dumps(
                [s.material.name if s.material else ""
                 for s in low.material_slots], ensure_ascii=False)

        # 烘焙目标节点要挂在低模的材质上，一个都没有就垫一个
        mats = [s.material for s in low.material_slots
                if s.material and s.material.use_nodes]
        if not mats:
            pad = bpy.data.materials.get(f"低模底_{low.name}")
            if pad is None:
                pad = bpy.data.materials.new(f"低模底_{low.name}")
                pad.use_nodes = True
            if pad.name not in [s.material.name if s.material else ""
                                for s in low.material_slots]:
                low.data.materials.append(pad)
            mats = [pad]

        bpy.ops.object.select_all(action="DESELECT")
        for o in highs:
            o.select_set(True)
        low.select_set(True)
        context.view_layer.objects.active = low

        scene = context.scene
        prev_engine = scene.render.engine
        try:
            scene.render.engine = "CYCLES"
        except TypeError:
            self.report({"ERROR"}, "Cycles 不可用")
            return {"CANCELLED"}
        prev_samples = scene.cycles.samples
        scene.cycles.samples = 1
        size = int(wm.pond_hilow_res)
        margin = wm.pond_hilow_margin
        extrude = wm.pond_hilow_extrude
        ray_dist = wm.pond_hilow_raydist
        base = f"{low.name}_高转低"
        images = {}
        try:
            if wm.pond_hilow_normal:
                images["normal"] = _bake_one(
                    context, base, mats, "法线", size, margin,
                    {"type": "NORMAL"}, True, extrude, ray_dist)
            if wm.pond_hilow_color:
                images["color"] = _bake_one(
                    context, base, mats, "基础色", size, margin,
                    {"type": "DIFFUSE", "pass_filter": {"COLOR"}},
                    False, extrude, ray_dist)
            if wm.pond_hilow_rough:
                images["rough"] = _bake_one(
                    context, base, mats, "糙度", size, margin,
                    {"type": "ROUGHNESS"}, True, extrude, ray_dist)
            if wm.pond_hilow_ao:
                # AO要采样光线,1采样全是噪点,临时提到64
                scene.cycles.samples = 64
                try:
                    images["ao"] = _bake_one(
                        context, base, mats, "AO", size, margin,
                        {"type": "AO"}, True, extrude, ray_dist)
                finally:
                    scene.cycles.samples = 1
        except RuntimeError as e:
            self.report({"ERROR"}, f"烘焙失败: {str(e)[:120]}")
            return {"CANCELLED"}
        finally:
            scene.cycles.samples = prev_samples
            try:
                scene.render.engine = prev_engine
            except TypeError:
                pass
        if not images:
            self.report({"WARNING"}, "一个通道都没勾，啥也没烘")
            return {"CANCELLED"}
        mat = _build_baked_mat(base, images, uv_name)
        low["pond_bake_mat"] = mat.name
        tail = "（点「切到烘焙材质」看效果）"
        if "normal" in images:
            done, busy = _plug_normal(mats, images["normal"], uv_name)
            if done:
                tail = "，法线已接进低模材质"
            if busy:
                self.report({"WARNING"},
                            "%d 个材质的法线口已有连线，没敢动，"
                            "图在 textures/ 里自己接" % busy)
        self.report({"INFO"},
                    "高模%d件→低模%s，烘好 %d 张 → textures/%s" % (
                        len(highs), low.name, len(images), tail))
        return {"FINISHED"}


_classes = (
    POND_OT_hilow_bake,
)


def register():
    bpy.types.WindowManager.pond_hilow_res = bpy.props.EnumProperty(
        name="分辨率", items=RES_ITEMS, default="2048")
    bpy.types.WindowManager.pond_hilow_margin = bpy.props.IntProperty(
        name="扩边", default=16, min=2, max=64)
    bpy.types.WindowManager.pond_hilow_extrude = bpy.props.FloatProperty(
        name="挤出距离", default=0.05, min=0.0, soft_max=1.0,
        unit="LENGTH", precision=3,
        description="低模表面向外撑出多远去找高模。高低模贴得近用小值，"
                    "结果有黑斑或缺细节就加大一点")
    bpy.types.WindowManager.pond_hilow_raydist = bpy.props.FloatProperty(
        name="射线上限", default=0.0, min=0.0, soft_max=2.0,
        unit="LENGTH", precision=3,
        description="找高模的最远距离，0是不限制。"
                    "别的部件细节被错烘进来时，用它把射线拦短")
    bpy.types.WindowManager.pond_hilow_normal = bpy.props.BoolProperty(
        name="法线", default=True,
        description="高模的表面起伏烘成切线空间法线图，低模糊上去冒充高模")
    bpy.types.WindowManager.pond_hilow_ao = bpy.props.BoolProperty(
        name="AO", default=False,
        description="高模的环境光遮蔽烘给低模（临时提到64采样，比别的慢）。"
                    "烘焙材质里自动乘进基础色")
    bpy.types.WindowManager.pond_hilow_color = bpy.props.BoolProperty(
        name="基础色", default=False,
        description="把高模材质的颜色烘给低模（高模要有材质才有东西可烘）")
    bpy.types.WindowManager.pond_hilow_rough = bpy.props.BoolProperty(
        name="糙度", default=False,
        description="把高模材质的糙度烘给低模")
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
    del bpy.types.WindowManager.pond_hilow_rough
    del bpy.types.WindowManager.pond_hilow_color
    del bpy.types.WindowManager.pond_hilow_ao
    del bpy.types.WindowManager.pond_hilow_normal
    del bpy.types.WindowManager.pond_hilow_raydist
    del bpy.types.WindowManager.pond_hilow_extrude
    del bpy.types.WindowManager.pond_hilow_margin
    del bpy.types.WindowManager.pond_hilow_res
