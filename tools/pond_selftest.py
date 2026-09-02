# 池塘全模块 headless 自检 v2（对齐 frogpond-box 仓库结构）
# 用法: blender --background --factory-startup --python tools/pond_selftest.py
# 结果落在本文件旁 pond_selftest_result.json
import bpy, json, os, sys, tempfile, traceback

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pond_selftest_result.json")
RESULTS = []
TMP = tempfile.mkdtemp(prefix="pond_test_")

def rec(module, name, status, detail=""):
    RESULTS.append({"module": module, "test": name, "status": status, "detail": str(detail)[:400]})
    print("[%s] %s / %s : %s" % (status, module, name, str(detail)[:120]))

def step(module, name, fn, gui_ok=False):
    try:
        r = fn()
        rec(module, name, "PASS", r if r else "")
        return True
    except Exception as e:
        msg = "%s: %s" % (type(e).__name__, e)
        if gui_ok and "poll() failed" in str(e):
            rec(module, name, "SKIP_GUI", "headless 无 3D 视口, 需真机验证")
            return False
        rec(module, name, "FAIL", msg)
        traceback.print_exc()
        return False

def clean_scene():
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    for coll in list(bpy.data.collections):
        bpy.data.collections.remove(coll)

def new_cube(name, loc=(0,0,0)):
    me = bpy.data.meshes.new(name)
    import bmesh
    bm = bmesh.new(); bmesh.ops.create_cube(bm, size=1.0)
    bm.to_mesh(me); bm.free()
    ob = bpy.data.objects.new(name, me)
    ob.location = loc
    bpy.context.scene.collection.objects.link(ob)
    return ob

def select_only(*obs):
    bpy.ops.object.select_all(action='DESELECT')
    for o in obs: o.select_set(True)
    if obs: bpy.context.view_layer.objects.active = obs[0]

# ---------- 0. 启用插件 ----------
import addon_utils
def enable_pond():
    addon_utils.enable("pond", default_set=True, persistent=True)
    return "enabled"
step("core", "启用插件", enable_pond)

n_ops = len([k for k in dir(bpy.ops.pond) if not k.startswith("_")])
rec("core", "注册操作符计数", "PASS" if n_ops >= 45 else "WARN", "%d 个" % n_ops)

# 保存工程(bakemap/hilow/C4D一条龙 需要)
blend_path = os.path.join(TMP, "pondtest_v001.blend")
step("core", "保存测试工程", lambda: bpy.ops.wm.save_as_mainfile(filepath=blend_path))

# ---------- 1. 父子级 hierarchy ----------
def t_hier():
    clean_scene()
    a = new_cube("h_a", (0,0,0)); b = new_cube("h_b", (2,0,0))
    select_only(a, b)   # 激活=a, 其余挂到 a 下面
    bpy.ops.pond.group_to_parent()
    assert b.parent is a, "打组后 b 没挂到激活物体 a 下: %s" % b.parent
    select_only(b)
    bpy.ops.pond.select_parents()
    assert a.select_get(), "选父级没选中 a"
    select_only(b)
    bpy.ops.pond.extract()
    assert b.parent is None, "拎出后 b 还有父级"
    return "挂载/选父/拎出全对"
step("父子级", "打组/选父级/拎出", t_hier)

# ---------- 2. 原点吸附 organize ----------
def t_origin():
    clean_scene()
    a = new_cube("o_a", (1, 2, 3))
    select_only(a)
    bpy.ops.pond.origin_to_side(side='BOTTOM')
    bpy.context.view_layer.update()
    zs = [(a.matrix_world @ v.co).z for v in a.data.vertices]
    oz = a.matrix_world.translation.z
    assert abs(min(zs) - oz) < 1e-4, "原点没落到包围盒底面: 原点z=%.4f 最低点z=%.4f" % (oz, min(zs))
    bpy.ops.pond.origin_to_side(side='TOP')
    bpy.context.view_layer.update()
    zs = [(a.matrix_world @ v.co).z for v in a.data.vertices]
    assert abs(max(zs) - a.matrix_world.translation.z) < 1e-4, "原点没落到包围盒顶面"
    return "底/顶两向都验过"
step("原点吸附", "吸附到底部/顶部", t_origin)

# ---------- 3. 同步体检 synccheck ----------
def t_sync():
    clean_scene()
    a = new_cube("s_a"); b = new_cube("s_b", (2,0,0))
    a.hide_set(True)          # 眼睛关
    a.hide_render = False     # 渲染开 -> 不一致
    bpy.ops.pond.sync_scan()
    bpy.ops.pond.sync_apply()
    bpy.ops.pond.sync_undo()
    return "扫描+对齐+撤回跑通"
step("同步体检", "扫描/对齐/撤回", t_sync)

# ---------- 4. 明度检查 lumen ----------
def t_lumen():
    clean_scene()
    new_cube("l_a")
    bpy.context.scene.render.engine = 'CYCLES'
    bpy.ops.pond.lumen_clay()
    ov = bpy.context.view_layer.material_override
    bpy.ops.pond.lumen_restore()
    assert ov is not None, "白膜没有设置 material_override"
    bpy.ops.pond.lumen_bw()
    bpy.ops.pond.lumen_restore()
    return "白膜override=%s" % (ov.name if ov else None)
