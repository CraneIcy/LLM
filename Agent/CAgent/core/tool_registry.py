"""
工具注册表：统一管理所有可用的 Function Call 工具。
提供工具 Schema 导出和工具执行能力，新增工具只需注册即可。
"""

from typing import Dict, List, Optional

from .config import Config
from .tools import BaseTool, GetDateTool, IsLeapYearTool, GetCwdTool, ListDirTool, GetFileTypeTool, ReadFileTool, CreateFileTool, WriteFileTool, MakeDirTool, RemoveDirTool, RemoveFileTool, RenameTool
from .tools.web_search import SearchWebTool
from .tools.web_fetch import FetchWebTool
from .tools.cli_tool import RunCliTool


class ToolRegistry:
    """工具注册表，维护 name -> Tool 实例 的映射。"""

    def __init__(self, config: Optional[Config] = None):
        self._tools: Dict[str, BaseTool] = {}
        self._register_default_tools(config)

    def _register_default_tools(self, config: Optional[Config] = None):
        """注册内置的所有工具。"""
        default_tools = [
            GetDateTool(),
            IsLeapYearTool(),
            GetCwdTool(),
            ListDirTool(),
            GetFileTypeTool(),
            ReadFileTool(),
            CreateFileTool(),
            WriteFileTool(),
            MakeDirTool(),
            RemoveDirTool(),
            RemoveFileTool(),
            RenameTool(),
            RunCliTool(),
            FetchWebTool(),
        ]

        # 注册网络搜索工具（如果配置了 API Key）
        if config and config.search_api_key:
            default_tools.append(
                SearchWebTool(
                    api_key=config.search_api_key,
                    base_url=config.search_base_url,
                )
            )

        for tool in default_tools:
            self.register(tool)

    def register(self, tool: BaseTool):
        """注册一个新工具。"""
        self._tools[tool.name] = tool

    def get_tools_schema(self) -> List[dict]:
        """导出所有工具的 JSON Schema，用于传给 LLM API。"""
        return [tool.to_schema() for tool in self._tools.values()]

    def execute(self, name: str, args: dict) -> str:
        """按名称执行工具，传入参数字典，返回字符串结果。"""
        if name not in self._tools:
            return f"错误：未找到工具 {name}"
        try:
            return self._tools[name].execute(**args)
        except Exception as e:
            return f"工具执行出错: {e}"
