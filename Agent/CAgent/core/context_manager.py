"""
上下文管理器：负责 Token 估算、原始上下文归档、上下文压缩与历史检索。

设计目标（教学要求）：
- 不使用向量数据库 / Embedding，保持实现简单、可理解
- 归档目录：<项目根>/.agents/context/
- 归档文件：YYYYMMDD-HHMMSS.jsonl（每条消息一行 JSON）
- 检索方式：Python 本地全文关键词匹配
"""

import json
import os
import re
from datetime import datetime
from typing import Dict, List, Optional

# 默认上下文窗口大小（无法从模型 API 获取时使用），单位 Token
DEFAULT_CONTEXT_WINDOW = 128 * 1024

# 上下文使用量达到窗口的该比例时，向用户显示压缩警告（可被配置覆盖）
WARN_RATIO = 0.8

# 上下文压缩专用 Prompt（教学文档给定的口径）
COMPRESS_PROMPT = """你是一名 AI Agent 的上下文管理助手。当前会话即将达到上下文窗口限制，需要将历史对话压缩为一份高质量的工作摘要，以便 Agent 在新的上下文中继续执行任务。

请认真阅读提供的历史上下文，提取对后续工作仍然有价值的信息，并生成一份约 5,000 Tokens 的 Markdown 摘要。

摘要应重点保留以下内容：

1. **用户目标与要求**：用户希望完成什么任务？有哪些必须遵守的约束、偏好和验收条件？
2. **已经完成的工作**：哪些任务已经完成？实现了哪些功能？获得了哪些已经验证的结果？
3. **当前工作状态**：Agent 正在处理什么任务？当前进展到哪一步？是否存在尚未解决的问题？
4. **关键技术信息**：保留重要的文件路径、函数名称、接口定义、配置项、执行命令、错误信息和必要的代码片段。
5. **关键决策与原因**：记录用户和 Agent 已经确定的技术方案，以及重要的设计取舍。
6. **下一步任务**：明确接下来应该执行的操作，以及需要继续验证的事项。

请遵守以下要求：

- 优先保留对后续任务有直接影响的信息，删除寒暄、重复讨论、过时的尝试和无关内容。
- 对已经验证的事实与尚未验证的推测作出明确区分。
- 不要将计划完成的任务描述为已经完成。
- 重要的文件路径、函数名称、配置名称和命令应保留准确原文。
- 对失败的尝试，只保留有助于避免重复错误的信息。
- 如果信息存在冲突，应优先保留用户最新确认的要求，并简要说明仍然存在的冲突。
- 如果某些历史细节无法在摘要中完整保留，可简要说明它们已保存到原始上下文归档中，后续可以通过 recallContext 工具重新检索。
- 使用清晰的 Markdown 结构输出摘要，不要附加解释或无关内容。

最终目标：使一个从未阅读过原始对话的 Agent，仅凭这份摘要，就能够理解当前任务、继承关键决策，并继续开展工作。"""


