import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.knowledge import KnowledgeDetailResponse, KnowledgeListResponse
from app.services import knowledge_service

router = APIRouter(prefix="/knowledges", tags=["Knowledge"])


def _parse_uuid_list(raw_values: list[str] | None) -> list[uuid.UUID] | None:
    if raw_values is None:
        return None
    parsed: list[uuid.UUID] = []
    for item in raw_values:
        stripped = item.strip()
        if not stripped:
            continue
        if stripped.startswith("["):
            try:
                loaded = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Format JSON keep_document_ids tidak valid.",
                ) from exc
            if not isinstance(loaded, list):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="keep_document_ids harus berupa array UUID.",
                )
            for sub in loaded:
                parsed.append(_parse_single_uuid(str(sub)))
        else:
            for part in stripped.split(","):
                part_clean = part.strip()
                if part_clean:
                    parsed.append(_parse_single_uuid(part_clean))
    return parsed


def _parse_single_uuid(raw: str) -> uuid.UUID:
    try:
        return uuid.UUID(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Format UUID tidak valid: '{raw}'.",
        ) from exc


DBSession = Annotated[AsyncSession, Depends(get_db)]


@router.get("", response_model=KnowledgeListResponse)
async def list_knowledges(
    session: DBSession,
    q: Annotated[str | None, Query(description="Kata kunci pencarian nama knowledge")] = None,
    status_filter: Annotated[
        str | None,
        Query(alias="status", description="Filter status: all, unfinished, processing, done"),
    ] = "all",
) -> KnowledgeListResponse:
    return await knowledge_service.list_knowledges(session=session, q=q, status_filter=status_filter)


@router.get("/{knowledge_id}", response_model=KnowledgeDetailResponse)
async def get_knowledge_detail(
    knowledge_id: uuid.UUID,
    session: DBSession,
) -> KnowledgeDetailResponse:
    return await knowledge_service.get_knowledge_detail(session=session, knowledge_id=knowledge_id)


@router.post("", response_model=KnowledgeDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_knowledge(
    session: DBSession,
    name: Annotated[str, Form(..., description="Nama knowledge")],
    description: Annotated[str | None, Form(description="Deskripsi singkat knowledge")] = None,
    process_now: Annotated[
        bool, Form(description="true untuk langsung embed, false untuk simpan sebagai draft")
    ] = True,
    files: Annotated[list[UploadFile] | None, File(description="Daftar file PDF, DOCX, atau PPTX")] = None,
) -> KnowledgeDetailResponse:
    return await knowledge_service.create_knowledge(
        session=session,
        name=name,
        description=description,
        files=files or [],
        process_now=process_now,
    )


@router.patch("/{knowledge_id}", response_model=KnowledgeDetailResponse)
async def update_draft_knowledge(
    knowledge_id: uuid.UUID,
    session: DBSession,
    name: Annotated[str | None, Form()] = None,
    description: Annotated[str | None, Form()] = None,
    keep_document_ids: Annotated[list[str] | None, Form()] = None,
    files: Annotated[list[UploadFile] | None, File()] = None,
) -> KnowledgeDetailResponse:
    parsed_keep_ids = _parse_uuid_list(keep_document_ids)
    return await knowledge_service.update_draft(
        session=session,
        knowledge_id=knowledge_id,
        name=name,
        description=description,
        keep_document_ids=parsed_keep_ids,
        new_files=files or [],
    )


@router.post("/{knowledge_id}/process", response_model=KnowledgeDetailResponse)
async def start_knowledge_embedding(
    knowledge_id: uuid.UUID,
    session: DBSession,
) -> KnowledgeDetailResponse:
    return await knowledge_service.start_processing(session=session, knowledge_id=knowledge_id)


@router.post("/{knowledge_id}/renew", response_model=KnowledgeDetailResponse)
async def renew_knowledge(
    knowledge_id: uuid.UUID,
    session: DBSession,
    note: Annotated[str | None, Form(description="Catatan perubahan versi")] = None,
    keep_document_ids: Annotated[
        list[str] | None,
        Form(description="ID dokumen lama yang tetap dipertahankan (tidak di-embed ulang)"),
    ] = None,
    files: Annotated[list[UploadFile] | None, File(description="File PDF, DOCX, atau PPTX baru yang ditambahkan")] = None,
) -> KnowledgeDetailResponse:
    parsed_keep_ids = _parse_uuid_list(keep_document_ids) or []
    return await knowledge_service.renew_knowledge(
        session=session,
        knowledge_id=knowledge_id,
        note=note,
        keep_document_ids=parsed_keep_ids,
        new_files=files or [],
    )


@router.delete("/{knowledge_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_knowledge(
    knowledge_id: uuid.UUID,
    session: DBSession,
) -> None:
    await knowledge_service.delete_knowledge(session=session, knowledge_id=knowledge_id)
