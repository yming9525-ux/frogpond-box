# core/snapshot.py — IPR 视口快照对比（合并核心）
#
# 合并基准：Bekkan/STOOL_part/Snapshot.py。
# 相比 Pond 旧复制版的优势：逐窗口独立快照（area_id）、RGBA8 纹理（显存 1/4）、
# 画回前 sRGB 预解码校准（5.2 实测 1 LSB 无损）、load_post 自动清理失效纹理。
# 移植自 Pond 的新增：DeleteSnap（删除选中）、ExportSnap（导出为图像数据块）。
# 已删除：4.x 兼容分支与旧 GLSL（合并后整体锁定 Blender 5.2）。
#
# GPU 资源全用「每次启动重新惰性初始化」的模式：
#   - shader / draw handler 只放模块级变量，启动时必是 None
#   - 首次用到时现建，blender --background --python 下取不到 context 也能 import
#
# 色彩链路标定记录（5.2，2026-08-01 实机测试通过）：
#   - 5.x draw_view3d 已直出显示编码 sRGB 字节（视图变换/Filmic 已烘进去）。
#   - 存「显示编码字节」到 RGBA8 纹理，画回前在 shader 里 srgb_to_linear 预解码，
#     硬件再做 encode，round-trip 实测 1 LSB 无损。
#   - 将来要支持 5.0/5.1 时把 _DRAW_DECODE_SRGB 关成 False 即可（那时 draw_view3d
#     出的是线性场景参考色，预解码恰好校正了硬件 encode）。
import time
import bpy
import gpu
import gpu_extras.presets
import blf
import numpy as np
from gpu_extras.batch import batch_for_shader
from bpy.app.handlers import persistent

# 画回 shader 是否做 sRGB 预解码（校准开关，见文件头标定记录）
_DRAW_DECODE_SRGB = True

# ---- 5.x shader 源码（GPUShaderCreateInfo 路线；pos 为 CPU 侧换算的 NDC）----
_VERT5 = """
void main()
{
    texCoordInterp = texCoord;
    gl_Position = vec4(pos, 0.0, 1.0);
}
"""

_FRAG5_DECODE = """
void main()
{
    vec4 c = texture(image, texCoordInterp);
    if(decode > 0.5) c.rgb = pow(max(c.rgb, vec3(0.0)), vec3(2.2));
    c.a = 1.0;  /* 快照永远不透明：半透明黑图会伪装成「实时画面变暗」 */
    fragColor = c;
}
"""

_SHADER = None
_LINE_SHADER = None

_snaps = {}        # key -> {"tex": GPUTexture, "w": int, "h": int, "label": str}
_next_id = [1]     # 列表包一层，避免函数内 global 声明
# 快照池全局共用（不再按视口分家）：对比只画在「渲染」着色模式的视口里。
# 多视口工作流（一个渲染视口 + 一个实体视口改模型）是设计基准。
_disp = [None]     # 当前显示的快照 key（None=不显示）
_hdl = [None]      # 全局绘制句柄


def _get_shader():
    """延迟初始化主 shader，确保 Blender 上下文已就绪"""
    global _SHADER
    if _SHADER is None:
        try:
            interface = gpu.types.GPUStageInterfaceInfo("bekkan_snap")
            interface.smooth("VEC2", "texCoordInterp")
            info = gpu.types.GPUShaderCreateInfo()
            info.vertex_in(0, "VEC2", "pos")
            info.vertex_in(1, "VEC2", "texCoord")
            info.vertex_out(interface)
            info.fragment_out(0, "VEC4", "fragColor")
            info.sampler(0, "FLOAT_2D", "image")
            info.push_constant("FLOAT", "decode")
            info.vertex_source(_VERT5)
            info.fragment_source(_FRAG5_DECODE)
            _SHADER = gpu.shader.create_from_info(info)
        except Exception:
            print("Warning: snapshot shader initialization failed")
    return _SHADER


