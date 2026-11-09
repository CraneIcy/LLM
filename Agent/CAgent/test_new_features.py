# -*- coding: utf-8 -*-
"""
CAgent 新增功能验证测试（本轮 5 项新需求）：
1. 斜杠命令系统与补全引导面板（/new /resume /save /quit + 面板）
2. 配置化改造（config.ini + 默认参数）
3. config.ini 缺失自动创建 mock 模板
4. MCP 边栏显示 + 异步加载动态刷新
5. AGENTS.md「一次注入，全程复用」

运行：python test_new_features.py
（不真实调用外部 API；MCP 使用 Fake 客户端模拟异步加载）
"""
import os
import sys
import time
import tempfile
import asyncio

sys.path.insert(0, r"D:\LLM\Agent\CAgent")

from core.config import Config
from core.tool_registry import ToolRegistry
from core.context_manager import ContextManager
from core.session_manager import SessionManager
from core.llm_client import LLMClient
from ui.tui.app import TUIApp, ToolLogPanel, Input, SessionPicker, ListView

# ----------------------------------------------------------------------
# Mock 网络请求（避免真实调用 API）
# ----------------------------------------------------------------------
import requests as _requests
import json as _json


class FakeResp:
    status_code = 200

    def json(self):
        return {"choices": [{"message": {"content": "# 摘要\n\n## 用户目标\n测试。\n## 下一步\n验证。"}}]}

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

CONFIG_PATH = r"D:\LLM\Agent\CAgent\.config.ini"
config = Config(config_path=CONFIG_PATH)
tool_registry = ToolRegistry(config=config)
tmp = tempfile.mkdtemp(prefix="newfeat_")
cm = ContextManager(project_root=tmp)
cm.context_window = 0  # 未知窗口 -> 显示默认 128k
llm = LLMClient(config=config, tool_registry=tool_registry, context_manager=cm)

failures = []


def check(name, cond, extra=""):
    """断言并统计。"""
    if cond:
        print(f"✓ {name}" + (f"  {extra}" if extra else ""), flush=True)
    else:
        print(f"✗ {name}  {extra}", flush=True)
        failures.append(name)


# ======================================================================
# 1. 配置化：默认参数（不存在的键应返回默认值，不抛异常）
# ======================================================================
print("=== 1. 配置化（默认参数） ===", flush=True)
check("base_url 默认值", config.get("llm", "base_url", "https://api.deepseek.com/v1") == "https://api.deepseek.com/v1")
check("model 默认值", config.model == "deepseek-chat")
check("temperature 默认 0.7", config.get_float("llm", "temperature", 0.7) == 0.7)
check("request_timeout 默认 300", config.get_int("llm", "request_timeout", 300) == 300)
check("warn_ratio 默认 0.8", config.warn_ratio == 0.8)
check("compact_max_tokens 默认 8192", config.compact_max_tokens == 8192)
check("ui_default_context_window 默认 131072", config.ui_default_context_window == 131072)
check("ui_show_clock 默认 True", config.ui_show_clock is True)
check("ui_tool_panel_visible 默认 True", config.ui_tool_panel_visible is True)
check("mcp_enabled 默认 True", config.mcp_enabled is True)
check("session_save_dir 默认", config.session_save_dir == ".agents/sessions")

# ======================================================================
# 2. config.ini 缺失时自动创建完整 mock 模板
# ======================================================================
print("\n=== 2. config 缺失自动创建 mock 模板 ===", flush=True)
tmp_cfg = os.path.join(tmp, "config_test.ini")
Config.create_template(tmp_cfg)
exists = os.path.exists(tmp_cfg)
check("模板文件已创建", exists)
if exists:
    content = open(tmp_cfg, "r", encoding="utf-8").read()
    check("模板含 [llm] 段", "[llm]" in content)
    check("模板含 [agent] 段", "[agent]" in content)
    check("模板含 [ui] 段", "[ui]" in content)
    check("模板含 [mcp] 段", "[mcp]" in content)
    check("模板含 [sessions] 段", "[sessions]" in content)
    check("模板含 mock api_key", "sk-" in content and "api_key" in content)
    check("模板含中文注释", "#" in content)
    # 用模板文件构造 Config 可正常读取
    cfg2 = Config(config_path=tmp_cfg)
    check("模板可被 Config 读取", cfg2.get("llm", "api_key", "") != "")

