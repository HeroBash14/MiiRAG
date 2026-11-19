import logging
import uuid

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import case, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.knowledge import (
    Document,
    DocumentStatus,
    Knowledge,
    KnowledgeStatus,
    KnowledgeVersion,
    KnowledgeVersionDocument,
    utc_now,
)
from app.schemas.knowledge import (
    DocumentOut,
    KnowledgeDetailResponse,
    KnowledgeListItem,
    KnowledgeListResponse,
    KnowledgeStatusCounts,
    KnowledgeVersionOut,
)
from app.services.graph_builder_service import build_knowledge_graph_for_version
from app.services.minio_service import minio_service
from app.services.storage_service import (
    delete_knowledge_storage,
    delete_stored_file,
    save_uploaded_pdf,
)
from app.services.worker_service import enqueue_version_embedding

logger = logging.getLogger(__name__)


async def _get_knowledge_or_404(session: AsyncSession, knowledge_id: uuid.UUID) -> Knowledge:
    knowledge = await session.get(Knowledge, knowledge_id)
    if knowledge is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge tidak ditemukan.")
    return knowledge


async def _get_version_and_docs(
    session: AsyncSession, knowledge_id: uuid.UUID, version_number: int
) -> tuple[KnowledgeVersion, list[Document]]:
    ver_stmt = select(KnowledgeVersion).where(
        KnowledgeVersion.knowledge_id == knowledge_id,
        KnowledgeVersion.version_number == version_number,
    )
    version = (await session.execute(ver_stmt)).scalar_one()

    docs_stmt = (
        select(Document)
        .join(KnowledgeVersionDocument, KnowledgeVersionDocument.document_id == Document.id)
        .where(KnowledgeVersionDocument.version_id == version.id)
        .order_by(Document.created_at.asc())
    )
    docs = list((await session.execute(docs_stmt)).scalars().all())
    return version, docs


async def _build_detail_response(
    session: AsyncSession, knowledge: Knowledge
) -> KnowledgeDetailResponse:
    _, docs = await _get_version_and_docs(session, knowledge.id, knowledge.current_version)
    versions_stmt = (
        select(KnowledgeVersion)
        .where(KnowledgeVersion.knowledge_id == knowledge.id)
        .order_by(KnowledgeVersion.version_number.desc())
    )
    versions = list((await session.execute(versions_stmt)).scalars().all())

    history = [
        KnowledgeVersionOut(
            id=v.id,
            version_number=v.version_number,
            note=v.note,
            status=v.status,
            doc_count=v.doc_count,
            is_active=(v.id == knowledge.active_version_id),
            created_at=v.created_at,
        )
        for v in versions
        if v.status != KnowledgeStatus.UNFINISHED or v.version_number > 1 or v.note is not None
    ]

    embedded_count = sum(1 for d in docs if d.status == DocumentStatus.EMBEDDED)

    return KnowledgeDetailResponse(
        id=knowledge.id,
        name=knowledge.name,
        description=knowledge.description,
        status=knowledge.status,
        current_version=knowledge.current_version,
        active_version_id=knowledge.active_version_id,
        doc_count=len(docs),
        embedded_doc_count=embedded_count,
        created_at=knowledge.created_at,
        updated_at=knowledge.updated_at,
        documents=[DocumentOut.model_validate(d) for d in docs],
        version_history=history,
    )


