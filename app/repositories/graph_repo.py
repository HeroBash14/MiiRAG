import re
import uuid
from collections import defaultdict
from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.knowledge import Document, DocumentChunk, Knowledge, KnowledgeVersion
from app.models.knowledge_graph import KGEdge, KGNode
from app.repositories.query_repo import SimilarChunkRow
from app.schemas.graph import (
    GraphChunkSnippetOut,
    GraphEdgeOut,
    GraphNeighborOut,
    GraphNodeDetailResponse,
    GraphNodeOut,
    GraphStatsOut,
    KnowledgeGraphResponse,
)


@dataclass(frozen=True, slots=True)
class GraphExpansionResult:
    expanded_rows: list[SimilarChunkRow]
    chunk_entities_map: dict[int, list[str]]
    matched_node_labels: list[str]
    existing_graph_links: dict[int, tuple[float, str]]


def _node_to_schema(node: KGNode) -> GraphNodeOut:
    props = node.properties_json or {}
    return GraphNodeOut(
        id=node.id,
        node_key=node.node_key,
        label=node.label,
        node_type=node.node_type,
        description=node.description,
        degree=node.degree,
        doc_frequency=node.doc_frequency,
        chunk_count=node.chunk_count,
        document_id=node.document_id,
        filenames=list(props.get("filenames") or []),
        aliases=list(props.get("aliases") or []),
        source_chunk_ids=list(node.source_chunk_ids or []),
        sample_snippets=list(props.get("sample_snippets") or []),
    )


def _edge_to_schema(edge: KGEdge) -> GraphEdgeOut:
    return GraphEdgeOut(
        id=edge.id,
        source=edge.source_node_id,
        target=edge.target_node_id,
        edge_type=edge.edge_type,
        weight=round(float(edge.weight), 4),
        label=edge.label,
        keywords=edge.keywords,
        description=edge.description,
        is_cross_document=edge.is_cross_document,
        source_chunk_ids=list(edge.source_chunk_ids or []),
    )


async def resolve_target_version(
    session: AsyncSession,
    knowledge_id: uuid.UUID,
    version_id: uuid.UUID | None = None,
) -> tuple[Knowledge, KnowledgeVersion | None]:
    knowledge = await session.get(Knowledge, knowledge_id)
    if knowledge is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge tidak ditemukan.")

    target_vid = version_id or knowledge.active_version_id
    version: KnowledgeVersion | None = None
    if target_vid is not None:
        version = await session.get(KnowledgeVersion, target_vid)
        if version is not None and version.knowledge_id != knowledge.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Versi knowledge tidak ditemukan pada knowledge ini.",
            )

    if version is None:
        stmt = (
            select(KnowledgeVersion)
            .where(KnowledgeVersion.knowledge_id == knowledge.id)
            .order_by(KnowledgeVersion.version_number.desc())
            .limit(1)
        )
        version = (await session.execute(stmt)).scalar_one_or_none()

    return knowledge, version


