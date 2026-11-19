import argparse
import asyncio
import logging
import os
import uuid
from typing import Annotated, Any, Literal

import httpx
import uvicorn
from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import Field
from sqlalchemy import select
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import settings
from app.core.database import AsyncSessionLocal, engine
from app.models.knowledge import (
    Document,
    Knowledge,
    KnowledgeStatus,
    KnowledgeVersion,
    KnowledgeVersionDocument,
)
from app.schemas.query import QueryRequest
from app.services.knowledge_service import list_knowledges as service_list_knowledges
from app.services.query_service import execute_similarity_query

# Matikan SQL echo ke stdout agar tidak merusak protokol JSON-RPC pada mode transport stdio
engine.echo = False
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

GUIDE_RESOURCE_URI = "miirag://guides/query-methods"

TOOL_DESCRIPTION = (
    "Melakukan pencarian potongan dokumen (RAG retrieval) pada MiiRAG Knowledge Base. "
    "Gunakan tool `list_knowledges` untuk melihat daftar Knowledge ID (`UUID`) yang tersedia sebelum memfilter `knowledge_ids`. "
    "PENTING: Untuk panduan dan penjelasan lengkap mengenai metode query (`search_mode`: hybrid, dense, keyword), "
    "fungsi setiap fitur peningkatan akurasi (`use_rerank`, `use_query_expansion`, `use_graph`, `use_hyde`, `expand_context`), "
    "rekomendasi kombinasi parameter sesuai jenis pertanyaan, serta cara membaca skor hasil, "
    f"BACA TERLEBIH DAHULU resource MCP `{GUIDE_RESOURCE_URI}` sebelum memanggil tool ini."
)

LIST_TOOL_DESCRIPTION = (
    "Mengambil daftar Knowledge Base yang tersedia di MiiRAG beserta ID (`UUID`), nama, deskripsi, status, versi aktif, "
    "dan daftar dokumen di dalamnya. Gunakan tool ini terlebih dahulu untuk mengetahui `knowledge_ids` yang dapat dikirim "
    f"ke tool `query_knowledge`. Untuk panduan lengkap cara memilih metode pencarian pada `query_knowledge`, baca resource `{GUIDE_RESOURCE_URI}`."
)

SERVER_INSTRUCTIONS = (
    "Server MCP resmi untuk MiiRAG Knowledge Base. "
    "1) Gunakan tool `list_knowledges` untuk melihat daftar Knowledge Base beserta UUID dan dokumen di dalamnya. "
    f"2) Selalu baca resource `{GUIDE_RESOURCE_URI}` terlebih dahulu untuk memahami panduan lengkap metode query "
    "serta rekomendasi parameter sebelum menjalankan tool `query_knowledge`."
)

mcp = MCPServer(
    name=settings.MCP_SERVER_NAME,
    title="MiiRAG Knowledge Retrieval MCP",
    version="0.1.0",
    description=(
        "MCP Server untuk pencarian dokumen (RAG Retrieval) pada MiiRAG menggunakan Hybrid Search "
        "(BAAI/bge-m3 + PostgreSQL FTS RRF), Cross-Encoder Reranker, dan Zero-LLM Knowledge Graph."
    ),
    instructions=SERVER_INSTRUCTIONS,
)

# Penanda apakah MCP berjalan di dalam proses yang sama dengan FastAPI Backend
_IN_BACKEND_PROCESS = False


class _EmbeddedUvicornServer(uvicorn.Server):
    """Uvicorn server tersemat untuk MCP yang tidak mengambil alih signal handler milik proses utama."""

    def install_signal_handlers(self) -> None:
        return


_bg_mcp_server: _EmbeddedUvicornServer | None = None
_bg_mcp_task: asyncio.Task[None] | None = None


