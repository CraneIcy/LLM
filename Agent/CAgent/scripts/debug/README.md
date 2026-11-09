# scripts/debug · 一次性调试脚本归档

这里存放的是开发期间为排查 MCP 集成问题临时写的小脚本（10–21 行），**不是测试用例**，
`pytest` 不会收集它们，CI 也不运行。保留它们只是为了留下排查过程的可追溯记录。

| 脚本 | 当时要排查的问题 |
|---|---|
| `test_import_mcp.py` | `from mcp import ClientSession` 能否在本机解释器里导入 |
| `test_mcp_server_api.py` | `MCPServer` 对象上有哪些可用的注册方法 |
| `test_mcpserver_api.py` | `MCPServer` 的 `tool` / `custom_route` 装饰器签名 |
| `test_mcpserver_import.py` | `pet_hospital_mcp.server` 模块能否被导入 |
| `test_mcpserver_import2.py` | 换 `PYTHONPATH` 后的导入行为对比 |
| `test_mcpserver_mod.py` | `mcp.server` 子模块的模块结构 |
| `test_mcpserver_mod2.py` | `mcp.server.fastmcp` 与 `MCPServer` 的对应关系 |

正式的自测请跑根目录下的 `test_*.py`（手动脚本）与
`PetHospitalMCP/pet-hospital-mcp` 的 `pytest`（66 项）。
