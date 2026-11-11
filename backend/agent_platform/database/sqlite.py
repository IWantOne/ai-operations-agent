"""SQLite 后端：连接、事务式建表与方言。驱动异常翻译成 DatabaseError。"""
from pathlib import Path
import sqlite3

from .adapter import DatabaseAdapter
from .errors import DatabaseCode, DatabaseError


class SQLiteAdapter(DatabaseAdapter):
    NAME = "sqlite"
    label = "SQLite"

    def connect(self, source: str):
        if source != ":memory:":
            Path(source).parent.mkdir(parents=True, exist_ok=True)
        try:
            connection = sqlite3.connect(source, isolation_level=None, check_same_thread=False, timeout=10)
        except sqlite3.Error as exc:
            raise DatabaseError(f"打开 SQLite 数据库失败：{exc}", DatabaseCode.CONNECTION_FAILED) from exc
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA busy_timeout=10000")
        except sqlite3.Error as exc:
            connection.close()
            raise DatabaseError(f"初始化 SQLite 连接失败：{exc}", DatabaseCode.CONNECTION_FAILED) from exc
        return connection

    def initialize(self, connection, schema: str) -> None:
        try:
            connection.executescript("BEGIN IMMEDIATE;\n" + schema + "\nCOMMIT;")
        except sqlite3.Error as exc:
            raise DatabaseError(f"建立 SQLite 表结构失败：{exc}", DatabaseCode.SCHEMA_FAILED) from exc

    def begin(self) -> str:
        return "BEGIN IMMEDIATE"
