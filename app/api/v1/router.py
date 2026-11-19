from fastapi import APIRouter

from app.api.v1.graph import router as graph_router
from app.api.v1.knowledge import router as knowledge_router
from app.api.v1.query import router as query_router

api_router = APIRouter()
api_router.include_router(knowledge_router)
api_router.include_router(graph_router)
api_router.include_router(query_router)
