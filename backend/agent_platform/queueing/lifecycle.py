"""Single atomic final commit: attempt, request, projection, budget and event."""
from .models import TERMINAL
from .repository import encode
from .retry import reserve_retry


def finish(service, request_id, status, *, result=None, error=None, safe=False):
    store, now = service.store, service.clock()
    if status not in TERMINAL:
        raise ValueError(f"Invalid final status: {status}")
    with store.transaction():
        request = service.repository.get(request_id)
        if request["status"] in TERMINAL:
            return
        if request["status"] != "RUNNING":
            raise ValueError(f"Request {request_id} has not started")
        attempt = store.one("SELECT * FROM work_attempt WHERE id=?", (request["last_attempt_id"],))
        if attempt["status"] != "RUNNING":
            raise ValueError("Attempt already settled")
        retry_at = reserve_retry(store, request, status, safe=safe, now=now)
        store.update("work_attempt", attempt["id"], status=status, finished_at=now,
                     result_data=encode(result), error_data=encode(error) if error else None,
                     stop_confirmed_at=now if status in {"CANCELLED", "TIMEOUT"} else None)
        store.update("work_request", request_id, status="RETRY_WAIT" if retry_at is not None else status,
                     ready_at=retry_at, wait_reason="retry" if retry_at is not None else None,
                     result_data=encode(result), error_data=encode(error) if error else None,
                     version=request["version"]+1)
        if request["kind"] == "task.run":
            eid = request["last_execution_id"]
            service._freeze(eid)
            store.update("execution_info", eid, status=status, finished_at=now,
                         result_data=encode(result), error_message=error.get("error") if error else None,
                         wait_reason=None, waiting_since=None,
                         stop_confirmed_at=now if status in {"CANCELLED", "TIMEOUT"} else None)
            for commands in (service.pause_commands, service.resume_commands):
                command = commands.get(eid)
                if command:
                    service.repository.confirm(command, error={"error": "执行已经结束，未到达此控制命令的确认点"})
        service.log.write("work_finished", {"request_id": request_id,
                          "attempt_id": attempt["id"], "kind": request["kind"], "status": status,
                          "error": error, "retry_at": retry_at}, task_id=request["task_id"],
                          execution_id=request["last_execution_id"] or request["execution_id"],
                          level="ERROR" if error else "INFO")
    if request["kind"] == "task.run":
        for mapping in (service.pause_commands, service.resume_commands, service.pause_requests, service.pause_ids):
            mapping.pop(request["last_execution_id"], None)
