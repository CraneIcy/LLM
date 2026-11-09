"""MCP tools exposed by the Pet Hospital MCP service.

Adding a new tool means adding a module here and registering it in
``pet_hospital_mcp.server``. Each module is expected to expose a
``register(mcp, rest_client)`` function that wires the tool into the
MCPServer.
"""

from . import get_pet_records, list_pets  # noqa: F401  - re-export for convenience

__all__ = ["get_pet_records", "list_pets"]
