from fastapi import APIRouter, Request
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from app.api.product_support import Configuration, Cursor, Database, Limit
from app.models import CompanyProfile
from app.schemas import product as s
from app.schemas.company import CompanyInput
from app.services import companies, product_actions, queries

router = APIRouter()


def company_json_schema():
    schema = CompanyInput.model_json_schema()
    definitions = schema.pop("$defs", {})

    def expand(value):
        if isinstance(value, list):
            return [expand(item) for item in value]
        if isinstance(value, dict):
            if "$ref" in value:
                return expand(definitions[value["$ref"].split("/")[-1]])
            return {key: expand(item) for key, item in value.items()}
        return value

    return expand(schema)


@router.get("/companies", response_model=s.Page[s.CompanySummary], tags=["Companies"])
def company_list(db: Database, cursor: Cursor = None, limit: Limit = 20):
    return queries.company_list(db, cursor, limit)


@router.post(
    "/companies",
    response_model=s.CompanyDetail,
    status_code=201,
    tags=["Companies"],
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": company_json_schema()}},
        }
    },
)
async def company_create(request: Request, db: Database):
    try:
        profile = CompanyInput.model_validate_json(await request.body())
    except ValidationError:
        raise RequestValidationError([]) from None
    # JSON validation preserves the strict CLI decimal/date rules.
    from starlette.concurrency import run_in_threadpool

    company_id = await run_in_threadpool(companies.create_company, db, profile)
    return {"id": company_id, "profile": profile}


@router.get(
    "/companies/{company_id}", response_model=s.CompanyDetail, tags=["Companies"]
)
def company_detail(company_id: s.ID, db: Database):
    queries.require(db, CompanyProfile, company_id, "company")
    return {"id": company_id, "profile": companies.show_company(db, company_id)}


@router.post("/matches", response_model=s.MatchDetail, tags=["Matching"])
def match_create(body: s.MatchRequest, db: Database):
    return product_actions.create_match(db, body.company_id, body.analysis_id)


@router.get("/matches/{match_id}", response_model=s.MatchDetail, tags=["Matching"])
def match_detail(match_id: s.ID, db: Database):
    return queries.match_detail(db, match_id)


@router.get(
    "/companies/{company_id}/matches",
    response_model=s.Page[s.MatchSummary],
    tags=["Matching"],
)
def company_matches(
    company_id: s.ID, db: Database, cursor: Cursor = None, limit: Limit = 20
):
    return queries.match_list(db, company_id=company_id, cursor=cursor, limit=limit)


@router.get(
    "/tenders/{tender_id}/matches",
    response_model=s.Page[s.MatchSummary],
    tags=["Matching"],
)
def tender_matches(
    tender_id: s.ID, db: Database, cursor: Cursor = None, limit: Limit = 20
):
    return queries.match_list(db, tender_id=tender_id, cursor=cursor, limit=limit)


@router.post(
    "/document-versions/{version_id}/ask", response_model=s.Answer, tags=["Ask Tender"]
)
def ask(version_id: s.ID, body: s.AskRequest, db: Database, config: Configuration):
    return product_actions.ask(db, version_id, body.question, config)
