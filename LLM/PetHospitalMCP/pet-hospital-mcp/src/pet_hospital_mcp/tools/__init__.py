"""MCP tools exposed by the Pet Hospital MCP service.

Adding a new tool means adding a module here and registering it in
``pet_hospital_mcp.server``. Each module is expected to expose a
``register(mcp, rest_client)`` coroutine or function that wires the tool
into the MCPServer.
"""

from . import list_pets  # noqa: F401  - re-export for convenience

__all__ = ["list_pets"]
