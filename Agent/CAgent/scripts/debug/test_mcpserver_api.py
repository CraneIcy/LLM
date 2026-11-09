# -*- coding: utf-8 -*-
from mcp.server.mcpserver import MCPServer
import inspect

print("MCPServer 方法:", [n for n in dir(MCPServer) if not n.startswith("_")][:40])
print()
# 查看关键方法签名
for name in ["tool", "run", "list_tools", "call_tool"]:
    if hasattr(MCPServer, name):
        try:
            print(f"{name}{inspect.signature(getattr(MCPServer, name))}")
        except Exception as e:
            print(f"{name}: (无法获取签名 {e})")
