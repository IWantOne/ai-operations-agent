"""Windows 进程管理：Job Object 挂接、崩溃连带回收、taskkill 兜底。"""
import asyncio
import subprocess

from .supervisor import ProcessError, ProcessSupervisor
from .windows_job import WindowsJob

CREATE_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
CREATE_SUSPENDED = 0x4
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class WindowsSupervisor(ProcessSupervisor):
    NAME = "windows"
    label = "Windows Job Object"

    def prepare(self):
        return WindowsJob()

    def options(self) -> dict:
        # 先挂进 Job 再放行：用户代码不会在归属确认之前跑起来。
        return {"creationflags": CREATE_NEW_PROCESS_GROUP | CREATE_SUSPENDED}

    def start(self, process, handle) -> None:
        handle.attach(process.pid)
        handle.resume(process.pid)

    def watch(self, process, handle):
        async def close_when_exited():
            # 根进程退出后关闭 Job，顺带清掉仍持有输出管道的子孙进程。
            while process.returncode is None:
                await asyncio.sleep(.01)
            self.release(handle)

        return close_when_exited()

    async def stop(self, process, handle) -> None:
        if handle is not None:
            self.release(handle)  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            return
        if process.returncode is not None:
            return
        killer = await asyncio.create_subprocess_exec(
            "taskkill", "/PID", str(process.pid), "/T", "/F",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            creationflags=CREATE_NO_WINDOW)
        stdout, stderr = await killer.communicate()
        if killer.returncode != 0 and process.returncode is None:
            # 进程可能正在退出；先确认再判定停止失败。
            try:
                await asyncio.wait_for(asyncio.shield(process.wait()), 0.1)
            except TimeoutError as exc:
                raise ProcessError(f"Cannot stop owned process {process.pid}: {stdout!r} {stderr!r}") from exc

    def release(self, handle) -> None:
        if handle is not None:
            handle.close()
