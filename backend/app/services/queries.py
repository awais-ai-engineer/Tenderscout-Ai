"""Bounded product projections. Never select PDF text, vectors or provider bodies."""

from datetime import UTC, datetime

from sqlalchemy import case, exists, func, literal, or_, select, union_all
from sqlalchemy.orm import Session

from app.ai.schemas import ANALYSIS_SCHEMA_VERSION, TenderAnalysisOutput
from app.models import (
    Alert,
    ChunkEmbedding,
    CompanyCapability,
    CompanyCertification,
    CompanyExperience,
    CompanyProfile,
    DocumentAnalysisChangeSet,
    DocumentChunk,
    DocumentVersion,
    PipelineRun,
    PipelineStageRun,
    SavedTender,
    Source,
    Tender,
    TenderAnalysis,
    TenderDocument,
    TenderMatch,
    TenderMetadataChangeSet,
    TenderRevision,
)
from app.rag.chunking import CHUNKER_VERSION
from app.schemas.product import AnalysisDetail, MatchDetail
from app.services import pipeline


class ReadNotFound(LookupError):
    def __init__(self, resource: str):
        self.resource = resource
        super().__init__(resource)


def require(engine, model, row_id: int, resource: str) -> None:
    with Session(engine) as session:
        if session.scalar(select(model.id).where(model.id == row_id)) is None:
            raise ReadNotFound(resource)


def page(
    engine, query, id_column, cursor: int | None, limit: int = 20, *, key="id"
) -> dict:
    if not 1 <= limit <= 100 or (cursor is not None and cursor <= 0):
        raise ValueError("Invalid page bounds")
    if cursor is not None:
        query = query.where(id_column < cursor)
    with Session(engine) as session:
        rows = [
            dict(row)
            for row in session.execute(
                query.order_by(id_column.desc()).limit(limit + 1)
            ).mappings()
        ]
    return {
        "items": rows[:limit],
        "next_cursor": rows[limit - 1][key] if len(rows) > limit else None,
    }


def tender_query():
    revision = (
        select(func.coalesce(func.max(TenderRevision.revision_index), 0))
        .where(TenderRevision.tender_id == Tender.id)
        .correlate(Tender)
        .scalar_subquery()
    )
    documents = (
        select(func.count())
        .select_from(TenderDocument)
        .where(TenderDocument.tender_id == Tender.id)
        .correlate(Tender)
        .scalar_subquery()
    )
    status = (
        select(TenderAnalysis.status)
        .join(DocumentVersion)
        .join(TenderDocument)
        .where(TenderDocument.tender_id == Tender.id)
        .order_by(
            DocumentVersion.downloaded_at.desc(),
            DocumentVersion.id.desc(),
            TenderAnalysis.id.desc(),
        )
        .limit(1)
        .correlate(Tender)
        .scalar_subquery()
    )
    fields = (
        "id",
        "external_id",
        "organization",
        "category",
        "location",
        "published_at",
        "deadline",
        "first_seen_at",
        "last_seen_at",
    )
    return select(
        *(getattr(Tender, name) for name in fields),
        func.substr(Tender.title, 1, 2000).label("title"),
        Source.slug.label("source"),
        revision.label("latest_revision_index"),
        documents.label("document_count"),
        status.label("latest_analysis_status"),
    ).join(Source)


def tenders(
    engine,
    *,
    cursor=None,
    limit=20,
    source=None,
    search=None,
    organization=None,
    category=None,
    deadline_before=None,
    deadline_after=None,
):
    query = tender_query()
    if source:
        query = query.where(Source.slug == source)
    if search:
        query = query.where(
            or_(
                Tender.title.icontains(search, autoescape=True),
                Tender.organization.icontains(search, autoescape=True),
            )
        )
    for column, value in (
        (Tender.organization, organization),
        (Tender.category, category),
    ):
        if value:
            query = query.where(column.icontains(value, autoescape=True))
    if deadline_before:
        query = query.where(Tender.deadline <= deadline_before)
    if deadline_after:
        query = query.where(Tender.deadline >= deadline_after)
    return page(engine, query, Tender.id, cursor, limit)


