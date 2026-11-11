"""智易飞 ERP 接入配置：Amazon 原生 API 的地址与应用凭据。

凭据在落库前用本机用户凭据加密（settings/secrets.py），接口只返回是否已保存。
调用超时属于运行时限，放在 settings/timing.py。
"""
import base64
import json

from ..logs.writer import LogWriter
from .secrets import protect

DEFAULTS = {
    "base_url": "https://test.effiseller.com",
    "app_id": "",
}


class ErpSettings:
    def __init__(self, store):
        self.store = store
        self.log = LogWriter(store, "system_log")

    def _saved(self):
        row = self.store.one("SELECT value FROM platform_setting WHERE key='erp.effiseller'")
        return json.loads(row["value"]) if row else {}

    def read(self):
        """内部使用：返回含明文密钥的配置。"""
        saved = self._saved()
        settings = {**DEFAULTS, **{key: saved[key] for key in DEFAULTS if key in saved}}
        settings["app_secret"] = (protect(base64.b64decode(saved["app_secret"]), True).decode()
                                  if saved.get("app_secret") else "")
        return settings

    def public(self):
        saved = self._saved()
        return {"base_url": saved.get("base_url", DEFAULTS["base_url"]),
                "app_id": saved.get("app_id", ""),
                "secret_set": bool(saved.get("app_secret"))}

    def save(self, values):
        current = self._saved()
        base_url = values.get("base_url", current.get("base_url", DEFAULTS["base_url"]))
        app_id = values.get("app_id", current.get("app_id", ""))
        secret = values.get("app_secret", "")
        if not isinstance(base_url, str) or not base_url.startswith(("http://", "https://")) or len(base_url) > 512:
            raise ValueError("请填写 http(s):// 开头的部署地址")
        if not isinstance(app_id, str) or len(app_id) > 256:
            raise ValueError("App ID 无效")
        if not isinstance(secret, str) or len(secret) > 512:
            raise ValueError("App Secret 无效")
        saved = {"base_url": base_url.rstrip("/"), "app_id": app_id.strip(),
                 "app_secret": current.get("app_secret", "")}
        if secret.strip():
            saved["app_secret"] = base64.b64encode(protect(secret.strip().encode())).decode()
        with self.store.transaction():
            self.store.execute("INSERT INTO platform_setting (key,value) VALUES ('erp.effiseller',?) "
                               "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                               (json.dumps(saved),))
            self.log.write("erp_settings_saved", {"base_url": saved["base_url"], "app_id": saved["app_id"],
                                                  "secret_set": bool(saved["app_secret"])})
        return self.public()
