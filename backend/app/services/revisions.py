from datetime import datetime

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.models import Tender, TenderMetadataChangeSet, TenderRevision
from app.services import change_rules
from app.services.change_rules import BUSINESS_FIELDS, metadata_diff, snapshot_hash


def business_state(row: Tender | TenderRevision) -> dict:
    return {
        name: getattr(
            row,
            "content_hash"
            if name == "source_content_hash" and isinstance(row, Tender)
            else name,
        )
        for name in BUSINESS_FIELDS
    }


def ensure_baseline(session: Session, tender: Tender) -> TenderRevision:
    """Caller holds the tender/source lock; capture only the previously stored state."""
    previous = session.scalar(
        select(TenderRevision)
        .where(TenderRevision.tender_id == tender.id)
        .order_by(TenderRevision.revision_index.desc())
        .limit(1)
    )
    if previous is not None:
        return previous
    state = business_state(tender)
    baseline = TenderRevision(
        tender_id=tender.id,
        revision_index=1,
        snapshot_hash=snapshot_hash(state),
        **state,
        observed_at=tender.last_seen_at,
    )
    session.add(baseline)
    session.flush()
    return baseline


def capture_revision(
    session: Session, tender: Tender, previous: TenderRevision, observed_at: datetime
) -> TenderRevision:
    state = business_state(tender)
    digest = snapshot_hash(state)
    if digest == previous.snapshot_hash:
        return previous
    revision = TenderRevision(
        tender_id=tender.id,
        revision_index=previous.revision_index + 1,
        snapshot_hash=digest,
        **state,
        observed_at=observed_at,
    )
    session.add(revision)
    session.flush()
    changes = metadata_diff(business_state(previous), state)
    session.add(
        TenderMetadataChangeSet(
            tender_id=tender.id,
            from_revision_id=previous.id,
            to_revision_id=revision.id,
            changeset_version=change_rules.CHANGESET_VERSION,
            has_changes=bool(changes),
            change_count=len(changes),
            changed_fields=[change["field"] for change in changes],
            changes=changes,
        )
    )
    return revision


def revision_history(
    engine: Engine, tender_id: int, *, after_index: int = 0, limit: int = 100
) -> list[dict]:
    if after_index < 0 or not 1 <= limit <= 100:
        raise ValueError("History requires nonnegative cursor and limit 1 to 100")
    with Session(engine) as session:
        if session.get(Tender, tender_id) is None:
            raise ValueError("Tender does not exist")
        rows = (
            session.execute(
                select(
                    TenderRevision.id,
                    TenderRevision.revision_index,
                    TenderRevision.observed_at,
                    TenderRevision.deadline,
                    TenderRevision.snapshot_hash,
                )
                .where(
                    TenderRevision.tender_id == tender_id,
                    TenderRevision.revision_index > after_index,
                )
                .order_by(TenderRevision.revision_index)
                .limit(limit)
            )
            .mappings()
            .all()
        )
        return [dict(row) for row in rows]
