"""
CAgent 图形界面（GUI）：基于 tkinter + ttkbootstrap 深色主题，商业化设计。

设计语言（GitHub Dark 精修）：
- #0d1117 主背景 / #161b22 面板 / #21262d 悬浮 / #30363d 分隔线 / #58a6ff 品牌蓝
- 顶部状态栏：产品名 + 模型徽章 + 上下文占用进度条 + 工具数徽章 + 压缩按钮
- 左侧栏：MCP 服务器列表 + 历史会话列表（一栏两用，双击恢复）
- 中间：圆角消息气泡聊天区 + 底部输入行（回车发送）
- 右侧栏：工具调用日志（固定宽度，grid + minsize 保证始终可见）
- 自绘组件：胶囊按钮（Pill，支持 hover）、迷你进度条（MiniBar）、圆角矩形
- 功能与 TUI 完全对齐：斜杠命令补全面板 / 历史会话恢复 / 上下文压缩 /
  AGENTS.md 注入 / MCP 异步加载 / config 缺失弹窗

教学要求：耗时操作放后台线程，界面更新回主线程（after(0, ...)）；逐行中文注释。
"""

import threading
import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox

import ttkbootstrap as ttkb

from core.llm_client import LLMClient
from core.config import Config
from core.session_manager import SessionManager
from core.mcp_client import MCPClient
from core.tools.mcp_tool import MCPToolAdapter
from ui.base import BaseUI

# ----------------------------------------------------------------------
# 配色（GitHub Dark 深色商业风）
# ----------------------------------------------------------------------
BG_MAIN = "#0d1117"        # 主背景（聊天区）
BG_PANEL = "#161b22"       # 面板背景（侧栏 / 日志）
BG_HOVER = "#21262d"       # 悬浮 / 内嵌
BORDER = "#30363d"         # 分隔线
FG_TEXT = "#e6edf3"        # 主文字
FG_DIM = "#8b949e"         # 次要文字
FG_MUTED = "#6e7681"       # 弱化文字
ACCENT = "#58a6ff"         # 品牌蓝
ACCENT_HOVER = "#79c0ff"   # 品牌蓝（悬浮）
ACCENT_DIM = "#1f6feb"     # 用户气泡背景
ACCENT_GREEN = "#3fb950"   # 成功 / 已连接
ACCENT_RED = "#f85149"     # 失败 / 锁定
ACCENT_YELLOW = "#d29922"  # 警告 / 压缩中
BUBBLE_AI_BG = "#21262d"   # 助手气泡背景
PAD_X = 14
PAD_Y = 9
CORNER = 14

FONT = ("Microsoft YaHei UI", 10)
FONT_SMALL = ("Microsoft YaHei UI", 9)
FONT_BOLD = ("Microsoft YaHei UI", 10, "bold")
FONT_TITLE = ("Microsoft YaHei UI", 12, "bold")


def round_rect(canvas, x1, y1, x2, y2, r, **kw):
    """在 Canvas 上绘制圆角矩形（smooth 折线模拟圆角）。"""
    pts = [
        x1 + r, y1,
        x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2,
        x1 + r, y2, x1, y2, x1, y2 - r,
        x1, y1 + r, x1, y1,
    ]
    return canvas.create_polygon(pts, smooth=True, **kw)


def est_text_width(text: str, font_size: int = 10) -> int:
    """估算文本像素宽度：中文按字号+4，其它按字号-2（不依赖字体测量，兼容 DPI）。"""
    w = 0
    for ch in text:
        if ord(ch) > 0x2E80:  # CJK 字符（中文等）
            w += font_size + 4
        elif ch == " ":
            w += font_size // 2
        else:
            w += font_size - 2
    return w


# ----------------------------------------------------------------------
# 自绘胶囊按钮（商业化质感：圆角、hover 反馈、选中态）
# ----------------------------------------------------------------------
class Pill(tk.Canvas):
    """
    圆角胶囊按钮 / 状态徽章。
    kind:
      - "primary"  : 品牌蓝底白字（主要动作，如发送 / 压缩）
      - "ghost"    : 透明底浅色字（次要动作，hover 变面板色）
      - "outline"  : 描边幽灵按钮（hover 变面板色）
    """

    def __init__(self, master, text="", command=None, kind="ghost",
                 fg=FG_TEXT, height=30, padx=16, font=FONT,
                 bg=None):
        self._text = text
        self._command = command
        self._kind = kind
        self._fg = fg
        self._font = font
        self._height = height
        self._padx = padx
        self._hover = False
        self._container_bg = bg if bg is not None else master["bg"]
        # 用字符估算宽度（避免字体测量在部分环境下返回异常值导致按钮塌缩成 1px）
        size = 10 if font[1] == 10 else (9 if font[1] == 9 else font[1])
        w = est_text_width(text, size) + 2 * padx
        w = max(w, height)  # 圆形胶囊最少是正方形
        super().__init__(
            master, width=w, height=height,
            bg=self._container_bg, highlightthickness=0, bd=0,
        )
        self._bg_item = None
        self._text_item = None
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)
        self._draw()

    # ---- 配色逻辑 ----
    def _colors(self):
        if self._kind == "primary":
            return {"bg": ACCENT, "fg": "#ffffff", "hover": ACCENT_HOVER}
        if self._kind == "outline":
            return {"bg": self._container_bg, "fg": self._fg, "hover": BG_HOVER}
        return {"bg": self._container_bg, "fg": self._fg, "hover": BG_HOVER}

    def _draw(self):
        c = self._colors()
        bg = c["hover"] if self._hover else c["bg"]
        w = int(self.cget("width"))
        h = int(self.cget("height"))
        if self._bg_item is not None:
            self.delete(self._bg_item)
        self._bg_item = round_rect(self, 1, 1, w - 1, h - 1, h // 2,
                                   fill=bg, outline=bg)
        if self._text_item is not None:
            self.delete(self._text_item)
        self._text_item = self.create_text(
            w // 2, h // 2, text=self._text, font=self._font, fill=c["fg"],
        )

    def _on_enter(self, _e):
        self._hover = True
        self._draw()

    def _on_leave(self, _e):
        self._hover = False
        self._draw()

    def _on_click(self, _e):
        if self._command:
            self._command()

    def get_text(self):
        return self._text