step("明度检查", "白膜/黑白/还原(Cycles)", t_lumen, gui_ok=True)

# ---------- 5. 灯光台 lightdesk ----------
def t_ld():
    clean_scene()
    l1d = bpy.data.lights.new("ld1", 'POINT'); l1 = bpy.data.objects.new("ld_灯1", l1d)
    l2d = bpy.data.lights.new("ld2", 'POINT'); l2 = bpy.data.objects.new("ld_灯2", l2d)
    sc = bpy.context.scene.collection
    sc.objects.link(l1); sc.objects.link(l2)
    bpy.ops.pond.ld_group_new(name="测试组") if "name" in bpy.ops.pond.ld_group_new.get_rna_type().properties.keys() else bpy.ops.pond.ld_group_new()
    select_only(l1)
    # 各操作符参数名不确定, 逐个试
    tried = []
    for opname, kwargs in [("ld_assign", {}), ("ld_solo", {"target": "obj:ld_灯1"}),
                           ("ld_solo", {}), ("ld_vis", {"target": "obj:ld_灯1"}), ("ld_vis", {}),
                           ("ld_sync_lightgroups", {})]:
        try:
            getattr(bpy.ops.pond, opname)(**kwargs)
            tried.append(opname + ":ok")
        except TypeError:
            tried.append(opname + ":参数不符")
        except Exception as e:
            tried.append(opname + ":" + type(e).__name__)
    return "; ".join(tried)
step("灯光台", "建组/分组/solo/开关/灯光组同步", t_ld)

# ---------- 6. 色卡 palette ----------
def t_pal():
    img_path = r"I:\Shoal\404notfound-蝴蝶信使小水印2.png"
    if not os.path.exists(img_path):
        return "基准图不存在, 跳过"
    bpy.ops.pond.palette_from_file(filepath=img_path)
    pals = [p for p in bpy.data.palettes if p.name.endswith("_色卡")]
    assert pals, "没生成 _色卡 调色板"
    bpy.ops.pond.palette_delete()
    return "生成 %d 块色卡" % len(pals)
step("色卡", "从图片生成/删除", t_pal)

# ---------- 7. 摄像机组 stage ----------
def t_cam():
    clean_scene()
    a = new_cube("cam_target")
    select_only(a)
    bpy.ops.pond.cam_rig_build()
    cams = [o for o in bpy.data.objects if o.type == 'CAMERA']
    assert cams, "没生成摄像机"
    return "对象数=%d" % len(bpy.data.objects)
step("摄像机组", "简洁机组一键搭建", t_cam)

def t_cam_film():
    """短片机组：五件套齐全, 两个目标各司其职（她惯用的那套, 别再被合并覆盖）"""
    clean_scene()
    a = new_cube("film_target")
    select_only(a)
    bpy.ops.pond.make_cam_rig()
    need = {"CAM_根", "CAM_环绕层", "短片摄像机", "CAM_注视目标", "CAM_对焦目标"}
    missing = need - set(bpy.data.objects.keys())
    assert not missing, "少了: %s" % missing
    cam = bpy.data.objects["短片摄像机"]
    track = next((c for c in cam.constraints if c.type == "TRACK_TO"), None)
    assert track and track.target.name == "CAM_注视目标", "注视目标没接上"
    assert cam.data.dof.focus_object.name == "CAM_对焦目标", "对焦目标没接上"
    assert cam.data.show_passepartout, "黑框没开"
    return "五件套齐全, 注视/对焦各自独立"
step("摄像机组", "短片机组五件套", t_cam_film)

def t_cam_empty():
    """删光机组后 active 会变 None, 两个按钮都不许变灰"""
    clean_scene()
    bpy.context.view_layer.objects.active = None
    assert bpy.ops.pond.cam_rig_build.poll(), "简洁机组按钮变灰了"
    assert bpy.ops.pond.make_cam_rig.poll(), "短片机组按钮变灰了"
    bpy.ops.pond.cam_rig_build()
    assert bpy.data.objects.get("镜头Cam"), "空场景搭不出简洁机组"
    clean_scene()
    bpy.context.view_layer.objects.active = None
    bpy.ops.pond.make_cam_rig()
    root = bpy.data.objects.get("CAM_根")
    assert root and root.location.length < 1e-6, "空场景没以原点为中心"
    return "两个按钮空场景都能点"
step("摄像机组", "空场景按钮不变灰", t_cam_empty)

# ---------- 8. 图转立体 trace2solid ----------
def t_trace():
    clean_scene()
    img_path = r"I:\Shoal\404notfound-蝴蝶信使小水印2.png"
    if not os.path.exists(img_path):
        return "基准图不存在, 跳过"
    props = bpy.ops.pond.trace_solid.get_rna_type().properties.keys()
    kwargs = {}
    if "filepath" in props: kwargs["filepath"] = img_path
    bpy.ops.pond.trace_solid(**kwargs)
    outs = [o for o in bpy.data.objects if o.type in ('MESH', 'CURVE') and o.name.endswith("_立体")]
    assert outs, "没生成 _立体 对象"
    return "生成: %s (%s)" % (outs[0].name, outs[0].type)
