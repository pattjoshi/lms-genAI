"""Saving uploaded files and creating their `documents` row."""

import hashlib
import re
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.ingest.parsers import ParseError, file_type_for
from app.models import Document, DocumentStatus


class DuplicateFile(Exception):
    def __init__(self, existing: Document):
        super().__init__(f"This file was already uploaded to this course as '{existing.file_name}'.")
        self.existing = existing


def _safe_name(file_name: str) -> str:
    """Keep only safe characters, so a name like '../../x' can't escape the upload folder."""
    name = Path(file_name).name
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)[:120] or "file"


async def store_upload(
    session: AsyncSession, *, data: bytes, file_name: str, course_id: int, module_id: int, uploaded_by: int
) -> Document:
    """Validate, save to disk and create the Document row (status = uploaded)."""
    s = get_settings()
    file_type = file_type_for(file_name)  # raises ParseError for .doc / unsupported types
    if len(data) == 0:
        raise ParseError("The file is empty.")
    if len(data) > s.max_upload_mb * 1024 * 1024:
        raise ParseError(f"The file is larger than {s.max_upload_mb} MB.")

    digest = hashlib.sha256(data).hexdigest()
    existing = await session.scalar(select(Document).where(Document.course_id == course_id, Document.sha256 == digest))
    if existing is not None:
        raise DuplicateFile(existing)

    s.upload_dir.mkdir(parents=True, exist_ok=True)
    path = s.upload_dir / f"{uuid.uuid4().hex[:12]}_{_safe_name(file_name)}"
    path.write_bytes(data)

    doc = Document(
        course_id=course_id,
        module_id=module_id,
        uploaded_by=uploaded_by,
        file_name=Path(file_name).name,
        file_type=file_type,
        stored_path=str(path),
        sha256=digest,
        size_bytes=len(data),
        status=DocumentStatus.uploaded,
    )
    session.add(doc)
    await session.commit()
    return doc
