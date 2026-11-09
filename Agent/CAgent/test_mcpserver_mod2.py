# -*- coding: utf-8 -*-
import sys

def log(msg):
    print(msg, flush=True)

log("step1: 开始")

try:
    import mcp.server.mcpserver as ms
    log("step2: mcpserver 导入成功")
    log("exports: " + str([n for n in dir(ms) if not n.startswith("_")]))
except SystemExit as e:
    log("SystemExit: " + repr(e))
except BaseException as e:
    import traceback
    log("异常: " + repr(e))
    traceback.print_exc()
    log("step3: 结束")
