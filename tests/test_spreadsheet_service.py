import io
from datetime import date
from pathlib import Path

import openpyxl
import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.services.embedding_service import embedding_service
from app.services.pdf_service import extract_and_chunk_document_with_snapshots
from app.services.rerank_service import rerank_service
from app.services.spreadsheet_service import extract_and_chunk_spreadsheet
from tests.test_knowledge_and_query import _wait_for_done


def _make_xlsx_bytes() -> bytes:
    """Membuat workbook .xlsx realistis: multi-sheet, banner merge, vertical merge, tanggal, sheet kosong, dan teks bebas."""
    wb = openpyxl.Workbook()

    # Sheet 1: Matriks Risiko dengan banner merge + vertical merge + footnote
    ws1 = wb.active
    ws1.title = "Matriks Risiko"
    ws1["A1"] = "MATRIKS KEWENANGAN KLAIM 2026"
    ws1.merge_cells("A1:E1")

    ws1.append([])  # baris 2 kosong
    ws1.append(["Kode", "Kategori", "Nominal Maks", "Tanggal Efektif", "Eskalasi Direksi"])
    ws1.append(["TRX-RISK-77", "Kecelakaan Kerja", 150000000.0, date(2026, 1, 15), "Tidak"])
    ws1.append(["TRX-RISK-88", None, 500000000.0, date(2026, 2, 1), "Ya"])
    ws1.merge_cells("B4:B5")
    ws1.append(["*Catatan: Seluruh klaim di atas Rp 500 juta wajib audit khusus."])

    # Sheet 2: Kosong total (harus dilewati)
    wb.create_sheet(title="Sheet Kosong")

    # Sheet 3: Catatan bebas tanpa tabel
    ws3 = wb.create_sheet(title="Catatan Bebas")
    ws3["A1"] = "Panduan Singkat Verifikator"
    ws3["A3"] = "1. Pastikan nomor polis aktif sebelum melakukan verifikasi."
    ws3["A4"] = "2. Lampirkan bukti foto kerusakan asli."

    buf = io.BytesIO()
    wb.save(buf)
    wb.close()
    return buf.getvalue()


def test_xlsx_multisheet_unmerge_banners_and_dual_representation(tmp_path: Path) -> None:
    xlsx_path = tmp_path / "matriks_klaim.xlsx"
    xlsx_path.write_bytes(_make_xlsx_bytes())

    sheet_count, chunks, snapshots = extract_and_chunk_document_with_snapshots(
        xlsx_path, render_snapshots=True
    )

    # Sheet kosong dilewati -> 2 sheet terisi, dan tanpa snapshot gambar
    assert sheet_count == 2
    assert snapshots == {}
    assert len(chunks) >= 2

    # Sheet 1: banner tidak digandakan ke semua kolom, vertical merge di-fill down
    s1_chunks = [c for c in chunks if c.page_number == 1]
    assert len(s1_chunks) >= 1
    table_chunk = next(c for c in s1_chunks if "| Kode |" in c.content)

    assert "MATRIKS KEWENANGAN KLAIM 2026" in table_chunk.content
    assert "MATRIKS KEWENANGAN KLAIM 2026 | MATRIKS KEWENANGAN KLAIM 2026" not in table_chunk.content
    assert "| TRX-RISK-77 | Kecelakaan Kerja | 150000000 | 2026-01-15 | Tidak |" in table_chunk.content
    # Baris kedua mewarisi kategori dari vertical merge B4:B5
    assert "| TRX-RISK-88 | Kecelakaan Kerja | 500000000 | 2026-02-01 | Ya |" in table_chunk.content
    assert table_chunk.section_title == "Sheet: Matriks Risiko > MATRIKS KEWENANGAN KLAIM 2026"

    # Dual-Representation: search_text menggunakan format Row-Semantic Key-Value
    assert table_chunk.search_text is not None
    assert "Kode: TRX-RISK-88 | Kategori: Kecelakaan Kerja | Nominal Maks: 500000000" in table_chunk.search_text
    assert "Eskalasi Direksi: Ya" in table_chunk.search_text

    embed_text = table_chunk.to_embedding_text("matriks_klaim.xlsx")
    assert "[Dokumen: matriks_klaim.xlsx | Halaman: 1 | Bagian: Sheet: Matriks Risiko > MATRIKS KEWENANGAN KLAIM 2026]" in embed_text
    assert "Eskalasi Direksi: Ya" in embed_text

    # Sheet 3 (dipetakan ke sheet_number = 2): teks bebas tanpa tabel tetap terekstrak rapi
    s2_chunks = [c for c in chunks if c.page_number == 2]
    assert len(s2_chunks) >= 1
    s2_text = "\n".join(c.content for c in s2_chunks)
    assert "Panduan Singkat Verifikator" in s2_text
    assert "Pastikan nomor polis aktif" in s2_text


