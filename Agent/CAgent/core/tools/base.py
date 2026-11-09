"""
工具基类：所有 Function Call 工具的抽象父类。
每个工具子类需要实现 name、description、parameters 和 execute() 方法。
"""

from abc import ABC, abstractmethod
from typing import Any


class BaseTool(ABC):
    """Function Call 工具抽象基类。"""

    name: str = ""
    description: str = ""
    parameters: dict = {}

    @abstractmethod
    def execute(self, **kwargs) -> str:
        """执行工具逻辑，返回字符串结果。"""
        ...

    def to_schema(self) -> dict:
        """转换为 OpenAI / DeepSeek Function Call 要求的 JSON Schema 格式。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
