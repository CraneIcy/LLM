# -*- coding: utf-8 -*-
import sys

def log(msg):
    print(msg, flush=True)

log("step1")
import mcp.server.mcpserver as ms
log("step2: 模块导入成功")

# 通过模块属性访问 MCPServer，避免直接 from-import
MCPServer = getattr(ms, "MCPServer")
log("step3: MCPServer 类访问成功: " + str(MCPServer))

methods = [n for n in dir(MCPServer) if not n.startswith("_")]
log("step4: 方法列表: " + ", ".join(methods[:30]))
