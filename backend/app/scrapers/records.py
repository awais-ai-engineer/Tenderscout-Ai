from dataclasses import dataclass, field

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, HttpUrl


class ScrapedTender(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    external_id: str | None = Field(default=None, min_length=1, max_length=255)
    title: str = Field(min_length=1)
    organization: str | None = Field(default=None, max_length=255)
    description: str | None = None
    source_url: HttpUrl
    category: str | None = Field(default=None, max_length=255)
    location: str | None = Field(default=None, max_length=255)
    published_at: AwareDatetime | None = None
    deadline: AwareDatetime | None = None


@dataclass
class ParsedListing:
    records: list[ScrapedTender] = field(default_factory=list)
    failed: int = 0
    skipped: int = 0
    limited: int = 0

    @property
    def discovered(self) -> int:
        return len(self.records) + self.failed + self.skipped


class DiscoveredDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    tender_external_id: str = Field(min_length=1, max_length=255)
    source_document_id: str | None = Field(default=None, min_length=1, max_length=255)
    title: str | None = None
    source_url: HttpUrl
    document_type: str | None = Field(default=None, max_length=255)
    media_type: str | None = Field(default=None, max_length=255)


@dataclass
class DiscoveredDocuments:
    records: list[DiscoveredDocument] = field(default_factory=list)
    failed: int = 0
