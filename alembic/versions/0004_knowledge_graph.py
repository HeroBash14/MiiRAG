"""Add Zero-LLM Knowledge Graph tables (kg_nodes, kg_edges) with pgvector HNSW index

Revision ID: 0004_knowledge_graph
Revises: 0003_hybrid_tsv
Create Date: 2026-11-19

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004_knowledge_graph"
down_revision: str | Sequence[str] | None = "0003_hybrid_tsv"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS kg_nodes (
            id UUID PRIMARY KEY,
            knowledge_id UUID NOT NULL REFERENCES knowledges(id) ON DELETE CASCADE,
            version_id UUID NOT NULL REFERENCES knowledge_versions(id) ON DELETE CASCADE,
            document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
            node_key VARCHAR(255) NOT NULL,
            label VARCHAR(255) NOT NULL,
            node_type VARCHAR(32) NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            degree INTEGER NOT NULL DEFAULT 0,
            doc_frequency INTEGER NOT NULL DEFAULT 1,
            chunk_count INTEGER NOT NULL DEFAULT 0,
            source_doc_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
            source_chunk_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
            properties_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            embedding vector(1024) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_kg_nodes_version_key UNIQUE (version_id, node_key)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_kg_nodes_knowledge_version "
        "ON kg_nodes (knowledge_id, version_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_kg_nodes_version_type "
        "ON kg_nodes (version_id, node_type)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_kg_nodes_embedding_hnsw "
        "ON kg_nodes USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS kg_edges (
            id UUID PRIMARY KEY,
            knowledge_id UUID NOT NULL REFERENCES knowledges(id) ON DELETE CASCADE,
            version_id UUID NOT NULL REFERENCES knowledge_versions(id) ON DELETE CASCADE,
            source_node_id UUID NOT NULL REFERENCES kg_nodes(id) ON DELETE CASCADE,
            target_node_id UUID NOT NULL REFERENCES kg_nodes(id) ON DELETE CASCADE,
            edge_type VARCHAR(32) NOT NULL,
            weight DOUBLE PRECISION NOT NULL DEFAULT 1.0,
            label VARCHAR(255) NOT NULL DEFAULT '',
            keywords TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            is_cross_document BOOLEAN NOT NULL DEFAULT FALSE,
            source_chunk_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
            properties_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_kg_edges_version_pair_type UNIQUE (version_id, source_node_id, target_node_id, edge_type)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_kg_edges_knowledge_version "
        "ON kg_edges (knowledge_id, version_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_kg_edges_source ON kg_edges (source_node_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_kg_edges_target ON kg_edges (target_node_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_kg_edges_cross_doc "
        "ON kg_edges (version_id, is_cross_document)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS kg_edges CASCADE")
    op.execute("DROP TABLE IF EXISTS kg_nodes CASCADE")
