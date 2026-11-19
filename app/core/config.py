from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Konfigurasi aplikasi backend RAG dari environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = "MiiRAG Backend"
    APP_ENV: str = "development"
    API_V1_PREFIX: str = "/api/v1"
    CORS_ORIGINS: list[str] = ["*"]

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://miirag:miirag@localhost:5432/miirag"

    # Embedding Model (BAAI/bge-m3 local via PyTorch CUDA)
    EMBEDDING_PROVIDER: str = "local"  # "local" atau "vertex"
    EMBEDDING_MODEL: str = "BAAI/bge-m3"
    EMBEDDING_DIMENSIONS: int = 1024
    EMBEDDING_DEVICE: str = "cuda"
    EMBEDDING_BATCH_SIZE: int = 16

    # Google Vertex AI (Opsional jika ingin beralih ke cloud)
    GCP_PROJECT_ID: str = ""
    GCP_LOCATION: str = "us-central1"
    EMBEDDING_MAX_RETRIES: int = 3

    # MinIO Object Storage (Page Snapshots)
    MINIO_ENABLED: bool = True
    MINIO_FOLDER_PREFIX: str = "documents"
    MINIO_ENDPOINT: str = "minioapi.clientsolve.com"
    MINIO_BUCKET: str = "evorag"
    MINIO_ACCESS_KEY: str = ""
    MINIO_SECRET_KEY: str = ""
    MINIO_REGION: str = "us-east-1"
    MINIO_SECURE: bool = True
    MINIO_PUBLIC_URL: str = "https://minioapi.clientsolve.com"
    MINIO_PRESIGNED_EXPIRY_SECONDS: int = 1800

    # Storage & PDF Processing
    STORAGE_DIR: Path = Path("./storage/uploads")
    MAX_UPLOAD_SIZE_MB: int = 50
    CHUNK_SIZE: int = 1000
    CHUNK_OVERLAP: int = 150
    PAGE_SNAPSHOT_DPI: int = 150

    # Vector Search & Hybrid Retrieval
    HNSW_EF_SEARCH: int = 64
    DEFAULT_TOP_K: int = 5
    DEFAULT_SCORE_THRESHOLD: float = 0.35
    DEFAULT_SEARCH_MODE: str = "hybrid"
    HYBRID_RRF_K: int = 60
    HYBRID_DENSE_WEIGHT: float = 0.65
    HYBRID_SPARSE_WEIGHT: float = 0.35

    # Cross-Encoder Reranking
    RERANK_ENABLED: bool = True
    RERANK_MODEL: str = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
    RERANK_DEVICE: str = "cuda"
    RERANK_CANDIDATE_LIMIT: int = 20
    PRELOAD_MODELS: bool = True

    # Query Enhancement (HyDE & Query Expansion)
    HYDE_LLM_PROVIDER: str = "none"
    HYDE_LLM_MODEL: str = "gemini-2.5-flash"
    HYDE_API_KEY: str = ""
    HYDE_BASE_URL: str = ""
    HYDE_TIMEOUT_SECONDS: float = 5.0

    # Zero-LLM Knowledge Graph (Pure BAAI/bge-m3 + PostgreSQL pgvector)
    KG_ENABLED: bool = True
    KG_SEMANTIC_EDGE_THRESHOLD: float = 0.68
    KG_ALIAS_MERGE_THRESHOLD: float = 0.86
    KG_MAX_CONCEPT_NODES: int = 45
    KG_MAX_SECTIONS_PER_DOC: int = 12
    KG_MAX_SEMANTIC_BRIDGES_PER_NODE: int = 3
    KG_MAX_COOCCUR_EDGES_PER_NODE: int = 4
    KG_QUERY_MAX_EXPANDED_CHUNKS: int = 8

    # Server Backend & MCP (Model Context Protocol)
    BACKEND_HOST: str = "0.0.0.0"
    BACKEND_PORT: int = 8000
    MCP_ENABLED: bool = True
    MCP_SERVER_NAME: str = "miirag-mcp"
    MCP_TRANSPORT: str = "streamable-http"  # "streamable-http" atau "sse"
    MCP_HOST: str = "0.0.0.0"
    MCP_PORT: int = 8001
    MCP_PATH: str = "/mcp"
    MCP_SSE_PATH: str = "/sse"
    MCP_MESSAGE_PATH: str = "/messages/"

    @property
    def max_upload_size_bytes(self) -> int:
        return self.MAX_UPLOAD_SIZE_MB * 1024 * 1024

    @property
    def normalized_minio_bucket(self) -> str:
        return self.MINIO_BUCKET.strip().lower()


settings = Settings()
