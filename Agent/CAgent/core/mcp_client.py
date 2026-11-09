"""
MCP Client 模块：让 CAgent 能够连接外部 MCP Server，并通过 Function Calling 调用 MCP 工具。

支持协议：
- stdio：本地 MCP Server 通过标准输入输出通信
- Streamable HTTP：远程 MCP Server 通过 HTTP 通信

配置文件：当前项目目录下的 .mcp.json
格式：
{
  "mcpServers": {
    "server-name": {
      "type": "stdio" | "streamable_http",
      "command": "python",            # stdio 专用：启动命令
      "args": ["server.py"],          # stdio 专用：启动参数
      "url": "https://...",           # streamable_http 专用：Server URL
      "headers": {...}                # 可选：HTTP 请求头（鉴权等）
    }
  }
}

实现说明：
MCP SDK 的 ClientSession 绑定创建它的那个事件循环。为避免每次调用都重建连接，
本模块使用一个常驻的后台线程 + 事件循环，所有连接、发现、调用都提交到该循环，
保证 session 跨多次调用持续有效。
"""

import asyncio
import json
import os
import threading
from typing import Any, Callable, Coroutine, Dict, List, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client


class MCPLoop:
    """常驻事件循环：所有 MCP 异步操作统一提交到该循环执行。"""

    def __init__(self):
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def start(self):
        """启动后台事件循环线程。"""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._loop = asyncio.new_event_loop()
            self._thread = threading.Thread(
                target=self._loop.run_forever,
                name="mcp-event-loop",
                daemon=True,
            )
            self._thread.start()

    def run(self, coro: Coroutine, timeout: float = 120.0):
        """
        在常驻事件循环中执行协程并等待结果。
        :param coro: 要执行的协程
        :param timeout: 超时秒数
        """
        self.start()
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    def stop(self):
        """停止后台事件循环线程。"""
        with self._lock:
            if self._loop is not None:
                try:
                    self._loop.call_soon_threadsafe(self._loop.stop)
                except Exception:
                    pass
            if self._thread is not None:
                try:
                    self._thread.join(timeout=3)
                except Exception:
                    pass
            self._loop = None
            self._thread = None


