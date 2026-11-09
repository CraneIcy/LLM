"""
UI 抽象基类：定义所有界面版本需要实现的统一接口。
未来开发 Web UI / Desktop UI 时，只需继承 BaseUI 并实现 run() 方法，
core 层代码完全不需要修改。
"""

from abc import ABC, abstractmethod

from core.llm_client import LLMClient


class BaseUI(ABC):
    """所有用户界面的抽象基类。"""

    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client

    @abstractmethod
    def run(self):
        """启动界面，进入主交互循环。"""
        ...
