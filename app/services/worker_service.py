import asyncio
import logging
import uuid

from sqlalchemy import delete, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.knowledge import (
    Document,
    DocumentChunk,
    DocumentStatus,
    Knowledge,
    KnowledgeStatus,
    KnowledgeVersion,
    KnowledgeVersionDocument,
    utc_now,
)
from app.services.embedding_service import embedding_service
from app.services.minio_service import minio_service
from app.services.pdf_service import extract_and_chunk_document_with_snapshots

logger = logging.getLogger(__name__)

_knowledge_locks: dict[uuid.UUID, asyncio.Lock] = {}
_background_tasks: set[asyncio.Task] = set()


def _get_lock(knowledge_id: uuid.UUID) -> asyncio.Lock:
    lock = _knowledge_locks.get(knowledge_id)
    if lock is None:
        lock = asyncio.Lock()
        _knowledge_locks[knowledge_id] = lock
    return lock


def enqueue_version_embedding(knowledge_id: uuid.UUID, version_id: uuid.UUID) -> None:
    """Menjadwalkan proses embedding versi knowledge di background tanpa memblokir HTTP request."""
    task = asyncio.create_task(process_knowledge_version(knowledge_id, version_id))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def _embed_single_document(doc_id: uuid.UUID, knowledge_id: uuid.UUID) -> None:
    """Memproses satu dokumen PDF: update status, ekstrak teks & render snapshot halaman, upload MinIO, embed vector."""
    async with AsyncSessionLocal() as session:
        doc = await session.get(Document, doc_id)
        if doc is None or doc.status == DocumentStatus.EMBEDDED:
            return
        doc.status = DocumentStatus.PROCESSING
        doc.error_message = None
        doc.updated_at = utc_now()
        await session.commit()

        filename = doc.filename
        storage_path = doc.storage_path

    try:
        render_snapshots = settings.MINIO_ENABLED
        page_count, chunks, snapshots = await asyncio.to_thread(
            extract_and_chunk_document_with_snapshots, storage_path, render_snapshots
        )

        # Upload snapshot gambar halaman ke MinIO
        page_image_objects: dict[int, str] = {}
        if render_snapshots and snapshots:
            logger.info("Mengunggah %d snapshot gambar halaman ke MinIO...", len(snapshots))
            for page_num, img_bytes in snapshots.items():
                obj_name = await asyncio.to_thread(
                    minio_service.upload_page_snapshot,
                    knowledge_id,
                    doc_id,
                    page_num,
                    img_bytes,
                )
                if obj_name:
                    page_image_objects[page_num] = obj_name

        # Embed vector menggunakan Contextual Chunk Header untuk akurasi semantik lintas bagian
        vectors = await embedding_service.embed_documents(
            [c.to_embedding_text(filename) for c in chunks],
            title=filename,
        )

        async with AsyncSessionLocal() as session:
            doc = await session.get(Document, doc_id)
            if doc is None:
                return

            await session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == doc_id))

            chunk_models = [
                DocumentChunk(
                    knowledge_id=knowledge_id,
                    document_id=doc_id,
                    chunk_index=chunk.chunk_index,
                    page_number=chunk.page_number,
                    content=chunk.content,
                    metadata_json={
                        "filename": filename,
                        "page_number": chunk.page_number,
                        "section_title": chunk.section_title,
                        "contextual_header": chunk.build_contextual_header(filename),
                        "page_image_object": page_image_objects.get(chunk.page_number),
                        "page_image_url": page_image_objects.get(chunk.page_number),
                    },
                    embedding=vector,
                )
                for chunk, vector in zip(chunks, vectors, strict=True)
            ]
            session.add_all(chunk_models)

            doc.status = DocumentStatus.EMBEDDED
            doc.page_count = page_count
            doc.chunk_count = len(chunk_models)
            doc.error_message = None
            doc.updated_at = utc_now()
            await session.commit()

        logger.info("Dokumen '%s' (%s) selesai di-embed (%d chunks, %d snapshots MinIO).", filename, doc_id, len(chunks), len(page_image_objects))

    except Exception as exc:
        logger.exception("Gagal memproses embedding dokumen %s (%s)", filename, doc_id)
        async with AsyncSessionLocal() as session:
            doc = await session.get(Document, doc_id)
            if doc is not None:
                doc.status = DocumentStatus.FAILED
                doc.error_message = str(exc)[:1000]
                doc.updated_at = utc_now()
                await session.commit()


async def process_knowledge_version(knowledge_id: uuid.UUID, version_id: uuid.UUID) -> None:
    """Memproses seluruh dokumen yang belum di-embed pada versi knowledge tertentu secara berurutan."""
    lock = _get_lock(knowledge_id)
    async with lock:
        async with AsyncSessionLocal() as session:
            stmt = (
                select(Document.id)
                .join(KnowledgeVersionDocument, KnowledgeVersionDocument.document_id == Document.id)
                .where(
                    KnowledgeVersionDocument.version_id == version_id,
                    Document.status.in_([DocumentStatus.WAITING, DocumentStatus.FAILED]),
                )
                .order_by(Document.created_at.asc())
            )
            pending_doc_ids = list((await session.execute(stmt)).scalars().all())

        for doc_id in pending_doc_ids:
            await _embed_single_document(doc_id=doc_id, knowledge_id=knowledge_id)

        async with AsyncSessionLocal() as session:
            knowledge = await session.get(Knowledge, knowledge_id)
            version = await session.get(KnowledgeVersion, version_id)
            if knowledge is None or version is None:
                return

            doc_statuses_stmt = (
                select(Document.status)
                .join(KnowledgeVersionDocument, KnowledgeVersionDocument.document_id == Document.id)
                .where(KnowledgeVersionDocument.version_id == version_id)
            )
            statuses = list((await session.execute(doc_statuses_stmt)).scalars().all())

            all_embedded = bool(statuses) and all(s == DocumentStatus.EMBEDDED for s in statuses)
            if all_embedded:
                version.status = KnowledgeStatus.DONE
                knowledge.status = KnowledgeStatus.DONE
                knowledge.active_version_id = version.id
            else:
                version.status = KnowledgeStatus.UNFINISHED
                knowledge.status = KnowledgeStatus.UNFINISHED

            knowledge.updated_at = utc_now()
            await session.commit()