def discover_tenders(
    engine,
    *,
    search: str,
    limit: int,
    source=None,
    organization=None,
    category=None,
    deadline_before=None,
):
    """A bounded, deterministic read of stored matches after live refresh."""
    title = Tender.title.icontains(search, autoescape=True)
    buyer = Tender.organization.icontains(search, autoescape=True)
    category_match = Tender.category.icontains(search, autoescape=True)
    description = Tender.description.icontains(search, autoescape=True)
    query = tender_query().where(or_(title, buyer, category_match, description))
    if source:
        query = query.where(Source.slug == source)
    if organization:
        query = query.where(
            Tender.organization.icontains(organization, autoescape=True)
        )
    if category:
        query = query.where(Tender.category.icontains(category, autoescape=True))
    if deadline_before:
        query = query.where(Tender.deadline <= deadline_before)
    rank = case((title, 0), (buyer, 1), (category_match, 2), else_=3)
    with Session(engine) as session:
        return [
            dict(row)
            for row in session.execute(
                query.order_by(rank, Tender.id.desc()).limit(limit)
            ).mappings()
        ]


def analysis_list(engine, tender_id, cursor=None, limit=20):
    query = (
        select(
            TenderAnalysis.id,
            TenderAnalysis.document_version_id,
            TenderAnalysis.status,
            TenderAnalysis.model,
            TenderAnalysis.created_at,
        )
        .join(DocumentVersion)
        .join(TenderDocument)
        .where(TenderDocument.tender_id == tender_id)
    )
    return page(engine, query, TenderAnalysis.id, cursor, limit)


def revision_list(engine, tender_id, cursor=None, limit=20):
    require(engine, Tender, tender_id, "tender")
    query = select(
        TenderRevision.id.label("revision_id"),
        TenderRevision.revision_index,
        TenderRevision.observed_at,
        TenderRevision.deadline,
        TenderRevision.snapshot_hash,
    ).where(TenderRevision.tender_id == tender_id)
    return page(engine, query, TenderRevision.id, cursor, limit, key="revision_id")


def index_ready(version_id, settings):
    chunk_count = (
        select(func.count())
        .select_from(DocumentChunk)
        .where(
            DocumentChunk.document_version_id == version_id,
            DocumentChunk.chunker_version == CHUNKER_VERSION,
            DocumentChunk.chunk_size == settings.rag_chunk_size_chars,
            DocumentChunk.chunk_overlap == settings.rag_chunk_overlap_chars,
        )
        .correlate(DocumentVersion)
        .scalar_subquery()
    )
    embedded = (
        select(func.count(func.distinct(DocumentChunk.id)))
        .select_from(DocumentChunk)
        .join(ChunkEmbedding)
        .where(
            DocumentChunk.document_version_id == version_id,
            DocumentChunk.chunker_version == CHUNKER_VERSION,
            DocumentChunk.chunk_size == settings.rag_chunk_size_chars,
            DocumentChunk.chunk_overlap == settings.rag_chunk_overlap_chars,
            ChunkEmbedding.provider == "openai",
            ChunkEmbedding.model == settings.ai_embedding_model,
            ChunkEmbedding.dimensions == settings.ai_embedding_dimensions,
            ChunkEmbedding.input_hash == DocumentChunk.content_hash,
        )
        .correlate(DocumentVersion)
        .scalar_subquery()
    )
    return (chunk_count > 0) & (embedded == chunk_count)


def version_query(settings):
    analysis = exists(
        select(TenderAnalysis.id).where(
            TenderAnalysis.document_version_id == DocumentVersion.id,
            TenderAnalysis.status == "completed",
            TenderAnalysis.analysis_schema_version == ANALYSIS_SCHEMA_VERSION,
        )
    )
    return select(
        DocumentVersion.id,
        DocumentVersion.document_id,
        DocumentVersion.content_hash,
        DocumentVersion.byte_size,
        DocumentVersion.media_type,
        DocumentVersion.downloaded_at,
        DocumentVersion.extraction_status,
        analysis.label("has_analysis"),
        index_ready(DocumentVersion.id, settings).label("is_indexed"),
    )


