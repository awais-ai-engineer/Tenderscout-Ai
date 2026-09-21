from dataclasses import dataclass, field

from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai.schemas import ANALYSIS_SCHEMA_VERSION, TenderAnalysisOutput
from app.models import (
    DocumentAnalysisChangeSet,
    DocumentVersion,
    TenderAnalysis,
    TenderMetadataChangeSet,
    TenderRevision,
)
from app.services import change_rules
from app.services.change_rules import (
    analysis_diff,
    category_counts,
    metadata_diff,
    utc_datetime,
)
from app.services.revisions import business_state


class ComparisonError(ValueError):
    pass


@dataclass(frozen=True)
class ChangeSetResult:
    change_set_id: int
    parent_id: int
    from_id: int
    to_id: int
    has_changes: bool
    change_count: int
    changes: list[dict] = field(repr=False)
    reused: bool


def metadata_result(row: TenderMetadataChangeSet, reused: bool) -> ChangeSetResult:
    return ChangeSetResult(
        row.id,
        row.tender_id,
        row.from_revision_id,
        row.to_revision_id,
        row.has_changes,
        row.change_count,
        row.changes,
        reused,
    )


def document_result(row: DocumentAnalysisChangeSet, reused: bool) -> ChangeSetResult:
    return ChangeSetResult(
        row.id,
        row.tender_document_id,
        row.from_analysis_id,
        row.to_analysis_id,
        row.has_changes,
        row.change_count,
        row.changes,
        reused,
    )


def compare_metadata(
    engine: Engine, from_revision_id: int, to_revision_id: int
) -> ChangeSetResult:
    identity = dict(
        from_revision_id=from_revision_id,
        to_revision_id=to_revision_id,
        changeset_version=change_rules.CHANGESET_VERSION,
    )
    query = select(TenderMetadataChangeSet).filter_by(**identity)
    with Session(engine) as session:
        before = session.get(TenderRevision, from_revision_id)
        after = session.get(TenderRevision, to_revision_id)
        if before is None or after is None:
            raise ComparisonError("Both revisions must exist")
        if before.tender_id != after.tender_id:
            raise ComparisonError("Revisions must belong to the same tender")
        if before.revision_index >= after.revision_index:
            raise ComparisonError("From revision must precede to revision")
        existing = session.scalar(query)
        if existing is not None:
            return metadata_result(existing, True)
        tender_id = before.tender_id
        old, new = business_state(before), business_state(after)
    changes = metadata_diff(old, new)
    try:
        with Session(engine) as session, session.begin():
            existing = session.scalar(query)
            if existing is not None:
                return metadata_result(existing, True)
            row = TenderMetadataChangeSet(
                **identity,
                tender_id=tender_id,
                has_changes=bool(changes),
                change_count=len(changes),
                changed_fields=[change["field"] for change in changes],
                changes=changes,
            )
            session.add(row)
            session.flush()
            return metadata_result(row, False)
    except IntegrityError:
        with Session(engine) as session:
            existing = session.scalar(query)
            if existing is not None:
                return metadata_result(existing, True)
        raise


def validate_analysis_pair(
    before: TenderAnalysis | None,
    after: TenderAnalysis | None,
    old_version: DocumentVersion | None,
    new_version: DocumentVersion | None,
) -> None:
    if before is None or after is None or old_version is None or new_version is None:
        raise ComparisonError("Both analyses and document versions must exist")
    if before.status != "completed" or after.status != "completed":
        raise ComparisonError("Both analyses must be completed")
    if old_version.document_id != new_version.document_id:
        raise ComparisonError("Analyses must reference the same logical document")
    if (utc_datetime(old_version.downloaded_at), old_version.id) >= (
        utc_datetime(new_version.downloaded_at),
        new_version.id,
    ):
        raise ComparisonError("From document version must precede to document version")
    for name in ("analysis_schema_version", "provider", "model", "prompt_version"):
        if getattr(before, name) != getattr(after, name):
            raise ComparisonError(f"Analysis {name} differs; comparison rejected")
    if before.analysis_schema_version != ANALYSIS_SCHEMA_VERSION:
        raise ComparisonError("Unsupported analysis schema version")


def compare_document(
    engine: Engine, from_analysis_id: int, to_analysis_id: int
) -> ChangeSetResult:
    identity = dict(
        from_analysis_id=from_analysis_id,
        to_analysis_id=to_analysis_id,
        changeset_version=change_rules.CHANGESET_VERSION,
    )
    query = select(DocumentAnalysisChangeSet).filter_by(**identity)
    with Session(engine) as session:
        before = session.get(TenderAnalysis, from_analysis_id)
        after = session.get(TenderAnalysis, to_analysis_id)
        old_version = (
            session.get(DocumentVersion, before.document_version_id) if before else None
        )
        new_version = (
            session.get(DocumentVersion, after.document_version_id) if after else None
        )
        validate_analysis_pair(before, after, old_version, new_version)
        existing = session.scalar(query)
        if existing is not None:
            return document_result(existing, True)
        document_id = old_version.document_id
        old, new = (
            {name: getattr(row, name) for name in TenderAnalysisOutput.model_fields}
            for row in (before, after)
        )
    before_output = TenderAnalysisOutput.model_validate(old)
    after_output = TenderAnalysisOutput.model_validate(new)
    changes = analysis_diff(before_output, after_output)
    try:
        with Session(engine) as session, session.begin():
            existing = session.scalar(query)
            if existing is not None:
                return document_result(existing, True)
            row = DocumentAnalysisChangeSet(
                **identity,
                tender_document_id=document_id,
                has_changes=bool(changes),
                change_count=len(changes),
                category_counts=category_counts(changes),
                changes=changes,
            )
            session.add(row)
            session.flush()
            return document_result(row, False)
    except IntegrityError:
        with Session(engine) as session:
            existing = session.scalar(query)
            if existing is not None:
                return document_result(existing, True)
        raise
