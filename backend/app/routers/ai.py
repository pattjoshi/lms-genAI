"""POST /ai/hello — the first LLM call. Shows tokens, cost, latency and retries."""

from fastapi import APIRouter
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.auth import CurrentUser, SessionDep
from app.llm import service
from app.prompts.hello import HELLO_SYSTEM

router = APIRouter(prefix="/ai", tags=["ai"])


class HelloIn(BaseModel):
    message: str = Field(min_length=1, max_length=1000)


@router.post("/hello")
async def hello(body: HelloIn, session: SessionDep, user: CurrentUser):
    messages = [
        SystemMessage(HELLO_SYSTEM.format(role=user.role.value, name=user.full_name)),
        HumanMessage(body.message),
    ]
    result = await service.chat(session, messages=messages, feature="hello", user=user, max_tokens=120)
    return {
        "reply": result.text,
        "model": result.model,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "cost_usd": result.cost_usd,
        "latency_ms": result.latency_ms,
        "attempts": result.attempts,
    }
