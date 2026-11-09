# -*- coding: utf-8 -*-
"""集成测试：LLMClient + ContextManager 的压缩状态机（mock 掉真实 API）"""
import os
import sys
import tempfile

sys.path.insert(0, r"D:\LLM\Agent\CAgent")

from core.config import Config
from core.tool_registry import ToolRegistry
from core.context_manager import ContextManager
from core.llm_client import LLMClient

# ---------- Mock requests.post ----------
import requests as _requests

class FakeResponse:
    def __init__(self, status_code=200, text="", json_data=None, lines=None):
        self.status_code = status_code
        self._text = text
        self._json_data = json_data or {}
        self._lines = lines or []

    def json(self):
        return self._json_data

    def iter_lines(self):
        return self._lines

    @property
    def text(self):
        return self._text


# 模拟 DeepSeek 流式响应：第一轮没有工具调用，返回普通文本 + usage
def fake_stream_chunks(reply: str, usage: dict):
    import json as _json
    return [
        b'data: {"choices":[{"delta":{"role":"assistant"}}]}',
        f'data: {{"choices":[{{"delta":{{"content":"{reply}"}}}}]}}'.encode(),
        f'data: {{"usage":{_json.dumps(usage)}}}'.encode(),
        b'data: [DONE]',
    ]


calls = []

def fake_post(url, headers=None, json=None, stream=False, timeout=None):
    print(f"[MOCK] url={url} stream={stream} keys={list((json or {}).keys())[:5]}", flush=True)
    calls.append(json)
    if "stream" in (json or {}) and (json or {}).get("stream"):
        # 对话流式调用
        usage = {"prompt_tokens": 500, "completion_tokens": 50, "total_tokens": 550}
        return FakeResponse(lines=fake_stream_chunks("这是模拟回复内容。", usage))
    # 压缩调用（stream=False）
    summary = (
        "# 工作摘要\n\n"
        "## 用户目标\n实现上下文压缩功能。\n"
        "## 已完成\nContextManager 已实现并通过测试。\n"
        "## 关键文件\n`core/context_manager.py`\n"
        "## 下一步\n集成到 TUI。"
    )
    return FakeResponse(
        status_code=200,
        json_data={"choices": [{"message": {"content": summary}}]},
    )


_requests.post = fake_post

# ---------- 初始化 ----------
tmp = tempfile.mkdtemp(prefix="ctx_integ_")

# 需要真实 config.ini（指向真实文件，但 mock 掉了网络请求）
config = Config(config_path=r"D:\LLM\Agent\CAgent\.config.ini")
tool_registry = ToolRegistry(config=config)
cm = ContextManager(project_root=tmp)
cm.context_window = 131072

llm = LLMClient(config=config, tool_registry=tool_registry, context_manager=cm)

print("=== 1. 正常对话 ===", flush=True)
reply = llm.chat("你好，介绍一下自己")
print(f"回复: {reply}", flush=True)
status = llm.get_context_status()
print(f"状态: usage={status['usage_tokens']}, ratio={status['ratio']:.3f}, state={status['state']}, blocked={status['input_blocked']}", flush=True)
assert status["state"] == "ok"
assert not status["input_blocked"]

print("\n=== 2. 模拟上下文接近 80% ===", flush=True)
# 手工制造高 usage：把 last_usage 改大（模拟 API 返回 105k tokens，> 窗口的 80%）
cm.last_usage = {"prompt_tokens": 105 * 1024, "total_tokens": 105 * 1024}
status = llm.check_and_warn()
print(f"状态: usage={status['usage_tokens']}, ratio={status['ratio']:.3f}, state={status['state']}, blocked={status['input_blocked']}", flush=True)
assert status["state"] == "warn"
assert status["input_blocked"] is True
print("✓ 达到 80% 后 input_blocked = True（暂停接收新提示词）", flush=True)

print("\n=== 3. 锁定状态下拒绝普通输入 ===", flush=True)
try:
    llm.chat("普通消息")
    print("✗ 应该被拒绝但没有", flush=True)
except RuntimeError as e:
    print(f"✓ 已拒绝: {e}", flush=True)

print("\n=== 4. 执行 /compact 压缩 ===", flush=True)
progress_log = []
result = llm.compact(on_progress=lambda m: progress_log.append(m))
print(f"结果: success={result['success']}, archive_id={result['archive_id']}", flush=True)
for p in progress_log:
    print(f"  {p}", flush=True)
assert result["success"]
assert result["archive_id"]

print("\n=== 5. 压缩后：输入解锁 + 摘要替换 ===", flush=True)
status = llm.get_context_status()
print(f"状态: blocked={status['input_blocked']}, compacting={status['compacting']}", flush=True)
assert not status["input_blocked"]
assert not status["compacting"]

print(f"压缩后消息条数: {len(llm.messages)}", flush=True)
for m in llm.messages:
    role = m["role"]
    content = (m.get("content") or "")[:80].replace("\n", " ")
    print(f"  [{role}] {content}", flush=True)
assert llm.messages[0]["role"] == "system"  # System Prompt 保留
assert "工作摘要" in llm.messages[-1]["content"]
assert "recallContext" in llm.messages[-1]["content"]  # 归档说明

print("\n=== 6. 压缩后可以继续对话 ===", flush=True)
reply = llm.chat("压缩后继续问问题")
print(f"回复: {reply}", flush=True)
print("✓ 压缩后正常恢复", flush=True)

print("\n=== 7. 归档文件检查 ===", flush=True)
archive_dir = os.path.join(tmp, ".agents", "context")
files = os.listdir(archive_dir)
print(f"归档文件: {files}", flush=True)
assert len(files) == 1
with open(os.path.join(archive_dir, files[0]), "r", encoding="utf-8") as f:
    archived = f.readlines()
print(f"归档行数: {len(archived)}（原始对话含 system 消息）", flush=True)

print("\n=== 8. recallContext 检索归档 ===", flush=True)
from core.tools.recall_context_tool import RecallContextTool
tool = RecallContextTool(context_manager=cm)
r = tool.execute(text="你好", id=result["archive_id"])
print(r[:400], flush=True)
assert "你好" in r

print("\n=== 9. 压缩失败场景：API 返回错误 ===", flush=True)
# 模拟：上下文已锁定（80%），尝试压缩但 API 失败
cm.last_usage = {"prompt_tokens": 105 * 1024, "total_tokens": 105 * 1024}
llm.check_and_warn()
assert llm._input_blocked is True

def fake_post_error(url, headers=None, json=None, stream=False, timeout=None):
    return FakeResponse(status_code=500, text="Internal Error", json_data={"error": {"message": "server error"}})
_requests.post = fake_post_error

old_len = len(llm.messages)
result = llm.compact(on_progress=lambda m: None)
print(f"结果: success={result['success']}, error={result['error']}", flush=True)
assert not result["success"]
assert len(llm.messages) == old_len  # 失败保留原上下文
print("✓ 压缩失败时保留原有上下文", flush=True)
status = llm.get_context_status()
print(f"失败后 blocked={status['input_blocked']}（应保持 True，等待重试 /compact）", flush=True)
assert status["input_blocked"] is True

print("\n全部集成测试通过", flush=True)
