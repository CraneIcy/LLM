"""
CAgent Core 层
完全与 UI 解耦的业务逻辑层，包含配置、LLM 客户端、工具注册表、Skill 加载器等核心模块。
未来新增 Web / Desktop 等界面时，只需在 ui/ 下新增目录，无需修改 core 层。
"""

from .skill_loader import Skill, SkillLoader

__all__ = ["Skill", "SkillLoader"]
