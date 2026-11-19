import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.knowledge import KnowledgeStatus
from app.repositories.graph_repo import (
    fetch_graph_node_detail,
    fetch_knowledge_graph,
    resolve_target_version,
)
from app.schemas.graph import GraphNodeDetailResponse, KnowledgeGraphResponse
from app.services.graph_builder_service import build_knowledge_graph_for_version

router = APIRouter(prefix="/knowledges", tags=["Knowledge Graph"])

DBSession = Annotated[AsyncSession, Depends(get_db)]


@router.get("/{knowledge_id}/graph", response_model=KnowledgeGraphResponse)
async def get_knowledge_graph(
    knowledge_id: uuid.UUID,
    session: DBSession,
    version_id: Annotated[
        uuid.UUID | None,
        Query(description="ID versi spesifik; kosongkan untuk versi aktif terbaru."),
    ] = None,
    include_sections: Annotated[
        bool,
        Query(description="Sertakan node bagian/heading/sheet pada respons graf."),
    ] = True,
    node_types: Annotated[
        str | None,
        Query(description="Filter tipe node dipisah koma: document,section,concept,reference"),
    ] = None,
    min_weight: Annotated[
        float,
        Query(ge=0.0, le=1.0, description="Batas minimum bobot relasi edge."),
    ] = 0.0,
    max_nodes: Annotated[
        int,
        Query(ge=10, le=500, description="Jumlah maksimum node yang dikembalikan."),
    ] = 250,
) -> KnowledgeGraphResponse:
    """Mengambil Zero-LLM Knowledge Graph (nodes, edges, dan statistik relasi lintas dokumen)."""
    parsed_types = (
        [t.strip().lower() for t in node_types.split(",") if t.strip()]
        if node_types
        else None
    )
    return await fetch_knowledge_graph(
        session=session,
        knowledge_id=knowledge_id,
        version_id=version_id,
        include_sections=include_sections,
        node_types=parsed_types,
        min_weight=min_weight,
        max_nodes=max_nodes,
    )


@router.post("/{knowledge_id}/graph/rebuild", response_model=KnowledgeGraphResponse)
async def rebuild_knowledge_graph(
    knowledge_id: uuid.UUID,
    session: DBSession,
    version_id: Annotated[
        uuid.UUID | None,
        Query(description="ID versi spesifik untuk dibangun ulang; default versi aktif."),
    ] = None,
) -> KnowledgeGraphResponse:
    """Membangun atau memperbarui Zero-LLM Knowledge Graph berbasis BAAI/bge-m3 tanpa LLM."""
    knowledge, version = await resolve_target_version(session, knowledge_id, version_id)
    if knowledge.status == KnowledgeStatus.PROCESSING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Tunggu proses embedding dokumen selesai sebelum membangun Knowledge Graph.",
        )
    if version is None or version.status != KnowledgeStatus.DONE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Knowledge harus berstatus Done (sudah di-embed) untuk membangun Knowledge Graph.",
        )

    await build_knowledge_graph_for_version(
        knowledge_id=knowledge.id,
        version_id=version.id,
        session=session,
    )
    return await fetch_knowledge_graph(
        session=session,
        knowledge_id=knowledge.id,
        version_id=version.id,
    )


@router.get("/{knowledge_id}/graph/nodes/{node_id}", response_model=GraphNodeDetailResponse)
async def get_graph_node_detail(
    knowledge_id: uuid.UUID,
    node_id: uuid.UUID,
    session: DBSession,
    max_chunks: Annotated[int, Query(ge=1, le=30)] = 12,
) -> GraphNodeDetailResponse:
    """Mengambil detail node Knowledge Graph beserta tetangga 1-hop dan potongan teks dokumen aslinya."""
    return await fetch_graph_node_detail(
        session=session,
        knowledge_id=knowledge_id,
        node_id=node_id,
        max_chunks=max_chunks,
    )
