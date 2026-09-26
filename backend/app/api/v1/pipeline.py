from typing import Annotated

from fastapi import APIRouter, Query

from app.api.product_support import Configuration, Cursor, Database, Limit
from app.schemas import product as s
from app.services import product_actions, queries

router = APIRouter(prefix="/pipeline", tags=["Pipeline"])


@router.post("/runs", response_model=s.PipelineTrigger, status_code=202)
def trigger(body: s.PipelineRequest, db: Database, config: Configuration):
    return product_actions.trigger(db, body.source, config)


@router.get("/runs", response_model=s.Page[s.RunSummary])
def recent(db: Database, cursor: Cursor = None, limit: Limit = 20):
    return queries.runs(db, cursor, limit)


@router.get("/runs/{run_id}", response_model=s.RunDetail)
def status(
    run_id: s.ID,
    db: Database,
    after_stage_id: Annotated[int, Query(ge=0)] = 0,
    limit: Limit = 100,
):
    return queries.run_detail(db, run_id, after_stage_id, limit)
