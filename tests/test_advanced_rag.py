import math

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.evaluation.rag_eval import (
    EvalCase,
    evaluate_retrieval_case,
    ndcg_at_k,
    reciprocal_rank,
    summarize_mode_results,
)
from app.repositories.query_repo import build_or_tsquery
from app.services.embedding_service import embedding_service
from app.services.pdf_service import PDFPageText, chunk_pdf_pages
from app.services.query_enhancement_service import (
    blend_query_and_hyde_vectors,
    enhance_query,
)
from app.services.rerank_service import rerank_service
from tests.conftest import make_pdf_bytes
from tests.test_knowledge_and_query import _wait_for_done


def test_contextual_chunk_headers_across_pages() -> None:
    pages = [
        PDFPageText(
            page_number=1,
            text="# Panduan Cafe\n\n## 1. Kasir\n\nBuka laci kasir pukul 07:00 WIB.",
        ),
        PDFPageText(
            page_number=2,
            text="| Kode | Alat |\n|---|---|\n| K-01 | Mesin EDC |",
        ),
        PDFPageText(
            page_number=3,
            text="## 2. Sanitasi\n\nBersihkan meja setiap jam.",
        ),
    ]

    chunks = chunk_pdf_pages(pages, chunk_size=500, chunk_overlap=0)
    assert len(chunks) == 3

    assert chunks[0].section_title == "Panduan Cafe > 1. Kasir"
    # Halaman 2 mewarisi heading aktif dari halaman 1
    assert chunks[1].section_title == "Panduan Cafe > 1. Kasir"
    # Konten tabel tetap pure Markdown
    assert chunks[1].content.startswith("| Kode | Alat |")
    header = chunks[1].build_contextual_header("SOP_Cafe.pdf")
    assert header == "Dokumen: SOP_Cafe.pdf | Halaman: 2 | Bagian: Panduan Cafe > 1. Kasir"
    assert chunks[1].to_embedding_text("SOP_Cafe.pdf").startswith(f"[{header}]\n\n| Kode | Alat |")

    # Halaman 3 memperbarui sub-heading level 2 namun menjaga heading level 1
    assert chunks[2].section_title == "Panduan Cafe > 2. Sanitasi"


def test_build_or_tsquery_tokenization() -> None:
    q = build_or_tsquery("Apa prosedur kode SOP-KSR-01 di kasir?")
    assert q == "prosedur | kode | sop | ksr | 01 | kasir"

    assert build_or_tsquery("??? !!!") is None
    assert build_or_tsquery("apa itu") == "apa | itu"


@pytest.mark.asyncio
async def test_query_enhancement_hyde_and_expansion() -> None:
    enhanced = await enhance_query(
        "Bagaimana prosedur SOP kasir?",
        use_hyde=True,
        use_query_expansion=True,
    )
    assert enhanced.enhancement_used == "hyde_heuristic+expansion"
    assert enhanced.hyde_document is not None
    assert "kasir" in enhanced.hyde_document.lower()
    assert "standar" in enhanced.expanded_terms
    assert "operasional" in enhanced.expanded_terms

    v1 = [1.0, 0.0, 0.0]
    v2 = [0.0, 1.0, 0.0]
    blended = blend_query_and_hyde_vectors(v1, v2, hyde_weight=0.65)
    norm = math.sqrt(sum(x * x for x in blended))
    assert math.isclose(norm, 1.0, rel_tol=1e-5)
    assert blended[1] > blended[0]


def test_rag_evaluation_metrics() -> None:
    assert reciprocal_rank([False, True, False]) == 0.5
    assert reciprocal_rank([False, False]) == 0.0
    assert ndcg_at_k([True, False, False], k=3) == 1.0
    assert ndcg_at_k([False, True, False], k=3) < 1.0

    case = EvalCase(case_id="c1", query="cek suhu", expected_keywords=("2°C", "chiller"))
    r1 = evaluate_retrieval_case(case, ["teks lain", "Chiller dijaga pada suhu 2°C"], latency_ms=20, k=3)
    assert r1.hit_at_k is True
    assert r1.rr == 0.5

    summary = summarize_mode_results("hybrid", [r1])
    assert summary.hit_rate_at_k == 1.0
    assert summary.mrr == 0.5
    assert summary.avg_latency_ms == 20.0


