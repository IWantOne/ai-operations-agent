"""Single authority for tasks, external work, control and draining."""
import asyncio
from collections import OrderedDict
import json
import time
import subprocess
import weakref

from .dispatcher import Dispatcher
from .repository import Repository, encode
from .models import Executor, TERMINAL
from .lifecycle import finish
from ..tasks import TaskDefinitions
from ..executions.context import ExecutionContext
from ..executions import timing
from ..runtime import ScriptRuntime
from ..tools import ToolRegistry
from ..settings.retry import RetrySettings
from ..settings.timing import TimingSettings
from ..settings.queue import QueueSettings
from ..settings.tools import ToolSettings
from ..settings.integrations import IntegrationSettings
from ..logs.errors import exception_details, PersistedFailure
from ..logs.writer import LogWriter
from ..skills import load as load_skill


class QueueService:
    def __init__(self, store, *, clock=time.time, poll_interval=.01):
        self.store, self.clock, self.poll_interval = store, clock, poll_interval
        self.log = LogWriter(store, "execution_log")
        self.system = LogWriter(store, "system_log")
        self.timing_settings, self.retry_settings = TimingSettings(store), RetrySettings(store)
        self.queue_settings = QueueSettings(store)
        self.tool_settings = ToolSettings(store)
        self.integration_settings = IntegrationSettings(store)
        self.definitions = TaskDefinitions(store, clock, self.timing_settings)
        self.jobs = self.definitions.jobs
        self.repository, self.dispatcher = Repository(store, clock), Dispatcher(self)
        self.runtime, self.tools = ScriptRuntime(store), ToolRegistry(store)
        self.pool = None
        self.pause_requests, self.stop_reasons, self.pause_commands = {}, {}, {}
        self.resume_commands = {}
        self.pause_ids = {}
        self.cancel_locks = weakref.WeakValueDictionary()
        self.stopping = set()
        self.finishing = set()
        self.started = set()
        self.reclaim_attempts = {}
        self.reclaim_interval = 5.0
        self.commit_errors = {}
        self.fault = None
        self.errors = OrderedDict()
        self.accepting, self.draining, self.recovered = True, False, True
        self.executors = {
            "control.cancel": Executor(self._cancel_operation, "commands"),
            "task.run": Executor(self._task, "tasks", interruptible=True),
            "ziniao.acquire": Executor(self._acquire, "ziniao"),
            "ziniao.release": Executor(self._release, "control"),
            "ziniao.inspect": Executor(self._inspect, "control", True),
            "script.run": Executor(self._script, "operations", interruptible=True),
            "tool.call": Executor(self._tool, "operations"),
        }

    def register(self, *args, **kwargs):
        self.definitions.register(*args, **kwargs)

    def create_task(self, *args, **kwargs):
        return self.definitions.create_task(*args, **kwargs)

    @property
    def running(self):
        return {row["last_execution_id"]: self.dispatcher.runners[row["id"]]
                for row in self.store.all("SELECT * FROM work_request WHERE kind='task.run' AND status='RUNNING'")
                if row["id"] in self.dispatcher.runners}

    def lane(self, row):
        return self.executors[row["kind"]].lane

    def submit_work(self, kind, inputs, *, parent_attempt_id=None, execution_id=None,
                    operation_key=None, task_id=None, source="manual", control=None, retry_limit=None, policy=None):
        if kind not in self.executors:
            raise ValueError(f"没有登记执行器：{kind}")
        if not isinstance(inputs, dict):
            raise ValueError("工作输入必须是对象")
        is_control = self.executors[kind].lane in {"control", "commands"}
        if control is not None and control != is_control:
            raise ValueError("控制权限由执行器类型决定，不能用提交参数改变")
        control = is_control
        if self.fault and not control:
            raise PersistedFailure(self.fault)
        if not self.accepting and parent_attempt_id is None and not control:
            raise ValueError("服务正在停止，不再接收新工作")
        if parent_attempt_id:
            parent = self.store.one("SELECT * FROM work_attempt WHERE id=?", (parent_attempt_id,))
            if not parent or parent["status"] != "RUNNING" or (parent["request_id"] in self.stopping and not control):
                raise ValueError("父执行已经结束或正在取消，不能派生新工作")
            if parent["execution_id"] != execution_id:
                raise ValueError("子操作所属执行必须与父尝试一致")
            if policy is None:
                policy = json.loads(self.repository.get(parent["request_id"])["policy"])
            if not control and self.store.one("SELECT id FROM work_request WHERE execution_id=? "
                "AND kind='ziniao.release' AND status IN ('QUEUED','RETRY_WAIT','RUNNING')", (execution_id,)):
                raise ValueError("执行正在交还窗口，须等待归还确认后再提交其他子操作")
        elif kind in {"ziniao.acquire", "script.run", "tool.call"}:
            raise ValueError("窗口、脚本和工具操作必须关联有效的父执行尝试")
        limit = retry_limit if retry_limit is not None else (
            self.queue_settings.read()["control_retries"] if control else self.retry_settings.limit())
        if type(limit) is not int or limit < 0:
            raise ValueError("重试总预算必须是非负整数")
        return self.repository.submit(kind, inputs, policy=policy or self.timing_settings.read(), retry_limit=limit,
            parent_attempt_id=parent_attempt_id, operation_key=operation_key, task_id=task_id,
            execution_id=execution_id, source=source, control=control)

    def submit(self, task_id, *, source="manual", operation_key=None, input_data=None, reject_overlap=False, retry_limit=None):
        task = self.store.one("SELECT * FROM task_info WHERE id=?", (task_id,))
        if task is None:
            raise KeyError(task_id)
        inputs = input_data if input_data is not None else json.loads(task["input_data"])
        with self.store.transaction():
            # Repeated submissions must still validate the original payload, even when disabled.
            duplicate = operation_key and self.store.one("SELECT id FROM work_request WHERE operation_key=?", (operation_key,))
            if not duplicate:
                if not task["enabled"]:
                    return None
                if (reject_overlap or json.loads(task["sync_data"] or "{}").get("schedules")) and self.store.one(
                    "SELECT id FROM work_request WHERE task_id=? AND kind='task.run' AND status IN ('QUEUED','RETRY_WAIT','RUNNING')", (task_id,)):
                    self.log.write("schedule_skip", {"reason": "previous_unfinished"}, task_id=task_id)
                    return None
            policy = {**self.timing_settings.read(), "task_timeout_seconds": task["timeout_seconds"],
                      "restart_safe": bool(self.jobs.get(task["handler"]) and self.jobs[task["handler"]].restart_safe),
                      "handler": task["handler"]}
            return self.submit_work("task.run", inputs, task_id=task_id, source=source, operation_key=operation_key,
                                    retry_limit=retry_limit, policy=policy)

    async def wait(self, request_id, *, checkpoint=None):
        while True:
            if checkpoint:
                await checkpoint()
            if request_id in self.commit_errors:
                raise self.commit_errors[request_id]
            row = self.repository.get(request_id)
            if row["status"] in TERMINAL:
                if row["status"] == "SUCCEEDED":
                    return json.loads(row["result_data"])
                if row["status"] == "CANCELLED":
                    raise asyncio.CancelledError()
                if request_id in self.errors:
                    raise self.errors[request_id]
                raise PersistedFailure(json.loads(row["error_data"] or "{}"))
            if self.fault and not row["control"] and row["status"] in {"QUEUED", "RETRY_WAIT"}:
                raise PersistedFailure(self.fault)
            self.dispatcher.dispatch()
            await asyncio.sleep(self.poll_interval)

    async def child(self, aid, eid, kind, inputs, *, control=False, operation_key=None):
        rid = self.submit_work(kind, inputs, parent_attempt_id=aid, execution_id=eid,
                               control=control, operation_key=operation_key)
        return await self.wait(rid)

    async def _cancel_operation(self, row, *args):
        values = json.loads(row["run_input"])
        target = self.repository.get(values["request_id"])
        if target["control"]:
            raise ValueError("不能通过取消命令中断收尾控制命令")
        expected = values.get("expected_attempt_id")
        if expected is not None and (target["last_attempt_id"] != expected or target["status"] != "RUNNING"):
            return {"applied": False, "reason": "该执行尝试已结束，未取消其他尝试"}
        return {"command_id": await self.cancel_request(target["id"], values.get("reason", "CANCELLED")), "applied": True}

    async def _task(self, row, aid, eid, lease_id):
        inputs = json.loads(row["run_input"])
        if inputs.get("skill_path"):
            self.store.update("execution_info", eid, skill_content=load_skill(inputs["skill_path"]))
        self._log(eid, "started", {"attempt_id": aid})
        policy = json.loads(row["policy"])
        return await self.jobs[policy["handler"]].run(ExecutionContext(self, eid, aid))

    async def _acquire(self, row, aid, eid, lease_id):
        return await self.pool.acquire_once(lease_id)

    def _user_stopped(self, eid, row):
        # A release requested by the current task is a cooperative handoff boundary.
        parent = row["parent_attempt_id"]
        if parent and eid not in self.runtime.processes:
            owner = self.store.one("SELECT execution_id FROM work_attempt WHERE id=?", (parent,))
            if not owner or owner["execution_id"] != eid:
                return False
            return not self.store.one("SELECT id FROM work_request WHERE execution_id=? AND status IN ('QUEUED','RETRY_WAIT','RUNNING') "
                                     "AND kind IN ('script.run','tool.call','ziniao.acquire')", (eid,))
        return (eid not in self.running and eid not in self.runtime.processes and not self.store.one(
            "SELECT id FROM work_request WHERE execution_id=? AND status IN ('QUEUED','RETRY_WAIT','RUNNING') "
            "AND kind IN ('script.run','tool.call','ziniao.acquire')", (eid,)))

    async def _release(self, row, aid, eid, lease_id):
        inputs = json.loads(row["run_input"])
        lease = self.pool.get(inputs["lease_id"])
        if eid is not None and lease["execution_id"] != eid:
            raise ValueError("不能归还其他执行持有的窗口")
        return await self.pool.release_once(lease["id"], user_stopped=self._user_stopped(lease["execution_id"], row))

    async def _inspect(self, row, aid, eid, lease_id):
        lease = self.pool.get(json.loads(row["run_input"])["lease_id"])
        if eid is not None and lease["execution_id"] != eid:
            raise ValueError("窗口所属执行与核验请求不匹配")
        return await self.pool.inspect_once(lease["id"], user_stopped=self._user_stopped(lease["execution_id"], row))

    async def _script(self, row, aid, eid, lease_id):
        inputs = json.loads(row["run_input"])
        result = await self.runtime.run(eid, inputs["argv"], **inputs.get("options", {}))
        if result.get("returncode", 0):
            error = subprocess.CalledProcessError(result["returncode"], inputs["argv"],
                                                  output=result.get("stdout"), stderr=result.get("stderr"))
            error.output_call_id = result.get("output_call_id")
            raise error
        return result

    async def _tool(self, row, aid, eid, lease_id):
        inputs = json.loads(row["run_input"])
        return await self.tools.call(inputs["name"], eid, **inputs.get("params", {}))

    def replay_safe(self, row):
        if row["kind"] == "task.run":
            return json.loads(row["policy"]).get("restart_safe", False)
        if row["kind"] == "tool.call":
            return self.tools.safety.get(json.loads(row["run_input"])["name"], False)
        return self.executors[row["kind"]].restart_safe

    async def execute(self, rid, aid, eid, lease_id, admission_error=None):
        self.started.add(rid)
        row = self.repository.get(rid)
        result, evidence, status = None, None, "SUCCEEDED"
        confirmed_safe = False
        try:
            try:
                if admission_error:
                    raise admission_error
                result = await self.executors[row["kind"]].execute(row, aid, eid, lease_id)
                encode(result)  # Reject invalid executor output before the final database commit.
            except asyncio.CancelledError as exc:
                status = self.stop_reasons.get(rid, "CANCELLED")
                evidence = exception_details(exc)
            except Exception as exc:
                result = None
                self.errors[rid] = exc
                confirmed_safe = row["kind"] == "ziniao.acquire" and getattr(exc, "retry_safe", False)
                evidence, status = exception_details(exc), "TIMEOUT" if isinstance(exc, TimeoutError) else "FAILED"
                if row["kind"] == "task.run":
                    self._log(eid, "execution_error", evidence)
                if row["kind"] in {"script.run", "tool.call"} and not self.replay_safe(row) and not isinstance(exc, (ValueError, KeyError, TimeoutError)):
                    status = "NEEDS_REVIEW"
            self.finishing.add(rid)
            if row["kind"] == "task.run":
                # All child use must stop before any lease is handed back.
                try:
                    await self.cancel_children(aid)
                    for lease in self.store.all("SELECT * FROM resource_lease WHERE execution_id=? AND status='ACTIVE'", (eid,)):
                        await self.child(aid, eid, "ziniao.release", {"lease_id": lease["id"]}, control=True,
                                         operation_key=f"cleanup:{aid}:{lease['id']}")
                except Exception as exc:
                    cleanup = exception_details(exc)
                    self._log(eid, "cleanup_incomplete", cleanup)
                    evidence = {**(evidence or cleanup), "cleanup_error": cleanup,
                                "error": ((evidence["error"] + "; 收尾失败：") if evidence else "") + cleanup["error"]}
                    if status == "SUCCEEDED":
                        self.errors[rid] = exc
                        status = "NEEDS_REVIEW"
                unresolved = self.store.all("SELECT id,shop_id,error_message FROM resource_lease WHERE execution_id=? "
                                             "AND status IN ('OPENING','ACTIVE','CLOSING')", (eid,))
                reviews = self.store.all("SELECT id,error_data FROM work_request WHERE parent_attempt_id=? AND status='NEEDS_REVIEW'", (aid,))
                if unresolved or reviews:
                    if status not in {"CANCELLED", "TIMEOUT"}:
                        status = "NEEDS_REVIEW"
                    evidence = {**(evidence or {"error": "; ".join(x["error_message"] or "尚未取得窗口关闭确认" for x in unresolved) or "; ".join(json.loads(x["error_data"] or "{}").get("error", "子操作尚未确认结果") for x in reviews)}),
                                "unresolved_leases": unresolved, "child_reviews": reviews}
            if rid in self.stop_reasons and (status == "SUCCEEDED" or row["kind"] in {"task.run", "script.run", "tool.call"}):
                status = self.stop_reasons[rid]
            if len(self.errors) > 128:
                self.errors.popitem(last=False)
            finish(self, rid, status, result=result, error=evidence,
                   safe=(self.replay_safe(row) or confirmed_safe) and rid not in self.stopping)
        except Exception as exc:
            from .faults import record_commit_failure
            record_commit_failure(self, rid, aid, exc, status=status, result=result, evidence=evidence)
        finally:
            self.dispatcher.runners.pop(rid, None)
            self.finishing.discard(rid)
            self.started.discard(rid)
            self._forget_terminal_control(rid)

    async def cancel_children(self, aid):
        for row in self.store.all("SELECT * FROM work_request WHERE parent_attempt_id=? AND status IN ('QUEUED','RETRY_WAIT','RUNNING')", (aid,)):
            if row["control"]:
                try:
                    await self.wait(row["id"])
                except Exception:
                    # Its failed attempt retains the original evidence; parent cleanup records occupancy.
                    pass
            else:
                await self._cancel(row["id"], "CANCELLED")

    async def _cancel(self, rid, reason):
        lock = self.cancel_locks.get(rid)
        if lock is None:
            lock = asyncio.Lock()
            self.cancel_locks[rid] = lock
        async with lock:
            try:
                await self._cancel_once(rid, reason)
            finally:
                self._forget_terminal_control(rid)

    def _forget_terminal_control(self, rid):
        try:
            row = self.repository.get(rid)
        except Exception:
            if self.fault:
                return  # Storage failure and both traces have already been recorded.
            raise
        if row["status"] in TERMINAL:
            self.stopping.discard(rid)
            self.stop_reasons.pop(rid, None)
            if row["status"] == "SUCCEEDED":
                self.errors.pop(rid, None)

    async def _cancel_once(self, rid, reason):
        row = self.repository.get(rid)
        if row["status"] in TERMINAL:
            return
        self.stopping.add(rid)
        self.stop_reasons.setdefault(rid, reason)
        if row["kind"] == "task.run" and row["last_execution_id"]:
            execution = self.execution(row["last_execution_id"])
            if execution["stop_requested_at"] is None:
                self.store.update("execution_info", execution["id"], stop_requested_at=self.clock())
        if row["status"] in {"QUEUED", "RETRY_WAIT"}:
            with self.store.transaction():
                self.store.update("work_request", rid, status=reason, version=row["version"]+1)
            return
        if rid not in self.started:
            await asyncio.sleep(0)
        await self.cancel_children(row["last_attempt_id"])
        runner = self.dispatcher.runners.get(rid)
        if runner and runner is not asyncio.current_task():
            if row["kind"] == "script.run":
                await self.runtime.stop(row["execution_id"])
            # By default every executor settles its actual call before cancellation is
            # confirmed. Cancelling to_thread would otherwise leave untracked work alive.
            if rid not in self.finishing and self.executors[row["kind"]].interruptible:
                runner.cancel()
            await asyncio.shield(runner)

    async def cancel_request(self, request_id, reason="CANCELLED"):
        if reason not in {"CANCELLED", "TIMEOUT"}:
            raise ValueError("停止结果只能是 CANCELLED 或 TIMEOUT")
        command = self.repository.command("cancel", request_id)
        try:
            await self._cancel(request_id, reason)
            row = self.repository.get(request_id)
            if row["status"] not in TERMINAL:
                raise RuntimeError("停止尚未确认，请查看请求原始错误和运行状态")
            self.repository.confirm(command)
        except BaseException as exc:
            self.repository.confirm(command, error=exception_details(exc))
            raise
        return command

    async def stop_execution(self, eid, reason="CANCELLED"):
        row = self.execution(eid)
        self.store.update("execution_info", eid, stop_requested_at=self.clock())
        return await self.cancel_request(row["request_id"], reason)

    def execution(self, eid):
        return self.store.one("SELECT * FROM execution_info WHERE id=?", (eid,))

    def _freeze(self, eid):
        row = self.execution(eid)
        start, stop = timing.freeze(row["timer_started_at"], row["timer_stopped_at"], self.clock())
        self.store.update("execution_info", eid, timer_started_at=start, timer_stopped_at=stop)

    def _resume_timer(self, eid):
        row = self.execution(eid)
        start, stop = timing.resume(row["timer_started_at"], row["timer_stopped_at"], self.clock())
        self.store.update("execution_info", eid, timer_started_at=start, timer_stopped_at=stop)

    def _log(self, eid, action, content):
        self.log.write(action, content, execution_id=eid,
                       task_id=self.execution(eid)["task_id"], level="ERROR" if action in {"execution_error", "cleanup_incomplete"} else "INFO")

    def request_pause(self, eid, reason="manual"):
        if eid not in self.running:
            raise ValueError("执行不在运行中")
        if eid in self.pause_requests:
            return self.pause_ids[eid]
        previous = self.resume_commands.pop(eid, None)
        if previous:
            self.repository.confirm(previous, error={"error": "继续命令在执行恢复前被暂停命令撤销"})
        command = self.repository.command("pause", eid)
        self.pause_requests[eid], self.pause_commands[eid] = reason, command
        self.pause_ids[eid] = command
        return command

    def resume_execution(self, eid):
        if eid not in self.running:
            raise ValueError("原运行上下文不存在，不能从内存中断处继续")
        if eid in self.resume_commands:
            return self.resume_commands[eid]
        command = self.repository.command("resume", eid)
        self.pause_requests.pop(eid, None)
        self.pause_ids.pop(eid, None)
        previous = self.pause_commands.pop(eid, None)
        if previous:
            self.repository.confirm(previous, error={"error": "暂停在到达检查点前被继续命令撤销"})
        if self.execution(eid)["status"] == "PAUSED":
            self.resume_commands[eid] = command
        else:
            self.repository.confirm(command)
        return command

    async def checkpoint(self, eid):
        if self.execution(eid)["request_id"] in self.stopping:
            raise asyncio.CancelledError()
        while eid in self.pause_requests:
            if self.execution(eid)["request_id"] in self.stopping:
                raise asyncio.CancelledError()
            self._freeze(eid)
            self.store.update("execution_info", eid, status="PAUSED", pause_reason=self.pause_requests[eid])
            command = self.pause_commands.pop(eid, None)
            if command:
                self.repository.confirm(command)
            await asyncio.sleep(self.poll_interval)
        row = self.execution(eid)
        if row["status"] == "PAUSED":
            self.store.update("execution_info", eid, status="RUNNING", pause_reason=None)
            if row["wait_reason"] != "WINDOW":
                self._resume_timer(eid)
            command = self.resume_commands.pop(eid, None)
            if command:
                self.repository.confirm(command)

    def continue_from(self, eid):
        row = self.execution(eid)
        if not row or row["status"] not in TERMINAL or not row["resume_enabled"]:
            raise ValueError("请选择已结束且启用断点续跑的执行")
        inputs = json.loads(row["run_input"])
        inputs.update(_resume_data=json.loads(row["resume_data"] or "{}"), _previous_execution_id=eid)
        return self.submit(row["task_id"], source="continue", input_data=inputs)

    async def dispatch(self):
        self.dispatcher.dispatch()

    async def collect_expired(self):
        for eid in list(self.running):
            row = self.execution(eid)
            if timing.elapsed(row["timer_started_at"], row["timer_stopped_at"], self.clock()) >= row["timeout_seconds"]:
                self._queue_expiry(row)
        for lease in self.store.all("SELECT * FROM resource_lease WHERE status='ACTIVE' AND expires_at<=?", (self.clock(),)):
            self._queue_expiry(self.execution(lease["execution_id"]))
        # 催债人：该回收的租约转 CLOSING，再逐个关窗；失败就留在 CLOSING，下次再试。
        grace = self.timing_settings.read()["window_lease_seconds"]
        for lease in self.store.all("SELECT * FROM resource_lease WHERE status='ACTIVE'"):
            if lease["expires_at"] and lease["expires_at"] <= self.clock() - grace:
                self.pool.mark_closing(lease, "租约到期且执行未响应，等待回收")
            elif self._execution_gone(lease["execution_id"]):
                self.pool.mark_closing(lease, "执行已结束但窗口未归还，等待回收")
        now = time.monotonic()
        for lease in self.store.all("SELECT * FROM resource_lease WHERE status='CLOSING'"):
            if now - self.reclaim_attempts.get(lease["id"], 0) < self.reclaim_interval:
                continue
            self.reclaim_attempts[lease["id"]] = now
            try:
                await self.pool.reclaim(lease)
            except Exception:
                pass

    def _execution_gone(self, eid):
        if eid in self.running or eid in self.runtime.processes:
            return False
        return not self.store.one(
            "SELECT id FROM work_request WHERE execution_id=? AND status IN ('QUEUED','RETRY_WAIT','RUNNING')", (eid,))

    def _queue_expiry(self, execution):
        row = self.repository.get(execution["request_id"])
        if row["status"] != "RUNNING" or row["last_execution_id"] != execution["id"]:
            return
        self.submit_work("control.cancel", {"request_id": row["id"], "reason": "TIMEOUT",
                         "expected_attempt_id": row["last_attempt_id"]},
                         operation_key=f"timeout:{row['last_attempt_id']}", source="timeout")

    async def tick(self):
        self.dispatcher.dispatch()
        await self.collect_expired()

    async def recover(self):
        from .recovery import recover
        await recover(self)

    def begin_drain(self):
        if not self.draining:
            self.accepting, self.draining = False, True
            self.drain_command = self.repository.command("drain")
            self.system.write("shutdown_started", {"message": "停止接单和新根请求派发，保留子操作与控制"})
        return self.drain_command

    async def drain(self, timeout=None):
        command = self.begin_drain()
        policy = self.timing_settings.read()
        action = "cancel" if timeout is not None else policy["shutdown_timeout_action"]
        deadline = time.monotonic() + (timeout if timeout is not None else policy["shutdown_wait_seconds"])
        expired = False
        try:
            while self.dispatcher.runners or self.store.one(
                "SELECT id FROM work_request WHERE control=1 AND status IN ('QUEUED','RETRY_WAIT')"):
                if not expired and time.monotonic() >= deadline:
                    expired = True
                    self.system.write("shutdown_wait_elapsed", {"action": action}, level="WARNING")
                    if action == "cancel":
                        for row in self.store.all("SELECT id FROM work_request WHERE status='RUNNING' AND parent_attempt_id IS NULL AND control=0"):
                            self.submit_work("control.cancel", {"request_id": row["id"]},
                                             operation_key=f"drain:{command}:{row['id']}", source="shutdown")
                await self.tick()
                await asyncio.sleep(self.poll_interval)
            incomplete = self.store.all("SELECT id,error_data FROM work_request WHERE status='RUNNING'")
            if incomplete:
                if self.fault:
                    raise PersistedFailure(self.fault)
                raise RuntimeError(f"仍有未确认完成的工作请求：{[r['id'] for r in incomplete]}")
            pending = self.store.all("SELECT * FROM resource_lease WHERE status IN ('ACTIVE','OPENING','CLOSING')")
            if pending:
                raise RuntimeError("服务退出时窗口尚未释放：" + "; ".join(
                    f"店铺 {x['shop_id']}：{x['error_message'] or '未取得关闭确认'}" for x in pending))
            self.repository.confirm(command)
        except BaseException as exc:
            self.repository.confirm(command, error=exception_details(exc))
            raise

    def snapshot(self):
        executions = self.store.all("SELECT * FROM execution_info ORDER BY id DESC")
        for row in executions:
            row["elapsed_seconds"] = timing.elapsed(row["timer_started_at"], row["timer_stopped_at"], self.clock())
        requests = self.store.all("SELECT r.*,b.used AS retry_count,b.retry_limit FROM work_request r "
                                  "JOIN retry_budget b ON b.id=r.budget_id ORDER BY r.id")
        for request in requests:
            if "_sealed" in request["run_input"]:
                request["run_input"] = json.dumps({"mode": json.loads(request["run_input"]).get("mode")})
        return {"tasks": self.store.all("SELECT * FROM task_info ORDER BY id"), "requests": requests,
                "executions": executions, "attempts": self.store.all("SELECT * FROM work_attempt ORDER BY id"),
                "commands": self.store.all("SELECT * FROM control_command ORDER BY id"),
                "leases": self.store.all("SELECT * FROM resource_lease ORDER BY id"),
                "resources": self.store.all("SELECT * FROM resource_info ORDER BY id"),
                "cases": self.store.all("SELECT id,sid,store_name,marketplace_id,order_id,rating,status,reason,"
                                        "execution_id,case_ref,updated_at FROM feedback_case ORDER BY id"),
                "accepting": self.accepting, "draining": self.draining,
                "fault": self.fault,
                "settings": {"retry": self.retry_settings.read(), "queue": self.queue_settings.read(),
                             "tools": self.tool_settings.read(),
                             "integrations": self.integration_settings.all_public(),
                             "runtime": {"timing": self.timing_settings.read()}}}
