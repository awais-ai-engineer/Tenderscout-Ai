from contextlib import ExitStack

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.embeddings import OpenAIEmbeddingClient
from app.ai.openai_client import OpenAIStructuredClient
from app.models import CompanyProfile, DocumentVersion, TenderAnalysis
from app.rag.config import EmbeddingConfig
from app.rag.schemas import TenderAnswerOutput
from app.services import matching, qa, queries


class ProductActionError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def create_match(engine, company_id: int, analysis_id: int):
    queries.require(engine, CompanyProfile, company_id, "company")
    queries.require(engine, TenderAnalysis, analysis_id, "analysis")
    try:
        result = matching.match_tender(engine, company_id, analysis_id)
    except ValueError:
        raise ProductActionError("analysis_not_comparable") from None
    return queries.match_detail(engine, result.match_id, result.reused)


def ask(engine, version_id: int, question: str, settings):
    queries.require(engine, DocumentVersion, version_id, "document_version")
    if not all(
        (settings.openai_api_key, settings.ai_model, settings.ai_embedding_model)
    ):
        raise ProductActionError("ai_configuration_missing")
    with Session(engine) as session:
        ready = session.scalar(
            select(queries.index_ready(DocumentVersion.id, settings)).where(
                DocumentVersion.id == version_id
            )
        )
    if not ready:
        raise ProductActionError("document_not_indexed")
    with ExitStack() as stack:
        embedding_client = OpenAIEmbeddingClient(settings.openai_api_key)
        stack.callback(embedding_client.close)
        answer_client = OpenAIStructuredClient(
            settings.openai_api_key, output_schema=TenderAnswerOutput
        )
        stack.callback(answer_client.close)
        result = qa.ask_tender(
            engine,
            version_id,
            question,
            embedding_client,
            answer_client,
            embedding=EmbeddingConfig(
                model=settings.ai_embedding_model,
                dimensions=settings.ai_embedding_dimensions,
                batch_size=settings.rag_embedding_batch_size,
            ),
            answer_model=settings.ai_model,
            top_k=settings.rag_top_k,
            max_context_chars=settings.rag_max_context_chars,
        )
    if result.status == "failed":
        if result.failure_reason == (
            "Document is not fully indexed for this chunker and embedding model"
        ):
            raise ProductActionError("document_not_indexed")
        code = (
            "answer_validation_failed"
            if result.failure_reason
            in {
                "Answer output failed schema validation",
                "Answer output or citations failed validation",
            }
            else "provider_unavailable"
        )
        raise ProductActionError(code)
    return {
        name: getattr(result, name)
        for name in ("question_id", "status", "answer", "citations", "reused")
    }


def trigger(engine, source: str, settings):
    # HTTP must never turn a trigger into inline scraping, even in eager dev mode.
    if settings.celery_task_always_eager:
        raise ProductActionError("pipeline_eager_disabled")
    from app.worker.tasks import trigger_pipeline

    result = trigger_pipeline(engine, source)
    if result["status"] == "failed":
        raise ProductActionError("pipeline_unavailable")
    return result
