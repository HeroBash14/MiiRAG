import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.knowledge import DocumentStatus, KnowledgeStatus


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    file_size: int
    status: DocumentStatus
    error_message: str | None = None
    page_count: int
    chunk_count: int
    created_at: datetime
    updated_at: datetime


class KnowledgeVersionOut(BaseModel):
    id: uuid.UUID
    version_number: int
    note: str | None = None
    status: KnowledgeStatus
    doc_count: int
    is_active: bool
    created_at: datetime


class KnowledgeStatusCounts(BaseModel):
    all: int
    unfinished: int
    processing: int
    done: int


class KnowledgeListItem(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None = None
    status: KnowledgeStatus
    current_version: int
    doc_count: int
    embedded_doc_count: int
    created_at: datetime
    updated_at: datetime


class KnowledgeListResponse(BaseModel):
    counts: KnowledgeStatusCounts
    items: list[KnowledgeListItem]


class KnowledgeDetailResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None = None
    status: KnowledgeStatus
    current_version: int
    active_version_id: uuid.UUID | None = None
    doc_count: int
    embedded_doc_count: int
    created_at: datetime
    updated_at: datetime
    documents: list[DocumentOut]
    version_history: list[KnowledgeVersionOut]
