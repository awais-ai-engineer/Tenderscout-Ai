from pydantic import Field, model_validator

from app.ai.schemas import StrictOutput

VECTOR_DIMENSIONS = 1536


class ChunkConfig(StrictOutput):
    size: int = Field(default=2000, ge=256, le=8000)
    overlap: int = Field(default=250, ge=0)

    @model_validator(mode="after")
    def validate_overlap(self):
        if self.overlap >= self.size:
            raise ValueError("Chunk overlap must be smaller than chunk size")
        return self


class EmbeddingConfig(StrictOutput):
    model: str = Field(
        min_length=1, max_length=255, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$"
    )
    dimensions: int = VECTOR_DIMENSIONS
    batch_size: int = Field(default=16, ge=1, le=64)

    @model_validator(mode="after")
    def validate_dimensions(self):
        if self.dimensions != VECTOR_DIMENSIONS:
            raise ValueError(
                "Embedding dimensions must match the 1536-dimensional schema"
            )
        return self
