"""All work submission and claim writes occur in synchronous transactions."""
import hashlib
import json

from ..logs.writer import LogWriter


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


class Repository:
    def __init__(self, store, clock):
        self.store, self.clock = store, clock
        self.log = LogWriter(store, "execution_log")
        self.system = LogWriter(store, "system_log")

    def get(self, identity):
        row = self.store.one("SELECT * FROM work_request WHERE id=?", (identity,))
        if row is None:
            raise KeyError(identity)
        return row

    def submit(self, kind, inputs, *, policy, retry_limit, parent_attempt_id=None,
               operation_key=None, task_id=None, execution_id=None, source="manual", control=False):
        payload = encode(inputs)
        fingerprint = hashlib.sha256(encode([kind, {k: v for k, v in inputs.items() if k != "_sealed"}, task_id, parent_attempt_id]).encode()).hexdigest()
        with self.store.transaction():
            if operation_key:
                old = self.store.one("SELECT * FROM work_request WHERE operation_key=?", (operation_key,))
                if old:
                    if old["input_hash"] != fingerprint:
                        raise ValueError("提交键已用于不同的请求内容，请使用新的提交键")
                    return old["id"]
            parent = None
            if parent_attempt_id:
                parent = self.store.one("SELECT r.* FROM work_request r JOIN work_attempt a ON a.request_id=r.id WHERE a.id=?", (parent_attempt_id,))
                if parent is None:
                    raise ValueError("父执行尝试不存在")
            budget = parent["budget_id"] if parent and not control else self.store.insert(
                "retry_budget", {"retry_limit": retry_limit, "used": 0})
            previous = self.store.one("SELECT id FROM work_request WHERE task_id=? AND kind='task.run' ORDER BY id DESC LIMIT 1", (task_id,)) if kind == "task.run" else None
            identity = self.store.insert("work_request", {
                "kind": kind, "previous_request_id": previous["id"] if previous else None, "run_input": payload, "input_hash": fingerprint,
                "operation_key": operation_key, "task_id": task_id, "execution_id": execution_id,
                "parent_attempt_id": parent_attempt_id, "root_id": parent["root_id"] if parent else None,
                "budget_id": budget, "policy": encode(policy), "source": source,
                "control": int(control), "status": "QUEUED", "created_at": self.clock(),
            })
            if not parent:
                self.store.update("work_request", identity, root_id=identity)
            self.log.write("work_queued", {"request_id": identity, "kind": kind,
                           "parent_attempt_id": parent_attempt_id}, task_id=task_id, execution_id=execution_id)
            return identity

    def command(self, kind, target=None):
        with self.store.transaction():
            identity = self.store.insert("control_command", {"kind": kind, "target_id": target,
                                        "status": "SUBMITTED", "created_at": self.clock()})
            self.system.write("control_submitted", {"command_id": identity, "kind": kind, "target_id": target})
            return identity

    def confirm(self, command_id, *, error=None):
        with self.store.transaction():
            self.store.update("control_command", command_id, status="FAILED" if error else "CONFIRMED",
                              finished_at=self.clock(), error_data=encode(error) if error else None)
            self.system.write("control_failed" if error else "control_confirmed",
                              {"command_id": command_id, **(error or {})}, level="ERROR" if error else "INFO")
