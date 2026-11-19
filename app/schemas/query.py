import uuid
from typing import Literal

from pydantic import BaseModel, Field

from app.core.config import settings


class QueryRequest(BaseModel):
    query: str = Field(
        ..., min_length=1, max_length=4000, description="Teks pertanyaan atau kata kunci pencarian"
    )
    knowledge_ids: list[uuid.UUID] | None = Field(
        default=None,
        description="Filter opsional ke daftar knowledge_id tertentu; jika kosong akan mencari di seluruh knowledge berstatus done.",
    )
    top_k: int = Field(
        default=settings.DEFAULT_TOP_K,
        ge=1,
        le=50,
        description="Jumlah maksimum potongan dokumen yang dikembalikan.",
    )
    score_threshold: float = Field(
        default=settings.DEFAULT_SCORE_THRESHOLD,
        ge=0.0,
        le=1.0,
        description="Batas minimum cosine similarity score (0.0 - 1.0).",
    )
    search_mode: Literal["hybrid", "dense", "keyword"] = Field(
        default="hybrid",
        description="Mode pencarian: hybrid (Vector + PostgreSQL FTS RRF), dense (Vector saja), atau keyword (FTS saja).",
    )
    use_rerank: bool = Field(
        default=settings.RERANK_ENABLED,
        description="Aktifkan Cross-Encoder Reranker multilingual untuk meningkatkan presisi urutan hasil.",
    )
    use_hyde: bool = Field(
        default=False,
        description="Aktifkan Hypothetical Document Embeddings (HyDE) untuk pertanyaan konseptual/abstrak.",
    )
    use_query_expansion: bool = Field(
        default=False,
        description="Aktifkan ekspansi sinonim dan singkatan otomatis untuk memperkaya recall.",
    )
    expand_context: bool = Field(
        default=False,
        description="Sertakan konteks chunk tetangga (sebelum/sesudah) pada field expanded_content.",
    )
    use_graph: bool = Field(
        default=False,
        description="Aktifkan Zero-LLM Knowledge Graph (BAAI/bge-m3) untuk menelusuri relasi lintas dokumen.",
    )


class QueryResultItem(BaseModel):
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
    page_image_url: str | None = Field(
        default=None,
        description="URL snapshot gambar halaman dokumen di MinIO (jika tersedia).",
    )
    section_title: str | None = Field(
        default=None,
        description="Hierarki judul bagian/heading Markdown tempat chunk ini berada.",
    )
    expanded_content: str | None = Field(
        default=None,
        description="Teks gabungan dengan chunk tetangga sebelum dan sesudahnya (jika expand_context=true).",
    )
    keyword_score: float | None = Field(
        default=None,
        description="Skor kecocokan kata kunci penuh (PostgreSQL Full-Text Search).",
    )
    rerank_score: float | None = Field(
        default=None,
        description="Skor relevansi probabilistik dari Cross-Encoder Reranker (0.0 - 1.0).",
    )
    via_graph: bool = Field(
        default=False,
        description="True jika potongan dokumen ini ditarik melalui jembatan relasi Knowledge Graph lintas dokumen.",
    )
    graph_reason: str | None = Field(
        default=None,
        description="Penjelasan jalur relasi Knowledge Graph yang menemukan potongan dokumen ini.",
    )
    related_entities: list[str] = Field(
        default_factory=list,
        description="Daftar entitas/konsep/kode pada Knowledge Graph yang terhubung dengan potongan dokumen ini.",
    )


class QueryResponse(BaseModel):
    query: str
    latency_ms: int
    total_results: int
    search_mode: str = "hybrid"
    reranked: bool = False
    graph_used: bool = False
    graph_nodes_matched: list[str] = Field(default_factory=list)
    enhancement_used: str = "none"
    hyde_document: str | None = None
    results: list[QueryResultItem]