async def fetch_knowledge_graph(
    session: AsyncSession,
    knowledge_id: uuid.UUID,
    version_id: uuid.UUID | None = None,
    include_sections: bool = True,
    node_types: list[str] | None = None,
    min_weight: float = 0.0,
    max_nodes: int = 250,
) -> KnowledgeGraphResponse:
    """Mengambil data Knowledge Graph (nodes, edges, statistik) untuk satu versi knowledge."""
    knowledge, version = await resolve_target_version(session, knowledge_id, version_id)
    if version is None:
        return KnowledgeGraphResponse(
            knowledge_id=knowledge.id,
            knowledge_name=knowledge.name,
            version_id=None,
            version_number=knowledge.current_version,
            status="empty",
            stats=GraphStatsOut(),
            nodes=[],
            edges=[],
        )

    all_nodes_stmt = (
        select(KGNode)
        .where(KGNode.version_id == version.id)
        .order_by(
            KGNode.doc_frequency.desc(),
            KGNode.degree.desc(),
            KGNode.label.asc(),
        )
    )
    all_nodes = list((await session.execute(all_nodes_stmt)).scalars().all())

    all_edges_stmt = (
        select(KGEdge)
        .where(KGEdge.version_id == version.id)
        .order_by(KGEdge.is_cross_document.desc(), KGEdge.weight.desc())
    )
    all_edges = list((await session.execute(all_edges_stmt)).scalars().all())

    if not all_nodes:
        return KnowledgeGraphResponse(
            knowledge_id=knowledge.id,
            knowledge_name=knowledge.name,
            version_id=version.id,
            version_number=version.version_number,
            status="empty",
            stats=GraphStatsOut(),
            nodes=[],
            edges=[],
        )

    built_at = max((n.created_at for n in all_nodes), default=None)
    stats = GraphStatsOut(
        total_nodes=len(all_nodes),
        total_edges=len(all_edges),
        document_nodes=sum(1 for n in all_nodes if n.node_type == "document"),
        section_nodes=sum(1 for n in all_nodes if n.node_type == "section"),
        concept_nodes=sum(1 for n in all_nodes if n.node_type == "concept"),
        reference_nodes=sum(1 for n in all_nodes if n.node_type == "reference"),
        cross_document_edges=sum(1 for e in all_edges if e.is_cross_document),
        semantic_bridge_edges=sum(1 for e in all_edges if e.edge_type == "semantic_bridge"),
        built_at=built_at,
    )

    allowed_types: set[str] | None = set(node_types) if node_types else None
    filtered_nodes: list[KGNode] = []
    for n in all_nodes:
        if not include_sections and n.node_type == "section":
            continue
        if allowed_types is not None and n.node_type not in allowed_types:
            continue
        filtered_nodes.append(n)
        if len(filtered_nodes) >= max_nodes:
            break

    kept_ids = {n.id for n in filtered_nodes}
    filtered_edges = [
        e
        for e in all_edges
        if e.source_node_id in kept_ids
        and e.target_node_id in kept_ids
        and e.weight >= min_weight
    ]

    return KnowledgeGraphResponse(
        knowledge_id=knowledge.id,
        knowledge_name=knowledge.name,
        version_id=version.id,
        version_number=version.version_number,
        status="ready",
        stats=stats,
        nodes=[_node_to_schema(n) for n in filtered_nodes],
        edges=[_edge_to_schema(e) for e in filtered_edges],
    )


async def fetch_graph_node_detail(
    session: AsyncSession,
    knowledge_id: uuid.UUID,
    node_id: uuid.UUID,
    max_chunks: int = 12,
) -> GraphNodeDetailResponse:
    """Mengambil detail 1 node graf beserta tetangga 1-hop dan cuplikan chunk asli dari PostgreSQL."""
    node = await session.get(KGNode, node_id)
    if node is None or node.knowledge_id != knowledge_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Node graph tidak ditemukan.")

    edges_stmt = (
        select(KGEdge)
        .where(
            KGEdge.version_id == node.version_id,
            or_(KGEdge.source_node_id == node.id, KGEdge.target_node_id == node.id),
        )
        .order_by(KGEdge.is_cross_document.desc(), KGEdge.weight.desc())
    )
    incident_edges = list((await session.execute(edges_stmt)).scalars().all())

    neighbor_ids = {
        e.target_node_id if e.source_node_id == node.id else e.source_node_id
        for e in incident_edges
    }
    neighbor_map: dict[uuid.UUID, KGNode] = {}
    if neighbor_ids:
        n_stmt = select(KGNode).where(KGNode.id.in_(list(neighbor_ids)))
        neighbor_map = {n.id: n for n in (await session.execute(n_stmt)).scalars().all()}

    neighbors: list[GraphNeighborOut] = []
    for edge in incident_edges:
        other_id = edge.target_node_id if edge.source_node_id == node.id else edge.source_node_id
        other = neighbor_map.get(other_id)
        if other is None:
            continue
        neighbors.append(
            GraphNeighborOut(
                node_id=other.id,
                label=other.label,
                node_type=other.node_type,
                edge_id=edge.id,
                edge_type=edge.edge_type,
                edge_label=edge.label,
                weight=round(float(edge.weight), 4),
                is_cross_document=edge.is_cross_document,
            )
        )

    chunk_ids = [int(cid) for cid in (node.source_chunk_ids or [])][:max_chunks]
    chunks_out: list[GraphChunkSnippetOut] = []
    if chunk_ids:
        c_stmt = (
            select(DocumentChunk, Document.filename)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(DocumentChunk.id.in_(chunk_ids))
            .order_by(Document.filename.asc(), DocumentChunk.page_number.asc(), DocumentChunk.chunk_index.asc())
        )
        for chunk_row, fname in (await session.execute(c_stmt)).all():
            meta = chunk_row.metadata_json or {}
            chunks_out.append(
                GraphChunkSnippetOut(
                    chunk_id=chunk_row.id,
                    document_id=chunk_row.document_id,
                    filename=fname,
                    page_number=chunk_row.page_number,
                    chunk_index=chunk_row.chunk_index,
                    section_title=meta.get("section_title"),
                    content=chunk_row.content,
                )
            )

    return GraphNodeDetailResponse(
        node=_node_to_schema(node),
        neighbors=neighbors,
        chunks=chunks_out,
    )


