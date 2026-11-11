"""Persistent defaults for newly submitted root work requests."""
import json

from ..logs.writer import LogWriter


class RetrySettings:
    def __init__(self, store):
        self.store = store
        self.log = LogWriter(store, "system_log")

    def read(self):
        row = self.store.one("SELECT value FROM platform_setting WHERE key='queue.retry'")
        return json.loads(row["value"]) if row else {"enabled": False, "total_retries": 3}

    def save(self, values):
        enabled = values.get("enabled")
        count = values.get("total_retries")
        if type(enabled) is not bool:
            raise ValueError("自动重试开关必须为布尔值")
        if type(count) is not int or not 1 <= count <= 100:
            raise ValueError("根请求总重试预算必须为 1 到 100 的整数")
        settings = {"enabled": enabled, "total_retries": count}
        with self.store.transaction():
            self.store.execute(
                "INSERT INTO platform_setting (key,value) VALUES ('queue.retry',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (json.dumps(settings),))
            self.log.write("retry_settings_saved", settings)
        return settings

    def limit(self):
        settings = self.read()
        return settings["total_retries"] if settings["enabled"] else 0
