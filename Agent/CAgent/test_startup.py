# -*- coding: utf-8 -*-
"""启动冒烟测试：完整复刻 main.py 的初始化流程 + Textual 驱动 TUI 启动。

验证点：
1. 配置加载（.config.ini）
2. 工具注册表（内置 14 + loadSkill + createSkill + recallContext + MCP 工具）
3. SkillLoader 技能发现（.agents/skills/）
4. MCP Client 连接与工具注册（.mcp.json）
5. LLMClient + ContextManager 注入
6. TUI 启动（compose 成功、状态栏渲染、输入可用）
"""
import os
import sys

sys.path.insert(0, r"D:\LLM\Agent\CAgent")

from core.config import Config
from core.tool_registry import ToolRegistry
from core.skill_loader import SkillLoader
from core.context_manager import ContextManager
from core.mcp_client import MCPClient
from core.llm_client import LLMClient
from ui.tui.app import TUIApp, Input, Label

BASE_DIR = r"D:\LLM\Agent\CAgent"

print("=== 1. 加载配置 ===", flush=True)
config = Config(config_path=os.path.join(BASE_DIR, ".config.ini"))
print(f"model={config.model}, base_url={config.base_url}", flush=True)
print(f"context_window 配置={config.context_window}（0=未知，将用默认 128k）", flush=True)

print("\n=== 2. 工具注册表（内置工具）===", flush=True)
tool_registry = ToolRegistry(config=config)
print(f"内置工具数: {len(tool_registry.get_tools_schema())}", flush=True)

print("\n=== 3. Skill 发现 ===", flush=True)
skill_loader = SkillLoader(project_root=BASE_DIR)
skills = skill_loader.discover_skills()
names = [s.name for s in skills]
print(f"发现 {len(skills)} 个 Skill: {names}", flush=True)

from core.tools.load_skill_tool import LoadSkillTool
from core.tools.create_skill_tool import CreateSkillTool
from core.tools.recall_context_tool import RecallContextTool
tool_registry.register(LoadSkillTool(skill_loader=skill_loader))
tool_registry.register(CreateSkillTool(skill_loader=skill_loader))

print("\n=== 4. 上下文压缩组件 ===", flush=True)
context_manager = ContextManager(project_root=BASE_DIR)
context_manager.context_window = config.context_window
tool_registry.register(RecallContextTool(context_manager=context_manager))
print(f"归档目录: {context_manager.context_dir}", flush=True)

print("\n=== 5. MCP 连接 ===", flush=True)
mcp_project_root = os.getcwd()
if not os.path.exists(os.path.join(mcp_project_root, ".mcp.json")):
    if os.path.exists(os.path.join(BASE_DIR, ".mcp.json")):
        mcp_project_root = BASE_DIR
print(f"MCP 项目根: {mcp_project_root}", flush=True)

mcp_client = MCPClient(project_root=mcp_project_root)
server_tools = mcp_client.discover_and_register()

from core.tools.mcp_tool import MCPToolAdapter
mcp_tool_count = 0
for server_name, tools in server_tools.items():
    for tool in tools:
        exposed_name = f"{server_name}__{tool['name']}"
        adapter = MCPToolAdapter(
            mcp_client=mcp_client,
            exposed_name=exposed_name,
            server_name=server_name,
            original_name=tool["name"],
            description=tool["description"],
            input_schema=tool["inputSchema"],
        )
        tool_registry.register(adapter)
        mcp_tool_count += 1
print(f"MCP 注册 {mcp_tool_count} 个工具", flush=True)

print("\n=== 6. LLM 客户端 ===", flush=True)
llm_client = LLMClient(
    config=config,
    tool_registry=tool_registry,
    skill_loader=skill_loader,
    context_manager=context_manager,
)
all_schemas = tool_registry.get_tools_schema()
tool_names = [t["function"]["name"] for t in all_schemas]
print(f"最终工具总数: {len(all_schemas)}", flush=True)
print(f"工具列表: {tool_names}", flush=True)
assert "recallContext" in tool_names, "recallContext 未注册！"
print("✓ recallContext 已注册", flush=True)

print("\n=== 7. TUI 启动 ===", flush=True)
import asyncio

async def run_tui():
    app = TUIApp(llm_client=llm_client)
    async with app.run_test() as pilot:
        await pilot.pause(0.5)
        label = app.query_one("#status-line", Label)
        status_text = str(label.render())
        print("状态栏:", status_text, flush=True)
        assert "上下文" in status_text and "默认" in status_text
        input_box = app.query_one("#input-box", Input)
        print("输入框可用:", not input_box.disabled, flush=True)
        assert not input_box.disabled
        print("✓ TUI 启动成功，界面组件正常", flush=True)

asyncio.run(run_tui())

print("\n✓✓✓ 启动冒烟测试全部通过 ✓✓✓", flush=True)
