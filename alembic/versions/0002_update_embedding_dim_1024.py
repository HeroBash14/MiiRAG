"""Update embedding dimension to 1024 for BAAI/bge-m3

Revision ID: 0002_dim_1024
Revises: 0001_initial
Create Date: 2026-11-15

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0002_dim_1024"
down_revision: Union[str, Sequence[str], None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop HNSW index before changing vector dimension
    op.drop_index("idx_document_chunks_embedding_hnsw", table_name="document_chunks")

    # Clear existing chunks because 768-dim vectors cannot be cast to 1024-dim
    op.execute("TRUNCATE TABLE document_chunks")

    # Reset any documents to 'waiting' so they can be embedded with the new model
    op.execute(
        "UPDATE documents SET status = 'waiting', chunk_count = 0 WHERE status = 'embedded'"
    )
    op.execute(
        "UPDATE knowledges SET status = 'unfinished' WHERE status = 'done'"
    )
    op.execute(
        "UPDATE knowledge_versions SET status = 'unfinished' WHERE status = 'done'"
    )

    # Alter column to vector(1024)
    op.execute("ALTER TABLE document_chunks ALTER COLUMN embedding TYPE vector(1024)")

    # Recreate HNSW index for vector(1024)
    op.execute(
        "CREATE INDEX idx_document_chunks_embedding_hnsw "
        "ON document_chunks "
        "USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )


def downgrade() -> None:
    op.drop_index("idx_document_chunks_embedding_hnsw", table_name="document_chunks")
    op.execute("TRUNCATE TABLE document_chunks")
    op.execute("ALTER TABLE document_chunks ALTER COLUMN embedding TYPE vector(768)")
    op.execute(
        "CREATE INDEX idx_document_chunks_embedding_hnsw "
        "ON document_chunks "
        "USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )
