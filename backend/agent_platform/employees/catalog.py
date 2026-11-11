"""Workbench edits persist to employee manifests; task history stays in the database."""
import json
from pathlib import Path
import re
from uuid import uuid4

from ..settings import load_tasks
from ..settings.manifests import default_owner

ROOT = Path(__file__).resolve().parent


def _root(manager):
    return Path(getattr(manager, "employee_root", ROOT)).resolve()


def _read(path):
    return json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {"tasks": []}


def _write(path, contents):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        tmp.write_bytes(contents)
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def _manifest(manager, key):
    if not isinstance(key, str) or not re.fullmatch(r"[\w-]+", key) or key.startswith("__"):
        raise ValueError("员工目录标识无效")
    root = _root(manager)
    target = (root / key / "manifest.json").resolve()
    if target.parent.parent != root:
        raise ValueError("员工清单路径超出目录")
    return target


def visible_tasks(manager, tasks):
    return [t for t in tasks if not json.loads(t["sync_data"] or "{}").get("archived")]


def list_employees(manager):
    rows = manager.store.all("SELECT employee_key, sync_data FROM task_info")
    result = {t["employee_key"]: {"key": t["employee_key"], "name": t["employee_key"], "description": ""}
              for t in visible_tasks(manager, rows)}
    root = _root(manager)
    hidden = set()
    for directory in sorted(root.iterdir()) if root.is_dir() else []:
        if not directory.is_dir() or directory.name.startswith((".", "__")) or directory.resolve().parent != root:
            continue
        path = directory / "manifest.json"
        if not path.is_file() and not (directory / "__init__.py").is_file():
            continue
        if path.resolve().parent != directory:
            raise ValueError("员工清单路径超出目录")
        data = _read(path)
        info = data.get("employee", {})
        if not info and data["tasks"]:
            # Existing manifests can explicitly assign tasks to another employee.
            if all(t.get("employee_key", directory.name) != directory.name for t in data["tasks"]):
                continue
        key = directory.name
        if info.get("removed"):
            hidden.add(key)
        else:
            result[key] = {"key": key, "name": info.get("name", key), "description": info.get("description", "")}
    return [result[k] for k in sorted(result) if k not in hidden]


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"请填写{label}")
    return value.strip()


def _employee_change(manager, action, values):
    employees = {e["key"]: e for e in list_employees(manager)}
    if action == "create_employee":
        name = _text(values.get("name"), "员工名称")
        key = name if name.isidentifier() and not name.startswith("_") and not Path(name).is_reserved() and len(name) < 80 else ""
        if not key or key in employees or (_root(manager) / key).exists() or (_root(manager) / f"{key}.py").exists():
            key = f"employee_{uuid4().hex[:12]}"
    else:
        key = values.get("key")
        if key not in employees:
            raise ValueError("员工不存在")
        name = _text(values.get("name", employees[key]["name"]), "员工名称")
    path = _manifest(manager, key)
    config = _read(path)
    info = config.setdefault("employee", {})
    if action == "delete_employee":
        rows = manager.store.all("SELECT sync_data FROM task_info WHERE employee_key=?", (key,))
        if visible_tasks(manager, rows):
            raise ValueError("请先移除该员工的任务")
        info["removed"] = True
    else:
        if any(e["key"] != key and e["name"] == name for e in employees.values()):
            raise ValueError("员工名称已存在")
        description = values.get("description", info.get("description", ""))
        if not isinstance(description, str):
            raise ValueError("员工说明必须是文本")
        info.update(name=name, description=description.strip())
    _write(path, (json.dumps(config, ensure_ascii=False, indent=2) + "\n").encode())
    return {"key": key}


