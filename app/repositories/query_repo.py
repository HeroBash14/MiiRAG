import re
import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

_TOKEN_RE = re.compile(r"[0-9a-zA-Z]+")

# Stopwords ringan Indonesia & Inggris agar OR-tsquery fokus pada kata kunci bermakna
_STOPWORDS = frozenset(
    {
        "yang",
        "dan",
        "di",
        "ke",
        "dari",
        "untuk",
        "pada",
        "dengan",
        "adalah",
        "ini",
        "itu",
        "atau",
        "juga",
        "oleh",
        "sebagai",
        "dalam",
        "apa",
        "saja",
        "bagaimana",
        "cara",
        "siapa",
        "kapan",
        "dimana",
        "mengapa",
        "kenapa",
        "berapa",
        "apakah",
        "tolong",
        "jelaskan",
        "sebutkan",
        "the",
        "is",
        "are",
        "was",
        "were",
        "a",
        "an",
        "of",
        "in",
        "on",
        "at",
        "to",
        "for",
        "with",
        "by",
        "and",
        "or",
        "what",
        "how",
        "when",
        "where",
        "who",
        "why",
    }
)


@dataclass(frozen=True, slots=True)
class SimilarChunkRow:
    chunk_id: int
    knowledge_id: uuid.UUID
    knowledge_name: str
    version: int
    document_id: uuid.UUID
    filename: str
    page_number: int
    chunk_index: int
    content: str
    similarity_score: float
    page_image_url: str | None = None
    section_title: str | None = None
    contextual_header: str | None = None
    keyword_score: float = 0.0
    rrf_score: float = 0.0
    rerank_score: float | None = None


def build_or_tsquery(query: str, max_tokens: int = 16) -> str | None:
    """Membangun ekspresi PostgreSQL to_tsquery('simple', ...) berbasis OR dari token kata kunci."""
    raw_tokens = _TOKEN_RE.findall(query.lower())
    if not raw_tokens:
        return None

    filtered = [t for t in raw_tokens if t not in _STOPWORDS and len(t) > 1]
    if not filtered:
        filtered = raw_tokens

    deduped: list[str] = []
    seen: set[str] = set()
    for tok in filtered:
        if tok not in seen:
            seen.add(tok)
            deduped.append(tok)
        if len(deduped) >= max_tokens:
            break

    return " | ".join(deduped) if deduped else None


async def search_similar_chunks(
    session: AsyncSession,
    query_vector: list[float],
    top_k: int,
    score_threshold: float,
    knowledge_ids: list[uuid.UUID] | None = None,
) -> list[SimilarChunkRow]:
    """Pencarian dense vector murni di pgvector menggunakan Cosine Similarity + HNSW."""
    return await search_hybrid_chunks(
        session=session,
        query_text="",
        query_vector=query_vector,
        top_k=top_k,
        score_threshold=score_threshold,
        knowledge_ids=knowledge_ids,
        search_mode="dense",
        candidate_limit=top_k,
    )