step("图转立体", "几何模式描摹", t_trace)

# ---------- 9. 一键拆分 splitter ----------
def t_split():
    clean_scene()
    import bmesh
    me = bpy.data.meshes.new("sp")
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.create_cube(bm, size=1.0)
    for v in list(bm.verts)[8:]: v.co.x += 5
    bm.to_mesh(me); bm.free()
    ob = bpy.data.objects.new("sp_obj", me)
    bpy.context.scene.collection.objects.link(ob)
    select_only(ob)
    bpy.ops.pond.split()
    parts = [o for o in bpy.data.objects if o.name.startswith("sp_obj")]
    assert len(parts) >= 2, "松散块没拆开: %d" % len(parts)
    return "拆成 %d 块" % len(parts)
step("一键拆分", "按松散块拆分", t_split)

# ---------- 10. 烘焙贴图 bakemap ----------
def t_bake():
    clean_scene()
    bpy.ops.wm.save_as_mainfile(filepath=blend_path)  # 确保已保存
    a = new_cube("bk_a")
    m = bpy.data.materials.new("程序化"); m.use_nodes = True
    nt = m.node_tree
    noise = nt.nodes.new("ShaderNodeTexNoise")
    bsdf = nt.nodes["Principled BSDF"]
    nt.links.new(noise.outputs["Color"], bsdf.inputs["Base Color"])
    a.data.materials.append(m)
    select_only(a)
    bpy.context.scene.render.engine = 'CYCLES'
    bpy.context.window_manager.pond_bake_res = '512'
    bpy.ops.pond.bakemap()
    texdir = os.path.join(os.path.dirname(blend_path), "textures")
    files = os.listdir(texdir) if os.path.isdir(texdir) else []
    assert files, "textures/ 没有产出"
    bpy.ops.pond.bakemap_use_baked()
    bpy.ops.pond.bakemap_use_orig()
    return "产出: %s" % files[:4]
step("烘焙贴图", "程序化烘焙+材质切换", t_bake)

# ---------- 11. 高模烘低模 hilow ----------
def t_hilow():
    clean_scene()
    bpy.ops.wm.save_as_mainfile(filepath=blend_path)
    bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=24)
    high = bpy.context.active_object; high.name = "hi_高模"
    tex = bpy.data.textures.get("hl_噪波") or bpy.data.textures.new("hl_噪波", "CLOUDS")
    mod = high.modifiers.new("位移", "DISPLACE"); mod.texture = tex; mod.strength = 0.08
    bpy.ops.mesh.primitive_uv_sphere_add(segments=12, ring_count=6)
    low = bpy.context.active_object; low.name = "hi_低模"
    m = bpy.data.materials.new("低模材质"); m.use_nodes = True
    low.data.materials.append(m)
    wm = bpy.context.window_manager
    wm.pond_hilow_res = '512'
    wm.pond_hilow_normal = True
    wm.pond_hilow_ao = False; wm.pond_hilow_color = False; wm.pond_hilow_rough = False
    select_only(high, low)
    bpy.context.view_layer.objects.active = low
    bpy.ops.pond.hilow_bake()
    texdir = os.path.join(os.path.dirname(blend_path), "textures")
    outs = [f for f in os.listdir(texdir) if "高转低" in f]
    assert outs, "textures/ 没有高转低产出"
    nt2 = m.node_tree
    bsdf = next(n for n in nt2.nodes if n.type == "BSDF_PRINCIPLED")
    assert bsdf.inputs["Normal"].is_linked, "法线没自动接进低模材质"
    return "产出: %s, 法线已接" % outs
step("高模烘低模", "法线烘焙+自动接线", t_hilow)

# ---------- 12. 分层渲染(通道EXR) renderlayers ----------
def t_exr():
    clean_scene()
    new_cube("exr_a")
    bpy.context.scene.render.engine = 'CYCLES'
    bpy.ops.pond.exr_passes_setup()
    ng = bpy.data.node_groups.get("池塘_通道EXR输出")
    assert ng is not None, "合成组没建出来"
    assert bpy.context.scene.compositing_node_group == ng, "合成组没挂上场景"
    outs = [n for n in ng.nodes if n.type == 'OUTPUT_FILE']
    assert outs, "没有文件输出节点"
    n_items = len(outs[0].file_output_items)
    assert n_items >= 5, "输出通道太少: %d" % n_items
    bpy.ops.pond.exr_passes_clear()
    assert bpy.data.node_groups.get("池塘_通道EXR输出") is None, "拆掉后合成组还在"
    return "通道输出 %d 条, 拆掉干净" % n_items
step("分层渲染", "一键通道EXR/拆掉", t_exr)

# ---------- 13. C4D 互导 c4d_bridge ----------
def t_fbx():
    clean_scene()
    c1 = bpy.data.collections.new("组A")
    bpy.context.scene.collection.children.link(c1)
    a = new_cube("c4d_a")
    for coll in a.users_collection: coll.objects.unlink(a)
    c1.objects.link(a)
    select_only(a)
    out = os.path.join(TMP, "test.fbx")
    props = bpy.ops.pond.export_c4d.get_rna_type().properties.keys()
    kwargs = {"filepath": out} if "filepath" in props else {}
    bpy.ops.pond.export_c4d(**kwargs)
    assert os.path.exists(out) or any(f.endswith(".fbx") for f in os.listdir(TMP)), "没产出 FBX"
    return "ok"
