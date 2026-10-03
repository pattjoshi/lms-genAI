"""GET /health — is every service reachable? Shown as status dots on the login page."""

import asyncio

from fastapi import APIRouter
from neo4j import AsyncGraphDatabase
from qdrant_client import AsyncQdrantClient
from sqlalchemy import text

from app.config import get_settings
from app.db import engine
from app.llm.service import openai_breaker
from app.llm.tracing import tracing_enabled

router = APIRouter(tags=["health"])
TIMEOUT_S = 3


async def _check(coro) -> dict:
    try:
        await asyncio.wait_for(coro, TIMEOUT_S)
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}


async def _postgres():
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


async def _qdrant():
    client = AsyncQdrantClient(url=get_settings().qdrant_url, timeout=TIMEOUT_S)
    try:
        await client.get_collections()
    finally:
        await client.close()


async def _neo4j():
    s = get_settings()
    driver = AsyncGraphDatabase.driver(s.neo4j_uri, auth=(s.neo4j_user, s.neo4j_password))
    try:
        await driver.verify_connectivity()
    finally:
        await driver.close()


@router.get("/health")
async def health():
    s = get_settings()
    postgres, qdrant, neo4j = await asyncio.gather(_check(_postgres()), _check(_qdrant()), _check(_neo4j()))
    return {
        "postgres": postgres,
        "qdrant": qdrant,
        "neo4j": neo4j,
        # Config only — we don't spend tokens on a health check.
        "openai": {"ok": s.openai_api_key is not None, "model": s.openai_chat_model, "breaker": openai_breaker.state},
        "langfuse": {"ok": tracing_enabled(), "base_url": s.langfuse_base_url},
    }