async def expand_candidates_via_graph(
    session: AsyncSession,
    query_text: str,
    query_vector: list[float] | None,
    initial_candidates: list[SimilarChunkRow],
    knowledge_ids: list[uuid.UUID] | None = None,
    score_threshold: float = 0.35,
    max_expanded_chunks: int | None = None,
) -> GraphExpansionResult:
    """Zero-LLM Cross-Document Graph Expansion (< 30ms di PostgreSQL):
    1) Mencocokkan query ke node konsep/referensi/bagian di kg_nodes (vektor BGE-M3 + leksikal).
    2) Melakukan 1-hop traversal lintas dokumen dari chunk hasil awal melalui jembatan graf.
    """
    max_expand = max_expanded_chunks or settings.KG_QUERY_MAX_EXPANDED_CHUNKS
    existing_chunk_ids = {c.chunk_id for c in initial_candidates}
    seed_hits = initial_candidates[:4]
    seed_chunk_ids = {c.chunk_id for c in seed_hits}
    seed_doc_ids = {str(c.document_id) for c in seed_hits}
    seed_doc_names = {c.chunk_id: c.filename for c in seed_hits}

    # Muat active version IDs yang masuk cakupan pencarian
    k_filter_clause = ""
    params: dict = {}
    if knowledge_ids:
        k_filter_clause = "AND k.id = ANY(:knowledge_ids)"
        params["knowledge_ids"] = knowledge_ids

    # Query seluruh konsep, referensi & semantic_bridge pada versi aktif (ringan, puluhan node per knowledge)
    nodes_sql = text(
        f"""
        SELECT
            gn.id,
            gn.knowledge_id,
            gn.version_id,
            gn.label,
            gn.node_type,
            gn.doc_frequency,
            gn.source_doc_ids,
            gn.source_chunk_ids,
            gn.properties_json,
            {
                "1.0 - (gn.embedding <=> CAST(:query_vec AS vector))"
                if query_vector is not None
                else "0.0"
            } AS node_sim
        FROM kg_nodes gn
        JOIN knowledges k ON k.active_version_id = gn.version_id
        WHERE k.status = 'done'
          {k_filter_clause}
        """
    )
    if query_vector is not None:
        params["query_vec"] = "[" + ",".join(f"{v:.8f}" for v in query_vector) + "]"

    node_rows = (await session.execute(nodes_sql, params)).mappings().all()
    if not node_rows:
        return GraphExpansionResult(
            expanded_rows=[],
            chunk_entities_map={},
            matched_node_labels=[],
            existing_graph_links={},
        )

    # Peta cepat chunk_id -> document_id dari node bertipe 'document' agar prioritas lintas dokumen akurat
    chunk_to_doc: dict[int, str] = {}
    for row in node_rows:
        if row["node_type"] == "document":
            s_docs = row["source_doc_ids"] or []
            if s_docs:
                d_str = str(s_docs[0])
                for cid in row["source_chunk_ids"] or []:
                    chunk_to_doc[int(cid)] = d_str

    primary_doc_id: str | None = (
        str(initial_candidates[0].document_id) if initial_candidates else None
    )

    # Bangun peta chunk_id -> entitas terkait (untuk badge & enrichment di UI)
    chunk_entities_map: dict[int, list[str]] = defaultdict(list)
    active_version_ids: set[uuid.UUID] = set()
    node_by_id: dict[uuid.UUID, dict] = {}
    query_lower = query_text.lower()
    query_tokens = {
        t.lower() for t in re.findall(r"[0-9a-zA-Z_-]{3,}", query_text)
    }

    # Kandidat chunk baru: chunk_id -> (is_cross_doc, graph_score, reason)
    discovered_chunks: dict[int, tuple[bool, float, str]] = {}
    # Tautan graf untuk chunk lintas dokumen yang sudah ada di kandidat awal
    existing_graph_links: dict[int, tuple[float, str]] = {}
    matched_nodes: list[tuple[float, str]] = []

    def _record_link(cid: int, score: float, reason: str) -> None:
        is_cross = primary_doc_id is not None and chunk_to_doc.get(cid) != primary_doc_id
        if cid in existing_chunk_ids:
            if is_cross:
                prev_ex = existing_graph_links.get(cid)
                if prev_ex is None or score > prev_ex[0]:
                    existing_graph_links[cid] = (score, reason)
            return
        prev = discovered_chunks.get(cid)
        if prev is None or (is_cross, score) > (prev[0], prev[1]):
            discovered_chunks[cid] = (is_cross, score, reason)

    node_sim_gate = max(0.52, min(0.72, score_threshold + 0.15))

    for row in node_rows:
        nid = row["id"]
        node_by_id[nid] = dict(row)
        active_version_ids.add(row["version_id"])
        ntype = row["node_type"]
        label = str(row["label"])
        cids = [int(cid) for cid in (row["source_chunk_ids"] or [])]
        props = row["properties_json"] or {}
        aliases = [str(a) for a in (props.get("aliases") or [])]

        if ntype in ("concept", "reference"):
            for cid in cids:
                if len(chunk_entities_map[cid]) < 6 and label not in chunk_entities_map[cid]:
                    chunk_entities_map[cid].append(label)

        # Signal 1: Direct Query -> Graph Node Match (vektor BGE-M3 atau kecocokan label/alias)
        if ntype in ("concept", "reference"):
            sim = float(row["node_sim"] or 0.0)
            label_low = label.lower()
            lexical_hit = (
                (len(label_low) >= 4 and label_low in query_lower)
                or any(len(a) >= 4 and a.lower() in query_lower for a in aliases)
                or (ntype == "reference" and label_low in query_tokens)
            )
            if lexical_hit or sim >= node_sim_gate:
                match_score = max(sim, 0.88 if lexical_hit else sim)
                matched_nodes.append((match_score, label))
                for cid in cids:
                    reason = (
                        f"Terhubung via {'kode' if ntype == 'reference' else 'konsep'} "
                        f"'{label}' di Knowledge Graph"
                    )
                    _record_link(cid, match_score, reason)

        # Signal 2A: Shared Cross-Document Concept/Reference Hub dari seed chunks!
        if ntype in ("concept", "reference") and int(row["doc_frequency"] or 0) >= 2:
            hit_seeds = [cid for cid in cids if cid in seed_chunk_ids]
            if hit_seeds:
                seed_fname = seed_doc_names.get(hit_seeds[0], "dokumen terkait")
                hub_score = max(float(row["node_sim"] or 0.0), 0.74)
                for cid in cids:
                    reason = (
                        f"Terhubung lintas dokumen melalui '{label}' "
                        f"dengan {seed_fname}"
                    )
                    _record_link(cid, hub_score, reason)

    # Signal 2B: 1-Hop Cross-Document Semantic Bridge Edges (BAAI/bge-m3!)
    if seed_chunk_ids and active_version_ids:
        edges_sql = text(
            """
            SELECT
                ge.source_node_id,
                ge.target_node_id,
                ge.edge_type,
                ge.weight,
                ge.label,
                ge.source_chunk_ids,
                ge.properties_json
            FROM kg_edges ge
            WHERE ge.version_id = ANY(:version_ids)
              AND ge.is_cross_document = TRUE
              AND ge.edge_type IN ('semantic_bridge', 'mentions')
            ORDER BY ge.weight DESC
            LIMIT 200
            """
        )
        edge_rows = (
            await session.execute(edges_sql, {"version_ids": list(active_version_ids)})
        ).mappings().all()

        for erow in edge_rows:
            e_cids = [int(cid) for cid in (erow["source_chunk_ids"] or [])]
            props = erow["properties_json"] or {}
            weight = float(erow["weight"] or 0.0)
            etype = str(erow["edge_type"])

            if etype == "semantic_bridge":
                chunk_pairs = props.get("chunk_pairs") or []
                for pair in chunk_pairs:
                    src_cid = int(pair.get("src_chunk_id", -1))
                    tgt_cid = int(pair.get("tgt_chunk_id", -1))
                    p_score = float(pair.get("score", weight))
                    if src_cid in seed_chunk_ids and tgt_cid > 0:
                        reason = (
                            f"Jembatan semantik BGE-M3 ({round(p_score * 100)}%) "
                            f"dari {pair.get('src_file', 'dokumen terkait')}"
                        )
                        _record_link(tgt_cid, p_score + 0.08, reason)
                    elif tgt_cid in seed_chunk_ids and src_cid > 0:
                        reason = (
                            f"Jembatan semantik BGE-M3 ({round(p_score * 100)}%) "
                            f"dari {pair.get('tgt_file', 'dokumen terkait')}"
                        )
                        _record_link(src_cid, p_score + 0.08, reason)

                # Fallback bila section semantic_bridge tidak menyimpan chunk_pairs granular
                if not chunk_pairs and any(cid in seed_chunk_ids for cid in e_cids):
                    src_n = node_by_id.get(erow["source_node_id"])
                    tgt_n = node_by_id.get(erow["target_node_id"])
                    for cid in e_cids:
                        if cid not in seed_chunk_ids:
                            label_pair = (
                                f"{src_n['label']} ↔ {tgt_n['label']}"
                                if src_n and tgt_n
                                else "jembatan semantik"
                            )
                            reason = f"Jembatan semantik BGE-M3 ({round(weight * 100)}%): {label_pair}"
                            _record_link(cid, weight + 0.06, reason)

            elif etype == "mentions":
                # Direct Document -> Document explicit mention edge
                src_n = node_by_id.get(erow["source_node_id"])
                tgt_n = node_by_id.get(erow["target_node_id"])
                if (
                    src_n
                    and tgt_n
                    and src_n["node_type"] == "document"
                    and tgt_n["node_type"] == "document"
                ):
                    src_doc = (src_n["source_doc_ids"] or [None])[0]
                    tgt_doc = (tgt_n["source_doc_ids"] or [None])[0]
                    if src_doc in seed_doc_ids and tgt_doc not in seed_doc_ids:
                        for cid in (tgt_n["source_chunk_ids"] or [])[:3]:
                            _record_link(int(cid), weight, f"Dirujuk langsung oleh {src_n['label']}")

    matched_nodes.sort(key=lambda item: item[0], reverse=True)
    matched_node_labels = list(dict.fromkeys(label for _, label in matched_nodes))[:8]

    if not discovered_chunks:
        return GraphExpansionResult(
            expanded_rows=[],
            chunk_entities_map=dict(chunk_entities_map),
            matched_node_labels=matched_node_labels,
            existing_graph_links=existing_graph_links,
        )

    # Prioritaskan chunk dari dokumen BERBEDA (lintas dokumen!) lalu biarkan SQL memilih yang paling relevan secara vektor
    cross_doc_pool = [
        (cid, score, reason)
        for cid, (is_cross, score, reason) in discovered_chunks.items()
        if is_cross
    ]
    same_doc_pool = [
        (cid, score, reason)
        for cid, (is_cross, score, reason) in discovered_chunks.items()
        if not is_cross
    ]
    cross_doc_pool.sort(key=lambda item: item[1], reverse=True)
    same_doc_pool.sort(key=lambda item: item[1], reverse=True)

    # Jika ada kandidat lintas dokumen, fokuskan ekspansi graf ke dokumen lain (bukan duplikasi dokumen dominan!)
    selected_pool = (
        cross_doc_pool[: max(max_expand * 4, 32)]
        if cross_doc_pool
        else same_doc_pool[: max(max_expand * 2, 16)]
    )
    fetch_ids = [cid for cid, _, _ in selected_pool]
    reason_map = {cid: (score, reason) for cid, score, reason in selected_pool}

    order_sql = (
        "ORDER BY (dc.embedding <=> CAST(:query_vec AS vector)) ASC"
        if query_vector is not None
        else "ORDER BY dc.id ASC"
    )
    fetch_sql = text(
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
            dc.metadata_json ->> 'search_text' AS search_text,
            COALESCE(
                dc.metadata_json ->> 'page_image_object',
                dc.metadata_json ->> 'page_image_url'
            ) AS page_image_url,
            {
                "1.0 - (dc.embedding <=> CAST(:query_vec AS vector))"
                if query_vector is not None
                else "0.0"
            } AS similarity_score
        FROM document_chunks dc
        JOIN documents d ON d.id = dc.document_id
        JOIN knowledge_version_documents kvd ON kvd.document_id = d.id
        JOIN knowledge_versions kv ON kv.id = kvd.version_id
        JOIN knowledges k ON k.active_version_id = kv.id
        WHERE dc.id = ANY(:chunk_ids)
          AND kv.status = 'done'
          AND d.status = 'embedded'
          {k_filter_clause}
        {order_sql}
        LIMIT :max_expand
        """
    )
    fetch_params: dict = {"chunk_ids": fetch_ids, "max_expand": max_expand}
    if knowledge_ids:
        fetch_params["knowledge_ids"] = knowledge_ids
    if query_vector is not None:
        fetch_params["query_vec"] = params["query_vec"]

    fetched_rows = (await session.execute(fetch_sql, fetch_params)).mappings().all()

    expanded_rows: list[SimilarChunkRow] = []
    for row in fetched_rows:
        cid = int(row["chunk_id"])
        g_score, g_reason = reason_map.get(cid, (0.7, "Terhubung melalui Knowledge Graph"))
        sim_score = max(0.0, round(float(row["similarity_score"] or 0.0), 6))
        expanded_rows.append(
            SimilarChunkRow(
                chunk_id=cid,
                knowledge_id=row["knowledge_id"],
                knowledge_name=row["knowledge_name"],
                version=row["version"],
                document_id=row["document_id"],
                filename=row["filename"],
                page_number=row["page_number"],
                chunk_index=row["chunk_index"],
                content=row["content"],
                similarity_score=sim_score,
                page_image_url=row["page_image_url"],
                section_title=row["section_title"],
                contextual_header=row["contextual_header"],
                search_text=row["search_text"],
                keyword_score=0.0,
                rrf_score=round(g_score * 0.015, 6),
                via_graph=True,
                graph_reason=g_reason,
                graph_score=round(min(1.0, g_score), 4),
                related_entities=tuple(chunk_entities_map.get(cid, [])),
            )
        )

    return GraphExpansionResult(
        expanded_rows=expanded_rows,
        chunk_entities_map=dict(chunk_entities_map),
        matched_node_labels=matched_node_labels,
        existing_graph_links=existing_graph_links,
    )
