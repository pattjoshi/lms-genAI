"""The chat agent as a LangGraph state machine (Phase 4).

    START ─▶ memory ─▶ route ─┬─▶ doubt ─────────────▶ END     RAG answer with citations (Phase 1-2)
                              ├─▶ learning_path ─┬───▶ END     study order (Phase 3)
                              │                  └─▶ doubt     no such concept: answer the question instead
                              ├─▶ practice ──────────▶ END     3 checked practice questions
                              ├─▶ progress ──────────▶ END     weak topics from memory
                              ├─▶ support ───────────▶ END     own login / payment records
                              └─▶ assistant ─────────▶ END     tool-calling loop over our MCP tools (4b)

Why a fixed graph and not a free "ReAct" agent that picks tools in a loop: every path here is known,
so a graph is cheaper (no LLM call to decide what to do next), faster, testable node by node, and it
can't loop. The one decision that needs judgement, which branch, is made by the router, cheapest
method first. Only open, multi-step requests go to the `assistant` branch (Phase 4b), a bounded
tool-calling loop whose tools come from our own MCP server (app/agent/assistant.py).

Nodes talk to the browser through LangGraph's stream writer: each `emit(event, data)` becomes one
Server-Sent Event (route, sources, token, card), and chat.py adds `done` at the end.
"""

from typing import Any, TypedDict

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import assistant as assistant_svc
from app.agent import practice as practice_svc
from app.agent import support as support_svc
from app.agent.intents import Intent
from app.agent.memory import WeakTopic, remember, weak_topics
from app.agent.router import Route, route
from app.config import get_settings
from app.graph import study
from app.llm.service import StreamStats, chat_stream
from app.models import Course, Doubt, Role, User
from app.prompts.rag_answer import NO_ANSWER
from app.rag.answer import confidence, rag_messages
from app.rag.retriever import retrieve


class ChatState(TypedDict, total=False):
    # input
    session: AsyncSession
    user: User
    question: str
    conversation_id: str | None
    course_id: int | None
    module_id: int | None
    history: list[tuple[str, str]]
    doubt: Doubt  # the row saved for this message; nodes fill it in
    # filled by nodes
    weak: list[WeakTopic]
    route: Route
    fallback: str | None
    usage: dict[str, Any]


def emit(event: str, data: dict) -> None:
    get_stream_writer()((event, data))


def say(text: str) -> None:
    """Non-RAG nodes answer with fixed text; sent as one token so the browser treats it like an answer."""
    emit("token", {"text": text})


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


async def load_memory(state: ChatState) -> dict:
    user = state["user"]
    weak = await weak_topics(state["session"], user) if user.role == Role.student else []
    return {"weak": weak}


async def route_node(state: ChatState) -> dict:
    r = await route(state["session"], state["user"], state["question"])
    state["doubt"].intent = r.intent.value
    state["doubt"].route = r.out()
    emit("route", r.out())
    return {"route": r, "usage": {"cost_usd": r.cost_usd}}


def pick_branch(state: ChatState) -> str:
    return state["route"].intent.value


async def learning_path_node(state: ChatState) -> dict:
    session, user, topic = state["session"], state["user"], state["route"].topic
    found = await study.find_concepts(session, user, topic or "")
    clear = study.clear_match(found["matches"])
    if not found["matches"]:
        # Not a concept in the graph ("I don't understand why my loop never ends"): it's a question.
        return {"fallback": f"No published concept matches “{topic}”, so I answered it as a question."}
    doubt = state["doubt"]
    doubt.status = "answered"
    if clear is None:
        say("Which of these do you mean? Pick one to see what to study first, in order.")
        emit("card", {"kind": "choose_concept", "topic": topic, "matches": found["matches"]})
        doubt.answer = "Asked to pick a concept: " + ", ".join(m["name"] for m in found["matches"])
        return {}
    path = await study.build_path(session, user, clear["uid"])
    if path is None:
        return {"fallback": f"No published concept matches “{topic}”, so I answered it as a question."}
    await remember(session, user, path["target"]["name"], "asked_path")
    todo = [s for s in path["steps"] if not s["known"] and not s["is_target"]]
    known = [s for s in path["steps"] if s["known"]]
    if todo:
        text = f"To understand {path['target']['name']}, study these first, in this order: " + ", ".join(
            s["name"] for s in todo
        )
    else:
        text = f"{path['target']['name']} has no prerequisites you still need. Start with it directly."
    if known:
        them = "them" if len(known) > 1 else "it"
        text += f". You can skip {', '.join(s['name'] for s in known)}: your quiz scores show you know {them}."
    text += " Each step below links to the file and page that explains it."
    say(text)
    emit("card", {"kind": "path", "path": path})
    doubt.answer = text
    return {}