def test_xlsx_large_table_splitting_repeats_headers_and_bounds_search_text(tmp_path: Path) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Daftar Produk"
    ws.append(["Kode", "Nama Produk", "Kategori", "Status"])
    for i in range(1, 36):
        ws.append([f"PRD-{i:03d}", f"Produk Asuransi Syariah Paket {i}", "Perlindungan", "Aktif"])

    xlsx_path = tmp_path / "produk_besar.xlsx"
    wb.save(xlsx_path)
    wb.close()

    sheet_count, chunks = extract_and_chunk_spreadsheet(xlsx_path, chunk_size=350)
    assert sheet_count == 1
    assert len(chunks) >= 4

    for chunk in chunks:
        assert chunk.content.startswith("| Kode | Nama Produk | Kategori | Status |\n| --- | --- | --- | --- |")
        assert chunk.search_text is not None
        assert "Kode: PRD-" in chunk.search_text
        assert "Status: Aktif" in chunk.search_text
        assert chunk.section_title == "Sheet: Daftar Produk"

    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


def test_csv_semicolon_bom_and_comma_parsing(tmp_path: Path) -> None:
    # Format CSV Excel lokal Indonesia: UTF-8 BOM + delimiter titik koma ';'
    semicolon_csv = (
        "\ufeffKode;Nama Cabang;Kota;Limit Harian\n"
        "CAB-01;Cabang Sudirman;Jakarta Selatan;250000000\n"
        "CAB-02;Cabang Dago;Bandung;175000000\n"
    ).encode("utf-8")
    p_semi = tmp_path / "cabang_id.csv"
    p_semi.write_bytes(semicolon_csv)

    count_s, chunks_s, snaps_s = extract_and_chunk_document_with_snapshots(p_semi, render_snapshots=True)
    assert count_s == 1
    assert snaps_s == {}
    assert len(chunks_s) == 1
    assert "| Kode | Nama Cabang | Kota | Limit Harian |" in chunks_s[0].content
    assert "| CAB-02 | Cabang Dago | Bandung | 175000000 |" in chunks_s[0].content
    assert chunks_s[0].search_text is not None
    assert "Kode: CAB-02 | Nama Cabang: Cabang Dago | Kota: Bandung | Limit Harian: 175000000" in chunks_s[0].search_text

    # Format CSV standar koma dengan quoted field berisi koma
    comma_csv = (
        b"Kode,Deskripsi,Status\n"
        b'CSV-ITEM-99,"Pengecualian bencana alam, perang, dan huru-hara",Berlaku\n'
    )
    p_comma = tmp_path / "pengecualian.csv"
    p_comma.write_bytes(comma_csv)

    count_c, chunks_c = extract_and_chunk_spreadsheet(p_comma)
    assert count_c == 1
    assert "| CSV-ITEM-99 | Pengecualian bencana alam, perang, dan huru-hara | Berlaku |" in chunks_c[0].content
    assert chunks_c[0].search_text is not None
    assert "Status: Berlaku" in chunks_c[0].search_text


@pytest.mark.asyncio
async def test_upload_invalid_xlsx_and_binary_csv_rejected(client: AsyncClient) -> None:
    bad_xlsx = await client.post(
        "/api/v1/knowledges",
        data={"name": "Bad Excel", "process_now": "false"},
        files=[
            (
                "files",
                (
                    "fake.xlsx",
                    b"ini bukan file zip xlsx",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                ),
            )
        ],
    )
    assert bad_xlsx.status_code == 400
    assert "Excel" in bad_xlsx.json()["detail"]

    bad_csv = await client.post(
        "/api/v1/knowledges",
        data={"name": "Bad CSV", "process_now": "false"},
        files=[("files", ("binary.csv", b"\x89PNG\r\n\x1a\n\x00\x00binary", "text/csv"))],
    )
    assert bad_csv.status_code == 400
    assert "CSV" in bad_csv.json()["detail"]