async def list_knowledges(
    session: AsyncSession,
    q: str | None = None,
    status_filter: str | None = None,
) -> KnowledgeListResponse:
    """Mengambil daftar knowledge beserta filter status, pencarian nama, dan jumlah per status."""
    count_stmt = select(
        func.count(Knowledge.id).label("all"),
        func.count(case((Knowledge.status == KnowledgeStatus.UNFINISHED, 1))).label("unfinished"),
        func.count(case((Knowledge.status == KnowledgeStatus.PROCESSING, 1))).label("processing"),
        func.count(case((Knowledge.status == KnowledgeStatus.DONE, 1))).label("done"),
    )
    counts_row = (await session.execute(count_stmt)).one()
    counts = KnowledgeStatusCounts(
        all=counts_row.all,
        unfinished=counts_row.unfinished,
        processing=counts_row.processing,
        done=counts_row.done,
    )

    stmt = select(Knowledge).order_by(Knowledge.updated_at.desc())
    if q and q.strip():
        stmt = stmt.where(Knowledge.name.ilike(f"%{q.strip()}%"))
    if status_filter and status_filter != "all":
        try:
            parsed_status = KnowledgeStatus(status_filter)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Filter status harus salah satu dari: all, unfinished, processing, done.",
            ) from exc
        stmt = stmt.where(Knowledge.status == parsed_status)

    knowledges = list((await session.execute(stmt)).scalars().all())
    if not knowledges:
        return KnowledgeListResponse(counts=counts, items=[])

    # Batch-fetch document counts for each knowledge's current version
    doc_stats_stmt = (
        select(
            Knowledge.id.label("knowledge_id"),
            func.count(Document.id).label("doc_count"),
            func.count(case((Document.status == DocumentStatus.EMBEDDED, 1))).label(
                "embedded_doc_count"
            ),
        )
        .join(
            KnowledgeVersion,
            (KnowledgeVersion.knowledge_id == Knowledge.id)
            & (KnowledgeVersion.version_number == Knowledge.current_version),
        )
        .outerjoin(KnowledgeVersionDocument, KnowledgeVersionDocument.version_id == KnowledgeVersion.id)
        .outerjoin(Document, Document.id == KnowledgeVersionDocument.document_id)
        .where(Knowledge.id.in_([k.id for k in knowledges]))
        .group_by(Knowledge.id)
    )
    stats_map = {
        row.knowledge_id: (row.doc_count, row.embedded_doc_count)
        for row in (await session.execute(doc_stats_stmt)).all()
    }

    items = [
        KnowledgeListItem(
            id=k.id,
            name=k.name,
            description=k.description,
            status=k.status,
            current_version=k.current_version,
            doc_count=stats_map.get(k.id, (0, 0))[0],
            embedded_doc_count=stats_map.get(k.id, (0, 0))[1],
            created_at=k.created_at,
            updated_at=k.updated_at,
        )
        for k in knowledges
    ]

    return KnowledgeListResponse(counts=counts, items=items)


async def get_knowledge_detail(
    session: AsyncSession, knowledge_id: uuid.UUID
) -> KnowledgeDetailResponse:
    knowledge = await _get_knowledge_or_404(session, knowledge_id)
    return await _build_detail_response(session, knowledge)


async def create_knowledge(
    session: AsyncSession,
    name: str,
    description: str | None,
    files: list[UploadFile],
    process_now: bool,
) -> KnowledgeDetailResponse:
    clean_name = name.strip()
    if not clean_name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Nama knowledge wajib diisi.")
    if process_now and not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload minimal 1 dokumen (PDF / DOCX) untuk langsung diproses.",
        )

    knowledge_id = uuid.uuid4()
    initial_status = KnowledgeStatus.PROCESSING if process_now else KnowledgeStatus.UNFINISHED
    now = utc_now()

    knowledge = Knowledge(
        id=knowledge_id,
        name=clean_name,
        description=description.strip() if description and description.strip() else None,
        status=initial_status,
        current_version=1,
        created_at=now,
        updated_at=now,
    )
    version = KnowledgeVersion(
        id=uuid.uuid4(),
        knowledge_id=knowledge_id,
        version_number=1,
        note="Versi awal" if process_now else None,
        status=initial_status,
        doc_count=len(files),
        created_at=now,
    )
    session.add(knowledge)
    session.add(version)

    for upload in files:
        stored = await save_uploaded_pdf(knowledge_id, upload)
        doc = Document(
            id=uuid.uuid4(),
            knowledge_id=knowledge_id,
            filename=stored.filename,
            file_size=stored.file_size,
            file_hash=stored.file_hash,
            storage_path=stored.storage_path,
            status=DocumentStatus.WAITING,
            created_at=now,
            updated_at=now,
        )
        session.add(doc)
        session.add(KnowledgeVersionDocument(version_id=version.id, document_id=doc.id))

    await session.commit()

    if process_now:
        enqueue_version_embedding(knowledge.id, version.id)

    return await _build_detail_response(session, knowledge)


