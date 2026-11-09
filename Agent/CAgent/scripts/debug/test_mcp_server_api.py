# -*- coding: utf-8 -*-
"""检查 mcp 2.3.0 的 Server 端 API"""
import mcp
import mcp.server
print("mcp.server module:", mcp.server)

try:
    import mcp.server.fastmcp as fm
    print("fastmcp 可导入")
    print([n for n in dir(fm) if not n.startswith("_")])
except Exception as e:
    print("fastmcp 导入失败:", type(e).__name__, e)

try:
    from mcp.server import Server
    print("Server 可导入")
except Exception as e:
    print("Server 导入失败:", type(e).__name__, e)