def estimate_tokens(text: str) -> int:
    """
    估算文本的 Token 数量（不依赖模型 API 时的兜底方案）。

    简单估算规则（教学用，不做分词）：
    - 英文按 4 个字符 ≈ 1 Token
    - 中文按 1 个字符 ≈ 1 Token（中文单字信息密度高）
    实际按"字符数 / 2"取整，兼顾中英文混合场景。
    """
    if not text:
        return 0
    return max(1, len(text) // 2)


class ContextManager:
    """上下文管理：估算用量、归档原始上下文、生成归档编号、全文检索。"""

    def __init__(self, project_root: str, warn_ratio: float = WARN_RATIO,
                 default_window: int = DEFAULT_CONTEXT_WINDOW):
        self.project_root = project_root
        self.context_dir = os.path.join(project_root, ".agents", "context")
        # 上下文窗口大小：0 表示未知（显示时用默认窗口并标注「默认」）
        self.context_window: int = 0
        # 占用比例达到该值时警告（可从 config.ini [agent] warn_ratio 配置）
        self.warn_ratio: float = warn_ratio
        # 窗口未知时用于显示的默认窗口大小（可从 config.ini [ui] default_context_window 配置）
        self.default_window: int = default_window
        # 最近一次从模型 API 拿到的真实 usage（None 表示未获取到）
        self.last_usage: Optional[Dict] = None

    # ------------------------------------------------------------------
    # 目录与编号
    # ------------------------------------------------------------------
    def _ensure_context_dir(self):
        """确保归档目录存在。"""
        os.makedirs(self.context_dir, exist_ok=True)

    def _generate_archive_id(self) -> str:
        """生成唯一归档编号，格式：YYYYMMDD-HHMMSS。"""
        return datetime.now().strftime("%Y%m%d-%H%M%S")

    # ------------------------------------------------------------------
    # Token 用量计算
    # ------------------------------------------------------------------
    def messages_to_text(self, messages: List[Dict]) -> str:
        """把消息列表序列化为文本，用于 Token 估算。"""
        parts = []
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if isinstance(content, list):
                # 多模态 content 数组，只取文本部分
                texts = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        texts.append(item.get("text", ""))
                content = " ".join(texts)
            parts.append(f"{role}: {content}")
            # 工具调用消息附带参数
            if msg.get("tool_calls"):
                parts.append(json.dumps(msg["tool_calls"], ensure_ascii=False))
        return "\n".join(parts)

    def estimate_messages_tokens(self, messages: List[Dict], tools_schema: List[Dict]) -> int:
        """
        估算一组消息 + 工具定义的 Token 用量。

        优先使用模型 API 提供的 usage（由 LLMClient 写入 last_usage），
        否则用本地估算兜底。
        """
        if self.last_usage:
            # 优先用 prompt_tokens（上下文窗口占用 = 输入侧），兜底用 total_tokens
            if self.last_usage.get("prompt_tokens"):
                return int(self.last_usage["prompt_tokens"])
            if self.last_usage.get("total_tokens"):
                return int(self.last_usage["total_tokens"])
        # 兜底估算：消息正文 + 工具 Schema
        text = self.messages_to_text(messages)
        schema_text = json.dumps(tools_schema, ensure_ascii=False)
        return estimate_tokens(text) + estimate_tokens(schema_text)

    def get_context_usage(self, messages: List[Dict], tools_schema: List[Dict]) -> Dict:
        """
        计算当前上下文使用情况。

        返回：
        {
            "usage_tokens": 当前已用 Token 数,
            "window_tokens": 上下文窗口大小（0 = 未知）,
            "ratio": 已占用比例（0~1）,
            "state": "ok" | "warn" | "blocked",
        }
        """
        usage_tokens = self.estimate_messages_tokens(messages, tools_schema)
        window = self.context_window or self.default_window
        ratio = usage_tokens / window if window > 0 else 0.0

        if ratio >= self.warn_ratio:
            state = "blocked" if ratio >= 1.0 else "warn"
        else:
            state = "ok"

        return {
            "usage_tokens": usage_tokens,
            "window_tokens": self.context_window,  # 0 = 未知（用默认）
            "display_window": window,              # 实际用于计算的窗口
            "ratio": ratio,
            "state": state,
        }

    # ------------------------------------------------------------------
    # 归档：保存完整原始上下文
    # ------------------------------------------------------------------
    def save_archive(self, messages: List[Dict]) -> Optional[str]:
        """
        把当前会话消息完整保存为归档文件。

        :param messages: 要归档的消息列表（原始顺序）
        :return: 归档编号（成功）；None（失败）
        """
        try:
            self._ensure_context_dir()
            archive_id = self._generate_archive_id()
            file_path = os.path.join(self.context_dir, f"{archive_id}.jsonl")

            with open(file_path, "w", encoding="utf-8") as f:
                for msg in messages:
                    # 每条消息保留 role / content / tool_calls / tool_call_id 等原始字段
                    line = json.dumps(msg, ensure_ascii=False)
                    f.write(line + "\n")

            return archive_id
        except Exception as e:
            print(f"[Context] 归档保存失败: {e}")
            return None

    # ------------------------------------------------------------------
    # 检索：recallContext 工具的底层实现
    # ------------------------------------------------------------------
    def recall(self, text: str, archive_id: Optional[str] = None,
               max_results: int = 5, max_chars_per_result: int = 800) -> str:
        """
        在归档文件中做本地全文关键词检索。

        :param text: 需要查找的关键词或文本内容
        :param archive_id: 指定归档编号（YYYYMMDD-HHMMSS）；None 则搜索全部归档
        :param max_results: 最多返回的匹配片段数
        :param max_chars_per_result: 每个片段的字符上限（防止结果占满上下文）
        :return: 检索结果文本
        """
        if not text or not text.strip():
            return "错误：检索关键词 text 不能为空"

        keyword = text.strip()
        # 生成候选归档文件列表
        files = self._list_archive_files(archive_id)
        if not files:
            if archive_id:
                return f"错误：未找到归档文件 {archive_id}"
            return "错误：.agents/context/ 目录下没有任何归档文件"

        results = []  # (archive_id, line_no, snippet)

        for fid, path in files.items():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for line_no, line in enumerate(f, 1):
                        line = line.rstrip("\n")
                        if not line:
                            continue
                        # 关键词匹配（大小写不敏感的子串匹配）
                        if keyword.lower() in line.lower():
                            snippet = self._make_snippet(line, keyword, max_chars_per_result)
                            results.append((fid, line_no, snippet))
            except Exception as e:
                print(f"[Context] 读取归档 {fid} 失败: {e}")

        if not results:
            return f"未在归档中找到包含「{keyword}」的内容"

        # 按归档编号倒序（新的在前），每份归档最多保留 2 条
        results.sort(key=lambda r: r[0], reverse=True)
        seen_files = {}
        final_results = []
        for fid, line_no, snippet in results:
            if seen_files.get(fid, 0) >= 2:
                continue
            seen_files[fid] = seen_files.get(fid, 0) + 1
            final_results.append((fid, line_no, snippet))
            if len(final_results) >= max_results:
                break

        # 格式化输出
        lines = [f"【recallContext 检索结果】关键词：{keyword}", ""]
        for fid, line_no, snippet in final_results:
            lines.append(f"归档 {fid} · 第 {line_no} 行:")
            lines.append(f"  {snippet}")
            lines.append("")
        lines.append(f"共返回 {len(final_results)} 条匹配（归档编号 {', '.join(f'{fid}' for f, _, _ in final_results)}）")
        return "\n".join(lines)

    def _list_archive_files(self, archive_id: Optional[str] = None) -> Dict[str, str]:
        """
        返回 {归档编号: 文件路径} 映射。
        指定 archive_id 时只返回该文件（若存在）。
        """
        if not os.path.isdir(self.context_dir):
            return {}

        if archive_id:
            # 去掉可能的扩展名，防止拼接 .jsonl.jsonl
            fid = archive_id.replace(".jsonl", "")
            path = os.path.join(self.context_dir, f"{fid}.jsonl")
            if os.path.exists(path):
                return {fid: path}
            return {}

        result = {}
        for fname in os.listdir(self.context_dir):
            if fname.endswith(".jsonl"):
                fid = fname[:-6]
                result[fid] = os.path.join(self.context_dir, fname)
        return result

    def _make_snippet(self, line: str, keyword: str, max_chars: int) -> str:
        """
        从一行消息中截取包含关键词的片段，控制返回长度。
        """
        # 先解析 JSON，尽量展示可读内容
        try:
            msg = json.loads(line)
            content = msg.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    i.get("text", "") for i in content
                    if isinstance(i, dict) and i.get("type") == "text"
                )
            if not content:
                content = json.dumps(msg, ensure_ascii=False)
        except Exception:
            content = line

        idx = content.lower().find(keyword.lower())
        if idx < 0:
            idx = 0
        # 从关键词往前截一点，避免片段从中间开始太突兀
        start = max(0, idx - 60)
        snippet = content[start:start + max_chars]
        if start > 0:
            snippet = "…" + snippet
        if start + max_chars < len(content):
            snippet = snippet + "…"
        return snippet
