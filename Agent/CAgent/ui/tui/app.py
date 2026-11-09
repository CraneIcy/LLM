"""
Textual TUI 界面：极简现代风格聊天窗口（GitHub Dark 深色商业风）。

功能总览：
- 左侧边栏：MCP 服务器与工具列表（异步加载，界面先启动、边栏后刷新）
- 中间：聊天区 + 输入框
- 右侧：工具调用日志面板
- 斜杠命令（输入 / 自动弹出 CommandPalette 补全引导面板）：
    /new     新建会话（自动保存当前会话历史）
    /resume  从历史会话列表中选择并恢复（上下键选择、回车恢复、ESC 取消）
    /save    保存当前会话
    /quit    退出 CAgent
    /compact 手动触发上下文压缩
    /help    显示帮助
    /clear   清空当前对话
    /tools   查看已注册工具
    /skills  查看可用技能
    /mcp     查看 MCP 服务器与工具
    /context 查看上下文占用状态
- 状态栏：当前上下文 k / 窗口 k（占用百分比）+ 工具数 + 状态提示
"""

import threading

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, ScrollableContainer, Container
from textual.widgets import Header, Footer, Input, RichLog, Static, Label, ListView, ListItem
from textual.binding import Binding
from textual.command import Provider, Hit, Hits
from textual.screen import Screen, ModalScreen

from ui.base import BaseUI
from core.llm_client import LLMClient
from core.config import Config
from core.context_manager import DEFAULT_CONTEXT_WINDOW
from core.session_manager import SessionManager
from core.mcp_client import MCPClient
from core.tools.mcp_tool import MCPToolAdapter


class UserBubble(Static):
    """用户消息：靠右，柔和蓝色背景，无边框。"""

    def __init__(self, text: str, **kwargs):
        content = f"[#94a3b8]你 ›[/]\n[#f1f5f9]{text}[/]"
        super().__init__(content, classes="user-msg", **kwargs)


class AssistantBubble(Static):
    """助手消息：靠左，无背景，品牌色标识。"""

    def __init__(self, text: str = "", **kwargs):
        self.full_text = text
        content = f"[#22d3ee]CAgent ›[/]\n[#e2e8f0]{text}[/]" if text else "[#22d3ee]CAgent ›[/]"
        super().__init__(content, classes="assistant-msg", **kwargs)

    def append_text(self, token: str):
        self.full_text += token
        self.update(
            f"[#22d3ee]CAgent ›[/]\n[#e2e8f0]{self.full_text}[/]"
        )


class ToolLogPanel(RichLog):
    """工具日志侧边栏。"""

    def on_mount(self):
        self.write("[dim]─ 工具调用 ─[/dim]")


class SessionPicker(Screen):
    """
    历史会话选择面板（/resume 使用）。
    交互：上下键选择、回车选中并恢复、ESC 取消。
    选择结果通过 dismiss(session_id) 返回给调用方。
    """

    BINDINGS = [Binding("escape", "cancel", "取消")]

    def __init__(self, sessions: list, **kwargs):
        super().__init__(**kwargs)
        self.sessions = sessions  # SessionManager.list_sessions() 的结果

    def compose(self) -> ComposeResult:
        yield Header("恢复历史会话（上下键选择，回车恢复，ESC 取消）")
        with Vertical(id="session-list"):
            # 会话列表：方向键选择、回车恢复、ESC 取消
            with ListView(id="session-listview"):
                for s in self.sessions:
                    # 每条会话显示：标题 + 时间 + 消息数
                    # 注意：Textual 的 widget id 不能以数字开头，因此加 item- 前缀
                    yield ListItem(
                        Label(
                            f"[#58a6ff]●[/] [bold]{s['title']}[/bold]  "
                            f"[dim]{s['created_at']} · {s['msg_count']} 条消息 · {s['id']}[/dim]"
                        ),
                        id=f"item-{s['id']}",
                    )

    def on_mount(self):
        """面板打开后自动聚焦会话列表，保证方向键 / 回车 / ESC 可用。"""
        self.query_one(ListView).focus()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """回车 / 点击选中：把会话编号返回给调用方。"""
        item_id = event.item.id if event.item else None
        # 去掉 item- 前缀，还原成真实会话编号（YYYYMMDD-HHMMSS）
        if item_id and item_id.startswith("item-"):
            item_id = item_id[len("item-"):]
        self.dismiss(item_id)

    def action_cancel(self) -> None:
        """ESC 取消：返回 None，不恢复任何会话。"""
        self.dismiss(None)