@mcp.custom_route("/", methods=["GET"], include_in_schema=False)
@mcp.custom_route("/health", methods=["GET"], include_in_schema=False)
async def mcp_health_check(_: Request) -> Response:
    """Endpoint status kesehatan & informasi endpoint pada server MCP HTTP/SSE."""
    display_host = "localhost" if settings.MCP_HOST in ("0.0.0.0", "::") else settings.MCP_HOST
    base_url = f"http://{display_host}:{settings.MCP_PORT}"
    return JSONResponse(
        {
            "status": "ok",
            "name": settings.MCP_SERVER_NAME,
            "version": "0.1.0",
            "transport": settings.MCP_TRANSPORT,
            "endpoints": {
                "streamable_http": f"{base_url}{settings.MCP_PATH}",
                "sse": f"{base_url}{settings.MCP_SSE_PATH}",
                "messages": f"{base_url}{settings.MCP_MESSAGE_PATH}",
            },
            "tools": ["list_knowledges", "query_knowledge"],
            "resources": [GUIDE_RESOURCE_URI],
        }
    )


async def _fetch_active_knowledges_markdown() -> str:
    """Mengambil daftar knowledge berstatus DONE dari database untuk disertakan di dalam panduan resource."""
    try:
        async with AsyncSessionLocal() as session:
            stmt = (
                select(Knowledge)
                .where(Knowledge.status == KnowledgeStatus.DONE)
                .order_by(Knowledge.updated_at.desc())
            )
            rows = (await session.execute(stmt)).scalars().all()
            if not rows:
                return (
                    "> Saat ini belum ada Knowledge berstatus `done` di database. "
                    "Silakan buat dan proses dokumen terlebih dahulu melalui WebUI atau REST API."
                )
            lines = [
                "| Knowledge ID (`UUID`) | Nama Knowledge | Versi Aktif | Deskripsi |",
                "| :--- | :--- | :---: | :--- |",
            ]
            for k in rows:
                desc = (k.description or "-").replace("\n", " ").strip()
                lines.append(f"| `{k.id}` | **{k.name}** | `v{k.current_version}` | {desc} |")
            return "\n".join(lines)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Gagal memuat daftar knowledge aktif untuk resource guide: %s", exc)
        return "> Daftar knowledge aktif dapat dicari otomatis dengan mengosongkan parameter `knowledge_ids` (`null`)."


