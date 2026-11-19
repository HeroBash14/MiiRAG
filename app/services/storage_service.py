import hashlib
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException, UploadFile, status

from app.core.config import settings

PDF_MAGIC_HEADER = b"%PDF-"
ZIP_MAGIC_HEADER = b"PK\x03\x04"
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".pptx", ".xlsx", ".csv"}
_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]")


@dataclass(frozen=True, slots=True)
class StoredFile:
    filename: str
    file_size: int
    file_hash: str
    storage_path: str


def _sanitize_filename(filename: str) -> str:
    base = Path(filename).name.strip() or "document"
    sanitized = _SAFE_FILENAME_RE.sub("_", base)
    return sanitized[:200]


async def save_uploaded_document(knowledge_id: uuid.UUID, upload: UploadFile) -> StoredFile:
    """Validasi file dokumen (PDF, DOCX, PPTX, XLSX, atau CSV) lalu simpan ke storage lokal."""
    raw_name = upload.filename or "document"
    ext = Path(raw_name).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"File '{raw_name}' tidak didukung. Format yang didukung: "
                "PDF (.pdf), Word (.docx), PowerPoint (.pptx), Excel (.xlsx), dan CSV (.csv)."
            ),
        )

    content = await upload.read()
    file_size = len(content)

    if file_size == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File '{raw_name}' kosong.",
        )

    if file_size > settings.max_upload_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Ukuran file '{raw_name}' melebihi batas {settings.MAX_UPLOAD_SIZE_MB} MB.",
        )

    if ext == ".pdf" and not content.startswith(PDF_MAGIC_HEADER):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File '{raw_name}' bukan dokumen PDF yang valid.",
        )

    if ext == ".docx" and not content.startswith(ZIP_MAGIC_HEADER):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File '{raw_name}' bukan dokumen Word (.docx) yang valid.",
        )

    if ext == ".pptx" and not content.startswith(ZIP_MAGIC_HEADER):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File '{raw_name}' bukan dokumen PowerPoint (.pptx) yang valid.",
        )

    if ext == ".xlsx" and not content.startswith(ZIP_MAGIC_HEADER):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File '{raw_name}' bukan dokumen Excel (.xlsx) yang valid.",
        )

    if ext == ".csv":
        head = content[:8192]
        if b"\x00" in head or content.startswith((PDF_MAGIC_HEADER, ZIP_MAGIC_HEADER)):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File '{raw_name}' bukan dokumen CSV teks yang valid.",
            )
        decoded_ok = False
        for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
            try:
                if content.decode(enc).strip():
                    decoded_ok = True
                break
            except UnicodeDecodeError:
                continue
        if not decoded_ok:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File '{raw_name}' kosong atau bukan dokumen CSV yang valid.",
            )

    file_hash = hashlib.sha256(content).hexdigest()
    safe_name = _sanitize_filename(raw_name)
    target_dir = settings.STORAGE_DIR / str(knowledge_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"{uuid.uuid4()}_{safe_name}"
    target_path.write_bytes(content)

    return StoredFile(
        filename=Path(raw_name).name,
        file_size=file_size,
        file_hash=file_hash,
        storage_path=str(target_path),
    )


# Alias untuk backward compatibility
save_uploaded_pdf = save_uploaded_document


def delete_stored_file(storage_path: str) -> None:
    """Menghapus file fisik dari storage lokal jika masih ada."""
    path = Path(storage_path)
    if path.exists() and path.is_file():
        path.unlink()


def delete_knowledge_storage(knowledge_id: uuid.UUID) -> None:
    """Menghapus seluruh folder storage milik knowledge tertentu."""
    target_dir = settings.STORAGE_DIR / str(knowledge_id)
    if target_dir.exists() and target_dir.is_dir():
        shutil.rmtree(target_dir, ignore_errors=True)
