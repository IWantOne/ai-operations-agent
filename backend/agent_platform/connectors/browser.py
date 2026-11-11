"""浏览器适配器基类：只规定接口、统一异常类型与连接器码表，不实现、不写日志。

- 四个公开方法只声明语义，实现、异常翻译和 resource_log 由 CliBrowser /
  WebDriverBrowser 各自完成。
- ConnectorCode 是唯一的码表：适配器写日志和抛异常都只能取这里的码，
  两种连接方式因此不会各写各的事件名。
"""
from .errors import ConnectorCode, ConnectorError, Foreign

__all__ = ["Browser", "ConnectorCode", "ConnectorError", "Foreign"]


class Browser:
    """适配器基类：只规定接口与统一异常类型。"""

    label = "浏览器"

    def __init__(self, store, stores):
        self.store = store
        self.stores = dict(stores)

    def _require_shop(self, shop_id) -> str:
        if shop_id not in self.stores:
            raise ConnectorError(f"店铺 {shop_id} 不在任务授权名单中")
        return shop_id

    async def open(self, shop_id: str) -> str:
        """打开店铺窗口并确认已打开，返回窗口引用。"""
        raise NotImplementedError

    async def close(self, window_ref: str) -> None:
        """关闭窗口并确认已关闭。"""
        raise NotImplementedError

    async def inspect(self, window_ref: str) -> bool | None:
        """True=窗口开着，False=已关闭，None=无法确认。"""
        raise NotImplementedError

    async def find_windows(self, shop_id: str) -> list[str]:
        """返回该店铺当前可回收的窗口引用列表。"""
        raise NotImplementedError

    async def debug_port(self, shop_id: str) -> int | None:
        """窗口的页面调试端口；连接方式不提供时返回 None。"""
        return None