def _build_query_guide_markdown(active_knowledges_section: str) -> str:
    """Menyusun dokumentasi Markdown lengkap mengenai metode dan parameter query MiiRAG."""
    return f"""# Panduan Lengkap Metode & Parameter Query MiiRAG

Dokumen resource ini berisi panduan lengkap bagi AI Agent / LLM maupun pengguna dalam memilih **metode pencarian (`search_mode`)**, mengatur **parameter peningkatan akurasi**, memahami **filter & threshold**, serta menginterpretasikan **skor hasil** pada tool `query_knowledge`.

---

## 1. Daftar Knowledge Base Aktif Saat Ini

Berikut adalah daftar Knowledge Base berstatus `done` yang siap dicari:

{active_knowledges_section}

* **Tips Parameter `knowledge_ids`:**
  * Kosongkan (`null` / tidak diisi) jika ingin mencari di **seluruh knowledge aktif** sekaligus.
  * Isi dengan daftar UUID (misal `["<uuid-knowledge>"]`) jika pengguna hanya ingin mencari pada topik/divisi tertentu.

---

## 2. Memahami 3 Pilihan Mode Pencarian (`search_mode`)

Parameter `search_mode` menentukan algoritma dasar penarikan kandidat dokumen dari PostgreSQL:

### A. `"hybrid"` — **Vector + Keyword dengan Reciprocal Rank Fusion (Default & Direkomendasikan)**
* **Cara Kerja:** Menggabungkan pencarian kemiripan makna vektor (**`BAAI/bge-m3` 1024-dim cosine similarity** via `pgvector` HNSW) dan pencarian kata kunci eksak (**PostgreSQL Full-Text Search / FTS** `ts_rank_cd`), lalu menyatukan peringkatnya menggunakan rumus **Reciprocal Rank Fusion (RRF)** (`k=60`, bobot dense `0.65`, bobot keyword `0.35`).
* **Kelebihan:** Paling seimbang dan tahan banting. Mampu menangkap maksud kalimat yang menggunakan sinonim sekaligus tetap presisi menemukan kode dokumen, nomor pasal, atau istilah teknis.
* **Kapan Digunakan:** Gunakan sebagai pilihan utama (**default**) untuk 90% skenario pertanyaan.

### B. `"dense"` — **Semantic Vector Search Saja (`pgvector`)**
* **Cara Kerja:** Hanya mencocokkan kedekatan makna kalimat pertanyaan terhadap vektor dokumen menggunakan model lokal `BAAI/bge-m3`.
* **Kelebihan:** Sangat baik untuk pertanyaan konseptual, parafrase, atau lintas bahasa (Indonesia–Inggris) ketika kata kunci yang dipakai berbeda jauh dari teks asli dokumen.
* **Kelemahan:** Kurang peka terhadap nomor kode unik (seperti `SOP-CHIL-09`, nomor surat, atau SKU barang).
* **Kapan Digunakan:** Saat pertanyaan bersifat sangat konseptual/abstrak dan pencocokan kata persis justru menimbulkan distraksi.

### C. `"keyword"` — **Full-Text Search / Pencocokan Kata Persis Saja (FTS)**
* **Cara Kerja:** Mencari kecocokan leksikal kata/frasa secara persis menggunakan indeks GIN `tsvector` PostgreSQL (seperti `Ctrl+F` tingkat lanjut).
* **Kelebihan:** Instan (<10 ms) dan 100% akurat untuk kode unik, nomor pasal, nama pejabat, atau nomor seri.
* **Kelemahan:** Tidak memahami sinonim atau kemiripan makna jika kata yang diketik tidak tertulis persis di dokumen.
* **Kapan Digunakan:** Saat mencari kode SOP spesifik, nomor dokumen, nama entitas persis, atau SKU.

---

## 3. Memahami 5 Teknik Peningkatan Akurasi (Boolean Flags)

Selain `search_mode`, Anda dapat mengaktifkan kombinasi fitur berikut pada tool `query_knowledge`:

### 1. `use_rerank` *(bool, Default: `true` — Sangat Direkomendasikan)*
* **Mekanisme:** Mengambil 20 kandidat teratas dari tahap retrieval awal, lalu membaca ulang pasangan `(query, chunk)` secara mendalam menggunakan model **Multilingual Cross-Encoder Reranker** (`BAAI/bge-reranker-v2-m3`).
* **Dampak:** Menyaring *false positive* (potongan teks yang hanya kebetulan mirip kata kuncinya) dan menaikkan potongan dokumen yang paling menjawab pertanyaan ke urutan `#1`. Menghasilkan skor probabilistik pada field `rerank_score` (`0.0` – `1.0`).

### 2. `use_query_expansion` *(bool, Default: `false`, Direkomendasikan `true`)*
* **Mekanisme:** Memperluas query secara deterministik menggunakan kamus sinonim & kepanjangan singkatan Bahasa Indonesia tanpa latensi tambahan (`0 ms`).
  * Contoh: `SOP` -> `standar operasional prosedur`, `HR`/`SDM` -> `karyawan, kepegawaian, personalia`, `cek` -> `periksa, pemeriksaan, checklist`.
* **Dampak:** Meningkatkan *recall* ketika pertanyaan memakai singkatan atau istilah sehari-hari. Teks hasil ekspansi dapat dilihat pada field response `expanded_query`.

### 3. `use_graph` *(bool, Default: `false`, Direkomendasikan `true` untuk Pertanyaan Lintas Dokumen)*
* **Mekanisme:** Mengaktifkan **Zero-LLM Knowledge Graph berbasis `BAAI/bge-m3`**. Sistem menelusuri graf relasi antar dokumen di dalam Knowledge Base melalui:
  1. **Kode & Referensi Bersama (`code`):** Kode `SOP-xxx`, `POJK`, `ISO`, atau `Pasal` yang disebut di beberapa dokumen.
  2. **Konsep Penghubung (`concept`):** Entitas penting yang muncul lintas dokumen dan telah digabungkan variasinya melalui *Semantic Alias Merging* (>= 0.86).
  3. **Jembatan Makna Lintas Dokumen (`semantic_bridge`):** Kemiripan vektor `BAAI/bge-m3` antar bagian dokumen yang berbeda (>= 0.68).
* **Dampak:**
  * Menemukan jawaban *multi-hop* yang tersebar di beberapa file berbeda (misalnya aturan insiden di dokumen *Security Awareness* beserta konsekuensi sanksi/kepatuhannya di dokumen *HR Regulation*).
  * Menerapkan **Graph Diversification** sehingga satu dokumen tebal tidak memonopoli seluruh slot `top_k` ketika ada dokumen lain yang terhubung melalui Knowledge Graph.
  * Potongan dokumen yang ditarik lewat graf akan memiliki penanda `via_graph: true`, penjelasan jalur relasi pada `graph_reason`, serta daftar node pada `related_entities`.

### 4. `use_hyde` *(bool, Default: `false`)*
* **Mekanisme:** **Hypothetical Document Embeddings (HyDE)** mengubah kalimat tanya singkat menjadi kalimat deklaratif bergaya dokumen SOP/kebijakan terlebih dahulu sebelum diubah menjadi vektor pencarian.
* **Dampak:** Membantu menjembatani perbedaan gaya bahasa antara kalimat tanya pengguna yang singkat dengan bahasa formal dokumen. Jangan diaktifkan jika sedang mencari kode unik spesifik.

### 5. `expand_context` *(bool, Default: `false`)*
* **Mekanisme:** **Context Window Expansion** otomatis menyertakan potongan teks tepat sebelum (`chunk_index - 1`) dan sesudah (`chunk_index + 1`) dari halaman dokumen yang sama ke dalam field `expanded_content`.
* **Dampak:** Sangat berguna apabila potongan dokumen merupakan bagian dari langkah prosedur berurutan atau tabel yang panjang agar konteksnya terbaca utuh tanpa terpotong.

---

## 4. Parameter Kuantitas & Ambang Batas Skor

* **`top_k` *(int, 1–50, Default: `5`)*:**
  Jumlah maksimum potongan dokumen yang dikembalikan. Gunakan `5` untuk pertanyaan fokus, atau naikkan ke `8`–`10` untuk pertanyaan analisis menyeluruh lintas dokumen.
* **`score_threshold` *(float, 0.0–1.0, Default: `0.35`)*:**
  Batas minimum skor kemiripan (*cosine similarity*):
  * `0.35` (Default): Seimbang untuk mayoritas pertanyaan.
  * `0.20` – `0.25`: Gunakan jika pencarian sebelumnya mengembalikan terlalu sedikit hasil atau pertanyaan menggunakan istilah yang sangat berbeda.
  * `0.50` – `0.65`: Gunakan jika hanya menginginkan potongan dengan kemiripan sangat ketat.

---

## 5. Rekomendasi Paket Kombinasi Parameter (Best Practice Presets)

Gunakan tabel berikut untuk menentukan parameter terbaik saat memanggil tool `query_knowledge`:

| Skenario Pertanyaan | `search_mode` | `use_rerank` | `use_query_expansion` | `use_graph` | `use_hyde` | `expand_context` | `top_k` |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **1. Pertanyaan Umum & Lintas Dokumen (Rekomendasi Utama)** | `"hybrid"` | `true` | `true` | `true` | `false` | `false` | `5` – `10` |
| **2. Cari Kode SOP / Nomor Pasal / Nama Persis** | `"keyword"` | `false` | `false` | `false` | `false` | `false` | `5` |
| **3. Pertanyaan Konseptual Singkat / Abstrak** | `"hybrid"` | `true` | `true` | `true` | `true` | `false` | `5` |
| **4. Baca Prosedur Lengkap / Tabel Panjang** | `"hybrid"` | `true` | `true` | `true` | `false` | `true` | `5` |
| **5. Mode Cepat (Latency Minimal)** | `"hybrid"` | `false` | `true` | `false` | `false` | `false` | `5` |

---

## 6. Panduan Membaca Output Tool `query_knowledge`

Response JSON dari `query_knowledge` memiliki metadata tingkat atas (*top-level*):
* `query`: Teks pertanyaan asli.
* `total_results`: Jumlah potongan dokumen yang lolos seleksi dan dikembalikan.
* `latency_ms`: Waktu eksekusi pencarian dalam milidetik.
* `search_mode`: Mode pencarian yang digunakan (`"hybrid"`, `"dense"`, atau `"keyword"`).
* `reranked`: `true` jika hasil telah diurutkan ulang menggunakan Cross-Encoder Reranker.
* `graph_used`: `true` jika ekspansi Zero-LLM Knowledge Graph diaktifkan dan dijalankan.
* `graph_nodes_matched`: Daftar entitas/konsep/kode pada Knowledge Graph yang terdeteksi dari pertanyaan dan kandidat awal.
* `enhancement_used`: Teknik pengayaan query yang aktif (`"query_expansion"`, `"hyde"`, `"query_expansion+hyde"`, atau `"none"`).
* `hyde_document`: Kalimat dokumen hipotetis yang dibangkitkan jika `use_hyde=true`.

Setiap item di dalam `results` memuat informasi berikut:
* `content`: Teks potongan dokumen utama.
* `expanded_content`: Teks gabungan dengan chunk sebelum & sesudahnya (terisi jika `expand_context=true`).
* `section_title`: Hierarki bab/sub-judul atau nama sheet Excel tempat potongan teks berada.
* `filename` & `page_number`: Nama file sumber dan nomor halaman/slide/sheet.
* `knowledge_id`, `knowledge_name`, `version`: Identitas Knowledge Base sumber.
* `rerank_score`: Skor relevansi Cross-Encoder (`0.0` – `1.0`). Indikator paling akurat untuk menentukan seberapa relevan potongan tersebut menjawab pertanyaan.
* `similarity_score`: Skor kemiripan vektor `BAAI/bge-m3` (`0.0` – `1.0`).
* `keyword_score`: Skor kecocokan kata kunci PostgreSQL FTS (jika ada kata yang cocok persis).
* `via_graph`: Bernilai `true` jika potongan dokumen ini ditemukan berkat ekspansi lintas dokumen Knowledge Graph.
* `graph_reason`: Penjelasan jalur relasi Knowledge Graph yang menghubungkan potongan ini dengan hasil utama.
* `related_entities`: Daftar entitas/konsep/kode pada Knowledge Graph yang terkait dengan potongan dokumen ini.
* `page_image_url`: URL pratinjau gambar halaman asli dokumen (jika tersedia di MinIO).
"""