async def update_draft(
    session: AsyncSession,
    knowledge_id: uuid.UUID,
    name: str | None,
    description: str | None,
    keep_document_ids: list[uuid.UUID] | None,
    new_files: list[UploadFile],
) -> KnowledgeDetailResponse:
    """Mengubah draft knowledge (hanya saat status unfinished)."""
    knowledge = await _get_knowledge_or_404(session, knowledge_id)
    if knowledge.status != KnowledgeStatus.UNFINISHED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Edit draft hanya dapat dilakukan ketika status knowledge adalah 'unfinished'.",
        )

    version, existing_docs = await _get_version_and_docs(
        session, knowledge.id, knowledge.current_version
    )

    if name is not None:
        clean_name = name.strip()
        if not clean_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Nama knowledge tidak boleh kosong."
            )
        knowledge.name = clean_name

    if description is not None:
        knowledge.description = description.strip() if description.strip() else None

    if keep_document_ids is not None:
        existing_map = {d.id: d for d in existing_docs}
        invalid_ids = [doc_id for doc_id in keep_document_ids if doc_id not in existing_map]
        if invalid_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Terdapat document_id yang tidak termasuk dalam draft ini.",
            )
        keep_set = set(keep_document_ids)
        for doc in existing_docs:
            if doc.id not in keep_set:
                await session.execute(
                    delete(KnowledgeVersionDocument).where(
                        KnowledgeVersionDocument.version_id == version.id,
                        KnowledgeVersionDocument.document_id == doc.id,
                    )
                )
                delete_stored_file(doc.storage_path)
                await session.delete(doc)

    now = utc_now()
    for upload in new_files:
        stored = await save_uploaded_pdf(knowledge.id, upload)
        doc = Document(
            id=uuid.uuid4(),
            knowledge_id=knowledge.id,
            filename=stored.filename,
            file_size=stored.file_size,
            file_hash=stored.file_hash,
            storage_path=stored.storage_path,
            status=DocumentStatus.WAITING,
            created_at=now,
            updated_at=now,
        )
        session.add(doc)
        session.add(KnowledgeVersionDocument(version_id=version.id, document_id=doc.id))

    await session.flush()
    _, updated_docs = await _get_version_and_docs(session, knowledge.id, knowledge.current_version)
    version.doc_count = len(updated_docs)
    knowledge.updated_at = now
    await session.commit()

    return await _build_detail_response(session, knowledge)


async def start_processing(
    session: AsyncSession, knowledge_id: uuid.UUID
) -> KnowledgeDetailResponse:
    """Memulai proses embedding untuk knowledge yang masih berstatus unfinished."""
    knowledge = await _get_knowledge_or_404(session, knowledge_id)
    if knowledge.status == KnowledgeStatus.PROCESSING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Knowledge sedang dalam proses embedding."
        )
    if knowledge.status == KnowledgeStatus.DONE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Knowledge sudah selesai di-embed. Gunakan endpoint re-new untuk memperbarui dokumen.",
        )

    version, docs = await _get_version_and_docs(session, knowledge.id, knowledge.current_version)
    if not docs:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload minimal 1 dokumen (PDF / DOCX) sebelum memulai proses embedding.",
        )

    now = utc_now()
    knowledge.status = KnowledgeStatus.PROCESSING
    knowledge.updated_at = now
    version.status = KnowledgeStatus.PROCESSING
    if version.version_number == 1 and not version.note:
        version.note = "Versi awal"
    await session.commit()

    enqueue_version_embedding(knowledge.id, version.id)
    return await _build_detail_response(session, knowledge)


