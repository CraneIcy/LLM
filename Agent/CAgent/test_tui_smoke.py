# -*- coding: utf-8 -*-
"""TUI 冒烟测试：验证状态栏上下文显示与 /compact 命令处理（不真实调用 API）。"""
import os
import sys
import tempfile

sys.path.insert(0, r"D:\LLM\Agent\CAgent")

from core.config import Config
from core.tool_registry import ToolRegistry
from core.context_manager import ContextManager
from core.llm_client import LLMClient
from ui.tui.app import TUIApp, ToolLogPanel, Input

# Mock 掉网络请求，避免真实调用
import requests as _requests
import json as _json

class FakeResp:
    status_code = 200
    def json(self):
        return {"choices": [{"message": {"content": "# 测试摘要\n\n## 用户目标\nTUI 测试。\n## 下一步\n完成验证。"}}]}
    @property
    def text(self):
        return "ok"
    def iter_lines(self):
        usage = {"prompt_tokens": 500, "completion_tokens": 30, "total_tokens": 530}
        return [
            b'data: {"choices":[{"delta":{"role":"assistant"}}]}',
            'data: {"choices":[{"delta":{"content":"你好，这是测试回复。"}}]}'.encode(),
            f'data: {{"usage":{_json.dumps(usage)}}}'.encode(),
            b'data: [DONE]',
        ]

def fake_post(url, headers=None, json=None, stream=False, timeout=None):
    return FakeResp()

_requests.post = fake_post

config = Config(config_path=r"D:\LLM\Agent\CAgent\.config.ini")
tool_registry = ToolRegistry(config=config)
tmp = tempfile.mkdtemp(prefix="ctx_tui_")
cm = ContextManager(project_root=tmp)
cm.context_window = 0  # 未知窗口 -> 显示默认 128k
llm = LLMClient(config=config, tool_registry=tool_registry, context_manager=cm)

async def run_smoke():
    app = TUIApp(llm_client=llm)
    async with app.run_test() as pilot:
        # 1. 启动后检查状态栏
        await pilot.pause()
        label = app.query_one("#status-line")
        text = label.render()
        print("启动状态栏:", str(text), flush=True)
        assert "128" in str(text) and "默认" in str(text), "状态栏应显示默认 128k + 「默认」"
        assert "上下文" in str(text)
        print("✓ 状态栏显示上下文占用 + 默认 128k", flush=True)

        # 2. 模拟 on_input_submitted 发普通消息（走 mock API）
        input_box = app.query_one("#input-box", Input)
        input_box.value = "hello"
        await app.on_input_submitted(Input.Submitted(input_box, "hello"))
        await pilot.pause(1.0)
        label = app.query_one("#status-line")
        status = llm.get_context_status()
        print("对话后 usage:", status["usage_tokens"], flush=True)
        assert status["usage_tokens"] == 500, "对话后应使用 mock usage"
        print("✓ 普通对话流程正常，usage 已收集", flush=True)

        # 3. 模拟输入 /compact 触发压缩
        input_box.value = "/compact"
        await app.on_input_submitted(Input.Submitted(input_box, "/compact"))
        await pilot.pause(1.0)
        label = app.query_one("#status-line")
        status = llm.get_context_status()
        print("压缩后 blocked:", status["input_blocked"], flush=True)
        print("压缩后状态栏:", str(label.render()), flush=True)
        # 归档文件应已生成
        ctx_dir = os.path.join(tmp, ".agents", "context")
        files = os.listdir(ctx_dir)
        print("归档文件:", files, flush=True)
        assert len(files) == 1
        print("✓ /compact 命令已处理并生成归档", flush=True)

        # 4. 验证压缩真实生效：消息被摘要替换（含归档说明）
        assert len(llm.messages) == 2, "压缩后应只剩 system + 摘要"
        assert "recallContext" in llm.messages[-1]["content"], "摘要末尾应含归档说明"
        print("压缩后消息数:", len(llm.messages), "（system + 摘要）", flush=True)
        print("✓ 摘要已替换历史，归档说明已追加", flush=True)

        # 5. 锁定测试：手工把 usage 推到 80%+ 后刷新状态栏
        cm.last_usage = {"prompt_tokens": 110 * 1024, "total_tokens": 110 * 1024}
        llm.check_and_warn()
        app._update_status_line()  # 测试在 app 线程，直接调用
        await pilot.pause(0.3)
        label = app.query_one("#status-line")
        print("锁定状态栏:", str(label.render()), flush=True)
        assert llm._input_blocked is True
        print("✓ 达到 80% 后 input_blocked 生效", flush=True)

print("启动 TUI 冒烟测试", flush=True)
import asyncio
asyncio.run(run_smoke())
print("\nTUI 冒烟测试通过", flush=True)
