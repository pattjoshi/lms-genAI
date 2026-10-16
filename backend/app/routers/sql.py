"""Ask the data (Phase 6): every role, each within its own scope.

GET  /sql/scope     what the agent can see for you: the scope per kind of data, and the tables
POST /sql/ask       a question in plain English -> SQL, rows, answer, chart (S16, T12, T15, A1-A3)
GET  /sql/history   your last questions

There is no role check here on purpose: a student may ask too. What each role gets back is decided by
the database (row-level security for the read-only user), not by this file.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import schema
from app.auth import CurrentUser, SessionDep
from app.sql_agent import agent
from app.sql_agent.access import AGENT_TABLES
from app.sql_agent.describe import scope_summary

router = APIRouter(prefix="/sql", tags=["sql agent"])


class Ask(BaseModel):
    question: str = Field(min_length=3, max_length=500)


def _not_ready() -> None:
    if schema.sql_access_error:
        raise HTTPException(
            503,
            "The SQL agent isn't set up: the backend could not create its read-only database user. "
            f"({schema.sql_access_error[:200]})",
        )


@router.get("/scope")
async def scope(user: CurrentUser):
    return {
        "role": user.role.value,
        "scope": scope_summary(user.role),
        "tables": [{"name": t.name, "who": t.who} for t in AGENT_TABLES],
        "ready": schema.sql_access_error is None,
        "error": schema.sql_access_error,
    }


@router.post("/ask")
async def ask(body: Ask, session: SessionDep, user: CurrentUser):
    _not_ready()
    out = await agent.ask(session, user, body.question.strip())
    await session.commit()
    return out


@router.get("/history")
async def history(session: SessionDep, user: CurrentUser, limit: int = 20):
    return await agent.history(session, user, min(max(limit, 1), 50))
