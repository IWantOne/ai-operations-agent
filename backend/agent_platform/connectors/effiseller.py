"""智易飞 Amazon 原生 API 客户端：只做 HTTP 通信，不做业务判断。

- ``stores()``：GET /api/open/amazon/stores，列出当前应用可访问的店铺。
- ``request()``：POST /api/open/amazon/request，把 Amazon 请求透传给 ERP；
  ERP 返回 Amazon 的原始状态与正文，错误、限流、重定向都由调用方处理。
- 只抛原始异常 ``ErpError``（带 HTTP 状态、正文、request_id、ERP code），
  不写日志，日志由工具层写 tool_call_log。
"""
import json
import urllib.error
import urllib.request

API_TYPES = ("sp-api", "ads")


class ErpError(RuntimeError):
    """智易飞调用失败。保留 HTTP 状态、返回正文和对端请求编号。"""

    def __init__(self, message, *, status=None, body=None, request_id=None, code=None):
        super().__init__(message)
        self.status = status
        self.body = body
        self.request_id = request_id
        self.code = code


class EffisellerClient:
    def __init__(self, base_url, app_id, app_secret, timeout=30):
        if not base_url or not app_id or not app_secret:
            raise ValueError("请先在「配置 → 工具」填写智易飞部署地址、App ID 和 App Secret")
        self.base_url = base_url.rstrip("/")
        self.headers = {"X-App-Id": app_id, "X-App-Secret": app_secret}
        self.timeout = timeout

    def stores(self):
        return self._call("GET", "/api/open/amazon/stores")

    def request(self, *, sid=None, store_name=None, api_type="sp-api", method="GET", path="/",
                query=None, headers=None, body=None, ads_scope=None):
        if (sid is None) == (not store_name):
            raise ValueError("sid 与 store_name 必须且只能提供一个")
        if api_type not in API_TYPES:
            raise ValueError(f"api_type 只能是 {' 或 '.join(API_TYPES)}")
        if not isinstance(method, str) or not method:
            raise ValueError("method 不能为空")
        if not isinstance(path, str) or not path.startswith("/") or ".." in path:
            raise ValueError("path 必须以 / 开头，且不能包含 ..")
        payload = {"api_type": api_type, "method": method.upper(), "path": path}
        payload["sid" if sid is not None else "store_name"] = sid if sid is not None else store_name
        for key, value in (("query", query), ("headers", headers), ("body", body), ("ads_scope", ads_scope)):
            if value is not None:
                payload[key] = value
        return self._call("POST", "/api/open/amazon/request", payload)

    def _call(self, method, path, payload=None):
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(self.base_url + path, data=data, method=method,
                                         headers={"Content-Type": "application/json", **self.headers})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return {"status": response.status, "body": self._decode(response.read())}
        except urllib.error.HTTPError as exc:
            body = self._decode(exc.read())
            raise ErpError(self._message(exc.code, body), status=exc.code, body=body,
                           request_id=body.get("request_id") if isinstance(body, dict) else None,
                           code=body.get("code") if isinstance(body, dict) else None) from exc
        except urllib.error.URLError as exc:
            raise ErpError(f"连接智易飞失败：{exc.reason}") from exc

    @staticmethod
    def _decode(raw):
        text = raw.decode("utf-8", errors="replace")
        try:
            return json.loads(text)
        except ValueError:
            return text

    @staticmethod
    def _message(status, body):
        if isinstance(body, dict) and body.get("message"):
            return f"智易飞拒绝请求（code={body.get('code')}，request_id={body.get('request_id')}）：{body['message']}"
        return f"智易飞返回 HTTP {status}：{str(body)[:500]}"