@mcp.resource(
    GUIDE_RESOURCE_URI,
    name="panduan_lengkap_metode_query",
    title="Panduan Lengkap Metode & Parameter Query MiiRAG",
    description=(
        "Panduan lengkap penjelasan metode pencarian (hybrid, dense, keyword), "
        "fitur peningkatan akurasi (use_rerank, use_query_expansion, use_graph, use_hyde, expand_context), "
        "daftar knowledge base aktif, rekomendasi kombinasi parameter, serta cara membaca skor hasil query."
    ),
    mime_type="text/markdown",
)
async def get_query_methods_guide() -> str:
    """Mengembalikan panduan lengkap metode dan parameter query MiiRAG beserta daftar knowledge aktif."""
    active_knowledges_md = await _fetch_active_knowledges_markdown()
    return _build_query_guide_markdown(active_knowledges_md)


async def _execute_query_request(payload: QueryRequest) -> dict[str, Any]:
    """Mengeksekusi QueryRequest secara langsung di memori (jika satu proses dengan BE) atau via HTTP/DB."""
    db_url = os.environ.get("DATABASE_URL", settings.DATABASE_URL)
    is_test_env = settings.APP_ENV == "test" or "/miirag_test" in db_url

    if _IN_BACKEND_PROCESS or is_test_env or os.environ.get("MIIRAG_MCP_DIRECT_DB", "").lower() in ("1", "true"):
        response = await execute_similarity_query(payload)
        return response.model_dump(mode="json")

    default_be_url = f"http://127.0.0.1:{settings.BACKEND_PORT}"
    backend_url = os.environ.get("MIIRAG_BACKEND_URL", default_be_url).rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{backend_url}{settings.API_V1_PREFIX}/query",
                json=payload.model_dump(mode="json"),
            )
            if resp.status_code == 200:
                return resp.json()
    except Exception as exc:  # noqa: BLE001
        logger.debug("Backend HTTP lokal tidak terjangkau (%s), beralih ke koneksi DB langsung.", exc)

    response = await execute_similarity_query(payload)
    return response.model_dump(mode="json")


