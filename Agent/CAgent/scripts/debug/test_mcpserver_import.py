# -*- coding: utf-8 -*-
import sys

def log(msg):
    print(msg, flush=True)

try:
    from mcp.server.mcpserver import MCPServer
    log("MCPServer 导入成功")
    methods = [n for n in dir(MCPServer) if not n.startswith("_")]
    log("方法: " + ", ".join(methods))
except SystemExit as e:
    log("SystemExit: " + repr(e))
except BaseException as e:
    import traceback
    log("异常: " + repr(e))
    traceback.print_exc()
