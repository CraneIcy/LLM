"""Command-line entry point for the Pet Hospital MCP service.

Run with:
    python -m pet_hospital_mcp

or (after install):
    pet-hospital-mcp
"""

from __future__ import annotations

import sys

from .config import load_settings
from .logging_config import configure_logging, get_logger
from .server import mcp


def main() -> None:
    settings = load_settings()
    configure_logging()
    logger = get_logger("main")
    logger.info(
        event="startup",
        mcp_host=settings.mcp_host,
        mcp_port=settings.mcp_port,
        pet_hospital_base_url=settings.pet_hospital_base_url,
    )
    try:
        mcp.run(
            transport="streamable-http",
            host=settings.mcp_host,
            port=settings.mcp_port,
        )
    except KeyboardInterrupt:
        logger.info(event="shutdown", reason="KeyboardInterrupt")
        sys.exit(0)


if __name__ == "__main__":
    main()
