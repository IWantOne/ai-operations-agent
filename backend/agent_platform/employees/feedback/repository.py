"""差评台账：本员工业务表的唯一读写入口，handler 不直接写 SQL。"""
import json
import time


def by_order(manager, sid, marketplace_id, order_id):
    return manager.store.one(
        "SELECT id FROM feedback_case WHERE sid=? AND marketplace_id=? AND order_id=?",
        (sid, marketplace_id, order_id))


def touch(manager, case_id, external_id, now):
    manager.store.update("feedback_case", case_id, updated_at=now, external_id=external_id)


def insert_case(manager, record, now):
    return manager.store.insert("feedback_case", {
        **record, "status": "NEW", "reason": "", "created_at": now, "updated_at": now})


def new_cases(manager, limit):
    return manager.store.all(
        "SELECT * FROM feedback_case WHERE status='NEW' ORDER BY id LIMIT ?", (int(limit),))


def set_execution(manager, case_id, execution_id):
    manager.store.update("feedback_case", case_id, execution_id=execution_id)


def update_case(manager, case_id, **changes):
    changes.setdefault("updated_at", time.time())
    manager.store.update("feedback_case", case_id, **changes)


def mark(manager, case_id, status, reason, evidence):
    now = time.time()
    case = manager.store.one("SELECT execution_id FROM feedback_case WHERE id=?", (case_id,))
    manager.store.update("feedback_case", case_id, status=status, reason=reason,
                         evidence=json.dumps(evidence, ensure_ascii=False), updated_at=now)
    # 每次处理都记一个批次，日志按 execution_id 关联，明细下可查处理历史。
    manager.store.insert("feedback_case_run", {
        "case_id": case_id, "execution_id": case["execution_id"] if case else None,
        "status": status, "reason": reason, "at": now})


def reportable(manager, limit=20):
    return manager.store.all(
        "SELECT * FROM feedback_case WHERE status IN ('SUBMITTED','REMOVED') "
        "AND reported_at IS NULL ORDER BY id LIMIT ?", (int(limit),))


def mark_reported(manager, case_id, ok, body, now):
    manager.store.update("feedback_case", case_id,
                         reported_at=now if ok else None,
                         report_error="" if ok else str(body)[:500])


def detail_rows(manager, limit):
    return manager.store.all(
        "SELECT id,sid,store_name,marketplace_id,order_id,rating,status,reason,execution_id,case_ref,updated_at "
        "FROM feedback_case ORDER BY id DESC LIMIT ?", (int(limit),))


def case_runs(manager, case_ids):
    result = {}
    if not case_ids:
        return result
    marks = ",".join("?" * len(case_ids))
    for run in manager.store.all(
            f"SELECT id,case_id,execution_id,status,reason,at FROM feedback_case_run "
            f"WHERE case_id IN ({marks}) ORDER BY at DESC", case_ids):
        result.setdefault(run["case_id"], []).append(run)
    return result


def counts(manager):
    return manager.store.all("SELECT status,count(*) AS total FROM feedback_case GROUP BY status")
