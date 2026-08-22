# core 逻辑层注册中心：全部 Operator / PropertyGroup / 纯函数，无任何 Panel。
from . import (snapshot, hierarchy, stage, organize, lumen, synccheck,
               c4d_bridge, preset_lib, palette, trace2solid, sixproj,
               lightdesk, bakemap, hilow, splitter, renderlayers, mmd)

_MODULES = (
    snapshot, hierarchy, stage, organize, lumen, synccheck,
    c4d_bridge, preset_lib, palette, trace2solid, sixproj,
    lightdesk, bakemap, hilow, splitter, renderlayers, mmd,
)


def register():
    for m in _MODULES:
        m.register()


def unregister():
    for m in reversed(_MODULES):
        m.unregister()
