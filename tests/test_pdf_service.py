from pathlib import Path

import pytest

from app.services.pdf_service import extract_and_chunk_pdf
from tests.conftest import make_pdf_bytes, make_pptx_bytes


def test_extract_and_chunk_pdf_multipage(tmp_path: Path) -> None:
    pdf_path = tmp_path / "sample.pdf"
    long_para = ("Prosedur klaim asuransi syariah memerlukan formulir pengajuan dan fotokopi polis. " * 25).strip()
    pdf_bytes = make_pdf_bytes(
        [
            f"Halaman Pertama\n\n{long_para}",
            "Halaman Kedua berisi daftar pengecualian polis kendaraan.",
        ]
    )
    pdf_path.write_bytes(pdf_bytes)

    page_count, chunks = extract_and_chunk_pdf(pdf_path)

    assert page_count == 2
    assert len(chunks) >= 3
    assert chunks[0].chunk_index == 0
    assert chunks[0].page_number == 1
    assert chunks[-1].page_number == 2
    assert "pengecualian polis kendaraan" in chunks[-1].content
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


def test_extract_empty_pdf_raises(tmp_path: Path) -> None:
    pdf_path = tmp_path / "blank.pdf"
    pdf_path.write_bytes(make_pdf_bytes([""]))

    with pytest.raises(ValueError, match="tidak memiliki teks"):
        extract_and_chunk_pdf(pdf_path)


def test_extract_and_chunk_pdf_with_snapshots(tmp_path: Path) -> None:
    from app.services.pdf_service import extract_and_chunk_pdf_with_snapshots

    pdf_path = tmp_path / "sample_snapshots.pdf"
    pdf_bytes = make_pdf_bytes(
        [
            "Halaman Pertama dengan teks prosedur.",
            "Halaman Kedua dengan diagram alur pelayanan.",
        ]
    )
    pdf_path.write_bytes(pdf_bytes)

    page_count, chunks, snapshots = extract_and_chunk_pdf_with_snapshots(pdf_path)

    assert page_count == 2
    assert len(chunks) == 2
    assert 1 in snapshots
    assert 2 in snapshots
    # Verify snapshots are valid PNG bytes (starts with PNG signature: \x89PNG\r\n\x1a\n)
    assert snapshots[1].startswith(b"\x89PNG\r\n\x1a\n")
    assert snapshots[2].startswith(b"\x89PNG\r\n\x1a\n")


def test_extract_and_chunk_docx(tmp_path: Path) -> None:
    from app.services.pdf_service import extract_and_chunk_document_with_snapshots
    from tests.conftest import make_docx_bytes

    docx_path = tmp_path / "sample.docx"
    docx_bytes = make_docx_bytes(
        [
            "SOP Operasional Layanan Pelanggan dalam format Word DOCX.",
            "Langkah 1: Menyapa pelanggan dengan ramah dan menanyakan keperluan.",
            "Langkah 2: Melakukan verifikasi data akun dan memberikan solusi.",
        ]
    )
    docx_path.write_bytes(docx_bytes)

    page_count, chunks, snapshots = extract_and_chunk_document_with_snapshots(docx_path)

    assert page_count >= 1
    assert len(chunks) >= 1
    assert "SOP Operasional Layanan Pelanggan" in chunks[0].content
    assert chunks[0].chunk_index == 0
    assert isinstance(snapshots, dict)


def _find_fixture_file(filename: str, fallback_subdir: str) -> Path:
    matches = list(Path("storage/uploads").glob(f"*/*{filename}"))
    if matches:
        return matches[0]
    fallback = Path("/home/remibook/Downloads/TESTING RAG") / fallback_subdir / filename
    if fallback.exists():
        return fallback
    raise FileNotFoundError(f"Fixture file {filename} tidak ditemukan.")


def test_markdown_fidelity_pdf_tables_and_flowchart() -> None:
    from app.services.pdf_service import extract_and_chunk_document_with_snapshots

    upload_file = _find_fixture_file("SOP_Cafe.pdf", "Cafe Document")
    page_count, chunks, snapshots = extract_and_chunk_document_with_snapshots(upload_file)

    assert page_count == 3
    assert len(snapshots) == 3
    assert all(i in snapshots for i in (1, 2, 3))

    # Page 1 contains table with standard markdown grid syntax
    p1_chunks = [c for c in chunks if c.page_number == 1]
    assert len(p1_chunks) >= 1
    p1_content = "\n\n".join(c.content for c in p1_chunks)
    assert (
        "| Waktu | Kegiatan | Penanggung Jawab |" in p1_content
        or "|Waktu|Kegiatan|Penanggung Jawab|" in p1_content
    )
    assert "|---|---|---|" in p1_content or "| --- | --- | --- |" in p1_content
    assert "# Standar Operasional Prosedur (SOP) Cafe" in p1_content
    assert "## 1. Tujuan dan Ruang Lingkup" in p1_content

    # Page 2 contains table with Langkah & Tindakan
    p2_chunks = [c for c in chunks if c.page_number == 2]
    p2_content = "\n\n".join(c.content for c in p2_chunks)
    assert "| Langkah | Tindakan |" in p2_content or "|Langkah|Tindakan|" in p2_content
    assert "|---|---|" in p2_content or "| --- | --- |" in p2_content
    assert "Dengarkan keluhan sampai selesai" in p2_content

    # Page 3 contains flowchart preserving logical order
    p3_chunks = [c for c in chunks if c.page_number == 3]
    p3_content = "\n\n".join(c.content for c in p3_chunks)
    assert "# 9. Diagram Alur Pelayanan Pesanan" in p3_content
    assert "MULAI" in p3_content
    assert "SELESAI" in p3_content
    mulai_idx = p3_content.index("MULAI")
    selesai_idx = p3_content.index("SELESAI")
    assert mulai_idx < selesai_idx


