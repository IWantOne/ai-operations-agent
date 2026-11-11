"""进程管理适配器：基类规定接口与码表，各平台实现自己的进程控制。

与 ``connectors.Browser``、``database.DatabaseAdapter`` 同一形状：

- 基类钉住创建参数、挂接、停止、释放和退出收尾，并给出 ``ProcessCode``；
  少声明 ``NAME`` 的实现类定义时直接失败。
- 实现只碰本平台的进程控制，不写日志；``runtime_log`` 由 ScriptRuntime 写。
- 启动失败保留原始 OSError（调用点需要区分文件不存在、权限不足等）；
  停止失败抛 ``ProcessError``，原始证据留在消息和 ``__cause__`` 上。
"""
from __future__ import annotations

from enum import Enum


class ProcessCode(str, Enum):
    STOP_FAILED = "STOP_FAILED"


class ProcessError(RuntimeError):
    """进程控制失败。原始证据保留在消息和 __cause__ 上。"""

    def __init__(self, message, code=ProcessCode.STOP_FAILED):
        super().__init__(message)
        self.code = code


class ProcessSupervisor:
    """进程管理后端：只规定接口。"""

    NAME = ""
    label = "进程管理"

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if not cls.__dict__.get("NAME"):
            raise TypeError(f"{cls.__name__} 必须声明 NAME")

    def prepare(self):
        """子进程创建前取得平台句柄；没有句柄的平台返回 None。"""
        raise NotImplementedError

    def options(self) -> dict:
        """交给 create_subprocess_exec 的平台参数。"""
        raise NotImplementedError

    def start(self, process, handle) -> None:
        """子进程已创建、用户代码尚未运行：挂接并放行。"""
        raise NotImplementedError

    def watch(self, process, handle):
        """子进程退出后需要收尾时返回可等待对象，否则返回 None。"""
        return None

    async def stop(self, process, handle) -> None:
        raise NotImplementedError

    def release(self, handle) -> None:
        raise NotImplementedError
