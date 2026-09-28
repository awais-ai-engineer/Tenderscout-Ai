"""Small, explicit contract and registry for public procurement sources."""

from collections.abc import Callable
from dataclasses import dataclass

import httpx

from app.schemas.source import SourceCreate
from app.scrapers import contracts_finder, find_tender, ted, world_bank
from app.scrapers.records import ParsedListing, ScrapedTender

Fetcher = Callable[[httpx.Client, int, float], ParsedListing]
Searcher = Callable[[httpx.Client, str, int, float], ParsedListing]


def _matches(record: ScrapedTender, query: str) -> bool:
    needle = query.casefold()
    return any(
        needle in (value or "").casefold()
        for value in (
            record.title,
            record.description,
            record.organization,
            record.category,
        )
    )


def _bounded(listing: ParsedListing, limit: int) -> ParsedListing:
    unique = []
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    for record in listing.records:
        url = str(record.source_url)
        if url in seen_urls or (record.external_id and record.external_id in seen_ids):
            continue
        seen_urls.add(url)
        if record.external_id:
            seen_ids.add(record.external_id)
        unique.append(record)
    duplicates = len(listing.records) - len(unique)
    limited = max(0, len(unique) - limit)
    return ParsedListing(
        unique[:limit],
        listing.failed,
        listing.skipped + duplicates + limited,
        limited,
    )


def _contracts_refresh(client: httpx.Client, limit: int, timeout: float):
    listing = contracts_finder.parse_releases(
        contracts_finder.fetch_releases(client, timeout=timeout)
    )
    return _bounded(listing, limit)


def _contracts_search(client: httpx.Client, query: str, limit: int, timeout: float):
    listing = _contracts_refresh(client, contracts_finder.BATCH_LIMIT, timeout)
    return _bounded(
        ParsedListing(
            [record for record in listing.records if _matches(record, query)],
            listing.failed,
            listing.skipped,
        ),
        limit,
    )


def _find_refresh(client: httpx.Client, limit: int, timeout: float):
    return _bounded(
        find_tender.parse_listing(find_tender.fetch_listing(client, timeout=timeout)),
        limit,
    )


def _find_search(client: httpx.Client, query: str, limit: int, timeout: float):
    listing = _find_refresh(client, limit, timeout)
    return ParsedListing(
        [record for record in listing.records if _matches(record, query)],
        listing.failed,
        listing.skipped,
    )


def _ted_refresh(client: httpx.Client, limit: int, timeout: float):
    return ted.refresh(client, limit=limit, timeout=timeout)


def _ted_search(client: httpx.Client, query: str, limit: int, timeout: float):
    return ted.search(client, query=query, limit=limit, timeout=timeout)


def _world_bank_refresh(client: httpx.Client, limit: int, timeout: float):
    return _bounded(world_bank.fetch(client, limit=limit, timeout=timeout), limit)


def _world_bank_search(client: httpx.Client, query: str, limit: int, timeout: float):
    return _bounded(
        world_bank.fetch(client, limit=limit, timeout=timeout, query=query), limit
    )


@dataclass(frozen=True)
class SourceConnector:
    source: SourceCreate
    search_fn: Searcher
    refresh_fn: Fetcher
    supports_documents: bool = False

    @property
    def slug(self) -> str:
        return self.source.slug

    @property
    def display_name(self) -> str:
        return self.source.name

    def search(
        self, client: httpx.Client, query: str, *, limit: int, timeout: float
    ) -> ParsedListing:
        return self.search_fn(client, query, limit, timeout)

    def refresh(
        self, client: httpx.Client, *, limit: int, timeout: float
    ) -> ParsedListing:
        return self.refresh_fn(client, limit, timeout)


def registry(*connectors: SourceConnector) -> dict[str, SourceConnector]:
    values = {item.slug: item for item in connectors}
    if len(values) != len(connectors):
        raise ValueError("Source connector slugs must be unique")
    return values


SOURCE_CONNECTORS = registry(
    SourceConnector(
        contracts_finder.SOURCE,
        _contracts_search,
        _contracts_refresh,
        supports_documents=True,
    ),
    SourceConnector(find_tender.SOURCE, _find_search, _find_refresh),
    SourceConnector(ted.SOURCE, _ted_search, _ted_refresh),
    SourceConnector(world_bank.SOURCE, _world_bank_search, _world_bank_refresh),
)


def connector(slug: str) -> SourceConnector:
    try:
        return SOURCE_CONNECTORS[slug]
    except KeyError:
        raise ValueError("Unsupported source") from None