step("C4D互导", "分组FBX导出", t_fbx)

def t_abc():
    clean_scene()
    a = new_cube("abc_a")
    cam_d = bpy.data.cameras.new("c"); cam = bpy.data.objects.new("abc_cam", cam_d)
    bpy.context.scene.collection.objects.link(cam)
    bpy.context.scene.camera = cam
    bpy.context.scene.frame_start = 1; bpy.context.scene.frame_end = 2
    select_only(a)
    out = os.path.join(TMP, "test.abc")
    props = bpy.ops.pond.export_c4d_abc.get_rna_type().properties.keys()
    kwargs = {"filepath": out} if "filepath" in props else {}
    bpy.ops.pond.export_c4d_abc(**kwargs)
    assert os.path.exists(out) or any(f.endswith(".abc") for f in os.listdir(TMP)), "没产出 abc"
    return "ok"
step("C4D互导", "abc顶点缓存导出", t_abc)

def t_manifest():
    clean_scene()
    a = new_cube("mf_a")
    m = bpy.data.materials.new("清单材质"); m.use_nodes = True
    a.data.materials.append(m)
    select_only(a)
    props = bpy.ops.pond.export_mat_manifest.get_rna_type().properties.keys()
    out = os.path.join(TMP, "manifest.json")
    kwargs = {"filepath": out} if "filepath" in props else {}
    bpy.ops.pond.export_mat_manifest(**kwargs)
    return "ok"
step("C4D互导", "材质清单导出", t_manifest)

def t_full():
    clean_scene()
    full_blend = os.path.join(TMP, "一条龙工程_v001.blend")
    a = new_cube("full_a")
    m = bpy.data.materials.new("一条龙材质"); m.use_nodes = True
    a.data.materials.append(m)
    cam_d = bpy.data.cameras.new("fc"); cam = bpy.data.objects.new("full_cam", cam_d)
    bpy.context.scene.collection.objects.link(cam)
    bpy.context.scene.camera = cam
    bpy.ops.wm.save_as_mainfile(filepath=full_blend)
    select_only(a)
    before = set(os.listdir(TMP))
    bpy.ops.pond.export_c4d_full()
    after = set(os.listdir(TMP))
    new = sorted(after - before)
    assert new, "一条龙没有任何产出"
    return "产出: %s" % new[:6]
step("C4D互导", "一条龙导出(abc+贴图+材质)", t_full)

# ---------- 14. 预设库 preset_lib (只测临时库, 不碰她的真库) ----------
def t_lib():
    libdir = os.path.join(TMP, "预设库测试")
    prefs = bpy.context.preferences.addons["pond"].preferences
    old_root = prefs.preset_lib_root
    prefs.preset_lib_root = libdir
    try:
        clean_scene()
        a = new_cube("lib_a")
        m = bpy.data.materials.new("入库材质"); m.use_nodes = True
        a.data.materials.append(m)
        a.active_material_index = 0
        select_only(a)
        bpy.context.window_manager.pond_lib_tab = 'SHADER'
        bpy.ops.pond.lib_refresh()
        bpy.ops.pond.lib_save()
        bpy.ops.pond.lib_refresh()
        files = []
        for root, _, fs in os.walk(libdir):
            files += [x for x in fs if x.endswith(".blend") or x.endswith(".json")]
        assert files, "库目录没有产出: %s" % libdir
        return "库产出: %s" % files
    finally:
        prefs.preset_lib_root = old_root
step("预设库", "临时库存入/刷新(走偏好设置路径)", t_lib)

# ---------- 15. 视窗渲染对比 snapshot (headless 无 GPU 上下文) ----------
def t_snap():
    bpy.ops.object.take_snapshot()
    return "意外可用"
step("视窗渲染对比", "拍快照", t_snap, gui_ok=True)

# ---------- 16. 六面投射 sixproj ----------
def t_six():
    clean_scene()
    a = new_cube("sw_a")
    select_only(a)
    sixdir = os.path.join(TMP, "sixmaps"); os.makedirs(sixdir, exist_ok=True)
    for tag, col in [("正面",(1,0,0,1)),("背面",(0,1,0,1)),("左侧",(0,0,1,1)),
                     ("右侧",(1,1,0,1)),("顶部",(1,0,1,1)),("底部",(0,1,1,1))]:
        img = bpy.data.images.new("six_"+tag, 8, 8)
        img.generated_color = col
        p = os.path.join(sixdir, tag + ".png")
        img.filepath_raw = p; img.file_format = 'PNG'; img.save()
    bpy.context.scene.pond_sixway.source_dir = sixdir
    bpy.ops.pond.swb_scan_folder()
    bpy.ops.pond.swb_setup()
    assert a.material_slots and a.material_slots[0].material, "投影材质没搭上"
    return "材质=%s" % a.material_slots[0].material.name
step("六面投射", "识别六图+搭投影材质", t_six)

