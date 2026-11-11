"""Process-loss reconciliation: no replay of an unconfirmed side effect."""
import json
from .lifecycle import finish


async def recover(service):
    service.accepting, service.recovered, service.draining = False, False, True
    store = service.store
    for row in store.all("SELECT * FROM work_request WHERE status='RUNNING' ORDER BY id DESC"):
        evidence = {"error": "服务在执行期间中断，未收到完成结果；需核对外部实际结果",
                    "operation": row["kind"], "request_id": row["id"], "attempt_id": row["last_attempt_id"]}
        recorded = store.one("SELECT content FROM system_log WHERE action='work_commit_error' AND call_id=? ORDER BY id DESC LIMIT 1",
                             (f"attempt:{row['last_attempt_id']}",))
        if recorded:
            prior = json.loads(recorded["content"])
            evidence = {**prior, "recovery_error": evidence,
                        "error": prior["error"] + "; " + evidence["error"]}
        finish(service, row["id"], "NEEDS_REVIEW", error=evidence)
    for row in store.all("SELECT r.id,r.version FROM work_request r JOIN work_attempt a ON a.id=r.parent_attempt_id "
                         "WHERE r.status IN ('QUEUED','RETRY_WAIT') AND a.status!='RUNNING'"):
        store.update("work_request", row["id"], status="CANCELLED", version=row["version"]+1,
                     error_data='{"error":"服务中断后父执行已停止；未启动的子操作已取消"}')
    # Work is not replayed. Closed windows can be positively reconciled; live/foreign windows remain held.
    service.recovered = True
    for lease in store.all("SELECT * FROM resource_lease WHERE status IN ('OPENING','ACTIVE','CLOSING','UNKNOWN') ORDER BY id"):
        rid = service.submit_work("ziniao.inspect", {"lease_id": lease["id"]},
                                  execution_id=lease["execution_id"], control=True, source="recovery")
        try:
            await service.wait(rid)
        except Exception:
            # The executor and request retain the actual exception and full trace.
            pass
    for command in store.all("SELECT * FROM control_command WHERE status='SUBMITTED'"):
        service.repository.confirm(command["id"], error={"error": "服务在命令确认前中断，请核对实际结果"})
    if service.fault:
        raise service.commit_errors[next(iter(service.commit_errors))]
    service.draining, service.accepting = False, True
