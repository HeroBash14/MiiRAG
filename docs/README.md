# Dokumentasi Teknis MiiRAG

Selamat datang di pusat dokumentasi teknis **MiiRAG** (*Multi-format Intelligent Ingestion Retrieval-Augmented Generation*).

Dokumentasi ini disusun untuk mempermudah developer, AI engineer, maupun DevOps dalam memahami arsitektur, alur pipeline data, serta cara kerja sistem secara mendalam.

---

## 📚 Daftar Isi Dokumentasi

1. [**Arsitektur Sistem (`ARCHITECTURE.md`)**](ARCHITECTURE.md)
   * Diagram Arsitektur 3-Tier (Frontend, Backend, Persistence Layer).
   * Penjelasan Service & Modul Backend.
   * Model Relasional Database & Siklus Versioning Dokumen (*Zero Re-Embedding Waste*).
   * Konfigurasi MinIO Object Storage & Docker Persistence.
   * Strategi Isolasi Database Pengujian (`miirag_test`).

2. [**Alur Pipeline Ingestion & Embedding (`PIPELINE_FLOW.md`)**](PIPELINE_FLOW.md)
   * Diagram Alur Pipeline End-to-End.
   * Tahapan Validasi Magic Header File (`.pdf`, `.docx`, `.pptx`).
   * Dekoder Dokumen Hibrida Dua Tingkat (*Tier 1: Headless LibreOffice + PyMuPDF vs Tier 2: Pure Python AST*).
   * Ekstraksi Tabel Markdown & Catatan Presenter (*Speaker Notes*).
   * Algoritma *Table-Aware Semantic Chunking* + *Contextual Chunk Headers*.
   * Model Vektor Embedding `BAAI/bge-m3` (1024 Dimensi).

3. [**Metode Query & Retrieval (`RETRIEVAL_METHODS.md`)**](RETRIEVAL_METHODS.md)
   * Diagram Alur Hybrid Retrieval & Cross-Encoder Reranking.
   * 3 Mode Retrieval (`hybrid` dengan RRF, `dense`, `keyword`).
   * Penjelasan Fitur Peningkatan Query: *Cross-Encoder Reranker*, *Query Expansion*, *HyDE*, dan *Expand Context*.
   * Spesifikasi JSON API `/api/v1/query`, interpretasi skor, *Decision Matrix*, dan hasil benchmark kuantitatif (`scripts/evaluate_rag.py`).

---

## 🖼️ Visualisasi Arsitektur & Pipeline

Seluruh diagram sistem telah diekspor dalam resolusi tinggi dan tersedia dalam dua format (PNG untuk pratinjau cepat, dan SVG untuk inspeksi vektor tanpa pecah):

| Diagram | Pratinjau Gambar (PNG) | Sumber Vektor (SVG) |
| :--- | :--- | :--- |
| **System Architecture Overview** | [Lihat PNG](images/architecture_overview.png) | [Buka SVG](images/architecture_overview.svg) |
| **Ingestion & Embedding Pipeline** | [Lihat PNG](images/embedding_pipeline_flow.png) | [Buka SVG](images/embedding_pipeline_flow.svg) |
| **Query & Retrieval Lifecycle** | [Lihat PNG](images/query_retrieval_flow.png) | [Buka SVG](images/query_retrieval_flow.svg) |

---

## 🚀 Panduan Ringkas Menjalankan Proyek (Developer Cheat Sheet)

### 1. Prasyarat Sistem
* Linux / macOS / WSL2 (Ubuntu 22.04+ direkomendasikan).
* Docker & Docker Compose (untuk PostgreSQL + pgvector).
* Python 3.11+ dikelola dengan [`uv`](https://github.com/astral-sh/uv).
* Node.js 18+ & npm (untuk Frontend).
* LibreOffice (`soffice`) terpasang di sistem (`sudo apt install libreoffice` atau setara).

### 2. Menjalankan Docker Database
```bash
# Menjalankan PostgreSQL dengan pgvector (volume data tersimpan aman)
docker compose up -d

# Memeriksa status container
docker ps
```
> ⚠️ **Catatan Penting:** Jangan gunakan perintah `docker compose down -v` karena flag `-v` akan menghapus volume database. Cukup gunakan `docker compose stop` atau `docker compose down`.

### 3. Menjalankan Backend (FastAPI)
```bash
# Sinkronisasi dependensi Python
uv sync

# Menjalankan migrasi database
uv run alembic upgrade head

# Menjalankan server backend
uv run uvicorn app.main:app --reload --port 8000
```
Dokumentasi interaktif Swagger UI tersedia di: `http://localhost:8000/docs`.

### 4. Menjalankan Frontend (React + Vite)
```bash
cd Frontend
npm install
npm run dev
```
Akses aplikasi Web UI di: `http://localhost:3000` (atau port yang ditampilkan di terminal).

### 5. Menjalankan Pengujian Otomatis (Tests)
```bash
# Menjalankan seluruh test suite (aman, berjalan di database miirag_test)
uv run pytest -v

# Memeriksa kepatuhan kode (linting)
uv run ruff check app/ tests/
```