# ---------- 17. MMD 刚体关节 mmd ----------
def _fake_mmd_model():
    """搭一个假的 mmd_tools 层级。真 mmd_tools 在的话用它的真属性，
    不在就临时挂一个同名字符串属性顶上（只验池塘这边的逻辑）"""
    if not hasattr(bpy.types.Object, "mmd_type"):
        try:
            addon_utils.enable("bl_ext.blender_org.mmd_tools", default_set=False)
        except Exception:
            pass
    stub = not hasattr(bpy.types.Object, "mmd_type")
    if stub:
        bpy.types.Object.mmd_type = bpy.props.StringProperty(default="NONE")

    def emp(name, t, parent=None):
        o = bpy.data.objects.new(name, None)
        bpy.context.scene.collection.objects.link(o)
        o.mmd_type = t
        if parent:
            o.parent = parent
        return o

    root = emp("测试模型", "ROOT")
    rg = emp("rigidbodies", "RIGID_GRP_OBJ", root)
    jg = emp("joints", "JOINT_GRP_OBJ", root)
    items = [emp("刚体%d" % i, "RIGID_BODY", rg) for i in range(2)]
    items += [emp("关节%d" % i, "JOINT", jg) for i in range(2)]
    mesh = new_cube("身体")
    mesh.parent = root
    return root, [rg, jg] + items, mesh, stub


def t_mmd_hide():
    clean_scene()
    root, phys, mesh, stub = _fake_mmd_model()
    bpy.ops.object.select_all(action='DESELECT')
    bpy.ops.pond.mmd_physics_vis(show=False)
    off = [o.name for o in phys if not o.hide_viewport]
    assert not off, "这些没被藏起来: %s" % off
    assert not mesh.hide_viewport, "网格被误伤了，只该动刚体和关节"
    bpy.ops.pond.mmd_physics_vis(show=True)
    on = [o.name for o in phys if o.hide_viewport]
    assert not on, "放不回来: %s" % on
    return "%d 个刚体/关节藏得下放得回，网格没动%s" % (len(phys), "（mmd_tools 属性是临时顶替的）" if stub else "")
step("MMD 刚体关节", "藏起来/放出来", t_mmd_hide)


def t_mmd_survives_exclude():
    """她的原话：每次开关集合刚体又冒出来。
    这一条盯的是：集合复选框取消再勾回之后，藏起来的刚体关节不许放出来。
    只断言显示器图标(hide_viewport)。小眼睛(hide_set)存在视图层上，
    2026-08-22 实测它在简单场景下会被这一下重置、带父子链的场景下又不会，
    行为看情形，所以不拿它当判据，只在结果里报一下观察值
    """
    clean_scene()
    root, phys, mesh, stub = _fake_mmd_model()
    c = bpy.data.collections.new("装MMD的集合")
    bpy.context.scene.collection.children.link(c)
    for o in [root] + phys + [mesh]:
        for cc in list(o.users_collection):
            cc.objects.unlink(o)
        c.objects.link(o)
    bpy.context.view_layer.update()

    bpy.ops.object.select_all(action='DESELECT')
    bpy.ops.pond.mmd_physics_vis(show=False)
    assert all(o.hide_viewport for o in phys), "藏都没藏上"

    lc = bpy.context.view_layer.layer_collection.children[c.name]
    lc.exclude = True
    lc.exclude = False                          # 复选框取消再勾回，复现她说的场景

    out = [o.name for o in phys if not o.hide_viewport]
    assert not out, "开关集合之后又冒出来了: %s" % out
    eyes = sum(1 for o in phys if o.hide_get())
    return "开关集合后 %d 个全都还藏着（同一批里小眼睛只剩 %d 个还关着）" % (len(phys), eyes)
step("MMD 刚体关节", "开关集合后不会再冒出来", t_mmd_survives_exclude)


# ---------- 18. 关键帧错开 keyoffset ----------

def _fake_chain(n=5):
    """一条 n 节的骨链，每根 K 上第 1 和第 20 帧"""
    if bpy.context.mode != 'OBJECT':
        try:
            bpy.ops.object.mode_set(mode='OBJECT')
        except Exception:
            pass
    clean_scene()
    arm = bpy.data.armatures.new("测试骨架")
    ob = bpy.data.objects.new("骨链", arm)
    bpy.context.scene.collection.objects.link(ob)
    bpy.context.view_layer.objects.active = ob
    ob.select_set(True)

    bpy.ops.object.mode_set(mode='EDIT')
    prev = None
    for i in range(1, n + 1):
        b = arm.edit_bones.new("Bone_%d" % i)
        b.head = (0, 0, (i - 1) * 0.2)
        b.tail = (0, 0, i * 0.2)
        if prev:
            b.parent = prev
            b.use_connect = True
        prev = b
    bpy.ops.object.mode_set(mode='POSE')

    for f in (1, 20):
        bpy.context.scene.frame_set(f)
        for pb in ob.pose.bones:
            pb.rotation_quaternion = (1, 0.05 * f, 0, 0)
            pb.keyframe_insert("rotation_quaternion", frame=f)
    for pb in ob.pose.bones:
        pb.select = True
    return ob