def after_path(state: ChatState) -> str:
    return "doubt" if state.get("fallback") else END


async def practice_node(state: ChatState) -> dict:
    session, user, doubt = state["session"], state["user"], state["doubt"]
    topic = state["route"].topic
    if not topic and state.get("weak"):
        topic = state["weak"][0].name  # S13: practise the weakest topic
    if not topic:
        text = "Tell me what to practise, for example “quiz me on gradient descent”. I don't know your weak topics yet."
        say(text)
        doubt.answer, doubt.status = text, "answered"
        return {}
    try:
        practice = await practice_svc.create_set(session, user, topic)
    except practice_svc.PracticeError as exc:
        say(exc.message)
        doubt.answer, doubt.status = exc.message, "no_context"
        return {}
    course = await session.get(Course, practice.course_id)
    why = "" if state["route"].topic else " (your weakest topic)"
    text = (
        f"Here are {len(practice.questions)} practice questions on {practice.topic}{why}. "
        "Pick an answer for each: you'll see if it's right, why, and where to read about it."
    )
    say(text)
    emit("card", {"kind": "practice", "practice": practice_svc.public(practice, course.code if course else None)})
    doubt.answer, doubt.status = text, "answered"
    usage = dict(state.get("usage") or {})
    usage["cost_usd"] = usage.get("cost_usd", 0.0) + practice.cost_usd
    return {"usage": usage}


async def progress_node(state: ChatState) -> dict:
    weak, doubt = state.get("weak") or [], state["doubt"]
    if not weak:
        text = (
            "I don't know any weak topics of yours yet. They come from your quiz scores, from topics you tell me "
            "you don't understand, and from practice questions you get wrong."
        )
    else:
        names = ", ".join(w.name for w in weak[:3])
        text = (
            f"I'd work on {names}{' and more' if len(weak) > 3 else ''}. Below is each topic and why I think so, "
            "with a study path and practice questions for it."
        )
    say(text)
    emit(
        "card",
        {"kind": "progress", "weak": [{"name": w.name, "course_code": w.course_code, "why": w.why} for w in weak]},
    )
    doubt.answer, doubt.status = text, "answered"
    return {}


async def support_node(state: ChatState) -> dict:
    text, facts = await support_svc.answer(state["session"], state["user"], state["question"])
    say(text)
    emit("card", {"kind": "support", "facts": facts})
    state["doubt"].answer, state["doubt"].status = text, "answered"
    return {}


async def assistant_node(state: ChatState) -> dict:
    session, user, doubt = state["session"], state["user"], state["doubt"]

    def on_step(step: assistant_svc.ToolStep) -> None:
        emit("tool", {"name": step.name, "args": step.args, "ok": step.ok})
        card = tool_card(step)
        if card:
            emit("card", card)

    run = await assistant_svc.run(session, user, state["question"], on_step=on_step)
    say(run.answer)
    doubt.answer, doubt.status = run.answer, "answered"
    usage = dict(state.get("usage") or {})
    usage.update(
        input_tokens=run.input_tokens,
        output_tokens=run.output_tokens,
        cost_usd=usage.get("cost_usd", 0.0) + run.cost_usd,
        agent_steps=[{"name": s.name, "args": s.args, "ok": s.ok} for s in run.steps],
        llm_calls=run.llm_calls,
    )
    if run.notes_error:
        emit("tool", {"name": "notes", "args": {}, "ok": False, "error": run.notes_error})
    return {"usage": usage}


def tool_card(step: assistant_svc.ToolStep) -> dict | None:
    """Show what a tool found as the same card the fixed branches use (path, practice, progress)."""
    data = step.structured
    if not step.ok or not data:
        return None
    if step.name == "get_learning_path" and data.get("found"):
        return {"kind": "path", "path": data["path"]}
    if step.name == "practice_questions":
        questions = [{**q, "difficulty": ""} for q in data["questions"]]
        practice = {"id": data["practice_id"], "topic": data["topic"], "course_code": data["course_code"]}
        return {"kind": "practice", "practice": {**practice, "questions": questions}}
    if step.name == "my_weak_topics" and data.get("weak_topics"):
        weak = [{"name": w["topic"], "course_code": w["course_code"], "why": w["why"]} for w in data["weak_topics"]]
        return {"kind": "progress", "weak": weak}
    return None


