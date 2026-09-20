"""Pydantic contracts shared by services and API endpoints."""

from __future__ import annotations

from typing import Any, Literal
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_file: str
    section: str | None = None
    page: int | None = None
    chunk_id: str
    score: float = Field(ge=0.0, le=1.0)


class RetrievalEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: str
    content: str
    source_file: str
    relative_path: str
    document_type: str
    page_number: int | None = None
    section_title: str | None = None
    vector_score: float = 0.0
    bm25_score: float = 0.0
    score: float = 0.0
    index_fingerprint: str = ""
    external_allowed: bool = False
    chunk_strategy: str = "text-window"


class DocumentChunk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: str
    project_id: str
    source_file: str
    relative_path: str
    document_type: str
    page_number: int | None = None
    section_title: str | None = None
    chunk_index: int = Field(ge=0)
    content: str
    file_hash: str
    updated_at: datetime
    vector: list[float] = Field(default_factory=list)
    index_fingerprint: str = ""
    external_allowed: bool = False
    chunk_strategy: str = "text-window"


class RAGQueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=1_000)
    project_id: str = Field(default="default", min_length=1, max_length=80)
    top_k: int = Field(default=5, ge=1, le=10)
    session_id: str | None = Field(default=None, min_length=1, max_length=100)
    allow_external_processing: bool = False

    @field_validator("question")
    @classmethod
    def question_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("question cannot be blank")
        return value


class CitationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str
    confidence: Literal["high", "medium", "low"]
    citations: list[Citation] = Field(default_factory=list)
    trace_id: str
    session_id: str | None = None


class IngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_path: str = Field(min_length=1, max_length=500)
    project_id: str = Field(default="default", min_length=1, max_length=80)
    allow_external_processing: bool = False


class IngestResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_file: str
    file_hash: str
    status: Literal["indexed", "unchanged"]
    chunk_count: int = Field(ge=0)
    trace_id: str


class ScanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(default="default", min_length=1, max_length=80)
    recursive: bool = True
    allow_external_processing: bool = False


class ScanFailure(BaseModel):
    relative_path: str
    error: str


class ScanResponse(BaseModel):
    project_id: str
    indexed: int = Field(ge=0)
    unchanged: int = Field(ge=0)
    failed: int = Field(ge=0)
    failures: list[ScanFailure] = Field(default_factory=list)
    trace_id: str


class AgentRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_goal: str = Field(min_length=1, max_length=1_000)
    project_id: str = Field(default="default", min_length=1, max_length=80)
    session_id: str | None = Field(default=None, min_length=1, max_length=100)
    allow_external_processing: bool = False

    @field_validator("user_goal")
    @classmethod
    def goal_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("user_goal cannot be blank")
        return value


class AgentConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1, max_length=100)
    confirm: bool


class LogEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    source_file: str
    relative_path: str
    line_number: int = Field(ge=1)
    content: str


class ChecklistItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    check_object: str
    method: str
    normal: str
    next_step: str
    citations: list[Citation] = Field(default_factory=list)


class AgentPlanStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: str
    label: str


class AgentStateModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    trace_id: str
    user_goal: str
    project_id: str = "default"
    summary: str = ""
    current_plan: list[AgentPlanStep] = Field(default_factory=list, max_length=4)
    completed_steps: list[str] = Field(default_factory=list)
    tool_results: list[dict[str, Any]] = Field(default_factory=list)
    retrieved_evidence: list[RetrievalEvidence] = Field(default_factory=list)
    log_evidence: list[LogEvidence] = Field(default_factory=list)
    pending_confirmation: bool = False
    error: str | None = None
    final_answer: str | None = None
    note_path: str | None = None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    mode: Literal["offline-mock", "configured"]
    trace_id: str
    checks: dict[str, str] = Field(default_factory=dict)


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody
    trace_id: str