def _get_line_shader():
    """延迟初始化分割线 shader"""
    global _LINE_SHADER
    if _LINE_SHADER is None:
        try:
            _LINE_SHADER = gpu.shader.from_builtin("UNIFORM_COLOR")
        except Exception:
            print("Warning: UNIFORM_COLOR shader initialization failed")
    return _LINE_SHADER


def _ndc(rw, rh, x, y):
    """像素坐标 -> NDC（5.x 无 gpu.matrix 可取矩阵，CPU 侧换算）"""
    return (x / rw) * 2.0 - 1.0, (y / rh) * 2.0 - 1.0


def is_showing():
    """给 UI 面板用：当前是否在显示对比"""
    return _disp[0] is not None


def _rm_handler():
    """安全移除绘制句柄：区域被合并/关闭后句柄已失效，忽略 ReferenceError"""
    h = _hdl[0]
    if h:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(h, "WINDOW")
        except ReferenceError:
            pass
    _hdl[0] = None


def _ensure_handler():
    """确保全局绘制句柄存在"""
    if _hdl[0] is None:
        _hdl[0] = bpy.types.SpaceView3D.draw_handler_add(
            _draw, (), "WINDOW", "POST_PIXEL")


def _free_res():
    """关闭快照显示：移除绘制句柄并清除显示记录"""
    _rm_handler()
    _disp[0] = None


def _find_render_area(context):
    """找「渲染」着色模式的 3D 视口：优先当前视口，其次所有窗口里最大的那个。
    返回 (area, space, region) 或 None"""
    def pick(area):
        space = area.spaces.active
        region = next((r for r in area.regions if r.type == "WINDOW"), None)
        if region and getattr(space, "region_3d", None) is not None:
            return area, space, region
        return None

    a = context.area
    if a and a.type == "VIEW_3D" and a.spaces.active.shading.type == "RENDERED":
        got = pick(a)
        if got:
            return got
    best = None
    for win in context.window_manager.windows:
        for area in win.screen.areas:
            if area.type != "VIEW_3D" or area.spaces.active.shading.type != "RENDERED":
                continue
            got = pick(area)
            if got and (best is None or
                        area.width * area.height > best[0].width * best[0].height):
                best = got
    return best


def _srgb_encode(rgb):
    """sRGB 编码（标准分段曲线）。Snapshot 本体已不再使用，
    保留给 tools/test_snap_visual.py 做色彩链路标定"""
    return np.where(rgb <= 0.0031308, rgb * 12.92, 1.055 * np.power(rgb, 1 / 2.4) - 0.055)


def _srgb_decode(rgb):
    """sRGB 解码（标准分段曲线），导出图像数据块时把显示值换回 scene-linear"""
    return np.where(rgb <= 0.04045, rgb / 12.92, np.power((rgb + 0.055) / 1.055, 2.4))


def _capture_screen_crop(window, region):
    """Cycles 路线：截整窗前台缓冲（= 屏幕最终像素，视图变换/ACES/曝光全烘好），
    裁出渲染视口的 WINDOW 区域。所见即所得，采样到哪存到哪（同 Octane 存缓存）。
    draw_view3d 离屏重画对 Cycles 无效（交互渲染会话绑在真实视口，离屏出黑图）；
    POST_PIXEL/POST_VIEW 帧缓冲分别只有叠加层/视图变换前的线性色，都不能用。
    存储语义与离屏路线对齐：像素 = srgb_dec(屏幕字节)，画回时 shader 再预解码。"""
    import os
    import tempfile
    path = os.path.join(bpy.app.tempdir or tempfile.gettempdir(), "_pond_snap_grab.png")
    with bpy.context.temp_override(window=window):
        bpy.ops.screen.screenshot(filepath=path)
    img = bpy.data.images.load(path)
    try:
        iw, ih = img.size
        arr = np.empty(iw * ih * 4, dtype=np.float32)
        img.pixels.foreach_get(arr)   # 字节 PNG 的 .pixels 是原始 D/255，无色彩管理
    finally:
        bpy.data.images.remove(img)
        try:
            os.remove(path)
        except OSError:
            pass
    rgba = arr.reshape(ih, iw, 4)
    crop = rgba[region.y:region.y + region.height,
                region.x:region.x + region.width, :].copy()
    h, w = crop.shape[:2]
    flat = crop.reshape(-1, 4)
    # 屏幕字节本身就是「显示编码 sRGB」，与离屏路线的存储语义一致，直接存；
    # （此前多做了一次 srgb_decode，等于解码两遍，画面整体变暗——勿复发）
    flat[:, 3] = 1.0
    buf = gpu.types.Buffer("FLOAT", w * h * 4, flat.reshape(-1))
    tex = gpu.types.GPUTexture((w, h), format="RGBA8", data=buf)
    return tex, w, h


