# -*- coding: utf-8 -*-
"""
GUI 冒烟测试：真实启动图形界面（本机有显示器），
验证主窗口组件、状态栏、消息发送/流式、斜杠命令补全面板、
会话面板、MCP 异步边栏刷新。不真实调用外部 API。

运行：python test_gui_smoke.py
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, r"D:\LLM\Agent\CAgent")

from core.config import Config
from core.tool_registry import ToolRegistry
from core.context_manager import ContextManager
from core.session_manager import SessionManager
from core.llm_client import LLMClient
from ui.gui.app import CAgentGUI, CommandPalette, SessionPickerDialog, Pill, MiniBar

# ----------------------------------------------------------------------
# Mock 网络请求（避免真实调用 API）
# ----------------------------------------------------------------------
import requests as _requests
import json as _json


class FakeResp:
    status_code = 200

    def json(self):
        return {"choices": [{"message": {"content": "# 摘要\n\n## 用户目标\nGUI 测试。\n## 下一步\n验证。"}}]}

    @property
    def text(self):
        return "ok"

    def iter_lines(self):
        usage = {"prompt_tokens": 500, "completion_tokens": 30, "total_tokens": 530}
        return [
            b'data: {"choices":[{"delta":{"role":"assistant"}}]}',
            'data: {"choices":[{"delta":{"content":"你好，这是 GUI 测试回复。"}}]}'.encode(),
            f'data: {{"usage":{_json.dumps(usage)}}}'.encode(),
            b'data: [DONE]',
        ]


def fake_post(url, headers=None, json=None, stream=False, timeout=None):
    return FakeResp()


_requests.post = fake_post

config = Config(config_path=r"D:\LLM\Agent\CAgent\.config.ini")
tool_registry = ToolRegistry(config=config)
tmp = tempfile.mkdtemp(prefix="gui_")
cm = ContextManager(project_root=tmp)
cm.context_window = 0  # 未知窗口 -> 显示默认 128k
llm = LLMClient(config=config, tool_registry=tool_registry, context_manager=cm)
sm = SessionManager(project_root=tmp)
sm.save_session([{"role": "system", "content": "s"}, {"role": "user", "content": "历史会话A 内容"}])
sm.save_session([{"role": "system", "content": "s"}, {"role": "user", "content": "历史会话B 内容"}])


class FakeMCPClient:
    """模拟 MCP 客户端（异步加载）。"""

    def __init__(self):
        self.servers = {"Bazi-MCP": object()}
        self.server_tools = {
            "Bazi-MCP": [
                {"name": "getBaziDetail", "description": "八字", "inputSchema": {}},
                {"name": "getSolarTimes", "description": "日出日落", "inputSchema": {}},
            ]
        }

    def discover_and_register(self):
        time.sleep(0.5)  # 模拟连接耗时

    def get_server_summary(self):
        return [{
            "name": n,
            "status": "connected" if n in self.servers else "failed",
            "tool_count": len(t),
            "tools": [x["name"] for x in t],
        } for n, t in self.server_tools.items()]


failures = []


def check(name, cond, extra=""):
    if cond:
        print(f"✓ {name}" + (f"  {extra}" if extra else ""), flush=True)
    else:
        print(f"✗ {name}  {extra}", flush=True)
        failures.append(name)


def safe(step):
    """执行一个验证步骤；异常也继续（避免单步失败中断后续验证）。"""
    try:
        step()
    except Exception as e:
        import traceback
        print(f"✗ 步骤异常: {e}", flush=True)
        traceback.print_exc()
        failures.append(f"异常:{e}")


gui = None


def _drive():
    """在 GUI 事件循环里依次执行验证（每一步独立容错）。"""
    safe(lambda: check("主窗口标题", "CAgent" in gui.title()))
    safe(lambda: check(
        "顶部信息栏显示上下文",
        "%" in gui.ctx_label.cget("text") and "128" in gui.ctx_label.cget("text"),
    ))
    safe(lambda: check(
        "上下文进度条存在",
        isinstance(gui.ctx_bar, MiniBar),
    ))
    safe(lambda: check("信息栏标注默认 128k", "默认" in gui.ctx_label.cget("text")))
    safe(lambda: check("工具数显示", "工具" in gui.tool_pill.get_text()))

    # 顶栏功能按钮存在（功能一目了然）：递归遍历所有子孙 widget
    def walk(w):
        for c in w.winfo_children():
            yield c
            yield from walk(c)

    def check_toolbar():
        texts = []
        for c in walk(gui):
            if isinstance(c, Pill):
                texts.append(c.get_text())
        joined = " | ".join(texts)
        for expect in ("压缩上下文", "帮助", "发送"):
            check(f"顶栏按钮[{expect}]", expect in joined)
    safe(check_toolbar)

    # 1. 发送普通消息（走 mock API + 流式）
    gui.input_box.insert(0, "你好，GUI")
    gui._on_send(None)
    gui.after(800, _after_send)


def _after_send():
    safe(lambda: check("用户气泡已添加", bool(gui.chat_text.get("1.0", "end").strip())))
    safe(lambda: check(
        "助手回复已流式输出",
        bool(gui._current_bubble) and "GUI 测试回复" in gui._current_bubble.itemcget(
            gui._current_bubble._text_item, "text"
        ),
    ))
    safe(lambda: check("对话后 usage 已收集", llm.get_context_status()["usage_tokens"] == 500))
    gui.after(200, _test_palette)


def _test_palette():
    # 2. 输入 / 弹出斜杠命令补全面板
    gui.input_box.delete(0, "end")
    gui.input_box.insert(0, "/new")

    class FakeEvent:
        """模拟键盘事件（keysym 用于跳过回车/方向键分支）。"""
        keysym = "a"

    gui._on_key_release(FakeEvent())
    safe(lambda: check(
        "斜杠命令补全面板已创建",
        gui._palette is not None and gui._palette.winfo_exists(),
    ))
    if gui._palette is not None and gui._palette.winfo_exists():
        items = list(gui._palette.listbox.get(0, "end"))
        safe(lambda: check("补全面板过滤生效", len(items) == 1 and "/new" in items[0]))
        # 改输入 "/" 重新触发：应显示全部 11 条命令
        gui.input_box.delete(0, "end")
        gui.input_box.insert(0, "/")
        gui._on_key_release(FakeEvent())
        items_all = list(gui._palette.listbox.get(0, "end"))
        safe(lambda: check("补全面板含 /new", any("/new" in i for i in items_all)))
        safe(lambda: check("补全面板含 /resume", any("/resume" in i for i in items_all)))
        safe(lambda: check("补全面板含 /quit", any("/quit" in i for i in items_all)))
        safe(lambda: check("补全面板共 11 条命令", len(items_all) == 11))
        # 恢复 /new 并执行
        gui.input_box.delete(0, "end")
        gui.input_box.insert(0, "/new")
        gui._on_key_release(FakeEvent())
        gui._palette.listbox.selection_set(0)
        gui._palette._select()
    gui.after(200, _test_resume)


def _test_resume():
    # 3. /resume：弹出历史会话面板
    gui.action_resume_session()
    gui.after(300, _check_picker)


def _check_picker():
    picker = None
    for w in gui.winfo_children():
        if isinstance(w, SessionPickerDialog):
            picker = w
            break
    safe(lambda: check("/resume 弹出会话列表面板", picker is not None))
    if picker is not None:
        rows = picker.tree.get_children()
        safe(lambda: check("面板列出历史会话", len(rows) >= 2))
        picker.tree.selection_set(rows[0])
        picker._pick()
        gui.after(200, _test_after_resume)
    else:
        _test_after_resume()


def _test_after_resume():
    user_msgs = [m for m in llm.messages if m["role"] == "user"]
    # /new 时保存了含「你好，GUI」的会话，rows[0] 是最新会话 -> 恢复后应能取到该消息
    safe(lambda: check(
        "会话恢复后消息已替换",
        len(user_msgs) >= 1 and "你好" in user_msgs[-1]["content"],
    ))
    safe(lambda: check(
        "会话面板已关闭",
        not any(isinstance(w, SessionPickerDialog) for w in gui.winfo_children()),
    ))
    gui.after(200, _test_save_clear)


def _test_save_clear():
    # 4. /save + /clear + /help + /tools 不抛异常
    before = len(sm.list_sessions())
    gui.action_save_session()
    gui.action_clear_chat()
    gui.action_help_command()
    gui.action_show_tools()
    safe(lambda: check("/save 保存会话", len(sm.list_sessions()) == before + 1))
    gui.after(200, _test_compact_mcp)


def _test_compact_mcp():
    # 5. /compact 压缩流程（mock API 返回摘要）
    gui.action_compact_command()
    gui.after(1200, _test_mcp_sidebar)


def _test_mcp_sidebar():
    # 6. MCP 边栏：异步线程已完成，应刷新出服务器与工具
    mcp_summary = gui.mcp_text.get("1.0", "end")
    mcp_detail = gui.mcp_detail.get("1.0", "end")
    safe(lambda: check("MCP 左栏显示服务器名", "Bazi-MCP" in mcp_summary))
    safe(lambda: check("MCP 详情显示工具列表", "getBaziDetail" in mcp_detail and "getSolarTimes" in mcp_detail))
    safe(lambda: check("MCP 显示已连接", "已连接" in mcp_detail))
    gui.action_show_mcp()
    gui.action_show_context()
    gui.after(300, _finish)


def _finish():
    print("\nGUI 冒烟测试完成", flush=True)
    gui.destroy()


def _finish_force():
    """超时保险：无论如何都关闭窗口，避免测试挂死。"""
    try:
        gui.destroy()
    except Exception:
        pass


print("启动 GUI 冒烟测试", flush=True)
gui = CAgentGUI(
    llm_client=llm,
    session_manager=sm,
    mcp_client=FakeMCPClient(),
    config=config,
    config_warning=False,
)
gui.after(600, _drive)  # 等窗口就绪后开始验证
gui.after(30000, _finish_force)  # 超时保险（30 秒后强制关闭）
gui.mainloop()

# ----------------------------------------------------------------------
# 汇总
# ----------------------------------------------------------------------
print("=" * 50, flush=True)
if failures:
    print(f"失败 {len(failures)} 项: {failures}", flush=True)
    sys.exit(1)
print("全部 GUI 冒烟测试通过", flush=True)
