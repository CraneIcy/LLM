# -*- coding: utf-8 -*-
"""验证 ContextManager：估算、归档、检索（不依赖 LLM）"""
import os
import sys
import tempfile

sys.path.insert(0, r"D:\LLM\Agent\CAgent")

from core.context_manager import ContextManager, estimate_tokens

# 用临时目录做测试，避免污染项目
tmp = tempfile.mkdtemp(prefix="ctx_test_")
cm = ContextManager(project_root=tmp)
cm.context_window = 131072

print("=== 1. Token 估算 ===", flush=True)
text = "你好，这是一段测试文本。Hello world, this is a test." * 100
tokens = estimate_tokens(text)
print(f"文本长度 {len(text)} -> 估算 {tokens} tokens", flush=True)

print("\n=== 2. 归档保存 ===", flush=True)
messages = [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "帮我写一个 Python 排序函数"},
    {"role": "assistant", "content": "好的，以下是快速排序实现...", "tool_calls": [
        {"id": "call_1", "type": "function", "function": {"name": "createFile", "arguments": '{"path":"sort.py"}'}}
    ]},
    {"role": "tool", "tool_call_id": "call_1", "content": "文件已创建"},
    {"role": "user", "content": "再加一个递归版本"},
]
archive_id = cm.save_archive(messages)
print(f"归档编号: {archive_id}", flush=True)
print(f"文件存在: {os.path.exists(os.path.join(tmp, '.agents', 'context', archive_id + '.jsonl'))}", flush=True)

print("\n=== 3. 全文检索（指定 id）===", flush=True)
result = cm.recall(text="排序", archive_id=archive_id)
print(result, flush=True)

print("\n=== 4. 全文检索（全部归档）===", flush=True)
result = cm.recall(text="递归")
print(result, flush=True)

print("\n=== 5. 检索不存在关键词 ===", flush=True)
result = cm.recall(text="不存在的关键词xyz")
print(result, flush=True)

print("\n=== 6. 检索空关键词 ===", flush=True)
result = cm.recall(text="  ")
print(result, flush=True)

print("\n=== 7. 上下文用量计算 ===", flush=True)
usage = cm.get_context_usage(messages, [])
print(f"usage: {usage}", flush=True)

print("\n全部通过", flush=True)
