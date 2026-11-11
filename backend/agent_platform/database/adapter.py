"""数据库适配器基类：只规定接口与统一码，具体后端各自实现。

与 ``connectors.Browser`` 同一形状：

- 基类钉住接口（连接、建表、旧结构检查、事务起始语句、占位符方言）和
  ``DatabaseCode``；少声明 ``NAME`` 的后端类定义时直接失败。
- sqlite / postgresql 负责连接、建表、方言，并把驱动异常翻译成 ``DatabaseError``，
  原始异常留在 ``__cause__`` 上。
- 本层不写日志。数据库只提供读写事实，日志由事实的拥有者按自己的语义写入。
"""
from .errors import DatabaseCode, DatabaseError

__all__ = ["DatabaseAdapter", "DatabaseCode", "DatabaseError"]


class DatabaseAdapter:
    """数据库后端：只规定接口与统一异常类型。"""

    NAME = ""
    label = "数据库"

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if not cls.__dict__.get("NAME"):
            raise TypeError(f"{cls.__name__} 必须声明 NAME")

    def connect(self, source: str):
        raise NotImplementedError

    def initialize(self, connection, schema: str) -> None:
        raise NotImplementedError

    def begin(self) -> str:
        """事务起始语句。需要更强隔离的后端可以覆盖。"""
        return "BEGIN"

    def placeholders(self, sql: str) -> str:
        """值占位符方言。默认原样返回（问号占位）。"""
        return sql