def version_list(engine, document_id, settings, cursor=None, limit=20):
    require(engine, TenderDocument, document_id, "document")
    result = page(
        engine,
        version_query(settings).where(DocumentVersion.document_id == document_id),
        DocumentVersion.id,
        cursor,
        limit,
    )
    for item in result["items"]:
        item.pop("document_id")
    return result


def documents(engine, tender_id, settings, cursor=None, limit=20):
    require(engine, Tender, tender_id, "tender")
    result = page(
        engine,
        select(
            TenderDocument.id,
            func.substr(TenderDocument.title, 1, 2000).label("title"),
            TenderDocument.media_type,
        ).where(TenderDocument.tender_id == tender_id),
        TenderDocument.id,
        cursor,
        limit,
    )
    ids = [item["id"] for item in result["items"]]
    ranked = (
        version_query(settings)
        .add_columns(
            func.row_number()
            .over(
                partition_by=DocumentVersion.document_id,
                order_by=DocumentVersion.id.desc(),
            )
            .label("position")
        )
        .where(DocumentVersion.document_id.in_(ids))
        .subquery()
    )
    with Session(engine) as session:
        versions = (
            session.execute(
                select(ranked)
                .where(ranked.c.position <= 6)
                .order_by(ranked.c.id.desc())
            )
            .mappings()
            .all()
        )
    for item in result["items"]:
        rows = [
            {
                key: value
                for key, value in row.items()
                if key not in {"document_id", "position"}
            }
            for row in versions
            if row["document_id"] == item["id"]
        ]
        item["versions"] = {
            "items": rows[:5],
            "next_cursor": rows[4]["id"] if len(rows) > 5 else None,
        }
    return result


def analysis(engine, analysis_id):
    fields = list(AnalysisDetail.model_fields.keys() - {"facts"})
    with Session(engine) as session:
        row = (
            session.execute(
                select(
                    *(getattr(TenderAnalysis, name) for name in fields),
                    *(
                        getattr(TenderAnalysis, name)
                        for name in TenderAnalysisOutput.model_fields
                    ),
                ).where(TenderAnalysis.id == analysis_id)
            )
            .mappings()
            .first()
        )
    if row is None:
        raise ReadNotFound("analysis")
    facts = (
        TenderAnalysisOutput.model_validate(
            {name: row[name] for name in TenderAnalysisOutput.model_fields}
        )
        if row["status"] == "completed"
        and row["analysis_schema_version"] == ANALYSIS_SCHEMA_VERSION
        else None
    )
    return {name: row[name] for name in fields} | {"facts": facts}


def latest_analysis(engine, version_id):
    require(engine, DocumentVersion, version_id, "document_version")
    with Session(engine) as session:
        analysis_id = session.scalar(
            select(TenderAnalysis.id)
            .where(
                TenderAnalysis.document_version_id == version_id,
                TenderAnalysis.status == "completed",
                TenderAnalysis.analysis_schema_version == ANALYSIS_SCHEMA_VERSION,
            )
            .order_by(TenderAnalysis.id.desc())
            .limit(1)
        )
    if analysis_id is None:
        raise ReadNotFound("analysis")
    return analysis(engine, analysis_id)


def company_list(engine, cursor=None, limit=20):
    counts = [
        select(func.count())
        .select_from(model)
        .where(model.company_id == CompanyProfile.id)
        .correlate(CompanyProfile)
        .scalar_subquery()
        .label(label)
        for model, label in (
            (CompanyCapability, "capability_count"),
            (CompanyCertification, "certification_count"),
            (CompanyExperience, "experience_count"),
        )
    ]
    fields = (
        "id",
        "name",
        "country",
        "capabilities_complete",
        "certifications_complete",
        "experience_complete",
        "financials_complete",
    )
    return page(
        engine,
        select(*(getattr(CompanyProfile, name) for name in fields), *counts),
        CompanyProfile.id,
        cursor,
        limit,
    )


