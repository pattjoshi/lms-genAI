"""Students (and staff previewing): "I don't understand X" -> a study order (Phase 3b, S9 + S10).

Students see approved concepts of their enrolled courses only (the same course filter as RAG).
Teachers and admins can pass preview=true to see the path drafts would give, before approving.
"""

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.auth import CurrentUser, SessionDep
from app.config import get_settings
from app.graph import paths
from app.llm.service import embed_texts
from app.models import Course, Module, Role
from app.scopes import manageable_course_ids, readable_course_ids

router = APIRouter(prefix="/learning-path", tags=["learning path"])


async def _scope(session, user, preview: bool) -> tuple[list[int], list[str]]:
    """-> (courses, concept statuses) this user may see."""
    if preview and user.role in (Role.teacher, Role.admin):
        return await manageable_course_ids(session, user), ["draft", "approved"]
    return await readable_course_ids(session, user), ["approved"]


@router.get("/search")
async def search(q: str, session: SessionDep, user: CurrentUser, preview: bool = False):
    """Which concept does the student mean? Rules first; one embedding call only if they find nothing."""
    q = q.strip()[:200]
    if not q:
        return {"matches": [], "how": None}
    course_ids, statuses = await _scope(session, user, preview)
    candidates = await paths.searchable(course_ids, statuses)
    matches, how = paths.match_by_rules(q, candidates), "name"
    if not matches and candidates:
        embedded = await embed_texts(session, [q], feature="learning_path_search", user=user)
        matches = paths.match_by_embedding(embedded.vectors[0], candidates, get_settings().learning_path_min_similarity)
        how = "meaning"
    codes = dict((await session.execute(select(Course.id, Course.code).where(Course.id.in_(course_ids)))).all())
    return {
        "how": how,
        "matches": [
            {
                "uid": c.uid,
                "name": c.name,
                "definition": c.definition,
                "course_code": codes.get(c.course_id),
                "score": s,
            }
            for c, s in matches
        ],
    }


@router.get("")
async def learning_path(concept: str, session: SessionDep, user: CurrentUser, preview: bool = False):
    course_ids, statuses = await _scope(session, user, preview)
    graph = await paths.subgraph(concept, statuses)
    nodes = {n["uid"]: n for n in graph["nodes"]}
    target = nodes.get(concept)
    if target is None or target["course_id"] not in course_ids:
        # Same answer for "doesn't exist" and "not yours": don't reveal other courses' concepts.
        raise HTTPException(404, "No published concept with that name in your courses.")

    module_ids = {m["module_id"] for n in graph["nodes"] for m in n["materials"]}
    elsewhere = await paths.explained_elsewhere(
        [n["key"] for n in graph["nodes"] if not n["materials"]], course_ids, target["course_id"]
    )
    module_ids |= {m["module_id"] for ms in elsewhere.values() for m in ms}
    modules = {m.id: m for m in (await session.scalars(select(Module).where(Module.id.in_(module_ids or [-1])))).all()}
    courses = {c.id: c for c in (await session.scalars(select(Course).where(Course.id.in_(course_ids)))).all()}

    def where(m: dict) -> dict:
        module = modules.get(m["module_id"])
        course = courses.get(module.course_id) if module else None
        return {
            "file_name": m["file_name"],
            "course_code": course.code if course else None,
            "module_title": module.title if module else None,
            "pages": m.get("pages") or [],
            "section": m.get("section"),
        }

    # Ties in the study order are broken by where the concept appears in the course.
    def rank(n: dict) -> tuple:
        if not n["materials"]:
            return (0, 0, n["name"])  # explained nowhere here: background knowledge, so first
        first = min(
            n["materials"],
            key=lambda m: (modules[m["module_id"]].position if m["module_id"] in modules else 99, m.get("chunk") or 0),
        )
        module = modules.get(first["module_id"])
        return (module.position if module else 99, first.get("chunk") or 0, n["name"])

    order = paths.study_order(list(nodes), graph["edges"], {u: rank(n) for u, n in nodes.items()})
    needs: dict[str, list[str]] = {}
    for concept_uid, prereq in graph["edges"]:
        needs.setdefault(concept_uid, []).append(nodes[prereq]["name"])
    steps = [
        {
            "uid": u,
            "name": nodes[u]["name"],
            "definition": nodes[u]["definition"],
            "status": nodes[u]["status"],
            "is_target": u == concept,
            "needs": sorted(needs.get(u, [])),
            "materials": [where(m) for m in nodes[u]["materials"]],
            "elsewhere": [where(m) for m in elsewhere.get(nodes[u]["key"], [])],
        }
        for u in order
    ]
    course = courses.get(target["course_id"])
    return {
        "target": {"uid": concept, "name": target["name"], "course_code": course.code if course else None},
        "steps": steps,
    }
