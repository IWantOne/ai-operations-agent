"""数据库失败的分类与统一码。码表只在本模块定义。

DatabaseCode 是数据库层唯一的失败码：适配器翻译驱动异常、Store 拒绝旧结构时
都用它。调用方按 code 区分失败性质，不需要解析异常文本。
"""
from enum import Enum


class DatabaseCode(str, Enum):
    CONNECTION_FAILED = "CONNECTION_FAILED"
    SCHEMA_FAILED = "SCHEMA_FAILED"


class DatabaseError(RuntimeError):
    """数据库层失败。原始驱动异常保留在 __cause__ 上。"""

    def __init__(self, message, code=DatabaseCode.CONNECTION_FAILED):
        super().__init__(message)
        self.code = code
