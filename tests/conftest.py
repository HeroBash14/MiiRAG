import os

# Pastikan test suite SELALU menggunakan database khusus testing (miirag_test)
# agar tidak pernah menghapus data di database development (miirag).
_base_db_url = os.environ.get("DATABASE_URL", "postgresql+asyncpg://miirag:miirag@localhost:5432/miirag")
if "/miirag_test" not in _base_db_url:
    os.environ["DATABASE_URL"] = _base_db_url.rsplit("/", 1)[0] + "/miirag_test"

import io
from collections.abc import AsyncGenerator
from pathlib import Path

import docx
import pymupdf
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.core.config import settings
from app.core.database import AsyncSessionLocal, engine
from app.main import app


def make_pdf_bytes(pages: list[str]) -> bytes:
    """Membuat file PDF valid di memori menggunakan PyMuPDF untuk kebutuhan testing."""
    doc = pymupdf.open()
    for content in pages:
        page = doc.new_page()
        if content:
            page.insert_textbox(pymupdf.Rect(72, 72, 520, 750), content)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def make_docx_bytes(paragraphs: list[str]) -> bytes:
    """Membuat file Word DOCX valid di memori menggunakan python-docx untuk kebutuhan testing."""
    doc = docx.Document()
    for text_para in paragraphs:
        if text_para:
            doc.add_paragraph(text_para)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def make_pptx_bytes(slides_content: list[dict[str, object]]) -> bytes:
    """Membuat file PowerPoint PPTX valid di memori menggunakan python-pptx untuk kebutuhan testing."""
    import pptx
    from pptx.util import Inches

    prs = pptx.Presentation()
    blank_layout = prs.slide_layouts[6]

    for s_data in slides_content:
        slide = prs.slides.add_slide(blank_layout)
        top_offset = 0.5

        title = str(s_data.get("title", "")).strip()
        if title:
            tx = slide.shapes.add_textbox(Inches(0.5), Inches(top_offset), Inches(9), Inches(0.8))
            tx.text_frame.text = title
            top_offset += 1.0

        bullets = s_data.get("bullets", [])
        if bullets and isinstance(bullets, list):
            tx = slide.shapes.add_textbox(Inches(0.5), Inches(top_offset), Inches(9), Inches(1.5))
            tf = tx.text_frame
            for b_idx, b_item in enumerate(bullets):
                p = tf.paragraphs[0] if b_idx == 0 else tf.add_paragraph()
                p.text = str(b_item)
            top_offset += 1.8

        table_data = s_data.get("table", [])
        if table_data and isinstance(table_data, list):
            rows = len(table_data)
            cols = max(len(r) for r in table_data)
            table_shape = slide.shapes.add_table(
                rows, cols, Inches(0.5), Inches(top_offset), Inches(8), Inches(1.5)
            )
            table = table_shape.table
            for r_idx, row in enumerate(table_data):
                for c_idx, cell_text in enumerate(row):
                    table.cell(r_idx, c_idx).text = str(cell_text)
            top_offset += 1.8

        notes = str(s_data.get("notes", "")).strip()
        if notes:
            slide.notes_slide.notes_text_frame.text = notes

    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


@pytest.fixture(autouse=True)
def temp_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    storage_dir = tmp_path / "uploads"
    storage_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "STORAGE_DIR", storage_dir)
    return storage_dir


@pytest_asyncio.fixture
async def clean_db() -> AsyncGenerator[None, None]:
    """Membersihkan seluruh tabel database test (miirag_test) sebelum dan sesudah test integrasi."""
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("TRUNCATE TABLE document_chunks, knowledge_version_documents, documents, knowledge_versions, knowledges RESTART IDENTITY CASCADE")
        )
        await session.commit()
    yield
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("TRUNCATE TABLE document_chunks, knowledge_version_documents, documents, knowledge_versions, knowledges RESTART IDENTITY CASCADE")
        )
        await session.commit()
    await engine.dispose()


@pytest_asyncio.fixture
async def client(clean_db: None) -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
