"""智易飞工具：把 Amazon 原生 API 暴露成工具。

- ``amazon.stores``：列出当前应用可访问的店铺（只读，可安全重跑）。
- ``amazon.request``：按 Amazon 官方文档传 api_type / method / path / query / body。
- 配置在「配置 → 工具」，凭据加密保存；超时取 settings/timing.py 的 erp_timeout_seconds。
- 日志由 ToolRegistry 写 tool_call_log，不在这里另写。
"""
import asyncio

from ..connectors.effiseller import EffisellerClient


def build_client(manager):
    settings = manager.erp_settings.read()
    timeout = manager.timing_settings.read()["erp_timeout_seconds"]
    return EffisellerClient(settings["base_url"], settings["app_id"], settings["app_secret"], timeout)


async def probe(manager):
    """配置页“测试连接”用：只读店铺列表，返回可访问店铺数量与类型。"""
    result = await asyncio.to_thread(build_client(manager).stores)
    body = result.get("body")
    stores = body.get("stores") if isinstance(body, dict) else None
    return {"status": result.get("status"),
            "stores": len(stores) if isinstance(stores, list) else None,
            "api_types": body.get("api_types") if isinstance(body, dict) else None}


def register_erp(manager):
    async def stores():
        return await asyncio.to_thread(build_client(manager).stores)

    async def request(**fields):
        return await asyncio.to_thread(build_client(manager).request, **fields)

    manager.tools.register("amazon.stores", stores, restart_safe=True)
    manager.tools.register("amazon.request", request)