def match_query():
    return select(
        TenderMatch.id.label("match_id"),
        TenderMatch.company_id,
        TenderMatch.tender_analysis_id.label("analysis_id"),
        TenderMatch.eligibility_status,
        TenderMatch.score,
        TenderMatch.coverage_ratio,
        TenderMatch.created_at,
    )


def match_list(engine, *, company_id=None, tender_id=None, cursor=None, limit=20):
    query = match_query()
    if company_id:
        require(engine, CompanyProfile, company_id, "company")
        query = query.where(TenderMatch.company_id == company_id)
    if tender_id:
        require(engine, Tender, tender_id, "tender")
        query = (
            query.join(TenderAnalysis)
            .join(DocumentVersion)
            .join(TenderDocument)
            .where(TenderDocument.tender_id == tender_id)
        )
    return page(engine, query, TenderMatch.id, cursor, limit, key="match_id")


def match_detail(engine, match_id, reused=False):
    arrays = [
        name
        for name in MatchDetail.model_fields
        if name
        not in {
            "match_id",
            "company_id",
            "analysis_id",
            "eligibility_status",
            "score",
            "coverage_ratio",
            "created_at",
            "reused",
        }
    ]
    with Session(engine) as session:
        row = (
            session.execute(
                match_query()
                .add_columns(*(getattr(TenderMatch, name) for name in arrays))
                .where(TenderMatch.id == match_id)
            )
            .mappings()
            .first()
        )
    if row is None:
        raise ReadNotFound("match")
    return dict(row) | {"reused": reused}


def changes_query(kind, tender_id=None):
    if kind == "metadata":
        query = select(
            TenderMetadataChangeSet.id,
            TenderMetadataChangeSet.tender_id,
            literal(kind).label("kind"),
            TenderMetadataChangeSet.change_count,
            TenderMetadataChangeSet.created_at,
        )
        return (
            query.where(TenderMetadataChangeSet.tender_id == tender_id)
            if tender_id
            else query
        )
    query = select(
        DocumentAnalysisChangeSet.id,
        TenderDocument.tender_id,
        literal(kind).label("kind"),
        DocumentAnalysisChangeSet.change_count,
        DocumentAnalysisChangeSet.created_at,
    ).join(TenderDocument)
    return query.where(TenderDocument.tender_id == tender_id) if tender_id else query


def changes(engine, tender_id, kind="metadata", cursor=None, limit=20):
    require(engine, Tender, tender_id, "tender")
    model = TenderMetadataChangeSet if kind == "metadata" else DocumentAnalysisChangeSet
    return page(engine, changes_query(kind, tender_id), model.id, cursor, limit)


def change_detail(engine, change_id, kind):
    model = TenderMetadataChangeSet if kind == "metadata" else DocumentAnalysisChangeSet
    with Session(engine) as session:
        row = session.get(model, change_id)
        if row is None:
            raise ReadNotFound("changeset")
        data = {
            name: getattr(row, name)
            for name in (
                "id",
                "change_count",
                "created_at",
                "changeset_version",
                "changes",
            )
        }
        data.update(
            kind=kind,
            tender_id=row.tender_id
            if kind == "metadata"
            else session.scalar(
                select(TenderDocument.tender_id).where(
                    TenderDocument.id == row.tender_document_id
                )
            ),
            from_id=row.from_revision_id
            if kind == "metadata"
            else row.from_analysis_id,
            to_id=row.to_revision_id if kind == "metadata" else row.to_analysis_id,
            from_analysis_id=row.from_analysis_id if kind == "document" else None,
            to_analysis_id=row.to_analysis_id if kind == "document" else None,
            from_revision_id=row.from_revision_id if kind == "metadata" else None,
            to_revision_id=row.to_revision_id if kind == "metadata" else None,
            category_counts={} if kind == "metadata" else row.category_counts,
            changed_fields=row.changed_fields if kind == "metadata" else [],
        )
        return data


