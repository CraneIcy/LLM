"""
loadSkill 工具：让 LLM 可以按需加载 Skill 的完整内容和附加文件。
"""

import os
from .base import BaseTool
from ..skill_loader import SkillLoader


class LoadSkillTool(BaseTool):
    """加载指定 Skill 的完整指令或附加文件。"""

    name = "loadSkill"
    description = """加载指定 Skill 的完整指令或附加文件。
当你需要使用某个 Skill 时调用此工具。
如果只提供 name，返回该 Skill 的 SKILL.md 完整内容。
如果同时提供 filename，读取该 Skill 目录下的指定附加文件。"""
    parameters = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "要加载的 Skill 名称（必需）",
            },
            "filename": {
                "type": "string",
                "description": "要加载的附加文件名或路径（可选）。支持相对路径、绝对路径。如果只提供文件名，会在 Skill 目录下递归搜索。",
            },
        },
        "required": ["name"],
    }

    def __init__(self, skill_loader: SkillLoader):
        self.skill_loader = skill_loader

    def execute(self, name: str, filename: str = None) -> str:
        """
        加载指定 Skill 的内容或附加文件。
        :param name: Skill 名称（必需）
        :param filename: 附加文件名或路径（可选）
        """
        skill = self.skill_loader.load_skill_content(name)
        if not skill:
            return f"错误：未找到 Skill '{name}'。可用的 Skill 请查看系统提示中的列表。"

        # 如果没有 filename，返回 SKILL.md 全文
        if not filename:
            return f"# Skill: {skill.name}\n\n{skill.content}"

        # 有 filename，尝试加载附加文件
        return self._load_skill_file(skill, filename)

    def _load_skill_file(self, skill, filename: str) -> str:
        """
        加载 Skill 目录下的指定文件。
        支持相对路径、绝对路径、纯文件名递归搜索。
        所有文件读取都限制在 Skill 目录内部，防止路径遍历攻击。
        """
        skill_dir = skill.path

        # 安全检查：确保路径在 Skill 目录内部
        def is_safe_path(path: str) -> bool:
            abs_path = os.path.abspath(path)
            abs_skill_dir = os.path.abspath(skill_dir)
            return abs_path.startswith(abs_skill_dir + os.sep) or abs_path == abs_skill_dir

        # 尝试 1：相对于 Skill 目录的路径
        candidate1 = os.path.join(skill_dir, filename)
        if os.path.exists(candidate1) and os.path.isfile(candidate1) and is_safe_path(candidate1):
            return self._read_file(candidate1, skill_dir)

        # 尝试 2：相对于项目根目录的路径
        candidate2 = os.path.join(self.skill_loader.project_root, filename)
        if os.path.exists(candidate2) and os.path.isfile(candidate2) and is_safe_path(candidate2):
            return self._read_file(candidate2, skill_dir)

        # 尝试 3：绝对路径
        if os.path.isabs(filename) and os.path.exists(filename) and os.path.isfile(filename) and is_safe_path(filename):
            return self._read_file(filename, skill_dir)

        # 尝试 4：只提供文件名，在 Skill 目录下递归搜索
        if not os.path.dirname(filename):
            matches = []
            for root, dirs, files in os.walk(skill_dir):
                if filename in files:
                    full_path = os.path.join(root, filename)
                    if is_safe_path(full_path):
                        matches.append(full_path)

            if len(matches) == 1:
                return self._read_file(matches[0], skill_dir)
            elif len(matches) > 1:
                # 多个匹配，返回候选路径让 LLM 选择
                candidates = "\n".join([f"  - {os.path.relpath(m, skill_dir)}" for m in matches])
                return f"找到多个名为 '{filename}' 的文件，请指定完整路径：\n{candidates}"

        # 没找到文件
        return f"错误：在 Skill '{skill.name}' 目录下未找到文件 '{filename}'。"

    def _read_file(self, file_path: str, skill_dir: str) -> str:
        """读取文件内容，返回格式化的结果。"""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            rel_path = os.path.relpath(file_path, skill_dir)
            return f"# File: {rel_path}\n\n{content}"
        except Exception as e:
            return f"错误：读取文件失败: {e}"
