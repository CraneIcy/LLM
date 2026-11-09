"""
LLM 客户端：封装 DeepSeek / OpenAI 兼容 API 的流式调用与 Function Call 循环。
本模块完全不依赖任何 UI 框架，通过回调函数向外层推送事件，
未来接入 Web / Desktop 界面时只需传入新的回调实现即可。

上下文压缩功能：
- 每次 LLM 响应后检查 Token 用量（优先用 API 的 usage，否则本地估算）
- 达到 80%（config.ini [agent] warn_ratio，默认 0.8）显示警告，达到 100% 暂停接收新输入
- /compact 手动触发压缩：归档原始上下文 -> 调用 LLM 生成摘要 -> 替换历史
- 压缩期间禁止执行其他 Function Calling 工具

AGENTS.md 支持：
- 会话首次初始化时若项目根目录存在 AGENTS.md，将内容作为一条 system 消息注入聊天历史
- "一次注入，全程复用"：该消息常驻 messages，后续每一轮请求都会随历史一起发送，
  无需重复读取文件，保证缓存有效性
"""

import json
import os
from datetime import datetime
from typing import Callable, List, Dict, Optional

import requests

from .config import Config
from .tool_registry import ToolRegistry
from .skill_loader import SkillLoader
from .context_manager import ContextManager, COMPRESS_PROMPT, WARN_RATIO

# 项目指导文件注入时的字符上限：文件过长只截取前 N 个字符，避免占满上下文
AGENTS_MD_MAX_CHARS = 8000
# 兼容的项目指导文件名：配置的文件不存在时按顺序回退
AGENTS_MD_ALIASES = ("AGENTS.md", "AGENT.md")