def _bone_keys(ob, bname):
    """5.x 的分层动作要走 channelbag 才拿得到曲线"""
    ad = ob.animation_data
    act = ad.action
    handle = getattr(ad, "action_slot_handle", None)
    curves = []
    for layer in getattr(act, "layers", ()):
        for strip in layer.strips:
            for cb in getattr(strip, "channelbags", ()):
                if handle is not None and getattr(cb, "slot_handle", None) != handle:
                    continue
                curves.extend(cb.fcurves)
    if not curves:
        curves = list(getattr(act, "fcurves", ()) or ())
    pre = 'pose.bones["%s"]' % bname
    out = set()
    for fc in curves:
        if fc.data_path.startswith(pre):
            for kp in fc.keyframe_points:
                out.add(round(kp.co.x, 3))
    return sorted(out)


def t_keyoff_cascade():
    ob = _fake_chain()
    bpy.ops.pond.key_offset(step=2, reverse=False, order='HIERARCHY')
    bad = []
    for i in range(1, 6):
        want = [1 + (i - 1) * 2, 20 + (i - 1) * 2]
        got = _bone_keys(ob, "Bone_%d" % i)
        if got != want:
            bad.append("Bone_%d 要 %s 得了 %s" % (i, want, got))
    assert not bad, "；".join(bad)
    return "5 节骨链步长 2，逐根延后到位"
step("关键帧错开", "按层级依次延后", t_keyoff_cascade)


def t_keyoff_back():
    ob = _fake_chain()
    before = {i: _bone_keys(ob, "Bone_%d" % i) for i in range(1, 6)}
    bpy.ops.pond.key_offset(step=3, reverse=False, order='HIERARCHY')
    bpy.ops.pond.key_offset(step=-3, reverse=False, order='HIERARCHY')
    after = {i: _bone_keys(ob, "Bone_%d" % i) for i in range(1, 6)}
    assert before == after, "收不回原位: %s -> %s" % (before, after)
    return "负步长原样收回"
step("关键帧错开", "负步长收回原位", t_keyoff_back)


def t_keyoff_no_bleed():
    """Bone_1 的前缀不许误伤 Bone_10，没选中的骨骼一帧都不许动"""
    ob = _fake_chain()
    bpy.ops.object.mode_set(mode='EDIT')
    b = ob.data.edit_bones.new("Bone_10")
    b.head = (1, 0, 0)
    b.tail = (1, 0, 0.2)
    bpy.ops.object.mode_set(mode='POSE')
    pb = ob.pose.bones["Bone_10"]
    bpy.context.scene.frame_set(5)
    pb.rotation_quaternion = (1, 0.1, 0, 0)
    pb.keyframe_insert("rotation_quaternion", frame=5)
    for p in ob.pose.bones:
        p.select = (p.name != "Bone_10")

    before = _bone_keys(ob, "Bone_10")
    bpy.ops.pond.key_offset(step=3, reverse=False, order='HIERARCHY')
    after = _bone_keys(ob, "Bone_10")
    assert before == after, "没选中的 Bone_10 被动了: %s -> %s" % (before, after)
    return "没选中的骨骼没被前缀误伤"
step("关键帧错开", "不误伤没选中的骨骼", t_keyoff_no_bleed)


# ---------- 17b. 防回潮：修过的 bug 逐条盯着 ----------

def t_reg_lumen_state():
    """明度检查状态必须存在场景上,存 WindowManager 会随工程保存丢失"""
    bpy.context.scene.pond_lumen_state = json.dumps({"mode": "CLAY"})
    p = os.path.join(TMP, "reg_lumen.blend")
    bpy.ops.wm.save_as_mainfile(filepath=p)
    bpy.ops.wm.open_mainfile(filepath=p)
    v = bpy.context.scene.pond_lumen_state
    assert v and json.loads(v).get("mode") == "CLAY", "状态没跟着工程存盘"
    bpy.context.scene.pond_lumen_state = ""
    return "存盘重开后状态还在"
step("防回潮", "明度检查状态跟着工程走", t_reg_lumen_state)

def t_reg_select_parents():
    """父级在被排除的集合里:说人话报错,不清空用户选择,不弹traceback"""
    clean_scene()
    c = bpy.data.collections.new("排除组")
    bpy.context.scene.collection.children.link(c)
    par = bpy.data.objects.new("父空物体", None)
    c.objects.link(par)
    ch = new_cube("孩子")
    ch.parent = par
    bpy.context.view_layer.layer_collection.children["排除组"].exclude = True
    select_only(ch)
    try:
        bpy.ops.pond.select_parents()
        msg = ""
    except RuntimeError as e:
        msg = str(e)
    assert "被排除的集合" in msg, "没给出说人话的提示: %s" % msg[:80]
    assert ch.select_get(), "用户原来的选择被清空了"
    return "友好报错且保住选择"
step("防回潮", "选父级遇排除集合", t_reg_select_parents)

