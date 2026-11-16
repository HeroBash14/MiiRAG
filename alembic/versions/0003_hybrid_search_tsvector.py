"""Add generated tsvector column and GIN index for hybrid search

Revision ID: 0003_hybrid_tsv
Revises: 0002_dim_1024
Create Date: 2026-11-16

"""
from collections.abc import Sequence

from alembic import op

revision: str = "0003_hybrid_tsv"
down_revision: str | Sequence[str] | None = "0002_dim_1024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE document_chunks "
        "ADD COLUMN IF NOT EXISTS tsv tsvector "
        "GENERATED ALWAYS AS ("
        "to_tsvector('simple', coalesce(metadata_json->>'contextual_header', '') || ' ' || coalesce(content, ''))"
        ") STORED"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_document_chunks_tsv_gin "
        "ON document_chunks USING gin (tsv)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_document_chunks_tsv_gin")
    op.execute("ALTER TABLE document_chunks DROP COLUMN IF EXISTS tsv")
