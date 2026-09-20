from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, HttpUrl


class SourceCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(max_length=100, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    base_url: HttpUrl
    is_active: bool = True


class SourceRead(SourceCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    last_scraped_at: AwareDatetime | None
    created_at: AwareDatetime
    updated_at: AwareDatetime
