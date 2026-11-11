"""外部应用接入配置：飞书、领星等，支持 API 与 MCP 两种传输。

每个接入方独立保存（platform_setting 的 integration.<key>），App Secret 加密存放，
接口只返回是否已保存。超时属于运行时限，放在 settings/timing.py。
"""
import base64
import json

from ..logs.writer import LogWriter
from .secrets import protect

# 已知接入方的默认值；页面上的可编辑项都在这里定义。
PROVIDERS = {
    "feishu": {
        "label": "飞书",
        "transport": "api",
        "base_url": "https://open.feishu.cn",
        "auth": "token",
        "token_path": "/open-apis/auth/v3/tenant_access_token/internal",
        "token_field": "tenant_access_token",
        "mcp_command": "",
    },
    "lingxing": {
        "label": "领星",
        "transport": "api",
        "base_url": "",
        "auth": "token",
        "token_path": "",
        "token_field": "access_token",
        "mcp_command": "",
    },
}
FIELDS = ("transport", "base_url", "auth", "token_path", "token_field", "mcp_command")
TRANSPORTS = ("api", "mcp")
AUTH_MODES = ("token", "headers", "none")


class IntegrationSettings:
    def __init__(self, store):
        self.store = store
        self.log = LogWriter(store, "system_log")

    def _key(self, provider):
        if provider not in PROVIDERS:
            raise ValueError(f"未知接入方：{provider}")
        return f"integration.{provider}"

    def _saved(self, provider):
        row = self.store.one("SELECT value FROM platform_setting WHERE key=?", (self._key(provider),))
        return json.loads(row["value"]) if row else {}

    def read(self, provider):
        """内部使用：返回含明文 App Secret 的配置。"""
        preset = PROVIDERS[provider]
        saved = self._saved(provider)
        settings = {**preset, **{field: saved[field] for field in FIELDS if field in saved}}
        settings["app_id"] = saved.get("app_id", "")
        settings["app_secret"] = (protect(base64.b64decode(saved["app_secret"]), True).decode()
                                  if saved.get("app_secret") else "")
        return settings

    def public(self, provider):
        preset = PROVIDERS[provider]
        saved = self._saved(provider)
        return {"label": preset["label"], **{field: saved.get(field, preset[field]) for field in FIELDS},
                "app_id": saved.get("app_id", ""), "secret_set": bool(saved.get("app_secret"))}

    def all_public(self):
        return {provider: self.public(provider) for provider in PROVIDERS}

    def save(self, provider, values):
        preset = PROVIDERS[provider]
        current = self._saved(provider)
        merged = {field: values.get(field, current.get(field, preset[field])) for field in FIELDS}
        app_id = values.get("app_id", current.get("app_id", ""))
        secret = values.get("app_secret", "")
        if merged["transport"] not in TRANSPORTS:
            raise ValueError("传输方式只能是 api 或 mcp")
        if merged["auth"] not in AUTH_MODES:
            raise ValueError("认证方式只能是 token、headers 或 none")
        if not isinstance(merged["base_url"], str) or len(merged["base_url"]) > 512:
            raise ValueError("部署地址无效")
        if merged["base_url"] and not merged["base_url"].startswith(("http://", "https://")):
            raise ValueError("部署地址必须以 http(s):// 开头")
        if not isinstance(app_id, str) or len(app_id) > 256:
            raise ValueError("App ID 无效")
        if not isinstance(secret, str) or len(secret) > 512:
            raise ValueError("App Secret 无效")
        if not isinstance(merged["mcp_command"], str) or len(merged["mcp_command"]) > 1024:
            raise ValueError("MCP 启动命令无效")
        if merged["transport"] == "api" and merged["auth"] == "token" and not merged["token_path"]:
            raise ValueError("token 认证需要填写获取 token 的路径")
        if merged["transport"] == "mcp" and not merged["mcp_command"]:
            raise ValueError("MCP 传输需要填写启动命令")
        saved = {**merged, "base_url": merged["base_url"].rstrip("/"), "app_id": app_id.strip(),
                 "app_secret": current.get("app_secret", "")}
        if secret.strip():
            saved["app_secret"] = base64.b64encode(protect(secret.strip().encode())).decode()
        with self.store.transaction():
            self.store.execute("INSERT INTO platform_setting (key,value) VALUES (?,?) "
                               "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                               (self._key(provider), json.dumps(saved)))
            self.log.write("integration_settings_saved",
                           {"provider": provider, "transport": saved["transport"],
                            "base_url": saved["base_url"], "app_id": saved["app_id"],
                            "secret_set": bool(saved["app_secret"])})
        return self.public(provider)
