"""Small adapters from pipeline stages to the existing synchronous services."""

import hashlib
import json
from dataclasses import asdict

import httpx
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.ai.embeddings import OpenAIEmbeddingClient
from app.ai.openai_client import OpenAIStructuredClient
from app.ai.prompt import TENDER_ANALYSIS_PROMPT
from app.ai.schemas import ANALYSIS_SCHEMA_VERSION
from app.models import (
    CompanyProfile,
    DocumentVersion,
    PipelineStageRun,
    Tender,
    TenderAnalysis,
    TenderDocument,
)
from app.rag.chunking import CHUNKER_VERSION
from app.rag.config import ChunkConfig, EmbeddingConfig
from app.scrapers import contracts_finder
from app.scrapers.contracts_finder_documents import discover_documents
from app.services import change_rules
from app.services.analysis import analyze_document, prepare_document
from app.services.change_detection import compare_document
from app.services.documents import process_documents
from app.services.indexing import index_document
from app.services.ingestion import ingest_tenders
from app.services.matching import MATCHER_VERSION, match_tender
from app.services.pipeline import Outcome, Reason, Stage, StageSpec
from app.sources import connector


def config_key(settings) -> str:
    # No credentials: only settings/version constants affecting processing identity.
    names = (
        "ai_model",
        "ai_max_input_chars",
        "ai_embedding_model",
        "ai_embedding_dimensions",
        "rag_chunk_size_chars",
        "rag_chunk_overlap_chars",
        "auto_match_enabled",
        "auto_match_max_companies",
        "pipeline_max_documents",
        "document_max_bytes",
        "document_max_pages",
    )
    values = {name: getattr(settings, name) for name in names}
    values["versions"] = [
        ANALYSIS_SCHEMA_VERSION,
        TENDER_ANALYSIS_PROMPT.version,
        CHUNKER_VERSION,
        MATCHER_VERSION,
        change_rules.CHANGESET_VERSION,
    ]
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def ingest_step(engine, row, run, settings) -> Outcome:
    source = connector(run.source_slug)
    with httpx.Client(trust_env=False, follow_redirects=False) as client:
        listing = source.refresh(
            client,
            limit=settings.pipeline_max_tenders,
            timeout=30.0,
        )
    limited = listing.limited
    ids: set[int] = set()
    result = ingest_tenders(engine, source.source, listing, affected_ids=ids)
    return Outcome(
        metrics=asdict(result) | {"limited": limited, "scope_count": len(ids)},
        children=[
            StageSpec(
                Stage.DOCUMENTS, config_key=config_key(settings), scope_ids=sorted(ids)
            )
        ],
    )


def latest_versions(engine, tender_ids: list[int], limit: int) -> list[int]:
    with Session(engine) as session:
        ranked = (
            select(
                DocumentVersion.id,
                func.row_number()
                .over(
                    partition_by=DocumentVersion.document_id,
                    order_by=(
                        DocumentVersion.downloaded_at.desc(),
                        DocumentVersion.id.desc(),
                    ),
                )
                .label("position"),
            )
            .join(TenderDocument)
            .where(TenderDocument.tender_id.in_(tender_ids))
            .subquery()
        )
        return list(
            session.scalars(
                select(DocumentVersion.id)
                .join(ranked, ranked.c.id == DocumentVersion.id)
                .where(
                    ranked.c.position == 1,
                    DocumentVersion.extraction_status == "extracted",
                    func.length(func.trim(DocumentVersion.extracted_text)) > 0,
                )
                .order_by(DocumentVersion.id)
                .limit(limit)
            )
        )


