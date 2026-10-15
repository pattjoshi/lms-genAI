"""The MCP server over Streamable HTTP, at POST /mcp on the FastAPI app (M1).

Streamable HTTP is the MCP spec's network transport: the client POSTs JSON-RPC messages to one URL and
gets JSON back (or an SSE stream when a tool streams). We run it stateless with JSON responses, so it
behaves like any small JSON API and survives restarts.

Auth: `Authorization: Bearer lms_...` (a personal access token, see tokens.py). This wrapper resolves
the token to a user before the MCP layer sees the request, and puts that identity on the request, where
the tools read it. No token, or a revoked one: 401, and the request never reaches a tool. The spec's
full answer is OAuth 2.1 (the client sends the user to a login page and gets a token); personal tokens
are the simple version, like GitHub's own MCP server with a PAT.
"""

import json
import logging

from starlette.types import ASGIApp, Receive, Scope, Send

from app.db import SessionLocal
from app.mcp_server import server, tokens

log = logging.getLogger("app.mcp")


class BearerAuth:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        header = dict(scope["headers"]).get(b"authorization", b"").decode("latin-1")
        token = header[7:].strip() if header[:7].lower() == "bearer " else ""
        identity = None
        if token:
            async with SessionLocal() as session:
                identity = await tokens.verify(session, token)
        if identity is None:
            await server._audit(None, "auth", {}, "refused", "missing or invalid token", 0)
            await _unauthorized(send, "missing" if not token else "invalid")
            return
        scope.setdefault("state", {})["lms_identity"] = identity  # read by server.current_identity()
        await self.app(scope, receive, send)


async def _unauthorized(send: Send, why: str) -> None:
    message = (
        "Send a personal access token: Authorization: Bearer lms_... (create one on the MCP access page)."
        if why == "missing"
        else "This token is unknown or revoked. Create a new one on the MCP access page."
    )
    body = json.dumps({"error": "unauthorized", "message": message}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json"),
                (b"www-authenticate", b'Bearer realm="lms-mcp"'),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


def mcp_endpoint() -> ASGIApp:
    """The ASGI app to mount at /mcp. Its session manager must run inside the FastAPI lifespan."""
    starlette_app = server.mcp.streamable_http_app()  # creates mcp.session_manager
    handler = starlette_app.routes[0].endpoint  # the StreamableHTTP handler, without Starlette's routing
    return BearerAuth(handler)
