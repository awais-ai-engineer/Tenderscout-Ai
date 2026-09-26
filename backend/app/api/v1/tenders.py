from typing import Annotated, Literal

from fastapi import APIRouter, Query
from pydantic import AwareDatetime

from app.api.product_support import Configuration, Cursor, Database, Limit
from app.models import Tender
from app.schemas import product as s
from app.services import queries as q

router = APIRouter(tags=["Tenders"])
TextFilter = Annotated[str | None, Query(min_length=1, max_length=255)]


@router.get("/tenders", response_model=s.Page[s.TenderSummary])
def list_tenders(
    db: Database,
    cursor: Cursor = None,
    limit: Limit = 20,
    source: s.SourceSlug | None = None,
    search: TextFilter = None,
    organization: TextFilter = None,
    category: TextFilter = None,
    deadline_before: AwareDatetime | None = None,
    deadline_after: AwareDatetime | None = None,
):
    return q.tenders(
        db,
        cursor=cursor,
        limit=limit,
        source=source,
        search=search,
        organization=organization,
        category=category,
        deadline_before=deadline_before,
        deadline_after=deadline_after,
    )


@router.get("/tenders/{tender_id}", response_model=s.TenderDetail)
def detail(tender_id: s.ID, db: Database, config: Configuration):
    return q.tender_detail(db, tender_id, config)


@router.get("/tenders/{tender_id}/documents", response_model=s.Page[s.DocumentSummary])
def documents(
    tender_id: s.ID,
    db: Database,
    config: Configuration,
    cursor: Cursor = None,
    limit: Limit = 20,
):
    return q.documents(db, tender_id, config, cursor, limit)


@router.get(
    "/documents/{document_id}/versions", response_model=s.Page[s.DocumentVersionSummary]
)
def versions(
    document_id: s.ID,
    db: Database,
    config: Configuration,
    cursor: Cursor = None,
    limit: Limit = 20,
):
    return q.version_list(db, document_id, config, cursor, limit)


@router.get("/tenders/{tender_id}/analyses", response_model=s.Page[s.AnalysisSummary])
def analyses(tender_id: s.ID, db: Database, cursor: Cursor = None, limit: Limit = 20):
    q.require(db, Tender, tender_id, "tender")
    return q.analysis_list(db, tender_id, cursor, limit)


@router.get("/analyses/{analysis_id}", response_model=s.AnalysisDetail)
def analysis(analysis_id: s.ID, db: Database):
    return q.analysis(db, analysis_id)


@router.get("/document-versions/{version_id}/analysis", response_model=s.AnalysisDetail)
def latest(version_id: s.ID, db: Database):
    return q.latest_analysis(db, version_id)


@router.get("/tenders/{tender_id}/revisions", response_model=s.Page[s.Revision])
def revisions(tender_id: s.ID, db: Database, cursor: Cursor = None, limit: Limit = 20):
    return q.revision_list(db, tender_id, cursor, limit)


@router.get("/tenders/{tender_id}/changes", response_model=s.Page[s.ChangeSummary])
def changes(
    tender_id: s.ID,
    db: Database,
    kind: Literal["metadata", "document"] = "metadata",
    cursor: Cursor = None,
    limit: Limit = 20,
):
    return q.changes(db, tender_id, kind, cursor, limit)


@router.get(
    "/changes/{kind}/{changeset_id}", response_model=s.ChangeDetail, tags=["Changes"]
)
def change(kind: Literal["metadata", "document"], changeset_id: s.ID, db: Database):
    return q.change_detail(db, changeset_id, kind)


@router.get("/dashboard/summary", response_model=s.Dashboard, tags=["Dashboard"])
def dashboard(db: Database):
    return q.dashboard(db)
