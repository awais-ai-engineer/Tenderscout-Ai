import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import Engine, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import Source, Tender
from app.schemas.source import SourceCreate
from app.scrapers.records import ParsedListing, ScrapedTender

logger = logging.getLogger(__name__)


@dataclass
class IngestionResult:
    discovered: int
    created: int = 0
    changed: int = 0
    unchanged: int = 0
    failed: int = 0
    skipped: int = 0


class InactiveSourceError(ValueError):
    pass


class IdentityConflict(ValueError):
    pass


def find_existing(
    session: Session, source_id: int, record: ScrapedTender
) -> Tender | None:
    identities = [Tender.source_url == str(record.source_url)]
    if record.external_id is not None:
        identities.append(Tender.external_id == record.external_id)
    matches = session.scalars(
        select(Tender)
        .where(Tender.source_id == source_id, or_(*identities))
        .with_for_update()
    ).all()
    if len(matches) > 1:
        raise IdentityConflict("External ID and URL refer to different tenders")
    if not matches:
        return None
    existing = matches[0]
    if (
        record.external_id is not None
        and existing.external_id is not None
        and record.external_id != existing.external_id
    ):
        raise IdentityConflict("URL is already assigned to a different external ID")
    return existing


def persist_record(
    session: Session,
    source_id: int,
    record: ScrapedTender,
    observed_at: datetime,
) -> Literal["created", "changed", "unchanged"]:
    existing = find_existing(session, source_id, record)
    values = record.model_dump()
    values["source_url"] = str(record.source_url)
    if existing is None:
        session.add(
            Tender(
                source_id=source_id,
                **values,
                first_seen_at=observed_at,
                last_seen_at=observed_at,
            )
        )
        return "created"
    changed = False
    for name, value in values.items():
        if value is not None and getattr(existing, name) != value:
            setattr(existing, name, value)
            changed = True
    existing.last_seen_at = observed_at
    return "changed" if changed else "unchanged"


def ingest_tenders(
    engine: Engine,
    source: SourceCreate,
    listing: ParsedListing,
) -> IngestionResult:
    result = IngestionResult(
        discovered=listing.discovered,
        failed=listing.failed,
        skipped=listing.skipped,
    )
    try:
        with Session(engine) as session, session.begin():
            session.execute(
                insert(Source)
                .values(
                    name=source.name,
                    slug=source.slug,
                    base_url=str(source.base_url),
                    is_active=source.is_active,
                )
                .on_conflict_do_nothing(index_elements=[Source.slug])
            )
            # Serialize this adapter's runs before resolving either tender identity.
            stored_source = session.scalars(
                select(Source).where(Source.slug == source.slug).with_for_update()
            ).one()
            if not stored_source.is_active:
                raise InactiveSourceError(
                    "Source is inactive; ingestion was not committed"
                )
            observed_at = datetime.now(UTC)
            for record in listing.records:
                try:
                    outcome = persist_record(
                        session, stored_source.id, record, observed_at
                    )
                except IdentityConflict as error:
                    result.failed += 1
                    logger.warning(
                        "event=identity_conflict source=%s external_id=%s reason=%s",
                        source.slug,
                        record.external_id,
                        error,
                    )
                    continue
                if outcome == "created":
                    result.created += 1
                elif outcome == "changed":
                    result.changed += 1
                else:
                    result.unchanged += 1
            stored_source.last_scraped_at = observed_at
    except SQLAlchemyError as error:
        logger.error(
            "event=ingestion_rolled_back source=%s error=%s",
            source.slug,
            type(error).__name__,
        )
        raise
    logger.info(
        "event=ingestion_complete source=%s discovered=%d created=%d "
        "changed=%d unchanged=%d failed=%d skipped=%d",
        source.slug,
        result.discovered,
        result.created,
        result.changed,
        result.unchanged,
        result.failed,
        result.skipped,
    )
    return result