def test_markdown_fidelity_docx_tables_and_styles() -> None:
    from app.services.pdf_service import extract_and_chunk_document_with_snapshots

    docx_file = _find_fixture_file("SOP_Hotel.docx", "Hotel Document")
    page_count, chunks, snapshots = extract_and_chunk_document_with_snapshots(docx_file)

    assert page_count >= 1
    assert len(chunks) >= 1
    assert isinstance(snapshots, dict)
    full_content = "\n\n".join(c.content for c in chunks)

    # Tables formatted with standard Markdown syntax
    assert (
        "| Departemen | Tanggung Jawab Utama | Penanggung Jawab |" in full_content
        or "|Departemen|Tanggung Jawab Utama|Penanggung Jawab|" in full_content
    )
    assert "|---|---|---|" in full_content or "| --- | --- | --- |" in full_content
    assert "| Langkah | Tindakan |" in full_content or "|Langkah|Tindakan|" in full_content

    # Font styles and headings
    assert "Standar Operasional Prosedur (SOP) Hotel" in full_content
    assert "Front Office" in full_content


def test_docx_fallback_ast_markdown() -> None:
    from app.services.pdf_service import _extract_docx_fallback

    docx_file = _find_fixture_file("SOP_Hotel.docx", "Hotel Document")
    page_count, pages, snapshots = _extract_docx_fallback(docx_file)

    assert page_count == 1
    assert len(pages) == 1
    assert isinstance(snapshots, dict)
    page_text = pages[0].text

    assert "| Departemen | Tanggung Jawab Utama | Penanggung Jawab |" in page_text
    assert "| --- | --- | --- |" in page_text
    assert "# Standar Operasional Prosedur (SOP) Hotel" in page_text


def test_table_aware_chunking_preserves_headers() -> None:
    from app.services.pdf_service import PDFPageText, chunk_pdf_pages

    long_table = "| ID | Nama | Posisi |\n|---|---|---|\n" + "\n".join(
        f"| {i} | Pegawai {i} | Jabatan {i} |" for i in range(1, 40)
    )
    page = PDFPageText(page_number=1, text=f"# Header Halaman\n\n{long_table}\n\nFooter halaman.")

    chunks = chunk_pdf_pages([page], chunk_size=300, chunk_overlap=0)
    assert len(chunks) > 1

    table_chunks = [c for c in chunks if "| ID |" in c.content]
    assert len(table_chunks) >= 2
    for tc in table_chunks:
        assert "| ID | Nama | Posisi |\n|---|---|---|" in tc.content
        assert tc.page_number == 1
    for tc in table_chunks[1:]:
        assert tc.content.startswith("| ID | Nama | Posisi |\n|---|---|---|")

    # Sequential chunk indices
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


def test_extract_and_chunk_pptx(tmp_path: Path) -> None:
    from app.services.pdf_service import extract_and_chunk_document_with_snapshots

    pptx_path = tmp_path / "presentation.pptx"
    slides = [
        {
            "title": "Pengenalan AI Agent",
            "bullets": ["Autonomous decision making", "Tool calling integration"],
            "notes": "Jelaskan definisi agen cerdas dan integrasi MCP.",
        },
        {
            "title": "Matriks Perbandingan Model",
            "table": [
                ["Model", "Latency", "Accuracy"],
                ["Claude 3.5 Sonnet", "Fast", "High"],
                ["Gemini 2.0 Flash", "Ultra Fast", "High"],
            ],
            "notes": "Fokus pada trade-off latency vs accuracy.",
        },
    ]
    pptx_path.write_bytes(make_pptx_bytes(slides))

    page_count, chunks, snapshots = extract_and_chunk_document_with_snapshots(
        pptx_path, render_snapshots=True
    )

    assert page_count == 2
    assert len(chunks) >= 2
    assert len(snapshots) >= 1
    assert any(c.page_number == 1 for c in chunks)
    assert any(c.page_number == 2 for c in chunks)

    full_text = " ".join(c.content for c in chunks)
    assert "Pengenalan AI Agent" in full_text
    assert "Matriks Perbandingan Model" in full_text
    assert "Jelaskan definisi agen cerdas" in full_text or "Autonomous decision making" in full_text


def test_pptx_fallback_ast_markdown(tmp_path: Path) -> None:
    from app.services.pdf_service import _extract_pptx_fallback

    pptx_path = tmp_path / "fallback_sample.pptx"
    slides = [
        {
            "title": "Arsitektur Sistem",
            "bullets": ["Frontend: React Vite", "Backend: FastAPI"],
            "notes": "Catatan presenter untuk slide 1.",
        },
        {
            "title": "Tabel Data",
            "table": [
                ["Komponen", "Status"],
                ["PostgreSQL", "Connected"],
                ["pgvector", "Ready"],
            ],
            "notes": "Pastikan ekstensi vector aktif.",
        },
    ]
    pptx_path.write_bytes(make_pptx_bytes(slides))

    page_count, pages, snapshots = _extract_pptx_fallback(pptx_path)

    assert page_count == 2
    assert len(pages) == 2
    assert isinstance(snapshots, dict)

    s1_text = pages[0].text
    assert "# Arsitektur Sistem" in s1_text
    assert "- Frontend: React Vite" in s1_text
    assert "> **Catatan Presenter:**" in s1_text
    assert "Catatan presenter untuk slide 1." in s1_text

    s2_text = pages[1].text
    assert "# Tabel Data" in s2_text
    assert "| Komponen | Status |" in s2_text
    assert "| --- | --- |" in s2_text
    assert "| PostgreSQL | Connected |" in s2_text
    assert "Pastikan ekstensi vector aktif." in s2_text

