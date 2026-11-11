"""Read raw events across the platform log tables."""
import math
import time
from ..database import LOG_TABLES
from .catalog import UNKNOWN_ACTIONS, MODULES, EVENT_TYPES, PROVIDERS, definitions, sql_metadata

# Query metadata only: never alter content or construct another exception.


def query_logs(store, *, source="", level="", category="", execution_id=None, call_id="",
               module="", event_type="", provider="", q="", since=None, until=None, page=1, page_size=50):
    if source and source not in LOG_TABLES:
        raise ValueError("日志来源无效")
    if level not in {"", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ValueError("日志级别无效")
    if category not in {"", "UNKNOWN"}:
        raise ValueError("日志分类无效")
    for value, allowed, label in ((module, MODULES, "记录模块"), (event_type, EVENT_TYPES, "事件类型"), (provider, PROVIDERS, "数据来源")):
        if value and value not in allowed:
            raise ValueError(f"日志{label}无效")
    if page < 1 or not 1 <= page_size <= 100:
        raise ValueError("页码必须大于零，每页条数须为 1–100")
    if execution_id is not None and execution_id < 1:
        raise ValueError("执行 ID 必须大于零")
    until = time.time() if until is None else until
    if not math.isfinite(until) or (since is not None and (not math.isfinite(since) or since > until)):
        raise ValueError("日志时间范围无效")
    if not isinstance(call_id, str) or len(call_id) > 128:
        raise ValueError("调用 ID 无效")
    if len(q) > 500:
        raise ValueError("搜索内容不能超过 500 字")
    branches = []
    for table in sorted([source] if source else LOG_TABLES):
        actions = ",".join(f"'{action}'" for action in UNKNOWN_ACTIONS)
        classification = f"CASE WHEN action IN ({actions}) THEN 'UNKNOWN' ELSE '' END" if table == "resource_log" else "''"
        metadata = ", ".join(f"{sql_metadata(table, field)} AS {field}" for field in ("module", "event_type", "provider", "event_label"))
        branches.append(f"SELECT '{table}' AS source, {classification} AS category, {metadata}, "
                        f"id,task_id,execution_id,borrow_id,call_id,level,action,content,occurred_at FROM {table}")
    clauses, params = ["occurred_at<=?"], [until]
    for field, value in (("level", level), ("category", category), ("execution_id", execution_id),
                         ("module", module), ("event_type", event_type), ("provider", provider), ("call_id", call_id)):
        if value not in (None, ""):
            clauses.append(f"{field}=?")
            params.append(value)
    if since is not None:
        clauses.append("occurred_at>=?")
        params.append(since)
    if q:
        pattern = "%" + q.lower().replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"
        clauses.append("(LOWER(content) LIKE ? ESCAPE '!' OR LOWER(action) LIKE ? ESCAPE '!')")
        params.extend([pattern, pattern])
    base = " FROM (" + " UNION ALL ".join(branches) + ") AS events WHERE " + " AND ".join(clauses)
    # One transaction keeps the count and page consistent while other threads log.
    with store.transaction():
        total = store.one("SELECT COUNT(*) AS n" + base, params)["n"]
        rows = store.all("SELECT *" + base + " ORDER BY occurred_at DESC,source DESC,id DESC LIMIT ? OFFSET ?",
                         [*params, page_size, (page - 1) * page_size])
    return {"items": rows, "total": total, "page": page, "page_size": page_size, "until": until, "definitions": definitions()}


def read_logs(store, execution_id=None):
    entries = []
    for table in sorted(LOG_TABLES):
        clause = " WHERE execution_id=?" if execution_id is not None else ""
        rows = store.all(f"SELECT * FROM {table}{clause} ORDER BY id DESC LIMIT 100",
                         (execution_id,) if execution_id is not None else ())
        entries.extend({"table": table, **row} for row in rows)
    return sorted(entries, key=lambda row: (row["occurred_at"], row["table"], row["id"]))
