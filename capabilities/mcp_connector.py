"""MCP 连接器 —— 把外部 MCP server 的工具,包成本系统统一的 Capability。

为什么这么做:与其为每个外部服务(GitHub、Notion、数据库、文件系统…)手写一套
集成,不如接 MCP(Model Context Protocol)这个开放标准——写一个适配器,任何 MCP
server 暴露的工具都自动变成一个 `Capability`,注册进同一个 registry,**走同一条
治理管线**(硬/软边界、按角色白名单、确认、计费、trace)。安全模型不分裂。

映射约定:
- 名称:`mcp.<server>.<tool>`,带 server 前缀避免重名、便于白名单按前缀授权。
- 风险:以工具自报的 annotations 为准;未声明则 fail-safe 当 DESTRUCTIVE(宁可多问)。
    readOnlyHint=true        -> READ
    destructiveHint=false    -> WRITE
    其余 / 未知                -> DESTRUCTIVE
- 入参 schema:直接透传工具的 inputSchema,供模型做 function calling。

客户端可注入(MCPClient 协议),便于离线测试;真实连接用 connect_stdio_server()。
"""
from __future__ import annotations

import json
import os
from typing import Any, Optional, Protocol, runtime_checkable

from core.types import CapabilityResult, Risk


@runtime_checkable
class MCPClient(Protocol):
    """与单个 MCP server 通信的最小接口。"""

    async def list_tools(self) -> list: ...
    async def call_tool(self, name: str, arguments: dict) -> Any: ...


# ── 字段归一(兼容 SDK 对象 / 纯 dict)──────────────────────────────────────────

