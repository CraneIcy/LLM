"""
CAgent 入口文件。
用法: python main.py            # 启动图形界面（GUI，默认）
      python main.py --tui      # 启动终端界面（TUI）

启动流程：
1. 检查 .config.ini 是否存在；不存在则自动生成 mock 模板并提示用户修改后重启
2. 加载配置（所有参数均可配置，未配置项使用默认值）
3. 初始化工具注册表 / Skill 加载器 / 上下文管理器 / 会话管理器
4. 初始化 LLM 客户端（注入 AGENTS.md，一次注入全程复用）
5. 启动界面（GUI 默认；MCP 改为异步加载：界面先启动，边栏后动态刷新）
"""

import sys
import os
import argparse


def get_base_dir() -> str:
    """获取程序运行的基础目录（打包后是 exe 所在目录，开发时是项目根目录）。"""
    if getattr(sys, "frozen", False):
        # PyInstaller 打包后的 exe
        return os.path.dirname(sys.executable)
    else:
        # 直接运行 python
        return os.path.dirname(os.path.abspath(__file__))


# 把项目根目录加入搜索路径，找到 core / ui 模块
base_dir = get_base_dir()
sys.path.insert(0, base_dir)

from core.config import Config
from core.tool_registry import ToolRegistry
from core.skill_loader import SkillLoader
from core.context_manager import ContextManager
from core.session_manager import SessionManager
from core.tools.load_skill_tool import LoadSkillTool
from core.tools.create_skill_tool import CreateSkillTool
from core.tools.recall_context_tool import RecallContextTool
from core.mcp_client import MCPClient
from core.llm_client import LLMClient
from ui.gui import GUIUI
from ui.tui import TUIUI


def main():
    # 1. 加载配置（从 exe 同目录找 .config.ini）
    #    若不存在：自动生成一份完整模板（mock 信息），
    #    并标记 config_warning，让 TUI 弹窗提示用户修改后重启。
    config_path = os.path.join(base_dir, ".config.ini")
    config_warning = False
    if not os.path.exists(config_path):
        try:
            Config.create_template(config_path)
            config_warning = True
            print(f"⚠ 未找到配置文件，已自动生成模板: {config_path}")
            print("  当前使用 mock 配置，请修改 api_key 后重新启动。")
        except OSError as e:
            print(f"错误：无法创建配置文件模板: {e}")
            input("按回车退出...")
            return

    config = Config(config_path=config_path)

    # 2. 初始化工具注册表（传入配置以启用搜索等需要配置的工具）
    tool_registry = ToolRegistry(config=config)

    # 3. 初始化 Skill 加载器，发现可用的 Skill
    skill_loader = SkillLoader(project_root=base_dir)
    skills = skill_loader.discover_skills()
    if skills:
        print(f"已加载 {len(skills)} 个 Skill: {', '.join(s.name for s in skills)}")

    # 注册 loadSkill 工具（让 LLM 可以加载 Skill 内容）
    tool_registry.register(LoadSkillTool(skill_loader=skill_loader))

    # 注册 createSkill 工具（让 LLM 可以根据用户要求创建新 Skill）
    tool_registry.register(CreateSkillTool(skill_loader=skill_loader))

    # 初始化上下文管理器（Token 统计 / 归档 / 检索 / 压缩）
    # 警告比例与默认窗口均从 config.ini 读取（未配置则用默认值）
    context_manager = ContextManager(
        project_root=base_dir,
        warn_ratio=config.warn_ratio,
        default_window=config.ui_default_context_window,
    )
    # 从配置读取模型真实上下文窗口大小（0 表示未知，TUI 默认显示 + 「默认」）
    context_manager.context_window = config.context_window

    # 注册 recallContext 工具（让 LLM 可以检索历史上下文归档）
    tool_registry.register(RecallContextTool(context_manager=context_manager))

    # 初始化会话管理器（/new /resume /save 使用），保存目录可从配置读取
    session_manager = SessionManager(
        project_root=base_dir,
        save_dir=config.session_save_dir,
    )

    # 4. 初始化 MCP Client（读取 .mcp.json，异步连接外部 MCP Server）
    #    优先使用启动时的工作目录作为项目目录；若没有 .mcp.json 则回退到程序所在目录
    mcp_project_root = os.getcwd()
    mcp_config_file = config.mcp_config_file
    if not os.path.exists(os.path.join(mcp_project_root, mcp_config_file)):
        if os.path.exists(os.path.join(base_dir, mcp_config_file)):
            mcp_project_root = base_dir

    mcp_client = None
    if config.mcp_enabled:
        mcp_client = MCPClient(project_root=mcp_project_root)
        # 注意：这里不再同步连接——MCP 由 TUI 异步加载，
        #      界面先启动，边栏在连接完成后动态刷新。

    # 5. 初始化 LLM 客户端（传入 skill_loader，把 Skill 信息注入 System Prompt；
    #    传入 context_manager，启用上下文监控与压缩；
    #    传入 agents_md_path，实现 AGENTS.md「一次注入，全程复用」）
    #    文件名可通过 .config.ini 的 [agent] agents_md_file 配置，默认 AGENTS.md
    llm_client = LLMClient(
        config=config,
        tool_registry=tool_registry,
        skill_loader=skill_loader,
        context_manager=context_manager,
        agents_md_path=os.path.join(base_dir, config.agents_md_file),
    )

    # 6. 启动界面（默认图形界面 GUI；--tui 切回终端界面）
    #    MCP 异步加载 + 会话管理 + 配置缺失弹窗均由界面层负责
    parser = argparse.ArgumentParser(description="CAgent 启动入口")
    parser.add_argument(
        "--tui", action="store_true",
        help="使用终端界面（默认启动图形界面）",
    )
    args, _ = parser.parse_known_args()

    ui_cls = TUIUI if args.tui else GUIUI
    ui = ui_cls(
        llm_client=llm_client,
        session_manager=session_manager,
        mcp_client=mcp_client,
        config=config,
        config_warning=config_warning,
    )
    ui.run()


if __name__ == "__main__":
    main()
