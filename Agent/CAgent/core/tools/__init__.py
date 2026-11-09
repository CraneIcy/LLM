"""
工具模块：所有 Function Call 工具的集合。
新增工具时只需在对应文件中实现 BaseTool 子类，并在 ToolRegistry 中注册。
"""

from .base import BaseTool
from .datetime_tools import GetDateTool, IsLeapYearTool
from .file_tools import (
    GetCwdTool,
    ListDirTool,
    GetFileTypeTool,
    ReadFileTool,
    CreateFileTool,
    WriteFileTool,
    MakeDirTool,
    RemoveDirTool,
    RemoveFileTool,
    RenameTool,
)
from .load_skill_tool import LoadSkillTool
from .create_skill_tool import CreateSkillTool
from .mcp_tool import MCPToolAdapter
from .recall_context_tool import RecallContextTool
from .web_search import SearchWebTool
from .web_fetch import FetchWebTool
from .cli_tool import RunCliTool

__all__ = [
    "BaseTool",
    "GetDateTool",
    "IsLeapYearTool",
    "GetCwdTool",
    "ListDirTool",
    "GetFileTypeTool",
    "ReadFileTool",
    "CreateFileTool",
    "WriteFileTool",
    "MakeDirTool",
    "RemoveDirTool",
    "RemoveFileTool",
    "RenameTool",
    "LoadSkillTool",
    "CreateSkillTool",
    "MCPToolAdapter",
    "RecallContextTool",
    "SearchWebTool",
    "FetchWebTool",
    "RunCliTool",
]
