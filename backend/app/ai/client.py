from enum import StrEnum
from typing import Protocol


class ProviderFailure(StrEnum):
    TIMEOUT = "Provider request timed out"
    CONNECTION = "Provider connection failed"
    API = "Provider request failed"
    INVALID_OUTPUT = "Provider output failed schema validation"
    INCOMPLETE = "Provider response was incomplete"
    REFUSAL = "Provider refused or returned no structured output"


class ProviderError(RuntimeError):
    def __init__(self, reason: ProviderFailure):
        self.reason = ProviderFailure(reason)
        super().__init__(self.reason.value)


class StructuredLLMClient(Protocol):
    provider: str

    def generate(self, *, model: str, instructions: str, text: str) -> str:
        """Return the provider's JSON output, or raise a sanitized ProviderError."""
        ...
