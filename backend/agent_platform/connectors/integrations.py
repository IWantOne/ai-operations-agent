"""外部应用接入客户端：API 与 MCP 两种传输，只做通信，不做业务判断。

- API：按配置的认证方式调用 HTTP，返回对端状态与正文；非 2xx 抛 ``IntegrationError``，
  保留状态、正文和业务码。
- MCP：以 stdio 启动 MCP 服务，按 JSON-RPC 完成 initialize、tools/list、tools/call。
- 本层不写日志，日志由工具层写 tool_call_log。
"""
from __future__ import annotations

import asyncio
import json
import shlex
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_IDLE = 3600
MCP_PROTOCOL = "2024-11-05"


class IntegrationError(RuntimeError):
    """接入调用失败。保留对端的 HTTP 状态、正文和业务码。"""

    def __init__(self, message, *, provider=None, status=None, body=None, code=None):
        super().__init__(message)
        self.provider = provider
        self.status = status
        self.body = body
        self.code = code


def _pick(body, field):
    if not isinstance(body, dict):
        return None
    if field in body:
        return body[field]
    data = body.get("data")
    if isinstance(data, dict) and field in data:
        return data[field]
    return None


def _decode(raw):
    text = raw.decode("utf-8", errors="replace")
    try:
        return json.loads(text)
    except ValueError:
        return text


class ApiClient:
    def __init__(self, settings, timeout=30, provider=None):
        base_url = (settings.get("base_url") or "").rstrip("/")
        if not base_url:
            raise ValueError(f"{provider or '该接入方'} 还没有填写部署地址")
        self.provider = provider
        self.base_url = base_url
        self.app_id = settings.get("app_id", "")
        self.app_secret = settings.get("app_secret", "")
        self.auth = settings.get("auth", "none")
        self.token_path = settings.get("token_path", "")
        self.token_field = settings.get("token_field", "access_token")
        self.timeout = timeout

    def token(self):
        if not self.app_id or not self.app_secret:
            raise ValueError(f"{self.provider or '该接入方'} 还没有填写 App ID 和 App Secret")
        payload = json.dumps({"app_id": self.app_id, "app_secret": self.app_secret}).encode()
        request = urllib.request.Request(self.base_url + self.token_path, data=payload, method="POST",
                                         headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = _decode(response.read())
        except urllib.error.HTTPError as exc:
            body = _decode(exc.read())
            raise IntegrationError(self._message(f"获取 token 失败（HTTP {exc.code}）", body),
                                   provider=self.provider, status=exc.code, body=body) from exc
        except urllib.error.URLError as exc:
            raise IntegrationError(f"连接{self.provider or '接入方'}失败：{exc.reason}",
                                   provider=self.provider) from exc
        token = _pick(body, self.token_field)
        if not token:
            raise IntegrationError(self._message("获取 token 失败：返回中没有 " + self.token_field, body),
                                   provider=self.provider, body=body)
        return token

    def request(self, method="GET", path="/", query=None, body=None, headers=None):
        if not isinstance(path, str) or not path.startswith("/"):
            raise ValueError("path 必须以 / 开头")
        url = self.base_url + path
        if query:
            url += "?" + urllib.parse.urlencode(query, doseq=True)
        payload = json.dumps(body).encode() if body is not None else None
        sent = {"Content-Type": "application/json"}
        if self.auth == "token":
            sent["Authorization"] = f"Bearer {self.token()}"
        elif self.auth == "headers":
            sent.update({"X-App-Id": self.app_id, "X-App-Secret": self.app_secret})
        sent.update(headers or {})
        request = urllib.request.Request(url, data=payload, method=method.upper(), headers=sent)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return {"status": response.status, "body": _decode(response.read())}
        except urllib.error.HTTPError as exc:
            detail = _decode(exc.read())
            raise IntegrationError(self._message(f"{method.upper()} {path} 返回 HTTP {exc.code}", detail),
                                   provider=self.provider, status=exc.code, body=detail,
                                   code=detail.get("code") if isinstance(detail, dict) else None) from exc
        except urllib.error.URLError as exc:
            raise IntegrationError(f"连接{self.provider or '接入方'}失败：{exc.reason}",
                                   provider=self.provider) from exc

    @staticmethod
    def _message(prefix, body):
        if isinstance(body, dict):
            code = body.get("code", body.get("error_code"))
            message = body.get("msg") or body.get("message") or body.get("error")
            if code is not None or message:
                return f"{prefix}：code={code}，{message or ''}".rstrip("，")
        return f"{prefix}：{str(body)[:500]}"


class McpClient:
    """以 stdio 启动 MCP 服务并完成一次工具调用。"""

    def __init__(self, command, timeout=30, provider=None):
        self.argv = shlex.split(command)
        if not self.argv:
            raise ValueError("MCP 启动命令不能为空")
        self.timeout = timeout
        self.provider = provider
        self.process = None
        self._id = 0

    async def __aenter__(self):
        self.process = await asyncio.create_subprocess_exec(
            *self.argv, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        await self._request("initialize", {
            "protocolVersion": MCP_PROTOCOL, "capabilities": {},
            "clientInfo": {"name": "agent-platform", "version": "1"}})
        await self._notify("notifications/initialized")
        return self

    async def __aexit__(self, *exc_info):
        if self.process and self.process.returncode is None:
            try:
                self.process.stdin.close()
            except Exception:
                pass
            try:
                await asyncio.wait_for(self.process.wait(), 3)
            except asyncio.TimeoutError:
                self.process.kill()

    async def list_tools(self):
        result = await self._request("tools/list", {})
        tools = result.get("tools") if isinstance(result, dict) else None
        return tools or []

    async def call_tool(self, name, arguments=None):
        return await self._request("tools/call", {"name": name, "arguments": arguments or {}})

    async def _notify(self, method):
        message = {"jsonrpc": "2.0", "method": method}
        await self._send(message)

    async def _send(self, message):
        self.process.stdin.write((json.dumps(message) + "\n").encode())
        await self.process.stdin.drain()

    async def _request(self, method, params):
        self._id += 1
        await self._send({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params})
        while True:
            try:
                line = await asyncio.wait_for(self.process.stdout.readline(), self.timeout)
            except asyncio.TimeoutError as exc:
                raise IntegrationError(f"MCP {method} 超过 {self.timeout} 秒未返回",
                                       provider=self.provider) from exc
            if not line:
                raise IntegrationError(f"MCP 进程在 {method} 期间退出", provider=self.provider)
            try:
                payload = json.loads(line.decode("utf-8", "replace"))
            except ValueError:
                continue
            if payload.get("id") != self._id:
                continue
            if "error" in payload:
                error = payload["error"]
                raise IntegrationError(f"MCP {method} 失败：{error}", provider=self.provider,
                                       code=error.get("code") if isinstance(error, dict) else None)
            return payload.get("result")