@mcp.tool(
    name="list_knowledges",
    title="List MiiRAG Knowledge Base",
    description=LIST_TOOL_DESCRIPTION,
)
async def list_knowledges(
    search: Annotated[
        str | None,
        Field(
            default=None,
            description="Opsional: Kata kunci untuk memfilter nama Knowledge Base (kosongkan untuk menampilkan semua).",
        ),
    ] = None,
    status: Annotated[
        Literal["done", "all", "processing", "unfinished"],
        Field(
            default="done",
            description=(
                "Filter status Knowledge Base: 'done' (default, hanya yang siap di-query), "
                "'all' (semua status), 'processing', atau 'unfinished'."
            ),
        ),
    ] = "done",
) -> dict[str, Any]:
    """Mengambil daftar Knowledge Base beserta UUID, status, versi aktif, dan daftar dokumen di dalamnya."""
    async with AsyncSessionLocal() as session:
        list_resp = await service_list_knowledges(session, q=search, status_filter=status)
        knowledge_ids = [item.id for item in list_resp.items]

        docs_by_knowledge: dict[uuid.UUID, list[dict[str, Any]]] = {}
        if knowledge_ids:
            docs_stmt = (
                select(
                    Knowledge.id.label("knowledge_id"),
                    Document.id.label("doc_id"),
                    Document.filename,
                    Document.page_count,
                    Document.chunk_count,
                    Document.status,
                )
                .join(
                    KnowledgeVersion,
                    (KnowledgeVersion.knowledge_id == Knowledge.id)
                    & (KnowledgeVersion.version_number == Knowledge.current_version),
                )
                .join(
                    KnowledgeVersionDocument,
                    KnowledgeVersionDocument.version_id == KnowledgeVersion.id,
                )
                .join(Document, Document.id == KnowledgeVersionDocument.document_id)
                .where(Knowledge.id.in_(knowledge_ids))
                .order_by(Document.created_at.asc())
            )
            for row in (await session.execute(docs_stmt)).all():
                docs_by_knowledge.setdefault(row.knowledge_id, []).append(
                    {
                        "id": str(row.doc_id),
                        "filename": row.filename,
                        "page_count": row.page_count,
                        "chunk_count": row.chunk_count,
                        "status": row.status.value if hasattr(row.status, "value") else str(row.status),
                    }
                )

        items_out: list[dict[str, Any]] = []
        for item in list_resp.items:
            dumped = item.model_dump(mode="json")
            dumped["documents"] = docs_by_knowledge.get(item.id, [])
            items_out.append(dumped)

        return {
            "counts": list_resp.counts.model_dump(mode="json"),
            "total": len(items_out),
            "items": items_out,
        }


