"""Load task definitions without replacing already-created executions."""
import json
import math
from pathlib import Path


def default_owner(manager, source):
    root = Path(getattr(manager, "employee_root", Path(__file__).resolve().parents[1] / "employees")).resolve()
    return source.parent.name if source.name == "manifest.json" and source.parent.parent == root else "default"


def load_tasks(manager, path):
    source = Path(path).resolve()
    config = json.loads(source.read_text(encoding="utf-8-sig"))
    rows = manager.store.all("SELECT * FROM task_info WHERE manifest_ref=? ORDER BY id", (str(source),))
    ids = []
    with manager.store.transaction():
        for definition in config["tasks"]:
            name = definition["name"]
            key = definition.get("task_key", name)
            employee = definition.get("employee_key", default_owner(manager, source))
            old = next((r for r in rows if r["employee_key"] == employee and
                        json.loads(r["sync_data"] or "{}").get("manifest_key", r["name"]) == key), None)
            sync = json.loads(old["sync_data"] or "{}") if old else {}
            if definition.get("archived"):
                if old:
                    sync.update(archived=True, schedules=[], schedule_next={})
                    manager.store.update("task_info", old["id"], enabled=0, sync_data=json.dumps(sync))
                    ids.append(old["id"])
                continue
            handler = definition.get("handler", "")
            inputs = dict(definition.get("input", {}))
            if inputs.get("skill_path"):
                inputs["skill_path"] = str((source.parent / inputs["skill_path"]).resolve())
            schedules = definition.get("schedules", [])
            timeout = definition.get("timeout_seconds", manager.timing_settings.read()["task_timeout_seconds"])
            if not math.isfinite(timeout) or timeout <= 0:
                raise ValueError("执行时限必须大于零")
            keys = [p["key"] for p in schedules]
            if len(keys) != len(set(keys)) or any(not p["key"] or not math.isfinite(p["interval_seconds"]) or p["interval_seconds"] <= 0 for p in schedules):
                raise ValueError("定时计划名称不可重复，间隔必须大于零")
            for plan in schedules:
                first = plan.get("first_at", manager.clock())
                if type(first) not in (int, float) or not math.isfinite(first):
                    raise ValueError("定时计划 first_at 必须为有限时间戳")
            if old:
                previous = {p["key"]: p for p in sync.get("schedules", [])}
                times = sync.get("schedule_next", {})
                next_times = {p["key"]: times[p["key"]] if p == previous.get(p["key"]) and p["key"] in times
                              else p.get("first_at", manager.clock() + p["interval_seconds"]) for p in schedules}
                sync.update(manifest_key=key, schedules=schedules, schedule_next=next_times)
                enabled = int(bool(handler) and (old["enabled"] or not old["handler"]))
                manager.store.update("task_info", old["id"], name=name, enabled=enabled,
                                     input_data=json.dumps(inputs), handler=handler, timeout_seconds=timeout,
                                     resume_enabled=int(definition.get("resume_enabled", False)), sync_data=json.dumps(sync))
                ids.append(old["id"])
            else:
                tid = manager.create_task(name, employee_key=employee, handler=handler, input_data=inputs,
                                          timeout_seconds=timeout, resume_enabled=definition.get("resume_enabled", False),
                                          schedules=schedules)
                sync = json.loads(manager.store.one("SELECT sync_data FROM task_info WHERE id=?", (tid,))["sync_data"])
                sync["manifest_key"] = key
                manager.store.update("task_info", tid, enabled=int(bool(handler)), manifest_ref=str(source), sync_data=json.dumps(sync))
                ids.append(tid)
    return ids
