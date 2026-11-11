"""The sole business dispatcher. No database transaction crosses an await."""
import asyncio
import json
from ..logs.errors import exception_details


class Dispatcher:
    def __init__(self, service):
        self.service = service
        self.runners = {}

    def resource_shop(self, row):
        values = json.loads(row["run_input"])
        if row["kind"] == "ziniao.acquire":
            return values["shop_id"]
        if row["kind"] in {"ziniao.release", "ziniao.inspect"}:
            return self.service.pool.get(values["lease_id"])["shop_id"]
        return None

    def dispatch(self):
        s, store = self.service, self.service.store
        if not s.recovered:
            return
        capacity = s.queue_settings.read()
        occupied = {lane: 0 for lane in ("tasks", "ziniao", "operations", "control", "commands")}
        busy_shops = set()
        for rid in self.runners:
            row = s.repository.get(rid)
            occupied[s.lane(row)] += 1
            try:
                shop = self.resource_shop(row)
            except (KeyError, ValueError, TypeError):
                shop = None  # Admission error is recorded by this running attempt.
            if shop:
                busy_shops.add(shop)
        rows = store.all("SELECT * FROM work_request WHERE status IN ('QUEUED','RETRY_WAIT') "
                         "AND (ready_at IS NULL OR ready_at<=?) ORDER BY control DESC,created_at,id", (s.clock(),))
        blocked_shops = set()
        for row in rows:
            if s.fault and not row["control"]:
                continue
            if row["parent_attempt_id"]:
                parent = store.one("SELECT a.status,a.request_id FROM work_attempt a WHERE a.id=?", (row["parent_attempt_id"],))
                if not parent or parent["status"] != "RUNNING":
                    store.update("work_request", row["id"], status="CANCELLED", version=row["version"]+1,
                                 error_data=json.dumps({"error": "父执行尝试已结束，未启动的子操作已取消"}, ensure_ascii=False))
                    continue
                if parent["request_id"] in s.stopping and not row["control"]:
                    continue
            if row["id"] in s.stopping or (s.draining and row["parent_attempt_id"] is None and not row["control"]):
                continue
            lane = s.lane(row)
            if occupied[lane] >= capacity[lane]:
                continue
            inputs = json.loads(row["run_input"])
            error = None
            operation_shop = None
            try:
                operation_shop = self.resource_shop(row)
                if operation_shop and operation_shop in busy_shops:
                    continue
                if row["kind"] == "task.run":
                    task = store.one("SELECT * FROM task_info WHERE id=?", (row["task_id"],))
                    if not task["enabled"]:
                        continue
                if row["kind"] == "ziniao.acquire":
                    shop = inputs["shop_id"]
                    if shop in blocked_shops:
                        continue
                    blocked_shops.add(shop)
                    if row["execution_id"] in s.pause_requests:
                        continue
                    if not s.pool.eligible(row["execution_id"], shop, capacity["windows"]):
                        resource = store.one("SELECT error_message FROM resource_info WHERE shop_id=?", (shop,))
                        reason = (resource or {}).get("error_message") or "等待店铺互斥或可用窗口容量"
                        store.update("work_request", row["id"], wait_reason=reason)
                        continue
            except Exception as exc:
                error = exc
            try:
                with store.transaction():
                    current = s.repository.get(row["id"])
                    if current["status"] not in {"QUEUED", "RETRY_WAIT"}:
                        continue
                    now = s.clock()
                    eid = row["execution_id"]
                    if row["kind"] == "task.run":
                        task = store.one("SELECT * FROM task_info WHERE id=?", (row["task_id"],))
                        eid = store.insert("execution_info", {
                            "task_id": task["id"], "request_id": row["id"], "status": "RUNNING",
                            "run_input": row["run_input"], "runtime_data": "{}",
                            "resume_data": json.dumps(inputs.get("_resume_data", {})),
                            "started_at": now, "timer_started_at": now,
                            "timeout_seconds": json.loads(row["policy"])["task_timeout_seconds"],
                            "resume_enabled": task["resume_enabled"],
                        })
                    aid = store.insert("work_attempt", {"request_id": row["id"], "executor": row["kind"],
                                       "status": "RUNNING", "execution_id": eid, "started_at": now})
                    store.update("work_request", row["id"], status="RUNNING", dispatched_at=now,
                                 last_attempt_id=aid, last_execution_id=eid if row["kind"] == "task.run" else None,
                                 wait_reason=None, version=row["version"]+1)
                    lease_id = None
                    if row["kind"] == "ziniao.acquire" and error is None:
                        lease_id = s.pool.reserve(eid, inputs["shop_id"])
                runner = asyncio.create_task(s.execute(row["id"], aid, eid, lease_id, error), name=f"work-{row['id']}")
                self.runners[row["id"]] = runner
                occupied[lane] += 1
                if operation_shop:
                    busy_shops.add(operation_shop)
            except Exception as exc:
                # Admission failed before external execution. Keep intent intact, report evidence.
                s.system.write("work_dispatch_error", {"request_id": row["id"], **exception_details(exc)}, level="ERROR")