@pytest.mark.asyncio
async def test_hybrid_search_rescues_exact_code_and_reranks(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    dim = settings.EMBEDDING_DIMENSIONS

    def _weak_dense_vector(idx: int) -> list[float]:
        vec = [0.0] * dim
        vec[idx] = 1.0
        return vec

    async def fake_embed_documents(texts: list[str], title: str | None = None) -> list[list[float]]:
        out = []
        for t in texts:
            if "SOP-CHIL-09" in t:
                # Simulasikan kegagalan dense vector (ortogonal terhadap query)
                out.append(_weak_dense_vector(5))
            else:
                out.append(_weak_dense_vector(0))
        return out

    async def fake_embed_query(query: str) -> list[float]:
        return _weak_dense_vector(0)

    async def fake_rerank(query: str, documents: list[str]) -> list[float]:
        # Reranker mendeteksi relevansi sebenarnya
        return [0.94 if "SOP-CHIL-09" in d else 0.18 for d in documents]

    monkeypatch.setattr(embedding_service, "embed_documents", fake_embed_documents)
    monkeypatch.setattr(embedding_service, "embed_query", fake_embed_query)
    monkeypatch.setattr(rerank_service, "rerank", fake_rerank)

    pdf_bytes = make_pdf_bytes(
        [
            "Prosedur umum operasional pembukaan toko pagi hari.",
            "Kode Peralatan SOP-CHIL-09 adalah Chiller Susu Segar dengan suhu 2 sampai 4 derajat.",
        ]
    )
    resp = await client.post(
        "/api/v1/knowledges",
        data={"name": "Kode Alat Knowledge", "process_now": "true"},
        files=[("files", ("Kode_Alat.pdf", pdf_bytes, "application/pdf"))],
    )
    assert resp.status_code == 201
    kid = resp.json()["id"]
    await _wait_for_done(client, kid)

    # 1. Dense-only GAGAL menemukan SOP-CHIL-09 karena vector ortogonal (sim = 0.0 < 0.35)
    dense_resp = await client.post(
        "/api/v1/query",
        json={
            "query": "SOP-CHIL-09 chiller",
            "knowledge_ids": [kid],
            "top_k": 3,
            "score_threshold": 0.35,
            "search_mode": "dense",
            "use_rerank": False,
        },
    )
    assert dense_resp.status_code == 200
    assert all("SOP-CHIL-09" not in r["content"] for r in dense_resp.json()["results"])

    # 2. Hybrid + Rerank MENYELAMATKAN SOP-CHIL-09 dan menempatkannya di peringkat #1!
    hybrid_resp = await client.post(
        "/api/v1/query",
        json={
            "query": "SOP-CHIL-09 chiller",
            "knowledge_ids": [kid],
            "top_k": 3,
            "score_threshold": 0.35,
            "search_mode": "hybrid",
            "use_rerank": True,
        },
    )
    assert hybrid_resp.status_code == 200
    hdata = hybrid_resp.json()
    assert hdata["search_mode"] == "hybrid"
    assert hdata["reranked"] is True
    assert hdata["total_results"] >= 1
    assert "SOP-CHIL-09" in hdata["results"][0]["content"]
    assert hdata["results"][0]["rerank_score"] == pytest.approx(0.94)
    assert hdata["results"][0]["keyword_score"] > 0.0

    # 3. Keyword-only mode tidak memanggil embedding query sama sekali
    kw_resp = await client.post(
        "/api/v1/query",
        json={
            "query": "SOP-CHIL-09",
            "knowledge_ids": [kid],
            "top_k": 3,
            "search_mode": "keyword",
            "use_rerank": False,
        },
    )
    assert kw_resp.status_code == 200
    assert "SOP-CHIL-09" in kw_resp.json()["results"][0]["content"]


@pytest.mark.asyncio
async def test_context_window_expansion_and_hyde_api(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    dim = settings.EMBEDDING_DIMENSIONS

    async def fake_embed_documents(texts: list[str], title: str | None = None) -> list[list[float]]:
        vecs = []
        for t in texts:
            v = [0.0] * dim
            v[0 if "BARISTA_TARGET" in t else 1] = 1.0
            vecs.append(v)
        return vecs

    async def fake_embed_query(query: str) -> list[float]:
        v = [0.0] * dim
        v[0] = 1.0
        return v

    async def fake_rerank(query: str, documents: list[str]) -> list[float]:
        return [0.9 if "BARISTA_TARGET" in d else 0.1 for d in documents]

    monkeypatch.setattr(embedding_service, "embed_documents", fake_embed_documents)
    monkeypatch.setattr(embedding_service, "embed_query", fake_embed_query)
    monkeypatch.setattr(rerank_service, "rerank", fake_rerank)

    # Buat 1 halaman panjang yang terpecah menjadi tepat 3 chunks (~600 chars per paragraf)
    long_p1 = "BAGIAN_AWAL_KONTEKS " + ("Pembukaan shift pagi dilakukan oleh supervisor. " * 12)
    long_p2 = "BARISTA_TARGET " + ("Standar ekstraksi espresso adalah 25 detik pada suhu 93C. " * 12)
    long_p3 = "BAGIAN_AKHIR_KONTEKS " + ("Catatan pembersihan portafilter sesudah ekstraksi. " * 12)
    pdf_bytes = make_pdf_bytes([f"{long_p1}\n\n{long_p2}\n\n{long_p3}"])

    resp = await client.post(
        "/api/v1/knowledges",
        data={"name": "Expand Context Knowledge", "process_now": "true"},
        files=[("files", ("Barista.pdf", pdf_bytes, "application/pdf"))],
    )
    assert resp.status_code == 201
    kid = resp.json()["id"]
    await _wait_for_done(client, kid)

    qresp = await client.post(
        "/api/v1/query",
        json={
            "query": "Bagaimana prosedur SOP ekstraksi espresso?",
            "knowledge_ids": [kid],
            "top_k": 1,
            "score_threshold": 0.3,
            "search_mode": "hybrid",
            "use_rerank": True,
            "use_hyde": True,
            "use_query_expansion": True,
            "expand_context": True,
        },
    )
    assert qresp.status_code == 200
    data = qresp.json()
    assert data["enhancement_used"] == "hyde_heuristic+expansion"
    assert data["hyde_document"] is not None
    assert data["total_results"] == 1
    hit = data["results"][0]
    assert "BARISTA_TARGET" in hit["content"]
    assert hit["expanded_content"] is not None
    assert len(hit["expanded_content"]) > len(hit["content"])
    assert "BAGIAN_AWAL_KONTEKS" in hit["expanded_content"] or "BAGIAN_AKHIR_KONTEKS" in hit["expanded_content"]


@pytest.mark.asyncio
async def test_real_cross_encoder_reranker_scores_multilingual() -> None:
    scores = await rerank_service.rerank(
        "Bagaimana cara membersihkan mesin espresso?",
        [
            "Lakukan backflush harian pada group head mesin espresso sebelum tutup shift.",
            "Jadwal cuti tahunan karyawan diajukan minimal tujuh hari sebelumnya.",
        ],
    )
    assert len(scores) == 2
    assert 0.0 < scores[1] < scores[0] < 1.0

