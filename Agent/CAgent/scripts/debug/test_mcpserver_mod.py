# -*- coding: utf-8 -*-
import sys, traceback

try:
    import mcp.server.mcpserver as ms
    print("mcpserver module OK:", ms.__file__)
    print("exports:", [n for n in dir(ms) if not n.startswith("_")])
except Exception as e:
    print("import fail:", repr(e))
    traceback.print_exc()
    sys.exit(1)
