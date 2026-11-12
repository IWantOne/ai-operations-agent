"""Shared task facts used by the employee cards and board."""
import json


def object_value(value):
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value or "{}")
    except (ValueError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def rows_for(task, state):
    return sorted((e for e in state["executions"] if e["task_id"] == task["id"]),
                  key=lambda e: e["id"], reverse=True)


def task_facts(task, state):
    """Board column and plain-language summary, using current execution and request facts."""
    rows = rows_for(task, state)
    active = [e for e in rows if e["status"] in {"STARTING", "RUNNING"}]
    if any(e.get("wait_reason") != "WINDOW" for e in active):
        return "running", "执行中"
    if any(e["status"] == "PAUSED" for e in rows):
        return "failed", "等待人工处理"
    if active:
        return "queued", "等待紫鸟窗口"
    if any(r["task_id"] == task["id"] and r["status"] in {"QUEUED", "RETRY_WAIT"} for r in state["requests"]):
        return "queued", "运行请求已排队"
    if rows:
        latest = rows[0]
        if latest["status"] in {"FAILED", "CANCELLED", "TIMEOUT", "NEEDS_REVIEW"}:
            return "failed", {"NEEDS_REVIEW": "需人工", "FAILED": "失败", "CANCELLED": "已取消", "TIMEOUT": "超时"}[latest["status"]]
    if not task.get("enabled", True):
        return "queued", "已停用"
    if object_value(task.get("sync_data")).get("schedules"):
        return "queued", "等待下次触发"
    if not rows:
        return "queued", "待首次执行"
    if rows[0]["status"] == "SUCCEEDED" and object_value(rows[0].get("result_data")).get("completed") is True:
        return "done", "业务已完成"
    return "failed", "业务结果待确认"
