from pathlib import Path

from pydantic import Field, SecretStr, field_validator
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

    @field_validator("document_storage_dir")
    @classmethod
    def resolve_storage_dir(cls, value: Path) -> Path:
        return (ENV_FILE.parent / value).resolve()

    @field_validator("postgres_password", "redis_password")
    @classmethod
    def validate_password(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and not value.get_secret_value().strip():
            raise ValueError("Password must not be empty")
        return value