# ----------------------------------------------------------------------
# 迷你进度条（Canvas 圆角填充条）
# ----------------------------------------------------------------------
class MiniBar(tk.Canvas):
    """上下文占用进度条：底槽 + 圆角填充，颜色随状态变化。"""

    def __init__(self, master, width=150, height=8, bg=None):
        self._bar_w = width
        self._bar_h = height
        container = bg if bg is not None else master["bg"]
        super().__init__(
            master, width=width, height=height,
            bg=container, highlightthickness=0, bd=0,
        )
        self._fill = None
        self._pct = 0
        self._color = ACCENT
        # 底槽
        round_rect(self, 1, 1, width - 1, height - 1, height // 2,
                   fill=BG_HOVER, outline=BG_HOVER)

    def set(self, percent: float, color: str = None):
        """设置占用百分比与颜色。"""
        self._pct = max(0.0, min(100.0, percent))
        if color:
            self._color = color
        if self._fill is not None:
            self.delete(self._fill)
        w = max(self._bar_h, int(self._bar_w * self._pct / 100))
        self._fill = round_rect(
            self, 1, 1, w - 1, self._bar_h - 1,
            self._bar_h // 2, fill=self._color, outline=self._color,
        )


# ----------------------------------------------------------------------
# 圆角消息气泡
# ----------------------------------------------------------------------
class Bubble(tk.Canvas):
    """
    单条消息气泡：Canvas 画圆角矩形背景 + 自动换行文本。
    用户消息品牌蓝靠右（外层 Text justify=right），助手消息深灰靠左。
    """

    def __init__(self, master, text: str, sender: str, max_width: int):
        super().__init__(master, bg=BG_MAIN, highlightthickness=0, bd=0)
        self.max_width = max_width
        self.sender = sender
        if sender == "user":
            self._bg, self._fg = ACCENT_DIM, "#ffffff"
        else:
            self._bg, self._fg = BUBBLE_AI_BG, FG_TEXT

        wrap = max(120, max_width - 2 * PAD_X)
        self._text_item = self.create_text(
            PAD_X, PAD_Y, anchor="nw", text=text,
            width=wrap, font=FONT, fill=self._fg, justify="left",
        )
        self._bg_item = None
        self._relayout()

    def _relayout(self):
        bb = self.bbox(self._text_item)
        if bb is None:
            x1, y1, x2, y2 = 0, 0, 10, 22
        else:
            x1, y1, x2, y2 = bb
        w = (x2 - x1) + 2 * PAD_X
        h = (y2 - y1) + 2 * PAD_Y
        self.configure(width=w, height=h + 4)

        if self._bg_item is not None:
            self.delete(self._bg_item)
        self._bg_item = round_rect(
            self, PAD_X, PAD_Y, x2 + PAD_X, y2 + PAD_Y,
            CORNER, fill=self._bg, outline=self._bg,
        )
        self.tag_lower(self._bg_item, self._text_item)

    def append_text(self, token: str):
        cur = self.itemcget(self._text_item, "text")
        self.itemconfigure(self._text_item, text=cur + token)
        self._relayout()


# ----------------------------------------------------------------------
# 斜杠命令补全引导面板
# ----------------------------------------------------------------------
class CommandPalette(ttkb.Toplevel):
    """输入框以 "/" 开头时弹出；上下键选择、回车执行、ESC 取消。"""

    def __init__(self, gui, commands, x, y, width):
        super().__init__(gui)
        self.gui = gui
        self.commands = commands
        self.withdraw()
        self.overrideredirect(True)
        self.configure(bg=BG_PANEL, highlightthickness=1, highlightbackground=ACCENT)

        tk.Label(
            self, text="  斜杠命令", font=FONT_BOLD,
            background=BG_PANEL, foreground=ACCENT,
        ).pack(fill="x", pady=(6, 2))

        self.listbox = tk.Listbox(
            self, bg=BG_PANEL, fg=FG_TEXT, selectbackground=ACCENT_DIM,
            selectforeground="#ffffff", font=FONT, relief="flat",
            highlightthickness=0, borderwidth=0,
        )
        self.listbox.pack(fill="both", expand=True)
        self.listbox.bind("<Return>", lambda e: self._select())
        self.listbox.bind("<Double-Button-1>", lambda e: self._select())
        self.listbox.bind("<Escape>", lambda e: self._hide())
        self.bind("<FocusOut>", lambda e: self._hide())

        self.geometry(f"{max(360, width)}x240+{x}+{y}")
        self.deiconify()

    def update_filter(self, prefix: str):
        self.listbox.delete(0, "end")
        for cmd, name, help_text, _ in self.commands:
            if cmd.startswith("/" + prefix):
                self.listbox.insert("end", f"{cmd:<9} {name}  —  {help_text}")
        if self.listbox.size() > 0:
            self.listbox.selection_set(0)
            self.listbox.activate(0)

    def _select(self):
        if self.listbox.size() == 0:
            return
        sel = self.listbox.curselection()
        if not sel:
            return
        display = self.listbox.get(sel[0])
        cmd = display.split()[0]
        for c, _, _, action in self.commands:
            if c == cmd:
                getattr(self.gui, action)()
                break
        self._hide()

    def _hide(self):
        self.withdraw()
        self.gui.input_box.focus_set()