def _grab_later(area_ptr):
    """timer 回调：旧叠加已随上一次重绘从前台缓冲消失，再截屏"""
    ctx = bpy.context
    for win in ctx.window_manager.windows:
        for area in win.screen.areas:
            if area.as_pointer() != area_ptr:
                continue
            region = next((r for r in area.regions if r.type == "WINDOW"), None)
            if region is None:
                return None
            try:
                tex, w, h = _capture_screen_crop(win, region)
            except Exception as e:
                print("快照抓屏失败:", e)
                return None
            _finish_capture(ctx.scene, area, tex, w, h)
            return None
    return None


def _finish_capture(scene, area, tex, w, h):
    """拍摄成功后的公共收尾：登记纹理与快照列表、切换显示、刷新窗口"""
    key = "s%d" % _next_id[0]
    _next_id[0] += 1
    # 序号（三位数占位）+ 拍摄时间点，如 "001 14:30:52"
    label = "%03d %s" % (len(scene.snapshot_list) + 1, time.strftime("%H:%M:%S"))
    _snaps[key] = {"tex": tex, "w": w, "h": h, "label": label}
    item = scene.snapshot_list.add()
    item.name, item.key = label, key
    scene.snapshot_list_index = len(scene.snapshot_list) - 1
    _disp[0] = key
    _ensure_handler()
    for r in area.regions:
        if r.type == "WINDOW":
            r.tag_redraw()


def _draw():
    """POST_PIXEL 绘制：只画在「渲染」着色模式的视口里；快照在分割线右侧"""
    cur_area = bpy.context.area
    if not cur_area or cur_area.type != "VIEW_3D":
        return
    if cur_area.spaces.active.shading.type != "RENDERED":
        return
    rec = _snaps.get(_disp[0])
    if rec is None:
        return
    sh = _get_shader()
    if sh is None:
        return
    try:
        scene = bpy.context.scene
        region = next(r for r in cur_area.regions if r.type == "WINDOW")
        # 快照宽度与窗口宽度保持一致，高度按比例缩放并垂直居中（窗口尺寸变化适配）
        scale = region.width / rec["w"]
        w, h = rec["w"] * scale, rec["h"] * scale
        y = (region.height - h) / 2
        p = scene.slider_position / 100.0
        x0 = w * p  # 分割线位置 = 比例（0-100%），拖鼠标时线跟鼠标走；快照在线右侧

        rw, rh = region.width, region.height
        verts = [_ndc(rw, rh, x0, y), _ndc(rw, rh, w, y),
                 _ndc(rw, rh, w, y + h), _ndc(rw, rh, x0, y + h)]
        batch = batch_for_shader(
            sh, "TRI_FAN",
            {"pos": verts,
             "texCoord": ((p, 0), (1, 0), (1, 1), (p, 1))})
        gpu.state.blend_set("ALPHA")
        sh.bind()
        sh.uniform_sampler("image", rec["tex"])
        sh.uniform_float("decode", 1.0 if _DRAW_DECODE_SRGB else 0.0)
        batch.draw(sh)
        gpu.state.blend_set("NONE")

        # 绘制分割线
        ls = _get_line_shader()
        if ls:
            lverts = [(x0, y, 0), (x0, y + h, 0)]
            line_batch = batch_for_shader(ls, "LINES", {"pos": lverts})
            gpu.state.blend_set("ALPHA")
            ls.bind()
            ls.uniform_float("color", (1.0, 1.0, 1.0, 1.0))
            line_batch.draw(ls)
            gpu.state.blend_set("NONE")

        # 角标：快照在线右侧，角标显示在右上角
        text = f"快照 {rec['label']}"
        blf.size(0, 13)
        tw, _ = blf.dimensions(0, text)
        bx, by = region.width - tw - 10, region.height - 26
        blf.position(0, bx - 1, by - 1, 0)
        blf.color(0, 0.1, 0.1, 0.1, 0.9)
        blf.draw(0, text)
        blf.position(0, bx, by, 0)
        blf.color(0, 1.0, 1.0, 1.0, 0.95)
        blf.draw(0, text)
    except Exception as e:
        print("快照对比绘制失败:", e)


