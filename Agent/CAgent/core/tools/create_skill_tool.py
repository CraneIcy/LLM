"""
createSkill 工具：让 LLM 根据用户自然语言要求创建新的 Skill。
"""

import os
import re

from .base import BaseTool
from ..skill_loader import SkillLoader


class CreateSkillTool(BaseTool):
    """创建新 Skill。"""

    name = "createSkill"
    description = """创建新的 Skill。当用户要求创建、新增一个 Skill 时调用此工具。
接收 Skill 名称和需要写入 SKILL.md 的完整内容，在 .agents/skills/ 目录下创建对应子目录并生成符合 Agent Skills 规范的 SKILL.md。
如果还需要创建 references/、scripts/ 等附加目录或辅助文件，请继续使用 fileOps 系列工具完成。"""
    parameters = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Skill 名称，使用小写字母、数字和连字符组成的格式，例如 my-skill",
            },
            "skillContext": {
                "type": "string",
                "description": "需要写入 SKILL.md 的完整内容（不含 YAML Frontmatter，工具会自动生成 Frontmatter）",
            },
        },
        "required": ["name", "skillContext"],
    }

    # Skill 名称合法格式：小写字母、数字、连字符
    _NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

    def __init__(self, skill_loader: SkillLoader):
        self.skill_loader = skill_loader

    def execute(self, name: str, skillContext: str) -> str:
        """
        创建新 Skill。
        :param name: Skill 名称（小写字母、数字、连字符）
        :param skillContext: SKILL.md 正文内容
        """
        name = name.strip().lower()

        # 1. 校验名称格式
        if not self._NAME_PATTERN.match(name):
            return (
                f"错误：Skill 名称 '{name}' 不符合规范。"
                "名称只能使用小写字母、数字和连字符，例如 my-skill、code-review。"
            )

        # 2. 定位 skills 目录
        skills_dir = self.skill_loader.skills_dir
        if not os.path.exists(skills_dir):
            os.makedirs(skills_dir, exist_ok=True)

        # 3. 检查是否已存在同名 Skill，避免覆盖
        skill_dir = os.path.join(skills_dir, name)
        skill_md_path = os.path.join(skill_dir, "SKILL.md")
        if os.path.exists(skill_dir):
            if os.path.exists(skill_md_path):
                return f"错误：Skill '{name}' 已存在（{skill_md_path}）。为避免覆盖原有内容，未进行任何操作。如需修改请使用 writeFile 工具。"
            return f"错误：目录 {skill_dir} 已存在但不包含 SKILL.md 文件。为避免意外覆盖，未进行任何操作。"

        # 4. 创建 Skill 目录
        os.makedirs(skill_dir, exist_ok=True)

        # 5. 从正文中提取 description（用于 YAML Frontmatter）
        description = self._extract_description(skillContext, name)

        # 6. 生成符合规范的 SKILL.md 内容
        content = self._build_skill_md(name, description, skillContext)

        # 7. 写入 SKILL.md
        try:
            with open(skill_md_path, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception as e:
            return f"错误：写入 SKILL.md 失败: {e}"

        return (
            f"Skill '{name}' 创建成功！\n"
            f"目录: {skill_dir}\n"
            f"文件: {skill_md_path}\n\n"
            "如需继续添加 references/、scripts/ 等附加目录或辅助文件，请使用 fileOps 工具（makeDir、createFile 等）完成。"
        )

    def _extract_description(self, skillContext: str, name: str) -> str:
        """
        从正文中提取描述，用于 YAML Frontmatter 的 description 字段。
        优先使用正文第一个标题下的内容或首段，否则用名称兜底。
        """
        text = skillContext.strip()

        # 去掉 Markdown 标题行
        lines = [ln for ln in text.split("\n") if not ln.strip().startswith("#")]

        # 找到第一段非空文字（去除列表、代码等）
        for ln in lines:
            ln = ln.strip()
            if len(ln) >= 10:
                # 截断到合理长度
                return ln[:200]
        return f"Skill {name} 的功能说明。"

    def _build_skill_md(self, name: str, description: str, body: str) -> str:
        """
        组装符合 Agent Skills 规范的 SKILL.md：
        - YAML Frontmatter（name、description 必需字段）
        - 正文内容
        """
        md = "---\n"
        md += f"name: {name}\n"
        md += f"description: {description}\n"
        md += "---\n\n"
        md += body.strip()
        md += "\n"
        return md