def _field(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _risk_from_annotations(ann: Any) -> Risk:
    """按 MCP 工具注解推断风险;未知一律 fail-safe 为高危。"""
    if ann is None:
        return Risk.DESTRUCTIVE
    read_only = _field(ann, "readOnlyHint", None)
    if read_only is True:
        return Risk.READ
    destructive = _field(ann, "destructiveHint", None)
    if destructive is False:
        return Risk.WRITE
    return Risk.DESTRUCTIVE


def _extract_text(result: Any) -> tuple[bool, str]:
    """把 MCP call_tool 的返回归一为 (ok, 文本)。

    标准返回含 content(内容块列表,每块可能是 {type:'text', text:...})与 isError。
    """
    is_error = bool(_field(result, "isError", False))
    content = _field(result, "content", None)
    parts: list[str] = []
    if isinstance(content, list):
        for block in content:
            text = _field(block, "text", None)
            if text is not None:
                parts.append(str(text))
            else:
                parts.append(json.dumps(block, ensure_ascii=False, default=str))
    elif content is not None:
        parts.append(str(content))
    elif isinstance(result, str):
        parts.append(result)
    return (not is_error), "\n".join(parts)


# ── 单个 MCP 工具 -> Capability ─────────────────────────────────────────────────

class MCPCapability:
    def __init__(self, server_name: str, tool: Any, client: MCPClient) -> None:
        self._server = server_name
        self._tool_name = str(_field(tool, "name", "") or "")
        self.name = f"mcp.{server_name}.{self._tool_name}"
        self.description = str(_field(tool, "description", "") or f"MCP 工具 {self.name}")
        self.schema = _field(tool, "inputSchema", None) or {"type": "object", "properties": {}}
        self.risk = _risk_from_annotations(_field(tool, "annotations", None))
        self._client = client

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        try:
            raw = await self._client.call_tool(self._tool_name, args or {})
        except Exception as e:
            return CapabilityResult(ok=False, error=f"MCP 调用失败({type(e).__name__}): {e}")
        ok, text = _extract_text(raw)
        return CapabilityResult(ok=ok, output=text if ok else "",
                                error=None if ok else (text or "MCP 工具返回错误"))


# ── 连接器:发现 + 注册 ─────────────────────────────────────────────────────────

class MCPConnector:
    def __init__(self, server_name: str, client: MCPClient) -> None:
        self.server_name = server_name
        self.client = client
        self.capabilities: list[MCPCapability] = []

    async def discover(self) -> list[MCPCapability]:
        tools = await self.client.list_tools() or []
        # 某些 SDK 返回 {"tools": [...]} 或带 .tools 属性
        if isinstance(tools, dict):
            tools = tools.get("tools", [])
        elif not isinstance(tools, list):
            tools = _field(tools, "tools", []) or []
        self.capabilities = [
            MCPCapability(self.server_name, t, self.client)
            for t in tools if _field(t, "name", "")
        ]
        return self.capabilities

    async def register_into(self, registry) -> list[str]:
        """发现并注册到 registry,返回成功注册的能力名。重名跳过(不覆盖)。"""
        caps = await self.discover()
        registered: list[str] = []
        for cap in caps:
            try:
                registry.register(cap)
                registered.append(cap.name)
            except ValueError:
                continue  # 重名跳过
        return registered


# ── 配置 ─────────────────────────────────────────────────────────────────────

def load_mcp_servers(path: str = "mcp_servers.json") -> list[dict]:
    """读取 MCP server 配置。格式:

        {"servers": [
            {"name": "fs", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/data"]},
            {"name": "github", "url": "http://127.0.0.1:3001/mcp"}
        ]}
    """
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
    except Exception:
        return []
    servers = data.get("servers") if isinstance(data, dict) else data
    return [s for s in (servers or []) if isinstance(s, dict) and s.get("name")]


async def connect_stdio_server(command: str, args: Optional[list[str]] = None,
                               env: Optional[dict] = None) -> "MCPClient":
    """用 mcp SDK 通过 stdio 启动并连接一个 MCP server,返回持久客户端。

    需要安装 mcp SDK(`pip install mcp`)。返回的客户端持有打开的会话,
    用完应调用 aclose()。
    """
    try:
        from mcp import ClientSession, StdioServerParameters  # type: ignore
        from mcp.client.stdio import stdio_client  # type: ignore
    except Exception as e:  # pragma: no cover - 取决于是否装了 mcp
        raise RuntimeError(
            "未安装 MCP SDK。请 `pip install mcp` 后再连接 stdio MCP server。") from e

    params = StdioServerParameters(command=command, args=args or [], env=env)
    return await _PersistentStdioClient.open(stdio_client, ClientSession, params)


class _PersistentStdioClient:  # pragma: no cover - 需真实 mcp server 才能跑
    """持有打开的 stdio 会话,实现 MCPClient 协议。"""

    def __init__(self, session, _ctxs: list) -> None:
        self._session = session
        self._ctxs = _ctxs  # 保存 async context,aclose 时逆序退出

    @classmethod
    async def open(cls, stdio_client, ClientSession, params) -> "_PersistentStdioClient":
        transport_cm = stdio_client(params)
        read, write = await transport_cm.__aenter__()
        session_cm = ClientSession(read, write)
        session = await session_cm.__aenter__()
        await session.initialize()
        return cls(session, [session_cm, transport_cm])

    async def list_tools(self) -> list:
        resp = await self._session.list_tools()
        return _field(resp, "tools", resp)

    async def call_tool(self, name: str, arguments: dict) -> Any:
        return await self._session.call_tool(name, arguments)

    async def aclose(self) -> None:
        for cm in self._ctxs:
            try:
                await cm.__aexit__(None, None, None)
            except Exception:
                pass


async def register_mcp_servers(registry, config_path: str = "mcp_servers.json") -> dict:
    """便捷入口:按配置连接所有 stdio MCP server 并把工具注册进 registry。

    返回 {server_name: [已注册能力名, ...]}。单个 server 失败不影响其余(fail-soft)。
    HTTP 型 server(只配 url)此处跳过,留待 HTTP 客户端实现。
    """
    out: dict[str, list[str]] = {}
    for spec in load_mcp_servers(config_path):
        name = spec["name"]
        if not spec.get("command"):
            continue  # 暂只支持 stdio 型
        try:
            client = await connect_stdio_server(
                spec["command"], spec.get("args"), spec.get("env"))
            connector = MCPConnector(name, client)
            out[name] = await connector.register_into(registry)
        except Exception:
            out[name] = []
    return out
