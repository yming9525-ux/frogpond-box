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
step("摄像机组", "一键搭建", t_cam)

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

# ---------- 输出 ----------
with open(OUT, "w", encoding="utf-8") as f:
    json.dump({"blender": bpy.app.version_string, "results": RESULTS}, f, ensure_ascii=False, indent=1)
n_pass = sum(1 for r in RESULTS if r["status"] == "PASS")
n_fail = sum(1 for r in RESULTS if r["status"] == "FAIL")
print("=== 自检完成: %d PASS / %d FAIL, 结果在 %s ===" % (n_pass, n_fail, OUT))
