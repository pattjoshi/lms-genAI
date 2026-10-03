"""Teacher (own courses) and admin (all courses): upload, list, preview, delete course files."""

from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.auth import SessionDep, require_roles
from app.ingest.parsers import ParseError
from app.ingest.pipeline import process_document
from app.ingest.storage import UploadAction, UploadRefused, store_upload
from app.models import Chunk, Course, Document, DocumentStatus, Module, Role, User
from app.permissions import PermissionDenied
from app.rag import vectorstore
from app.scopes import manageable_course_ids

router = APIRouter(prefix="/documents", tags=["documents"])
Manager = Depends(require_roles(Role.teacher, Role.admin))


def _doc_out(d: Document, course: Course | None = None, module: Module | None = None) -> dict:
    return {
        "id": d.id,
        "file_name": d.file_name,
        "file_type": d.file_type,
        "size_bytes": d.size_bytes,
        "status": d.status.value,
        "error": d.error,
        "num_pages": d.num_pages,
        "num_chunks": d.num_chunks,
        "embed_tokens": d.embed_tokens,
        "embed_cost_usd": d.embed_cost_usd,
        "course_code": course.code if course else None,
        "module_title": module.title if module else None,
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "version": d.version,
        "replaces_id": d.replaces_id,
    }


async def _get_managed_doc(session, user: User, document_id: int) -> Document:
    doc = await session.get(Document, document_id)
    if doc is None:
        raise HTTPException(404, "File not found.")
    if doc.course_id not in await manageable_course_ids(session, user):
        raise PermissionDenied("You can only manage files of your own courses.")
    return doc


@router.get("/options")
async def upload_options(session: SessionDep, user: User = Manager):
    """Courses (with modules) this user may upload to — fills the upload form."""
    ids = await manageable_course_ids(session, user)
    courses = (await session.scalars(select(Course).where(Course.id.in_(ids)).order_by(Course.code))).all()
    out = []
    for c in courses:
        modules = (
            await session.scalars(select(Module).where(Module.course_id == c.id).order_by(Module.position))
        ).all()
        out.append(
            {"id": c.id, "code": c.code, "title": c.title, "modules": [{"id": m.id, "title": m.title} for m in modules]}
        )
    return out


@router.get("")
async def list_documents(session: SessionDep, user: User = Manager):
    ids = await manageable_course_ids(session, user)
    rows = (
        await session.execute(
            select(Document, Course, Module)
            .join(Course, Course.id == Document.course_id)
            .join(Module, Module.id == Document.module_id)
            .where(Document.course_id.in_(ids), Document.superseded_at.is_(None))  # current versions only
            .order_by(Document.id.desc())
        )
    ).all()
    return [_doc_out(d, c, m) for d, c, m in rows]


@router.post("", status_code=202)
async def upload_document(
    session: SessionDep,
    background: BackgroundTasks,
    file: UploadFile = File(...),
    course_id: int = Form(...),
    module_id: int = Form(...),
    replace: bool = Form(False),  # teacher confirmed: replace the file with the same name
    user: User = Manager,
):
    if course_id not in await manageable_course_ids(session, user):
        raise PermissionDenied("You can only upload to your own courses.")
    module = await session.get(Module, module_id)
    if module is None or module.course_id != course_id:
        raise HTTPException(400, "That module doesn't belong to the selected course.")

    data = await file.read()
    try:
        doc, action = await store_upload(
            session,
            data=data,
            file_name=file.filename or "file",
            course_id=course_id,
            module_id=module_id,
            uploaded_by=user.id,
            replace=replace,
        )
    except ParseError as exc:
        raise HTTPException(415, str(exc)) from exc
    except UploadRefused as exc:
        # A machine-readable code lets the UI react, e.g. ask "Replace v1 with this version?"
        existing = exc.existing
        return JSONResponse(
            status_code=409,
            content={
                "error": exc.code,
                "message": exc.message,
                "existing": {"id": existing.id, "file_name": existing.file_name, "version": existing.version}
                if existing
                else None,
            },
        )

    # 202 Accepted: the file is saved; processing continues after the response is sent.
    background.add_task(process_document, doc.id)
    notes = {
        UploadAction.RETRY_FAILED: "This file had failed before, so it is being processed again.",
        UploadAction.NEW_VERSION: f"Uploaded as v{doc.version}. The old version stays live until this one is ready.",
    }
    return {**_doc_out(doc), "action": action.value, "note": notes.get(action)}


@router.post("/{document_id}/reprocess", status_code=202)
async def reprocess(document_id: int, session: SessionDep, background: BackgroundTasks, user: User = Manager):
    doc = await _get_managed_doc(session, user, document_id)
    if doc.superseded_at is not None:
        raise HTTPException(409, "This is an old version that was replaced. Re-process the current version instead.")
    if doc.status not in (DocumentStatus.ready, DocumentStatus.failed):
        raise HTTPException(409, "This file is still being processed.")
    doc.status = DocumentStatus.uploaded
    await session.commit()
    background.add_task(process_document, doc.id)
    return _doc_out(doc)


@router.get("/{document_id}/chunks")
async def document_chunks(document_id: int, session: SessionDep, user: User = Manager):
    """What the AI 'sees' for this file: every chunk with its page/section and tags."""
    doc = await _get_managed_doc(session, user, document_id)
    chunks = (await session.scalars(select(Chunk).where(Chunk.document_id == doc.id).order_by(Chunk.chunk_index))).all()
    return {
        "document": _doc_out(doc),
        "chunks": [
            {
                "index": c.chunk_index,
                "text": c.text,
                "chars": len(c.text),
                "page": c.page,
                "section": c.section,
                "topic": c.topic,
                "difficulty": c.difficulty,
                "topic_score": c.topic_score,
            }
            for c in chunks
        ],
    }


@router.delete("/{document_id}", status_code=204)
async def delete_document(document_id: int, session: SessionDep, user: User = Manager):
    """Delete a file together with all its older versions."""
    doc = await _get_managed_doc(session, user, document_id)
    versions = [doc]
    while versions[-1].replaces_id:
        older = await session.get(Document, versions[-1].replaces_id)
        if older is None:
            break
        versions.append(older)
    # Order matters: remove vectors first, so a half-finished delete never leaves
    # searchable chunks that point to a file that no longer exists.
    for d in versions:
        await vectorstore.delete_document(d.id)
    for d in versions:  # newest first, so no row is deleted while a newer one still points at it
        await session.delete(d)  # chunks are removed by ON DELETE CASCADE
        await session.flush()
    await session.commit()
    for d in versions:
        Path(d.stored_path).unlink(missing_ok=True)
