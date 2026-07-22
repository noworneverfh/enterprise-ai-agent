from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class KnowledgeDocumentCreate(BaseModel):
    """Data needed to create knowledge document metadata."""

    original_filename: str = Field(min_length=1, max_length=255)
    storage_filename: str = Field(min_length=1, max_length=255)
    file_type: str = Field(min_length=1, max_length=50)
    file_path: str | None = Field(default=None, max_length=500)
    file_size: int | None = Field(default=None, ge=0)
    status: str = Field(default="uploaded", min_length=1, max_length=30)


class KnowledgeDocumentResponse(BaseModel):
    """Knowledge document metadata returned by the API."""

    id: int
    filename: str
    file_type: str
    file_size: int | None
    status: str
    chunk_count: int
    error_message: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class KnowledgeChunkCreate(BaseModel):
    """Data needed to create one knowledge text chunk."""

    document_id: int
    chunk_index: int = Field(ge=0)
    content: str = Field(min_length=1)
    content_hash: str | None = Field(default=None, max_length=64)
    vector_id: str | None = Field(default=None, max_length=100)
    start_char: int | None = Field(default=None, ge=0)
    end_char: int | None = Field(default=None, ge=0)


class KnowledgeChunkResponse(BaseModel):
    """Knowledge text chunk returned by the API."""

    id: int
    document_id: int
    chunk_index: int
    content: str
    content_hash: str | None
    vector_id: str | None
    start_char: int | None
    end_char: int | None
    section: str | None = None
    page: int | None = None
    chunk_metadata: dict | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class KnowledgeCitation(BaseModel):
    """Business citation metadata attached to one knowledge hit."""

    document: str
    section: str | None = None
    summary: str | None = None


class KnowledgeSearchResult(BaseModel):
    """One knowledge search result returned from vector retrieval."""

    chunk_id: int
    document_id: int
    filename: str
    chunk_index: int
    content: str
    source: str
    distance: float
    vector_score: float | None = None
    rerank_score: float | None = None
    citation: KnowledgeCitation | None = None
    fault_code: str | None = None
    device_type: str | None = None
    section: str | None = None


class FaultCauseResponse(BaseModel):
    id: int
    cause: str
    priority: int
    evidence: str | None = None
    verification_method: str | None = None

    model_config = ConfigDict(from_attributes=True)


class InspectionStepResponse(BaseModel):
    id: int
    order: int
    operation: str
    expected_result: str | None = None
    safety_requirement: str | None = None

    model_config = ConfigDict(from_attributes=True)


class MaintenanceActionResponse(BaseModel):
    id: int
    priority: int
    action: str
    condition: str | None = None

    model_config = ConfigDict(from_attributes=True)


class MaintenanceCaseResponse(BaseModel):
    id: int
    device: str
    fault: str
    symptom: str
    root_cause: str
    solution: str
    result: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class FaultKnowledgeEntryResponse(BaseModel):
    id: int
    document_id: int | None = None
    fault_code: str
    fault_name: str
    description: str
    severity: str
    device_type: str | None = None
    model: str | None = None
    trigger_conditions: dict | list | None = None
    causes: list[FaultCauseResponse] = []
    inspection_steps: list[InspectionStepResponse] = []
    maintenance_actions: list[MaintenanceActionResponse] = []
    cases: list[MaintenanceCaseResponse] = []

    model_config = ConfigDict(from_attributes=True)


class KnowledgeSearchRequest(BaseModel):
    """Knowledge search request body."""

    query: str
    top_k: int = Field(default=5, ge=1, le=20)

    @field_validator("query")
    @classmethod
    def validate_query(cls, query: str) -> str:
        stripped_query = query.strip()

        if not stripped_query:
            raise ValueError("query must not be empty.")

        return stripped_query


class KnowledgeSearchResponse(BaseModel):
    """Knowledge search response body."""

    query: str
    results: list[KnowledgeSearchResult]
