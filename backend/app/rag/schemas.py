from typing import Annotated

from pydantic import AfterValidator, Field, model_validator

from app.ai.schemas import StrictOutput, validate_storage_text

Quote = Annotated[
    str, Field(min_length=1, max_length=500), AfterValidator(validate_storage_text)
]
Answer = Annotated[
    str, Field(min_length=1, max_length=4000), AfterValidator(validate_storage_text)
]


class Citation(StrictOutput):
    chunk_id: int = Field(gt=0)
    quote: Quote


class TenderAnswerOutput(StrictOutput):
    answer: Answer | None
    citations: list[Citation] = Field(max_length=20)
    insufficient_evidence: bool

    @model_validator(mode="after")
    def consistent_answer(self):
        if self.insufficient_evidence:
            if self.answer is not None or self.citations:
                raise ValueError(
                    "Insufficient output must use null answer and no citations"
                )
        elif self.answer is None or not self.citations:
            raise ValueError("A supported answer requires text and citations")
        return self