def tender_detail(engine, tender_id, settings):
    with Session(engine) as session:
        row = (
            session.execute(
                tender_query()
                .add_columns(
                    func.substr(Tender.description, 1, 20000).label("description"),
                    (func.coalesce(func.length(Tender.description), 0) > 20000).label(
                        "description_truncated"
                    ),
                    Tender.source_url,
                )
                .where(Tender.id == tender_id)
            )
            .mappings()
            .first()
        )
        if row is None:
            raise ReadNotFound("tender")
        result = dict(row)
        result["matches_count"] = session.scalar(
            select(func.count())
            .select_from(TenderMatch)
            .join(TenderAnalysis)
            .join(DocumentVersion)
            .join(TenderDocument)
            .where(TenderDocument.tender_id == tender_id)
        )
    revisions = revision_list(engine, tender_id, limit=1)["items"]
    metadata = changes(engine, tender_id, limit=1)["items"]
    return result | {
        "latest_revision": revisions[0] if revisions else None,
        "latest_metadata_change": metadata[0] if metadata else None,
        "documents": documents(engine, tender_id, settings, limit=5),
        "analyses": analysis_list(engine, tender_id, limit=20),
    }


def run_query():
    count = (
        select(func.count())
        .select_from(PipelineStageRun)
        .where(PipelineStageRun.pipeline_run_id == PipelineRun.id)
        .correlate(PipelineRun)
        .scalar_subquery()
    )
    return select(
        PipelineRun.id,
        PipelineRun.source_slug.label("source"),
        PipelineRun.trigger,
        PipelineRun.status,
        PipelineRun.created_at,
        PipelineRun.started_at,
        PipelineRun.finished_at,
        count.label("stage_count"),
    )


def runs(engine, cursor=None, limit=20):
    return page(engine, run_query(), PipelineRun.id, cursor, limit)


def run_detail(engine, run_id, after_stage_id=0, limit=100):
    require(engine, PipelineRun, run_id, "run")
    detail = pipeline.run_status(
        engine, run_id, after_stage_id=after_stage_id, limit=limit
    )
    with Session(engine) as session:
        row = dict(
            session.execute(run_query().where(PipelineRun.id == run_id))
            .mappings()
            .one()
        )
    return row | {
        name: detail[name]
        for name in ("summary", "failure_reason", "stages", "next_after_stage_id")
    }


def dashboard(engine):
    now = datetime.now(UTC)
    combined = union_all(
        changes_query("metadata"), changes_query("document")
    ).subquery()
    with Session(engine) as session:
        return {
            "active_tenders_count": session.scalar(
                select(func.count()).select_from(Tender).where(Tender.deadline >= now)
            ),
            "tender_count": session.scalar(select(func.count()).select_from(Tender)),
            "company_count": session.scalar(
                select(func.count()).select_from(CompanyProfile)
            ),
            "upcoming_deadlines": [
                dict(row)
                for row in session.execute(
                    tender_query()
                    .where(Tender.deadline >= now)
                    .order_by(Tender.deadline, Tender.id)
                    .limit(5)
                ).mappings()
            ],
            "recent_changes": [
                dict(row)
                for row in session.execute(
                    select(combined)
                    .order_by(
                        combined.c.created_at.desc(),
                        combined.c.kind,
                        combined.c.id.desc(),
                    )
                    .limit(5)
                ).mappings()
            ],
            "recent_runs": [
                dict(row)
                for row in session.execute(
                    run_query().order_by(PipelineRun.id.desc()).limit(5)
                ).mappings()
            ],
            "saved_tenders_count": session.scalar(
                select(func.count()).select_from(SavedTender)
            ),
            "unread_alerts_count": session.scalar(
                select(func.count()).select_from(Alert).where(Alert.read_at.is_(None))
            ),
            "matching_opportunities_count": session.scalar(
                select(func.count()).select_from(TenderMatch)
            ),
        }
