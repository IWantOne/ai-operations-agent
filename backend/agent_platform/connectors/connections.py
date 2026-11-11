"""连接方式的选择与凭据保护。CLI 与 WebDriver 是两个平级浏览器实现。"""
import asyncio
import http.client
import json
import os
import tempfile
import time
from uuid import uuid4

from .browser import Browser, ConnectorCode
from .errors import ConnectorError, Foreign
from .ziniao import CliBrowser
from ..logs.errors import exception_details
from ..logs.writer import LogWriter
from ..settings.secrets import protect
from ..settings.timing import TimingSettings


class WebDriverBrowser(Browser):
    """通过本机 WebDriver HTTP 接口操作店铺窗口。

    与 CliBrowser 平级，共同继承 Browser 适配器基类。

    分层（见框架图）：

    - 传输层 request() 只调平台、只抛原始异常（ValueError 带 HTTP 码/正文），
      不写日志、不翻译为统一异常。
    - 公开方法（open / close / inspect / find_windows）调底层，catch 原始异常，
      用基类的 ConnectorCode 翻译成统一异常，写 resource_log，再抛统一异常。
    """

    label = "紫鸟 WebDriver"

    def __init__(self, store, stores, config):
        super().__init__(store, stores)
        self.config = config
        self.log = LogWriter(store, "resource_log")

    # ------------------------------------------------------------ 传输层
    # 只调平台、只抛原始异常，不写日志。
    def request(self, action, **fields):
        payload = {"action": action, "requestId": str(uuid4()), **fields}
        if action != "getRunningInfo":
            payload.update({key: self.config[key] for key in ("company", "username", "password")})

        def safe(text):
            for key in ("password",):
                value = self.config.get(key)
                if value:
                    text = text.replace(value, "[REDACTED]")
                    text = text.replace(json.dumps(value)[1:-1], "[REDACTED]")
            return text

        client = http.client.HTTPConnection("127.0.0.1", self.config["port"],
                                             timeout=TimingSettings(self.store).read()["webdriver_timeout_seconds"])
        try:
            client.request("POST", "/", json.dumps(payload).encode(), {"Content-Type": "application/json"})
            response = client.getresponse()
            raw = response.read().decode("utf-8", errors="replace")
            display = safe(raw)
            if response.status != 200:
                raise ValueError(f"WebDriver {action}: HTTP {response.status}; 返回正文：{display}")
            result = json.loads(raw)
            if not isinstance(result, dict) or str(result.get("statusCode")) != "0":
                raise ValueError(f"WebDriver {action} 被对端拒绝；返回正文：{display}")
            if result.get("requestId") not in (None, payload["requestId"]):
                raise ValueError(f"WebDriver {action} requestId 不匹配；返回正文：{display}")
            return result, {"operation": action, "request_id": payload["requestId"],
                            "port": self.config["port"], "browser_id": fields.get("browserId"),
                            "http_status": response.status, "body": display}
        finally:
            client.close()

    # ------------------------------------------------------------ 公开接口
    # 调底层 → 落原始证据 → 翻译成统一异常 → 写 resource_log → 抛统一异常。
    def _record(self, code, content, level="INFO"):
        self.log.write(code.value, content, level=level)

    @staticmethod
    def _safe_values(config, value):
        password = config.get("password")
        if isinstance(value, str) and password:
            return value.replace(password, "[REDACTED]")
        if isinstance(value, dict):
            return {key: WebDriverBrowser._safe_values(config, item) for key, item in value.items()}
        if isinstance(value, list):
            return [WebDriverBrowser._safe_values(config, item) for item in value]
        return value

    async def _observe(self, operation, **fields):
        """调底层的唯一入口：原始证据先落库，失败仍抛原始异常，翻译由调用方完成。"""
        try:
            result, raw = await asyncio.to_thread(self.request, operation, **fields)
        except Exception as exc:
            self._record(ConnectorCode.ERROR,
                         self._safe_values(self.config, {
                             "operation": operation, "request_id": None,
                             "port": self.config["port"], "browser_id": fields.get("browserId"),
                             **exception_details(exc)}), level="ERROR")
            raise
        self._record(ConnectorCode.RAW, raw)
        return result

    async def query(self, action, **fields):
        """只读查询：与公开方法共用同一条证据落库路径。"""
        return await self._observe(action, **fields)

    async def verify(self):
        try:
            result = await self._observe("getBrowserList")
        except Exception as exc:
            raise ConnectorError(f"读取店铺列表失败，远端结果不明：{exc}") from exc
        rows = result.get("browserList")
        if not isinstance(rows, list):
            raise ConnectorError("客户端未返回有效的店铺列表。")
        aliases = {}
        for shop_id, name in self.stores.items():
            matches = [r for r in rows if isinstance(r, dict) and r.get("browserName") == name
                       and r.get("browserId") in (None, shop_id, int(shop_id)) and not r.get("isExpired")]
            if len(matches) != 1 or not matches[0].get("browserOauth"):
                raise ConnectorError("登录成功，但授权店铺未找到或名称不唯一。请核对账号及店铺授权。")
            aliases[shop_id] = str(matches[0]["browserOauth"])
        return aliases

    async def inspect(self, window_ref):
        self._require_shop(window_ref)
        try:
            aliases = await self.verify()
        except Exception as exc:
            raise ConnectorError(f"窗口 {window_ref} 检查请求失败，远端结果不明：{exc}") from exc
        ids = {window_ref, aliases[window_ref]}
        try:
            result = await self._observe("getRunningInfo")
        except Exception as exc:
            raise ConnectorError(f"窗口 {window_ref} 检查请求失败，远端结果不明：{exc}") from exc
        rows = result.get("browsers")
        if not isinstance(rows, list):
            raise ConnectorError(f"getRunningInfo 缺少 browsers 数组：{result!r}")
        for row in rows:
            keys = (row.get("browserId"), row.get("browserOauth")) if isinstance(row, dict) else (row,)
            if not any(isinstance(k, (str, int)) and str(k) for k in keys):
                raise ConnectorError(f"getRunningInfo 窗口记录缺少标识：{row!r}")
            if any(str(k) in ids for k in keys):
                return True
        return False

    async def open(self, shop_id):
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
            result = await self._observe("startBrowser", browserId=shop_id)
        except Exception as exc:
            raise ConnectorError(f"店铺 {shop_id} 开窗请求失败，远端结果不明：{exc}") from exc
        if not result.get("debuggingPort"):
            raise ConnectorError("紫鸟未返回调试端口。")
        try:
            confirmed = await self.inspect(shop_id)
        except Exception as exc:
            raise ConnectorError(f"店铺 {shop_id} 开窗后检查失败，远端结果不明：{exc}") from exc
        if confirmed is not True:
            raise ConnectorError(f"店铺 {shop_id} 开窗请求已返回，但未确认窗口在运行")
        self._record(ConnectorCode.OPENED, {"operation": "open", "store_id": shop_id})
        return shop_id

    async def close(self, window_ref):
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
            await self._observe("stopBrowser", browserId=window_ref, duplicate=0)
        except Exception as exc:
            raise ConnectorError(f"窗口 {window_ref} 关闭请求失败，远端结果不明：{exc}") from exc
        try:
            confirmed = await self.inspect(window_ref)
        except Exception as exc:
            raise ConnectorError(f"窗口 {window_ref} 关闭后检查失败，远端结果不明：{exc}") from exc
        if confirmed is not False:
            raise ConnectorError(f"窗口 {window_ref} 关闭请求已返回，但未确认窗口已关闭")
        self._record(ConnectorCode.CLOSED, {"operation": "close", "store_id": window_ref})

    async def find_windows(self, shop_id):
        self._require_shop(shop_id)
        try:
            running = await self.inspect(shop_id)
        except Exception as exc:
            raise ConnectorError(f"店铺 {shop_id} 窗口查询失败，远端结果不明：{exc}") from exc
        return [shop_id] if running else []

    async def debug_port(self, shop_id):
        self._require_shop(shop_id)
        try:
            result = await self._observe("getRunningInfo")
        except Exception as exc:
            raise ConnectorError(f"读取店铺 {shop_id} 调试端口失败，远端结果不明：{exc}") from exc
        rows = result.get("browsers")
        if not isinstance(rows, list):
            raise ConnectorError(f"getRunningInfo 缺少 browsers 数组：{result!r}")
        for row in rows:
            if not isinstance(row, dict):
                continue
            keys = (row.get("browserId"), row.get("browserOauth"))
            if any(str(key) == str(shop_id) for key in keys if key not in (None, "")):
                port = row.get("debuggingPort")
                if not port:
                    raise ConnectorError(f"店铺 {shop_id} 的窗口在运行，但没有返回调试端口")
                return int(port)
        raise ConnectorError(f"店铺 {shop_id} 没有运行中的窗口，请先打开窗口再操作页面")