@mcp.tool(
    name="query_knowledge",
    title="Query MiiRAG Knowledge Base",
    description=TOOL_DESCRIPTION,
)
async def query_knowledge(
    query: Annotated[
        str,
        Field(
            min_length=1,
            max_length=4000,
            description=(
                "Teks pertanyaan atau kata kunci yang ingin dicari di Knowledge Base. "
                f"Baca resource `{GUIDE_RESOURCE_URI}` untuk panduan lengkap memilih metode dan parameter query."
            ),
        ),
    ],
    knowledge_ids: Annotated[
        list[str] | None,
        Field(
            default=None,
            description=(
                "Opsional: Daftar UUID knowledge tertentu yang ingin dicari. "
                "Panggil tool `list_knowledges` terlebih dahulu atau lihat resource "
                f"`{GUIDE_RESOURCE_URI}` untuk mendapatkan daftar UUID knowledge yang tersedia. "
                "Biarkan kosong (null) untuk mencari di seluruh knowledge aktif berstatus done."
            ),
        ),
    ] = None,
    top_k: Annotated[
        int,
        Field(
            default=settings.DEFAULT_TOP_K,
            ge=1,
            le=50,
            description="Jumlah maksimum potongan dokumen yang dikembalikan (1 - 50, default: 5).",
        ),
    ] = settings.DEFAULT_TOP_K,
    score_threshold: Annotated[
        float,
        Field(
            default=settings.DEFAULT_SCORE_THRESHOLD,
            ge=0.0,
            le=1.0,
            description=(
                "Batas minimum cosine similarity score (0.0 - 1.0, default: 0.35). "
                f"Lihat panduan penyesuaian threshold di resource `{GUIDE_RESOURCE_URI}`."
            ),
        ),
    ] = settings.DEFAULT_SCORE_THRESHOLD,
    search_mode: Annotated[
        Literal["hybrid", "dense", "keyword"],
        Field(
            default="hybrid",
            description=(
                "Mode pencarian: 'hybrid' (Vector + Keyword RRF, direkomendasikan), "
                "'dense' (Vector BAAI/bge-m3 saja), atau 'keyword' (Full-Text Search kata persis). "
                f"Penjelasan lengkap perbandingan mode ada di resource `{GUIDE_RESOURCE_URI}`."
            ),
        ),
    ] = "hybrid",
    use_rerank: Annotated[
        bool,
        Field(
            default=settings.RERANK_ENABLED,
            description=(
                "Aktifkan Cross-Encoder Reranker multilingual untuk menyaring dan mengurutkan ulang hasil "
                f"agar jawaban paling relevan berada di posisi teratas. Detail di resource `{GUIDE_RESOURCE_URI}`."
            ),
        ),
    ] = settings.RERANK_ENABLED,
    use_query_expansion: Annotated[
        bool,
        Field(
            default=True,
            description=(
                "Aktifkan ekspansi sinonim dan singkatan otomatis Bahasa Indonesia untuk memperkaya recall. "
                f"Detail di resource `{GUIDE_RESOURCE_URI}`."
            ),
        ),
    ] = True,
    use_graph: Annotated[
        bool,
        Field(
            default=True,
            description=(
                "Aktifkan Zero-LLM Knowledge Graph (BAAI/bge-m3) untuk menelusuri keterhubungan entitas & jembatan makna "
                f"lintas dokumen (multi-hop retrieval). Detail mekanisme ada di resource `{GUIDE_RESOURCE_URI}`."
            ),
        ),
    ] = True,
    use_hyde: Annotated[
        bool,
        Field(
            default=False,
            description=(
                "Aktifkan Hypothetical Document Embeddings (HyDE) untuk pertanyaan singkat/konseptual. "
                f"Lihat kapan sebaiknya diaktifkan/dimatikan pada resource `{GUIDE_RESOURCE_URI}`."
            ),
        ),
    ] = False,
    expand_context: Annotated[
        bool,
        Field(
            default=False,
            description=(
                "Sertakan potongan teks tetangga (sebelum & sesudah) dari halaman yang sama pada field expanded_content. "
                f"Detail di resource `{GUIDE_RESOURCE_URI}`."
            ),
        ),
    ] = False,
) -> dict[str, Any]:
    """Melakukan pencarian dokumen pada MiiRAG Knowledge Base.

    PENTING: Untuk penjelasan lengkap mengenai metode query (`search_mode`),
    opsi peningkatan akurasi (`use_rerank`, `use_query_expansion`, `use_graph`, `use_hyde`, `expand_context`),
    dan rekomendasi kombinasi parameter, baca terlebih dahulu resource MCP `miirag://guides/query-methods`.
    """
    parsed_knowledge_ids: list[uuid.UUID] | None = None
    if knowledge_ids:
        parsed_knowledge_ids = [uuid.UUID(str(kid).strip()) for kid in knowledge_ids if str(kid).strip()]

    payload = QueryRequest(
        query=query,
        knowledge_ids=parsed_knowledge_ids,
        top_k=top_k,
        score_threshold=score_threshold,
        search_mode=search_mode,
        use_rerank=use_rerank,
        use_hyde=use_hyde,
        use_query_expansion=use_query_expansion,
        expand_context=expand_context,
        use_graph=use_graph,
    )
    return await _execute_query_request(payload)


