from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, HttpUrl


class TenderCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    source_id: int = Field(gt=0)
    external_id: str | None = Field(default=None, min_length=1, max_length=255)
    title: str = Field(min_length=1)
    organization: str | None = Field(default=None, max_length=255)
    description: str | None = None
    source_url: HttpUrl
    category: str | None = Field(default=None, max_length=255)
    location: str | None = Field(default=None, max_length=255)
    published_at: AwareDatetime | None = None
    deadline: AwareDatetime | None = None
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")


class TenderRead(TenderCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    first_seen_at: AwareDatetime
    last_seen_at: AwareDatetime
    created_at: AwareDatetime
    updated_at: AwareDatetime
