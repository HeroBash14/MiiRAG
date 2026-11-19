import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

GraphNodeType = Literal["document", "section", "concept", "reference"]
GraphEdgeType = Literal["contains", "mentions", "co_occurs", "semantic_bridge"]


class GraphStatsOut(BaseModel):
    total_nodes: int = 0
    total_edges: int = 0
    document_nodes: int = 0
    section_nodes: int = 0
    concept_nodes: int = 0
    reference_nodes: int = 0
    cross_document_edges: int = 0
    semantic_bridge_edges: int = 0
    built_at: datetime | None = None


class GraphNodeOut(BaseModel):
    id: uuid.UUID
    node_key: str
    label: str
    node_type: str
    description: str = ""
    degree: int = 0
    doc_frequency: int = 1
    chunk_count: int = 0
    document_id: uuid.UUID | None = None
    filenames: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    source_chunk_ids: list[int] = Field(default_factory=list)
    sample_snippets: list[str] = Field(default_factory=list)


class GraphEdgeOut(BaseModel):
    id: uuid.UUID
    source: uuid.UUID
    target: uuid.UUID
    edge_type: str
    weight: float
    label: str = ""
    keywords: str = ""
    description: str = ""
    is_cross_document: bool = False
    source_chunk_ids: list[int] = Field(default_factory=list)


class KnowledgeGraphResponse(BaseModel):
    knowledge_id: uuid.UUID
    knowledge_name: str
    version_id: uuid.UUID | None = None
    version_number: int
    status: Literal["ready", "empty"] = "empty"
    stats: GraphStatsOut
    nodes: list[GraphNodeOut] = Field(default_factory=list)
    edges: list[GraphEdgeOut] = Field(default_factory=list)


class GraphChunkSnippetOut(BaseModel):
    chunk_id: int
    document_id: uuid.UUID
    filename: str
    page_number: int
    chunk_index: int
    section_title: str | None = None
    content: str


class GraphNeighborOut(BaseModel):
    node_id: uuid.UUID
    label: str
    node_type: str
    edge_id: uuid.UUID
    edge_type: str
    edge_label: str
    weight: float
    is_cross_document: bool


class GraphNodeDetailResponse(BaseModel):
    node: GraphNodeOut
    neighbors: list[GraphNeighborOut] = Field(default_factory=list)
    chunks: list[GraphChunkSnippetOut] = Field(default_factory=list)