async def renew_knowledge(
    session: AsyncSession,
    knowledge_id: uuid.UUID,
    note: str | None,
    keep_document_ids: list[uuid.UUID],
    new_files: list[UploadFile],
) -> KnowledgeDetailResponse:
    """Membuat versi baru (v+1); dokumen lama yang dipertahankan tidak di-embed ulang."""
    knowledge = await _get_knowledge_or_404(session, knowledge_id)
    if knowledge.status == KnowledgeStatus.PROCESSING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Tunggu proses embedding selesai sebelum melakukan re-new.",
        )

    _, prev_docs = await _get_version_and_docs(session, knowledge.id, knowledge.current_version)
    prev_doc_map = {d.id: d for d in prev_docs}

    invalid_ids = [doc_id for doc_id in keep_document_ids if doc_id not in prev_doc_map]
    if invalid_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Terdapat keep_document_ids yang tidak berasal dari versi saat ini.",
        )

    keep_unique_ids = list(dict.fromkeys(keep_document_ids))
    has_changes = bool(new_files) or (set(keep_unique_ids) != set(prev_doc_map.keys()))
    if not has_changes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Belum ada perubahan dokumen untuk versi baru.",
        )

    total_docs = len(keep_unique_ids) + len(new_files)
    if total_docs == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Minimal harus ada 1 dokumen pada versi baru.",
        )

    now = utc_now()
    next_version_number = knowledge.current_version + 1
    new_version = KnowledgeVersion(
        id=uuid.uuid4(),
        knowledge_id=knowledge.id,
        version_number=next_version_number,
        note=note.strip() if note and note.strip() else None,
        status=KnowledgeStatus.PROCESSING,
        doc_count=total_docs,
        created_at=now,
    )
    session.add(new_version)

    needs_embedding = False
    for doc_id in keep_unique_ids:
        session.add(KnowledgeVersionDocument(version_id=new_version.id, document_id=doc_id))
        if prev_doc_map[doc_id].status != DocumentStatus.EMBEDDED:
            needs_embedding = True

    for upload in new_files:
        stored = await save_uploaded_pdf(knowledge.id, upload)
        doc = Document(
            id=uuid.uuid4(),
            knowledge_id=knowledge.id,
            filename=stored.filename,
            file_size=stored.file_size,
            file_hash=stored.file_hash,
            storage_path=stored.storage_path,
            status=DocumentStatus.WAITING,
            created_at=now,
            updated_at=now,
        )
        session.add(doc)
        session.add(KnowledgeVersionDocument(version_id=new_version.id, document_id=doc.id))
        needs_embedding = True

    knowledge.current_version = next_version_number
    knowledge.updated_at = now

    if needs_embedding:
        new_version.status = KnowledgeStatus.PROCESSING
        knowledge.status = KnowledgeStatus.PROCESSING
    else:
        await session.flush()
        new_version.status = KnowledgeStatus.DONE
        knowledge.status = KnowledgeStatus.DONE
        knowledge.active_version_id = new_version.id

    await session.commit()

    if needs_embedding:
        enqueue_version_embedding(knowledge.id, new_version.id)
    elif settings.KG_ENABLED:
        try:
            await build_knowledge_graph_for_version(knowledge.id, new_version.id)
        except Exception:
            logger.exception(
                "Gagal memperbarui Knowledge Graph saat re-new knowledge=%s version=%s",
                knowledge.id,
                new_version.id,
            )

    return await _build_detail_response(session, knowledge)


async def delete_knowledge(session: AsyncSession, knowledge_id: uuid.UUID) -> None:
    knowledge = await _get_knowledge_or_404(session, knowledge_id)
    if knowledge.status == KnowledgeStatus.PROCESSING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Tidak dapat menghapus knowledge yang sedang dalam proses embedding.",
        )
    await session.delete(knowledge)
    await session.commit()
    delete_knowledge_storage(knowledge_id)
    minio_service.delete_knowledge_snapshots(knowledge_id)
