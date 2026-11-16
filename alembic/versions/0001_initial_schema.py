"""Initial schema with pgvector extension and HNSW index

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-14

"""
from typing import Sequence, Union

from alembic import op
import pgvector.sqlalchemy
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    knowledge_status = postgresql.ENUM(
        "unfinished", "processing", "done", name="knowledge_status", create_type=False
    )
    document_status = postgresql.ENUM(
        "waiting", "processing", "embedded", "failed", name="document_status", create_type=False
    )
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE knowledge_status AS ENUM ('unfinished', 'processing', 'done'); "
        "EXCEPTION WHEN duplicate_object THEN null; END $$;"
    )
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE document_status AS ENUM ('waiting', 'processing', 'embedded', 'failed'); "
        "EXCEPTION WHEN duplicate_object THEN null; END $$;"
    )

    op.create_table(
        "knowledges",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", knowledge_status, nullable=False, server_default="unfinished"),
        sa.Column("current_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("active_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_knowledges_name", "knowledges", ["name"])
    op.create_index("ix_knowledges_status", "knowledges", ["status"])

    op.create_table(
        "knowledge_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "knowledge_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("knowledges.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("status", knowledge_status, nullable=False, server_default="unfinished"),
        sa.Column("doc_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("knowledge_id", "version_number", name="uq_knowledge_version_number"),
    )
    op.create_index("ix_knowledge_versions_knowledge_id", "knowledge_versions", ["knowledge_id"])

    op.create_foreign_key(
        "fk_knowledges_active_version",
        "knowledges",
        "knowledge_versions",
        ["active_version_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "knowledge_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("knowledges.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("file_hash", sa.String(64), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("status", document_status, nullable=False, server_default="waiting"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_documents_knowledge_id", "documents", ["knowledge_id"])
    op.create_index("ix_documents_status", "documents", ["status"])

    op.create_table(
        "knowledge_version_documents",
        sa.Column(
            "version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("knowledge_versions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    op.create_index(
        "ix_knowledge_version_documents_document_id",
        "knowledge_version_documents",
        ["document_id"],
    )

    op.create_table(
        "document_chunks",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("knowledge_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "metadata_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("embedding", pgvector.sqlalchemy.Vector(768), nullable=False),
    )
    op.create_index("ix_document_chunks_knowledge_id", "document_chunks", ["knowledge_id"])
    op.create_index("ix_document_chunks_document_id", "document_chunks", ["document_id"])
    op.create_index(
        "idx_document_chunks_embedding_hnsw",
        "document_chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_index("idx_document_chunks_embedding_hnsw", table_name="document_chunks")
    op.drop_index("ix_document_chunks_document_id", table_name="document_chunks")
    op.drop_index("ix_document_chunks_knowledge_id", table_name="document_chunks")
    op.drop_table("document_chunks")

    op.drop_index("ix_knowledge_version_documents_document_id", table_name="knowledge_version_documents")
    op.drop_table("knowledge_version_documents")

    op.drop_index("ix_documents_status", table_name="documents")
    op.drop_index("ix_documents_knowledge_id", table_name="documents")
    op.drop_table("documents")

    op.drop_constraint("fk_knowledges_active_version", "knowledges", type_="foreignkey")
    op.drop_index("ix_knowledge_versions_knowledge_id", table_name="knowledge_versions")
    op.drop_table("knowledge_versions")

    op.drop_index("ix_knowledges_status", table_name="knowledges")
    op.drop_index("ix_knowledges_name", table_name="knowledges")
    op.drop_table("knowledges")

    op.execute("DROP TYPE IF EXISTS document_status")
    op.execute("DROP TYPE IF EXISTS knowledge_status")