def build_mcp_http_app() -> Starlette:
    """Membangun aplikasi ASGI Starlette yang melayani Streamable HTTP (/mcp) sekaligus SSE (/sse & /messages/)."""
    security = TransportSecuritySettings(enable_dns_rebinding_protection=False)

    if settings.MCP_TRANSPORT.lower() == "sse":
        return mcp.sse_app(
            sse_path=settings.MCP_SSE_PATH,
            message_path=settings.MCP_MESSAGE_PATH,
            transport_security=security,
            host=settings.MCP_HOST,
        )

    app_starlette = mcp.streamable_http_app(
        streamable_http_path=settings.MCP_PATH,
        transport_security=security,
        host=settings.MCP_HOST,
    )
    sse_starlette = mcp.sse_app(
        sse_path=settings.MCP_SSE_PATH,
        message_path=settings.MCP_MESSAGE_PATH,
        transport_security=security,
        host=settings.MCP_HOST,
    )
    # Tambahkan route SSE (/sse dan /messages/) agar client Streamable HTTP maupun SSE bisa terhubung ke port yang sama
    for route in sse_starlette.routes[:2]:
        app_starlette.routes.insert(1, route)
    return app_starlette


async def start_mcp_background_server() -> None:
    """Menjalankan MCP HTTP/SSE server di background task dalam event loop yang sama dengan FastAPI Backend."""
    global _IN_BACKEND_PROCESS, _bg_mcp_server, _bg_mcp_task
    if _bg_mcp_task is not None and not _bg_mcp_task.done():
        return

    _IN_BACKEND_PROCESS = True
    mcp_asgi_app = build_mcp_http_app()
    config = uvicorn.Config(
        app=mcp_asgi_app,
        host=settings.MCP_HOST,
        port=settings.MCP_PORT,
        log_level="info",
        access_log=False,
    )
    _bg_mcp_server = _EmbeddedUvicornServer(config=config)
    _bg_mcp_task = asyncio.create_task(_bg_mcp_server.serve(), name="miirag-mcp-server")
    display_host = "localhost" if settings.MCP_HOST in ("0.0.0.0", "::") else settings.MCP_HOST
    logger.info(
        "MiiRAG MCP Server aktif di http://%s:%d%s (SSE: http://%s:%d%s)",
        display_host,
        settings.MCP_PORT,
        settings.MCP_PATH,
        display_host,
        settings.MCP_PORT,
        settings.MCP_SSE_PATH,
    )


