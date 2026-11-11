"""Restricted task interface. Every external action becomes a child work request."""
import asyncio
import json
import time
from dataclasses import dataclass
from typing import Callable


class WindowLost(RuntimeError):
    pass


@dataclass
class Job:
    run: Callable
    restart_safe: bool = False


class ExecutionContext:
    def __init__(self, controller, execution_id, attempt_id):
        self.__controller = controller
        self.id, self.attempt_id = execution_id, attempt_id
        self.input = json.loads(self.__row["run_input"])

    @property
    def __row(self):
        return self.__controller.execution(self.id)

    @property
    def data(self):
        return json.loads(self.__row["runtime_data"] or "{}")

    def save(self, **changes):
        data = self.data
        data.update(changes)
        self.__controller.store.update("execution_info", self.id, runtime_data=json.dumps(data))

    @property
    def skill(self):
        return self.__row["skill_content"]

    @property
    def progress(self):
        return json.loads(self.__row["resume_data"] or "{}")

    def save_progress(self, value):
        if not self.__row["resume_enabled"]:
            raise ValueError("Checkpoint continuation is not enabled for this execution")
        self.__controller.store.update("execution_info", self.id, resume_data=json.dumps(value))

    def log(self, action, content):
        self.__controller._log(self.id, action, content)

    async def checkpoint(self):
        await self.__controller.checkpoint(self.id)

    async def sleep(self, seconds):
        remaining = max(0.0, seconds)
        while remaining > 0:
            await self.checkpoint()
            start = time.monotonic()
            await asyncio.sleep(min(remaining, self.__controller.poll_interval))
            remaining -= time.monotonic() - start

    async def window(self, shop_id):
        await self.checkpoint()
        s = self.__controller
        s._freeze(self.id)
        s.store.update("execution_info", self.id, wait_reason="WINDOW", waiting_since=s.clock())
        s._log(self.id, "window_wait", {"shop_id": shop_id})
        try:
            rid = s.submit_work("ziniao.acquire", {"shop_id": shop_id}, parent_attempt_id=self.attempt_id, execution_id=self.id)
            lease = await s.wait(rid, checkpoint=self.checkpoint)
            self.save(lease_id=lease["id"])
            return lease
        finally:
            # A handled acquisition error must not leave all later business time excluded.
            s.store.update("execution_info", self.id, wait_reason=None, waiting_since=None)
            if self.__row["status"] == "RUNNING" and self.__row["request_id"] not in s.stopping:
                s._resume_timer(self.id)

    async def release(self, lease_id):
        return await self.__controller.child(self.attempt_id, self.id, "ziniao.release", {"lease_id": lease_id}, control=True)

    async def tool(self, name, **params):
        await self.checkpoint()
        return await self.__controller.child(self.attempt_id, self.id, "tool.call", {"name": name, "params": params})

    async def script(self, argv, **options):
        await self.checkpoint()
        if options.get("cwd") is not None:
            options["cwd"] = str(options["cwd"])
        return await self.__controller.child(self.attempt_id, self.id, "script.run", {"argv": argv, "options": options})

    async def human(self, reason):
        self.__controller.request_pause(self.id, reason)
        await self.checkpoint()