def _redraw_view3d(screen):
    for a in screen.areas:
        if a.type == "VIEW_3D":
            for r in a.regions:
                if r.type == "WINDOW":
                    r.tag_redraw()


@persistent
def _reset_on_load(_dummy=None):
    """打开/新建工程后纹理全部失效：移除句柄、清空记录；
    快照列表随 .blend 持久化但显存纹理不跨会话，必须逐场景同步清空"""
    _rm_handler()
    _snaps.clear()
    _disp[0] = None
    for sc in bpy.data.scenes:
        try:
            sc.snapshot_list.clear()
            sc.snapshot_list_index = -1
        except (AttributeError, ReferenceError):
            pass
    # 重画 UI，让列表跟着新文件状态
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            area.tag_redraw()


def _on_index_update(scene, context):
    """列表点选即切换：对比开着时，点哪条就显示哪条"""
    i = scene.snapshot_list_index
    if _disp[0] is not None and 0 <= i < len(scene.snapshot_list):
        key = scene.snapshot_list[i].key
        if key in _snaps and key != _disp[0]:
            _disp[0] = key
            for win in bpy.context.window_manager.windows:
                _redraw_view3d(win.screen)


class SnapItem(bpy.types.PropertyGroup):
    name: bpy.props.StringProperty()
    area_id: bpy.props.StringProperty()  # 旧版按视口分家的遗留字段，兼容旧 .blend，已不使用
    key: bpy.props.StringProperty()  # _snaps 的键


class TakeSnap(bpy.types.Operator):
    """拍摄当前 3D 视口快照"""
    bl_idname = "object.take_snapshot"
    bl_label = "拍摄快照"

    @classmethod
    def poll(cls, context):
        return context.area and context.area.type == "VIEW_3D"

    def execute(self, context):
        scene = context.scene
        # 不管从哪个视口触发，都拍「渲染」着色模式的那个视口
        got = _find_render_area(context)
        if got is None:
            self.report({"WARNING"}, "没找到渲染模式的视口——把要对比的视口切到渲染着色再拍")
            return {"CANCELLED"}
        area, space, region = got

        # 所有引擎统一截屏裁切（异步：先藏掉旧叠加、等一次重绘再截）。
        # 曾经 EEVEE 走 draw_view3d 离屏重画，但那是「裸渲染」——摄像机安全框、
        # 构图线等视口元素全丢，跟眼睛看到的对不上；对比工具必须所见即所得。
        _disp[0] = None          # 别把正在显示的旧快照叠加截进去
        region.tag_redraw()
        area_ptr = area.as_pointer()
        bpy.app.timers.register(lambda: _grab_later(area_ptr),
                                first_interval=0.15)
        self.report({"INFO"}, "正在抓取渲染视口画面…")
        return {"FINISHED"}


