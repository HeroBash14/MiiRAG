# Frontend – RAG Knowledge Base

Aplikasi Frontend React (Vite + TypeScript) untuk manajemen knowledge base dan dokumen RAG berbasis PDF, terintegrasi penuh dengan backend FastAPI + pgvector.

## Menjalankan Aplikasi

1. Pastikan backend FastAPI sudah berjalan di port 8000:
   ```bash
   # Di root project MiiRAG
   uv run uvicorn app.main:app --reload
   ```

2. Jalankan frontend development server:
   ```bash
   cd Frontend
   npm run dev
   ```

3. Buka browser di [http://localhost:3000](http://localhost:3000).

## Fitur Utama

- **Knowledge List**: Pencarian real-time, filter status (*Semua, Un-finished, On-process, Done*) lengkap dengan jumlah item.
- **Card Knowledge**: Badge status, label versi (*v1, v2, ...*), animasi progress bar saat proses embedding sedang berjalan (*X dari Y dokumen sudah di-embed*).
- **Knowledge Detail**:
  - Tab Dokumen: daftar nama file, ukuran, jumlah halaman, jumlah chunk, dan status tiap dokumen (*Menunggu, Sedang di-embed, Selesai*).
  - Tab Riwayat Versi: catatan perubahan, tanggal, dan tanda *Versi aktif*.
  - Tab Uji Similarity Search: uji coba pertanyaan langsung ke dokumen tanpa LLM menggunakan cosine similarity score.
- **Modal Native `<dialog>`**:
  - Buat knowledge baru (Simpan draft atau Simpan & proses).
  - Edit draft (tambah/hapus dokumen).
  - Re-new (naik versi otomatis, mempertahankan dokumen lama tanpa re-embed).
- **Dark/Light Mode**: Mendukung peralihan tema terang dan gelap.
