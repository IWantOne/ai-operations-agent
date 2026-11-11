"""Task definitions and handler registration, without dispatch or retry."""
import json
import math
from ..executions.context import Job


class TaskDefinitions:
    def __init__(self, store, clock, timing_settings):
        self.store, self.clock, self.timing_settings = store, clock, timing_settings
        self.jobs = {}

    def register(self, name, run, *, restart_safe=False):
        if name in self.jobs:
            raise ValueError(f"Handler already registered: {name}")
        if type(restart_safe) is not bool:
            raise ValueError("restart_safe must be an explicit boolean")
        self.jobs[name] = Job(run, restart_safe)

    def create_task(self, name, *, employee_key="default", handler,
                    input_data=None, timeout_seconds=None, resume_enabled=False,
                    schedules=None):
        if timeout_seconds is None:
            timeout_seconds = self.timing_settings.read()["task_timeout_seconds"]
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        now = self.clock()
        data = {"schedules": schedules or [], "schedule_next": {}}
        for item in data["schedules"]:
            if not math.isfinite(item["interval_seconds"]) or item["interval_seconds"] <= 0:
                raise ValueError("schedule interval must be positive")
            if not isinstance(item.get("first_at", now), (int, float)) or not math.isfinite(item.get("first_at", now)):
                raise ValueError("first_at must be a finite timestamp")
            if item["key"] in data["schedule_next"]:
                raise ValueError("schedule keys must be unique within a task")
            data["schedule_next"][item["key"]] = item.get("first_at", now + item["interval_seconds"])
        return self.store.insert("task_info", {
            "name": name, "employee_key": employee_key, "handler": handler,
            "input_data": json.dumps(input_data or {}), "enabled": 1,
            "timeout_seconds": timeout_seconds, "resume_enabled": int(resume_enabled),
            "created_at": now, "sync_data": json.dumps(data),
        })