# ----------------------------------------------------------------------
# 历史会话选择面板（/resume）
# ----------------------------------------------------------------------
class SessionPickerDialog(ttkb.Toplevel):
    """历史会话列表：上下键选择、回车恢复、ESC 取消、双击恢复。"""

    def __init__(self, gui, sessions):
        super().__init__(gui)
        self.gui = gui
        self.title("恢复历史会话")
        self.geometry("720x440")
        self.configure(bg=BG_PANEL)
        self.transient(gui)

        tk.Label(
            self, text="  选择要恢复的历史会话（回车恢复，ESC 取消）",
            font=FONT_BOLD, background=BG_PANEL, foreground=ACCENT,
        ).pack(anchor="w", pady=(10, 6), padx=6)

        columns = ("time", "title", "count", "sid")
        self.tree = ttkb.Treeview(self, columns=columns, show="headings", height=14)
        self.tree.heading("time", text="保存时间")
        self.tree.heading("title", text="标题（首条消息）")
        self.tree.heading("count", text="消息数")
        self.tree.heading("sid", text="会话编号")
        self.tree.column("time", width=160, anchor="w")
        self.tree.column("title", width=320, anchor="w")
        self.tree.column("count", width=70, anchor="center")
        self.tree.column("sid", width=140, anchor="w")
        self.tree.pack(fill="both", expand=True, padx=6, pady=6)

        for s in sessions:
            self.tree.insert(
                "", "end", iid=s["id"],
                values=(s["created_at"], s["title"], s["msg_count"], s["id"]),
            )

        self.bind("<Return>", lambda e: self._pick())
        self.bind("<Escape>", lambda e: self._cancel())
        self.tree.bind("<Double-Button-1>", lambda e: self._pick())
        self.tree.focus_set()
        self.protocol("WM_DELETE_WINDOW", self._cancel)

    def _pick(self):
        sel = self.tree.selection()
        if not sel:
            return
        self.gui._on_session_picked(sel[0])
        self.destroy()

    def _cancel(self):
        self.gui.log_write("[已取消恢复会话]", "dim")
        self.destroy()


