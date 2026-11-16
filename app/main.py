import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.database import check_db_health
from app.services.embedding_service import embedding_service
from app.services.rerank_service import rerank_service

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    if settings.PRELOAD_MODELS and settings.APP_ENV != "test":
        try:
            if hasattr(embedding_service, "preload"):
                await embedding_service.preload()
            if settings.RERANK_ENABLED:
                await rerank_service.preload()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Preload model saat startup dilewati: %s", exc)
    yield


app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
    description="Backend Python RAG untuk dokumen PDF menggunakan Vertex AI Gemini Embedding dan pgvector.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.get("/health", tags=["Health"])
async def health_check() -> dict[str, str]:
    """Mengecek kesiapan API, koneksi PostgreSQL, dan ekstensi pgvector."""
    ok = await check_db_health()
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Ekstensi pgvector belum aktif atau database tidak tersedia.",
        )
    return {"status": "ok", "pgvector": "ready"}


def custom_openapi() -> dict:
    """Modifikasi schema OpenAPI agar Swagger UI mengenali tombol upload file (format: binary)."""
    if app.openapi_schema:
        return app.openapi_schema

    from fastapi.openapi.utils import get_openapi

    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        openapi_version=app.openapi_version,
        description=app.description,
        routes=app.routes,
    )

    for schema_val in openapi_schema.get("components", {}).get("schemas", {}).values():
        for prop_val in schema_val.get("properties", {}).values():
            if "anyOf" in prop_val:
                for branch in prop_val["anyOf"]:
                    if branch.get("type") == "array" and branch.get("items", {}).get(
                        "contentMediaType"
                    ):
                        prop_val["type"] = "array"
                        prop_val["items"] = {"type": "string", "format": "binary"}
                        prop_val.pop("anyOf", None)
                        break
                    if branch.get("contentMediaType"):
                        prop_val["type"] = "string"
                        prop_val["format"] = "binary"
                        prop_val.pop("anyOf", None)
                        break
            elif prop_val.get("type") == "array":
                items = prop_val.get("items", {})
                if items.get("contentMediaType"):
                    items.pop("contentMediaType", None)
                    items["format"] = "binary"
            elif prop_val.get("contentMediaType"):
                prop_val.pop("contentMediaType", None)
                prop_val["format"] = "binary"

    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi
