"""
MCP 工具适配器：将 MCP Server 上的远程工具包装为 CAgent 的本地 Function Calling 工具。

MCP 工具与本地工具（RunCli、searchWeb、loadSkill 等）统一参与 Agent 的工具调用流程。
为避免不同 MCP Server 之间出现工具名称冲突，对 LLM 暴露的名称带 Server 名称前缀：
    exposed_name = "{server_name}__{tool_name}"
"""

import json
from typing import Any, Dict

from .base import BaseTool


class MCPToolAdapter(BaseTool):
    """将一个 MCP 远程工具包装为本地 BaseTool。"""

    def __init__(
        self,
        mcp_client,
        exposed_name: str,
        server_name: str,
        original_name: str,
        description: str,
        input_schema: Dict[str, Any],
    ):
        """
        :param mcp_client: MCPClient 实例（用于调用）
        :param exposed_name: 对 LLM 暴露的工具名称（带 Server 前缀）
        :param server_name: 所属 MCP Server 名称
        :param original_name: MCP Server 上的原始工具名称
        :param description: 工具描述
        :param input_schema: 工具参数 JSON Schema
        """
        self.mcp_client = mcp_client
        self.server_name = server_name
        self.original_name = original_name

        self.name = exposed_name
        self.description = (
            f"[MCP Server: {server_name}] {description} "
            f"(远程工具 '{original_name}'，来自 MCP Server '{server_name}')"
        )
        # 参数 Schema：MCP 返回的 inputSchema 可能没有 required，补全默认值
        self.parameters = self._normalize_schema(input_schema)

    def _normalize_schema(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        """规范 MCP 工具的参数 Schema，确保与 Function Calling 格式兼容。"""
        if not schema or not isinstance(schema, dict):
            return {"type": "object", "properties": {}}

        normalized = {
            "type": schema.get("type", "object"),
            "properties": schema.get("properties", {}),
        }
        if "required" in schema:
            normalized["required"] = schema["required"]
        return normalized

    def execute(self, **kwargs) -> str:
        """调用 MCP 工具，返回字符串结果给 LLM。"""
        return self.mcp_client.call_mcp_tool(self.name, kwargs)

    def to_schema(self) -> dict:
        """转换为 Function Calling 要求的 JSON Schema 格式。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