class Connections:
    def __init__(self, store, stores, path):
        self.store, self.stores, self.path = store, stores, path
        self.config = json.loads(protect(path.read_bytes(), True)) if path.exists() else {"mode": "cli"}
        self.browser = self.adapter(self.config)
        self.lock = asyncio.Lock()

    def adapter(self, config):
        """按配置选择浏览器实现。CLI 与 WebDriver 平级，互不继承。"""
        if config["mode"] == "webdriver":
            return WebDriverBrowser(self.store, self.stores, config)
        return CliBrowser(self.store, self.stores)

    def summary(self):
        return {k: v for k, v in self.config.items() if k in ("mode", "company", "username", "port")}

    async def account_overview(self):
        browser = self.browser
        account = self.summary()
        if account["mode"] != "webdriver":
            raise ValueError("账户店铺概览当前支持 WebDriver 连接。请在 API 设置中配置账号。")
        # 只读查询仍走适配器的证据落库路径；原始异常由本层收敛为面向界面的 ValueError。
        shops_reply, running_reply = await asyncio.gather(
            browser.query("getBrowserList"),
            browser.query("getRunningInfo"),
            return_exceptions=True,
        )
        if isinstance(shops_reply, BaseException):
            raise ValueError("读取账户店铺失败：" + exception_details(shops_reply)["error"]) from shops_reply
        if isinstance(shops_reply, tuple):
            shops_reply = shops_reply[0]
        if isinstance(running_reply, tuple):
            running_reply = running_reply[0]
        shops = shops_reply.get("browserList")
        if not isinstance(shops, list) or any(not isinstance(row, dict) for row in shops):
            raise ValueError("紫鸟返回的店铺列表格式无效。")
        running_ids = set()
        window_error = ""
        windows = running_reply.get("browsers") if isinstance(running_reply, dict) else None
        if isinstance(windows, list):
            for row in windows:
                identifiers = [row.get("browserId"), row.get("browserOauth")] if isinstance(row, dict) else [row]
                identifiers = [str(value) for value in identifiers if isinstance(value, (str, int)) and str(value)]
                if not identifiers:
                    window_error = "部分窗口无法识别，窗口状态待核验。"
                running_ids.update(identifiers)
        else:
            window_error = ("窗口状态读取失败：" + exception_details(running_reply)["error"]
                            if isinstance(running_reply, BaseException) else f"窗口状态返回格式无效：{running_reply!r}")
        rows = []
        for row in shops:
            shop_id = str(row.get("browserId") or "")
            identifiers = {shop_id, str(row.get("browserOauth") or "")} - {""}
            opened = bool(identifiers & running_ids)
            rows.append({
                "provider": "ziniao",
                "id": shop_id or str(row.get("browserOauth") or ""),
                "name": row.get("browserName") or shop_id or "未命名店铺",
                "platform": row.get("platform_name") or "未提供",
                "account": row.get("store_username") or "",
                "expired": row.get("isExpired") if type(row.get("isExpired")) is bool else None,
                "running": True if opened else None if window_error else False,
                "task_authorized": shop_id in self.stores,
            })
        return {"account": {key: account.get(key) for key in ("company", "username", "mode")},
                "shops": rows, "window_error": window_error, "fetched_at": time.time()}

    async def configure(self, manager, values, save):
        async with self.lock:
            mode = values.get("mode")
            config = {"mode": mode}
            if mode == "webdriver":
                for key in ("company", "username", "password"):
                    value = values.get(key)
                    if not isinstance(value, str) or not value.strip():
                        raise ValueError("请输入公司、账号和密码。")
                    config[key] = value if key == "password" else value.strip()
                port = values.get("port")
                if type(port) is not int or not 1 <= port <= 65535:
                    raise ValueError("请输入有效的本机端口（1–65535）。")
                config["port"] = port
            elif mode != "cli":
                raise ValueError("未知连接方式。")
            browser = self.adapter(config)
            if mode == "webdriver":
                await browser.verify()
            else:
                browser._command()
            if save:
                leases = self.store.one("SELECT id FROM resource_lease WHERE status IN ('OPENING','ACTIVE','CLOSING','UNKNOWN') LIMIT 1")
                active = self.store.one("SELECT id FROM execution_info WHERE status IN ('STARTING','RUNNING','PAUSED') LIMIT 1")
                if leases or active:
                    raise ValueError("请等待当前执行结束、窗口归还后再切换连接。")
                if mode == "cli":
                    self.path.unlink(missing_ok=True)
                else:
                    sealed = protect(json.dumps(config).encode())
                    with tempfile.NamedTemporaryFile(dir=self.path.parent, delete=False) as file:
                        tmp = file.name
                        file.write(sealed)
                    try:
                        os.replace(tmp, self.path)
                    finally:
                        if os.path.exists(tmp):
                            os.unlink(tmp)
                self.config, self.browser = config, browser
                manager.pool.browser = browser
            return {"connection": self.summary()}
