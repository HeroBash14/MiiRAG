import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import settings
from app.core.database import Base
from app.models.knowledge import utc_now


class KGNode(Base):
    """Node pada Zero-LLM Knowledge Graph (dokumen, bagian/sheet, konsep lintas dokumen, kode referensi)."""

    __tablename__ = "kg_nodes"
    __table_args__ = (
        UniqueConstraint("version_id", "node_key", name="uq_kg_nodes_version_key"),
        Index("idx_kg_nodes_knowledge_version", "knowledge_id", "version_id"),
        Index("idx_kg_nodes_version_type", "version_id", "node_type"),
        Index(
            "idx_kg_nodes_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    knowledge_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledges.id", ondelete="CASCADE"), nullable=False
    )
    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_versions.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=True
    )
    node_key: Mapped[str] = mapped_column(String(255), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    node_type: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    degree: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    doc_frequency: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_doc_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    source_chunk_ids: Mapped[list[int]] = mapped_column(JSONB, nullable=False, default=list)
    properties_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    embedding: Mapped[list[float]] = mapped_column(
        Vector(settings.EMBEDDING_DIMENSIONS), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class KGEdge(Base):
    """Relasi antar node pada Zero-LLM Knowledge Graph (contains, mentions, co_occurs, semantic_bridge)."""

    __tablename__ = "kg_edges"
    __table_args__ = (
        UniqueConstraint(
            "version_id",
            "source_node_id",
            "target_node_id",
            "edge_type",
            name="uq_kg_edges_version_pair_type",
        ),
        Index("idx_kg_edges_knowledge_version", "knowledge_id", "version_id"),
        Index("idx_kg_edges_source", "source_node_id"),
        Index("idx_kg_edges_target", "target_node_id"),
        Index("idx_kg_edges_cross_doc", "version_id", "is_cross_document"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    knowledge_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledges.id", ondelete="CASCADE"), nullable=False
    )
    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_versions.id", ondelete="CASCADE"), nullable=False
    )
    source_node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("kg_nodes.id", ondelete="CASCADE"), nullable=False
    )
    target_node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("kg_nodes.id", ondelete="CASCADE"), nullable=False
    )
    edge_type: Mapped[str] = mapped_column(String(32), nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    label: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    keywords: Mapped[str] = mapped_column(Text, nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_cross_document: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_chunk_ids: Mapped[list[int]] = mapped_column(JSONB, nullable=False, default=list)
    properties_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
