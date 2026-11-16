import enum
import uuid
from datetime import UTC, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Computed,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import settings
from app.core.database import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class KnowledgeStatus(str, enum.Enum):
    UNFINISHED = "unfinished"
    PROCESSING = "processing"
    DONE = "done"


class DocumentStatus(str, enum.Enum):
    WAITING = "waiting"
    PROCESSING = "processing"
    EMBEDDED = "embedded"
    FAILED = "failed"


class Knowledge(Base):
    """Entitas kumpulan dokumen pengetahuan RAG beserta versi dan statusnya."""

    __tablename__ = "knowledges"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[KnowledgeStatus] = mapped_column(
        Enum(KnowledgeStatus, name="knowledge_status", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=KnowledgeStatus.UNFINISHED,
        index=True,
    )
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    active_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "knowledge_versions.id",
            name="fk_knowledges_active_version",
            use_alter=True,
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    versions: Mapped[list["KnowledgeVersion"]] = relationship(
        "KnowledgeVersion",
        back_populates="knowledge",
        foreign_keys="KnowledgeVersion.knowledge_id",
        cascade="all, delete-orphan",
        order_by="KnowledgeVersion.version_number.desc()",
    )
    documents: Mapped[list["Document"]] = relationship(
        "Document",
        back_populates="knowledge",
        cascade="all, delete-orphan",
    )


class KnowledgeVersion(Base):
    """Riwayat versi knowledge (v1, v2, v3, ...) dan snapshot dokumennya."""

    __tablename__ = "knowledge_versions"
    __table_args__ = (
        UniqueConstraint("knowledge_id", "version_number", name="uq_knowledge_version_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    knowledge_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledges.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[KnowledgeStatus] = mapped_column(
        Enum(KnowledgeStatus, name="knowledge_status", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=KnowledgeStatus.UNFINISHED,
    )
    doc_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    knowledge: Mapped["Knowledge"] = relationship(
        "Knowledge",
        back_populates="versions",
        foreign_keys=[knowledge_id],
    )
    version_documents: Mapped[list["KnowledgeVersionDocument"]] = relationship(
        "KnowledgeVersionDocument",
        back_populates="version",
        cascade="all, delete-orphan",
    )


class Document(Base):
    """Metadata file PDF yang diupload serta status proses embedding-nya."""

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    knowledge_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledges.id", ondelete="CASCADE"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus, name="document_status", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=DocumentStatus.WAITING,
        index=True,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    knowledge: Mapped["Knowledge"] = relationship("Knowledge", back_populates="documents")
    version_links: Mapped[list["KnowledgeVersionDocument"]] = relationship(
        "KnowledgeVersionDocument",
        back_populates="document",
        cascade="all, delete-orphan",
    )
    chunks: Mapped[list["DocumentChunk"]] = relationship(
        "DocumentChunk",
        back_populates="document",
        cascade="all, delete-orphan",
    )


class KnowledgeVersionDocument(Base):
    """Tabel relasi M:N antara versi knowledge dan dokumen yang tergabung di dalamnya."""

    __tablename__ = "knowledge_version_documents"

    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_versions.id", ondelete="CASCADE"), primary_key=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True, index=True
    )

    version: Mapped["KnowledgeVersion"] = relationship(
        "KnowledgeVersion", back_populates="version_documents"
    )
    document: Mapped["Document"] = relationship("Document", back_populates="version_links")


class DocumentChunk(Base):
    """Potongan teks PDF beserta vector embedding untuk pencarian similarity di pgvector."""

    __tablename__ = "document_chunks"
    __table_args__ = (
        Index(
            "idx_document_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index(
            "idx_document_chunks_tsv_gin",
            "tsv",
            postgresql_using="gin",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    knowledge_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    embedding: Mapped[list[float]] = mapped_column(
        Vector(settings.EMBEDDING_DIMENSIONS), nullable=False
    )
    tsv: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('simple', coalesce(metadata_json->>'contextual_header', '') || ' ' || coalesce(content, ''))",
            persisted=True,
        ),
        nullable=True,
    )

    document: Mapped["Document"] = relationship("Document", back_populates="chunks")
