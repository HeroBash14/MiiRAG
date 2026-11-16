import asyncio
import logging
import time
from dataclasses import replace

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.repositories.query_repo import (
    SimilarChunkRow,
    fetch_adjacent_chunks_map,
    search_hybrid_chunks,
)
from app.schemas.query import QueryRequest, QueryResponse, QueryResultItem
from app.services.embedding_service import embedding_service
from app.services.minio_service import minio_service
from app.services.query_enhancement_service import (
    blend_query_and_hyde_vectors,
    enhance_query,
)
from app.services.rerank_service import rerank_service

logger = logging.getLogger(__name__)


def _filter_and_sort_candidates(
    candidates: list[SimilarChunkRow],
    search_mode: str,
    score_threshold: float,
    reranked: bool,
) -> list[SimilarChunkRow]:
    """Menyaring kandidat di bawah threshold dan mengurutkan berdasarkan rerank / RRF / similarity."""
    if not candidates:
        return []

    filtered: list[SimilarChunkRow] = []
    if search_mode == "dense":
        filtered = [c for c in candidates if c.similarity_score >= score_threshold]
        if reranked:
            filtered.sort(
                key=lambda c: (c.rerank_score or 0.0, c.similarity_score),
                reverse=True,
            )
        else:
            filtered.sort(key=lambda c: c.similarity_score, reverse=True)
        return filtered

    if search_mode == "keyword":
        filtered = [c for c in candidates if c.keyword_score > 0.0]
        if reranked:
            filtered.sort(
                key=lambda c: (c.rerank_score or 0.0, c.keyword_score),
                reverse=True,
            )
        else:
            filtered.sort(key=lambda c: c.keyword_score, reverse=True)
        return filtered

    # Hybrid mode: pertahankan semantic hits + keyword rescue yang terverifikasi
    for c in candidates:
        if c.similarity_score >= score_threshold:
            filtered.append(c)
        elif c.keyword_score > 0.0 and score_threshold <= 0.85:
            if reranked:
                min_rerank = max(0.25, score_threshold * 0.65)
                if (c.rerank_score or 0.0) >= min_rerank:
                    filtered.append(c)
            elif c.keyword_score >= 0.08 or c.similarity_score >= score_threshold * 0.5:
                filtered.append(c)

    if reranked:
        filtered.sort(
            key=lambda c: (c.rerank_score or 0.0, c.rrf_score, c.similarity_score),
            reverse=True,
        )
    else:
        filtered.sort(
            key=lambda c: (c.rrf_score, c.similarity_score),
            reverse=True,
        )

    return filtered


def _build_expanded_content(
    hit: SimilarChunkRow,
    neighbor_map: dict[tuple, str],
) -> str:
    """Menggabungkan chunk target dengan chunk tetangga sebelum/sesudah untuk Context Window Expansion."""
    parts: list[str] = []
    if hit.chunk_index > 0:
        prev_txt = neighbor_map.get((hit.document_id, hit.chunk_index - 1))
        if prev_txt and prev_txt not in hit.content:
            parts.append(prev_txt.strip())

    parts.append(hit.content.strip())

    next_txt = neighbor_map.get((hit.document_id, hit.chunk_index + 1))
    if next_txt and next_txt not in hit.content:
        parts.append(next_txt.strip())

    return "\n\n".join(parts)


async def execute_similarity_query(payload: QueryRequest) -> QueryResponse:
    """Pipeline retrieval lengkap: Query Enhancement -> Hybrid Search (RRF) -> Cross-Encoder Rerank -> Context Expansion."""
    start_ns = time.perf_counter_ns()
    mode = payload.search_mode.lower().strip()

    # 1. Query Enhancement (HyDE / Query Expansion)
    enhanced = await enhance_query(
        query=payload.query,
        use_hyde=payload.use_hyde,
        use_query_expansion=payload.use_query_expansion,
    )

    # 2. Vector Embedding (jika mode bukan keyword-only)
    query_vector: list[float] | None = None
    if mode != "keyword":
        if enhanced.hyde_document:
            q_vec, h_vec = await asyncio.gather(
                embedding_service.embed_query(payload.query),
                embedding_service.embed_query(enhanced.hyde_document),
            )
            query_vector = blend_query_and_hyde_vectors(q_vec, h_vec)
        else:
            query_vector = await embedding_service.embed_query(payload.query)

    # 3. Retrieval Kandidat (Hybrid Dense + Sparse RRF, Dense, atau Keyword)
    candidate_limit = (
        max(payload.top_k * 3, settings.RERANK_CANDIDATE_LIMIT)
        if payload.use_rerank
        else (payload.top_k if mode == "dense" else max(payload.top_k * 2, 15))
    )

    async with AsyncSessionLocal() as session, session.begin():
        candidates = await search_hybrid_chunks(
            session=session,
            query_text=enhanced.sparse_query or payload.query,
            query_vector=query_vector,
            top_k=payload.top_k,
            score_threshold=payload.score_threshold,
            knowledge_ids=payload.knowledge_ids,
            search_mode=mode,
            candidate_limit=candidate_limit,
        )

    # 4. Cross-Encoder Reranking (di luar transaksi DB agar koneksi cepat bebas)
    reranked = False
    if payload.use_rerank and candidates:
        try:
            doc_inputs = [
                f"[{c.contextual_header}]\n\n{c.content}" if c.contextual_header else c.content
                for c in candidates
            ]
            scores = await rerank_service.rerank(payload.query, doc_inputs)
            candidates = [
                replace(c, rerank_score=round(float(score), 6))
                for c, score in zip(candidates, scores, strict=True)
            ]
            reranked = True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Reranker gagal dieksekusi (%s), menggunakan skor retrieval awal.", exc)

    # 5. Threshold Filtering & Final Sorting
    selected = _filter_and_sort_candidates(
        candidates=candidates,
        search_mode=mode,
        score_threshold=payload.score_threshold,
        reranked=reranked,
    )[: payload.top_k]

    # 6. Optional Context Window Expansion
    neighbor_map: dict[tuple, str] = {}
    if payload.expand_context and selected:
        async with AsyncSessionLocal() as session, session.begin():
            neighbor_map = await fetch_adjacent_chunks_map(session, selected)

    # 7. Format Output + Cache Presigned URL MinIO
    url_cache: dict[str, str | None] = {}
    results: list[QueryResultItem] = []
    for row in selected:
        img_obj = row.page_image_url
        if img_obj:
            if img_obj not in url_cache:
                url_cache[img_obj] = minio_service.get_presigned_url(img_obj)
            signed_url = url_cache[img_obj]
        else:
            signed_url = None

        results.append(
            QueryResultItem(
                chunk_id=row.chunk_id,
                knowledge_id=row.knowledge_id,
                knowledge_name=row.knowledge_name,
                version=row.version,
                document_id=row.document_id,
                filename=row.filename,
                page_number=row.page_number,
                chunk_index=row.chunk_index,
                content=row.content,
                similarity_score=row.similarity_score,
                page_image_url=signed_url,
                section_title=row.section_title,
                expanded_content=(
                    _build_expanded_content(row, neighbor_map) if payload.expand_context else None
                ),
                keyword_score=row.keyword_score if mode in ("hybrid", "keyword") else None,
                rerank_score=row.rerank_score,
            )
        )

    latency_ms = int((time.perf_counter_ns() - start_ns) / 1_000_000)
    return QueryResponse(
        query=payload.query,
        latency_ms=latency_ms,
        total_results=len(results),
        search_mode=mode,
        reranked=reranked,
        enhancement_used=enhanced.enhancement_used,
        hyde_document=enhanced.hyde_document,
        results=results,
    )
