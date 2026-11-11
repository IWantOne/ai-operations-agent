"""外部应用工具：把飞书、领星等接入方暴露成 api.request / mcp.tools / mcp.call。

- API 传输：按接入方配置的认证方式调用；MCP 传输：stdio 启动服务后调工具。
- 配置在「配置 → 工具」，凭据加密保存；超时取 settings/timing.py 的 integration_timeout_seconds。
- 日志由 ToolRegistry 写 tool_call_log，不在这里另写。
"""
import asyncio

from ..connectors.integrations import ApiClient, McpClient


def build_api(manager, provider):
    settings = manager.integration_settings.read(provider)
    timeout = manager.timing_settings.read()["integration_timeout_seconds"]
    return ApiClient(settings, timeout, provider)


def build_mcp(manager, provider):
    settings = manager.integration_settings.read(provider)
    timeout = manager.timing_settings.read()["integration_timeout_seconds"]
    return McpClient(settings["mcp_command"], timeout, provider)


async def probe(manager, provider):
    """配置页“测试连接”用：API 取 token 或打一次根路径，MCP 列一次工具。"""
    public = manager.integration_settings.public(provider)
    if public["transport"] == "mcp":
        async with build_mcp(manager, provider) as client:
            tools = await client.list_tools()
        return {"transport": "mcp", "tools": len(tools),
                "names": [tool.get("name") for tool in tools if isinstance(tool, dict)][:20]}
    client = build_api(manager, provider)
    if client.auth == "token":
        client.token()
        return {"transport": "api", "auth": "token", "token": True}
    result = await asyncio.to_thread(client.request, "GET", "/")
    return {"transport": "api", "auth": client.auth, "status": result["status"]}


def register_integrations(manager):
    async def api_request(provider, method="GET", path="/", query=None, body=None, headers=None):
        client = build_api(manager, provider)
        return await asyncio.to_thread(client.request, method, path, query, body, headers)

    async def mcp_tools(provider):
        async with build_mcp(manager, provider) as client:
            return {"tools": await client.list_tools()}

    async def mcp_call(provider, tool, arguments=None):
        async with build_mcp(manager, provider) as client:
            return {"result": await client.call_tool(tool, arguments)}

    manager.tools.register("api.request", api_request)
    manager.tools.register("mcp.tools", mcp_tools)
    manager.tools.register("mcp.call", mcp_call)
