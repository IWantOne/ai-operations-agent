"""Named Python tools. Repeated parameters are normal independent calls."""
from __future__ import annotations

from ..logs.errors import exception_details
from ..logs.writer import LogWriter

import json
import time
import uuid


class ToolRegistry:
    def __init__(self, store):
        self.store = store
        self.log = LogWriter(store, "tool_call_log")
        self.handlers = {}
        self.safety = {}

    def register(self, name, handler, *, restart_safe=False):
        if name in self.handlers:
            raise ValueError(f"Tool already registered: {name}")
        if type(restart_safe) is not bool:
            raise ValueError("restart_safe must be an explicit boolean")
        self.handlers[name] = handler
        self.safety[name] = restart_safe

    async def call(self, name, execution_id, **params):
        if name not in self.handlers:
            raise KeyError(f"Unknown tool: {name}")
        call_id = uuid.uuid4().hex
        started = time.time()

        def log(action, payload, level="INFO"):
            self.log.write(action,
                           json.dumps({"call_id": call_id, "tool": name, **payload},
                                      ensure_ascii=False, default=str),
                           execution_id=execution_id, call_id=call_id, level=level)

        log("tool_start", {"params": params})
        try:
            result = await self.handlers[name](**params)
        except BaseException as exc:
            log("tool_error", {**exception_details(exc), "seconds": time.time() - started}, "ERROR")
            raise
        log("tool_result", {"result": result, "seconds": time.time() - started})
        return result
