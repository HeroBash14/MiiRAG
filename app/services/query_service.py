import asyncio
import logging
import time
from dataclasses import replace

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.repositories.graph_repo import expand_candidates_via_graph
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


def _passes_graph_gate(
    c: SimilarChunkRow,
    score_threshold: float,
    reranked: bool,
    top_rerank: float = 0.0,
) -> bool:
    if not c.via_graph:
        return False
    if reranked:
        # Gunakan batas relatif terhadap skor reranker tertinggi agar tahan terhadap skala logit rendah multilingual
        relative_floor = min(0.18, max(0.002, top_rerank * 0.06))
        return (c.rerank_score or 0.0) >= relative_floor or c.similarity_score >= score_threshold * 0.85
    return c.similarity_score >= score_threshold * 0.75 or c.graph_score >= 0.72


def _select_with_graph_diversification(
    sorted_candidates: list[SimilarChunkRow],
    top_k: int,
    use_graph: bool,
    score_threshold: float,
) -> list[SimilarChunkRow]:
    """Saat Knowledge Graph aktif, mencegah 1 dokumen besar memonopoli seluruh slot Top-K
    bila terdapat potongan relevan lintas dokumen yang terhubung lewat Knowledge Graph.
    """
    if not use_graph or top_k < 3 or len(sorted_candidates) <= 1:
        return sorted_candidates[:top_k]

    base = list(sorted_candidates[:top_k])
    primary_doc_id = base[0].document_id
    primary_count = sum(1 for c in base if c.document_id == primary_doc_id)

    # Hanya lakukan diversifikasi jika dokumen utama memonopoli >= 80% slot Top-K
    if primary_count < max(2, int(top_k * 0.8)):
        return base

    tail_cross_doc = [
        c
        for c in sorted_candidates[top_k:]
        if c.document_id != primary_doc_id
        and (c.via_graph or c.graph_reason is not None)
        and (c.similarity_score >= score_threshold * 0.85 or c.via_graph)
    ]
    if not tail_cross_doc:
        return base

    # Maksimal slot lintas dokumen yang dipromosikan (mis. Top 5 -> maks 2, Top 10 -> maks 3)
    max_promote = max(1, min(3, top_k // 3))
    already_other_docs = {c.document_id for c in base if c.document_id != primary_doc_id}

    # Pilih secara round-robin per dokumen berbeda agar semua dokumen terhubung terwakili
    by_doc: dict = {}
    for c in tail_cross_doc:
        by_doc.setdefault(c.document_id, []).append(c)

    # Urutkan dokumen yang belum muncul di base terlebih dahulu
    doc_order = sorted(
        by_doc.keys(),
        key=lambda d_id: (
            d_id in already_other_docs,
            -(by_doc[d_id][0].rerank_score or 0.0),
            -by_doc[d_id][0].similarity_score,
        ),
    )

    promoted: list[SimilarChunkRow] = []
    round_idx = 0
    while len(promoted) < max_promote:
        added_this_round = False
        for d_id in doc_order:
            bucket = by_doc[d_id]
            if round_idx < len(bucket):
                chosen = bucket[round_idx]
                promoted.append(
                    replace(
                        chosen,
                        via_graph=True,
                        graph_reason=chosen.graph_reason or "Terhubung lintas dokumen via Knowledge Graph",
                    )
                )
                added_this_round = True
                if len(promoted) >= max_promote:
                    break
        if not added_this_round:
            break
        round_idx += 1

    if not promoted:
        return base

    keep_primary_slots = max(2, top_k - len(promoted))
    return [*base[:keep_primary_slots], *promoted][:top_k]


def _filter_and_sort_candidates(
    candidates: list[SimilarChunkRow],
    search_mode: str,
    score_threshold: float,
    reranked: bool,
) -> list[SimilarChunkRow]:
    """Menyaring kandidat di bawah threshold dan mengurutkan berdasarkan rerank / RRF / similarity."""
    if not candidates:
        return []

    top_rerank = max((c.rerank_score or 0.0) for c in candidates) if reranked else 0.0

    filtered: list[SimilarChunkRow] = []
    if search_mode == "dense":
        filtered = [
            c
            for c in candidates
            if c.similarity_score >= score_threshold
            or _passes_graph_gate(c, score_threshold, reranked, top_rerank)
        ]
        if reranked:
            filtered.sort(
                key=lambda c: (c.rerank_score or 0.0, c.similarity_score, c.graph_score),
                reverse=True,
            )
        else:
            filtered.sort(
                key=lambda c: (max(c.similarity_score, c.graph_score * 0.85), c.similarity_score),
                reverse=True,
            )
        return filtered

    if search_mode == "keyword":
        filtered = [
            c
            for c in candidates
            if c.keyword_score > 0.0
            or _passes_graph_gate(c, score_threshold, reranked, top_rerank)
        ]
        if reranked:
            filtered.sort(
                key=lambda c: (c.rerank_score or 0.0, c.keyword_score, c.graph_score),
                reverse=True,
            )
        else:
            filtered.sort(key=lambda c: (c.keyword_score, c.graph_score), reverse=True)
        return filtered

    # Hybrid mode: pertahankan semantic hits + keyword rescue + graph-expanded cross-doc hits
    for c in candidates:
        if c.similarity_score >= score_threshold or _passes_graph_gate(
            c, score_threshold, reranked, top_rerank
        ):
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
            key=lambda c: (c.rrf_score, max(c.similarity_score, c.graph_score * 0.85)),
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

    graph_used = False
    graph_nodes_matched: list[str] = []

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

        # 3B. Zero-LLM Knowledge Graph Cross-Document Expansion (opsional)
        if payload.use_graph and settings.KG_ENABLED:
            try:
                g_exp = await expand_candidates_via_graph(
                    session=session,
                    query_text=payload.query,
                    query_vector=query_vector,
                    initial_candidates=candidates,
                    knowledge_ids=payload.knowledge_ids,
                    score_threshold=payload.score_threshold,
                    max_expanded_chunks=min(
                        max(payload.top_k, 4), settings.KG_QUERY_MAX_EXPANDED_CHUNKS
                    ),
                )
                graph_nodes_matched = g_exp.matched_node_labels
                if g_exp.chunk_entities_map or g_exp.existing_graph_links:
                    enriched_candidates: list[SimilarChunkRow] = []
                    for c in candidates:
                        link_info = g_exp.existing_graph_links.get(c.chunk_id)
                        enriched_candidates.append(
                            replace(
                                c,
                                related_entities=tuple(g_exp.chunk_entities_map.get(c.chunk_id, ())),
                                graph_score=round(link_info[0], 4) if link_info else c.graph_score,
                                graph_reason=link_info[1] if link_info else c.graph_reason,
                            )
                        )
                    candidates = enriched_candidates
                if g_exp.expanded_rows:
                    candidates = [*candidates, *g_exp.expanded_rows]
                if g_exp.expanded_rows or g_exp.matched_node_labels or g_exp.chunk_entities_map:
                    graph_used = True
            except Exception as exc:  # noqa: BLE001
                logger.warning("Knowledge Graph expansion dilewati karena galat: %s", exc)

    # 4. Cross-Encoder Reranking (di luar transaksi DB agar koneksi cepat bebas)
    reranked = False
    if payload.use_rerank and candidates:
        try:
            doc_inputs = [
                (
                    f"[{c.contextual_header}]\n\n{c.search_text or c.content}"
                    if c.contextual_header
                    else (c.search_text or c.content)
                )
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

    # 5. Threshold Filtering, Final Sorting & Cross-Document Graph Diversification
    sorted_filtered = _filter_and_sort_candidates(
        candidates=candidates,
        search_mode=mode,
        score_threshold=payload.score_threshold,
        reranked=reranked,
    )
    selected = _select_with_graph_diversification(
        sorted_candidates=sorted_filtered,
        top_k=payload.top_k,
        use_graph=payload.use_graph and graph_used,
        score_threshold=payload.score_threshold,
    )

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
                via_graph=row.via_graph,
                graph_reason=row.graph_reason,
                related_entities=list(row.related_entities),
            )
        )

    latency_ms = int((time.perf_counter_ns() - start_ns) / 1_000_000)
    return QueryResponse(
        query=payload.query,
        latency_ms=latency_ms,
        total_results=len(results),
        search_mode=mode,
        reranked=reranked,
        graph_used=graph_used,
        graph_nodes_matched=graph_nodes_matched,
        enhancement_used=enhanced.enhancement_used,
        hyde_document=enhanced.hyde_document,
        results=results,
    )