def eligible_children(engine, version_ids: list[int], key: str) -> list[StageSpec]:
    with Session(engine) as session:
        completed = session.scalars(
            select(PipelineStageRun).where(
                PipelineStageRun.entity_type == "document_version",
                PipelineStageRun.entity_id.in_(version_ids),
                PipelineStageRun.config_key == key,
                PipelineStageRun.status == "completed",
                PipelineStageRun.stage.in_((Stage.ANALYSIS, Stage.INDEXING)),
            )
        ).all()
        done = {(row.stage, row.entity_id) for row in completed}
        analyses = {
            row.metrics["analysis_id"]
            for row in completed
            if row.stage == Stage.ANALYSIS and "analysis_id" in row.metrics
        }
        local_done = set(
            session.execute(
                select(PipelineStageRun.stage, PipelineStageRun.entity_id).where(
                    PipelineStageRun.entity_type == "analysis",
                    PipelineStageRun.entity_id.in_(analyses),
                    PipelineStageRun.config_key == key,
                    PipelineStageRun.status.in_(("completed", "skipped")),
                )
            ).all()
        )
    return [
        StageSpec(stage, "document_version", version_id, key)
        for version_id in version_ids
        for stage in (Stage.ANALYSIS, Stage.INDEXING)
        if (stage, version_id) not in done
    ] + [
        StageSpec(stage, "analysis", analysis_id, key)
        for analysis_id in sorted(analyses)
        for stage in (Stage.MATCHING, Stage.CHANGES)
        if (stage, analysis_id) not in local_done
    ]


def documents_step(engine, row, run, settings) -> Outcome:
    if not connector(run.source_slug).supports_documents:
        return Outcome("skipped", reason=Reason.UNSUPPORTED)
    if not row.scope_ids:
        return Outcome("skipped", reason=Reason.NO_WORK)
    with Session(engine) as session:
        external_ids = set(
            session.scalars(
                select(Tender.external_id).where(Tender.id.in_(row.scope_ids))
            )
        )
    with httpx.Client(trust_env=False, follow_redirects=False) as client:
        listing = discover_documents(contracts_finder.fetch_releases(client))
        records = [
            record
            for record in listing.records
            if record.tender_external_id in external_ids
        ]
        limited = max(0, len(records) - settings.pipeline_max_documents)
        result = process_documents(
            engine, client, records[: settings.pipeline_max_documents], settings
        )
    versions = latest_versions(
        engine, row.scope_ids, settings.pipeline_max_documents + 1
    )
    limited += max(0, len(versions) - settings.pipeline_max_documents)
    result.failed += listing.failed
    result.skipped += limited
    return Outcome(
        metrics=asdict(result) | {"limited": limited},
        children=eligible_children(
            engine, versions[: settings.pipeline_max_documents], row.config_key
        ),
    )


def analysis_step(engine, row, run, settings) -> Outcome:
    if prepare_document(engine, row.entity_id, settings.ai_max_input_chars) is None:
        return Outcome("skipped", reason=Reason.NO_WORK)
    if not settings.ai_model or not settings.openai_api_key:
        return Outcome("failed", reason=Reason.AI_CONFIG)
    client = OpenAIStructuredClient(settings.openai_api_key)
    try:
        result = analyze_document(
            engine,
            row.entity_id,
            client,
            model=settings.ai_model,
            max_input_chars=settings.ai_max_input_chars,
        )
    finally:
        client.close()
    metrics = {"reused": result.reused}
    if result.analysis_id:
        metrics["analysis_id"] = result.analysis_id
    if result.status != "completed":
        return Outcome(
            result.status,
            metrics,
            Reason.ANALYSIS_FAILED if result.status == "failed" else Reason.NO_WORK,
        )
    return Outcome(
        metrics=metrics,
        children=[
            StageSpec(stage, "analysis", result.analysis_id, row.config_key)
            for stage in (Stage.MATCHING, Stage.CHANGES)
        ],
    )


def indexing_step(engine, row, run, settings) -> Outcome:
    if prepare_document(engine, row.entity_id, settings.ai_max_input_chars) is None:
        return Outcome("skipped", reason=Reason.NO_WORK)
    if not settings.ai_embedding_model or not settings.openai_api_key:
        return Outcome("failed", reason=Reason.AI_CONFIG)
    client = OpenAIEmbeddingClient(settings.openai_api_key)
    try:
        result = index_document(
            engine,
            row.entity_id,
            client,
            embedding=EmbeddingConfig(
                model=settings.ai_embedding_model,
                dimensions=settings.ai_embedding_dimensions,
                batch_size=settings.rag_embedding_batch_size,
            ),
            chunking=ChunkConfig(
                size=settings.rag_chunk_size_chars,
                overlap=settings.rag_chunk_overlap_chars,
            ),
        )
    finally:
        client.close()
    metrics = {
        key: value
        for key, value in asdict(result).items()
        if key not in {"document_version_id", "model", "skipped"}
    }
    return Outcome(
        "skipped" if result.skipped else "completed",
        metrics,
        Reason.NO_WORK if result.skipped else None,
    )