class ToggleSnap(bpy.types.Operator):
    """显示/隐藏快照对比"""
    bl_idname = "object.toggle_snapshot_display"
    bl_label = "对比开关"

    @classmethod
    def poll(cls, context):
        return context.area and context.area.type == "VIEW_3D"

    def execute(self, context):
        if _disp[0] is not None:
            _free_res()
        else:
            i = context.scene.snapshot_list_index
            if 0 <= i < len(context.scene.snapshot_list):
                item = context.scene.snapshot_list[i]
                if item.key in _snaps:
                    _disp[0] = item.key
                    _ensure_handler()
                    self.report({"INFO"}, f"显示快照 {item.name}")
                else:
                    self.report({"WARNING"}, "这条快照的纹理已经不在了（换过工程？）")
                    return {"CANCELLED"}
            else:
                self.report({"WARNING"}, "先拍一张快照")
                return {"CANCELLED"}
        _redraw_view3d(context.screen)
        return {"FINISHED"}


class SelectSnap(bpy.types.Operator):
    """选择列表中的快照"""
    bl_idname = "object.select_snapshot"
    bl_label = "选择快照"
    index: bpy.props.IntProperty()

    def execute(self, context):
        # 赋值即触发 snapshot_list_index 的 update 回调（对比开着时自动切换显示）
        context.scene.snapshot_list_index = self.index
        return {"FINISHED"}


class ClearSnapList(bpy.types.Operator):
    """清空快照列表"""
    bl_idname = "object.clear_snapshot_list"
    bl_label = "清空快照"

    def execute(self, context):
        _free_res()
        _snaps.clear()
        context.scene.snapshot_list.clear()
        context.scene.snapshot_list_index = 0
        _redraw_view3d(context.screen)
        return {"FINISHED"}


class DeleteSnap(bpy.types.Operator):
    """删除列表里选中的快照（移植自 Pond 版）"""
    bl_idname = "object.delete_snapshot"
    bl_label = "删除选中快照"

    @classmethod
    def poll(cls, context):
        return 0 <= context.scene.snapshot_list_index < len(context.scene.snapshot_list)

    def execute(self, context):
        scn = context.scene
        idx = scn.snapshot_list_index
        item = scn.snapshot_list[idx]
        # 从 _snaps 中移除纹理引用（GPUTexture 无 free()，靠解除引用 + GC）
        if item.key in _snaps:
            del _snaps[item.key]
        was_showing = _disp[0] == item.key
        if was_showing:
            _free_res()
        scn.snapshot_list.remove(idx)
        scn.snapshot_list_index = min(idx, len(scn.snapshot_list) - 1)
        # 删的是正在显示的那张 → 自动切到新选中的，别把对比整个关掉
        if was_showing and scn.snapshot_list:
            key = scn.snapshot_list[scn.snapshot_list_index].key
            if key in _snaps:
                _disp[0] = key
                _ensure_handler()
        _redraw_view3d(context.screen)
        return {"FINISHED"}


class ExportSnap(bpy.types.Operator):
    """把选中的快照导出成图像数据块（移植自 Pond 版，适配 RGBA8 存储）"""
    bl_idname = "object.export_snapshot"
    bl_label = "导出选中快照为图像数据块"

    @classmethod
    def poll(cls, context):
        return 0 <= context.scene.snapshot_list_index < len(context.scene.snapshot_list)

    def execute(self, context):
        scn = context.scene
        item = scn.snapshot_list[scn.snapshot_list_index]
        rec = _snaps.get(item.key)
        if not rec:
            self.report({"WARNING"}, "这条快照的纹理已经不在了（可能换过工程）")
            return {"CANCELLED"}
        buf = rec["tex"].read()  # RGBA8 → UBYTE buffer
        try:
            data = np.frombuffer(buf, dtype=np.uint8).astype(np.float32) / 255.0
        except Exception:
            data = np.array(list(buf), dtype=np.float32) / 255.0
        w, h = rec["w"], rec["h"]
        name = "快照导出"
        old = bpy.data.images.get(name)
        if old:
            bpy.data.images.remove(old)
        img = bpy.data.images.new(name, w, h, alpha=True, float_buffer=False)
        # 标 Non-Color/Raw：这些值已经是显示编码字节，别让色彩管理再动一遍
        for cs in ("Non-Color", "Raw"):
            try:
                img.colorspace_settings.name = cs
                break
            except Exception:
                continue
        img.pixels.foreach_set(data)
        img.update()
        self.report({"INFO"}, f"已生成图像数据块「{name}」，去图像编辑器里查看")
        return {"FINISHED"}


