"""POSIX 进程管理：独立会话 + 进程组信号。

没有 Job Object 那种内核级连带回收，靠 start_new_session 建独立进程组，
停止时整组发信号。服务自身崩溃时子进程不会被内核回收，这是与 Windows
实现的已知差异，写在这里而不是藏进调用点。
"""
import os
import signal

from .supervisor import ProcessSupervisor


class PosixSupervisor(ProcessSupervisor):
    NAME = "posix"
    label = "POSIX 进程组"

    def prepare(self):
        return None

    def options(self) -> dict:
        return {"start_new_session": True}

    def start(self, process, handle) -> None:
        return None

    async def stop(self, process, handle) -> None:
        if process.returncode is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    def release(self, handle) -> None:
        return None