class ConfigWarningScreen(ModalScreen):
    """
    config.ini 缺失时的提示弹窗。
    程序已自动生成一份 mock 模板，用户需修改 api_key 等配置后重启才能正常工作。
    """

    BINDINGS = [Binding("escape", "dismiss_ok", "知道了")]

    def compose(self) -> ComposeResult:
        yield Static(
            "[#f85149]⚠ 缺少配置文件[/#f85149]\n\n"
            "[bold]未找到 .config.ini[/bold]，已自动生成一份模板文件：\n"
            "[#58a6ff].config.ini[/#58a6ff]\n\n"
            "当前使用的是模板中的 [bold]示例（mock）配置[/bold]，"
            "LLM 调用无法正常工作。\n\n"
            "请按以下步骤操作：\n"
            "  1. 打开项目目录下的 [bold].config.ini[/bold]\n"
            "  2. 将 [bold][llm] api_key[/bold] 修改为你自己的真实 API Key\n"
            "  3. 按需调整模型、地址等参数\n"
            "  4. 保存后重新启动 CAgent\n\n"
            "[dim]按 ESC 或回车继续[/dim]",
            id="config-warning",
        )

    def action_dismiss_ok(self) -> None:
        """用户确认提示后关闭弹窗。"""
        self.dismiss()


class SlashCommandProvider(Provider):
    """
    斜杠命令提供者：CommandPalette 补全引导面板的数据源。
    打开面板后按名称/帮助文本模糊匹配；未输入时展示全部命令。
    """

    # 命令列表：(显示名, App 动作方法名, 帮助文本)
    COMMAND_ITEMS = [
        ("新会话 /new", "action_new_session", "保存当前会话并开始新会话"),
        ("恢复会话 /resume", "action_resume_session", "从历史会话列表中选择并恢复"),
        ("保存会话 /save", "action_save_session", "保存当前会话到 .agents/sessions"),
        ("压缩上下文 /compact", "action_compact_command", "归档并压缩上下文（约5000 Token 摘要）"),
        ("清空对话 /clear", "action_clear_chat", "清空当前对话历史"),
        ("帮助 /help", "action_help_command", "显示可用命令与快捷键"),
        ("查看工具 /tools", "action_show_tools", "显示当前已注册的工具列表"),
        ("查看技能 /skills", "action_show_skills", "显示当前可用的技能列表"),
        ("查看 MCP /mcp", "action_show_mcp", "显示已连接的 MCP 服务器与工具"),
        ("查看上下文 /context", "action_show_context", "显示当前上下文占用状态"),
        ("退出 /quit", "action_quit_app", "退出 CAgent"),
    ]

    async def search(self, query: str) -> Hits:
        """用户输入时按关键词模糊匹配命令。"""
        matcher = self.matcher(query)
        for name, action, help_text in self.COMMAND_ITEMS:
            score = matcher.match(name)
            if score:
                yield Hit(
                    score,
                    name,
                    lambda a=action: getattr(self.app, a)(),
                    help_text,
                )

    async def discover(self) -> Hits:
        """打开面板（未输入）时展示全部命令。"""
        for name, action, help_text in self.COMMAND_ITEMS:
            yield Hit(
                0,
                name,
                lambda a=action: getattr(self.app, a)(),
                help_text,
            )


