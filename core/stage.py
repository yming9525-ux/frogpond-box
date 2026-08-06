# 搭建类：摄像机组 / 约束灯光 / 清理空物体 / 打开文件夹（合并核心）
# 合并自 Bekkan/STOOL_part/StageOps.py + Pond/cam_rig.py。
# Bekkan 两套机组（C-P / C-SP-ZT）与 Pond 的简洁机组是不同设计，双双保留；
# Bekkan 原版 op 保留原 bl_idname。
# （面板在 ui/bekkan/panels.py 与 ui/pond/panels/cam_rig.py）
import os
import platform
import subprocess
import bpy

from mathutils import Vector

from .hierarchy import centro_global


class POND_OT_cam_rig_build(bpy.types.Operator):
    """以激活物体为中心搭 Root>Orbit>Cam 三级摄像机组"""
    bl_idname = "pond.cam_rig_build"
    bl_label = "搭建摄像机组"
    bl_options = {"REGISTER", "UNDO"}

    height_offset: bpy.props.FloatProperty(name="高度偏移", default=3.0)
    back_offset: bpy.props.FloatProperty(name="后退距离", default=8.0)
    focal: bpy.props.FloatProperty(name="焦距 mm", default=50.0, min=1.0)
    constraint_name: bpy.props.StringProperty(
        name="对准约束名", default="对准目标",
        description="想在别处认出这个约束就靠这个名字")

    # 没有激活物体也让点：删掉上一组后 active 会变 None,
    # 卡着 poll 会让按钮一直是灰的，得先随便点个东西才活过来
    def execute(self, context):
        target = context.active_object
        center = (target.matrix_world.translation.copy() if target
                  else Vector((0.0, 0.0, 0.0)))

        root = bpy.data.objects.new("镜头Root", None)
        context.scene.collection.objects.link(root)
        root.location = center

        orbit = bpy.data.objects.new("Orbit", None)
        context.scene.collection.objects.link(orbit)
        orbit.parent = root

        cam_data = bpy.data.cameras.new("镜头Cam")
        cam = bpy.data.objects.new("镜头Cam", cam_data)
        context.scene.collection.objects.link(cam)
        cam.parent = orbit
        cam.location = Vector((0, -self.back_offset, self.height_offset))
        cam_data.lens = self.focal

        if target is not None:      # 没有目标就只搭机组, 朝向自己转
            point = cam.constraints.new("TRACK_TO")
            point.name = self.constraint_name
            point.target = target
            point.track_axis = "TRACK_NEGATIVE_Z"
            point.up_axis = "UP_Y"
            cam_data.dof.use_dof = True
            cam_data.dof.focus_object = target

        context.scene.camera = cam
        context.view_layer.objects.active = cam
        cam.select_set(True)
        tail = "" if target is not None else "（没选物体，以原点为中心，没加对准约束）"
        self.report({"INFO"},
                    f"摄像机组就位：{root.name} > {orbit.name} > {cam.name}" + tail)
        return {"FINISHED"}


class POND_OT_make_cam_rig(bpy.types.Operator):
    """围绕选中物体（没有就在原点）搭一套短片摄像机组：
    根管位置、环绕层管转、注视球管朝向、对焦块管景深，两个目标都能单独拖"""
    bl_idname = "pond.make_cam_rig"
    bl_label = "搭短片机组"
    bl_options = {"REGISTER", "UNDO"}

    use_black_frame: bpy.props.BoolProperty(
        name="黑框区域", default=True,
        description="相机视图外全黑，构图不被场外抢戏")
    use_dof: bpy.props.BoolProperty(name="开景深", default=True)
    use_motion_blur: bpy.props.BoolProperty(name="开动态模糊", default=True)

    def execute(self, context):
        sel = context.selected_objects
        if sel:
            center = centro_global(sel)
            center = Vector(center)
        else:
            center = Vector((0, 0, 0))

        def link(o):
            context.scene.collection.objects.link(o)

        root = bpy.data.objects.new("CAM_根", None)
        root.empty_display_type = "PLAIN_AXES"
        root.empty_display_size = 1.2
        link(root)
        root.location = center

        orbit = bpy.data.objects.new("CAM_环绕层", None)
        orbit.empty_display_type = "CIRCLE"
        orbit.empty_display_size = 4.0
        link(orbit)
        orbit.parent = root

        cam_data = bpy.data.cameras.new("短片摄像机")
        cam = bpy.data.objects.new("短片摄像机", cam_data)
        link(cam)
        cam.parent = orbit
        cam.location = (0, -6, 2)

        target = bpy.data.objects.new("CAM_注视目标", None)
        target.empty_display_type = "SPHERE"
        target.empty_display_size = 0.3
        link(target)
        target.parent = root

        dof_target = bpy.data.objects.new("CAM_对焦目标", None)
        dof_target.empty_display_type = "CUBE"
        dof_target.empty_display_size = 0.18
        link(dof_target)
        dof_target.parent = root

        con = cam.constraints.new("TRACK_TO")
        con.target = target
        con.track_axis = "TRACK_NEGATIVE_Z"
        con.up_axis = "UP_Y"

        cam_data.dof.use_dof = self.use_dof
        cam_data.dof.focus_object = dof_target

        if self.use_black_frame:
            cam_data.show_passepartout = True
            cam_data.passepartout_alpha = 1.0
        if self.use_motion_blur:
            context.scene.render.use_motion_blur = True
            eevee = getattr(context.scene, "eevee", None)
            if eevee and hasattr(eevee, "use_motion_blur"):
                eevee.use_motion_blur = True

        context.scene.camera = cam
        bpy.ops.object.select_all(action="DESELECT")
        cam.select_set(True)
        context.view_layer.objects.active = cam
        extras = [s for s, on in (("黑框", self.use_black_frame),
                                  ("景深", self.use_dof),
                                  ("动态模糊", self.use_motion_blur)) if on]
        self.report({"INFO"},
                    "短片机组搭好了" + ("，已开：" + "/".join(extras) if extras else ""))
        return {"FINISHED"}


_classes = (
    POND_OT_cam_rig_build,
    POND_OT_make_cam_rig,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
