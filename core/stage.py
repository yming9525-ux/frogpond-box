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

    @classmethod
    def poll(cls, context):
        return context.active_object is not None

    def execute(self, context):
        target = context.active_object
        center = target.matrix_world.translation.copy()

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
        self.report({"INFO"}, f"摄像机组就位：{root.name} > {orbit.name} > {cam.name}")
        return {"FINISHED"}


_classes = (
    POND_OT_cam_rig_build,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
