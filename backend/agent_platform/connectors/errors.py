"""连接器失败的分类与统一码。分类规则和码表只在本模块定义。

框架只有两种连接器失败，用类型表达，不给异常对象挂临时属性：

- ConnectorError（基类）：远端结果不明。占用必须保留，等人工核验。
- Foreign：窗口由外部持有，不归工作台所有；池子借用时会先强制回收（关闭）再重新打开，
  调用方不得直接接管。

ConnectorCode 是连接器唯一的码表：既是 resource_log 的 action，也是异常的 code。
适配器不自己造 action 字符串，日志和异常因此说的是同一件事。

判定入口只有 no_effect() 与 is_foreign() 两个函数。调用方按这两个函数判断，
不再各自解释异常属性。改这里的类型即可全局生效。

"已确认未产生副作用"不能由连接器自己断言——必须由池子独立核验后认定。外部
调用方可以在自己的异常上声明 no_side_effect = True，no_effect() 统一承接。
"""
from enum import Enum


class ConnectorCode(str, Enum):
    """连接器统一码。写入 resource_log 时取 value，异常上保存成员本身。"""

    RAW = "CONNECTOR_RAW"
    ERROR = "CONNECTOR_ERROR"
    INTERRUPTED = "CONNECTOR_INTERRUPTED"
    OPENED = "CONNECTOR_OPENED"
    CLOSED = "CONNECTOR_CLOSED"
    FOREIGN = "CONNECTOR_FOREIGN"


class ConnectorError(RuntimeError):
    """连接器失败基类。远端结果不明，占用必须保留，等人工核验。"""

    def __init__(self, message, code=ConnectorCode.ERROR):
        super().__init__(message)
        self.code = code


class Foreign(ConnectorError):
    """窗口由外部持有，不归工作台所有；池子借用时会先强制回收（关闭）再重新打开。"""

    def __init__(self, message, code=ConnectorCode.FOREIGN):
        super().__init__(message, code)


def no_effect(exc):
    """该失败是否已确认未产生副作用。唯一判定处。"""
    return bool(getattr(exc, "no_side_effect", False))


def is_foreign(exc):
    """该失败是否因为窗口归属冲突。唯一判定处。"""
    return isinstance(exc, Foreign)