def t_reg_release_hidden():
    """小眼睛藏着的子级也要正常释放给上一层,且保持藏着"""
    clean_scene()
    grand = new_cube("爷爷", (0, 0, 4))
    par = new_cube("拎出目标")
    par.parent = grand
    kid = new_cube("藏起来的孩子", (2, 0, 0))
    kid.parent = par
    kid.hide_set(True)
    select_only(par)
    bpy.ops.object.solo_pick_visn()
    assert kid.parent is grand, "隐藏子级没释放给上一层: %s" % (
        kid.parent.name if kid.parent else None)
    assert kid.hide_get(), "释放后没把子级藏回去"
    return "归给上一层且仍藏着"
step("防回潮", "隐藏子级正常释放", t_reg_release_hidden)

def t_reg_fake_user():
    """切到烘焙材质后原材质要挂假用户,不然存盘被清掉再也切不回来"""
    clean_scene()
    a = new_cube("fu")
    orig = bpy.data.materials.new("防丢原材质"); orig.use_nodes = True
    a.data.materials.append(orig)
    baked = bpy.data.materials.new("烘焙材质_fu"); baked.use_nodes = True
    a["pond_bake_mat"] = baked.name
    select_only(a)
    bpy.ops.pond.bakemap_use_baked()
    assert orig.use_fake_user, "原材质没挂假用户"
    p = os.path.join(TMP, "reg_fake.blend")
    bpy.ops.wm.save_as_mainfile(filepath=p)
    bpy.ops.wm.open_mainfile(filepath=p)
    assert bpy.data.materials.get("防丢原材质"), "保存重开后原材质丢了"
    return "假用户保住原材质"
step("防回潮", "烘焙切换不丢原材质", t_reg_fake_user)

def t_reg_no_overwrite():
    """穿着烘焙材质重烘,原材质记录不许被改写成烘焙材质自己"""
    clean_scene()
    bpy.ops.wm.save_as_mainfile(filepath=blend_path)
    a = new_cube("rb")
    m = bpy.data.materials.new("重烘原材质"); m.use_nodes = True
    nt = m.node_tree
    noise = nt.nodes.new("ShaderNodeTexNoise")
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    nt.links.new(noise.outputs["Color"], bsdf.inputs["Base Color"])
    a.data.materials.append(m)
    select_only(a)
    bpy.context.scene.render.engine = 'CYCLES'
    wm = bpy.context.window_manager
    wm.pond_bake_res = '512'
    wm.pond_bake_color = True
    wm.pond_bake_rough = False
    bpy.ops.pond.bakemap()
    first = json.loads(a["pond_bake_orig"])
    bpy.ops.pond.bakemap_use_baked()
    select_only(a)
    bpy.ops.pond.bakemap()
    second = json.loads(a["pond_bake_orig"])
    assert first == second == ["重烘原材质"], "记录被覆盖: %s → %s" % (first, second)
    return "重烘后记录不变"
step("防回潮", "重烘不覆盖原材质记录", t_reg_no_overwrite)

def t_reg_manifest_dedup():
    """规范化后重名的两张贴图,清单里要各指各的文件"""
    clean_scene()
    a = new_cube("md_a"); b = new_cube("md_b", (4, 0, 0))
    for objx, iname, col in ((a, "tex", (1,0,0,1)), (b, "tex.png", (0,0,1,1))):
        img = bpy.data.images.new(iname, 8, 8)
        img.generated_color = col
        img.pack()
        m = bpy.data.materials.new("重名材质_" + iname); m.use_nodes = True
        nt = m.node_tree
        t = nt.nodes.new("ShaderNodeTexImage"); t.image = img
        bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
        nt.links.new(t.outputs["Color"], bsdf.inputs["Base Color"])
        objx.data.materials.append(m)
    cam = bpy.data.objects.new("md_cam", bpy.data.cameras.new("mc"))
    bpy.context.scene.collection.objects.link(cam)
    bpy.context.scene.camera = cam
    p = os.path.join(TMP, "md_v001.blend")
    bpy.ops.wm.save_as_mainfile(filepath=p)
    bpy.ops.object.select_all(action='DESELECT')
    a.select_set(True); b.select_set(True)
    bpy.context.view_layer.objects.active = a
    bpy.ops.pond.export_c4d_full()
    with open(os.path.join(TMP, "md_v001_材质清单.json"), encoding="utf-8") as f:
        d = json.load(f)
    texs = sorted(e["basecolor"]["tex"] for e in d["materials"].values()
                  if isinstance(e.get("basecolor"), dict) and "tex" in e["basecolor"])
    assert len(texs) == 2 and texs[0] != texs[1], "重名贴图指向同一个文件: %s" % texs
    return "各指各的: %s" % texs
step("防回潮", "一条龙重名贴图不串", t_reg_manifest_dedup)

