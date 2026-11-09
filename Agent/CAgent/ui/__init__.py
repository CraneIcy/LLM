"""
UI 层：所有用户界面的抽象与实现。
当前提供 TUI（终端界面），未来可扩展 Web / Desktop / Mobile 等。
"""

from .base import BaseUI

__all__ = ["BaseUI"]
