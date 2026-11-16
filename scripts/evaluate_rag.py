"""Benchmark komparatif Retrieval RAG MiiRAG pada database testing (miirag_test).

Membandingkan 4 konfigurasi retrieval secara kuantitatif (Hit@K, MRR, NDCG@K, Latency):
1. Dense Only (baseline lama)
2. Hybrid (Dense + PostgreSQL FTS RRF)
3. Hybrid + Cross-Encoder Rerank
4. Hybrid + Rerank + HyDE & Query Expansion
"""

import asyncio
import os
import sys
import uuid
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings as _base_settings

if "/miirag_test" not in _base_settings.DATABASE_URL:
    _test_db_url = _base_settings.DATABASE_URL.rsplit("/", 1)[0] + "/miirag_test"
    os.environ["DATABASE_URL"] = _test_db_url
    _base_settings.DATABASE_URL = _test_db_url

from app.core.database import AsyncSessionLocal
from app.evaluation.rag_eval import EvalCase, evaluate_retrieval_case, summarize_mode_results
from app.models.knowledge import (
    Document,
    DocumentChunk,
    DocumentStatus,
    Knowledge,
    KnowledgeStatus,
    KnowledgeVersion,
    KnowledgeVersionDocument,
)
from app.schemas.query import QueryRequest
from app.services.embedding_service import embedding_service
from app.services.pdf_service import PDFChunk
from app.services.query_service import execute_similarity_query
from app.services.rerank_service import rerank_service

BENCHMARK_CHUNKS = [
    (
        "SOP_Cafe_Operasional.pdf",
        1,
        "Standar Operasional Prosedur Cafe > 1. Pembukaan Kasir",
        (
            "Prosedur pembukaan toko dan kasir dilakukan pukul 07:00 WIB oleh Head Barista. "
            "Pastikan modal laci kasir sebesar Rp 500.000 tersedia dan mesin EDC BCA sudah terhubung ke jaringan WiFi."
        ),
    ),
    (
        "SOP_Cafe_Operasional.pdf",
        2,
        "Standar Operasional Prosedur Cafe > 2. Kode Alat & Sanitasi",
        (
            "| Kode Alat | Nama Peralatan | Frekuensi Pembersihan |\n"
            "|---|---|---|\n"
            "| SOP-ESP-01 | Mesin Espresso La Marzocco | Backflush harian setiap tutup shift |\n"
            "| SOP-GRD-02 | Grinder Mahlkonig EK43 | Sikat burr kering setiap malam |\n"
            "| SOP-CHIL-09 | Chiller Susu Segar | Cek suhu 2°C - 4°C setiap 4 jam |"
        ),
    ),
    (
        "SOP_Cafe_Operasional.pdf",
        3,
        "Standar Operasional Prosedur Cafe > 3. Penanganan Komplain",
        (
            "Jika pelanggan mengeluhkan minuman terlalu pahit atau dingin, barista wajib meminta maaf "
            "dengan tulus dan langsung membuatkan minuman pengganti gratis dalam waktu maksimal 5 menit."
        ),
    ),
    (
        "Kebijakan_SDM_Hotel.docx",
        1,
        "Kebijakan SDM > Cuti dan Kompensasi",
        (
            "Karyawan tetap berhak atas cuti tahunan sebanyak 12 hari kerja setelah melewati masa kerja 1 tahun. "
            "Pengajuan cuti diajukan minimal H-7 melalui sistem HRIS internal kode form HR-CUTI-04."
        ),
    ),
    (
        "Kebijakan_SDM_Hotel.docx",
        2,
        "Kebijakan SDM > Standar Seragam Housekeeping",
        "Petugas housekeeping wajib mengenakan seragam rapi, ID card aktif, dan sarung tangan nitril saat membersihkan kamar mandi tamu.",
    ),
]

EVAL_CASES = [
    EvalCase(
        case_id="exact_code_chiller",
        query="Apa fungsi dan jadwal perawatan untuk kode SOP-CHIL-09?",
        expected_keywords=("SOP-CHIL-09", "Chiller Susu Segar"),
        category="exact_keyword",
    ),
    EvalCase(
        case_id="exact_code_hr",
        query="Kode formulir HR-CUTI-04 untuk pengajuan apa?",
        expected_keywords=("HR-CUTI-04", "cuti tahunan"),
        category="exact_keyword",
    ),
    EvalCase(
        case_id="semantic_espresso",
        query="Kapan harus melakukan pembersihan backflush mesin kopi?",
        expected_keywords=("La Marzocco", "Backflush"),
        category="semantic_table",
    ),
    EvalCase(
        case_id="semantic_complaint",
        query="Bagaimana tindakan staf kalau rasa kopi dikeluhkan pelanggan?",
        expected_keywords=("meminta maaf", "minuman pengganti"),
        category="semantic_conceptual",
    ),
    EvalCase(
        case_id="contextual_section_kasir",
        query="Berapa modal awal kasir saat pembukaan toko?",
        expected_keywords=("Rp 500.000", "07:00"),
        category="contextual_detail",
    ),
]


