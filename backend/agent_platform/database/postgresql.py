"""PostgreSQL 后端：可选 psycopg 依赖、事务式建表与占位符方言。"""
from .adapter import DatabaseAdapter
from .errors import DatabaseCode, DatabaseError


class PostgresAdapter(DatabaseAdapter):
    NAME = "postgresql"
    label = "PostgreSQL"

    def connect(self, source: str):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise DatabaseError("PostgreSQL requires optional dependency: psycopg[binary]",
                                DatabaseCode.CONNECTION_FAILED) from exc
        try:
            return psycopg.connect(source, autocommit=True, row_factory=dict_row)
        except Exception as exc:
            raise DatabaseError(f"连接 PostgreSQL 失败：{exc}", DatabaseCode.CONNECTION_FAILED) from exc

    def initialize(self, connection, schema: str) -> None:
        try:
            with connection.transaction(), connection.cursor() as cursor:
                cursor.execute(schema)
        except Exception as exc:
            raise DatabaseError(f"建立 PostgreSQL 表结构失败：{exc}", DatabaseCode.SCHEMA_FAILED) from exc

    def begin(self) -> str:
        return "BEGIN"

    def placeholders(self, sql: str) -> str:
        """把问号占位符翻译成 %s，保留 SQL 字符串里的问号。"""
        parts, quote, index = [], None, 0
        while index < len(sql):
            char = sql[index]
            if quote:
                parts.append(char)
                if char == quote:
                    if index + 1 < len(sql) and sql[index + 1] == quote:
                        parts.append(quote)
                        index += 1
                    else:
                        quote = None
            elif char in ("'", '"'):
                quote = char
                parts.append(char)
            else:
                parts.append("%s" if char == "?" else char)
            index += 1
        return "".join(parts)
