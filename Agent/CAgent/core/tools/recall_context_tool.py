"""
recallContext 工具：让 LLM 在需要时检索之前保存的原始上下文归档。

实现方式：Python 本地全文关键词匹配（不使用向量数据库 / Embedding）。
"""

from .base import BaseTool
from ..context_manager import ContextManager


class RecallContextTool(BaseTool):
    """检索历史上下文归档，返回匹配的原始内容片段。"""

    name = "recallContext"
    description = """检索之前压缩时保存的历史上下文归档。
当你发现当前上下文摘要缺少某些历史细节、需要查询早期对话内容时调用此工具。
text 是要查找的关键词或文本内容；id 可选，指定归档编号（格式 YYYYMMDD-HHMMSS），
不提供 id 时会在所有历史归档中检索。返回相关原始片段、归档编号和所在位置。"""
    parameters = {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "需要查找的关键词或文本内容（必需）",
            },
            "id": {
                "type": "string",
                "description": "归档编号（可选），格式如 20261022-153000。不提供时检索全部归档。",
            },
        },
        "required": ["text"],
    }

    def __init__(self, context_manager: ContextManager):
        self.context_manager = context_manager

    def execute(self, text: str, id: str = None, **kwargs) -> str:
        """按关键词检索历史上下文归档。"""
        return self.context_manager.recall(text=text, archive_id=id)
