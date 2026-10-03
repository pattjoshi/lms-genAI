"""What happens when a teacher uploads a file that already exists (storage.decide_upload)."""

from app.ingest.storage import UploadAction, decide_upload
from app.models import Document, DocumentStatus
from app.schema import UPGRADES


def doc(status=DocumentStatus.ready, version=1) -> Document:
    return Document(id=1, file_name="notes.pdf", status=status, version=version)


def test_new_file():
    assert decide_upload(None, None, replace=False).action == UploadAction.NEW


def test_same_content_is_a_duplicate():
    assert decide_upload(doc(), None, replace=False).action == UploadAction.DUPLICATE
    # Replacing a file with an identical copy is pointless, so it's still a duplicate.
    assert decide_upload(doc(), None, replace=True).action == UploadAction.DUPLICATE


def test_same_content_that_failed_is_retried():
    decision = decide_upload(doc(DocumentStatus.failed), None, replace=False)
    assert decision.action == UploadAction.RETRY_FAILED


def test_same_name_new_content_asks_first():
    assert decide_upload(None, doc(), replace=False).action == UploadAction.ASK_REPLACE


def test_confirmed_replace_creates_new_version():
    decision = decide_upload(None, doc(version=2), replace=True)
    assert decision.action == UploadAction.NEW_VERSION
    assert decision.existing.version == 2


def test_cannot_replace_while_old_version_is_processing():
    assert decide_upload(None, doc(DocumentStatus.embedding), replace=True).action == UploadAction.BUSY


def test_failed_old_version_can_be_replaced():
    assert decide_upload(None, doc(DocumentStatus.failed), replace=True).action == UploadAction.NEW_VERSION


def test_schema_upgrades_are_idempotent():
    # They run on every start, so each must be safe to run again.
    assert all("IF NOT EXISTS" in sql for sql in UPGRADES)
