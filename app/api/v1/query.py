from fastapi import APIRouter

from app.schemas.query import QueryRequest, QueryResponse
from app.services.query_service import execute_similarity_query

router = APIRouter(prefix="/query", tags=["Query"])


@router.post("", response_model=QueryResponse)
async def query_knowledge_base(payload: QueryRequest) -> QueryResponse:
    """Mencari chunk dokumen relevan menggunakan Hybrid Search (Dense pgvector + Sparse FTS RRF), Cross-Encoder Reranking, serta HyDE/Context Expansion opsional."""
    return await execute_similarity_query(payload)
