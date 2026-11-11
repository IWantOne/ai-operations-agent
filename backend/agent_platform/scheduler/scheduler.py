"""Interval triggers submit work; individual invalid plans cannot stop the controller."""
import json
import math
import time
from ..logs.errors import exception_details
from ..logs.writer import LogWriter


class Scheduler:
    def __init__(self, manager, *, clock=time.time):
        self.manager, self.store, self.clock = manager, manager.store, clock
        self.log = LogWriter(manager.store, "execution_log")

    def _process(self, task, *, recovery):
        now, submitted = self.clock(), []
        data = json.loads(task["sync_data"] or "{}")
        changed = False
        for plan in data.get("schedules", []):
            due = data["schedule_next"][plan["key"]]
            step = plan["interval_seconds"]
            if type(due) not in (int, float) or not math.isfinite(due) or type(step) not in (int, float) or not math.isfinite(step) or step <= 0:
                raise ValueError(f"定时计划 {plan['key']} 的时间或间隔无效：due={due!r}, interval={step!r}")
            if due > now:
                continue
            if recovery:
                self.log.write("schedule_missed_during_restart", {"plan": plan["key"]}, task_id=task["id"], level="WARNING")
            else:
                request = self.manager.submit(task["id"], source=f"schedule:{plan['key']}",
                    operation_key=f"schedule:{task['id']}:{plan['key']}:{due}", reject_overlap=True)
                if request:
                    submitted.append(request)
            data["schedule_next"][plan["key"]] = due + (math.floor((now-due)/step)+1)*step
            changed = True
        if changed:
            self.store.update("task_info", task["id"], sync_data=json.dumps(data))
        return submitted

    def _scan(self, recovery):
        submitted = []
        for task in self.store.all("SELECT * FROM task_info WHERE enabled=1 ORDER BY id"):
            try:
                with self.store.transaction():
                    submitted.extend(self._process(task, recovery=recovery))
            except Exception as exc:
                self.log.write("schedule_error", exception_details(exc), task_id=task["id"], level="ERROR")
                # Invalid definitions stay visible but do not repeatedly flood the event loop/log.
                self.store.update("task_info", task["id"], enabled=0)
        return submitted

    def tick(self):
        return self._scan(False) if self.manager.accepting else []

    def skip_missed(self):
        return self._scan(True)
