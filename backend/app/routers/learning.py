"""Students (and staff previewing): "I don't understand X" -> a study order (Phase 3b, S9 + S10 + S11).

The logic lives in app/graph/study.py, shared with the chat agent (Phase 4).
"""

from fastapi import APIRouter, HTTPException

from app.auth import CurrentUser, SessionDep
from app.graph import study

router = APIRouter(prefix="/learning-path", tags=["learning path"])


@router.get("/search")
async def search(q: str, session: SessionDep, user: CurrentUser, preview: bool = False):
    """Which concept does the student mean? Rules first; one embedding call only if they find nothing."""
    return await study.find_concepts(session, user, q, preview)


@router.get("")
async def learning_path(concept: str, session: SessionDep, user: CurrentUser, preview: bool = False):
    path = await study.build_path(session, user, concept, preview)
    if path is None:
        # Same answer for "doesn't exist" and "not yours": don't reveal other courses' concepts.
        raise HTTPException(404, "No published concept with that name in your courses.")
    return path