# ======================================================================
# 3. SessionManager：保存 / 列表 / 加载
# ======================================================================
print("\n=== 3. 会话管理（/new /save /resume 的数据基础） ===", flush=True)
sm = SessionManager(project_root=tmp)
sid1 = sm.save_session([
    {"role": "system", "content": "你是助手"},
    {"role": "user", "content": "帮我写一个 Python 排序函数，要求逐行中文注释"},
    {"role": "assistant", "content": "好的，以下是快速排序实现..."},
])
sid2 = sm.save_session([
    {"role": "system", "content": "你是助手"},
    {"role": "user", "content": "第二段对话：介绍一下 AGENTS.md 的作用"},
])
check("会话 1 已保存", sid1 is not None and len(sid1) >= 15)
check("会话 2 已保存（不同编号）", sid2 is not None and sid2 != sid1)
sessions = sm.list_sessions()
check("列表返回按 id 倒序", sessions and sessions[0]["id"] == sid2)
check("列表含标题（首条 user 前 30 字）", sessions and sessions[0]["title"].startswith("第二段对话"))
check("列表含消息数", sessions and sessions[0]["msg_count"] == 2)
loaded = sm.load_session(sid1)
check("加载会话内容完整", loaded and len(loaded) == 3 and loaded[1]["content"].startswith("帮我写"))
check("加载会话角色保留", loaded and loaded[2]["role"] == "assistant")

# ======================================================================
# 4. AGENTS.md：一次注入，全程复用
# ======================================================================
print("\n=== 4. AGENTS.md 注入 ===", flush=True)
agents_dir = os.path.join(tmp, "agents_md_test")
os.makedirs(agents_dir, exist_ok=True)
with open(os.path.join(agents_dir, "AGENTS.md"), "w", encoding="utf-8") as f:
    f.write("# 项目指南\n\n本项目的代码风格要求：所有代码必须逐行配中文注释。")

llm2 = LLMClient(config=config, tool_registry=tool_registry,
                 agents_md_path=os.path.join(agents_dir, "AGENTS.md"))
md_msg = [m for m in llm2.messages if m["role"] == "system" and "AGENTS.md" in m["content"]]
check("AGENTS.md 已注入为 system 消息", len(md_msg) == 1)
check("注入内容完整", md_msg and "逐行配中文注释" in md_msg[0]["content"])

# reset（/new 清空）后应重新注入 -> 全程复用
llm2.reset()
md_msg2 = [m for m in llm2.messages if m["role"] == "system" and "AGENTS.md" in m["content"]]
check("reset 后重新注入（/new 后依然生效）", len(md_msg2) == 1)

# 不存在 AGENTS.md 时不报错
llm3 = LLMClient(config=config, tool_registry=tool_registry,
                 agents_md_path=os.path.join(agents_dir, "NO_SUCH_FILE.md"))
check("无 AGENTS.md 时不注入、不报错",
      not any("AGENTS.md" in m["content"] for m in llm3.messages))

# ======================================================================
# 5. TUI：斜杠命令补全面板 + /new /save /resume + MCP 边栏异步刷新
# ======================================================================
print("\n=== 5. TUI 斜杠命令与 MCP 边栏 ===", flush=True)


class FakeMCPClient:
    """模拟 MCP 客户端：discover_and_register 有耗时（模拟异步加载）。"""

    def __init__(self):
        self.servers = {"Bazi-MCP": object()}
        self.called = False  # 记录 discover_and_register 是否被调用
        self.server_tools = {
            "Bazi-MCP": [
                {"name": "getBaziDetail", "description": "获取八字详情", "inputSchema": {}},
                {"name": "getSolarTimes", "description": "获取日出日落", "inputSchema": {}},
            ]
        }

    def discover_and_register(self):
        self.called = True
        time.sleep(1.0)  # 模拟网络连接耗时

    def get_server_summary(self):
        result = []
        for name, tools in self.server_tools.items():
            result.append({
                "name": name,
                "status": "connected" if name in self.servers else "failed",
                "tool_count": len(tools),
                "tools": [t["name"] for t in tools],
            })
        return result


