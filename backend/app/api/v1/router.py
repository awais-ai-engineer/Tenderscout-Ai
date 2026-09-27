from fastapi import APIRouter

from app.api.v1 import actions, discover, pipeline, tenders
from app.schemas.product import ErrorEnvelope

router = APIRouter(
    prefix="/api/v1",
    responses={
        status: {"model": ErrorEnvelope}
        for status in (400, 404, 409, 413, 422, 500, 502, 503)
    },
)
for child in (tenders.router, discover.router, actions.router, pipeline.router):
    router.include_router(child)
