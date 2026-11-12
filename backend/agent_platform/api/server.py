"""Serve the built Vue application and its local HTTP API."""
import asyncio
import json
import mimetypes
from pathlib import Path
import secrets
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

from ..employees import list_employees, manage, visible_tasks
from ..logs import read_logs, query_logs
from ..logs.errors import exception_details
from ..logs.writer import LogWriter
from ..skills import load as load_skill
from .state import object_value, task_facts
from ..queueing.connections import register_connections, seal_input

DIST = Path(__file__).resolve().parents[3] / "frontend" / "dist"
ACTIONS = {"run", "retry_case", "enable", "disable", "pause", "resume", "cancel", "continue", "shutdown"}
MANAGEMENT = {"create_employee", "edit_employee", "delete_employee", "create_task", "edit_task", "delete_task"}


def start_panel(manager, port=8765, *, browser_label="紫鸟", shutdown_event=None, frontend_dir=DIST, connections=None):
    loop = asyncio.get_running_loop()
    register_connections(manager, connections)
    token = secrets.token_urlsafe(24)
    frontend_dir = Path(frontend_dir).resolve()
    panel = {"browser_label": browser_label, "can_shutdown": shutdown_event is not None, "token": token}

    async def snapshot():
        state = manager.snapshot()
        state["tasks"] = visible_tasks(manager, state["tasks"])
        for task in state["tasks"]:
            task["board_column"], task["status_label"] = task_facts(task, state)
        return {**state, "connection": connections.summary() if connections else None, "panel": panel, "employees": list_employees(manager), "handlers": sorted(manager.jobs)}

    async def skills():
        sources = {}
        for task in visible_tasks(manager, manager.store.all("SELECT * FROM task_info")):
            path = object_value(task["input_data"]).get("skill_path")
            if isinstance(path, str) and path and path not in sources:
                try:
                    sources[path] = load_skill(path)
                except (OSError, UnicodeError) as exc:
                    sources[path] = f"读取失败：{exc}"
        return sources

    async def action(name, values):
        if manager.draining and name not in {"shutdown", "cancel", "resume", "inspect_window", "release_window"}:
            raise ValueError("服务正在收尾，暂不接受修改；可继续查看状态和日志")
        if name == "save_timing_settings":
            return {"timing": manager.timing_settings.save(values)}
        if name == "save_retry_settings":
            return {"retry": manager.retry_settings.save(values)}
        if name == "save_queue_settings":
            return {"queue": manager.queue_settings.save(values)}
        if name == "save_tool_settings":
            return {"tools": manager.tool_settings.save(values)}
        if name == "save_integration":
            provider = values.get("provider")
            return {"integration": manager.integration_settings.save(provider, values)}
        if name == "test_integration":
            from ..tools.integrations import probe as integration_probe
            provider = values.get("provider")
            return {"integration": await integration_probe(manager, provider)}
        kinds = {"account_overview": "ziniao.accounts", "detect_webdriver": "ziniao.detect",
                 "verify_connection": "ziniao.verify", "save_connection": "ziniao.configure"}
        if name in kinds:
            inputs = seal_input(values) if name in {"verify_connection", "save_connection"} else {}
            rid = manager.submit_work(kinds[name], inputs, operation_key=values.get("operation_key"))
            return {"operation_id": rid}
        if name in {"inspect_window", "release_window"}:
            lease = manager.pool.get(int(values["id"]))
            rid = manager.submit_work("ziniao.inspect" if name == "inspect_window" else "ziniao.release",
                                      {"lease_id": lease["id"]}, execution_id=lease["execution_id"], control=True,
                                      operation_key=values.get("operation_key"))
            return {"operation_id": rid}
        if name == "shutdown" and shutdown_event is not None:
            manager.begin_drain()
            shutdown_event.set()
            return
        if name in MANAGEMENT:
            return manage(manager, name, values)
        if name not in ACTIONS or name == "shutdown":
            raise ValueError("操作不可用")
        identity = int(values["id"])
        if name == "retry_case":
            case = manager.store.one("SELECT * FROM feedback_case WHERE id=?", (identity,))
            if case is None:
                raise ValueError("差评记录不存在")
            if case["status"] not in {"MANUAL", "NEW"}:
                raise ValueError("只有需人工或待处理的差评可以重试")
            task_id = int(values.get("task_id") or 0)
            task = manager.store.one("SELECT * FROM task_info WHERE id=?", (task_id,))
            if task is None or task["handler"] != "feedback.process":
                raise ValueError("没有找到差评处理任务")
            manager.store.update("feedback_case", identity, status="NEW", reason="", updated_at=manager.clock())
            return {"request_id": manager.submit(task_id, operation_key=values["operation_key"],
                                                 input_data={"case_id": identity, "limit": 1})}
        if name in {"run", "enable", "disable", "continue"}:
            if name == "continue":
                execution = manager.store.one("SELECT task_id FROM execution_info WHERE id=?", (identity,))
                task_id = execution["task_id"] if execution else None
            else:
                task_id = identity
            task = manager.store.one("SELECT * FROM task_info WHERE id=?", (task_id,))
            if not task or not visible_tasks(manager, [task]):
                raise ValueError("任务已移除或不存在")
            if name != "disable" and task["handler"] not in manager.jobs:
                raise ValueError("请先编辑任务，选择已注册的执行函数")
        if name == "run":
            return {"request_id": manager.submit(identity, operation_key=values["operation_key"],
                                                 input_data=values.get("input_data"))}
        elif name in ("enable", "disable"):
            manager.store.update("task_info", identity, enabled=int(name == "enable"))
            LogWriter(manager.store, "execution_log").write(
                "task_enabled" if name == "enable" else "task_disabled",
                {"source": "panel"}, task_id=identity)
        elif name == "pause":
            return {"command_id": manager.request_pause(identity, "操作台人工暂停")}
        elif name == "resume":
            return {"command_id": manager.resume_execution(identity)}
        elif name == "cancel":
            return {"operation_id": manager.submit_work("control.cancel", {"request_id": identity}, control=True)}
        elif name == "continue":
            return {"request_id": manager.continue_from(identity)}

    class Handler(BaseHTTPRequestHandler):
        def reply(self, status, body, mime):
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def json(self, status, data):
            self.reply(status, json.dumps(data, ensure_ascii=False).encode(), "application/json; charset=utf-8")

        def failure(self, status, exc):
            details = exception_details(exc)
            evidence = {"method": self.command, "path": urlsplit(self.path).path, **details}
            response = {"error": details["error"]}
            try:
                LogWriter(manager.store, "system_log").write("API_ERROR", evidence, level="ERROR")
            except Exception as log_error:
                # An unavailable log store must not erase the original HTTP failure.
                diagnostic = exception_details(log_error)
                response["log_error"] = diagnostic
                response["error"] += "; 错误日志保存失败：" + diagnostic["error"]
                print(json.dumps({**evidence, "log_error": diagnostic}, ensure_ascii=False),
                      file=sys.stderr, flush=True)
            self.json(status, response)

        def do_GET(self):
            url = urlsplit(self.path)
            try:
                if url.path == "/api/state":
                    return self.json(200, asyncio.run_coroutine_threadsafe(snapshot(), loop).result(timeout=10))
                if url.path.startswith("/api/operations/"):
                    rid = int(url.path.rsplit("/", 1)[-1])
                    row = manager.repository.get(rid)
                    return self.json(200, {"id": rid, "status": row["status"],
                        "result": json.loads(row["result_data"] or "null"),
                        "error": json.loads(row["error_data"] or "null")})
                if url.path == "/api/session":
                    return self.json(200, panel)
                if url.path == "/api/details":
                    task_id = parse_qs(url.query).get("task_id")
                    if not task_id:
                        raise ValueError("需要 task_id")
                    task = manager.store.one("SELECT id,employee_key FROM task_info WHERE id=?", (int(task_id[-1]),))
                    if task is None:
                        raise ValueError("任务不存在")
                    provider = manager.details.get(task["employee_key"])
                    if provider is None:
                        return self.json(200, {"detail": None})
                    return self.json(200, {"detail": provider(manager, task)})
                if url.path == "/api/logs/query":
                    query = {key: values[-1] for key, values in parse_qs(url.query).items()}
                    options = {key: query[key] for key in ("source", "level", "category", "module", "event_type", "provider", "q", "call_id") if key in query}
                    for key in ("execution_id", "page", "page_size"):
                        if key in query:
                            options[key] = int(query[key])
                    for key in ("since", "until"):
                        if key in query:
                            options[key] = float(query[key])
                    return self.json(200, query_logs(manager.store, **options))
                if url.path == "/api/logs":
                    ids = parse_qs(url.query).get("execution_id")
                    return self.json(200, read_logs(manager.store, int(ids[-1]) if ids else None))
                if url.path == "/api/skills":
                    return self.json(200, asyncio.run_coroutine_threadsafe(skills(), loop).result(timeout=10))
                if url.path == "/favicon.ico":
                    return self.reply(204, b"", "image/x-icon")
                resource = unquote(url.path[1:]) if url.path != "/" else "index.html"
                target = (frontend_dir / resource).resolve()
                if url.path.startswith("/api/") or not target.is_relative_to(frontend_dir):
                    return self.json(404, {"error": "文件不存在"})
                if not target.is_file():
                    if url.path == "/":
                        return self.json(503, {"error": "请先在 frontend 目录构建 Vue 前端（npm run build）"})
                    return self.json(404, {"error": "文件不存在"})
                self.reply(200, target.read_bytes(), mimetypes.guess_type(target)[0] or "application/octet-stream")
            except (ValueError, TypeError) as exc:
                self.failure(400, exc)
            except Exception as exc:
                self.failure(500, exc)

        def do_POST(self):
            try:
                path = urlsplit(self.path).path
                if path != "/api/action":
                    return self.json(404, {"error": "接口不存在"})
                length = int(self.headers.get("Content-Length", 0))
                if not 0 < length <= 16384:
                    raise ValueError("请求正文长度无效")
                body = self.rfile.read(length).decode()
                if self.headers.get_content_type() == "application/json":
                    values = json.loads(body)
                else:
                    values = {k: v[-1] for k, v in parse_qs(body).items()}
                if not isinstance(values, dict):
                    raise ValueError("需要对象格式的请求")
                if not secrets.compare_digest(str(values.get("token", "")), token):
                    return self.json(403, {"error": "操作令牌无效"})
                name = values.get("action")
                result = asyncio.run_coroutine_threadsafe(action(name, values), loop).result(timeout=manager.timing_settings.read()["api_action_timeout_seconds"])
                self.json(200, {"ok": True, **(result or {})})
            except Exception as exc:
                self.failure(400, exc)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
