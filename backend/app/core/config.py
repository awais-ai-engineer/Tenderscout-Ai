from pathlib import Path

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    postgres_host: str = Field(default="localhost", min_length=1)
    postgres_port: int = Field(default=5432, ge=1, le=65535)
    postgres_db: str = Field(default="tenderscout", min_length=1)
    postgres_user: str = Field(default="tenderscout", min_length=1)
    postgres_password: SecretStr

    redis_host: str = Field(default="localhost", min_length=1)
    redis_port: int = Field(default=6379, ge=1, le=65535)
    redis_db: int = Field(default=0, ge=0)
    redis_password: SecretStr | None = None

    document_storage_dir: Path = Path(".data/documents")
    document_max_bytes: int = Field(default=26214400, gt=0)
    document_max_pages: int = Field(default=500, gt=0)

    openai_api_key: SecretStr | None = None
    ai_model: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$",
    )
    ai_max_input_chars: int = Field(default=60000, ge=128)
    ai_embedding_model: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$",
    )
    ai_embedding_dimensions: int = Field(default=1536, ge=1536, le=1536)
    rag_chunk_size_chars: int = Field(default=2000, ge=256, le=8000)
    rag_chunk_overlap_chars: int = Field(default=250, ge=0)
    rag_embedding_batch_size: int = Field(default=16, ge=1, le=64)
    rag_top_k: int = Field(default=5, ge=1, le=20)
    rag_max_context_chars: int = Field(default=12000, ge=256, le=64000)

    @model_validator(mode="after")
    def validate_chunk_overlap(self):
        if self.rag_chunk_overlap_chars >= self.rag_chunk_size_chars:
            raise ValueError("Chunk overlap must be smaller than chunk size")
        return self

    @field_validator("document_storage_dir")
    @classmethod
    def resolve_storage_dir(cls, value: Path) -> Path:
        return (ENV_FILE.parent / value).resolve()

    @field_validator("postgres_password", "redis_password", "openai_api_key")
    @classmethod
    def validate_secret(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and not value.get_secret_value().strip():
            raise ValueError("Secret must not be empty")
        return value