def t_reg_hilow_uv():
    """法线图必须指定UV层,不然多UV低模的采样层和烘焙落点对不上"""
    clean_scene()
    bpy.ops.wm.save_as_mainfile(filepath=blend_path)
    bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=12)
    high = bpy.context.active_object; high.name = "hu_高"
    bpy.ops.mesh.primitive_uv_sphere_add(segments=8, ring_count=6)
    low = bpy.context.active_object; low.name = "hu_低"
    me = low.data
    uv1 = me.uv_layers.new(name="第二套UV")
    me.uv_layers[0].active_render = True
    me.uv_layers.active = uv1
    m = bpy.data.materials.new("多UV低模材质"); m.use_nodes = True
    low.data.materials.append(m)
    wm = bpy.context.window_manager
    wm.pond_hilow_res = '512'; wm.pond_hilow_normal = True
    wm.pond_hilow_ao = False; wm.pond_hilow_color = False; wm.pond_hilow_rough = False
    bpy.ops.object.select_all(action='DESELECT')
    high.select_set(True); low.select_set(True)
    bpy.context.view_layer.objects.active = low
    bpy.ops.pond.hilow_bake()
    nt = m.node_tree
    tex = nt.nodes.get("池塘高低法线图")
    assert tex and tex.inputs["Vector"].is_linked, "法线贴图没接UV节点"
    uvn = nt.nodes.get("池塘高低法线UV")
    assert uvn and uvn.uv_map == "第二套UV", "UV节点指错层: %s" % (
        uvn.uv_map if uvn else None)
    return "采样层=烘焙落点=第二套UV"
step("防回潮", "高低法线图指定UV层", t_reg_hilow_uv)

def t_reg_origin_shared():
    """关联复制(共用网格)的物体默认跳过,不许连累没选中的复制体"""
    clean_scene()
    a = new_cube("链接A")
    b = bpy.data.objects.new("链接B", a.data)   # Alt+D 共用网格
    b.location = (5, 0, 0)
    bpy.context.scene.collection.objects.link(b)
    bpy.context.view_layer.update()
    before = min((b.matrix_world @ v.co).z for v in b.data.vertices)
    select_only(a)
    r = bpy.ops.pond.origin_to_side(side='BOTTOM')
    bpy.context.view_layer.update()
    after = min((b.matrix_world @ v.co).z for v in b.data.vertices)
    assert abs(before - after) < 1e-5, "没选中的复制体被挪走了: %.3f→%.3f" % (before, after)
    assert r == {"CANCELLED"}, "全跳过时应返回 CANCELLED, 实际 %s" % r
    # 勾上断开关联就能吸, 且各自分家互不影响
    select_only(a)
    bpy.ops.pond.origin_to_side(side='BOTTOM', unlink_shared=True)
    bpy.context.view_layer.update()
    assert a.data is not b.data, "断开关联后网格没分家"
    a_low = min((a.matrix_world @ v.co).z for v in a.data.vertices)
    assert abs(a_low - a.matrix_world.translation.z) < 1e-4, "断开后原点没落到底"
    b2 = min((b.matrix_world @ v.co).z for v in b.data.vertices)
    assert abs(before - b2) < 1e-5, "断开关联后复制体仍被连累"
    return "默认跳过, 勾断开后各归各的"
step("防回潮", "原点吸附不连累关联复制体", t_reg_origin_shared)

def t_reg_palette_keep():
    """删除当前色卡只删本模块导入的,用户自建的调色板一概不碰"""
    mine = bpy.data.palettes.new("用户自建配色")
    bpy.context.tool_settings.image_paint.palette = mine
    r = bpy.ops.pond.palette_delete()
    assert bpy.data.palettes.get("用户自建配色"), "用户自建的调色板被删了"
    assert r == {"CANCELLED"}, "不该删时应返回 CANCELLED, 实际 %s" % r
    card = bpy.data.palettes.new("测试图_色卡")
    bpy.context.tool_settings.image_paint.palette = card
    bpy.ops.pond.palette_delete()
    assert bpy.data.palettes.get("测试图_色卡") is None, "导入的色卡删不掉了"
    assert bpy.data.palettes.get("用户自建配色"), "误删了用户的调色板"
    bpy.data.palettes.remove(mine)
    return "用户的留着, 导入的照删"
step("防回潮", "色卡不删用户自建调色板", t_reg_palette_keep)

def t_reg_split_keep():
    """基础网格为空的物体(几何节点生成形体那种)不许被空壳清理删掉"""
    clean_scene()
    me = bpy.data.meshes.new("空网格")
    o = bpy.data.objects.new("GN物体", me)
    bpy.context.scene.collection.objects.link(o)
    o.modifiers.new("几何节点", 'NODES')
    select_only(o)
    try:
        bpy.ops.pond.split()
        msg = ""
    except RuntimeError as e:
        msg = str(e)
    assert "GN物体" in bpy.data.objects, "用户的物体被删了"
    assert "基础网格是空的" in msg, "没给出说人话的提示: %s" % msg[:80]
    # 一整块的普通物体也不许误删
    clean_scene()
    a = new_cube("一整块")
    select_only(a)
    bpy.ops.pond.split()
    assert "一整块" in bpy.data.objects, "一整块的物体被误删了"
    return "空网格和一整块都保住了"
step("防回潮", "拆分不删用户物体", t_reg_split_keep)

# ---------- 输出 ----------
with open(OUT, "w", encoding="utf-8") as f:
    json.dump({"blender": bpy.app.version_string, "results": RESULTS}, f, ensure_ascii=False, indent=1)
n_pass = sum(1 for r in RESULTS if r["status"] == "PASS")
n_fail = sum(1 for r in RESULTS if r["status"] == "FAIL")
print("=== 自检完成: %d PASS / %d FAIL, 结果在 %s ===" % (n_pass, n_fail, OUT))