# ----------------------------------------------------------------------
# 主窗口
# ----------------------------------------------------------------------
class CAgentGUI(ttkb.Window):
    """CAgent 主图形界面窗口（商业化深色布局）。"""

    COMMANDS = [
        ("/new", "新会话", "保存当前会话并开始新会话", "action_new_session"),
        ("/resume", "恢复会话", "从历史会话列表中选择并恢复", "action_resume_session"),
        ("/save", "保存会话", "保存当前会话到 .agents/sessions", "action_save_session"),
        ("/compact", "压缩上下文", "归档并压缩上下文（约5000 Token 摘要）", "action_compact_command"),
        ("/clear", "清空对话", "清空当前对话历史", "action_clear_chat"),
        ("/help", "帮助", "显示可用命令与快捷键", "action_help_command"),
        ("/tools", "查看工具", "显示当前已注册的工具列表", "action_show_tools"),
        ("/skills", "查看技能", "显示当前可用的技能列表", "action_show_skills"),
        ("/mcp", "查看 MCP", "显示已连接的 MCP 服务器与工具", "action_show_mcp"),
        ("/context", "查看上下文", "显示当前上下文占用状态", "action_show_context"),
        ("/quit", "退出", "退出 CAgent", "action_quit_app"),
    ]

    def __init__(
        self,
        llm_client: LLMClient,
        session_manager: SessionManager = None,
        mcp_client: MCPClient = None,
        config: Config = None,
        config_warning: bool = False,
    ):
        super().__init__(
            title="CAgent · AI Agent 工作台",
            themename="darkly",
            size=(1280, 800),
            minsize=(1120, 660),
        )
        self.llm_client = llm_client
        self.session_manager = session_manager
        self.mcp_client = mcp_client
        self.config = config or Config(config_path=".config.ini")
        self.config_warning = config_warning
        self._current_bubble = None
        self._compacting = False
        self._palette = None

        self._build_ui()
        self.after_idle(self._on_startup)

    # ------------------------------------------------------------------
    # 界面构建（grid 布局，minsize 保证各栏宽度始终可见）
    # ------------------------------------------------------------------
    def _build_ui(self):
        self.configure(bg=BG_MAIN)
        self.style.configure(".", font=FONT)

        root = tk.Frame(self, bg=BG_MAIN)
        root.pack(fill="both", expand=True)

        # 根网格：第 0 列 = 左侧栏（固定 250），第 1 列 = 主区（伸缩）
        root.grid_columnconfigure(0, weight=0, minsize=250)
        root.grid_columnconfigure(1, weight=1)
        root.grid_rowconfigure(1, weight=1)

        # ---------- 左侧栏：MCP 服务器 + 历史会话 ----------
        sidebar = tk.Frame(root, bg=BG_PANEL, width=250)
        sidebar.grid(row=0, column=0, rowspan=2, sticky="nsew")
        # 注意：内部是 pack 布局，必须用 pack_propagate(False) 固定宽度，
        # 否则 pack 会按子组件（Text 默认 80 字符宽）把侧栏撑到近 900px
        sidebar.pack_propagate(False)

        # 左栏顶部：品牌区
        brand = tk.Frame(sidebar, bg=BG_PANEL)
        brand.pack(fill="x", pady=(14, 6), padx=14)
        tk.Label(brand, text="●", bg=BG_PANEL, fg=ACCENT,
                 font=FONT_TITLE).pack(side="left")
        tk.Label(brand, text="  CAgent", bg=BG_PANEL, fg=FG_TEXT,
                 font=FONT_TITLE).pack(side="left")

        # --- 分区 1：MCP 服务器 ---
        tk.Label(sidebar, text="服务器", bg=BG_PANEL, fg=FG_MUTED,
                 font=FONT_SMALL, anchor="w").pack(fill="x", padx=14, pady=(10, 2))
        self.mcp_text = tk.Text(
            sidebar, bg=BG_PANEL, fg=FG_TEXT, font=FONT_SMALL,
            relief="flat", borderwidth=0, state="disabled", wrap="word",
            width=27, height=5, padx=4, pady=2,
        )
        self.mcp_text.pack(fill="x", padx=10, pady=(0, 6))
        self.mcp_text.tag_configure("dim", foreground=FG_DIM)
        self.mcp_text.tag_configure("ok", foreground=ACCENT_GREEN)
        self.mcp_text.tag_configure("fail", foreground=ACCENT_RED)
        self.mcp_text.tag_configure("bold", foreground=FG_TEXT)

        # --- 分区 2：历史会话 ---
        tk.Label(sidebar, text="历史会话（双击恢复）", bg=BG_PANEL,
                 fg=FG_MUTED, font=FONT_SMALL, anchor="w").pack(
            fill="x", padx=14, pady=(10, 2))
        self.sessions_box = tk.Listbox(
            sidebar, bg=BG_HOVER, fg=FG_TEXT, font=FONT_SMALL,
            relief="flat", borderwidth=0, highlightthickness=0,
            selectbackground=ACCENT_DIM, selectforeground="#ffffff",
            activestyle="none", width=27,
        )
        self.sessions_box.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        self.sessions_box.bind("<Double-Button-1>", self._on_session_double)
        self._refresh_session_list()

        # 左栏底部：退出
        Pill(sidebar, text="退出", command=self.action_quit_app,
             kind="ghost", fg=FG_DIM, height=30).pack(side="bottom", padx=12, pady=10)

        # ---------- 主区 ----------
        main = tk.Frame(root, bg=BG_MAIN)
        main.grid(row=0, column=1, rowspan=2, sticky="nsew")
        main.grid_rowconfigure(1, weight=1)   # 内容行伸缩
        main.grid_columnconfigure(0, weight=1)

        self._build_topbar(main)
        self._build_content(main)

    # ------------------------------------------------------------------
    # 顶栏：产品名 + 状态徽章区
    # ------------------------------------------------------------------
    def _build_topbar(self, main):
        topbar = tk.Frame(main, bg=BG_MAIN)
        topbar.grid(row=0, column=0, sticky="ew", padx=20, pady=(12, 4))

        # 左侧：当前视图标题
        tk.Label(topbar, text="对话", bg=BG_MAIN, fg=FG_TEXT,
                 font=FONT_TITLE).pack(side="left")

        # 右侧：状态区
        right = tk.Frame(topbar, bg=BG_MAIN)
        right.pack(side="right")

        # 模型徽章
        self.model_pill = Pill(right, text="deepseek-chat", kind="outline",
                               fg=ACCENT, height=28, padx=14, font=FONT_SMALL)
        self.model_pill.pack(side="left", padx=(0, 8))

        # 上下文占用：文字 + 迷你进度条
        ctx_box = tk.Frame(right, bg=BG_MAIN)
        ctx_box.pack(side="left", padx=(0, 8))
        self.ctx_label = tk.Label(ctx_box, text="0k / 128k 默认",
                                  bg=BG_MAIN, fg=FG_DIM, font=FONT_SMALL)
        self.ctx_label.pack(side="left", padx=(0, 6))
        self.ctx_bar = MiniBar(ctx_box, width=150, height=8, bg=BG_MAIN)
        self.ctx_bar.pack(side="left")

        # 工具数徽章
        self.tool_pill = Pill(right, text="0 工具", kind="outline",
                              fg=FG_DIM, height=28, padx=14, font=FONT_SMALL)
        self.tool_pill.pack(side="left", padx=(0, 8))

        # 压缩按钮（primary 胶囊）
        self.compact_pill = Pill(right, text="压缩上下文", kind="primary",
                                 height=30, padx=18,
                                 command=self.action_compact_command)
        self.compact_pill.pack(side="left", padx=(0, 4))

        # 帮助按钮
        Pill(right, text="帮助", kind="ghost", fg=FG_DIM, height=30,
             command=self.action_help_command).pack(side="left")

    # ------------------------------------------------------------------
    # 内容区：左 MCP | 中聊天 | 右日志（grid + minsize 保证可见）
    # ------------------------------------------------------------------
    def _build_content(self, main):
        content = tk.Frame(main, bg=BG_MAIN)
        content.grid(row=1, column=0, sticky="nsew", padx=20, pady=(4, 12))
        # 三栏：中栏伸缩，左右栏固定且带最小宽度
        content.grid_columnconfigure(0, weight=0, minsize=210)
        content.grid_columnconfigure(1, weight=1, minsize=480)
        content.grid_columnconfigure(2, weight=0, minsize=290)
        content.grid_rowconfigure(0, weight=1)

        # ---- 左：MCP 详细边栏 ----
        mcp_panel = tk.Frame(content, bg=BG_PANEL, width=210)
        mcp_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        mcp_panel.pack_propagate(False)  # 固定宽度，防止被内部 Text 撑爆
        tk.Label(mcp_panel, text="MCP 服务器", bg=BG_PANEL, fg=ACCENT,
                 font=FONT_BOLD).pack(anchor="w", padx=12, pady=(10, 4))
        self.mcp_detail = tk.Text(
            mcp_panel, bg=BG_PANEL, fg=FG_TEXT, font=FONT_SMALL,
            relief="flat", borderwidth=0, state="disabled", wrap="word",
            width=24, padx=12, pady=4,
        )
        self.mcp_detail.pack(fill="both", expand=True)
        self.mcp_detail.tag_configure("dim", foreground=FG_DIM)
        self.mcp_detail.tag_configure("ok", foreground=ACCENT_GREEN)
        self.mcp_detail.tag_configure("fail", foreground=ACCENT_RED)
        self.mcp_detail.tag_configure("bold", foreground=FG_TEXT)

        # ---- 中：聊天区 + 输入行 ----
        chat_panel = tk.Frame(content, bg=BG_MAIN)
        chat_panel.grid(row=0, column=1, sticky="nsew", padx=(0, 10))
        chat_panel.grid_rowconfigure(0, weight=1)
        chat_panel.grid_columnconfigure(0, weight=1)

        self.chat_text = tk.Text(
            chat_panel, bg=BG_MAIN, fg=FG_TEXT, font=FONT,
            relief="flat", borderwidth=0, wrap="word", padx=10, pady=8,
            width=60,
        )
        self.chat_text.grid(row=0, column=0, sticky="nsew")
        self.chat_text.tag_configure("user", justify="right")
        self.chat_text.tag_configure("note", foreground=FG_DIM, font=FONT_SMALL)
        self.chat_text.tag_configure("accent", foreground=ACCENT, font=FONT_BOLD)

        # 输入行
        input_row = tk.Frame(chat_panel, bg=BG_MAIN)
        input_row.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        self.input_box = ttkb.Entry(input_row, font=FONT)
        self.input_box.pack(side="left", fill="x", expand=True, ipady=6)
        self.input_box.bind("<Return>", self._on_send)
        self.input_box.bind("<KeyRelease>", self._on_key_release)
        self.input_box.bind("<Escape>", lambda e: self._hide_palette())
        Pill(input_row, text="发送", kind="primary", height=36, padx=24,
             command=self._on_send_click).pack(side="left", padx=(10, 0))

        # ---- 右：工具日志 ----
        log_panel = tk.Frame(content, bg=BG_PANEL, width=290)
        log_panel.grid(row=0, column=2, sticky="nsew")
        log_panel.pack_propagate(False)  # 固定宽度，保证日志始终可读
        tk.Label(log_panel, text="工具调用日志", bg=BG_PANEL, fg=ACCENT,
                 font=FONT_BOLD).pack(anchor="w", padx=12, pady=(10, 4))
        self.log_text = tk.Text(
            log_panel, bg=BG_PANEL, fg=FG_DIM, font=FONT_SMALL,
            relief="flat", borderwidth=0, state="disabled", wrap="word",
            width=36, padx=12, pady=4,
        )
        self.log_text.pack(fill="both", expand=True, pady=(0, 10))
        self.log_text.tag_configure("dim", foreground=FG_DIM)
        self.log_text.tag_configure("ok", foreground=ACCENT_GREEN)
        self.log_text.tag_configure("warn", foreground=ACCENT_YELLOW)
        self.log_text.tag_configure("err", foreground=ACCENT_RED)
        self.log_text.tag_configure("accent", foreground=ACCENT)
        self.log_text.tag_configure("bold", foreground=FG_TEXT, font=FONT_BOLD)

        # 底部状态栏
        self.status_bar = tk.Label(
            main, text="", bg=BG_MAIN, fg=FG_MUTED, font=FONT_SMALL, anchor="w",
        )
        self.status_bar.grid(row=2, column=0, sticky="ew", padx=20, pady=(0, 8))

        # 初始化内容
        self.log_write("─ 工具调用日志 ─", "dim")
        self.log_write("工具调用 / 压缩进度 / 会话操作都会显示在这里", "dim")
        self._show_welcome()

    # ------------------------------------------------------------------
    # 历史会话列表（左栏）
    # ------------------------------------------------------------------
    def _refresh_session_list(self):
        """刷新左栏历史会话列表。"""
        self.sessions_box.delete(0, "end")
        if not self.session_manager:
            return
        sessions = self.session_manager.list_sessions()
        for s in sessions[:20]:
            self.sessions_box.insert(
                "end",
                f"{s['created_at']}  {s['title'][:14]}  [{s['msg_count']}]",
            )

    def _on_session_double(self, _e):
        """双击左栏会话：恢复选中会话。"""
        sel = self.sessions_box.curselection()
        if not sel or not self.session_manager:
            return
        sessions = self.session_manager.list_sessions()
        if sel[0] < len(sessions):
            self._on_session_picked(sessions[sel[0]]["id"])

    def _show_welcome(self):
        self.chat_note("● 直接输入消息与 AI 对话，回复会流式显示", "accent")
        self.chat_note("● 输入 / 弹出斜杠命令补全面板（如 /compact 压缩上下文）", "accent")
        self.chat_note("● 左侧栏：MCP 服务器状态 + 历史会话（双击恢复）", "accent")
        self.chat_note("● 右侧栏：工具调用日志，实时滚动", "accent")

    # ------------------------------------------------------------------
    # 启动流程
    # ------------------------------------------------------------------
    def _on_startup(self):
        self._update_info_bar()
        if self.mcp_client and (not self.config or self.config.mcp_enabled):
            threading.Thread(target=self._load_mcp_async, daemon=True).start()
        if self.config_warning:
            self.after(600, self._show_config_warning)

    def _show_config_warning(self):
        messagebox.showwarning(
            "缺少配置文件",
            "未找到 .config.ini，已自动生成一份模板文件：\n\n  .config.ini\n\n"
            "当前使用的是模板中的示例（mock）配置，LLM 调用无法正常工作。\n\n"
            "请按以下步骤操作：\n"
            "  1. 打开项目目录下的 .config.ini\n"
            "  2. 将 [llm] api_key 修改为你的真实 API Key\n"
            "  3. 按需调整模型、地址等参数\n"
            "  4. 保存后重新启动 CAgent",
            parent=self,
        )

    # ------------------------------------------------------------------
    # 聊天区操作
    # ------------------------------------------------------------------
    def chat_note(self, text: str, tag="note"):
        self.chat_text.configure(state="normal")
        self.chat_text.insert("end", f"  {text}\n", (tag,))
        self.chat_text.configure(state="disabled")
        self.chat_text.see("end")

    def add_user_bubble(self, text: str):
        self.chat_text.configure(state="normal")
        width = max(340, self.chat_text.winfo_width() - 220)
        bubble = Bubble(self.chat_text, text, "user", width)
        pos = self.chat_text.index("end")
        self.chat_text.window_create(pos, window=bubble)
        self.chat_text.tag_add("user", pos)
        self.chat_text.insert("end", "\n\n")
        self.chat_text.configure(state="disabled")
        self.chat_text.see("end")

    def add_assistant_bubble(self, text: str = ""):
        self.chat_text.configure(state="normal")
        width = max(340, self.chat_text.winfo_width() - 80)
        bubble = Bubble(self.chat_text, text, "assistant", width)
        self.chat_text.window_create("end", window=bubble)
        self.chat_text.insert("end", "\n\n")
        self.chat_text.configure(state="disabled")
        self.chat_text.see("end")
        return bubble

    def clear_chat(self):
        self.chat_text.configure(state="normal")
        self.chat_text.delete("1.0", "end")
        self.chat_text.configure(state="disabled")

    def log_write(self, text: str, tag: str = "dim"):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text + "\n", (tag,))
        self.log_text.configure(state="disabled")
        self.log_text.see("end")

    # ------------------------------------------------------------------
    # 顶栏状态更新
    # ------------------------------------------------------------------
    def _update_info_bar(self):
        status = self.llm_client.get_context_status()
        usage_k = status["usage_tokens"] / 1024
        if status["window_tokens"] == 0:
            window_k = status["display_window"] / 1024
            window_part = f"{window_k:g}k 默认"
        else:
            window_k = status["display_window"] / 1024
            window_part = f"{window_k:g}k"
        percent = int(status["ratio"] * 100)

        model_name = self.config.model if self.config else "deepseek-chat"
        tool_count = len(self.llm_client.tool_registry.get_tools_schema())

        # 模型徽章 / 工具徽章
        self.model_pill._text = model_name
        self.model_pill._draw()
        self.tool_pill._text = f"{tool_count} 工具"
        self.tool_pill._draw()

        # 上下文文字 + 进度条颜色
        self.ctx_label.configure(text=f"{usage_k:g}k / {window_part}（{percent}%）")
        state = status.get("state", "ok")
        if status.get("compacting"):
            color = ACCENT_YELLOW
        elif state == "blocked":
            color = ACCENT_RED
        elif state == "warn":
            color = ACCENT_YELLOW
        else:
            color = ACCENT
        self.ctx_bar.set(percent, color)

        # 底部状态栏提示
        if status.get("compacting"):
            hint = "上下文压缩中，请稍候..."
        elif state == "blocked":
            hint = "上下文已满，请点击「压缩上下文」或输入 /compact"
        elif state == "warn":
            hint = "上下文已用 80% 以上，建议压缩上下文"
        else:
            hint = "输入消息开始对话 · 输入 / 查看斜杠命令"
        self.status_bar.configure(text="  " + hint)

    # ------------------------------------------------------------------
    # 输入处理
    # ------------------------------------------------------------------
    def _on_send_click(self):
        self._on_send(None)

    def _on_send(self, _event):
        text = self.input_box.get().strip()
        if not text:
            return
        self._hide_palette()

        if text.startswith("/"):
            self.input_box.delete(0, "end")
            self._dispatch_slash(text)
            return

        status = self.llm_client.get_context_status()
        if status.get("input_blocked"):
            self.input_box.delete(0, "end")
            self.log_write("✗ 上下文已达 80%，请先压缩（压缩上下文 或 /compact）", "err")
            return

        self.input_box.delete(0, "end")
        self.add_user_bubble(text)
        self._current_bubble = self.add_assistant_bubble("")
        threading.Thread(target=self._run_llm, args=(text,), daemon=True).start()

    def _on_key_release(self, event):
        if getattr(event, "keysym", "") in ("Return", "Escape", "Up", "Down"):
            return
        text = self.input_box.get()
        if text.startswith("/"):
            self._show_palette(text[1:])
        else:
            self._hide_palette()

    # ------------------------------------------------------------------
    # 命令补全面板
    # ------------------------------------------------------------------
    def _show_palette(self, prefix: str):
        if self._palette is None or not self._palette.winfo_exists():
            x = self.input_box.winfo_rootx()
            y = self.input_box.winfo_rooty() - 250
            self._palette = CommandPalette(
                self, self.COMMANDS, x, y, max(360, self.input_box.winfo_width()),
            )
        self._palette.update_filter(prefix)
        self._palette.listbox.focus_set()

    def _hide_palette(self):
        if self._palette is not None and self._palette.winfo_exists():
            self._palette.withdraw()

    def _dispatch_slash(self, text: str):
        cmd = text.split()[0]
        for c, _, _, action in self.COMMANDS:
            if c == cmd:
                getattr(self, action)()
                return
        self.log_write(f"未知命令: {cmd}（输入 /help 查看可用命令）", "err")

    # ------------------------------------------------------------------
    # 斜杠命令动作
    # ------------------------------------------------------------------
    def action_new_session(self):
        saved_id = None
        if self.session_manager and self.llm_client.messages:
            saved_id = self.session_manager.save_session(self.llm_client.messages)

        self.llm_client.reset()
        self.clear_chat()
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")
        self.log_write("─ 工具调用日志 ─", "dim")

        if saved_id:
            self.log_write(f"✓ 当前会话已保存: {saved_id}", "ok")
        self.chat_note(
            "已开始新会话（原会话" + (f"保存为 {saved_id}" if saved_id else "为空未保存") + "）"
        )
        self._show_welcome()
        self._refresh_session_list()
        self._update_info_bar()

    def action_save_session(self):
        if not self.session_manager:
            self.log_write("✗ 未配置会话管理器", "err")
            return
        if not self.llm_client.messages:
            self.log_write("当前会话为空，无需保存", "dim")
            return
        saved_id = self.session_manager.save_session(self.llm_client.messages)
        if saved_id:
            self.log_write(f"✓ 会话已保存: {saved_id}", "ok")
            self._refresh_session_list()
        else:
            self.log_write("✗ 会话保存失败", "err")

    def action_resume_session(self):
        if not self.session_manager:
            self.log_write("✗ 未配置会话管理器", "err")
            return
        sessions = self.session_manager.list_sessions()
        if not sessions:
            self.log_write("没有任何历史会话（.agents/sessions/ 为空）", "dim")
            return
        SessionPickerDialog(self, sessions)

    def _on_session_picked(self, session_id: str):
        messages = self.session_manager.load_session(session_id)
        if not messages:
            self.log_write(f"✗ 会话 {session_id} 加载失败或为空", "err")
            return
        self.llm_client.messages = messages
        self.llm_client._input_blocked = False
        if self.llm_client.context_manager:
            self.llm_client.context_manager.last_usage = None
        self.clear_chat()
        self.chat_note(f"已恢复会话 {session_id}（{len(messages)} 条消息），可继续对话", "accent")
        self.log_write(f"✓ 已恢复会话 {session_id}（{len(messages)} 条消息）", "ok")
        self._update_info_bar()

    def action_quit_app(self):
        self.destroy()

    def action_help_command(self):
        self.log_write("── 可用斜杠命令 ──", "accent")
        for cmd, name, help_text, _ in self.COMMANDS:
            self.log_write(f"  {cmd:<9} {name} —— {help_text}", "bold")
        self.log_write("快捷键: 回车发送 · Esc 关闭面板", "dim")

    def action_show_tools(self):
        self.log_write("── 已注册工具 ──", "accent")
        schemas = self.llm_client.tool_registry.get_tools_schema()
        for s in schemas:
            fn = s["function"]
            self.log_write(f"  {fn['name']}  —  {fn.get('description', '')[:60]}", "bold")
        self.log_write(f"共 {len(schemas)} 个工具", "dim")

    def action_show_skills(self):
        self.log_write("── 可用技能 ──", "accent")
        if self.llm_client.skill_loader:
            skills = self.llm_client.skill_loader.list_skills()
            if skills:
                for s in skills:
                    self.log_write(f"  {s.name}  —  {s.description[:60]}", "bold")
                self.log_write(f"共 {len(skills)} 个技能，用 loadSkill 工具加载详情", "dim")
            else:
                self.log_write("没有可用技能（.agents/skills/ 为空）", "dim")
        else:
            self.log_write("未启用技能系统", "dim")

    def action_show_mcp(self):
        self._refresh_sidebar()
        self.log_write("── MCP 服务器 ──", "accent")
        if not self.mcp_client:
            self.log_write("未启用 MCP", "dim")
            return
        summary = self.mcp_client.get_server_summary()
        if not summary:
            self.log_write("未发现 MCP 服务器（检查 .mcp.json）", "dim")
            return
        for s in summary:
            state = "已连接" if s["status"] == "connected" else "连接失败"
            self.log_write(f"  {s['name']}  [{state}] {s['tool_count']} 工具", "bold")
            for t in s["tools"]:
                self.log_write(f"    ↳ {t}")

    def action_show_context(self):
        status = self.llm_client.get_context_status()
        self.log_write("── 上下文状态 ──", "accent")
        self.log_write(f"  已用: {status['usage_tokens']} Tokens")
        self.log_write(
            f"  窗口: {status['display_window']} Tokens"
            + ("（默认）" if status["window_tokens"] == 0 else "")
        )
        self.log_write(f"  占用: {int(status['ratio'] * 100)}%")
        self.log_write(
            f"  状态: {status['state']} · 压缩中: {status['compacting']} "
            f"· 输入锁定: {status['input_blocked']}"
        )

    def action_clear_chat(self):
        self.clear_chat()
        self.log_write("✓ 聊天区已清空（对话历史保留在内存中）", "ok")
        self._update_info_bar()

    def action_compact_command(self):
        self._run_compact()

    # ------------------------------------------------------------------
    # 上下文压缩
    # ------------------------------------------------------------------
    def _run_compact(self):
        if self._compacting:
            return
        self._compacting = True
        self.log_write("↻ 开始上下文压缩...", "warn")
        self._update_info_bar()

        def on_progress(msg: str):
            self.after(0, lambda: self.log_write(msg, "warn"))

        def _do_compact():
            try:
                result = self.llm_client.compact(on_progress=on_progress)

                def show_result():
                    if result["success"]:
                        self.log_write(f"✓ 压缩完成，归档 {result['archive_id']}", "ok")
                        self.log_write("历史细节可用 recallContext 工具检索", "dim")
                    else:
                        self.log_write(f"✗ 压缩失败: {result['error']}", "err")
                        self.log_write("原有上下文已保留，可重试压缩", "dim")
                    self._update_info_bar()

                self.after(0, show_result)
            except Exception as e:
                self.after(0, lambda: self.log_write(f"✗ 压缩异常: {e}", "err"))
            finally:
                self._compacting = False
                self.after(0, self._update_info_bar)

        threading.Thread(target=_do_compact, daemon=True).start()

    # ------------------------------------------------------------------
    # LLM 对话线程
    # ------------------------------------------------------------------
    def _run_llm(self, user_text: str):
        def on_token(token: str):
            def update():
                if self._current_bubble is not None:
                    self._current_bubble.append_text(token)
                    self.chat_text.see("end")
            self.after(0, update)

        def on_tool_call(name: str, args: dict):
            self.after(0, lambda: self.log_write(f"→ {name}  {args}", "accent"))

        def on_tool_result(name: str, result: str):
            preview = result[:120] + ("..." if len(result) > 120 else "")
            self.after(0, lambda: self.log_write(f"✓ {name}  {preview}", "ok"))

        try:
            self.llm_client.chat(
                user_input=user_text,
                on_token=on_token,
                on_tool_call=on_tool_call,
                on_tool_result=on_tool_result,
            )
        except Exception as e:
            self.after(0, lambda: self.log_write(f"✗ {e}", "err"))
        finally:
            self.after(0, self._update_info_bar)

    # ------------------------------------------------------------------
    # MCP 异步加载
    # ------------------------------------------------------------------
    def _load_mcp_async(self):
        try:
            self.mcp_client.discover_and_register()
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
            self.after(0, lambda: self.log_write(f"MCP 异步加载失败: {e}", "err"))
        finally:
            self.after(0, self._refresh_sidebar)
            self.after(0, self._update_info_bar)

    def _refresh_sidebar(self):
        """刷新左栏（简洁状态）与内容区左栏（详细列表）。"""
        # 左栏简洁状态
        self.mcp_text.configure(state="normal")
        self.mcp_text.delete("1.0", "end")
        if not self.mcp_client:
            self.mcp_text.insert("end", "未启用 MCP\n", ("dim",))
        else:
            summary = self.mcp_client.get_server_summary()
            if not summary:
                self.mcp_text.insert("end", "未发现服务器\n", ("dim",))
            else:
                for s in summary:
                    state_tag = "ok" if s["status"] == "connected" else "fail"
                    state_text = "已连接" if s["status"] == "connected" else "失败"
                    self.mcp_text.insert(
                        "end", f"● {s['name']}  {state_text}  {s['tool_count']} 工具\n",
                        (state_tag,),
                    )
        self.mcp_text.configure(state="disabled")

        # 内容区左栏详细列表
        self.mcp_detail.configure(state="normal")
        self.mcp_detail.delete("1.0", "end")
        if not self.mcp_client:
            self.mcp_detail.insert("end", "未启用 MCP\n", ("dim",))
        else:
            summary = self.mcp_client.get_server_summary()
            if not summary:
                self.mcp_detail.insert("end", "未发现 MCP 服务器\n", ("dim",))
                self.mcp_detail.insert("end", "（检查项目目录 .mcp.json）\n", ("dim",))
            else:
                for s in summary:
                    if s["status"] == "connected":
                        state_tag, state_text = "ok", "● 已连接"
                    else:
                        state_tag, state_text = "fail", "● 连接失败"
                    self.mcp_detail.insert("end", f"{s['name']}  ", ("bold",))
                    self.mcp_detail.insert("end", f"{state_text}  ", (state_tag,))
                    self.mcp_detail.insert("end", f"{s['tool_count']} 个工具\n", ("dim",))
                    for tool_name in s["tools"]:
                        self.mcp_detail.insert("end", f"    ↳ {tool_name}\n", ("dim",))
                    self.mcp_detail.insert("end", "\n")
        self.mcp_detail.configure(state="disabled")


class GUIUI(BaseUI):
    """GUI 界面入口。"""

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
        CAgentGUI(
            llm_client=self.llm_client,
            session_manager=self.session_manager,
            mcp_client=self.mcp_client,
            config=self.config,
            config_warning=self.config_warning,
        ).mainloop()
