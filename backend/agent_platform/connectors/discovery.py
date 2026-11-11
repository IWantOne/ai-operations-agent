"""Discover WebDriver only on ports owned by the local Ziniao client."""
import asyncio
import http.client
import json
import os
import shutil
import subprocess
from uuid import uuid4
from ..logs.errors import exception_details
from ..logs.writer import LogWriter

def client_ports(timeout):
    if os.name != "nt":
        raise ValueError("当前自动检测支持 Windows，请在高级设置中填写客户端端口。")
    powershell = shutil.which("powershell.exe") or shutil.which("pwsh.exe")
    if not powershell:
        raise ValueError("未找到 PowerShell，无法检测本机端口。")
    script = """
$ErrorActionPreference = 'Stop'
$clients = @(Get-CimInstance Win32_Process | Where-Object {
    $_.Name -in 'ziniao.exe','SuperBrowser.exe','ziniaobrowser.exe'
})
$ports = @(Get-NetTCPConnection -State Listen | Where-Object {
    $_.OwningProcess -in $clients.ProcessId -and
    $_.LocalAddress -in '127.0.0.1','0.0.0.0','::','::1'
} | Select-Object -ExpandProperty LocalPort -Unique)
ConvertTo-Json -InputObject $ports -Compress
"""
    result = subprocess.run([powershell, "-NoProfile", "-NonInteractive", "-Command", script],
                            capture_output=True, timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError(f"读取本机监听端口失败：exit={result.returncode}; stdout={result.stdout!r}; stderr={result.stderr!r}")
    ports = json.loads(result.stdout.decode("utf-8-sig"))
    return [p for p in ports if type(p) is int and 1 <= p <= 65535][:32]


def is_webdriver(port, timeout):
    request_id = str(uuid4())
    client = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        body = json.dumps({"action": "getRunningInfo", "requestId": request_id})
        client.request("POST", "/", body, {"Content-Type": "application/json"})
        response = client.getresponse()
        raw = response.read(1024 * 1024)
        if response.status != 200:
            raise RuntimeError(f"端口 {port} HTTP {response.status}: {raw!r}")
        result = json.loads(raw)
        valid = (isinstance(result, dict) and str(result.get("statusCode")) == "0"
                and result.get("requestId") == request_id
                and isinstance(result.get("browsers"), list))
        if not valid:
            raise ValueError(f"端口 {port} 返回内容未满足 WebDriver 协议：{result!r}")
        return True
    finally:
        client.close()


async def detect_webdriver(store, policy):
    ports = await asyncio.to_thread(client_ports, policy["discovery_scan_seconds"])
    if not ports:
        raise ValueError("未发现紫鸟客户端拥有的本机监听端口")
    log = LogWriter(store, "resource_log")
    results = await asyncio.gather(*(asyncio.to_thread(is_webdriver, port, policy["discovery_probe_seconds"]) for port in ports), return_exceptions=True)
    errors, found = [], []
    for port, result in zip(ports, results):
        if isinstance(result, Exception):
            errors.append(result)
            log.write("WEBDRIVER_DISCOVERY_PROBE", {"port": port, **exception_details(result)}, level="ERROR")
        elif result:
            found.append(port)
        else:
            log.write("WEBDRIVER_DISCOVERY_PROBE", {"port":port,"error":"响应未满足 WebDriver requestId / statusCode / browsers 协议"}, level="WARNING")
    if not found:
        if errors:
            raise errors[0]
        raise ValueError(f"已探测端口 {ports!r}，没有响应满足 WebDriver 协议；探测证据已记录")
    if len(found) > 1:
        raise ValueError("检测到多个 WebDriver 端口，请在高级设置中选择：" + "、".join(map(str, found)))
    return {"port": found[0]}
