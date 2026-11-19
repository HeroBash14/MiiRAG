import asyncio
import math

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.services import worker_service
from app.services.embedding_service import embedding_service
from tests.conftest import make_pdf_bytes, make_pptx_bytes


def _semantic_mock_vector(text: str) -> list[float]:
    """Menghasilkan vector unit deterministik berdasarkan topik teks untuk uji similarity."""
    dim = settings.EMBEDDING_DIMENSIONS
    vec = [0.0] * dim
    lower = text.lower()
    if "klaim" in lower or "syariah" in lower:
        vec[0] = 1.0
    if "polis" in lower or "kendaraan" in lower:
        vec[1] = 1.0
    if "glosarium" in lower or "istilah" in lower:
        vec[2] = 1.0
    if "presentasi" in lower or "slide" in lower or "agen" in lower:
        vec[0] = 1.0
        vec[1] = 1.0
    if sum(vec) == 0.0:
        vec[3] = 1.0
    norm = math.sqrt(sum(v * v for v in vec))
    return [v / norm for v in vec]


async def _wait_for_done(client: AsyncClient, knowledge_id: str, timeout: float = 15.0) -> dict:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        resp = await client.get(f"/api/v1/knowledges/{knowledge_id}")
        assert resp.status_code == 200
        data = resp.json()
        if data["status"] == "done":
            return data
        await asyncio.sleep(0.05)
    raise AssertionError("Knowledge tidak selesai di-embed dalam batas waktu.")


