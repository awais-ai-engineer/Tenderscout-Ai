from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import AwareDatetime

from app.api.product_support import Cursor, Database, Limit
from app.schemas import product as s
from app.services import discovery

router = APIRouter(tags=["Discover"])
TextFilter = Annotated[str | None, Query(min_length=1, max_length=255)]


@router.get("/discover", response_model=s.DiscoverResponse)
def discover(
    db: Database,
    q: str | None = None,
    source: s.SourceSlug | None = None,
    organization: TextFilter = None,
    category: TextFilter = None,
    deadline_before: AwareDatetime | None = None,
    limit: Limit = 20,
    cursor: Cursor = None,
):
    return discovery.search(
        db,
        q=q,
        source=source,
        organization=organization,
        category=category,
        deadline_before=deadline_before,
        limit=limit,
        cursor=cursor,
    )
