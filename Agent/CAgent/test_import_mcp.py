# -*- coding: utf-8 -*-
import sys
print("python:", sys.executable)
print("start")

try:
    import mcp
    print("mcp imported:", mcp.__file__)
except Exception as e:
    print("mcp import fail:", repr(e))
    sys.exit(1)

try:
    import mcp.server
    print("mcp.server imported:", mcp.server.__file__)
except Exception as e:
    print("mcp.server import fail:", repr(e))

try:
    import mcp.server.fastmcp
    print("mcp.server.fastmcp imported OK")
except Exception as e:
    print("mcp.server.fastmcp import fail:", repr(e))

print("done")
