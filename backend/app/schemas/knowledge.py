from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class KnowledgeDocumentCreate(BaseModel):
    """Data needed to create knowledge document metadata."""

    filename: str = Field(min_length=1, max_length=255)
    file_type: str = Field(min_length=1, max_length=50)
    file_path: str | None = Field(default=None, max_length=500)
    file_size: int | None = Field(default=None, ge=0)
    status: str = Field(default="uploaded", min_length=1, max_length=30)


class KnowledgeDocumentResponse(BaseModel):
    """Knowledge document metadata returned by the API."""

    id: int
    filename: str
    file_type: str
    file_path: str | None
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
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