class TUIApp(App):
    """极简现代风 TUI 应用。"""

    CSS = """
    Screen {
        background: #0d1117;
    }

    Header {
        background: #161b22;
        color: #58a6ff;
        text-style: bold;
    }

    Footer {
        background: #161b22;
        color: #8b949e;
    }

    #main-row {
        height: 1fr;
    }

    /* 左侧边栏：MCP 服务器与工具 */
    #sidebar {
        width: 26%;
        background: #161b22;
        border-right: solid #30363d;
        padding: 1;
    }

    #sidebar Label {
        width: 100%;
    }

    #mcp-panel {
        height: auto;
        color: #c9d1d9;
    }

    #sidebar-info {
        height: auto;
        color: #8b949e;
        margin-top: 1;
    }

    #chat-area {
        width: 1fr;
        padding: 1 3;
    }

    /* 用户消息：靠右对齐 */
    .user-msg {
        padding: 0 2;
        margin: 1 0 1 25;
        background: #1f6feb33;
        border-left: thick #58a6ff;
    }

    /* 助手消息：靠左对齐，无边框 */
    .assistant-msg {
        padding: 0 2;
        margin: 1 25 1 0;
    }

    /* 系统提示消息（如 /new /save 结果、会话恢复提示） */
    .system-note {
        padding: 0 2;
        margin: 1 0;
        color: #8b949e;
        border-left: thick #30363d;
    }

    #input-row {
        height: 4;
        padding: 0 3 1 3;
    }

    #input-box {
        background: #161b22;
        color: #f0f6fc;
        border: solid #30363d;
        padding: 0 1;
    }

    #input-box:focus {
        border: solid #58a6ff;
    }

    /* 输入锁定状态：红色边框 + 暗淡文字，提示需要 /compact */
    #input-box.disabled {
        border: solid #f85149;
        color: #8b949e;
    }

    #tool-panel {
        width: 30%;
        background: #161b22;
        border-left: solid #30363d;
        padding: 1;
    }

    #status-line {
        height: 1;
        background: #0d1117;
        color: #484f58;
        padding: 0 3;
    }

    /* /resume 会话选择面板样式 */
    #session-list {
        padding: 1 3;
    }

    #session-list ListView {
        background: #161b22;
        border: solid #30363d;
    }

    #session-list ListItem {
        padding: 1 2;
    }

    #session-list ListItem.--highlight {
        background: #1f6feb44;
    }

    /* config 缺失提示弹窗样式 */
    #config-warning {
        width: 60;
        height: auto;
        background: #161b22;
        border: thick #f85149;
        padding: 2 3;
        color: #c9d1d9;
        margin: 8 10;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "退出"),
        Binding("ctrl+r", "reset_chat", "清空对话"),
        Binding("ctrl+l", "toggle_log", "切换日志"),
    ]

    # ------------------------------------------------------------------
    # 斜杠命令数据源（CommandPalette 补全引导面板）
    # ------------------------------------------------------------------
    COMMANDS = [SlashCommandProvider]

    def __init__(
        self,
        llm_client: LLMClient,
        session_manager: SessionManager = None,
        mcp_client: MCPClient = None,
        config: Config = None,
        config_warning: bool = False,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.llm_client = llm_client
        self.session_manager = session_manager
        self.mcp_client = mcp_client
        self.config = config
        self.config_warning = config_warning
        self._current_msg = None
        self._log_visible = True
        self._compacting = False  # 本界面是否正在执行压缩（避免并发触发）
        self._palette_open = False  # CommandPalette 是否已打开（避免重复触发）

    def compose(self) -> ComposeResult:
        # 顶部标题栏：显示时钟与否可由 config.ini [ui] show_clock 配置
        show_clock = self.config.ui_show_clock if self.config else True
        yield Header(show_clock=show_clock)

        with Horizontal(id="main-row"):
            # 左侧边栏：MCP 服务器与工具（异步加载后刷新）
            with Vertical(id="sidebar"):
                yield Label("[bold]# MCP 服务器[/bold]")
                yield Static("加载中...", id="mcp-panel")
                yield Static("", id="sidebar-info")

            # 中间：聊天区 + 输入框
            with Vertical():
                yield ScrollableContainer(id="chat-area")
                yield Container(
                    Input(placeholder=" 输入消息，回车发送... / 输入斜杠命令", id="input-box"),
                    id="input-row",
                )

            # 右侧：工具调用日志面板（初始可见性可由配置控制）
            yield ToolLogPanel(id="tool-panel", highlight=True)

        yield Label("", id="status-line")
        yield Footer()

    def on_mount(self):
        self.query_one("#input-box", Input).focus()
        self._update_status_line()
        self._refresh_sidebar()

        # 右侧工具面板初始可见性：config.ini [ui] tool_panel_visible
        if self.config and not self.config.ui_tool_panel_visible:
            panel = self.query_one("#tool-panel", ToolLogPanel)
            panel.display = False
            self._log_visible = False

        # 异步加载 MCP（界面先启动，边栏随后动态刷新）
        if self.mcp_client and (not self.config or self.config.mcp_enabled):
            threading.Thread(target=self._load_mcp_async, daemon=True).start()

        # config.ini 缺失时：弹出提示弹窗
        if self.config_warning:
            self.call_after_refresh(self._show_config_warning)

    # ------------------------------------------------------------------
    # config.ini 缺失提示
    # ------------------------------------------------------------------
    def _show_config_warning(self):
        """弹出「缺少配置」提示弹窗。"""
        self.push_screen(ConfigWarningScreen())

    # ------------------------------------------------------------------
    # MCP 异步加载
    # ------------------------------------------------------------------
    def _load_mcp_async(self):
        """
        后台线程：连接 MCP 服务器、发现工具并注册到共享工具注册表。
        完成后通过 call_from_thread 回主线程刷新边栏与状态栏。
        """
        try:
            self.mcp_client.discover_and_register()
            # 动态注册 MCP 工具（统一参与 Agent 的工具调用流程）
            for server_name, tools in self.mcp_client.server_tools.items():
                for tool in tools:
                    exposed_name = f"{server_name}__{tool['name']}"
                    adapter = MCPToolAdapter(
                        mcp_client=self.mcp_client,
                        exposed_name=exposed_name,
                        server_name=server_name,
                        original_name=tool["name"],
                        description=tool["description"],
                        input_schema=tool["inputSchema"],
                    )
                    self.llm_client.tool_registry.register(adapter)
        except Exception as e:
            print(f"[MCP] 异步加载失败: {e}")
        finally:
            # 跨线程回到 UI 线程刷新界面
            self.call_from_thread(self._refresh_sidebar)
            self.call_from_thread(self._update_status_line)

    # ------------------------------------------------------------------
    # 边栏刷新
    # ------------------------------------------------------------------
    def _refresh_sidebar(self):
        """刷新左侧边栏：MCP 服务器 + 工具 / 技能统计。"""
        mcp_panel = self.query_one("#mcp-panel", Static)

        lines = []
        if not self.mcp_client:
            lines.append("[dim]未启用 MCP[/dim]")
        else:
            summary = self.mcp_client.get_server_summary()
            if not summary:
                lines.append("[dim]未发现 MCP 服务器[/dim]")
                lines.append("[dim]（检查项目目录 .mcp.json）[/dim]")
            else:
                for s in summary:
                    # 服务器行：名称 + 状态 + 工具数
                    if s["status"] == "connected":
                        status_text = f"[#3fb950]● 已连接[/#3fb950]"
                    else:
                        status_text = f"[#f85149]● 连接失败[/#f85149]"
                    lines.append(f"[bold]{s['name']}[/bold]  {status_text}")
                    lines.append(f"[dim]  {s['tool_count']} 个工具[/dim]")
                    # 每个工具一行（缩进显示）
                    for tool_name in s["tools"]:
                        lines.append(f"  [dim]↳ {tool_name}[/dim]")
                    lines.append("")

        mcp_panel.update("\n".join(lines) if lines else "[dim]（无）[/dim]")

        # 边栏下方：内置工具 / 技能统计
        info = self.query_one("#sidebar-info", Static)
        tool_count = len(self.llm_client.tool_registry.get_tools_schema())
        skill_count = len(self.llm_client.skill_loader.list_skills()) if self.llm_client.skill_loader else 0
        info.update(
            f"[dim]内置+动态工具: {tool_count}\n可用技能: {skill_count}[/dim]"
        )

    # ------------------------------------------------------------------
    # 状态栏：当前上下文 k / 窗口 k（百分比）
    # ------------------------------------------------------------------
    def _update_status_line(self):
        """更新底部状态栏：模型名 + 上下文占用 + 工具数 + 状态提示。"""
        tool_count = len(self.llm_client.tool_registry.get_tools_schema())
        status = self.llm_client.get_context_status()

        # 格式化上下文占用（:g 自动去掉多余的 .0，如 128.0 -> 128）
        usage_k = f"{status['usage_tokens'] / 1024:g}"
        window_k = f"{status['display_window'] / 1024:g}"
        percent = int(status["ratio"] * 100)

        # 窗口未知（window_tokens == 0）时显示默认窗口并标注「默认」
        if status["window_tokens"] == 0:
            window_part = f"{window_k}k 默认"
        else:
            window_part = f"{window_k}k"

        ctx_part = f"上下文 {usage_k}k / {window_part}（{percent}%）"

        # 模型名：从配置读取（不再硬编码）
        model_name = self.config.model if self.config else "DeepSeek Chat"

        # 状态着色：ok=灰，warn=黄，blocked=红；压缩中显示特殊标记
        state = status.get("state", "ok")
        if status.get("compacting"):
            color = "#d29922"
            state_text = "压缩中..."
        elif state == "blocked":
            color = "#f85149"
            state_text = "上下文已满，请执行 /compact"
        elif state == "warn":
            color = "#d29922"
            state_text = "上下文≥80%，建议执行 /compact"
        else:
            color = "#484f58"
            state_text = ""

        tool_part = f"{tool_count} 个工具可用"
        hint = "输入 / 查看斜杠命令 · Ctrl+R 清空对话"

        label = self.query_one("#status-line", Label)
        if state_text:
            label.update(
                f"● {model_name}  ·  {ctx_part}  ·  {tool_part}  ·  "
                f"[{color}]{state_text}[/]  ·  {hint}"
            )
        else:
            label.update(
                f"● {model_name}  ·  {ctx_part}  ·  {tool_part}  ·  {hint}"
            )

        # 根据输入锁定状态更新提示文案（注意：不能禁用输入框，
        # 否则用户无法输入 /compact 解锁——锁定只拦截普通消息）
        input_box = self.query_one("#input-box", Input)
        if status.get("input_blocked") and not status.get("compacting"):
            input_box.placeholder = " 上下文已满，请仅输入 /compact 压缩上下文后继续对话... "
            if not input_box.has_class("disabled"):
                input_box.add_class("disabled")
        else:
            input_box.placeholder = " 输入消息，回车发送... / 输入斜杠命令 "
            if input_box.has_class("disabled"):
                input_box.remove_class("disabled")

    # ------------------------------------------------------------------
    # 斜杠命令触发：输入 / 自动弹出补全引导面板
    # ------------------------------------------------------------------
    async def on_input_changed(self, event: Input.Changed):
        """输入框内容变化时，若以 / 开头则弹出 CommandPalette 引导面板。"""
        if not self._palette_open and event.value.strip().startswith("/"):
            self._palette_open = True
            # 清空输入框，避免 "/" 作为普通消息被提交
            self.query_one("#input-box", Input).value = ""
            self.action_command_palette()

    def on_command_palette_closed(self, event):
        """CommandPalette 关闭（执行命令或 ESC 取消）后复位标志。"""
        self._palette_open = False

    # ------------------------------------------------------------------
    # 输入处理
    # ------------------------------------------------------------------
    async def on_input_submitted(self, event: Input.Submitted):
        user_text = event.value.strip()
        if not user_text:
            return

        # /compact 命令：手动触发上下文压缩（任何状态下都允许，兜底路径）
        if user_text == "/compact":
            self.query_one("#input-box", Input).value = ""
            self._run_compact()
            return

        # 上下文已满时：暂停接受普通提示词，只允许 /compact
        status = self.llm_client.get_context_status()
        if status.get("input_blocked"):
            self.query_one("#input-box", Input).value = ""
            tool_log = self.query_one("#tool-panel", ToolLogPanel)
            tool_log.write(
                "[#f85149]✗ 上下文使用量已达 80%，请先输入 /compact 完成压缩[/#f85149]"
            )
            return

        self.query_one("#input-box", Input).value = ""
        chat = self.query_one("#chat-area", ScrollableContainer)

        await chat.mount(UserBubble(user_text))

        self._current_msg = AssistantBubble("")
        await chat.mount(self._current_msg)
        chat.scroll_end(animate=False)

        threading.Thread(
            target=self._run_llm,
            args=(user_text,),
            daemon=True,
        ).start()

    # ------------------------------------------------------------------
    # 斜杠命令动作
    # ------------------------------------------------------------------
    def action_new_session(self):
        """/new：保存当前会话 -> 清空 -> 重建 System Prompt，开始新会话。"""
        chat = self.query_one("#chat-area", ScrollableContainer)
        tool_log = self.query_one("#tool-panel", ToolLogPanel)

        saved_id = None
        if self.session_manager and self.llm_client.messages:
            saved_id = self.session_manager.save_session(self.llm_client.messages)

        self.llm_client.reset()  # 清空并重建 System Prompt + AGENTS.md
        chat.remove_children()
        tool_log.clear()
        tool_log.write("[dim]─ 工具调用 ─[/dim]")

        if saved_id:
            tool_log.write(f"[#3fb950]✓ 当前会话已保存: {saved_id}[/#3fb950]")
        chat.mount(
            Static("[dim]已开始新会话（原会话" + (f"保存为 {saved_id}" if saved_id else "为空未保存") + "）[/dim]", classes="system-note")
        )
        self._update_status_line()

    def action_save_session(self):
        """/save：保存当前会话到 .agents/sessions。"""
        tool_log = self.query_one("#tool-panel", ToolLogPanel)
        if not self.session_manager:
            tool_log.write("[#f85149]✗ 未配置会话管理器[/#f85149]")
            return
        if not self.llm_client.messages:
            tool_log.write("[dim]当前会话为空，无需保存[/dim]")
            return
        saved_id = self.session_manager.save_session(self.llm_client.messages)
        if saved_id:
            tool_log.write(f"[#3fb950]✓ 会话已保存: {saved_id}[/#3fb950]")
            self.notify(f"会话已保存: {saved_id}", timeout=4)
        else:
            tool_log.write("[#f85149]✗ 会话保存失败[/#f85149]")

    def action_resume_session(self):
        """/resume：弹出历史会话选择面板，选中后恢复。"""
        tool_log = self.query_one("#tool-panel", ToolLogPanel)
        if not self.session_manager:
            tool_log.write("[#f85149]✗ 未配置会话管理器[/#f85149]")
            return

        sessions = self.session_manager.list_sessions()
        if not sessions:
            tool_log.write("[dim]没有任何历史会话（.agents/sessions/ 为空）[/dim]")
            return

        # 弹出选择面板；回调接收 dismiss 返回的会话编号
        self.push_screen(SessionPicker(sessions), callback=self._on_session_picked)

    def _on_session_picked(self, session_id):
        """SessionPicker 回调：恢复选中的会话。"""
        tool_log = self.query_one("#tool-panel", ToolLogPanel)
        if not session_id:
            tool_log.write("[dim]已取消恢复会话[/dim]")
            return

        messages = self.session_manager.load_session(session_id)
        if not messages:
            tool_log.write(f"[#f85149]✗ 会话 {session_id} 加载失败或为空[/#f85149]")
            return

        # 恢复：替换 LLM 客户端的消息历史，并清空界面重新渲染
        self.llm_client.messages = messages
        self.llm_client._input_blocked = False
        if self.llm_client.context_manager:
            self.llm_client.context_manager.last_usage = None

        chat = self.query_one("#chat-area", ScrollableContainer)
        chat.remove_children()
        chat.mount(
            Static(
                f"[dim]已恢复会话 {session_id}（{len(messages)} 条消息）。"
                "输入消息继续对话，或 /compact 压缩上下文。[/dim]",
                classes="system-note",
            )
        )
        tool_log.write(f"[#3fb950]✓ 已恢复会话 {session_id}（{len(messages)} 条消息）[/#3fb950]")
        self._update_status_line()

    def action_quit_app(self):
        """/quit：退出 CAgent。"""
        self.exit()

    def action_help_command(self):
        """/help：在工具面板显示所有可用命令与快捷键。"""
        tool_log = self.query_one("#tool-panel", ToolLogPanel)
        tool_log.write("[#58a6ff]── 可用斜杠命令 ──[/#58a6ff]")
        tool_log.write("  /new      新建会话（自动保存当前历史）")
        tool_log.write("  /resume   恢复历史会话（面板选择）")
        tool_log.write("  /save     保存当前会话")
        tool_log.write("  /quit     退出 CAgent")
        tool_log.write("  /compact  压缩上下文（归档+摘要）")
        tool_log.write("  /clear    清空当前对话")
        tool_log.write("  /help     显示本帮助")
        tool_log.write("  /tools    查看已注册工具")
        tool_log.write("  /skills   查看可用技能")
        tool_log.write("  /mcp      查看 MCP 服务器")
        tool_log.write("  /context  查看上下文占用")
        tool_log.write("  [dim]快捷键: Ctrl+R 清空 · Ctrl+L 切换日志 · Ctrl+C 退出[/dim]")

    def action_show_tools(self):
        """/tools：列出当前已注册的所有工具。"""
        tool_log = self.query_one("#tool-panel", ToolLogPanel)
        tool_log.write("[#58a6ff]── 已注册工具 ──[/#58a6ff]")
        schemas = self.llm_client.tool_registry.get_tools_schema()
        for s in schemas:
            tool_log.write(f"  [bold]{s['function']['name']}[/bold]  "
                           f"[dim]{s['function'].get('description', '')[:60]}[/dim]")
        tool_log.write(f"[dim]共 {len(schemas)} 个工具[/dim]")

    def action_show_skills(self):
        """/skills：列出当前可用的 Skill。"""
        tool_log = self.query_one("#tool-panel", ToolLogPanel)
        tool_log.write("[#58a6ff]── 可用技能 ──[/#58a6ff]")
        if self.llm_client.skill_loader:
            skills = self.llm_client.skill_loader.list_skills()
            if skills:
                for s in skills:
                    tool_log.write(f"  [bold]{s.name}[/bold]  [dim]{s.description[:60]}[/dim]")
                tool_log.write(f"[dim]共 {len(skills)} 个技能，用 loadSkill 工具加载详情[/dim]")
            else:
                tool_log.write("[dim]没有可用技能（.agents/skills/ 为空）[/dim]")
        else:
            tool_log.write("[dim]未启用技能系统[/dim]")

    def action_show_mcp(self):
        """/mcp：在边栏输出 MCP 服务器摘要（并滚动到边栏）。"""
        self._refresh_sidebar()
        tool_log = self.query_one("#tool-panel", ToolLogPanel)
        tool_log.write("[#58a6ff]── MCP 服务器 ──[/#58a6ff]")
        if not self.mcp_client:
            tool_log.write("[dim]未启用 MCP[/dim]")
            return
        summary = self.mcp_client.get_server_summary()
        if not summary:
            tool_log.write("[dim]未发现 MCP 服务器（检查 .mcp.json）[/dim]")
            return
        for s in summary:
            status_text = "已连接" if s["status"] == "connected" else "连接失败"
            tool_log.write(f"  [bold]{s['name']}[/bold] [{status_text}] {s['tool_count']} 工具")
            for t in s["tools"]:
                tool_log.write(f"    ↳ {t}")

    def action_show_context(self):
        """/context：显示当前上下文占用详情。"""
        tool_log = self.query_one("#tool-panel", ToolLogPanel)
        status = self.llm_client.get_context_status()
        tool_log.write("[#58a6ff]── 上下文状态 ──[/#58a6ff]")
        tool_log.write(f"  已用: {status['usage_tokens']} Tokens")
        tool_log.write(f"  窗口: {status['display_window']} Tokens"
                       + ("（默认）" if status["window_tokens"] == 0 else ""))
        tool_log.write(f"  占用: {int(status['ratio'] * 100)}%")
        tool_log.write(f"  状态: {status['state']} · 压缩中: {status['compacting']} "
                       f"· 输入锁定: {status['input_blocked']}")

    def action_clear_chat(self):
        """/clear：清空当前对话（与 Ctrl+R 一致）。"""
        self.action_reset_chat()

    def action_compact_command(self):
        """/compact（经由 CommandPalette 触发）：手动压缩上下文。"""
        self._run_compact()

    # ------------------------------------------------------------------
    # /compact 压缩流程
    # ------------------------------------------------------------------
    def _run_compact(self):
        """在后台线程执行上下文压缩，并把进度输出到工具面板。"""
        if self._compacting:
            return  # 已在压缩中，忽略重复触发

        self._compacting = True
        tool_log = self.query_one("#tool-panel", ToolLogPanel)
        # 此处已在 app 线程，可直接写日志（不能 call_from_thread）
        tool_log.write("[#d29922]↻ 开始上下文压缩...[/#d29922]")
        self._update_status_line()

        def on_progress(msg: str):
            """压缩进度回调（运行在压缩线程，跨线程更新 UI）。"""
            def log():
                tool_log.write(msg)
                self._update_status_line()
            self.call_from_thread(log)

        def _do_compact():
            """压缩主流程（后台线程）。"""
            try:
                result = self.llm_client.compact(on_progress=on_progress)

                def show_result():
                    if result["success"]:
                        tool_log.write(
                            f"[#3fb950]✓ 压缩完成，归档 {result['archive_id']}[/#3fb950]"
                        )
                        tool_log.write(
                            "[dim]历史细节可用 recallContext 工具检索[/dim]"
                        )
                    else:
                        tool_log.write(
                            f"[#f85149]✗ 压缩失败: {result['error']}[/#f85149]"
                        )
                        tool_log.write("[dim]原有上下文已保留，可重试 /compact[/dim]")
                    self._update_status_line()
                self.call_from_thread(show_result)

            except Exception as e:
                def err():
                    tool_log.write(f"[#f85149]✗ 压缩异常: {e}[/#f85149]")
                self.call_from_thread(err)

            finally:
                self._compacting = False
                self.call_from_thread(self._update_status_line)

        threading.Thread(target=_do_compact, daemon=True).start()

    # ------------------------------------------------------------------
    # LLM 对话线程
    # ------------------------------------------------------------------
    def _run_llm(self, user_text: str):
        tool_log = self.query_one("#tool-panel", ToolLogPanel)

        def on_token(token: str):
            def update():
                if self._current_msg:
                    self._current_msg.append_text(token)
            self.call_from_thread(update)

        def on_tool_call(name: str, args: dict):
            def log():
                tool_log.write(f"[#58a6ff]→ {name}[/#58a6ff]")
                tool_log.write(f"  [dim italic]{args}[/dim italic]")
            self.call_from_thread(log)

        def on_tool_result(name: str, result: str):
            def log():
                preview = result[:120] + ("..." if len(result) > 120 else "")
                tool_log.write(f"[#3fb950]✓ {name}[/#3fb950]")
                tool_log.write(f"  [dim]{preview}[/dim]")
                tool_log.write("")
            self.call_from_thread(log)

        try:
            self.llm_client.chat(
                user_input=user_text,
                on_token=on_token,
                on_tool_call=on_tool_call,
                on_tool_result=on_tool_result,
            )
        except Exception as e:
            def err():
                tool_log.write(f"[#f85149]✗ {e}[/#f85149]")
            self.call_from_thread(err)
        finally:
            # 对话结束后刷新状态栏（上下文占用可能已变化）
            self.call_from_thread(self._update_status_line)

    def action_reset_chat(self):
        self.llm_client.reset()
        chat = self.query_one("#chat-area", ScrollableContainer)
        chat.remove_children()
        tool_log = self.query_one("#tool-panel", ToolLogPanel)
        tool_log.clear()
        tool_log.write("[dim]─ 工具调用 ─[/dim]")
        tool_log.write("[#3fb950]对话已清空[/#3fb950]")
        self._update_status_line()

    def action_toggle_log(self):
        panel = self.query_one("#tool-panel", ToolLogPanel)
        panel.display = not panel.display
        self._log_visible = panel.display


class TUIUI(BaseUI):
    """TUI 界面入口：把各组件组装进 TUIApp。"""

    def __init__(
        self,
        llm_client: LLMClient,
        session_manager: SessionManager = None,
        mcp_client: MCPClient = None,
        config: Config = None,
        config_warning: bool = False,
    ):
        super().__init__(llm_client)
        self.session_manager = session_manager
        self.mcp_client = mcp_client
        self.config = config
        self.config_warning = config_warning

    def run(self):
        TUIApp(
            llm_client=self.llm_client,
            session_manager=self.session_manager,
            mcp_client=self.mcp_client,
            config=self.config,
            config_warning=self.config_warning,
        ).run()
