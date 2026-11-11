"""紫鸟 CLI 浏览器实现。

与 WebDriverBrowser 平级，共同继承 Browser 适配器基类。

分层（见框架图）：

- 传输层（_command / _invoke / _run）只调平台、只抛原始异常，不写日志、
  不翻译为统一异常。退出码、stdout、stderr 保留在异常对象上。
- 公开方法（open / close / inspect / find_windows）调底层，catch 原始异常，
  用基类的 ConnectorCode 翻译成统一异常，写 resource_log，再抛统一异常。
  原始异常保留在异常链中。

适配器自己写日志，但事件码只能取 ConnectorCode：两种连接方式不说两套事件名。
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import shutil
import time

from ..logs.errors import exception_details
from ..logs.writer import LogWriter
from ..settings.timing import TimingSettings
from .browser import Browser, ConnectorCode
from .errors import ConnectorError, Foreign


def parse_cli_json(stdout: str) -> dict:
    decoder = json.JSONDecoder()
    for index, char in enumerate(stdout):
        if char == "{":
            try:
                value, _ = decoder.raw_decode(stdout[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict) and isinstance(value.get("ok"), bool):
                return value
    raise RuntimeError("Ziniao CLI returned no valid result object")


class CliBrowser(Browser):
    """通过本机 ziniao-cli 操作店铺窗口。"""

    label = "紫鸟 CLI"

    def __init__(self, store, stores, cli="ziniao-cli", timeout=None):
        super().__init__(store, stores)
        self.cli, self.timeout = str(cli), timeout
        self.log = LogWriter(store, "resource_log")

    # ------------------------------------------------------------ 传输层
    # 只调平台、只抛原始异常：exit/stdout/stderr 挂在异常对象上。不写日志。
    def _command(self):
        executable = shutil.which(self.cli)
        if not executable and Path(self.cli).is_file():
            executable = str(Path(self.cli).resolve())
        if os.name == "nt":
            executable = executable or shutil.which(self.cli + ".cmd")
            if executable:
                ps1 = Path(executable).with_suffix(".ps1")
                if ps1.is_file():
                    powershell = shutil.which("powershell.exe") or shutil.which("pwsh.exe")
                    if not powershell:
                        raise RuntimeError("PowerShell is required to invoke ziniao-cli.ps1")
                    return [powershell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(ps1)]
                if Path(executable).suffix.lower() != ".exe":
                    raise RuntimeError("Use ziniao-cli.ps1 or an executable; shell command construction is disabled")
        if not executable:
            raise RuntimeError("ziniao-cli was not found on PATH")
        return [executable]

    async def _invoke(self, args):
        process = await asyncio.create_subprocess_exec(*self._command(), *args,
                                                       stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        communication = asyncio.create_task(process.communicate())
        try:
            stdout, stderr = await asyncio.wait_for(
                asyncio.shield(communication),
                self.timeout if self.timeout is not None else TimingSettings(self.store).read()["cli_timeout_seconds"])
        except (asyncio.TimeoutError, asyncio.CancelledError) as exc:
            if os.name == "nt":
                killer = await asyncio.create_subprocess_exec("taskkill.exe", "/PID", str(process.pid), "/T", "/F",
                                                              stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
                await killer.wait()
            elif process.returncode is None:
                process.kill()
            try:
                stdout, stderr = await asyncio.wait_for(communication, 5)
                exc.stdout = stdout.decode("utf-8", errors="replace")
                exc.stderr = stderr.decode("utf-8", errors="replace")
            except asyncio.TimeoutError:
                pass
            raise
        return process.returncode, stdout.decode("utf-8", errors="replace"), stderr.decode("utf-8", errors="replace")

    async def _run(self, *args, allow_empty_close=False):
        """调平台并做状态码判断。成功返回 (result, raw)；失败抛原始异常。不写日志。"""
        started_at = time.time()
        start = time.monotonic()
        code, stdout, stderr = await self._invoke(args)
        raw = {"args": list(args), "returncode": code,
               "started_at": started_at, "returned_at": time.time(),
               "round_trip_seconds": time.monotonic() - start,
               "stdout": stdout, "stderr": stderr}
        if allow_empty_close and args[:2] == ("store", "close") and code == 0 and not stdout.strip():
            # This CLI version emits only a success banner on stderr for close.
            # This is not confirmation: close() still checks running=False.
            return {"close_reply_requires_verification": True}, raw
        try:
            result = parse_cli_json(stdout)
        except RuntimeError as exc:
            raise self._cli_failure(args, code, stdout, stderr) from exc
        if code != 0 or result["ok"] is not True:
            raise self._cli_failure(args, code, stdout, stderr)
        return result, raw

    def _cli_failure(self, args, code, stdout, stderr):
        """把 CLI 退出码翻译成一条带原始证据的异常。状态码翻译只发生在这里。"""
        failure = RuntimeError(f"Ziniao CLI {args!r}: exit={code}; stdout={stdout}; stderr={stderr}")
        failure.returncode = code
        failure.stdout = stdout
        failure.stderr = stderr
        return failure

    # ------------------------------------------------------------ 公开接口
    # 调底层 → 落原始证据 → 翻译成统一异常 → 写 resource_log → 抛统一异常。
    def _record(self, code, content, level="INFO"):
        self.log.write(code.value, content, level=level)

    async def _observe(self, operation, args, *, extra=None, **run_kwargs):
        """调底层的唯一入口：原始证据先落库，失败仍抛原始异常，翻译由调用方完成。"""
        extra = extra or {}
        try:
            result, raw = await self._run(*args, **run_kwargs)
        except (asyncio.TimeoutError, asyncio.CancelledError) as exc:
            self._record(ConnectorCode.INTERRUPTED,
                         {"operation": operation, **extra,
                          "stdout": getattr(exc, "stdout", None),
                          "stderr": getattr(exc, "stderr", None),
                          **exception_details(exc)}, level="ERROR")
            raise
        except Exception as exc:
            self._record(ConnectorCode.ERROR,
                         {"operation": operation, **extra,
                          "returncode": getattr(exc, "returncode", None),
                          "stdout": getattr(exc, "stdout", None),
                          "stderr": getattr(exc, "stderr", None),
                          **exception_details(exc)}, level="ERROR")
            raise
        self._record(ConnectorCode.RAW, {"operation": operation, **extra, **raw})
        return result

    async def inspect(self, window_ref: str) -> bool | None:
        self._require_shop(window_ref)
        try:
            result = await self._observe("page extract", ("page", "extract", "--mode", "store",
                                                          "--store-id", window_ref))
        except Exception as exc:
            raise ConnectorError(f"窗口 {window_ref} 检查请求失败，远端结果不明：{exc}") from exc
        data = result.get("data", {})
        if not isinstance(data, dict) or str(data.get("storeId", window_ref)) != window_ref:
            raise ConnectorError(f"窗口 {window_ref} 检查返回格式或店铺标识不匹配：{result!r}")
        running = data.get("running")
        if not isinstance(running, bool):
            raise ConnectorError(f"窗口 {window_ref} 检查未返回布尔 running：{result!r}")
        return running

    async def open(self, shop_id: str) -> str:
        self._require_shop(shop_id)
        try:
            running = await self.inspect(shop_id)
        except Exception as exc:
            raise ConnectorError(f"店铺 {shop_id} 开窗前检查失败，远端结果不明：{exc}") from exc
        if running is True:
            self._record(ConnectorCode.FOREIGN,
                         {"operation": "open", "store_id": shop_id,
                          "reason": "开窗前窗口已在运行，不接管也不关闭"}, level="WARNING")
            raise Foreign(f"店铺 {shop_id} 窗口已在运行，归属未经工作台确认，拒绝接管")
        try:
            result = await self._observe("store open", ("store", "open", "--id", shop_id,
                                                        "--expected-name", self.stores[shop_id],
                                                        "--url", "about:blank"))
        except Exception as exc:
            raise ConnectorError(f"店铺 {shop_id} 开窗请求失败，远端结果不明：{exc}") from exc
        data = result.get("data", {})
        if not isinstance(data, dict) or data.get("reused") is not False:
            self._record(ConnectorCode.FOREIGN,
                         {"operation": "open", "store_id": shop_id,
                          "reason": "开窗复用了已有窗口，归属无法确认"}, level="WARNING")
            raise Foreign(f"店铺 {shop_id} 开窗复用了已有窗口，归属未经工作台确认")
        if str(data.get("storeId", shop_id)) != shop_id:
            raise ConnectorError(f"开窗返回了非预期的店铺标识：{result!r}")
        try:
            confirmed = await self.inspect(shop_id)
        except Exception as exc:
            raise ConnectorError(f"店铺 {shop_id} 开窗后检查失败，远端结果不明：{exc}") from exc
        if confirmed is not True:
            raise ConnectorError(f"店铺 {shop_id} 开窗请求已返回，但未确认窗口在运行")
        self._record(ConnectorCode.OPENED, {"operation": "open", "store_id": shop_id})
        return shop_id

    async def close(self, window_ref: str) -> None:
        self._require_shop(window_ref)
        try:
            running = await self.inspect(window_ref)
        except Exception as exc:
            raise ConnectorError(f"窗口 {window_ref} 关闭前检查失败，远端结果不明：{exc}") from exc
        if running is False:
            self._record(ConnectorCode.CLOSED,
                         {"operation": "close", "store_id": window_ref, "reason": "关闭前已不在运行"})
            return
        try:
            await self._observe("store close", ("store", "close", "--id", window_ref),
                                allow_empty_close=True)
        except Exception as exc:
            raise ConnectorError(f"窗口 {window_ref} 关闭请求失败，远端结果不明：{exc}") from exc
        try:
            confirmed = await self.inspect(window_ref)
        except Exception as exc:
            raise ConnectorError(f"窗口 {window_ref} 关闭后检查失败，远端结果不明：{exc}") from exc
        if confirmed is not False:
            raise ConnectorError(f"窗口 {window_ref} 关闭请求已返回，但未确认窗口已关闭")
        self._record(ConnectorCode.CLOSED, {"operation": "close", "store_id": window_ref})

    async def find_windows(self, shop_id: str) -> list[str]:
        self._require_shop(shop_id)
        try:
            running = await self.inspect(shop_id)
        except Exception as exc:
            raise ConnectorError(f"店铺 {shop_id} 窗口查询失败，远端结果不明：{exc}") from exc
        return [shop_id] if running else []
