from pathlib import Path
from pydantic import BaseModel, Field


class RepositorySnapshot(BaseModel):
    id: str
    source: str
    commit_sha: str | None = None
    manifest_hash: str = ""
    root: Path
    status: str = "importing"
    excluded_files: list[str] = Field(default_factory=list)
    manifest: dict[str, str] = Field(default_factory=dict)
    dirty: bool | None = None
    error_code: str | None = None
    source_type: str = "local"
    requested_ref: str | None = None
    archive_hash: str | None = None


class SearchHit(BaseModel):
    path: str
    symbol: str = ""
    start_line: int
    end_line: int
    score: float = 1


class IndexSummary(BaseModel):
    files: int = 0
    symbols: int = 0
    parse_errors: dict[str, str] = Field(default_factory=dict)


class Evidence(BaseModel):
    id: str
    snapshot_id: str
    path: str
    start_line: int
    end_line: int
    excerpt: str
    content_hash: str
    commit_sha: str | None = None


class ToolContext(BaseModel):
    snapshot_id: str
    task_id: str


class ToolResult(BaseModel):
    invocation_id: str
    status: str
    data: object = None
    evidence_ids: list[str] = Field(default_factory=list)
    error_code: str | None = None
    retryable: bool = False
    elapsed_ms: float = 0


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: object


class ModelUsage(BaseModel):
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)


class ModelTurn(BaseModel):
    tool_calls: list[ToolCall] = Field(default_factory=list)
    content: str = ""
    usage: ModelUsage | None = None


class Usage(BaseModel):
    model_calls: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated: bool = False
    elapsed_ms: float = 0
    revision: int = 0


class Claim(BaseModel):
    text: str = Field(min_length=1, max_length=10000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=30)
    verification_status: str = "unverified"


class TaskEvent(BaseModel):
    task_id: str = ""
    sequence: int = 0
    type: str
    payload: dict = Field(default_factory=dict)
    timestamp: str = ""


class AnalysisResult(BaseModel):
    status: str
    claims: list[Claim] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    markdown: str = ""
    usage: Usage
    evidence_ids: list[str] = Field(default_factory=list)


class AnalysisTask(BaseModel):
    id: str
    snapshot_id: str
    question: str
    status: str = "queued"
    cancel_requested: bool = False
    error_code: str | None = None
    usage: Usage | None = None
    created_at: str
    updated_at: str
