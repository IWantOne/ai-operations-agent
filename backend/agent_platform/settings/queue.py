"""Capacity is independent per lane; control capacity cannot be borrowed."""
import json

from ..logs.writer import LogWriter

DEFAULTS = {"tasks": 4, "ziniao": 4, "operations": 4, "control": 2, "commands": 2, "windows": 5,
            "control_retries": 1}


class QueueSettings:
    def __init__(self, store):
        self.store = store
        self.log = LogWriter(store, "system_log")

    def read(self):
        row = self.store.one("SELECT value FROM platform_setting WHERE key='queue.capacity'")
        return {**DEFAULTS, **(json.loads(row["value"]) if row else {})}

    def save(self, values):
        result = {key: values.get(key) for key in DEFAULTS}
        for key, value in result.items():
            minimum = 0 if key == "control_retries" else 1
            if type(value) is not int or not minimum <= value <= 100:
                raise ValueError(f"{key} 必须为 {minimum}–100 的整数")
        with self.store.transaction():
            self.store.execute("INSERT INTO platform_setting(key,value) VALUES('queue.capacity',?) "
                               "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(result),))
            self.log.write("queue_settings_saved", result)
        return result
