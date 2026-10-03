"""Saving uploaded files and creating their `documents` row.

What happens when a teacher uploads a file that already exists in the course:

    same CONTENT (SHA-256) as a current file
        └─ that file failed before    -> RETRY: re-process the existing file
        └─ otherwise                  -> DUPLICATE: refuse (409)
    same NAME in the same module, different content (a new version of the notes)
        └─ replace not confirmed      -> ASK: refuse with "version_exists" so the UI can ask
        └─ old version still indexing -> refuse: wait until it finishes
        └─ replace confirmed          -> NEW VERSION (v2, v3...). The new version is indexed
                                         first; only then is the old one taken out of search
                                         (see pipeline.py), so students never hit a gap.
    otherwise                         -> NEW file
"""

import hashlib
import re
import uuid
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.ingest.parsers import ParseError, file_type_for
from app.models import Document, DocumentStatus

DONE_STATES = (DocumentStatus.ready, DocumentStatus.failed)


class UploadAction(StrEnum):
    NEW = "new"
    NEW_VERSION = "new_version"
    RETRY_FAILED = "retry_failed"
    DUPLICATE = "duplicate"
    ASK_REPLACE = "ask_replace"
    BUSY = "busy"


@dataclass
class Decision:
    action: UploadAction
    existing: Document | None = None


def decide_upload(same_content: Document | None, same_name: Document | None, replace: bool) -> Decision:
    """Pure decision logic (no I/O), so it is easy to unit-test. Inputs are CURRENT versions only."""
    if same_content is not None:
        if same_content.status == DocumentStatus.failed:
            return Decision(UploadAction.RETRY_FAILED, same_content)
        return Decision(UploadAction.DUPLICATE, same_content)
    if same_name is not None:
        if not replace:
            return Decision(UploadAction.ASK_REPLACE, same_name)
        if same_name.status not in DONE_STATES:
            return Decision(UploadAction.BUSY, same_name)
        return Decision(UploadAction.NEW_VERSION, same_name)
    return Decision(UploadAction.NEW)


class UploadRefused(Exception):
    """A refusal the teacher should see. `code` lets the UI react (e.g. ask to replace)."""

    def __init__(self, code: str, message: str, existing: Document | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.existing = existing


def _safe_name(file_name: str) -> str:
    """Keep only safe characters, so a name like '../../x' can't escape the upload folder."""
    name = Path(file_name).name
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)[:120] or "file"


async def store_upload(
    session: AsyncSession,
    *,
    data: bytes,
    file_name: str,
    course_id: int,
    module_id: int,
    uploaded_by: int,
    replace: bool = False,
) -> tuple[Document, UploadAction]:
    """Validate and save the upload. Returns the document to process and what happened.

    Raises ParseError (bad file) or UploadRefused (duplicate / needs confirmation / busy).
    """
    s = get_settings()
    file_type = file_type_for(file_name)  # raises ParseError for .doc / unsupported types
    if len(data) == 0:
        raise ParseError("The file is empty.")
    if len(data) > s.max_upload_mb * 1024 * 1024:
        raise ParseError(f"The file is larger than {s.max_upload_mb} MB.")

    name = Path(file_name).name
    digest = hashlib.sha256(data).hexdigest()
    current = (Document.course_id == course_id, Document.superseded_at.is_(None))
    same_content = await session.scalar(select(Document).where(*current, Document.sha256 == digest).limit(1))
    same_name = await session.scalar(
        select(Document).where(*current, Document.module_id == module_id, Document.file_name == name).limit(1)
    )
    decision = decide_upload(same_content, same_name, replace)
    existing = decision.existing

    if decision.action == UploadAction.DUPLICATE:
        raise UploadRefused(
            "duplicate_file", f"This exact file is already in this course as '{existing.file_name}'.", existing
        )
    if decision.action == UploadAction.ASK_REPLACE:
        raise UploadRefused(
            "version_exists",
            f"'{name}' already exists in this module (v{existing.version}) with different content.",
            existing,
        )
    if decision.action == UploadAction.BUSY:
        raise UploadRefused(
            "version_busy", f"'{name}' is still being processed. Wait until it is ready, then upload again.", existing
        )
    if decision.action == UploadAction.RETRY_FAILED:
        existing.status = DocumentStatus.uploaded
        existing.error = None
        await session.commit()
        return existing, decision.action

    s.upload_dir.mkdir(parents=True, exist_ok=True)
    path = s.upload_dir / f"{uuid.uuid4().hex[:12]}_{_safe_name(file_name)}"
    path.write_bytes(data)

    doc = Document(
        course_id=course_id,
        module_id=module_id,
        uploaded_by=uploaded_by,
        file_name=name,
        file_type=file_type,
        stored_path=str(path),
        sha256=digest,
        size_bytes=len(data),
        status=DocumentStatus.uploaded,
        version=existing.version + 1 if decision.action == UploadAction.NEW_VERSION else 1,
        replaces_id=existing.id if decision.action == UploadAction.NEW_VERSION else None,
    )
    session.add(doc)
    await session.commit()
    return doc, decision.action
