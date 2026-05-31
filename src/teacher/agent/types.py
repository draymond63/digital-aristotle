from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict


ContextFormat = Literal["messages", "transcript", "packet"]
ResponseT = TypeVar("ResponseT", bound="ResponseObject")


class ResponseObject(BaseModel):
    """Provide JSON serialization defaults for structured task responses."""

    model_config = ConfigDict(extra="ignore")

    def json_data(self):
        """Return model data in JSON-compatible form."""
        return self.model_dump(mode="json")


@dataclass(frozen=True)
class Task(Generic[ResponseT]):
    """Describe one model task and its generation settings."""

    name: str
    static_prompt: str
    model: str | None = None
    context_format: ContextFormat = "messages"
    visible_history: int | None = None
    dynamic_after_context: bool = False
    output_format: type[ResponseT] | None = None
    temperature: float = 0.5
    num_ctx: int = 4096
    num_predict: int = 1000
    top_p: float = 0.85
    repeat_penalty: float = 1.12