async def search_hybrid_chunks(
    session: AsyncSession,
    query_text: str,
    query_vector: list[float] | None,
    top_k: int,
    score_threshold: float,
    knowledge_ids: list[uuid.UUID] | None = None,
    search_mode: str = "hybrid",
    candidate_limit: int | None = None,
) -> list[SimilarChunkRow]:
    """Mencari chunk menggunakan Hybrid Search (Dense pgvector + Sparse PostgreSQL FTS) dengan RRF."""
    mode = search_mode.lower().strip()
    if mode not in ("hybrid", "dense", "keyword"):
        mode = "hybrid"

    tsquery_expr = build_or_tsquery(query_text) if mode in ("hybrid", "keyword") and query_text else None
    if mode == "keyword" and not tsquery_expr:
        return []
    if mode == "hybrid" and not tsquery_expr:
        mode = "dense"

    limit = max(top_k, candidate_limit or max(top_k * 2, 15))

    if mode in ("hybrid", "dense"):
        if query_vector is None:
            raise ValueError("query_vector wajib tersedia untuk pencarian dense/hybrid.")
        ef_search = max(settings.HNSW_EF_SEARCH, limit * 2)
        await session.execute(text(f"SET LOCAL hnsw.ef_search = {int(ef_search)}"))
        await session.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))

    filter_clause = ""
    params: dict = {
        "limit_n": limit,
        "rrf_k": int(settings.HYBRID_RRF_K),
        "w_dense": float(settings.HYBRID_DENSE_WEIGHT),
        "w_sparse": float(settings.HYBRID_SPARSE_WEIGHT),
    }

    if knowledge_ids:
        filter_clause = "AND k.id = ANY(:knowledge_ids)"
        params["knowledge_ids"] = knowledge_ids

    if mode == "dense":
        vector_literal = "[" + ",".join(f"{v:.8f}" for v in query_vector) + "]"
        params["query_vec"] = vector_literal
        params["max_distance"] = 1.0 - score_threshold
        params["top_k"] = limit

        sql = text(
            f"""
            SELECT
                dc.id AS chunk_id,
                k.id AS knowledge_id,
                k.name AS knowledge_name,
                kv.version_number AS version,
                d.id AS document_id,
                d.filename AS filename,
                dc.page_number AS page_number,
                dc.chunk_index AS chunk_index,
                dc.content AS content,
                dc.metadata_json ->> 'section_title' AS section_title,
                dc.metadata_json ->> 'contextual_header' AS contextual_header,
                COALESCE(
                    dc.metadata_json ->> 'page_image_object',
                    dc.metadata_json ->> 'page_image_url'
                ) AS page_image_url,
                1.0 - (dc.embedding <=> CAST(:query_vec AS vector)) AS similarity_score,
                0.0 AS keyword_score,
                1.0 / (:rrf_k + ROW_NUMBER() OVER (ORDER BY dc.embedding <=> CAST(:query_vec AS vector) ASC)) AS rrf_score
            FROM document_chunks dc
            JOIN documents d ON d.id = dc.document_id
            JOIN knowledge_version_documents kvd ON kvd.document_id = d.id
            JOIN knowledge_versions kv ON kv.id = kvd.version_id
            JOIN knowledges k ON k.active_version_id = kv.id
            WHERE kv.status = 'done'
              AND d.status = 'embedded'
              AND (dc.embedding <=> CAST(:query_vec AS vector)) <= :max_distance
              {filter_clause}
            ORDER BY dc.embedding <=> CAST(:query_vec AS vector) ASC
            LIMIT :top_k
            """
        )

    elif mode == "keyword":
        params["tsq"] = tsquery_expr
        sql = text(
            f"""
            SELECT
                dc.id AS chunk_id,
                k.id AS knowledge_id,
                k.name AS knowledge_name,
                kv.version_number AS version,
                d.id AS document_id,
                d.filename AS filename,
                dc.page_number AS page_number,
                dc.chunk_index AS chunk_index,
                dc.content AS content,
                dc.metadata_json ->> 'section_title' AS section_title,
                dc.metadata_json ->> 'contextual_header' AS contextual_header,
                COALESCE(
                    dc.metadata_json ->> 'page_image_object',
                    dc.metadata_json ->> 'page_image_url'
                ) AS page_image_url,
                ts_rank_cd(dc.tsv, to_tsquery('simple', :tsq), 32) AS similarity_score,
                ts_rank_cd(dc.tsv, to_tsquery('simple', :tsq), 32) AS keyword_score,
                1.0 / (:rrf_k + ROW_NUMBER() OVER (ORDER BY ts_rank_cd(dc.tsv, to_tsquery('simple', :tsq), 32) DESC)) AS rrf_score
            FROM document_chunks dc
            JOIN documents d ON d.id = dc.document_id
            JOIN knowledge_version_documents kvd ON kvd.document_id = d.id
            JOIN knowledge_versions kv ON kv.id = kvd.version_id
            JOIN knowledges k ON k.active_version_id = kv.id
            WHERE kv.status = 'done'
              AND d.status = 'embedded'
              AND dc.tsv @@ to_tsquery('simple', :tsq)
              {filter_clause}
            ORDER BY keyword_score DESC, dc.id ASC
            LIMIT :limit_n
            """
        )

    else:
        # Hybrid mode: Reciprocal Rank Fusion antara Dense HNSW dan Sparse GIN tsvector
        vector_literal = "[" + ",".join(f"{v:.8f}" for v in query_vector) + "]"
        params["query_vec"] = vector_literal
        params["tsq"] = tsquery_expr
        pool_size = max(limit * 2, 30)
        params["pool_size"] = pool_size

        sql = text(
            f"""
            WITH dense_candidates AS (
                SELECT
                    dc.id AS chunk_id,
                    1.0 - (dc.embedding <=> CAST(:query_vec AS vector)) AS dense_score,
                    ROW_NUMBER() OVER (ORDER BY dc.embedding <=> CAST(:query_vec AS vector) ASC) AS dense_rank
                FROM document_chunks dc
                JOIN documents d ON d.id = dc.document_id
                JOIN knowledge_version_documents kvd ON kvd.document_id = d.id
                JOIN knowledge_versions kv ON kv.id = kvd.version_id
                JOIN knowledges k ON k.active_version_id = kv.id
                WHERE kv.status = 'done'
                  AND d.status = 'embedded'
                  {filter_clause}
                ORDER BY dc.embedding <=> CAST(:query_vec AS vector) ASC
                LIMIT :pool_size
            ),
            sparse_candidates AS (
                SELECT
                    dc.id AS chunk_id,
                    ts_rank_cd(dc.tsv, to_tsquery('simple', :tsq), 32) AS sparse_score,
                    ROW_NUMBER() OVER (
                        ORDER BY ts_rank_cd(dc.tsv, to_tsquery('simple', :tsq), 32) DESC, dc.id ASC
                    ) AS sparse_rank
                FROM document_chunks dc
                JOIN documents d ON d.id = dc.document_id
                JOIN knowledge_version_documents kvd ON kvd.document_id = d.id
                JOIN knowledge_versions kv ON kv.id = kvd.version_id
                JOIN knowledges k ON k.active_version_id = kv.id
                WHERE kv.status = 'done'
                  AND d.status = 'embedded'
                  AND dc.tsv @@ to_tsquery('simple', :tsq)
                  {filter_clause}
                ORDER BY sparse_score DESC, dc.id ASC
                LIMIT :pool_size
            ),
            fused AS (
                SELECT
                    COALESCE(d.chunk_id, s.chunk_id) AS chunk_id,
                    d.dense_score,
                    COALESCE(s.sparse_score, 0.0) AS keyword_score,
                    (
                        CASE WHEN d.dense_rank IS NOT NULL THEN :w_dense / (:rrf_k + d.dense_rank) ELSE 0.0 END
                        + CASE WHEN s.sparse_rank IS NOT NULL THEN :w_sparse / (:rrf_k + s.sparse_rank) ELSE 0.0 END
                    ) AS rrf_score
                FROM dense_candidates d
                FULL OUTER JOIN sparse_candidates s ON d.chunk_id = s.chunk_id
            )
            SELECT
                dc.id AS chunk_id,
                k.id AS knowledge_id,
                k.name AS knowledge_name,
                kv.version_number AS version,
                d.id AS document_id,
                d.filename AS filename,
                dc.page_number AS page_number,
                dc.chunk_index AS chunk_index,
                dc.content AS content,
                dc.metadata_json ->> 'section_title' AS section_title,
                dc.metadata_json ->> 'contextual_header' AS contextual_header,
                COALESCE(
                    dc.metadata_json ->> 'page_image_object',
                    dc.metadata_json ->> 'page_image_url'
                ) AS page_image_url,
                COALESCE(f.dense_score, 1.0 - (dc.embedding <=> CAST(:query_vec AS vector))) AS similarity_score,
                f.keyword_score AS keyword_score,
                f.rrf_score AS rrf_score
            FROM fused f
            JOIN document_chunks dc ON dc.id = f.chunk_id
            JOIN documents d ON d.id = dc.document_id
            JOIN knowledge_version_documents kvd ON kvd.document_id = d.id
            JOIN knowledge_versions kv ON kv.id = kvd.version_id
            JOIN knowledges k ON k.active_version_id = kv.id
            WHERE kv.status = 'done'
              AND d.status = 'embedded'
              {filter_clause}
            ORDER BY f.rrf_score DESC, similarity_score DESC
            LIMIT :limit_n
            """
        )

    result = await session.execute(sql, params)
    rows = result.mappings().all()

    return [
        SimilarChunkRow(
            chunk_id=row["chunk_id"],
            knowledge_id=row["knowledge_id"],
            knowledge_name=row["knowledge_name"],
            version=row["version"],
            document_id=row["document_id"],
            filename=row["filename"],
            page_number=row["page_number"],
            chunk_index=row["chunk_index"],
            content=row["content"],
            similarity_score=round(float(row["similarity_score"]), 6),
            page_image_url=row["page_image_url"],
            section_title=row["section_title"],
            contextual_header=row["contextual_header"],
            keyword_score=round(float(row["keyword_score"]), 6),
            rrf_score=round(float(row["rrf_score"]), 6),
        )
        for row in rows
    ]


