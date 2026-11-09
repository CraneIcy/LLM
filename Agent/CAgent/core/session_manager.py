"""
会话管理器：负责历史会话的保存、列表、加载与删除。
支撑斜杠命令 /new（新建并保存当前）、/resume（恢复历史会话）、/save（保存当前会话）。

设计要点（教学要求）：
- 会话文件与上下文归档格式一致：JSONL，每行一条消息 JSON
- 保存目录：<项目根>/.agents/sessions/
- 文件命名：YYYYMMDD-HHMMSS.jsonl（与上下文归档编号风格统一，便于理解）
"""

import json
import os
from datetime import datetime
from typing import Dict, List, Optional


class SessionManager:
    """历史会话管理：保存 / 列出 / 加载 / 删除会话。"""

    def __init__(self, project_root: str, save_dir: Optional[str] = None):
        """
        :param project_root: 项目根目录（默认会话目录为 <项目根>/.agents/sessions/）
        :param save_dir: 可选，自定义会话保存目录（用于 config.ini 配置化）
        """
        self.project_root = project_root
        if save_dir:
            # 支持绝对路径或相对项目根目录的路径
            if os.path.isabs(save_dir):
                self.session_dir = save_dir
            else:
                self.session_dir = os.path.join(project_root, save_dir)
        else:
            self.session_dir = os.path.join(project_root, ".agents", "sessions")

    # ------------------------------------------------------------------
    # 目录与编号
    # ------------------------------------------------------------------
    def _ensure_session_dir(self):
        """确保会话目录存在（不存在则创建）。"""
        os.makedirs(self.session_dir, exist_ok=True)

    def _generate_session_id(self) -> str:
        """
        生成唯一会话编号，格式：YYYYMMDD-HHMMSS。
        同一秒内多次保存时追加序号（-001/-002...），避免文件名互相覆盖。
        """
        base = datetime.now().strftime("%Y%m%d-%H%M%S")
        candidate = base
        n = 0
        # 同秒已有同名文件：追加序号，保证编号唯一
        while os.path.exists(os.path.join(self.session_dir, f"{candidate}.jsonl")):
            n += 1
            candidate = f"{base}-{n:03d}"
        return candidate

    # ------------------------------------------------------------------
    # 保存
    # ------------------------------------------------------------------
    def save_session(self, messages: List[Dict]) -> Optional[str]:
        """
        把当前会话消息完整保存为会话文件。

        :param messages: 要保存的消息列表（原始顺序，含 role/content/tool_calls 等字段）
        :return: 会话编号（成功）；None（失败）
        """
        if not messages:
            return None  # 空会话不保存

        try:
            self._ensure_session_dir()
            session_id = self._generate_session_id()
            file_path = os.path.join(self.session_dir, f"{session_id}.jsonl")

            with open(file_path, "w", encoding="utf-8") as f:
                for msg in messages:
                    # 每条消息保留原始字段（role/content/tool_calls/tool_call_id 等）
                    line = json.dumps(msg, ensure_ascii=False)
                    f.write(line + "\n")

            return session_id
        except Exception as e:
            print(f"[Session] 会话保存失败: {e}")
            return None

    # ------------------------------------------------------------------
    # 列表
    # ------------------------------------------------------------------
    def list_sessions(self) -> List[Dict]:
        """
        返回所有历史会话的摘要信息，按创建时间倒序（新的在前）。

        返回示例：
        [
            {
                "id": "20261104-153000",
                "title": "帮我写一个上下文压缩功能",
                "msg_count": 12,
                "created_at": "2026-11-04 15:30:00",
                "size": 8421,
            },
            ...
        ]
        """
        if not os.path.isdir(self.session_dir):
            return []

        sessions = []
        for fname in os.listdir(self.session_dir):
            if not fname.endswith(".jsonl"):
                continue
            session_id = fname[:-6]  # 去掉 .jsonl 后缀
            file_path = os.path.join(self.session_dir, fname)

            # 读取首条用户消息作为标题，同时统计消息条数
            title = "（空会话）"
            msg_count = 0
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        msg_count += 1
                        try:
                            msg = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if title == "（空会话）" and msg.get("role") == "user":
                            content = msg.get("content", "")
                            if isinstance(content, list):
                                content = " ".join(
                                    i.get("text", "") for i in content
                                    if isinstance(i, dict) and i.get("type") == "text"
                                )
                            # 截取前 30 个字符作为会话标题
                            title = (str(content) or "（空会话）").replace("\n", " ")[:30]
            except Exception as e:
                print(f"[Session] 读取会话 {session_id} 摘要失败: {e}")

            created_at = self._parse_session_id(session_id)
            sessions.append({
                "id": session_id,
                "title": title,
                "msg_count": msg_count,
                "created_at": created_at,
                "size": os.path.getsize(file_path) if os.path.exists(file_path) else 0,
            })

        # 按会话编号倒序排列（编号含时间，倒序 = 新的在前）
        sessions.sort(key=lambda s: s["id"], reverse=True)
        return sessions

    @staticmethod
    def _parse_session_id(session_id: str) -> str:
        """把 YYYYMMDD-HHMMSS 解析成可读的 YYYY-MM-DD HH:MM:SS。"""
        try:
            # 优先按标准 15 位编号解析
            return datetime.strptime(session_id, "%Y%m%d-%H%M%S").strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
        try:
            # 兼容同秒追加序号的形式：YYYYMMDD-HHMMSS-NNN（取前 15 位解析）
            return datetime.strptime(session_id[:15], "%Y%m%d-%H%M%S").strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            return session_id

    # ------------------------------------------------------------------
    # 加载
    # ------------------------------------------------------------------
    def load_session(self, session_id: str) -> List[Dict]:
        """
        加载指定会话的消息列表。

        :param session_id: 会话编号（YYYYMMDD-HHMMSS）
        :return: 消息列表；文件不存在或解析失败时返回空列表
        """
        # 去掉可能的扩展名，防止拼接 .jsonl.jsonl
        sid = session_id.replace(".jsonl", "")
        file_path = os.path.join(self.session_dir, f"{sid}.jsonl")
        if not os.path.exists(file_path):
            return []

        messages = []
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        messages.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue  # 跳过损坏行，尽量恢复可用消息
            return messages
        except Exception as e:
            print(f"[Session] 加载会话 {session_id} 失败: {e}")
            return []

    # ------------------------------------------------------------------
    # 删除
    # ------------------------------------------------------------------
    def delete_session(self, session_id: str) -> bool:
        """
        删除指定会话文件。

        :param session_id: 会话编号（YYYYMMDD-HHMMSS）
        :return: 是否删除成功
        """
        sid = session_id.replace(".jsonl", "")
        file_path = os.path.join(self.session_dir, f"{sid}.jsonl")
        if not os.path.exists(file_path):
            return False
        try:
            os.remove(file_path)
            return True
        except Exception as e:
            print(f"[Session] 删除会话 {session_id} 失败: {e}")
            return False
