"""Codex 工具：把本机 codex-cli 当成一个工具调用。

- 命令、额外参数、单次上限来自「配置 → 工具」（platform_setting 的 tools.codex）。
- command 留空时使用 PATH 中的 codex；找不到就明确报错，不猜路径。
- 结果照实返回退出码、stdout、stderr；非零退出抛错并保留证据；超时先杀进程树。
- 日志由 ToolRegistry 写 tool_call_log（tool_start / tool_result / tool_error）。
"""
from __future__ import annotations

import asyncio
from pathlib import Path
import shlex
import shutil
import sys

PREVIEW_LIMIT = 20000


def resolve_codex(command):
    """返回可执行文件路径；留空时用 PATH 中的 codex。"""
    if command:
        candidate = shutil.which(command)
        if candidate:
            return candidate
        if Path(command).is_file():
            return str(Path(command))
        raise RuntimeError(f"Codex 可执行文件不存在：{command}")
    for name in ("codex", "codex.exe", "codex.cmd"):
        candidate = shutil.which(name)
        if candidate:
            return candidate
    raise RuntimeError("未找到 codex-cli；请在「配置 → 工具」填写可执行文件路径，或把 codex 加入 PATH")


def _preview(text):
    if len(text) <= PREVIEW_LIMIT:
        return text, False
    return text[:PREVIEW_LIMIT], True


async def run_codex(settings, prompt, cwd=None, timeout=600):
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("codex 需要非空的 prompt")
    executable = resolve_codex(settings.get("codex_command", ""))
    extra = shlex.split(settings.get("codex_args", ""))
    argv = [executable, "exec", *extra, prompt]
    process = await asyncio.create_subprocess_exec(
        *argv, cwd=cwd, stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout)
    except asyncio.TimeoutError as exc:
        await _kill(process)
        raise TimeoutError(f"codex 调用超过 {timeout} 秒，已停止进程树") from exc
    out, out_cut = _preview(stdout.decode("utf-8", errors="replace"))
    err, err_cut = _preview(stderr.decode("utf-8", errors="replace"))
    result = {"returncode": process.returncode, "stdout": out, "stderr": err,
              "stdout_truncated": out_cut, "stderr_truncated": err_cut}
    if process.returncode != 0:
        # 非零退出不包装成成功；原始证据挂在异常上，ToolRegistry 会写 tool_call_log。
        failure = RuntimeError(f"codex 退出码 {process.returncode}：{err or out or '对端未提供更具体原因'}")
        failure.returncode = process.returncode
        failure.stdout = out
        failure.stderr = err
        raise failure
    return result


async def _kill(process):
    if process.returncode is not None:
        return
    if sys.platform == "win32":
        killer = await asyncio.create_subprocess_exec(
            "taskkill.exe", "/PID", str(process.pid), "/T", "/F",
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        await killer.wait()
    else:
        process.kill()
    try:
        await asyncio.wait_for(process.wait(), 5)
    except asyncio.TimeoutError:
        pass


def register_codex(manager):
    async def codex(prompt, cwd=None, **extra):
        if extra:
            raise ValueError(f"codex 不接受参数：{sorted(extra)}")
        timeout = manager.timing_settings.read()["codex_timeout_seconds"]
        return await run_codex(manager.tool_settings.read(), prompt, cwd, timeout)

    manager.tools.register("codex", codex)
