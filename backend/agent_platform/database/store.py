"""Persistence; SQLite locally and optional PostgreSQL via psycopg.

All public SQL uses ``?`` value placeholders. Transactions are synchronous and
must never span an await. Business JSON values remain TEXT at this boundary.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import re
from . import postgresql, sqlite
import threading
import time
from typing import Any, Iterator, Sequence

LOG_TABLES = frozenset({"system_log", "execution_log", "runtime_log", "tool_call_log", "resource_log"})
TABLES = LOG_TABLES | {"task_info", "work_request", "work_attempt", "retry_budget", "control_command", "execution_info", "resource_info", "resource_lease", "feedback_case", "store_info"}


class Store:
    def __init__(self, path_or_dsn: str | Path = ":memory:") -> None:
        source = str(path_or_dsn)
        self.postgres = source.startswith(("postgresql://", "postgres://"))
        self.adapter = postgresql.PostgresAdapter() if self.postgres else sqlite.SQLiteAdapter()
        self._lock = threading.RLock()
        self._depth = 0
        schema_path = Path(__file__).resolve().parents[3] / "database" / self.adapter.NAME / "schema.sql"
        schema = schema_path.read_text(encoding="utf-8")
        self.connection = self.adapter.connect(source)
        try:
            self.adapter.initialize(self.connection, schema)
        except BaseException:
            self.connection.close()
            raise

    def _sql(self, sql: str) -> str:
        return self.adapter.placeholders(sql)

    def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        with self._lock:
            cursor = self.connection.execute(self._sql(sql), tuple(params))
            try:
                return cursor.rowcount
            finally:
                cursor.close()

    def one(self, sql: str, params: Sequence[Any] = ()) -> dict[str, Any] | None:
        with self._lock:
            cursor = self.connection.execute(self._sql(sql), tuple(params))
            try:
                row = cursor.fetchone()
                return dict(row) if row is not None else None
            finally:
                cursor.close()

    def all(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        with self._lock:
            cursor = self.connection.execute(self._sql(sql), tuple(params))
            try:
                return [dict(row) for row in cursor.fetchall()]
            finally:
                cursor.close()

    @staticmethod
    def _validate(table: str, fields: dict[str, Any]) -> None:
        if table not in TABLES or any(not re.fullmatch(r"[a-z_][a-z0-9_]*", field) for field in fields):
            raise ValueError("Invalid table or field name")

    def insert(self, table: str, data: dict[str, Any]) -> int:
        self._validate(table, data)
        if not data:
            row = self.one(f"INSERT INTO {table} DEFAULT VALUES RETURNING id")
        else:
            row = self.one(f"INSERT INTO {table} ({','.join(data)}) VALUES ({','.join('?' for _ in data)}) RETURNING id", tuple(data.values()))
        assert row is not None
        return int(row["id"])

    def update(self, table: str, id: int, **fields: Any) -> int:
        self._validate(table, fields)
        if not fields:
            return 0
        return self.execute(f"UPDATE {table} SET {','.join(key + '=?' for key in fields)} WHERE id=?", (*fields.values(), id))

    @contextmanager
    def transaction(self) -> Iterator["Store"]:
        with self._lock:
            depth = self._depth
            savepoint = f"nested_{depth}"
            self.execute(f"SAVEPOINT {savepoint}" if depth else self.adapter.begin())
            self._depth += 1
            try:
                yield self
            except BaseException:
                self.execute(f"ROLLBACK TO SAVEPOINT {savepoint}" if depth else "ROLLBACK")
                if depth:
                    self.execute(f"RELEASE SAVEPOINT {savepoint}")
                raise
            else:
                self.execute(f"RELEASE SAVEPOINT {savepoint}" if depth else "COMMIT")
            finally:
                self._depth -= 1

    def log(self, table: str, action: str, content: Any, task_id: int | None = None,
            execution_id: int | None = None, borrow_id: int | None = None,
            level: str = "INFO", call_id: str | None = None) -> int:
        if table not in LOG_TABLES:
            raise ValueError("Logs must use a domain log table")
        return self.insert(table, {"task_id": task_id, "execution_id": execution_id,
            "borrow_id": borrow_id, "call_id": call_id, "level": level, "action": action,
            "content": content if isinstance(content, str) else json.dumps(content, ensure_ascii=False),
            "occurred_at": time.time()})

    def close(self) -> None:
        with self._lock:
            self.connection.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