@pytest.mark.asyncio
async def test_upload_and_query_xlsx_and_csv_end_to_end(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    dim = settings.EMBEDDING_DIMENSIONS
    captured_embed_texts: list[str] = []
    captured_rerank_docs: list[str] = []

    def _mock_vec(text: str) -> list[float]:
        vec = [0.0] * dim
        low = text.lower()
        if "trx-risk-88" in low or "eskalasi direksi" in low:
            vec[0] = 1.0
        elif "csv-item-99" in low or "bencana alam" in low:
            vec[1] = 1.0
        else:
            vec[2] = 1.0
        return vec

    async def fake_embed_documents(texts: list[str], title: str | None = None) -> list[list[float]]:
        captured_embed_texts.extend(texts)
        return [_mock_vec(t) for t in texts]

    async def fake_embed_query(query: str) -> list[float]:
        return _mock_vec(query)

    async def fake_rerank(query: str, documents: list[str]) -> list[float]:
        captured_rerank_docs.extend(documents)
        q_low = query.lower()
        return [
            0.95
            if ("trx-risk-88" in q_low and "trx-risk-88" in d.lower())
            or ("csv-item-99" in q_low and "csv-item-99" in d.lower())
            else 0.2
            for d in documents
        ]

    monkeypatch.setattr(embedding_service, "embed_documents", fake_embed_documents)
    monkeypatch.setattr(embedding_service, "embed_query", fake_embed_query)
    monkeypatch.setattr(rerank_service, "rerank", fake_rerank)

    xlsx_bytes = _make_xlsx_bytes()
    csv_bytes = (
        b"Kode;Keterangan;Status\n"
        b"CSV-ITEM-99;Pengecualian klaim bencana alam besar;Aktif\n"
    )

    resp = await client.post(
        "/api/v1/knowledges",
        data={"name": "Knowledge Spreadsheet", "process_now": "true"},
        files=[
            (
                "files",
                (
                    "Matriks_Klaim.xlsx",
                    xlsx_bytes,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                ),
            ),
            ("files", ("Pengecualian.csv", csv_bytes, "text/csv")),
        ],
    )
    assert resp.status_code == 201
    kid = resp.json()["id"]

    done = await _wait_for_done(client, kid, timeout=15.0)
    assert done["status"] == "done"
    assert done["embedded_doc_count"] == 2

    # Verifikasi Dual-Representation masuk ke embed_documents
    assert any("Kode: TRX-RISK-88 | Kategori: Kecelakaan Kerja" in t for t in captured_embed_texts)
    assert any(
        "Kode: CSV-ITEM-99 | Keterangan: Pengecualian klaim bencana alam besar" in t
        for t in captured_embed_texts
    )

    # 1. Query data Excel (.xlsx)
    q_xlsx = await client.post(
        "/api/v1/query",
        json={
            "query": "TRX-RISK-88 eskalasi direksi",
            "knowledge_ids": [kid],
            "top_k": 3,
            "score_threshold": 0.35,
            "search_mode": "hybrid",
            "use_rerank": True,
        },
    )
    assert q_xlsx.status_code == 200
    x_data = q_xlsx.json()
    assert x_data["total_results"] >= 1
    top_x = x_data["results"][0]
    assert top_x["filename"] == "Matriks_Klaim.xlsx"
    assert top_x["page_image_url"] is None
    assert "| TRX-RISK-88 | Kecelakaan Kerja | 500000000 | 2026-02-01 | Ya |" in top_x["content"]
    assert top_x["section_title"] == "Sheet: Matriks Risiko > MATRIKS KEWENANGAN KLAIM 2026"
    # Reranker menerima Row-Semantic Key-Value search_text
    assert any("Eskalasi Direksi: Ya" in d for d in captured_rerank_docs)

    # 2. Query data CSV (.csv)
    q_csv = await client.post(
        "/api/v1/query",
        json={
            "query": "CSV-ITEM-99 bencana alam",
            "knowledge_ids": [kid],
            "top_k": 3,
            "score_threshold": 0.35,
            "search_mode": "hybrid",
            "use_rerank": True,
        },
    )
    assert q_csv.status_code == 200
    c_data = q_csv.json()
    assert c_data["total_results"] >= 1
    top_c = c_data["results"][0]
    assert top_c["filename"] == "Pengecualian.csv"
    assert top_c["page_image_url"] is None
    assert "| CSV-ITEM-99 | Pengecualian klaim bencana alam besar | Aktif |" in top_c["content"]
