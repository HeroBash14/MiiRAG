import io
import math
import uuid

import numpy as np
import openpyxl
import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.services.embedding_service import embedding_service
from app.services.graph_builder_service import (
    _ChunkRecord,
    _extract_candidates_from_chunks,
)
from app.services.rerank_service import rerank_service
from tests.conftest import make_pdf_bytes
from tests.test_knowledge_and_query import _wait_for_done


def _make_xlsx_bytes(sheets: dict[str, list[list[object]]]) -> bytes:
    wb = openpyxl.Workbook()
    first = True
    for name, rows in sheets.items():
        ws = wb.active if first else wb.create_sheet(title=name)
        if first:
            ws.title = name
            first = False
        for row in rows:
            ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_zero_llm_entity_extraction_and_spreadsheet_anti_explosion() -> None:
    """Memastikan ekstraksi kode SOP/Pasal, mention file, konsep lintas dokumen, dan filter angka Excel bekerja bersih."""
    d1 = uuid.uuid4()
    d2 = uuid.uuid4()
    d3 = uuid.uuid4()
    vec = np.zeros(settings.EMBEDDING_DIMENSIONS, dtype=np.float32)
    vec[0] = 1.0

    chunks = [
        _ChunkRecord(
            chunk_id=1,
            document_id=d1,
            filename="SOP_Cafe.pdf",
            page_number=1,
            chunk_index=0,
            content=(
                "Prosedur kode SOP-CHIL-09 wajib dijalankan oleh Head Barista "
                "untuk sanitasi Mesin Espresso setiap penutupan sesuai Pasal 12."
            ),
            section_title="Sanitasi Mesin Espresso",
            search_text=None,
            embedding=vec,
            is_spreadsheet=False,
        ),
        _ChunkRecord(
            chunk_id=2,
            document_id=d2,
            filename="Checklist_Harian_Cafe.pdf",
            page_number=1,
            chunk_index=0,
            content=(
                "Mengacu pada SOP Cafe, Head Barista wajib memeriksa suhu Chiller "
                "berkode SOP-CHIL-09 dan membersihkan Mesin Espresso."
            ),
            section_title="Checklist Penutupan",
            search_text=None,
            embedding=vec,
            is_spreadsheet=False,
        ),
        _ChunkRecord(
            chunk_id=3,
            document_id=d3,
            filename="Kelola_Cafe.xlsx",
            page_number=1,
            chunk_index=0,
            content=(
                "| Tanggal | Peralatan | Penanggung Jawab | Biaya |\n"
                "|---|---|---|---|\n"
                "| 2026-01-15 | Mesin Espresso | Head Barista | Rp 250.000 |\n"
                "| 2026-01-16 | Chiller | Kasir | Rp 120.000 |"
            ),
            section_title="Sheet: Maintenance",
            search_text=None,
            embedding=vec,
            is_spreadsheet=True,
        ),
    ]
    doc_filenames = {
        d1: "SOP_Cafe.pdf",
        d2: "Checklist_Harian_Cafe.pdf",
        d3: "Kelola_Cafe.xlsx",
    }

    candidates, doc_mentions = _extract_candidates_from_chunks(chunks, doc_filenames)

    # 1. Kode referensi terstruktur & formal terekstrak
    assert "ref:SOP-CHIL-09" in candidates
    assert candidates["ref:SOP-CHIL-09"].doc_ids == {d1, d2}
    assert any(k.startswith("ref:PASAL 12") for k in candidates)

    # 2. Mention eksplisit nama dokumen lain ("SOP Cafe") terdeteksi dari Checklist -> SOP_Cafe
    assert any(src == d2 and tgt == d1 for src, tgt, _, _ in doc_mentions)

    # 3. Konsep lintas 3 dokumen terekstrak (Head Barista & Mesin Espresso)
    assert "concept:head barista" in candidates
    assert candidates["concept:head barista"].doc_ids == {d1, d2, d3}
    assert "concept:mesin espresso" in candidates
    assert candidates["concept:mesin espresso"].doc_ids == {d1, d2, d3}

    # 4. Angka / tanggal / mata uang Excel TIDAK menjadi entitas sampah
    for key in candidates:
        assert "250.000" not in key
        assert "2026-01-15" not in key
        assert "120.000" not in key


