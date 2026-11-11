"""工具配置：外部能力怎么调用。当前只有 Codex。

Codex 有自己的 CLI（codex exec），本机装了就不需要配置；这里保存的是可选的覆盖：
可执行文件路径和追加参数。单次调用上限属于运行时限，放在 settings/timing.py。
"""
import json

from ..logs.writer import LogWriter

DEFAULTS = {
    "codex_command": "",
    "codex_args": "",
}


class ToolSettings:
    def __init__(self, store):
        self.store = store
        self.log = LogWriter(store, "system_log")

    def read(self):
        row = self.store.one("SELECT value FROM platform_setting WHERE key='tools.codex'")
        saved = json.loads(row["value"]) if row else {}
        return {**DEFAULTS, **{key: value for key, value in saved.items() if key in DEFAULTS}}

    def save(self, values):
        current = self.read()
        command = values.get("codex_command", current["codex_command"])
        args = values.get("codex_args", current["codex_args"])
        if not isinstance(command, str) or len(command) > 512:
            raise ValueError("Codex 可执行文件路径无效")
        if not isinstance(args, str) or len(args) > 1024:
            raise ValueError("Codex 额外参数无效")
        settings = {"codex_command": command.strip(), "codex_args": args.strip()}
        with self.store.transaction():
            self.store.execute("INSERT INTO platform_setting (key,value) VALUES ('tools.codex',?) "
                               "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                               (json.dumps(settings),))
            self.log.write("tool_settings_saved", settings)
        return settings
