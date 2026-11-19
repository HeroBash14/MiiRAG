# MiiRAG (Multi-format Intelligent Ingestion RAG)

Platform RAG performa tinggi untuk dokumen multi-format (**PDF**, **Word `.docx`**, **PowerPoint `.pptx`**, **Excel `.xlsx`**, dan **CSV `.csv`**) menggunakan **FastAPI**, **Hybrid Markdown Decoder**, **Dual-Representation Spreadsheet Parser**, embedding lokal **`BAAI/bge-m3` (1024 Dimensi)**, **PostgreSQL + `pgvector`**, dan **MinIO Object Storage** untuk visual grounding.

---

## 📖 Dokumentasi Lengkap & Arsitektur

Dokumentasi arsitektur dan alur pipeline data yang mendalam beserta visualisasi diagram SVG dan gambar resolusi tinggi telah disediakan di folder [`docs/`](docs/):

* 🏛️ [**Arsitektur Sistem (docs/ARCHITECTURE.md)**](docs/ARCHITECTURE.md): Diagram 3-tier, komponen service, model database relasional, siklus versioning dokumen, dan isolasi testing database.
* ⚙️ [**Alur Pipeline Ingestion & Embedding (docs/PIPELINE_FLOW.md)**](docs/PIPELINE_FLOW.md): Diagram alur tahapan ekstraksi hibrida (Tier 1 Headless & Tier 2 AST), ekstraksi tabel Markdown & speaker notes, *table-aware chunking*, vektorisasi, hingga sinkronisasi MinIO.
* 🖼️ [**Galeri Diagram Arsitektur & Pipeline (docs/images/)**](docs/images/): Kumpulan file gambar PNG resolusi tinggi dan vektor SVG tajam.

---

## ✨ Fitur Utama

- **Multi-Format Ingestion (PDF, DOCX, PPTX, XLSX, CSV)**: Mendukung pengunggahan dokumen PDF, Microsoft Word (`.docx`), PowerPoint (`.pptx`), Excel (`.xlsx`), dan CSV (`.csv`) dengan validasi integritas *magic header* & deteksi file biner.
- **Page-Preserving Hybrid Markdown & Spreadsheet Dual-Representation**: Menjaga struktur tabel (`|---|---|`), heading, daftar, *speaker notes* PPTX, serta auto-unmerge & *Row-Semantic Key-Value embedding* untuk Excel/CSV (bebas layout tanpa snapshot MinIO).
- **Contextual Chunk Headers & Table-Aware Chunking**: Mencegah pemutusan tabel, mengulang header kolom pada setiap pecahan chunk tabel, serta menyematkan hierarki judul dokumen & bagian pada embedding dan indeks pencarian.
- **Hybrid Retrieval + Cross-Encoder Reranking**: Menggabungkan **Dense Vector (`BAAI/bge-m3` HNSW)** dan **Sparse Full-Text (`PostgreSQL tsvector GIN`)** via **Reciprocal Rank Fusion (RRF)**, lalu disaring dengan **Multilingual Cross-Encoder Reranker (`mmarco-mMiniLMv2`)**.
- **Query Enhancement & Context Expansion**: Mendukung **HyDE** (*Hypothetical Document Embeddings*), **Query Expansion** sinonim/singkatan, dan **Expand Context** (*neighboring chunk window*) secara opsional per request.
- **Visual Grounding dengan MinIO Snapshot**: Setiap halaman dan slide dirender menjadi gambar PNG 150 DPI yang diunggah ke MinIO dan dapat diinspeksi secara instan via secure presigned URL.
- **Document Versioning (`Re-new`)**: Pembaruan dokumen menaikkan versi (`v1` &rarr; `v2` &rarr; `v3`), menyimpan riwayat versi, dan **tidak meng-embed ulang** dokumen lama yang dipertahankan (*Zero Re-Embedding Waste*).
- **Database Testing Terisolasi & RAG Evaluation**: Pengujian otomatis (`pytest`) berjalan otomatis di database terpisah (`miirag_test`), dilengkapi script benchmark evaluasi kuantitatif (`scripts/evaluate_rag.py`) untuk mengukur Hit@K, MRR, dan NDCG@K.

---

## 🚀 Menjalankan Secara Lokal

### 1. Salin Konfigurasi Environment:
```bash
cp .env.example .env
```

### 2. Jalankan PostgreSQL + `pgvector`:
```bash
docker compose up -d
```
> ⚠️ **Peringatan:** Jangan gunakan `docker compose down -v` karena flag `-v` akan menghapus volume database. Gunakan `docker compose stop` atau `docker compose down`.

### 3. Sinkronkan Dependensi & Jalankan Migrasi Database:
```bash
uv sync
uv run alembic upgrade head
```

### 4. Jalankan Server FastAPI:
```bash
uv run uvicorn app.main:app --reload --port 8000
```
Dokumentasi interaktif OpenAPI tersedia di `http://localhost:8000/docs`.

### 5. Jalankan Frontend Web UI:
```bash
cd Frontend
npm install
npm run dev
```
Buka Web UI di browser: `http://localhost:3000`.

---

## 🧪 Menjalankan Pengujian Otomatis

```bash
# Menjalankan seluruh test suite (otomatis menggunakan database miirag_test)
uv run pytest -v

# Memeriksa kualitas kode (linting)
uv run ruff check app/ tests/
```
