"""MCP access page (Phase 4b, M2 + M11): personal access tokens and the MCP audit log.

Every role gets tokens; what a token can do is decided by its user's role, call by call. Users see
their own calls; admins see everyone's (the audit log).
"""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.auth import CurrentUser, SessionDep
from app.mcp_server import tokens as svc
from app.mcp_server.server import mcp
from app.models import ApiToken, McpCall, Role, User

router = APIRouter(prefix="/mcp-access", tags=["mcp"])


def _token_out(t: ApiToken) -> dict:
    return {
        "id": t.id,
        "name": t.name,
        "prefix": t.prefix,
        "created_at": t.created_at,
        "last_used_at": t.last_used_at,
        "revoked": t.revoked_at is not None,
    }


@router.get("")
async def overview(request: Request, session: SessionDep, user: CurrentUser):
    rows = (
        await session.scalars(select(ApiToken).where(ApiToken.user_id == user.id).order_by(ApiToken.id.desc()))
    ).all()
    calls = select(McpCall, User.full_name).outerjoin(User, User.id == McpCall.user_id)
    if user.role != Role.admin:
        calls = calls.where(McpCall.user_id == user.id)  # scope: OWN (admins: ALL)
    recent = (await session.execute(calls.order_by(McpCall.id.desc()).limit(30))).all()
    tools = await mcp.list_tools()
    return {
        "url": str(request.base_url).rstrip("/") + "/mcp",
        "tokens": [_token_out(t) for t in rows],
        "tools": [
            {
                "name": t.name,
                "description": (t.description or "").strip().split("\n")[0],
                "read_only": bool(t.annotations and t.annotations.readOnlyHint),
            }
            for t in tools
        ],
        "calls": [
            {
                "id": c.id,
                "at": c.created_at,
                "user": name,
                "via": c.via,
                "name": c.name,
                "arguments": c.arguments,
                "status": c.status,
                "error": c.error,
                "latency_ms": c.latency_ms,
            }
            for c, name in recent
        ],
    }


class TokenIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)


@router.post("/tokens")
async def create_token(body: TokenIn, session: SessionDep, user: CurrentUser):
    row, token = await svc.create(session, user, body.name)
    await session.commit()
    return {**_token_out(row), "token": token}  # the only time the full token leaves the server


@router.delete("/tokens/{token_id}")
async def revoke_token(token_id: int, session: SessionDep, user: CurrentUser):
    row = await session.get(ApiToken, token_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(404, "Token not found.")
    if row.revoked_at is None:
        row.revoked_at = datetime.now(UTC)
        await session.commit()
    return _token_out(row)
