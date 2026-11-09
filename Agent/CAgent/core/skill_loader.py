"""
Skill 加载器：按照 Agent Skills 规范，动态发现和加载 Skill。
每个 Skill 是一个独立目录，包含 SKILL.md 文件，开头用 YAML Frontmatter 声明元信息。
"""

import os
import re
from typing import Dict, List, Optional
from dataclasses import dataclass


@dataclass
class Skill:
    """一个 Skill 的元信息和内容。"""
    name: str               # Skill 名称（必需）
    description: str        # Skill 描述（必需）
    path: str               # Skill 目录路径
    skill_md_path: str      # SKILL.md 文件路径
    content: str = ""       # SKILL.md 完整内容（按需加载）

    def __repr__(self):
        return f"Skill(name={self.name!r}, path={self.path!r})"


class SkillLoader:
    """Skill 加载器：负责发现、注册和加载 Skill。"""

    # 单个 Skill 正文的长度上限（字符数），超出部分截断，避免占满上下文
    MAX_SKILL_CHARS = 20000

    def __init__(self, project_root: Optional[str] = None):
        """
        初始化 Skill 加载器。
        :param project_root: 项目根目录，默认是当前工作目录
        """
        self.project_root = project_root or os.getcwd()
        self.skills_dir = os.path.join(self.project_root, ".agents", "skills")
        self._skills: Dict[str, Skill] = {}

    def discover_skills(self) -> List[Skill]:
        """
        发现所有可用的 Skill（仅加载元信息，不读取完整内容）。
        :return: Skill 列表
        """
        self._skills.clear()

        if not os.path.exists(self.skills_dir):
            # skills 目录不存在是正常的，返回空列表
            return []

        # 扫描 skills 目录下的所有子目录
        for entry in os.listdir(self.skills_dir):
            skill_dir = os.path.join(self.skills_dir, entry)
            if not os.path.isdir(skill_dir):
                continue

            # 检查是否有 SKILL.md 文件
            skill_md_path = os.path.join(skill_dir, "SKILL.md")
            if not os.path.exists(skill_md_path):
                continue

            # 解析 YAML Frontmatter
            meta = self._parse_frontmatter(skill_md_path)
            if not meta or "name" not in meta or "description" not in meta:
                # 缺少必需字段，跳过
                continue

            # 创建 Skill 对象（只加载元信息，不加载正文）
            skill = Skill(
                name=meta["name"],
                description=meta["description"],
                path=skill_dir,
                skill_md_path=skill_md_path,
            )
            self._skills[skill.name] = skill

        return list(self._skills.values())

    def load_skill_content(self, name: str) -> Optional[Skill]:
        """
        按需加载某个 Skill 的完整内容（读取 SKILL.md 正文）。
        :param name: Skill 名称
        :return: Skill 对象（包含完整内容），如果不存在返回 None
        """
        skill = self._skills.get(name)
        if not skill:
            return None

        if not skill.content:
            with open(skill.skill_md_path, "r", encoding="utf-8") as f:
                full_content = f.read()

            # 去掉 YAML Frontmatter，只保留正文
            body = self._strip_frontmatter(full_content)

            # 长度上限：超过 MAX_SKILL_CHARS 时截断，避免单个 Skill 占满上下文
            if len(body) > self.MAX_SKILL_CHARS:
                body = body[: self.MAX_SKILL_CHARS] + (
                    f"\n\n...（内容过长，已截断，原文共 {len(body)} 字符）"
                )
            skill.content = body

        return skill

    def get_skills_schema(self) -> List[dict]:
        """
        导出所有 Skill 的简要信息，用于传给 LLM（类似工具 Schema）。
        :return: Skill 信息列表
        """
        return [
            {
                "name": skill.name,
                "description": skill.description,
            }
            for skill in self._skills.values()
        ]

    def _parse_frontmatter(self, file_path: str) -> Optional[Dict[str, str]]:
        """
        解析 SKILL.md 文件开头的 YAML Frontmatter。
        Frontmatter 格式：
        ---
        name: skill-name
        description: skill description
        ---
        """
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read(500)  # 只读前 500 字符，足够读 frontmatter
        except Exception:
            return None

        # 匹配 YAML Frontmatter
        pattern = r"^---\s*\n(.*?)\n---\s*\n"
        match = re.match(pattern, content, re.DOTALL)
        if not match:
            return None

        frontmatter_text = match.group(1)
        meta = {}

        # 简单解析 key: value 格式的 YAML
        for line in frontmatter_text.split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" in line:
                key, value = line.split(":", 1)
                key = key.strip()
                value = value.strip().strip("\"'")
                meta[key] = value

        return meta if meta else None

    def _strip_frontmatter(self, content: str) -> str:
        """去掉 SKILL.md 开头的 YAML Frontmatter，只保留正文。"""
        pattern = r"^---\s*\n.*?\n---\s*\n"
        return re.sub(pattern, "", content, count=1, flags=re.DOTALL)

    def list_skills(self) -> List[Skill]:
        """列出所有已发现的 Skill。"""
        return list(self._skills.values())
