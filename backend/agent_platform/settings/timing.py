"""Operator-controlled durations. Values are seconds; scheduling loops are internal."""
import json
import math

from ..logs.writer import LogWriter


DEFAULTS = {
    "discovery_scan_seconds": 15,
    "discovery_probe_seconds": 2,
    "shutdown_wait_seconds": 60,
    "shutdown_timeout_action": "wait",
    "task_timeout_seconds": 3600,
    "window_lease_seconds": 3600,
    "retry_delay_seconds": 0.1,
    "cli_timeout_seconds": 60,
    "webdriver_timeout_seconds": 45,
    "api_action_timeout_seconds": 60,
}
RANGES = {
    "discovery_scan_seconds": (1, 300), "discovery_probe_seconds": (0.1, 60),
    "shutdown_wait_seconds": (1, 86400), "task_timeout_seconds": (1, 604800),
    "window_lease_seconds": (1, 604800), "retry_delay_seconds": (0.1, 86400),
    "api_action_timeout_seconds": (1, 86400),
    "cli_timeout_seconds": (1, 3600), "webdriver_timeout_seconds": (1, 3600),
}


class TimingSettings:
    def __init__(self, store):
        self.store = store
        self.log = LogWriter(store, "system_log")

    def read(self):
        row = self.store.one("SELECT value FROM platform_setting WHERE key='runtime.timing'")
        return {**DEFAULTS, **(json.loads(row["value"]) if row else {})}

    def save(self, values):
        settings = {key: values.get(key) for key in DEFAULTS}
        for key, (minimum, maximum) in RANGES.items():
            value = settings[key]
            if type(value) not in (int, float) or not math.isfinite(value) or not minimum <= value <= maximum:
                raise ValueError(f"{key} 必须为 {minimum}–{maximum} 秒之间的有限数值")
        if settings["shutdown_timeout_action"] not in ("wait", "cancel"):
            raise ValueError("等待到期后仅可选择继续等待或取消运行中的任务")
        with self.store.transaction():
            self.store.execute("INSERT INTO platform_setting (key,value) VALUES ('runtime.timing',?) "
                               "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(settings),))
            self.log.write("timing_settings_saved", settings)
        return settings
