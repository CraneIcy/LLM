"""
配置模块：负责读取 .config.ini 中的各项参数。

设计原则（教学要求）：
1. 所有配置项都有默认值 —— 未在 .config.ini 中配置时自动使用默认参数
2. 配置缺失时可通过 create_template() 生成一份完整的模板文件（填 mock 信息）
3. 新增配置项只需在 DEFAULT_TEMPLATE 中添加，并增加对应的属性读取方法

配置段说明：
- [llm]      大语言模型连接参数（API Key / 地址 / 模型 / 上下文窗口等）
- [agent]    Agent 行为参数（压缩阈值、请求超时等）
- [ui]       界面显示参数（默认窗口、时钟等）
- [mcp]      MCP 客户端参数（是否启用、配置文件路径）
- [sessions] 会话保存目录
- [search]   网络搜索 API 参数
"""

import configparser
import os
from typing import Optional


class Config:
    """全局配置，从 .config.ini 读取，未配置项使用默认值。"""

    def __init__(self, config_path: str = ".config.ini", create_if_missing: bool = False):
        """
        :param config_path: 配置文件路径
        :param create_if_missing: 若文件不存在，是否自动生成一份 mock 模板
        """
        self.config_path = config_path
        self._parser = configparser.ConfigParser()

        if not os.path.exists(config_path):
            if create_if_missing:
                # 自动生成完整模板（mock 信息），供用户修改后重启
                self.create_template(config_path)
            else:
                raise FileNotFoundError(f"配置文件不存在: {config_path}")

        self._parser.read(config_path, encoding="utf-8")

    # ------------------------------------------------------------------
    # 通用读取
    # ------------------------------------------------------------------
    def get(self, section: str, key: str, default: Optional[str] = None) -> Optional[str]:
        """按段名 + 键名读取字符串配置，不存在时返回默认值。"""
        return self._parser.get(section, key, fallback=default)

    def get_int(self, section: str, key: str, default: int = 0) -> int:
        """按段名 + 键名读取整数配置，解析失败或不存在时返回默认值。"""
        try:
            return int(self._parser.get(section, key, fallback=str(default)))
        except (ValueError, TypeError):
            return default

    def get_float(self, section: str, key: str, default: float = 0.0) -> float:
        """按段名 + 键名读取浮点配置，解析失败或不存在时返回默认值。"""
        try:
            return float(self._parser.get(section, key, fallback=str(default)))
        except (ValueError, TypeError):
            return default

    def get_bool(self, section: str, key: str, default: bool = False) -> bool:
        """按段名 + 键名读取布尔配置，解析失败或不存在时返回默认值。"""
        value = self._parser.get(section, key, fallback="true" if default else "false")
        return value.strip().lower() in ("1", "true", "yes", "on")

    # ------------------------------------------------------------------
    # [llm] 大语言模型配置
    # ------------------------------------------------------------------
    @property
    def base_url(self) -> str:
        return self.get("llm", "base_url", "https://api.deepseek.com/v1")

    @property
    def api_key(self) -> str:
        return self.get("llm", "api_key", "")

    @property
    def model(self) -> str:
        return self.get("llm", "model", "deepseek-chat")

    @property
    def context_window(self) -> int:
        """
        大语言模型的上下文窗口大小（Token 数），未配置时返回 0（表示未知）。
        未知时 TUI 状态栏显示默认 128k 并标注「默认」。
        """
        return self.get_int("llm", "context_window", 0)

    @property
    def temperature(self) -> float:
        """生成温度，默认 0.7。"""
        return self.get_float("llm", "temperature", 0.7)

    @property
    def request_timeout(self) -> int:
        """LLM API 请求超时（秒），默认 300。"""
        return self.get_int("llm", "request_timeout", 300)

    # ------------------------------------------------------------------
    # [agent] Agent 行为配置
    # ------------------------------------------------------------------
    @property
    def warn_ratio(self) -> float:
        """上下文占用达到窗口的该比例时警告并暂停输入，默认 0.8（80%）。"""
        return self.get_float("agent", "warn_ratio", 0.8)

    @property
    def compact_max_tokens(self) -> int:
        """压缩摘要请求的最大输出 Token，默认 8192。"""
        return self.get_int("agent", "compact_max_tokens", 8192)

    @property
    def max_tool_steps(self) -> int:
        """单轮对话内允许的最大工具调用轮数（防死循环），默认 8。"""
        return self.get_int("agent", "max_tool_steps", 8)

    @property
    def agents_md_file(self) -> str:
        """项目指导文件名，默认 AGENTS.md（兼容 AGENT.md 等等价命名）。"""
        return self.get("agent", "agents_md_file", "AGENTS.md")

    # ------------------------------------------------------------------
    # [ui] 界面配置
    # ------------------------------------------------------------------
    @property
    def ui_default_context_window(self) -> int:
        """
        无法获取模型上下文窗口时，界面显示的默认窗口大小（Token 数）。
        默认 131072（128k），并标注「默认」。
        """
        return self.get_int("ui", "default_context_window", 128 * 1024)

    @property
    def ui_show_clock(self) -> bool:
        """顶部标题栏是否显示时钟，默认 True。"""
        return self.get_bool("ui", "show_clock", True)

    @property
    def ui_tool_panel_visible(self) -> bool:
        """右侧工具日志面板初始是否可见，默认 True。"""
        return self.get_bool("ui", "tool_panel_visible", True)

    # ------------------------------------------------------------------
    # [mcp] MCP 客户端配置
    # ------------------------------------------------------------------
    @property
    def mcp_enabled(self) -> bool:
        """是否启用 MCP 客户端，默认 True。"""
        return self.get_bool("mcp", "enabled", True)

    @property
    def mcp_config_file(self) -> str:
        """MCP 配置文件名称，默认 .mcp.json。"""
        return self.get("mcp", "config_file", ".mcp.json")

    # ------------------------------------------------------------------
    # [sessions] 会话保存配置
    # ------------------------------------------------------------------
    @property
    def session_save_dir(self) -> str:
        """历史会话保存目录（相对项目根），默认 .agents/sessions。"""
        return self.get("sessions", "save_dir", ".agents/sessions")

    # ------------------------------------------------------------------
    # [search] 网络搜索配置
    # ------------------------------------------------------------------
    @property
    def search_api_key(self) -> str:
        """百度千帆搜索 API Key，未配置时返回空字符串。"""
        return self.get("search", "baidu_qianfan_api_key", "")

    @property
    def search_base_url(self) -> str:
        """搜索 API 地址，默认百度千帆 AI Search。"""
        return self.get(
            "search",
            "base_url",
            "https://qianfan.baidubce.com/v2/ai_search/chat/completions",
        )

    # ------------------------------------------------------------------
    # 模板生成
    # ------------------------------------------------------------------
    @staticmethod
    def create_template(config_path: str) -> None:
        """
        生成一份完整的 .config.ini 模板文件。
        所有关键项填入 mock（示例）信息，用户修改后重新启动即可正常工作。

        :param config_path: 要生成的配置文件路径
        """
        template = """# ============================================================
# CAgent 配置文件（.config.ini）
#
# 使用方法：
#   1. 修改 [llm] 段中的 api_key 为你自己的 API Key
#   2. 按需调整其他参数（不配置的项使用默认值）
#   3. 保存后重新启动 CAgent
# ============================================================

[llm]
# 大语言模型 API Key（必填，请替换为你的真实 Key）
api_key = sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
# API 地址（OpenAI 兼容接口）
base_url = https://api.deepseek.com/v1
# 模型名称
model = deepseek-chat
# 上下文窗口大小（Token 数），0 = 未知（界面显示默认 128k 并标注「默认」）
context_window = 0
# 生成温度（0~2，默认 0.7）
temperature = 0.7
# API 请求超时（秒，默认 300）
request_timeout = 300

[agent]
# 上下文占用达到窗口的该比例时警告并暂停输入（默认 0.8 = 80%）
warn_ratio = 0.8
# 上下文压缩摘要的最大输出 Token（默认 8192）
compact_max_tokens = 8192
# 单轮对话内允许的最大工具调用轮数（防止模型反复调用工具死循环，默认 8）
max_tool_steps = 8
# 项目指导文件名（放在程序根目录，内容作为长期规则注入；兼容 AGENT.md / AGENTS.md）
agents_md_file = AGENTS.md

[ui]
# 无法获取模型上下文窗口时，界面显示的默认窗口大小（默认 131072 = 128k）
default_context_window = 131072
# 顶部标题栏是否显示时钟（true/false）
show_clock = true
# 右侧工具日志面板初始是否可见（true/false）
tool_panel_visible = true

[mcp]
# 是否启用 MCP 客户端（true/false）
enabled = true
# MCP 配置文件名称
config_file = .mcp.json

[sessions]
# 历史会话保存目录（相对项目根目录）
save_dir = .agents/sessions

[search]
# 百度千帆 AI Search API Key（可选，配置后启用 searchWeb 工具）
baidu_qianfan_api_key =
# 搜索 API 地址
base_url = https://qianfan.baidubce.com/v2/ai_search/chat/completions
"""
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                f.write(template)
        except OSError as e:
            raise OSError(f"无法创建配置文件模板 {config_path}: {e}")