def completed_analysis(engine, analysis_id: int) -> bool:
    with Session(engine) as session:
        return (
            session.scalar(
                select(TenderAnalysis.status).where(TenderAnalysis.id == analysis_id)
            )
            == "completed"
        )


def matching_step(engine, row, run, settings) -> Outcome:
    if not completed_analysis(engine, row.entity_id):
        return Outcome("skipped", reason=Reason.NO_WORK)
    if not settings.auto_match_enabled:
        return Outcome("skipped", reason=Reason.DISABLED)
    with Session(engine) as session:
        companies = list(
            session.scalars(
                select(CompanyProfile.id)
                .order_by(CompanyProfile.id)
                .limit(settings.auto_match_max_companies + 1)
            )
        )
    metrics = {
        "matched": 0,
        "reused": 0,
        "limited": int(len(companies) > settings.auto_match_max_companies),
    }
    for company_id in companies[: settings.auto_match_max_companies]:
        try:
            result = match_tender(engine, company_id, row.entity_id)
        except ValueError:
            metrics["failed"] = metrics.get("failed", 0) + 1
            continue
        metrics["matched"] += 1
        metrics["reused"] += int(result.reused)
    if metrics.get("failed"):
        return Outcome("failed", metrics, Reason.INVALID)
    return Outcome(
        "completed" if companies else "skipped",
        metrics,
        None if companies else Reason.NO_WORK,
    )


def previous_analysis(engine, analysis_id: int) -> int | None:
    with Session(engine) as session:
        current = session.get(TenderAnalysis, analysis_id)
        if current is None or current.status != "completed":
            return None
        version = session.get(DocumentVersion, current.document_version_id)
        return session.scalar(
            select(TenderAnalysis.id)
            .join(DocumentVersion)
            .where(
                TenderAnalysis.status == "completed",
                DocumentVersion.document_id == version.document_id,
                or_(
                    DocumentVersion.downloaded_at < version.downloaded_at,
                    and_(
                        DocumentVersion.downloaded_at == version.downloaded_at,
                        DocumentVersion.id < version.id,
                    ),
                ),
                *(
                    getattr(TenderAnalysis, name) == getattr(current, name)
                    for name in (
                        "analysis_schema_version",
                        "provider",
                        "model",
                        "prompt_version",
                    )
                ),
            )
            .order_by(
                DocumentVersion.downloaded_at.desc(),
                DocumentVersion.id.desc(),
                TenderAnalysis.id.desc(),
            )
            .limit(1)
        )


def changes_step(engine, row, run, settings) -> Outcome:
    previous = previous_analysis(engine, row.entity_id)
    if previous is None:
        return Outcome("skipped", reason=Reason.NO_PREVIOUS)
    result = compare_document(engine, previous, row.entity_id)
    return Outcome(
        metrics={
            "change_set_id": result.change_set_id,
            "change_count": result.change_count,
            "reused": result.reused,
        }
    )


STEPS = {
    Stage.INGEST: ingest_step,
    Stage.DOCUMENTS: documents_step,
    Stage.ANALYSIS: analysis_step,
    Stage.INDEXING: indexing_step,
    Stage.MATCHING: matching_step,
    Stage.CHANGES: changes_step,
}


def execute_stage(engine, row, run, settings) -> Outcome:
    if row.stage != Stage.INGEST and row.config_key != config_key(settings):
        return Outcome("failed", reason=Reason.CONFIG_CHANGED)
    return STEPS[Stage(row.stage)](engine, row, run, settings)
