import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

import httpx
from sqlalchemy import Engine, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import DocumentVersion, Source, Tender, TenderDocument
from app.scrapers.records import DiscoveredDocument
from app.services.document_download import (
    DocumentDownloadError,
    DownloadedDocument,
    download_pdf,
    supported_pdf,
)
from app.services.ingestion import IdentityConflict
from app.services.pdf_text import ExtractionResult, extract_pdf

logger = logging.getLogger(__name__)


@dataclass
class DocumentResult:
    discovered: int = 0
    metadata_created: int = 0
    metadata_changed: int = 0
    metadata_unchanged: int = 0
    versions_created: int = 0
    content_unchanged: int = 0
    extracted: int = 0
    empty: int = 0
    failed: int = 0
    skipped: int = 0


@dataclass(frozen=True)
class PersistedMetadata:
    document_id: int
    outcome: Literal["created", "changed", "unchanged"]


def upsert_metadata(
    engine: Engine, record: DiscoveredDocument, observed_at: datetime
) -> PersistedMetadata | None:
    with Session(engine) as session, session.begin():
        # Serialize identity resolution even when the logical document is new.
        tender = session.scalar(
            select(Tender)
            .join(Source)
            .where(
                Source.slug == "contracts-finder",
                Source.is_active.is_(True),
                Tender.external_id == record.tender_external_id,
            )
            .with_for_update(of=Tender)
        )
        if tender is None:
            logger.warning(
                "Document skipped: active parent missing; ingest tenders first"
            )
            return None
        identities = [TenderDocument.source_url == str(record.source_url)]
        if record.source_document_id is not None:
            identities.append(
                TenderDocument.source_document_id == record.source_document_id
            )
        matches = session.scalars(
            select(TenderDocument).where(
                TenderDocument.tender_id == tender.id, or_(*identities)
            )
        ).all()
        if len(matches) > 1:
            raise IdentityConflict("Document ID and URL refer to different documents")
        document = matches[0] if matches else None
        if (
            document is not None
            and record.source_document_id is not None
            and document.source_document_id not in (None, record.source_document_id)
        ):
            raise IdentityConflict("Document URL already has a different source ID")
        values = record.model_dump(exclude={"tender_external_id"})
        values["source_url"] = str(record.source_url)
        outcome = "created"
        if document is None:
            document = TenderDocument(
                tender_id=tender.id,
                **values,
                first_seen_at=observed_at,
                last_seen_at=observed_at,
            )
            session.add(document)
        else:
            outcome = "unchanged"
            for field, value in values.items():
                if value is not None and getattr(document, field) != value:
                    setattr(document, field, value)
                    outcome = "changed"
            document.last_seen_at = observed_at
        session.flush()
        return PersistedMetadata(document.id, outcome)


def version_exists(engine: Engine, document_id: int, content_hash: str) -> bool:
    with Session(engine) as session:
        return (
            session.scalar(
                select(DocumentVersion.id).where(
                    DocumentVersion.document_id == document_id,
                    DocumentVersion.content_hash == content_hash,
                )
            )
            is not None
        )


def persist_version(
    engine: Engine,
    document_id: int,
    downloaded: DownloadedDocument,
    extraction: ExtractionResult,
) -> bool:
    with Session(engine) as session, session.begin():
        # Another process may have downloaded this hash while extraction ran.
        session.execute(
            select(TenderDocument.id)
            .where(TenderDocument.id == document_id)
            .with_for_update()
        ).scalar_one()
        existing = session.scalar(
            select(DocumentVersion.id).where(
                DocumentVersion.document_id == document_id,
                DocumentVersion.content_hash == downloaded.content_hash,
            )
        )
        if existing is not None:
            return False
        session.add(
            DocumentVersion(
                document_id=document_id,
                content_hash=downloaded.content_hash,
                byte_size=downloaded.byte_size,
                media_type=downloaded.media_type,
                storage_path=downloaded.storage_path,
                downloaded_at=downloaded.downloaded_at,
                extracted_text=extraction.text,
                extraction_status=extraction.status,
                extraction_error=extraction.error,
            )
        )
        return True


def process_documents(
    engine: Engine,
    client: httpx.Client,
    records: list[DiscoveredDocument],
    settings: Settings,
) -> DocumentResult:
    result = DocumentResult(discovered=len(records))
    for record in records:
        try:
            metadata = upsert_metadata(engine, record, datetime.now(UTC))
            if metadata is None:
                result.skipped += 1
                continue
            counter = f"metadata_{metadata.outcome}"
            setattr(result, counter, getattr(result, counter) + 1)
            if not supported_pdf(record):
                result.skipped += 1
                continue
            downloaded = download_pdf(
                client,
                str(record.source_url),
                settings.document_storage_dir,
                settings.document_max_bytes,
            )
            if version_exists(engine, metadata.document_id, downloaded.content_hash):
                result.content_unchanged += 1
                continue
            extraction = extract_pdf(
                settings.document_storage_dir / downloaded.storage_path,
                settings.document_max_pages,
            )
            if not persist_version(
                engine, metadata.document_id, downloaded, extraction
            ):
                result.content_unchanged += 1
                continue
            result.versions_created += 1
            setattr(result, extraction.status, getattr(result, extraction.status) + 1)
        except (DocumentDownloadError, IdentityConflict) as exc:
            result.failed += 1
            logger.warning("Document processing failed: %s", exc)
        except SQLAlchemyError as exc:
            result.failed += 1
            logger.error(
                "Document database operation rolled back (%s)", type(exc).__name__
            )
    return result