async def setup_benchmark_corpus() -> uuid.UUID:
    async with AsyncSessionLocal() as session:
        await session.execute(
            text(
                "TRUNCATE TABLE document_chunks, knowledge_version_documents, documents, knowledge_versions, knowledges RESTART IDENTITY CASCADE"
            )
        )
        await session.commit()

        kid = uuid.uuid4()
        ver_id = uuid.uuid4()
        k = Knowledge(id=kid, name="Benchmark Corpus", status=KnowledgeStatus.DONE, current_version=1)
        kv = KnowledgeVersion(
            id=ver_id,
            knowledge_id=kid,
            version_number=1,
            status=KnowledgeStatus.DONE,
            doc_count=2,
        )
        session.add_all([k, kv])
        await session.flush()
        k.active_version_id = ver_id

        docs_by_name: dict[str, Document] = {}
        chunks_objs: list[PDFChunk] = []
        chunk_meta: list[tuple[str, int, str, str]] = []

        for idx, (fname, page_num, sec_title, content) in enumerate(BENCHMARK_CHUNKS):
            if fname not in docs_by_name:
                doc = Document(
                    id=uuid.uuid4(),
                    knowledge_id=kid,
                    filename=fname,
                    file_size=1024,
                    file_hash=f"hash-{len(docs_by_name)}",
                    storage_path=f"/tmp/{fname}",
                    status=DocumentStatus.EMBEDDED,
                    page_count=3,
                    chunk_count=0,
                )
                docs_by_name[fname] = doc
                session.add(doc)
                session.add(KnowledgeVersionDocument(version_id=ver_id, document_id=doc.id))

            c = PDFChunk(
                chunk_index=idx,
                page_number=page_num,
                content=content,
                section_title=sec_title,
            )
            chunks_objs.append(c)
            chunk_meta.append((fname, page_num, sec_title, content))

        await session.flush()

        embed_inputs = [
            c.to_embedding_text(meta[0]) for c, meta in zip(chunks_objs, chunk_meta, strict=True)
        ]
        vectors = await embedding_service.embed_documents(embed_inputs)

        for c, meta, vec in zip(chunks_objs, chunk_meta, vectors, strict=True):
            fname, page_num, sec_title, content = meta
            doc = docs_by_name[fname]
            doc.chunk_count += 1
            session.add(
                DocumentChunk(
                    knowledge_id=kid,
                    document_id=doc.id,
                    chunk_index=c.chunk_index,
                    page_number=page_num,
                    content=content,
                    metadata_json={
                        "filename": fname,
                        "page_number": page_num,
                        "section_title": sec_title,
                        "contextual_header": c.build_contextual_header(fname),
                    },
                    embedding=vec,
                )
            )
        await session.commit()
        return kid


async def run_benchmark() -> None:
    print("Memuat model embedding & reranker...")
    await embedding_service.preload()
    await rerank_service.preload()

    kid = await setup_benchmark_corpus()

    configs: list[tuple[str, dict[str, object]]] = [
        (
            "Dense Only (Baseline)",
            {
                "search_mode": "dense",
                "use_rerank": False,
                "use_hyde": False,
                "use_query_expansion": False,
            },
        ),
        (
            "Hybrid (Dense+FTS RRF)",
            {
                "search_mode": "hybrid",
                "use_rerank": False,
                "use_hyde": False,
                "use_query_expansion": False,
            },
        ),
        (
            "Hybrid + Reranker",
            {
                "search_mode": "hybrid",
                "use_rerank": True,
                "use_hyde": False,
                "use_query_expansion": False,
            },
        ),
        (
            "Hybrid + Rerank + HyDE",
            {
                "search_mode": "hybrid",
                "use_rerank": True,
                "use_hyde": True,
                "use_query_expansion": True,
            },
        ),
    ]

    # Warmup 1 query
    await execute_similarity_query(
        QueryRequest(query="warmup", knowledge_ids=[kid], top_k=3, score_threshold=0.0)
    )

    print("\n=== HASIL BENCHMARK EVALUASI RAG (Top-3) ===")
    print(f"{'Mode':<26} | {'Hit@3':<7} | {'MRR':<7} | {'NDCG@3':<7} | {'Avg Latency':<12}")
    print("-" * 72)

    for label, kwargs in configs:
        results = []
        for case in EVAL_CASES:
            resp = await execute_similarity_query(
                QueryRequest(
                    query=case.query,
                    knowledge_ids=[kid],
                    top_k=3,
                    score_threshold=0.25,
                    **kwargs,
                )
            )
            contents = [r.content for r in resp.results]
            results.append(evaluate_retrieval_case(case, contents, resp.latency_ms, k=3))

        summary = summarize_mode_results(label, results)
        print(
            f"{summary.mode_name:<26} | {summary.hit_rate_at_k:<7.2%} | {summary.mrr:<7.4f} | {summary.ndcg:<7.4f} | {summary.avg_latency_ms:>7.1f} ms"
        )

    # Bersihkan data test
    async with AsyncSessionLocal() as session:
        await session.execute(
            text(
                "TRUNCATE TABLE document_chunks, knowledge_version_documents, documents, knowledge_versions, knowledges RESTART IDENTITY CASCADE"
            )
        )
        await session.commit()


if __name__ == "__main__":
    asyncio.run(run_benchmark())