def _task_change(manager, action, values):
    store = manager.store
    existing = None
    if action != "create_task":
        existing = store.one("SELECT * FROM task_info WHERE id=?", (int(values["id"]),))
        if not existing or not visible_tasks(manager, [existing]):
            raise ValueError("任务不存在")
    employee = existing["employee_key"] if existing else values.get("employee_key")
    if employee not in {e["key"] for e in list_employees(manager)}:
        raise ValueError("员工不存在")
    if values.get("employee_key", employee) != employee:
        raise ValueError("不能变更任务所属员工")
    path = _manifest(manager, employee)
    if existing and existing["manifest_ref"]:
        original = Path(existing["manifest_ref"]).resolve()
        external = getattr(manager, "external_manifest", None)
        if (external and original == Path(external).resolve()) or (
            original.name == "manifest.json" and original.parent.parent == _root(manager)
        ):
            path = original
        else:
            raise ValueError("此任务清单不属于当前工作台")
    before = path.read_bytes() if path.exists() else None
    config = _read(path)
    definitions = config["tasks"]
    prior = json.loads(existing["sync_data"] or "{}") if existing else {}
    key = prior.get("manifest_key", existing["name"]) if existing else uuid4().hex
    entry = next((d for d in definitions if d.get("task_key", d["name"]) == key and
                  d.get("employee_key", default_owner(manager, path)) == employee), None)
    if existing and existing["manifest_ref"] and entry is None:
        raise ValueError("原任务清单已变动，请重新载入")
    if entry is None:
        entry = {"task_key": key, "employee_key": employee}
        definitions.append(entry)
        if existing:
            entry.update(name=existing["name"], handler=existing["handler"], timeout_seconds=existing["timeout_seconds"],
                         resume_enabled=bool(existing["resume_enabled"]), schedules=prior.get("schedules", []),
                         input=json.loads(existing["input_data"]))
    entry["task_key"] = key
    if action == "delete_task" or (existing and values.get("handler", existing["handler"]) != existing["handler"]):
        if store.one("SELECT id FROM work_request WHERE task_id=? AND status IN ('QUEUED','RETRY_WAIT','RUNNING')", (existing["id"],)):
            raise ValueError("任务有未结束的请求，请结束后再操作")
    if action == "delete_task":
        entry["archived"] = True
    else:
        name = _text(values.get("name", entry.get("name")), "任务名称")
        siblings = visible_tasks(manager, store.all("SELECT id,name,sync_data FROM task_info WHERE employee_key=?", (employee,)))
        if any(t["name"] == name and (not existing or t["id"] != existing["id"]) for t in siblings):
            raise ValueError("此员工已有同名任务")
        handler = values.get("handler", entry.get("handler", ""))
        if not isinstance(handler, str) or (handler and handler not in manager.jobs):
            raise ValueError("请选择已注册的执行函数")
        inputs = values.get("input_data", entry.get("input", {}))
        if not isinstance(inputs, dict):
            raise ValueError("输入参数必须为 JSON 对象")
        schedules = values.get("schedules", entry.get("schedules", []))
        if not isinstance(schedules, list) or any(not isinstance(p, dict) or not isinstance(p.get("key"), str) or
                not isinstance(p.get("interval_seconds"), (int,float)) for p in schedules):
            raise ValueError("定时计划需要名称和间隔秒数")
        entry.update(name=name, handler=handler, input=inputs, schedules=schedules,
                     timeout_seconds=values.get("timeout_seconds", entry.get("timeout_seconds", manager.timing_settings.read()["task_timeout_seconds"])),
                     resume_enabled=values.get("resume_enabled", entry.get("resume_enabled", False)))
    replaced = False
    try:
        with store.transaction():
            if existing and not existing["manifest_ref"]:
                prior["manifest_key"] = key
                store.update("task_info", existing["id"], manifest_ref=str(path), sync_data=json.dumps(prior))
            _write(path, (json.dumps(config, ensure_ascii=False, indent=2) + "\n").encode())
            replaced = True
            load_tasks(manager, path)
            if existing:
                tid = existing["id"]
            else:
                tid = next(r["id"] for r in store.all("SELECT id,sync_data FROM task_info WHERE employee_key=? AND manifest_ref=?", (employee, str(path)))
                           if json.loads(r["sync_data"])["manifest_key"] == key)
    except BaseException:
        if replaced:
            if before is None:
                path.unlink(missing_ok=True)
            else:
                _write(path, before)
        raise
    return {"id": tid}


def manage(manager, action, values):
    if action in {"create_employee", "edit_employee", "delete_employee"}:
        return _employee_change(manager, action, values)
    if action in {"create_task", "edit_task", "delete_task"}:
        return _task_change(manager, action, values)
    raise ValueError("未知的管理操作")