class GrabSlider(bpy.types.Operator):
    """点住分割线直接拖（对比显示时，左键按在分割线附近生效；其余点击原样放行）"""
    bl_idname = "object.grab_snapshot_slider"
    bl_label = "拖动分割线（直接点线）"

    _GRAB_PX = 8   # 分割线可抓取的半径（像素）

    @classmethod
    def poll(cls, context):
        return context.area and context.area.type == "VIEW_3D"

    def invoke(self, context, event):
        area = context.area
        region = context.region
        if (_disp[0] is None or region is None or region.type != "WINDOW"
                or area.spaces.active.shading.type != "RENDERED"):
            return {"PASS_THROUGH"}
        x_line = region.width * context.scene.slider_position / 100.0
        if abs(event.mouse_region_x - x_line) > self._GRAB_PX:
            return {"PASS_THROUGH"}
        context.window.cursor_modal_set("MOVE_X")
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type == "MOUSEMOVE":
            region = context.region
            if region and region.type == "WINDOW":
                context.scene.slider_position = max(0.0, min(100.0,
                    100.0 * event.mouse_region_x / max(1, region.width)))
            _redraw_view3d(context.screen)
            return {"RUNNING_MODAL"}
        if event.type == "LEFTMOUSE" and event.value == "RELEASE":
            context.window.cursor_modal_restore()
            return {"FINISHED"}
        if event.type in {"RIGHTMOUSE", "ESC"}:
            context.window.cursor_modal_restore()
            return {"CANCELLED"}
        return {"RUNNING_MODAL"}


class DragSlider(bpy.types.Operator):
    """Alt+右键拖拽分割线"""
    bl_idname = "object.drag_slider"
    bl_label = "拖拽分割线"

    def modal(self, context, event):
        if event.type == "MOUSEMOVE":
            region = context.region
            if region and region.type == "WINDOW":
                x = event.mouse_region_x
                context.scene.slider_position = max(
                    0.0, min(100.0, 100.0 * x / region.width))
            _redraw_view3d(context.screen)
            return {"RUNNING_MODAL"}
        if event.type in {"LEFTMOUSE", "RIGHTMOUSE"} and event.value == "PRESS":
            return {"FINISHED"}
        if event.type == "ESC":
            return {"CANCELLED"}
        return {"RUNNING_MODAL"}

    def invoke(self, context, event):
        if not context.area or context.area.type != "VIEW_3D":
            return {"CANCELLED"}
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}


