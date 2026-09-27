"""Typed contracts for prompts, retrieval, memory, and RAG evaluation."""

from __future__ import annotations

from datetime import datetime, timezone
from string import Formatter
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator


class PromptTechnique(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    template: str = Field(min_length=1)
    examples: list[dict[str, str]] = Field(default_factory=list)


class PromptSecurity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sanitize_input: bool = True
    detect_injection: bool = True
    mask_pii: bool = True
    prevent_jailbreaks: bool = True
    block_injection: bool = True


class ScalingPromptEngineering(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    template: str = Field(min_length=1)
    variables: list[str] = Field(default_factory=list)
    version: int = Field(default=1, ge=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("variables")
    @classmethod
    def variables_must_be_unique(cls, variables: list[str]) -> list[str]:
        if len(variables) != len(set(variables)):
            raise ValueError("Prompt template variables must be unique.")
        return variables

    def render(self, **values: str) -> str:
        referenced = {name for _, name, _, _ in Formatter().parse(self.template) if name}
        missing = referenced - values.keys()
        undeclared = referenced - set(self.variables)
        if missing:
            raise ValueError(f"Missing prompt variables: {', '.join(sorted(missing))}.")
        if undeclared:
            raise ValueError(f"Undeclared prompt variables: {', '.join(sorted(undeclared))}.")
        return self.template.format_map(values)


class SecurityInspection(BaseModel):
    sanitized_text: str
    detected_injection: bool = False
    detected_pii: bool = False
    blocked: bool = False
    findings: list[str] = Field(default_factory=list)


class DocumentChunk(BaseModel):
    id: str
    text: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)
    index: int = Field(ge=0)


class RetrievedChunk(DocumentChunk):
    score: float = Field(ge=-1.0, le=1.0)


class VectorRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    namespace: str = Field(min_length=1)
    text: str = Field(min_length=1)
    embedding: list[float] = Field(min_length=1)
    embedding_provider: str
    embedding_model: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ConversationMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str = Field(pattern=r"^(system|user|assistant|tool)$")
    content: str


class SemanticEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_query: str
    reference_answer: str
    model_output: str
    similarity: float = Field(ge=-1.0, le=1.0)
    threshold: float = Field(ge=-1.0, le=1.0)
    passed: bool
    similarity_delta: float
    embedding_model: str

    @computed_field
    @property
    def status(self) -> Literal["PASS", "FAIL"]:
        return "PASS" if self.passed else "FAIL"


class RAGResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str
    retrieved_chunks: list[RetrievedChunk] = Field(default_factory=list)
    evaluation: SemanticEvaluation | None = None