async def fetch_adjacent_chunks_map(
    session: AsyncSession,
    hits: list[SimilarChunkRow],
) -> dict[tuple[uuid.UUID, int], str]:
    """Mengambil konten chunk tetangga (chunk_index - 1 dan + 1) untuk Context Window Expansion."""
    if not hits:
        return {}

    target_pairs: set[tuple[str, int]] = set()
    doc_ids: set[uuid.UUID] = set()
    target_indices: set[int] = set()
    for h in hits:
        doc_ids.add(h.document_id)
        if h.chunk_index > 0:
            target_pairs.add((str(h.document_id), h.chunk_index - 1))
            target_indices.add(h.chunk_index - 1)
        target_pairs.add((str(h.document_id), h.chunk_index + 1))
        target_indices.add(h.chunk_index + 1)

    if not target_pairs:
        return {}

    sql = text(
        """
        SELECT document_id, chunk_index, content
        FROM document_chunks
        WHERE document_id = ANY(:doc_ids)
          AND chunk_index = ANY(:chunk_indices)
        """
    )
    res = await session.execute(
        sql,
        {"doc_ids": list(doc_ids), "chunk_indices": list(target_indices)},
    )
    neighbor_map: dict[tuple[uuid.UUID, int], str] = {}
    for row in res.mappings().all():
        key = (row["document_id"], int(row["chunk_index"]))
        if (str(row["document_id"]), int(row["chunk_index"])) in target_pairs:
            neighbor_map[key] = row["content"]
    return neighbor_map