async def doubt_node(state: ChatState) -> dict:
    """The Phase 1-2 RAG answer: retrieve (rewrite, hybrid, rerank, corrective retry) then stream."""
    s = get_settings()
    session, user, question, doubt = state["session"], state["user"], state["question"], state["doubt"]
    if state.get("fallback"):
        emit("route", {**state["route"].out(), "intent": "doubt", "fallback": state["fallback"]})
        doubt.intent = "doubt"
    retrieval = await retrieve(
        session,
        user,
        question,
        course_ids=[state["course_id"]] if state.get("course_id") else None,
        module_id=state.get("module_id"),
        history=state.get("history") or [],
    )
    doubt.sources = [{k: v for k, v in x.items() if k != "text"} for x in retrieval.sources]
    doubt.top_score = retrieval.top_score
    doubt.top_rerank_score = retrieval.top_rerank_score
    searched = retrieval.retried_with or retrieval.query
    doubt.search_query = searched if searched != question else None
    emit(
        "sources",
        {
            "sources": retrieval.sources,
            "min_score": s.rag_min_score,
            "min_rerank_score": s.rag_min_rerank_score,
            "retrieval": retrieval.details(),
        },
    )

    stats, answer = StreamStats(), ""
    used = [x for x in retrieval.sources if x["used"]]
    if not used:
        # Nothing relevant: don't call the LLM at all (saves cost, prevents guessing).
        answer, doubt.status = NO_ANSWER, "no_context"
        say(answer)
    else:
        weak = [w.name for w in state.get("weak") or []]
        try:
            async for piece in chat_stream(
                session,
                messages=rag_messages(user, question, retrieval, weak),
                feature="rag_answer",
                user=user,
                stats=stats,
                max_tokens=s.rag_max_output_tokens,
            ):
                answer += piece
                emit("token", {"text": piece})
        finally:
            doubt.answer = answer or None
        doubt.status = "no_context" if answer.strip().startswith(NO_ANSWER) else "answered"
    doubt.answer = answer

    usage = dict(state.get("usage") or {})
    usage.update(
        model=stats.model or None,
        input_tokens=stats.input_tokens + retrieval.llm_input_tokens,
        output_tokens=stats.output_tokens + retrieval.llm_output_tokens,
        embed_tokens=retrieval.embed_tokens,
        cost_usd=usage.get("cost_usd", 0.0) + stats.cost_usd + retrieval.cost_usd,
        retrieval_cost_usd=retrieval.cost_usd,
        first_token_ms=stats.first_token_ms,
        attempts=stats.attempts,
        top_score=retrieval.top_score,
        relevance=retrieval.relevance(),
        confidence=confidence(retrieval.relevance()) if used else None,
    )
    return {"usage": usage}


# ---------------------------------------------------------------------------
# The graph
# ---------------------------------------------------------------------------


def build_graph():
    g = StateGraph(ChatState)
    g.add_node("memory", load_memory)
    g.add_node("route", route_node)
    g.add_node("doubt", doubt_node)
    g.add_node("learning_path", learning_path_node)
    g.add_node("practice", practice_node)
    g.add_node("progress", progress_node)
    g.add_node("support", support_node)
    g.add_node("assistant", assistant_node)
    g.add_edge(START, "memory")
    g.add_edge("memory", "route")
    g.add_conditional_edges("route", pick_branch, {i.value: i.value for i in Intent})
    g.add_conditional_edges("learning_path", after_path, {"doubt": "doubt", END: END})
    for node in ("doubt", "practice", "progress", "support", "assistant"):
        g.add_edge(node, END)
    return g.compile()


agent = build_graph()


async def previous_turns(session: AsyncSession, user: User, conversation_id: str | None, limit: int) -> list:
    """Earlier course questions of this chat (short-term memory), oldest first: [(question, answer)]."""
    if not conversation_id:
        return []
    rows = (
        await session.scalars(
            select(Doubt)
            .where(
                Doubt.student_id == user.id,
                Doubt.conversation_id == conversation_id,
                Doubt.hidden_at.is_(None),
                Doubt.status.in_(["answered", "no_context"]),
                (Doubt.intent.is_(None)) | (Doubt.intent == "doubt"),  # a quiz card isn't context for RAG
            )
            .order_by(Doubt.id.desc())
            .limit(limit)
        )
    ).all()
    return [(d.question, d.answer or "") for d in reversed(rows)]