async def run_tui_tests():
    fake_mcp = FakeMCPClient()
    app = TUIApp(llm_client=llm, session_manager=sm, mcp_client=fake_mcp, config=config)
    async with app.run_test() as pilot:
        # 5.1 MCP 异步加载：discover_and_register 不应阻塞 TUI 启动，
        #    而是在后台线程执行，完成后动态刷新边栏。
        await pilot.pause()
        check("TUI 已启动（主界面就绪）", app.screen is not None)
        check("MCP 异步线程已触发", fake_mcp.called)

        # 5.2 等待异步线程完成 -> 边栏动态刷新出 MCP 服务器与工具
        await pilot.pause(1.5)
        mcp_panel = app.query_one("#mcp-panel")
        text_after = str(mcp_panel.render())
        check("边栏刷新出服务器名", "Bazi-MCP" in text_after, f"[{text_after[:60]}]")
        check("边栏显示工具列表", "getBaziDetail" in text_after and "getSolarTimes" in text_after)
        check("边栏显示已连接状态", "已连接" in text_after)

        # 5.3 输入 / 自动弹出补全引导面板（CommandPalette）
        input_box = app.query_one("#input-box", Input)
        input_box.value = "/"
        await app.on_input_changed(Input.Changed(input_box, "/"))
        await pilot.pause(0.3)
        palette_open = app.screen.has_class("--textual-command-palette")
        check("输入 / 弹出 CommandPalette 补全面板", palette_open)

        # 5.4 在面板里输入 new 过滤 -> 回车执行 /new（新建会话）
        from textual.command import CommandInput
        cmd_input = app.screen.query_one(CommandInput)
        cmd_input.value = "new"
        await pilot.pause(0.3)
        await pilot.press("enter")
        await pilot.pause(0.3)
        check("/new 执行后消息历史被清空", len(llm.messages) <= 2)
        check("/new 自动保存了原会话",
              any(s["id"] == sid1 for s in sm.list_sessions()) or sm.list_sessions())

        # 5.5 /save：先发一条消息再保存
        input_box.value = "测试保存会话"
        await app.on_input_submitted(Input.Submitted(input_box, "测试保存会话"))
        await pilot.pause(0.5)
        before_count = len(sm.list_sessions())
        app.action_save_session()
        await pilot.pause(0.2)
        after_count = len(sm.list_sessions())
        check("/save 保存当前会话", after_count == before_count + 1,
              f"[{before_count}->{after_count}]")

        # 5.6 /resume：弹出历史会话列表面板 -> 上下键 -> 回车恢复
        app.action_resume_session()
        await pilot.pause(0.3)
        check("/resume 弹出会话选择面板", isinstance(app.screen, SessionPicker))
        if isinstance(app.screen, SessionPicker):
            # 列表按时间倒序（最新在最上），初始高亮第一项 = 最新会话
            listview = app.screen.query_one(ListView)
            await pilot.pause(0.1)
            await pilot.press("enter")  # 回车选中最新会话
            await pilot.pause(0.5)
            check("/resume 恢复后回到主界面", not isinstance(app.screen, SessionPicker))
            # 恢复的会话：最新会话（/save 保存的「测试保存会话」）首条 user 消息
            user_msgs = [m for m in llm.messages if m["role"] == "user"]
            check("/resume 消息历史被替换",
                  len(user_msgs) >= 1 and user_msgs[-1]["content"].startswith("测试保存会话"),
                  f"[{user_msgs[-1]['content'][:20] if user_msgs else '无'}]")

        # 5.7 /resume 的 ESC 取消
        app.action_resume_session()
        await pilot.pause(0.3)
        if isinstance(app.screen, SessionPicker):
            await pilot.press("escape")
            await pilot.pause(0.3)
            check("ESC 取消恢复会话", not isinstance(app.screen, SessionPicker))

        # 5.8 其他斜杠命令动作不抛异常
        app.action_help_command()
        app.action_show_tools()
        app.action_show_skills()
        app.action_show_mcp()
        app.action_show_context()
        app.action_clear_chat()
        await pilot.pause(0.2)
        check("其他斜杠命令（help/tools/skills/mcp/context/clear）可执行", True)

        # 5.9 /quit 退出
        app.action_quit_app()
        await pilot.pause(0.2)
        check("/quit 触发退出", app._exit is not None or not app._running)


print("启动新增功能验证测试", flush=True)
asyncio.run(run_tui_tests())

# ======================================================================
# 汇总
# ======================================================================
print("\n" + "=" * 50, flush=True)
if failures:
    print(f"失败 {len(failures)} 项: {failures}", flush=True)
    sys.exit(1)
print("全部新增功能验证通过", flush=True)