_classes = (
    SnapItem,
    TakeSnap,
    ToggleSnap,
    SelectSnap,
    ClearSnapList,
    DeleteSnap,
    ExportSnap,
    GrabSlider,
    DragSlider,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.slider_position = bpy.props.FloatProperty(
        name="分割线", subtype="PERCENTAGE", default=50.0, min=0.0, max=100.0)
    bpy.types.Scene.snapshot_list = bpy.props.CollectionProperty(type=SnapItem)
    bpy.types.Scene.snapshot_list_index = bpy.props.IntProperty(
        default=0, update=_on_index_update)
    bpy.types.Scene.snap_expanded = bpy.props.BoolProperty(default=False)
    if _reset_on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_reset_on_load)

    # 显存纹理不跨插件重载/重启：启动时清掉列表里纹理已丢的死条目，
    # 免得眼睛开关按上去只换来一句「纹理已经不在了」
    def _purge_stale():
        for sc in bpy.data.scenes:
            try:
                stale = [i for i, it in enumerate(sc.snapshot_list)
                         if it.key not in _snaps]
                for i in reversed(stale):
                    sc.snapshot_list.remove(i)
                if stale:
                    sc.snapshot_list_index = min(
                        sc.snapshot_list_index, len(sc.snapshot_list) - 1)
            except (AttributeError, ReferenceError):
                pass
        return None
    bpy.app.timers.register(_purge_stale, first_interval=0)
    km = bpy.context.window_manager.keyconfigs.addon.keymaps.new(
        name="3D View", space_type="VIEW_3D")
    km.keymap_items.new("object.drag_slider", "RIGHTMOUSE", "PRESS", alt=True)
    km.keymap_items.new("object.take_snapshot", "RIGHTMOUSE", "PRESS",
                        ctrl=True, alt=True)
    # 点住分割线直接拖：不在线附近时 invoke 返回 PASS_THROUGH，不影响正常左键
    km.keymap_items.new("object.grab_snapshot_slider", "LEFTMOUSE", "PRESS")


def unregister():
    km = bpy.context.window_manager.keyconfigs.addon.keymaps.get("3D View")
    if km:
        for kmi in list(km.keymap_items):
            if kmi.idname in {"object.drag_slider", "object.take_snapshot",
                              "object.grab_snapshot_slider"}:
                km.keymap_items.remove(kmi)
    if _reset_on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_reset_on_load)
    _rm_handler()
    _snaps.clear()
    _disp[0] = None
    del bpy.types.Scene.snap_expanded
    del bpy.types.Scene.snapshot_list_index
    del bpy.types.Scene.snapshot_list
    del bpy.types.Scene.slider_position
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)


# ============================================================================
# 【保留待议 · 决策点5】Pond 版快照的交互实现（点分割线附近直接拖、快照在线右）
# 当前合并核心统一用 Bekkan 交互（快照在线左、Alt+右键任意处拖）。
# 若蛙灾日后觉得不合适，再启用以下实现或做两个模式两套交互。
# ----------------------------------------------------------------------------
# class POND_OT_snap_split(bpy.types.Operator):
#     """点住分割线左右拖,松手停"""
#     bl_idname = "pond.snap_split"
#     bl_label = "拖动分割线"
#
#     def modal(self, context, event):
#         global _split_running
#         wm = context.window_manager
#         if event.type == "MOUSEMOVE":
#             reg = context.region
#             if reg and reg.type == "WINDOW":
#                 wm.pond_snap_split = min(0.95, max(0.05,
#                     event.mouse_region_x / max(1, reg.width)))
#             _tag_redraw()
#             return {"RUNNING_MODAL"}
#         if event.type == "LEFTMOUSE" and event.value == "RELEASE":
#             _split_running = False
#             return {"FINISHED"}
#         if event.type == "ESC":
#             _split_running = False
#             return {"CANCELLED"}
#         return {"RUNNING_MODAL"}
#
#     def invoke(self, context, event):
#         global _split_running
#         _split_running = True
#         context.window_manager.modal_handler_add(self)
#         return {"RUNNING_MODAL"}
#
# 配套的 Toggle 行为：拍完后第一次点「对比」自动进入拖线 modal
# （原版 POND_OT_snap_toggle.invoke 末尾：
#     wm.pond_snap_split = 0.5
#     bpy.ops.pond.snap_split("INVOKE_DEFAULT") ）
#
# 绘制差异（Pond 版 _draw_overlay 的逻辑）：
#   - 快照画在分割线右侧，左侧为实景（Bekkan 核心相反）
#   - 分割线竖线用 (x_split,0)-(x_split,h) 即可，无 bgl 段
#   - 遮罩画在左侧 [0, x_split]
#   - 快照图只在 [x_split, w] 区域绘制
# ============================================================================