class LLMClient:
    """大语言模型客户端，负责对话、工具调用与上下文压缩的完整流程。"""

    def __init__(
        self,
        config: Config,
        tool_registry: ToolRegistry,
        skill_loader: Optional[SkillLoader] = None,
        context_manager: Optional[ContextManager] = None,
        agents_md_path: Optional[str] = None,
    ):
        self.config = config
        self.tool_registry = tool_registry
        self.skill_loader = skill_loader
        self.messages: List[Dict] = []

        # 上下文管理器（负责归档 / 检索 / 用量统计）
        self.context_manager = context_manager

        # 压缩状态标志：
        #   self._compacting  = 正在执行压缩，禁止执行其他工具、禁止新输入
        #   self._input_blocked = 上下文已满，暂停接收普通输入（等 /compact）
        self._compacting = False
        self._input_blocked = False

        # 记录 AGENTS.md 路径，reset() 时重新注入（保证 /new 后依然生效）
        self._agents_md_path = agents_md_path

        # 初始化 System Prompt（包含可用的 Skill 列表）
        self._init_system_prompt()

        # 注入 AGENTS.md（"一次注入，全程复用"）
        self._inject_agents_md(agents_md_path)

    def _inject_agents_md(self, agents_md_path: Optional[str]):
        """
        把项目根目录的 AGENTS.md 内容作为一条 system 消息注入聊天历史。

        策略（"一次注入，全程复用"）：
        - 仅在会话初始化时读取一次文件，写入 self.messages
        - 该消息常驻历史，后续每一轮 LLM 请求都会随 messages 一起发送
          （无需每轮重新读文件，天然满足缓存有效性）
        - 文件缺失不报错，仅跳过；内容超过 AGENTS_MD_MAX_CHARS 时截断
        """
        if not agents_md_path:
            return

        # 配置的文件不存在时，回退到同目录下的 AGENT.md / AGENTS.md
        candidates = [agents_md_path]
        base_dir = os.path.dirname(agents_md_path)
        for alias in AGENTS_MD_ALIASES:
            candidate = os.path.join(base_dir, alias)
            if candidate not in candidates:
                candidates.append(candidate)

        target = next((path for path in candidates if os.path.exists(path)), None)
        if not target:
            return

        try:
            with open(target, "r", encoding="utf-8") as f:
                content = f.read().strip()
            if not content:
                return

            truncated = len(content) > AGENTS_MD_MAX_CHARS
            if truncated:
                content = content[:AGENTS_MD_MAX_CHARS]

            self.messages.append({
                "role": "system",
                "content": (
                    f"项目指导文件 {os.path.basename(target)} 内容（一次注入，全程复用）：\n\n"
                    + content
                    + ("\n\n（内容过长，已截断）" if truncated else "")
                ),
            })
            print(f"[AGENTS.md] 已注入 {os.path.basename(target)}（{len(content)} 字符）")
        except Exception as e:
            print(f"[AGENTS.md] 读取失败: {e}")

    def _init_system_prompt(self):
        """初始化系统提示词，注入可用的 Skill 列表。"""
        system_content = "You are a helpful AI assistant with access to various tools and skills."

        # 如果有 Skill 加载器，注入 Skill 信息
        if self.skill_loader:
            skills = self.skill_loader.list_skills()
            if skills:
                skill_list = "\n".join([f"- {s.name}: {s.description}" for s in skills])
                system_content += f"""

You have access to the following skills:
{skill_list}

Use the loadSkill tool to load the full instructions of a skill when needed.
"""

        self.messages.append({"role": "system", "content": system_content})

    # ------------------------------------------------------------------
    # 上下文状态查询（供 TUI 状态栏使用）
    # ------------------------------------------------------------------
    def get_context_status(self) -> Dict:
        """
        返回当前上下文使用状态：
        {
            "usage_tokens": 已用 Token,
            "window_tokens": 窗口大小（0=未知，TUI 显示默认 128k + 「默认」）,
            "display_window": 用于计算的窗口,
            "ratio": 占用比例,
            "state": "ok" | "warn" | "blocked",
            "compacting": 是否正在压缩,
            "input_blocked": 是否暂停输入,
        }
        """
        status = {"compacting": self._compacting, "input_blocked": self._input_blocked}
        if self.context_manager:
            status.update(
                self.context_manager.get_context_usage(self.messages, self.tool_registry.get_tools_schema())
            )
        else:
            status.update({
                "usage_tokens": 0,
                "window_tokens": 0,
                "display_window": 0,
                "ratio": 0.0,
                "state": "ok",
            })
        return status

    def check_and_warn(self) -> Dict:
        """
        每次响应后调用：检查上下文用量，达到 80% 时置 input_blocked（等待 /compact）。
        返回最新状态字典（包含更新后的 input_blocked）。
        """
        status = self.get_context_status()
        if status.get("state") in ("warn", "blocked"):
            # 达到 80%：暂停接收新输入，直到压缩成功
            self._input_blocked = True
        else:
            self._input_blocked = False
        # 返回更新后的最新状态（input_blocked 已刷新）
        return self.get_context_status()

    # ------------------------------------------------------------------
    # 主对话流程
    # ------------------------------------------------------------------
    def chat(
        self,
        user_input: str,
        on_token: Optional[Callable[[str], None]] = None,
        on_tool_call: Optional[Callable[[str, dict], None]] = None,
        on_tool_result: Optional[Callable[[str, str], None]] = None,
    ) -> str:
        """
        发送一轮对话，自动处理 Function Call 循环。

        参数:
            user_input: 用户输入文本
            on_token: 流式输出每个 token 时的回调 (token: str) -> None
            on_tool_call: 模型决定调用工具时的回调 (tool_name: str, args: dict) -> None
            on_tool_result: 工具执行完成后的回调 (tool_name: str, result: str) -> None

        返回:
            模型最终回复的完整文本
        """
        # 输入状态检查：压缩进行中 / 上下文已满，都拒绝新的普通输入
        if self._compacting:
            raise RuntimeError("正在执行上下文压缩，暂时无法处理新消息，请稍候")
        if self._input_blocked:
            raise RuntimeError(
                "上下文使用量已达 80%，请先执行 /compact 完成上下文压缩后再继续对话"
            )

        self.messages.append({"role": "user", "content": user_input})
        final_reply = ""

        # 最大工具调用轮数：防止模型反复调用工具形成死循环（可从 .config.ini 配置）
        max_steps = max(1, self.config.max_tool_steps)
        steps = 0

        while True:
            steps += 1
            if steps > max_steps:
                note = (
                    f"（本轮已连续发起 {max_steps} 轮工具调用，达到上限，已停止继续调用以避免死循环。"
                    "如果任务尚未完成，请拆分成更小的步骤重新提问。）"
                )
                self.messages.append({"role": "assistant", "content": note})
                final_reply = note
                break

            resp = requests.post(
                url=f"{self.config.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.config.api_key}"},
                json={
                    "model": self.config.model,
                    "messages": self.messages,
                    "tools": self.tool_registry.get_tools_schema(),
                    "stream": True,
                    # 请求 API 返回 usage 统计（DeepSeek / OpenAI 兼容）
                    "stream_options": {"include_usage": True},
                },
                stream=True,
                # 请求超时：可从 .config.ini 的 [llm] request_timeout 配置（默认 300 秒）
                timeout=self.config.request_timeout,
            )

            assistant_reply = ""
            tool_calls: Dict[int, dict] = {}

            for line in resp.iter_lines():
                if not line or not line.startswith(b"data: "):
                    continue
                data = line[6:].decode("utf-8")
                if data == "[DONE]":
                    break
                chunk = json.loads(data)

                # 流式结尾的 usage 统计（choices 为空、带 usage 字段）
                if chunk.get("usage"):
                    if self.context_manager:
                        self.context_manager.last_usage = chunk["usage"]
                    continue

                delta = chunk["choices"][0]["delta"]

                # 收集文本内容
                if delta.get("content"):
                    assistant_reply += delta["content"]
                    if on_token:
                        on_token(delta["content"])

                # 收集工具调用（流式分片拼接）
                if delta.get("tool_calls"):
                    for tc in delta["tool_calls"]:
                        idx = tc["index"]
                        tool_calls.setdefault(idx, {"id": "", "name": "", "args": ""})
                        if tc.get("id"):
                            tool_calls[idx]["id"] = tc["id"]
                        if tc.get("function", {}).get("name"):
                            tool_calls[idx]["name"] = tc["function"]["name"]
                        if tc.get("function", {}).get("arguments"):
                            tool_calls[idx]["args"] += tc["function"]["arguments"]

            # 没有工具调用，对话结束
            if not tool_calls:
                self.messages.append({"role": "assistant", "content": assistant_reply})
                final_reply = assistant_reply
                break

            # 压缩期间禁止执行其他 Function Calling 工具（防御性检查）
            if self._compacting:
                self.messages.append({"role": "assistant", "content": assistant_reply})
                final_reply = "上下文压缩进行中，已跳过工具调用。"
                break

            # 把助手的工具调用消息加入历史
            self.messages.append({
                "role": "assistant",
                "content": assistant_reply or None,
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {"name": tc["name"], "arguments": tc["args"]},
                    }
                    for tc in tool_calls.values()
                ],
            })

            # 依次执行每个工具
            for tc in tool_calls.values():
                name = tc["name"]
                args = json.loads(tc["args"]) if tc["args"] else {}

                if on_tool_call:
                    on_tool_call(name, args)

                result = self.tool_registry.execute(name, args)

                if on_tool_result:
                    on_tool_result(name, result)

                self.messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result,
                })

        # 每次 LLM 完成响应后，检查上下文用量（达到 80% 则警告并暂停输入）
        self.check_and_warn()
        return final_reply

    # ------------------------------------------------------------------
    # /compact 上下文压缩流程
    # ------------------------------------------------------------------
    def compact(self, on_progress: Optional[Callable[[str], None]] = None) -> Dict:
        """
        手动触发上下文压缩（对应 /compact 命令）。

        流程：
        1. 进入压缩状态（禁止执行其他工具、禁止新输入）
        2. 把当前原始上下文完整归档到 .agents/context/
        3. 调用 LLM 用专用 Prompt 生成约 5000 Tokens 的摘要
        4. 用摘要替换历史消息（保留 System Prompt 和工具定义）
        5. 解除压缩状态与输入限制

        返回:
            {"success": bool, "archive_id": str, "error": str}
        """
        def progress(msg: str):
            if on_progress:
                on_progress(msg)

        # 压缩开始：进入压缩状态
        self._compacting = True

        try:
            # ---- 1. 保存完整的原始上下文 ----
            if not self.context_manager:
                raise RuntimeError("未配置 ContextManager，无法执行上下文压缩")

            archive_id = self.context_manager.save_archive(self.messages)
            if not archive_id:
                raise RuntimeError("原始上下文归档保存失败，已中止压缩（保留原上下文）")
            progress(f"① 原始上下文已归档：{archive_id}")

            # ---- 2. 构造压缩请求：用专用 Prompt + 完整历史 ----
            compress_messages = [
                {"role": "system", "content": COMPRESS_PROMPT},
                {
                    "role": "user",
                    "content": "以下是需要压缩的历史对话（JSON 格式）：\n\n"
                               + self.context_manager.messages_to_text(self.messages),
                },
            ]

            progress("② 正在调用 LLM 生成上下文摘要...")
            resp = requests.post(
                url=f"{self.config.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.config.api_key}"},
                json={
                    "model": self.config.model,
                    "messages": compress_messages,
                    "stream": False,
                    # 摘要最大输出 Token：可从 config.ini [agent] compact_max_tokens 配置
                    "max_tokens": self.config.compact_max_tokens,
                },
                # 压缩请求超时：可从 config.ini [llm] request_timeout 配置
                timeout=self.config.request_timeout,
            )

            if resp.status_code != 200:
                try:
                    err = resp.json().get("error", {}).get("message", resp.text[:300])
                except Exception:
                    err = resp.text[:300]
                raise RuntimeError(f"压缩请求失败（HTTP {resp.status_code}）：{err}")

            data = resp.json()
            summary = data["choices"][0]["message"]["content"]

            if not summary or not summary.strip():
                raise RuntimeError("压缩结果为空，已中止（保留原上下文）")

            # ---- 3. 用摘要替换历史消息 ----
            # 保留 System Prompt 和工具定义（messages[0] 是 system）
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            archive_note = (
                f"\n\n> 此前上下文已于 {now_str} 完成压缩，"
                f"原始上下文保存在编号为 {archive_id} 的归档文件中。"
                f"如需查找历史信息，请使用 recallContext 工具。"
            )

            new_messages = [self.messages[0]]
            new_messages.append({
                "role": "assistant",
                "content": summary + archive_note,
            })
            self.messages = new_messages

            # 清空缓存的 usage（历史已变化）
            if self.context_manager:
                self.context_manager.last_usage = None

            # ---- 4. 压缩成功：解除输入限制 ----
            self._input_blocked = False
            progress(f"③ 压缩完成！会话已替换为摘要（归档 {archive_id}），可以继续对话。")
            return {"success": True, "archive_id": archive_id, "error": ""}

        except Exception as e:
            # 压缩失败：保留原有上下文，报告错误
            progress(f"✗ 压缩失败：{e}")
            return {"success": False, "archive_id": "", "error": str(e)}

        finally:
            # 无论成败，都要退出压缩状态
            self._compacting = False

    # ------------------------------------------------------------------
    # 其他
    # ------------------------------------------------------------------
    def reset(self):
        """清空对话历史，并重建 System Prompt 与 AGENTS.md 注入（/new 使用）。"""
        self.messages = []
        self._input_blocked = False
        if self.context_manager:
            self.context_manager.last_usage = None
        # 重建基础 System Prompt（Skill 列表）与 AGENTS.md 注入，
        # 保证新建会话后 Agent 能力与项目指导仍然生效
        self._init_system_prompt()
        self._inject_agents_md(getattr(self, "_agents_md_path", None))
