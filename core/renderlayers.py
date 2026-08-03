# 分层渲染（通道版）：打开常用渲染通道，合成器自动接「渲染层 → 多层EXR文件输出」
# 对标 C4D/Octane 多通道工作流：渲染一次，EXR 里带全部通道（含灯光组），后期分层取用。
# （旧版「每个集合一个视图层 + AlphaOver 叠回」的集合分层已退役，见 git 历史）
import bpy

NG_NAME = "池塘_通道EXR输出"


class POND_OT_exr_passes_setup(bpy.types.Operator):
    """打开常用渲染通道，并在合成器里接好「渲染层→多层EXR」输出节点。
    输出路径在文件输出节点上改（默认取渲染输出路径）"""
    bl_idname = "pond.exr_passes_setup"
    bl_label = "一键通道EXR"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        vl = context.view_layer

        # ── 打开常用通道（对应多通道 EXR 交付的标准配置） ──
        vl.use_pass_combined = True
        vl.use_pass_mist = True
        for pre in ("diffuse", "glossy", "transmission"):
            setattr(vl, f"use_pass_{pre}_direct", True)
            setattr(vl, f"use_pass_{pre}_indirect", True)
            setattr(vl, f"use_pass_{pre}_color", True)
        vl.use_pass_emit = True
        vl.use_pass_environment = True
        vl.use_pass_ambient_occlusion = True
        vl.use_pass_cryptomatte_object = True
        vl.use_pass_cryptomatte_material = True
        vl.use_pass_cryptomatte_asset = True
        cyc = getattr(vl, "cycles", None)
        if scene.render.engine == "CYCLES" and cyc is not None:
            cyc.use_pass_volume_direct = True
            cyc.use_pass_volume_indirect = True
            cyc.use_pass_shadow_catcher = True
            cyc.denoising_store_passes = True   # Noisy Image 等降噪配套通道

        # ── 合成组：渲染层 → 多层EXR 文件输出（每个启用的通道一条线） ──
        ng = bpy.data.node_groups.get(NG_NAME)
        if ng:
            bpy.data.node_groups.remove(ng)
        ng = bpy.data.node_groups.new(NG_NAME, "CompositorNodeTree")
        ng.interface.new_socket("Image", in_out="OUTPUT",
                                socket_type="NodeSocketColor")

        rl = ng.nodes.new("CompositorNodeRLayers")
        rl.location = (-500, 0)
        rl.label = "渲染层"
        try:
            rl.scene = scene
        except Exception:
            pass
        rl.layer = vl.name

        out = ng.nodes.new("CompositorNodeOutputFile")
        out.location = (150, 0)
        out.label = "EXR-MultiLayer"
        out.format.file_format = "OPEN_EXR_MULTILAYER"
        out.format.color_depth = "16"
        # 5.2 API：目录 + 文件名模板分开（旧 base_path/layer_slots 已移除）
        out.directory = scene.render.filepath or "//输出/"
        out.file_output_items.clear()

        # 先建全部槽位，再按序号一一对接
        # （inputs[-1] 是「+」虚拟扩展口，直接往它身上连全是无效线）
        enabled = [s for s in rl.outputs if s.enabled]
        for sock in enabled:
            out.file_output_items.new("RGBA", sock.name)
        linked = 0
        for i, sock in enumerate(enabled):
            ng.links.new(sock, out.inputs[i])
            linked += 1

        # 合成输出走 Combined，渲染窗口照常显示画面
        go = ng.nodes.new("NodeGroupOutput")
        go.location = (150, 300)
        ng.links.new(rl.outputs["Image"], go.inputs[0])
        scene.compositing_node_group = ng

        self.report({"INFO"},
                    f"已开通道并接好 {linked} 条输出线；"
                    f"输出路径在文件输出节点上改（现为 {out.directory}）")
        return {"FINISHED"}


class POND_OT_exr_passes_clear(bpy.types.Operator):
    """断开并删除通道EXR的合成组（通道开关保持现状不动）"""
    bl_idname = "pond.exr_passes_clear"
    bl_label = "拆掉通道EXR"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return bpy.data.node_groups.get(NG_NAME) is not None

    def execute(self, context):
        scene = context.scene
        ng = bpy.data.node_groups.get(NG_NAME)
        if ng:
            if scene.compositing_node_group == ng:
                scene.compositing_node_group = None
            bpy.data.node_groups.remove(ng)
        self.report({"INFO"}, "通道EXR输出拆掉了（通道开关没动）")
        return {"FINISHED"}


_classes = (
    POND_OT_exr_passes_setup,
    POND_OT_exr_passes_clear,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