async def stop_mcp_background_server() -> None:
    """Menghentikan MCP background server dengan bersih saat FastAPI Backend shutdown/reload."""
    global _IN_BACKEND_PROCESS, _bg_mcp_server, _bg_mcp_task
    _IN_BACKEND_PROCESS = False
    if _bg_mcp_server is not None:
        _bg_mcp_server.should_exit = True
    if _bg_mcp_task is not None:
        try:
            await asyncio.wait_for(_bg_mcp_task, timeout=5.0)
        except (TimeoutError, asyncio.CancelledError):
            _bg_mcp_task.cancel()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Pesan saat menghentikan MCP background server: %s", exc)
    _bg_mcp_server = None
    _bg_mcp_task = None


def main() -> None:
    """Entrypoint CLI untuk menjalankan MiiRAG MCP Server secara mandiri (stdio, streamable-http, atau sse)."""
    parser = argparse.ArgumentParser(description="Jalankan MiiRAG MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http", "sse"],
        default=os.environ.get("MCP_CLI_TRANSPORT", "stdio"),
        help="Protokol transport MCP (default: stdio)",
    )
    parser.add_argument(
        "--host",
        default=settings.MCP_HOST,
        help=f"Host untuk mode HTTP/SSE (default dari .env: {settings.MCP_HOST})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=settings.MCP_PORT,
        help=f"Port untuk mode HTTP/SSE (default dari .env: {settings.MCP_PORT})",
    )
    args = parser.parse_args()

    if args.transport == "stdio":
        mcp.run(transport="stdio")
    elif args.transport == "sse":
        mcp.run(
            transport="sse",
            host=args.host,
            port=args.port,
            sse_path=settings.MCP_SSE_PATH,
            message_path=settings.MCP_MESSAGE_PATH,
        )
    else:
        mcp.run(
            transport="streamable-http",
            host=args.host,
            port=args.port,
            streamable_http_path=settings.MCP_PATH,
        )


if __name__ == "__main__":
    main()