@pytest.mark.asyncio
async def test_graph_lifecycle_api_rebuild_node_detail_and_version_sync(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Menguji pembuatan otomatis KG, API GET/rebuild/node-detail, serta sinkronisasi saat re-new versi."""
    dim = settings.EMBEDDING_DIMENSIONS

    def _topic_vec(text: str) -> list[float]:
        vec = [0.0] * dim
        low = text.lower()
        if "espresso" in low or "barista" in low or "sop-chil-09" in low:
            vec[0] = 1.0
        if "kasir" in low or "laporan" in low:
            vec[1] = 1.0
        if sum(vec) == 0.0:
            vec[2] = 1.0
        norm = math.sqrt(sum(v * v for v in vec))
        return [v / norm for v in vec]

    async def fake_embed_documents(texts: list[str], title: str | None = None) -> list[list[float]]:
        return [_topic_vec(t) for t in texts]

    async def fake_embed_query(query: str) -> list[float]:
        return _topic_vec(query)

    monkeypatch.setattr(embedding_service, "embed_documents", fake_embed_documents)
    monkeypatch.setattr(embedding_service, "embed_query", fake_embed_query)

    pdf_sop = make_pdf_bytes(
        [
            "Prosedur SOP-CHIL-09 mengatur sanitasi Mesin Espresso oleh Head Barista sebelum toko tutup."
        ]
    )
    pdf_check = make_pdf_bytes(
        [
            "Checklist Harian: Mengacu pada SOP Cafe, Head Barista wajib cek SOP-CHIL-09 dan Mesin Espresso."
        ]
    )
    pdf_org = make_pdf_bytes(
        [
            "Struktur Organisasi: Head Barista bertanggung jawab atas kualitas Mesin Espresso dan supervisi Kasir."
        ]
    )

    resp = await client.post(
        "/api/v1/knowledges",
        data={"name": "Cafe Jeremi Test", "process_now": "true"},
        files=[
            ("files", ("SOP_Cafe.pdf", pdf_sop, "application/pdf")),
            ("files", ("Checklist_Harian_Cafe.pdf", pdf_check, "application/pdf")),
            ("files", ("Struktur_Organisasi.pdf", pdf_org, "application/pdf")),
        ],
    )
    assert resp.status_code == 201
    kid = resp.json()["id"]
    detail_v1 = await _wait_for_done(client, kid)

    # 1. GET /graph otomatis sudah ready setelah embedding selesai
    g_resp = await client.get(f"/api/v1/knowledges/{kid}/graph")
    assert g_resp.status_code == 200
    gdata = g_resp.json()
    assert gdata["status"] == "ready"
    assert gdata["version_number"] == 1
    assert gdata["stats"]["document_nodes"] == 3
    assert gdata["stats"]["cross_document_edges"] >= 1
    assert gdata["stats"]["semantic_bridge_edges"] >= 1

    labels = {n["label"].lower(): n for n in gdata["nodes"]}
    assert "sop-chil-09" in labels
    assert "head barista" in labels
    hub_node = labels["head barista"]
    assert hub_node["doc_frequency"] == 3

    # 2. GET /graph/nodes/{node_id} mengembalikan tetangga & cuplikan chunk asli lintas dokumen
    nd_resp = await client.get(f"/api/v1/knowledges/{kid}/graph/nodes/{hub_node['id']}")
    assert nd_resp.status_code == 200
    nd = nd_resp.json()
    assert nd["node"]["label"].lower() == "head barista"
    assert len(nd["neighbors"]) >= 3
    chunk_files = {c["filename"] for c in nd["chunks"]}
    assert chunk_files == {"SOP_Cafe.pdf", "Checklist_Harian_Cafe.pdf", "Struktur_Organisasi.pdf"}

    # 3. POST /graph/rebuild bekerja idempoten
    rb_resp = await client.post(f"/api/v1/knowledges/{kid}/graph/rebuild")
    assert rb_resp.status_code == 200
    assert rb_resp.json()["stats"]["document_nodes"] == 3

    # 4. Re-new v2 (hapus 1 file tanpa upload baru) -> graf v2 otomatis tersinkronisasi jadi 2 dokumen
    keep_ids = [d["id"] for d in detail_v1["documents"][:2]]
    renew_resp = await client.post(
        f"/api/v1/knowledges/{kid}/renew",
        data={"note": "Hapus struktur organisasi", "keep_document_ids": keep_ids},
    )
    assert renew_resp.status_code == 200
    g_v2 = (await client.get(f"/api/v1/knowledges/{kid}/graph")).json()
    assert g_v2["version_number"] == 2
    assert g_v2["stats"]["document_nodes"] == 2


@pytest.mark.asyncio
async def test_graph_expanded_retrieval_rescues_cross_document_context(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Membuktikan use_graph=True mampu menyelamatkan chunk lintas dokumen yang terlewat oleh pencarian biasa."""
    dim = settings.EMBEDDING_DIMENSIONS

    def _vec(idx: int) -> list[float]:
        v = [0.0] * dim
        v[idx] = 1.0
        return v

    async def fake_embed_documents(texts: list[str], title: str | None = None) -> list[list[float]]:
        out = []
        for t in texts:
            if "SOP-CHIL-09" in t:
                out.append(_vec(0))
            else:
                # Dokumen Struktur Organisasi dibuat ortogonal terhadap query agar pencarian dense awal melewatkannya
                out.append(_vec(9))
        return out

    async def fake_embed_query(query: str) -> list[float]:
        return _vec(0)

    async def fake_rerank(query: str, documents: list[str]) -> list[float]:
        # Cross-Encoder mengenali kedua dokumen relevan menjawab pertanyaan tentang penanggung jawab SOP-CHIL-09
        return [0.92 if "SOP-CHIL-09" in d else 0.78 if "Budi Santoso" in d else 0.1 for d in documents]

    monkeypatch.setattr(embedding_service, "embed_documents", fake_embed_documents)
    monkeypatch.setattr(embedding_service, "embed_query", fake_embed_query)
    monkeypatch.setattr(rerank_service, "rerank", fake_rerank)

    pdf_sop = make_pdf_bytes(
        [
            "Prosedur SOP-CHIL-09 dijalankan setiap malam oleh Head Barista untuk membersihkan chiller."
        ]
    )
    pdf_org = make_pdf_bytes(
        [
            "Jabatan Head Barista saat ini dijabat oleh Budi Santoso dengan wewenang penuh operasional bar."
        ]
    )

    resp = await client.post(
        "/api/v1/knowledges",
        data={"name": "Multi-Hop Cafe", "process_now": "true"},
        files=[
            ("files", ("SOP_Chiller.pdf", pdf_sop, "application/pdf")),
            ("files", ("Struktur_Tim.pdf", pdf_org, "application/pdf")),
        ],
    )
    assert resp.status_code == 201
    kid = resp.json()["id"]
    await _wait_for_done(client, kid)

    # Tanpa Knowledge Graph (dense): hanya menemukan SOP_Chiller.pdf, melewatkan siapa Head Barista di Struktur_Tim.pdf
    no_graph_resp = await client.post(
        "/api/v1/query",
        json={
            "query": "Siapa yang menjalankan SOP-CHIL-09?",
            "knowledge_ids": [kid],
            "top_k": 5,
            "score_threshold": 0.4,
            "search_mode": "dense",
            "use_rerank": True,
            "use_graph": False,
        },
    )
    assert no_graph_resp.status_code == 200
    no_graph_files = [r["filename"] for r in no_graph_resp.json()["results"]]
    assert no_graph_files == ["SOP_Chiller.pdf"]

    # Dengan Knowledge Graph (use_graph=True): melompat via node 'Head Barista' -> menarik Struktur_Tim.pdf!
    with_graph_resp = await client.post(
        "/api/v1/query",
        json={
            "query": "Siapa yang menjalankan SOP-CHIL-09?",
            "knowledge_ids": [kid],
            "top_k": 5,
            "score_threshold": 0.4,
            "search_mode": "dense",
            "use_rerank": True,
            "use_graph": True,
        },
    )
    assert with_graph_resp.status_code == 200
    gdata = with_graph_resp.json()
    assert gdata["graph_used"] is True
    by_file = {r["filename"]: r for r in gdata["results"]}
    assert "SOP_Chiller.pdf" in by_file
    assert "Struktur_Tim.pdf" in by_file
    assert by_file["Struktur_Tim.pdf"]["via_graph"] is True
    assert by_file["Struktur_Tim.pdf"]["graph_reason"] is not None
    assert "Head Barista" in by_file["Struktur_Tim.pdf"]["graph_reason"]


@pytest.mark.asyncio
async def test_real_bge_m3_semantic_bridge_and_alias_merging_end_to_end(
    client: AsyncClient,
) -> None:
    """Uji end-to-end dengan model lokal BAAI/bge-m3 ASLI (Zero-LLM) untuk jembatan makna lintas PDF + Excel."""
    pdf_sop = make_pdf_bytes(
        [
            (
                "Standar Operasional Prosedur Mesin Espresso: Head Barista wajib melakukan backflush, "
                "kalibrasi tekanan 9 bar, dan sanitasi steam wand setiap malam sebelum penutupan cafe."
            )
        ]
    )
    pdf_check = make_pdf_bytes(
        [
            (
                "Daftar Periksa Penutupan Malam: Kepala Barista memastikan pembersihan mesin kopi espresso, "
                "pembilasan group head, dan pencucian pipa uap susu sudah tuntas sebelum pulang."
            )
        ]
    )
    xlsx_data = _make_xlsx_bytes(
        {
            "Jadwal_Shift": [
                ["Jabatan", "Shift", "Tanggung Jawab"],
                ["Head Barista", "Pagi", "Kalibrasi Mesin Espresso & QC Kopi"],
                ["Kasir", "Sore", "Rekap Laporan Harian & Modal Kasir"],
            ]
        }
    )

    resp = await client.post(
        "/api/v1/knowledges",
        data={"name": "Real BGE-M3 Cafe Graph", "process_now": "true"},
        files=[
            ("files", ("SOP_Espresso.pdf", pdf_sop, "application/pdf")),
            ("files", ("Checklist_Malam.pdf", pdf_check, "application/pdf")),
            (
                "files",
                (
                    "Kelola_Cafe.xlsx",
                    xlsx_data,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                ),
            ),
        ],
    )
    assert resp.status_code == 201
    kid = resp.json()["id"]
    await _wait_for_done(client, kid, timeout=60.0)

    graph = (await client.get(f"/api/v1/knowledges/{kid}/graph")).json()
    assert graph["status"] == "ready"
    assert graph["stats"]["document_nodes"] == 3
    # BAAI/bge-m3 menemukan jembatan semantik antara SOP_Espresso.pdf & Checklist_Malam.pdf meski kata berbeda!
    assert graph["stats"]["semantic_bridge_edges"] >= 1
    assert graph["stats"]["cross_document_edges"] >= 2

    # Cek bahwa konsep lintas dokumen atau semantic alias merging berhasil terbentuk
    sem_edges = [e for e in graph["edges"] if e["edge_type"] == "semantic_bridge"]
    assert max(e["weight"] for e in sem_edges) >= settings.KG_SEMANTIC_EDGE_THRESHOLD

    # Uji query dengan use_graph=True memakai model BAAI/bge-m3 + Cross-Encoder asli
    q_resp = await client.post(
        "/api/v1/query",
        json={
            "query": "Apa tugas Head Barista saat penutupan mesin kopi malam hari?",
            "knowledge_ids": [kid],
            "top_k": 5,
            "score_threshold": 0.35,
            "search_mode": "hybrid",
            "use_rerank": True,
            "use_graph": True,
        },
    )
    assert q_resp.status_code == 200
    qdata = q_resp.json()
    assert qdata["graph_used"] is True
    assert qdata["total_results"] >= 2
    returned_files = {r["filename"] for r in qdata["results"]}
    assert "SOP_Espresso.pdf" in returned_files
    assert "Checklist_Malam.pdf" in returned_files


def test_graph_diversification_prevents_single_document_monopolization() -> None:
    """Memastikan dokumen dominan tidak memonopoli 100% Top-K saat dokumen lain terhubung lewat Knowledge Graph."""
    from app.repositories.query_repo import SimilarChunkRow
    from app.services.query_service import _select_with_graph_diversification

    kid = uuid.uuid4()
    doc_a = uuid.uuid4()
    doc_b = uuid.uuid4()
    doc_c = uuid.uuid4()

    # 8 chunk dari dokumen dominan A + 2 chunk lintas dokumen B & C di posisi bawah
    cands = [
        SimilarChunkRow(
            chunk_id=i + 1,
            knowledge_id=kid,
            knowledge_name="PT Besmart",
            version=1,
            document_id=doc_a,
            filename="Security.pdf",
            page_number=i + 1,
            chunk_index=i,
            content=f"Slide keamanan {i}",
            similarity_score=0.55 - i * 0.01,
            rerank_score=0.18 if i < 2 else 0.006 - i * 0.0005,
        )
        for i in range(8)
    ]
    cands.append(
        SimilarChunkRow(
            chunk_id=101,
            knowledge_id=kid,
            knowledge_name="PT Besmart",
            version=1,
            document_id=doc_b,
            filename="HR_Regulation.pdf",
            page_number=4,
            chunk_index=3,
            content="Disiplin dan kepatuhan karyawan",
            similarity_score=0.57,
            rerank_score=0.002,
            via_graph=False,
            graph_reason="Terhubung via konsep 'Karyawan' di Knowledge Graph",
            graph_score=0.88,
        )
    )
    cands.append(
        SimilarChunkRow(
            chunk_id=102,
            knowledge_id=kid,
            knowledge_name="PT Besmart",
            version=1,
            document_id=doc_c,
            filename="ISO_9001.pdf",
            page_number=15,
            chunk_index=14,
            content="Kebijakan mutu layanan efektif dan aman",
            similarity_score=0.47,
            rerank_score=0.0018,
            via_graph=True,
            graph_reason="Terhubung via konsep 'Keamanan' di Knowledge Graph",
            graph_score=0.85,
        )
    )

    # Tanpa Knowledge Graph: semua 6 slot dimonopoli Security.pdf
    no_graph = _select_with_graph_diversification(cands, top_k=6, use_graph=False, score_threshold=0.35)
    assert all(r.filename == "Security.pdf" for r in no_graph)

    # Dengan Knowledge Graph: 4 teratas Security.pdf tetap utuh + HR_Regulation & ISO_9001 ikut terangkat via_graph=True!
    with_graph = _select_with_graph_diversification(cands, top_k=6, use_graph=True, score_threshold=0.35)
    assert len(with_graph) == 6
    assert [r.chunk_id for r in with_graph[:4]] == [1, 2, 3, 4]
    promoted_files = {r.filename for r in with_graph[4:]}
    assert promoted_files == {"HR_Regulation.pdf", "ISO_9001.pdf"}
    assert all(r.via_graph is True for r in with_graph[4:])