@pytest.mark.asyncio
async def test_full_knowledge_lifecycle_renew_and_query(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    embedded_calls: list[list[str]] = []

    async def fake_embed_documents(texts: list[str], title: str | None = None) -> list[list[float]]:
        embedded_calls.append(list(texts))
        return [_semantic_mock_vector(t) for t in texts]

    async def fake_embed_query(query: str) -> list[float]:
        return _semantic_mock_vector(query)

    monkeypatch.setattr(embedding_service, "embed_documents", fake_embed_documents)
    monkeypatch.setattr(embedding_service, "embed_query", fake_embed_query)

    # 1. Buat draft knowledge (unfinished)
    pdf_klaim = make_pdf_bytes(["Prosedur pengajuan klaim asuransi syariah dan syarat dokumen."])
    pdf_polis = make_pdf_bytes(["Polis kendaraan bermotor dan perlindungan kecelakaan."])

    resp = await client.post(
        "/api/v1/knowledges",
        data={"name": "SOP Klaim", "description": "Panduan klaim", "process_now": "false"},
        files=[
            ("files", ("SOP-Klaim.pdf", pdf_klaim, "application/pdf")),
            ("files", ("Polis-Kendaraan.pdf", pdf_polis, "application/pdf")),
        ],
    )
    assert resp.status_code == 201
    draft = resp.json()
    kid = draft["id"]
    assert draft["status"] == "unfinished"
    assert draft["current_version"] == 1
    assert draft["doc_count"] == 2
    assert draft["version_history"] == []

    # 2. Edit draft: pertahankan 1 dokumen (SOP-Klaim.pdf) dan ganti dokumen kedua
    kept_doc_id = draft["documents"][0]["id"]
    pdf_glosarium = make_pdf_bytes(["Glosarium istilah umum asuransi takaful."])
    resp = await client.patch(
        f"/api/v1/knowledges/{kid}",
        data={"name": "SOP Klaim Syariah", "keep_document_ids": [kept_doc_id]},
        files=[("files", ("Glosarium.pdf", pdf_glosarium, "application/pdf"))],
    )
    assert resp.status_code == 200
    edited = resp.json()
    assert edited["name"] == "SOP Klaim Syariah"
    assert [d["filename"] for d in edited["documents"]] == ["SOP-Klaim.pdf", "Glosarium.pdf"]

    # 3. Mulai proses embedding
    resp = await client.post(f"/api/v1/knowledges/{kid}/process")
    assert resp.status_code == 200
    done_v1 = await _wait_for_done(client, kid)
    assert done_v1["current_version"] == 1
    assert done_v1["embedded_doc_count"] == 2
    assert len(done_v1["version_history"]) == 1
    assert done_v1["version_history"][0]["is_active"] is True
    assert len(embedded_calls) == 2

    # 4. Query similarity tanpa LLM
    resp = await client.post(
        "/api/v1/query",
        json={"query": "syarat pengajuan klaim syariah", "top_k": 3, "score_threshold": 0.5},
    )
    assert resp.status_code == 200
    qdata = resp.json()
    assert qdata["total_results"] >= 1
    top_hit = qdata["results"][0]
    assert top_hit["filename"] == "SOP-Klaim.pdf"
    assert top_hit["version"] == 1
    assert top_hit["page_number"] == 1
    assert top_hit["similarity_score"] >= 0.99
    assert "page_image_url" in top_hit
    assert top_hit["page_image_url"] is not None
    assert f"page_{top_hit['page_number']}.png" in top_hit["page_image_url"]
    assert "X-Amz-Signature=" in top_hit["page_image_url"]

    # 5. Re-new ke v2: pertahankan SOP-Klaim.pdf (tidak di-embed ulang) + tambah Polis-Kendaraan.pdf
    calls_before_renew = len(embedded_calls)
    sop_doc_id = done_v1["documents"][0]["id"]
    resp = await client.post(
        f"/api/v1/knowledges/{kid}/renew",
        data={"note": "Tambah polis kendaraan", "keep_document_ids": [sop_doc_id]},
        files=[("files", ("Polis-Kendaraan.pdf", pdf_polis, "application/pdf"))],
    )
    assert resp.status_code == 200
    done_v2 = await _wait_for_done(client, kid)
    assert done_v2["current_version"] == 2
    assert [d["filename"] for d in done_v2["documents"]] == [
        "SOP-Klaim.pdf",
        "Polis-Kendaraan.pdf",
    ]
    # Hanya 1 dokumen baru yang di-embed (dokumen lama tidak di-embed ulang!)
    assert len(embedded_calls) == calls_before_renew + 1
    assert done_v2["version_history"][0]["version_number"] == 2
    assert done_v2["version_history"][0]["is_active"] is True
    assert done_v2["version_history"][1]["is_active"] is False

    # 6. Verifikasi dokumen yang dihapus (Glosarium.pdf) tidak muncul di hasil query v2
    resp = await client.post(
        "/api/v1/query",
        json={"query": "glosarium istilah", "top_k": 5, "score_threshold": 0.5},
    )
    assert resp.status_code == 200
    assert resp.json()["total_results"] == 0

    # Query dokumen baru di v2 berhasil ditemukan dengan version=2
    resp = await client.post(
        "/api/v1/query",
        json={"query": "polis kendaraan", "top_k": 5, "score_threshold": 0.5},
    )
    assert resp.status_code == 200
    assert resp.json()["results"][0]["filename"] == "Polis-Kendaraan.pdf"
    assert resp.json()["results"][0]["version"] == 2

    # 7. Re-new ke v3 hanya menghapus Polis-Kendaraan.pdf -> langsung done tanpa background embed
    resp = await client.post(
        f"/api/v1/knowledges/{kid}/renew",
        data={"note": "Hapus polis kendaraan", "keep_document_ids": [sop_doc_id]},
    )
    assert resp.status_code == 200
    done_v3 = resp.json()
    assert done_v3["status"] == "done"
    assert done_v3["current_version"] == 3
    assert len(embedded_calls) == calls_before_renew + 1

    # 8. List & Filter + Counts
    resp = await client.get("/api/v1/knowledges", params={"q": "Syariah", "status": "done"})
    assert resp.status_code == 200
    listing = resp.json()
    assert listing["counts"] == {"all": 1, "unfinished": 0, "processing": 0, "done": 1}
    assert len(listing["items"]) == 1
    assert listing["items"][0]["current_version"] == 3

    # 9. Hapus knowledge
    resp = await client.delete(f"/api/v1/knowledges/{kid}")
    assert resp.status_code == 204
    resp = await client.get(f"/api/v1/knowledges/{kid}")
    assert resp.status_code == 404

    # Pastikan semua task background selesai
    if worker_service._background_tasks:
        await asyncio.gather(*list(worker_service._background_tasks))


@pytest.mark.asyncio
async def test_upload_non_pdf_rejected(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/knowledges",
        data={"name": "Invalid File", "process_now": "false"},
        files=[("files", ("notes.txt", b"bukan pdf", "text/plain"))],
    )
    assert resp.status_code == 400
    assert "PDF" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_health_and_query_filter_by_knowledge_ids(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.embedding_service import normalize_l2

    norm_vec = normalize_l2([3.0, 4.0, 0.0])
    assert math.isclose(math.sqrt(sum(x * x for x in norm_vec)), 1.0, rel_tol=1e-5)

    health = await client.get("/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok", "pgvector": "ready"}

    async def fake_embed_documents(texts: list[str], title: str | None = None) -> list[list[float]]:
        return [_semantic_mock_vector(t) for t in texts]

    async def fake_embed_query(query: str) -> list[float]:
        return _semantic_mock_vector(query)

    monkeypatch.setattr(embedding_service, "embed_documents", fake_embed_documents)
    monkeypatch.setattr(embedding_service, "embed_query", fake_embed_query)

    pdf_a = make_pdf_bytes(["Panduan klaim syariah perusahaan A."])
    pdf_b = make_pdf_bytes(["Panduan klaim syariah perusahaan B."])

    resp_a = await client.post(
        "/api/v1/knowledges",
        data={"name": "Knowledge A", "process_now": "true"},
        files=[("files", ("A.pdf", pdf_a, "application/pdf"))],
    )
    resp_b = await client.post(
        "/api/v1/knowledges",
        data={"name": "Knowledge B", "process_now": "true"},
        files=[("files", ("B.pdf", pdf_b, "application/pdf"))],
    )
    assert resp_a.status_code == 201
    assert resp_b.status_code == 201
    kid_a = resp_a.json()["id"]
    kid_b = resp_b.json()["id"]

    await _wait_for_done(client, kid_a)
    await _wait_for_done(client, kid_b)

    filtered = await client.post(
        "/api/v1/query",
        json={"query": "klaim syariah", "knowledge_ids": [kid_b], "top_k": 5, "score_threshold": 0.5},
    )
    assert filtered.status_code == 200
    items = filtered.json()["results"]
    assert len(items) == 1
    assert items[0]["knowledge_id"] == kid_b
    assert items[0]["filename"] == "B.pdf"


@pytest.mark.asyncio
async def test_upload_and_query_docx(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.conftest import make_docx_bytes

    async def fake_embed_documents(texts: list[str], title: str | None = None) -> list[list[float]]:
        return [_semantic_mock_vector(t) for t in texts]

    async def fake_embed_query(query: str) -> list[float]:
        return _semantic_mock_vector(query)

    monkeypatch.setattr(embedding_service, "embed_documents", fake_embed_documents)
    monkeypatch.setattr(embedding_service, "embed_query", fake_embed_query)

    docx_data = make_docx_bytes(
        [
            "Prosedur Operasional Standar Layanan Pelanggan.",
            "Semua staf wajib menyapa pelanggan dengan sopan dan ramah.",
        ]
    )

    resp = await client.post(
        "/api/v1/knowledges",
        data={"name": "SOP Word DOCX", "process_now": "true"},
        files=[
            (
                "files",
                (
                    "SOP-Layanan.docx",
                    docx_data,
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                ),
            )
        ],
    )
    assert resp.status_code == 201
    kid = resp.json()["id"]

    done_info = await _wait_for_done(client, kid)
    assert done_info["status"] == "done"
    assert done_info["embedded_doc_count"] == 1
    assert done_info["documents"][0]["filename"] == "SOP-Layanan.docx"

    # Query similarity
    qresp = await client.post(
        "/api/v1/query",
        json={"query": "staf wajib menyapa pelanggan", "knowledge_ids": [kid], "top_k": 3, "score_threshold": 0.5},
    )
    assert qresp.status_code == 200
    qdata = qresp.json()
    assert qdata["total_results"] >= 1
    assert qdata["results"][0]["filename"] == "SOP-Layanan.docx"
    assert "page_image_url" in qdata["results"][0]


@pytest.mark.asyncio
async def test_query_returns_markdown_table_and_valid_snapshot_url(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pathlib import Path

    async def fake_embed_documents(texts: list[str], title: str | None = None) -> list[list[float]]:
        return [_semantic_mock_vector(t) for t in texts]

    async def fake_embed_query(query: str) -> list[float]:
        return _semantic_mock_vector(query)

    monkeypatch.setattr(embedding_service, "embed_documents", fake_embed_documents)
    monkeypatch.setattr(embedding_service, "embed_query", fake_embed_query)

    matches = list(Path("storage/uploads").glob("*/*SOP_Cafe.pdf"))
    if matches:
        pdf_file = matches[0]
    else:
        pdf_file = Path("/home/remibook/Downloads/TESTING RAG/Cafe Document/SOP_Cafe.pdf")
    pdf_bytes = pdf_file.read_bytes()

    resp = await client.post(
        "/api/v1/knowledges",
        data={"name": "SOP Cafe Knowledge", "process_now": "true"},
        files=[("files", ("SOP_Cafe.pdf", pdf_bytes, "application/pdf"))],
    )
    assert resp.status_code == 201
    kid = resp.json()["id"]

    done_info = await _wait_for_done(client, kid, timeout=10.0)
    assert done_info["status"] == "done"

    qresp = await client.post(
        "/api/v1/query",
        json={"query": "prosedur cafe operasional", "knowledge_ids": [kid], "top_k": 5, "score_threshold": 0.0},
    )
    assert qresp.status_code == 200
    qdata = qresp.json()
    assert qdata["total_results"] >= 1

    found_table = False
    for hit in qdata["results"]:
        assert hit["page_number"] in (1, 2, 3)
        assert hit["page_image_url"] is not None
        assert f"page_{hit['page_number']}.png" in hit["page_image_url"]
        assert hit["similarity_score"] >= 0.0
        if "| Waktu | Kegiatan" in hit["content"] or "| Langkah | Tindakan" in hit["content"] or "|Waktu|Kegiatan" in hit["content"]:
            found_table = True

    assert found_table, "Hasil query harus memuat tabel Markdown valid."


@pytest.mark.asyncio
async def test_upload_and_query_pptx(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_embed_documents(texts: list[str], title: str | None = None) -> list[list[float]]:
        return [_semantic_mock_vector(t) for t in texts]

    async def fake_embed_query(query: str) -> list[float]:
        return _semantic_mock_vector(query)

    monkeypatch.setattr(embedding_service, "embed_documents", fake_embed_documents)
    monkeypatch.setattr(embedding_service, "embed_query", fake_embed_query)

    pptx_bytes = make_pptx_bytes(
        [
            {
                "title": "Presentasi Arsitektur Agen Cerdas",
                "bullets": ["Komponen LLM", "Tool Calling MCP", "Vector Database pgvector"],
                "notes": "Penjelasan detail arsitektur presentasi agen cerdas.",
            },
            {
                "title": "Tabel Evaluasi Presentasi",
                "table": [
                    ["Format", "Dukungan"],
                    ["PDF", "Yes"],
                    ["DOCX", "Yes"],
                    ["PPTX", "Yes"],
                ],
                "notes": "Semua format dokumen kini didukung penuh.",
            },
        ]
    )

    resp = await client.post(
        "/api/v1/knowledges",
        data={"name": "Presentasi Agen", "process_now": "true"},
        files=[(
            "files",
            (
                "arsitektur_agen.pptx",
                pptx_bytes,
                "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            ),
        )],
    )
    assert resp.status_code == 201
    kid = resp.json()["id"]

    done_info = await _wait_for_done(client, kid, timeout=15.0)
    assert done_info["status"] == "done"

    qresp = await client.post(
        "/api/v1/query",
        json={"query": "presentasi agen cerdas", "knowledge_ids": [kid], "top_k": 3, "score_threshold": 0.0},
    )
    assert qresp.status_code == 200
    qdata = qresp.json()
    assert qdata["total_results"] >= 1
    assert qdata["results"][0]["filename"] == "arsitektur_agen.pptx"
    assert qdata["results"][0]["page_number"] in (1, 2)
    assert qdata["results"][0]["page_image_url"] is not None

