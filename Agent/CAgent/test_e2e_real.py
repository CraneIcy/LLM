# -*- coding: utf-8 -*-
"""真实 API 端到端验证：确认 DeepSeek 返回 usage、压缩流程真实可用。"""
import os
import sys
import tempfile

sys.path.insert(0, r"D:\LLM\Agent\CAgent")

from core.config import Config
from core.tool_registry import ToolRegistry
from core.context_manager import ContextManager
from core.llm_client import LLMClient

config = Config(config_path=r"D:\LLM\Agent\CAgent\.config.ini")
tool_registry = ToolRegistry(config=config)
tmp = tempfile.mkdtemp(prefix="ctx_e2e_")
cm = ContextManager(project_root=tmp)
cm.context_window = 0  # 模拟"未知窗口"，应显示默认 128k

llm = LLMClient(config=config, tool_registry=tool_registry, context_manager=cm)

print("=== 真实对话（验证 usage 收集）===", flush=True)
reply = llm.chat("用一句话介绍你自己")
print(f"回复: {reply[:80]}", flush=True)
print(f"last_usage: {cm.last_usage}", flush=True)
assert cm.last_usage and cm.last_usage.get("total_tokens"), "未收集到 usage"
print("✓ API usage 收集成功", flush=True)

status = llm.get_context_status()
print(f"上下文状态: {status}", flush=True)
assert status["window_tokens"] == 0
assert status["display_window"] == 128 * 1024
print("✓ 窗口未知时默认 128k", flush=True)

print("\n=== 真实 /compact 压缩 ===", flush=True)
progress = []
result = llm.compact(on_progress=lambda m: progress.append(m))
print(f"success={result['success']}", flush=True)
for p in progress:
    print(f"  {p}", flush=True)
assert result["success"]
assert result["archive_id"]

# 检查归档文件
archive_path = os.path.join(tmp, ".agents", "context", result["archive_id"] + ".jsonl")
assert os.path.exists(archive_path), "归档文件不存在"
print(f"归档文件存在: {archive_path}", flush=True)

# 检查摘要内容
assert "recallContext" in llm.messages[-1]["content"], "摘要末尾缺少归档说明"
print("摘要前 200 字:", flush=True)
print(llm.messages[-1]["content"][:200], flush=True)
print("✓ 归档说明已追加", flush=True)

print("\n=== 真实 recallContext 检索 ===", flush=True)
from core.tools.recall_context_tool import RecallContextTool
tool = RecallContextTool(context_manager=cm)
r = tool.execute(text="介绍", id=result["archive_id"])
print(r[:500], flush=True)

print("\n=== 压缩后继续对话 ===", flush=True)
reply = llm.chat("刚才压缩完成了，继续。")
print(f"回复: {reply[:80]}", flush=True)
print("✓ 压缩后对话正常", flush=True)

print("\n端到端真实验证全部通过", flush=True)
