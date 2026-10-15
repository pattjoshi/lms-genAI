"""The MCP server over stdio, for desktop clients that launch it as a local program (M1).

    LMS_TOKEN=lms_... uv run python -m app.mcp_server       (from backend/)

The client starts this process and talks JSON-RPC over its stdin/stdout, so nothing may print to
stdout except MCP messages: logs go to stderr. There is no HTTP request to carry a token per call,
so the token is checked once at startup and every call acts as its user.
"""

import logging
import os
import sys

import anyio

from app.db import SessionLocal
from app.mcp_server import tokens
from app.mcp_server.server import local_identity, mcp


async def main() -> None:
    token = os.environ.get("LMS_TOKEN", "").strip()
    if not token:
        sys.exit("Set LMS_TOKEN to a personal access token (create one on the MCP access page).")
    async with SessionLocal() as session:
        identity = await tokens.verify(session, token)
    if identity is None:
        sys.exit("LMS_TOKEN is unknown or revoked. Create a new one on the MCP access page.")
    identity.via = "stdio"
    local_identity.set(identity)
    logging.getLogger("app").info("MCP stdio server for %s (%s)", identity.user.full_name, identity.user.role.value)
    await mcp.run_stdio_async()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(name)s: %(message)s")
    anyio.run(main)