class MCPServer:
    """管理单个 MCP Server 的连接、工具发现与工具调用。"""

    def __init__(self, name: str, config: Dict[str, Any], loop: MCPLoop):
        """
        :param name: MCP Server 名称（对应 .mcp.json 中的键）
        :param config: MCP Server 配置字典
        :param loop: 常驻事件循环
        """
        self.name = name
        self.config = config
        self._loop = loop
        self._session: Optional[ClientSession] = None
        self._transport = None  # 保存 transport 上下文，防止被 GC

    # ------------------------------------------------------------------
    # 连接管理
    # ------------------------------------------------------------------
    async def connect(self):
        """建立与 MCP Server 的连接并初始化会话。"""
        server_type = self.config.get("type", "streamable_http")

        if server_type == "stdio":
            await self._connect_stdio()
        elif server_type in ("streamable_http", "streamablehttp", "http"):
            await self._connect_streamable_http()
        else:
            raise ValueError(
                f"不支持的 MCP Server 类型 '{server_type}'，"
                "支持的类型：stdio、streamable_http"
            )

        # 初始化会话（必须）
        await self._session.initialize()

    async def _connect_stdio(self):
        """通过 stdio 协议连接本地 MCP Server。"""
        command = self.config.get("command")
        if not command:
            raise ValueError(f"MCP Server '{self.name}' 的 stdio 配置缺少 'command' 字段")

        args = self.config.get("args", [])
        env = self.config.get("env")

        params = StdioServerParameters(command=command, args=args, env=env)
        self._transport = stdio_client(params)
        read_stream, write_stream = await self._transport.__aenter__()
        self._session = ClientSession(read_stream, write_stream)
        await self._session.__aenter__()

    async def _connect_streamable_http(self):
        """通过 Streamable HTTP 协议连接远程 MCP Server。"""
        url = self.config.get("url")
        if not url:
            raise ValueError(
                f"MCP Server '{self.name}' 的 streamable_http 配置缺少 'url' 字段"
            )

        headers = self.config.get("headers")
        # Streamable HTTP 支持通过 http_client 传入自定义请求头（如鉴权）
        http_client = None
        if headers:
            try:
                import httpx2 as httpx
            except ImportError:
                try:
                    import httpx as httpx
                except ImportError:
                    httpx = None
            if httpx is not None:
                http_client = httpx.AsyncClient(headers=headers)

        if http_client is not None:
            self._transport = streamable_http_client(url=url, http_client=http_client)
        else:
            self._transport = streamable_http_client(url=url)
        # mcp 2.x 的 streamable_http_client 返回 (read_stream, write_stream) 二元组
        streams = await self._transport.__aenter__()
        read_stream, write_stream = streams[0], streams[1]
        self._session = ClientSession(read_stream, write_stream)
        await self._session.__aenter__()

    async def close(self):
        """关闭与 MCP Server 的连接。"""
        # 先退出 session，再退出 transport，避免异步生成器未关闭
        if self._session:
            try:
                await self._session.__aexit__(None, None, None)
            except Exception:
                pass
            self._session = None
        if self._transport:
            try:
                await self._transport.__aexit__(None, None, None)
            except Exception:
                pass
            self._transport = None

    # ------------------------------------------------------------------
    # 工具发现
    # ------------------------------------------------------------------
    async def list_tools(self) -> List[Dict[str, Any]]:
        """获取 MCP Server 提供的所有工具（名称、描述、参数 Schema）。"""
        if not self._session:
            await self.connect()

        tools_result = await self._session.list_tools()
        tools = []
        for tool in tools_result.tools:
            tools.append(
                {
                    "name": tool.name,
                    "description": tool.description or "",
                    "inputSchema": tool.input_schema or {"type": "object", "properties": {}},
                }
            )
        return tools

    # ------------------------------------------------------------------
    # 工具调用
    # ------------------------------------------------------------------
    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        调用 MCP Server 上的工具。
        :param tool_name: MCP Server 上的原始工具名称
        :param arguments: 工具参数
        :return: 统一的返回结构 {content, structured, isError, error}
        """
        if not self._session:
            await self.connect()

        try:
            result = await self._session.call_tool(tool_name, arguments=arguments)
        except Exception as e:
            return {
                "content": "",
                "structured": None,
                "isError": True,
                "error": f"调用工具 '{tool_name}' 失败: {e}",
            }

        # 解析返回内容
        texts = []
        is_error = bool(getattr(result, "isError", False))

        for item in result.content:
            item_type = getattr(item, "type", "")
            if item_type == "text":
                texts.append(item.text)
            elif item_type in ("image", "resource"):
                # 图片或资源内容，转为可读描述
                texts.append(f"[{item_type} 内容，大小 {len(getattr(item, 'data', b''))} 字节]")
            else:
                texts.append(str(item))

        content = "\n".join(texts)

        # 尝试解析结构化数据（如果是 JSON 格式的文本）
        structured_data = None
        if content:
            try:
                structured_data = json.loads(content)
            except json.JSONDecodeError:
                structured_data = None

        return {
            "content": content,
            "structured": structured_data,
            "isError": is_error,
            "error": result.error if is_error else None,
        }


class MCPClient:
    """MCP 客户端管理器：读取配置、连接所有 Server、维护 Server 与工具名映射。"""

    def __init__(self, project_root: Optional[str] = None):
        """
        :param project_root: 项目根目录（用于查找 .mcp.json），默认取当前工作目录
        """
        self.project_root = project_root or os.getcwd()
        self._loop = MCPLoop()
        self.servers: Dict[str, MCPServer] = {}
        # 工具映射：对外暴露名 -> (server 名称, 原始工具名)
        self.tool_mapping: Dict[str, tuple] = {}
        # 服务器 -> 工具列表 缓存（供 TUI 边栏展示使用）
        self.server_tools: Dict[str, List[Dict[str, Any]]] = {}

    def load_config(self) -> Dict[str, Any]:
        """读取项目目录下的 .mcp.json 配置文件。"""
        config_path = os.path.join(self.project_root, ".mcp.json")
        if not os.path.exists(config_path):
            return {}
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("mcpServers", {})
        except Exception as e:
            print(f"[MCP] 读取配置文件 {config_path} 失败: {e}")
            return {}

    def get_mapping_info(self) -> List[Dict[str, str]]:
        """返回工具映射信息（用于调试和展示）。"""
        result = []
        for exposed_name, (server_name, orig_name) in self.tool_mapping.items():
            result.append(
                {
                    "exposed": exposed_name,
                    "server": server_name,
                    "original": orig_name,
                }
            )
        return result

    # ------------------------------------------------------------------
    # 异步核心逻辑（提交到常驻事件循环执行）
    # ------------------------------------------------------------------
    async def _discover_and_register(self) -> Dict[str, List[Dict[str, Any]]]:
        """连接所有 Server 并发现工具。返回 server -> tools 的映射。"""
        config = self.load_config()
        server_tools: Dict[str, List[Dict[str, Any]]] = {}

        if not config:
            print("[MCP] 未找到 .mcp.json 配置文件，跳过 MCP 初始化")
            return server_tools

        for server_name, server_config in config.items():
            server = MCPServer(name=server_name, config=server_config, loop=self._loop)
            try:
                await server.connect()
                tools = await server.list_tools()
                self.servers[server_name] = server
                server_tools[server_name] = tools
                print(f"[MCP] Server '{server_name}' 连接成功，发现 {len(tools)} 个工具")
            except Exception as e:
                # 单个 Server 连接失败不影响其他 Server
                print(f"[MCP] Server '{server_name}' 连接失败: {e}")
                server_tools[server_name] = []
                try:
                    await server.close()
                except Exception:
                    pass

        # 建立工具映射（增加 Server 名称前缀避免冲突）
        self._build_tool_mapping(server_tools)
        # 缓存服务器 -> 工具列表（供 TUI 边栏等界面展示）
        self.server_tools = server_tools
        return server_tools

    def get_server_summary(self) -> List[Dict[str, Any]]:
        """
        返回每个 MCP Server 的摘要信息（供 TUI 边栏展示）。

        返回示例：
        [
            {
                "name": "Bazi-MCP",
                "status": "connected" | "failed",
                "tool_count": 3,
                "tools": ["getBaziDetail", "getSolarTimes", ...],
            },
            ...
        ]
        """
        result = []
        for server_name, tools in self.server_tools.items():
            # 连接成功时 server 实例会被记录到 self.servers；失败则不会
            status = "connected" if server_name in self.servers else "failed"
            result.append({
                "name": server_name,
                "status": status,
                "tool_count": len(tools),
                "tools": [t.get("name", "") for t in tools],
            })
        return result

    def _build_tool_mapping(self, server_tools: Dict[str, List[Dict[str, Any]]]):
        """建立 对外暴露名 -> (Server 名, 原始工具名) 的映射。

        为避免不同 MCP Server 之间出现工具名称冲突，
        统一使用 'serverName__toolName' 作为对 LLM 暴露的工具名称。
        """
        self.tool_mapping.clear()
        for server_name, tools in server_tools.items():
            for tool in tools:
                exposed_name = f"{server_name}__{tool['name']}"
                self.tool_mapping[exposed_name] = (server_name, tool["name"])

    def discover_and_register(self) -> Dict[str, List[Dict[str, Any]]]:
        """同步入口：连接 Server 并发现工具（供 main.py 调用）。"""
        return self._loop.run(self._discover_and_register())

    async def _close_all(self):
        """关闭所有已连接的 Server。"""
        for server in self.servers.values():
            try:
                await server.close()
            except Exception:
                pass
        self.servers.clear()
        self.tool_mapping.clear()

    def close_all(self):
        """同步入口：关闭所有 MCP Server 连接。"""
        try:
            self._loop.run(self._close_all())
        except Exception:
            pass
        finally:
            self._loop.stop()

    # ------------------------------------------------------------------
    # 工具调用（同步入口）
    # ------------------------------------------------------------------
    def call_mcp_tool(self, exposed_name: str, arguments: Dict[str, Any]) -> str:
        """
        根据暴露的工具名称找到对应的 Server 并调用。
        :param exposed_name: 对 LLM 暴露的工具名称（带 Server 前缀）
        :param arguments: 工具参数
        :return: 字符串结果（供 Function Calling 返回给 LLM）
        """
        if exposed_name not in self.tool_mapping:
            return f"错误：MCP 工具 '{exposed_name}' 未注册"

        server_name, orig_name = self.tool_mapping[exposed_name]
        server = self.servers.get(server_name)
        if not server:
            return f"错误：MCP Server '{server_name}' 未连接"

        try:
            result = self._loop.run(server.call_tool(orig_name, arguments))
        except Exception as e:
            return f"错误：调用 MCP 工具 '{exposed_name}' 时发生异常: {e}"

        if result["isError"]:
            return f"MCP 工具 '{exposed_name}' 返回错误: {result['error'] or result['content']}"

        if result["structured"] is not None:
            # 结构化数据（JSON）格式化为可读文本
            try:
                return json.dumps(result["structured"], ensure_ascii=False, indent=2)
            except Exception:
                return result["content"]
        return result["content"]
