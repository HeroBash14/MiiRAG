import logging
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import docx
import pptx
import pymupdf
from docx.table import Table
from docx.text.paragraph import Paragraph
from pptx.enum.shapes import MSO_SHAPE_TYPE

from app.core.config import settings

logger = logging.getLogger(__name__)

_MULTI_SPACE_RE = re.compile(r"[ \t]+")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")
_SEPARATORS = ("\n\n", "\n", ". ", " ")

_BULLET_CHARS = ("•", "◦", "▪", "▫", "–", "—", "*", "-")
_BULLET_PREFIX_RE = re.compile(r"^[\u2022\u25e6\u25aa\u25ab\u2013\u2014\*\-]\s+(.*)$")
_NUMBERED_PREFIX_RE = re.compile(r"^(\d+[\.\)])\s+(.*)$")
_SECTION_HEADING_RE = re.compile(r"^\d+(\.\d+)*\s+[A-Z]")


_HEADING_LINE_RE = re.compile(r"^(#{1,4})\s+(.+?)\s*$")


@dataclass(frozen=True, slots=True)
class PDFPageText:
    page_number: int
    text: str


@dataclass(frozen=True, slots=True)
class PDFChunk:
    chunk_index: int
    page_number: int
    content: str
    section_title: str | None = None

    def build_contextual_header(self, filename: str | None = None) -> str:
        """Membentuk header konteks hierarki (Contextual Chunk Header) untuk embedding & hybrid search."""
        parts: list[str] = []
        if filename:
            parts.append(f"Dokumen: {filename}")
        parts.append(f"Halaman: {self.page_number}")
        if self.section_title:
            parts.append(f"Bagian: {self.section_title}")
        return " | ".join(parts)

    def to_embedding_text(self, filename: str | None = None) -> str:
        """Menggabungkan contextual header dengan konten chunk untuk akurasi vector embedding."""
        header = self.build_contextual_header(filename)
        return f"[{header}]\n\n{self.content}"


def _clean_text(raw: str) -> str:
    text = raw.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    text = _MULTI_SPACE_RE.sub(" ", text)
    text = _MULTI_NEWLINE_RE.sub("\n\n", text)
    return text.strip()


def _format_markdown_table_rows(rows: list[list[str]]) -> str:
    """Format row lists into standard Markdown grid syntax."""
    if not rows:
        return ""

    clean_rows: list[list[str]] = []
    for r in rows:
        clean_cells = [
            c.replace("\x00", "")
            .replace("\r\n", " ")
            .replace("\r", " ")
            .replace("\n", " ")
            .replace("|", "\\|")
            .strip()
            for c in r
        ]
        clean_rows.append(clean_cells)

    # Filter completely empty rows
    clean_rows = [r for r in clean_rows if any(cell for cell in r)]
    if not clean_rows:
        return ""

    col_count = max(len(r) for r in clean_rows)
    if col_count == 0:
        return ""

    for r in clean_rows:
        while len(r) < col_count:
            r.append("")

    header = clean_rows[0]
    sep = ["---"] * col_count
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(sep) + " |",
    ]
    for r in clean_rows[1:]:
        lines.append("| " + " | ".join(r) + " |")

    return "\n".join(lines)


def _is_markdown_table(text: str) -> bool:
    """Check if a text block represents a valid Markdown table."""
    lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
    if len(lines) < 2:
        return False
    if not (lines[0].startswith("|") and lines[0].endswith("|")):
        return False
    sep = lines[1]
    if not (sep.startswith("|") and sep.endswith("|")):
        return False
    parts = [p.strip() for p in sep[1:-1].split("|")]
    return len(parts) >= 1 and all(re.match(r"^:?-+:?$", p) for p in parts if p)


def _split_table_by_rows(table_block: str, chunk_size: int) -> list[str]:
    """Split a Markdown table by rows, repeating header and separator rows on EVERY chunk."""
    lines = [l.strip() for l in table_block.strip().split("\n") if l.strip()]
    if len(lines) <= 2:
        return [table_block]

    header_lines = lines[:2]
    header_str = "\n".join(header_lines)
    data_rows = lines[2:]

    chunks: list[str] = []
    curr_rows: list[str] = []

    for row in data_rows:
        candidate = header_str + "\n" + "\n".join(curr_rows + [row])
        if len(candidate) <= chunk_size or not curr_rows:
            curr_rows.append(row)
        else:
            chunks.append(header_str + "\n" + "\n".join(curr_rows))
            curr_rows = [row]

    if curr_rows:
        chunks.append(header_str + "\n" + "\n".join(curr_rows))

    return chunks


def _format_styled_spans(spans: list[dict]) -> str:
    """Format spans in a line with standard markdown bold, italic, and inline code."""
    grouped: list[dict] = []
    for s in spans:
        raw_txt = s.get("text", "")
        if not raw_txt:
            continue
        flags = s.get("flags", 0)
        font = s.get("font", "").lower()
        bold = bool((flags & 16) or "bold" in font or "black" in font or "heavy" in font)
        italic = bool((flags & 2) or "italic" in font or "oblique" in font)
        code = bool((flags & 8) or any(k in font for k in ("mono", "courier", "consolas", "menlo", "code")))

        if (
            grouped
            and grouped[-1]["bold"] == bold
            and grouped[-1]["italic"] == italic
            and grouped[-1]["code"] == code
        ):
            grouped[-1]["text"] += raw_txt
        else:
            grouped.append({"text": raw_txt, "bold": bold, "italic": italic, "code": code})

    formatted_parts: list[str] = []
    for g in grouped:
        stxt = g["text"]
        bold = g["bold"]
        italic = g["italic"]
        code = g["code"]

        lspace = len(stxt) - len(stxt.lstrip())
        rspace = len(stxt) - len(stxt.rstrip())
        core = stxt.strip()

        if not core:
            formatted_parts.append(stxt)
            continue

        if code:
            styled = f"`{core}`"
        elif bold and italic:
            styled = f"***{core}***"
        elif bold:
            styled = f"**{core}**"
        elif italic:
            styled = f"*{core}*"
        else:
            styled = core

        formatted_parts.append((" " * lspace) + styled + (" " * rspace))

    return "".join(formatted_parts).strip()


def _decode_pdf_page_to_markdown(page: pymupdf.Page) -> str:
    """Ekstrak halaman PDF menjadi format Markdown terstruktur: tabel, heading, list, style."""
    tabs = page.find_tables(use_layout=False)
    tab_rects = [pymupdf.Rect(t.bbox) for t in tabs]

    elements: list[tuple[float, float, str, str]] = []

    # 1. Ekstrak tabel-tabel pada halaman
    for t in tabs:
        table_md = ""
        try:
            extracted_rows = t.extract()
            if extracted_rows:
                table_md = _format_markdown_table_rows(extracted_rows)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Gagal mengekstrak baris tabel: %s", exc)

        if not table_md:
            try:
                raw_md = t.to_markdown().strip()
                if _is_markdown_table(raw_md):
                    table_md = raw_md
            except Exception as exc:  # noqa: BLE001
                logger.debug("Gagal konversi tabel ke markdown: %s", exc)

        if table_md:
            elements.append((t.bbox[1], t.bbox[0], "table", table_md))

    # 2. Hitung ukuran font dasar pada halaman
    page_dict = page.get_text("dict", sort=True)
    font_sizes: list[float] = []
    for b in page_dict.get("blocks", []):
        if b.get("type") == 0:
            for l in b.get("lines", []):
                for s in l.get("spans", []):
                    t = s.get("text", "").strip()
                    if t:
                        font_sizes.extend([round(s.get("size", 0.0), 1)] * len(t))

    base_size = 9.5
    if font_sizes:
        font_sizes.sort()
        base_size = font_sizes[len(font_sizes) // 2]

    # 3. Ekstrak text blocks di luar tabel
    for b in page_dict.get("blocks", []):
        if b.get("type") != 0:
            continue

        brect = pymupdf.Rect(b["bbox"])
        is_in_table = False
        for tr in tab_rects:
            inter = brect & tr
            if inter.is_valid and not inter.is_empty:
                ratio = (inter.width * inter.height) / max(0.001, brect.width * brect.height)
                if ratio > 0.5:
                    is_in_table = True
                    break

        if is_in_table:
            continue

        block_lines: list[str] = []
        is_code_block = False
        all_spans = [s for l in b.get("lines", []) for s in l.get("spans", []) if s.get("text", "").strip()]
        if all_spans and all(
            (s.get("flags", 0) & 8) or any(k in s.get("font", "").lower() for k in ("mono", "courier", "consolas", "code"))
            for s in all_spans
        ):
            is_code_block = True

        if is_code_block:
            code_text = "\n".join(
                "".join(s.get("text", "") for s in l.get("spans", [])).rstrip()
                for l in b.get("lines", [])
            ).strip()
            if code_text:
                elements.append((b["bbox"][1], b["bbox"][0], "text", f"```\n{code_text}\n```"))
            continue

        for l in b.get("lines", []):
            spans = l.get("spans", [])
            if not spans:
                continue

            raw_line = "".join(s.get("text", "") for s in spans).strip()
            if not raw_line:
                continue

            total_chars = max(1, sum(len(s.get("text", "")) for s in spans))
            avg_size = sum(s.get("size", 0.0) * len(s.get("text", "")) for s in spans) / total_chars
            is_all_bold = all(
                (s.get("flags", 0) & 16) or "bold" in s.get("font", "").lower() or "black" in s.get("font", "").lower()
                for s in spans
                if s.get("text", "").strip()
            )

            # Heading level detection
            is_heading = False
            heading_level = 0
            if avg_size >= base_size * 1.35 and (is_all_bold or len(raw_line) < 100):
                is_heading = True
                heading_level = 1
            elif avg_size >= base_size * 1.1 and is_all_bold or is_all_bold and _SECTION_HEADING_RE.match(raw_line) and len(raw_line) < 100:
                is_heading = True
                heading_level = 2

            if is_heading:
                prefix = "#" * heading_level
                block_lines.append(f"{prefix} {raw_line}")
                continue

            # List item detection
            bullet_match = _BULLET_PREFIX_RE.match(raw_line)
            styled_line = _format_styled_spans(spans)

            if bullet_match:
                content = styled_line
                for b_char in _BULLET_CHARS:
                    if content.startswith(b_char):
                        content = content[len(b_char) :].strip()
                        break
                block_lines.append(f"- {content}")
            elif _NUMBERED_PREFIX_RE.match(raw_line):
                block_lines.append(styled_line)
            else:
                block_lines.append(styled_line)

        if block_lines:
            elements.append((b["bbox"][1], b["bbox"][0], "text", "\n".join(block_lines)))

    elements.sort(key=lambda el: (el[0], el[1]))
    return "\n\n".join(el[3] for el in elements)


def _docx_ast_to_markdown(docx_path: Path) -> tuple[int, list[PDFPageText], dict[int, bytes]]:
    """Ekstraksi dokumen DOCX ke format Markdown menggunakan AST traversal python-docx."""
    doc = docx.Document(str(docx_path))
    elements: list[str] = []

    for child in doc.element.body:
        if child.tag.endswith("p"):
            p = Paragraph(child, doc)
            raw = p.text.strip()
            if not raw:
                continue

            style_name = p.style.name if p.style else ""

            if style_name == "Title":
                elements.append(f"# {raw}")
                continue
            elif style_name == "Subtitle":
                elements.append(f"## {raw}")
                continue
            elif style_name == "Heading 1":
                elements.append(f"# {raw}")
                continue
            elif style_name == "Heading 2":
                elements.append(f"## {raw}")
                continue
            elif style_name == "Heading 3":
                elements.append(f"### {raw}")
                continue
            elif style_name == "Heading 4":
                elements.append(f"#### {raw}")
                continue

            is_bullet = style_name.startswith("List Bullet") or raw.startswith(_BULLET_CHARS)

            # Format runs with bold/italic/code
            parts: list[str] = []
            for r in p.runs:
                rtxt = r.text
                if not rtxt:
                    continue
                bold = bool(r.bold)
                italic = bool(r.italic)
                font_name = r.font.name.lower() if r.font and r.font.name else ""
                code = bool(any(k in font_name for k in ("mono", "courier", "consolas", "code")))

                lspace = len(rtxt) - len(rtxt.lstrip())
                rspace = len(rtxt) - len(rtxt.rstrip())
                core = rtxt.strip()

                if not core:
                    parts.append(rtxt)
                    continue

                if code:
                    styled = f"`{core}`"
                elif bold and italic:
                    styled = f"***{core}***"
                elif bold:
                    styled = f"**{core}**"
                elif italic:
                    styled = f"*{core}*"
                else:
                    styled = core

                parts.append((" " * lspace) + styled + (" " * rspace))

            p_text = "".join(parts).strip()
            if is_bullet:
                for b_char in _BULLET_CHARS:
                    if p_text.startswith(b_char):
                        p_text = p_text[len(b_char) :].strip()
                        break
                elements.append(f"- {p_text}")
            else:
                elements.append(p_text)

        elif child.tag.endswith("tbl"):
            tbl = Table(child, doc)
            rows: list[list[str]] = []
            for row in tbl.rows:
                cells = [c.text.strip().replace("\r\n", " ").replace("\n", " ").replace("|", "\\|") for c in row.cells]
                rows.append(cells)
            table_md = _format_markdown_table_rows(rows)
            if table_md:
                elements.append(table_md)

    if not elements:
        return 0, [], {}

    full_md = _clean_text("\n\n".join(elements))
    pages = [PDFPageText(page_number=1, text=full_md)]

    snapshots: dict[int, bytes] = {}
    img_idx = 1
    try:
        for rel in doc.part.rels.values():
            if "image" in rel.target_ref:
                snapshots[img_idx] = rel.target_part.blob
                img_idx += 1
    except Exception as exc:  # noqa: BLE001
        logger.warning("Gagal mengekstrak embedded images dari DOCX: %s", exc)

    return len(pages), pages, snapshots


def extract_pdf_pages_and_snapshots(
    file_path: str | Path,
    render_snapshots: bool = True,
) -> tuple[int, list[PDFPageText], dict[int, bytes]]:
    """Ekstrak teks per halaman ke Markdown dan render snapshot gambar halaman (PNG) untuk visual grounding."""
    pages: list[PDFPageText] = []
    snapshots: dict[int, bytes] = {}

    with pymupdf.open(str(file_path)) as doc:
        page_count = doc.page_count
        for idx in range(page_count):
            page_num = idx + 1
            page = doc.load_page(idx)
            md_text = _decode_pdf_page_to_markdown(page)
            cleaned = _clean_text(md_text)
            if cleaned:
                pages.append(PDFPageText(page_number=page_num, text=cleaned))

            if render_snapshots:
                try:
                    pix = page.get_pixmap(dpi=settings.PAGE_SNAPSHOT_DPI)
                    snapshots[page_num] = pix.tobytes("png")
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Gagal render snapshot halaman %d: %s", page_num, exc)

    return page_count, pages, snapshots


def extract_pdf_pages(file_path: str | Path) -> tuple[int, list[PDFPageText]]:
    """Ekstrak teks Markdown bersih per halaman dari file PDF menggunakan PyMuPDF."""
    page_count, pages, _ = extract_pdf_pages_and_snapshots(
        file_path, render_snapshots=False
    )
    return page_count, pages


def _convert_office_to_pdf(file_path: Path, output_dir: Path) -> Path | None:
    """Mengonversi file Office (DOCX, PPTX) ke PDF menggunakan LibreOffice headless untuk layout dan snapshot halaman persis."""
    soffice_bin = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice_bin:
        logger.warning("LibreOffice/soffice tidak ditemukan, beralih ke ekstraksi AST langsung.")
        return None

    try:
        cmd = [soffice_bin, "--headless", "--convert-to", "pdf", "--outdir", str(output_dir), str(file_path)]
        res = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=45)
        if res.returncode == 0:
            pdf_path = output_dir / f"{file_path.stem}.pdf"
            if pdf_path.exists():
                return pdf_path
        logger.warning(
            "Gagal konversi %s ke PDF via soffice (returncode %d): %s",
            file_path.suffix,
            res.returncode,
            res.stderr,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Error saat menjalankan soffice untuk konversi %s: %s", file_path.suffix, exc)

    return None


_convert_docx_to_pdf = _convert_office_to_pdf


def _extract_pptx_notes(pptx_path: Path) -> dict[int, str]:
    """Ekstrak catatan presenter (speaker notes) per slide dari file PPTX."""
    notes: dict[int, str] = {}
    try:
        prs = pptx.Presentation(str(pptx_path))
        for idx, slide in enumerate(prs.slides):
            slide_num = idx + 1
            if slide.has_notes_slide and slide.notes_slide.notes_text_frame:
                note_raw = slide.notes_slide.notes_text_frame.text.strip()
                if note_raw:
                    notes[slide_num] = note_raw
    except Exception as exc:  # noqa: BLE001
        logger.warning("Gagal membaca speaker notes dari PPTX: %s", exc)
    return notes


def _pptx_ast_to_markdown(pptx_path: Path) -> tuple[int, list[PDFPageText], dict[int, bytes]]:
    """Ekstraksi dokumen PPTX ke format Markdown menggunakan AST traversal python-pptx."""
    prs = pptx.Presentation(str(pptx_path))
    pages: list[PDFPageText] = []
    snapshots: dict[int, bytes] = {}

    for idx, slide in enumerate(prs.slides):
        slide_num = idx + 1
        elements: list[str] = []

        # Urutkan shapes berdasarkan koordinat top dan left untuk menjaga reading order
        shapes = sorted(slide.shapes, key=lambda s: (s.top or 0, s.left or 0))

        title_shape = slide.shapes.title
        title_text = ""
        if title_shape and title_shape.text:
            title_text = title_shape.text.strip()

        # Jika slide tidak memiliki placeholder title resmi, periksa shape paling atas
        if not title_text and shapes:
            top_shape = shapes[0]
            if top_shape.has_text_frame and len(top_shape.text_frame.paragraphs) <= 2:
                candidate = top_shape.text_frame.text.strip()
                if candidate and len(candidate.split("\n")) <= 2 and len(candidate) < 120:
                    title_text = candidate
                    title_shape = top_shape

        if title_text:
            elements.append(f"# {title_text}")

        for shape in shapes:
            if shape == title_shape:
                continue

            if shape.has_table:
                rows: list[list[str]] = []
                for row in shape.table.rows:
                    cells = [
                        c.text.strip().replace("\r\n", " ").replace("\n", " ").replace("|", "\\|")
                        for c in row.cells
                    ]
                    rows.append(cells)
                table_md = _format_markdown_table_rows(rows)
                if table_md:
                    elements.append(table_md)

            elif shape.has_text_frame:
                for p in shape.text_frame.paragraphs:
                    parts: list[str] = []
                    for r in p.runs:
                        rtxt = r.text
                        if not rtxt:
                            continue
                        bold = bool(r.font.bold)
                        italic = bool(r.font.italic)
                        font_name = r.font.name.lower() if r.font and r.font.name else ""
                        code = bool(any(k in font_name for k in ("mono", "courier", "consolas", "code")))

                        lspace = len(rtxt) - len(rtxt.lstrip())
                        rspace = len(rtxt) - len(rtxt.rstrip())
                        core = rtxt.strip()

                        if not core:
                            parts.append(rtxt)
                            continue

                        if code:
                            styled = f"`{core}`"
                        elif bold and italic:
                            styled = f"***{core}***"
                        elif bold:
                            styled = f"**{core}**"
                        elif italic:
                            styled = f"*{core}*"
                        else:
                            styled = core

                        parts.append((" " * lspace) + styled + (" " * rspace))

                    p_text = "".join(parts).strip()
                    if not p_text or p_text == title_text:
                        continue

                    level = p.level or 0
                    indent = "  " * level
                    elements.append(f"{indent}- {p_text}")

            elif shape.shape_type == MSO_SHAPE_TYPE.PICTURE and slide_num not in snapshots:
                try:
                    snapshots[slide_num] = shape.image.blob
                except Exception as exc:  # noqa: BLE001
                    logger.debug("Gagal mengekstrak gambar slide %d: %s", slide_num, exc)

        # Speaker notes
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame:
            note_raw = slide.notes_slide.notes_text_frame.text.strip()
            if note_raw:
                note_lines = [f"> {line}" for line in note_raw.split("\n") if line.strip()]
                elements.append("> **Catatan Presenter:**\n" + "\n".join(note_lines))

        slide_md = _clean_text("\n\n".join(elements))
        if slide_md:
            pages.append(PDFPageText(page_number=slide_num, text=slide_md))

    return len(prs.slides), pages, snapshots


def _extract_docx_fallback(file_path: Path) -> tuple[int, list[PDFPageText], dict[int, bytes]]:
    """Ekstraksi teks dan tabel langsung dari DOCX menggunakan AST traversal python-docx jika LibreOffice tidak tersedia."""
    return _docx_ast_to_markdown(file_path)


def _extract_pptx_fallback(file_path: Path) -> tuple[int, list[PDFPageText], dict[int, bytes]]:
    """Ekstraksi teks dan tabel langsung dari PPTX menggunakan AST traversal python-pptx jika LibreOffice tidak tersedia."""
    return _pptx_ast_to_markdown(file_path)


def extract_document_pages_and_snapshots(
    file_path: str | Path,
    render_snapshots: bool = True,
) -> tuple[int, list[PDFPageText], dict[int, bytes]]:
    """Ekstrak teks Markdown dan snapshot gambar halaman dari file PDF, Word (.docx), maupun PowerPoint (.pptx)."""
    path = Path(file_path)
    ext = path.suffix.lower()

    if ext == ".docx":
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = _convert_office_to_pdf(path, Path(tmpdir))
            if pdf_path and pdf_path.exists():
                return extract_pdf_pages_and_snapshots(pdf_path, render_snapshots=render_snapshots)
        return _extract_docx_fallback(path)

    if ext == ".pptx":
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = _convert_office_to_pdf(path, Path(tmpdir))
            if pdf_path and pdf_path.exists():
                count, pages, snapshots = extract_pdf_pages_and_snapshots(
                    pdf_path, render_snapshots=render_snapshots
                )
                notes = _extract_pptx_notes(path)
                if notes:
                    enriched_pages: list[PDFPageText] = []
                    for page in pages:
                        slide_note = notes.get(page.page_number)
                        if slide_note:
                            note_lines = [f"> {line}" for line in slide_note.split("\n") if line.strip()]
                            note_md = "> **Catatan Presenter:**\n" + "\n".join(note_lines)
                            enriched_pages.append(
                                PDFPageText(page_number=page.page_number, text=f"{page.text}\n\n{note_md}")
                            )
                        else:
                            enriched_pages.append(page)
                    return count, enriched_pages, snapshots
                return count, pages, snapshots
        return _extract_pptx_fallback(path)

    return extract_pdf_pages_and_snapshots(path, render_snapshots=render_snapshots)


def _split_text_block(text: str, chunk_size: int, separators: tuple[str, ...]) -> list[str]:
    if len(text) <= chunk_size:
        return [text]

    if not separators:
        return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]

    sep = separators[0]
    remaining_seps = separators[1:]
    parts = text.split(sep)

    if len(parts) == 1:
        return _split_text_block(text, chunk_size, remaining_seps)

    segments: list[str] = []
    current = ""
    for part in parts:
        part = part.strip()
        if not part:
            continue
        candidate = f"{current}{sep}{part}" if current else part
        if len(candidate) <= chunk_size:
            current = candidate
        else:
            if current:
                segments.append(current)
            if len(part) <= chunk_size:
                current = part
            else:
                segments.extend(_split_text_block(part, chunk_size, remaining_seps))
                current = ""

    if current:
        segments.append(current)

    return segments


def _update_heading_state(active_headings: dict[int, str], text: str) -> str | None:
    """Memperbarui state hierarki heading Markdown (#..####) dari segmen teks."""
    for line in text.splitlines():
        m = _HEADING_LINE_RE.match(line.strip())
        if not m:
            continue
        level = len(m.group(1))
        title = m.group(2).strip()
        if not title:
            continue
        active_headings[level] = title
        for deeper in [lvl for lvl in active_headings if lvl > level]:
            del active_headings[deeper]

    if not active_headings:
        return None
    ordered = [active_headings[lvl] for lvl in sorted(active_headings)]
    return " > ".join(ordered)[:240]


def chunk_pdf_pages(
    pages: list[PDFPageText],
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> list[PDFChunk]:
    """Memecah teks halaman menjadi chunk table-aware dengan overlap sambil menjaga nomor halaman dan konteks heading."""
    size = chunk_size or settings.CHUNK_SIZE
    overlap = chunk_overlap if chunk_overlap is not None else settings.CHUNK_OVERLAP

    chunks: list[PDFChunk] = []
    global_idx = 0
    active_headings: dict[int, str] = {}

    for page in pages:
        raw_blocks = [b.strip() for b in page.text.split("\n\n") if b.strip()]
        if not raw_blocks:
            continue

        semantic_units: list[str] = []
        for b in raw_blocks:
            if _is_markdown_table(b):
                if len(b) <= size:
                    semantic_units.append(b)
                else:
                    semantic_units.extend(_split_table_by_rows(b, size))
            else:
                if len(b) <= size:
                    semantic_units.append(b)
                else:
                    semantic_units.extend(_split_text_block(b, size, _SEPARATORS))

        page_chunks: list[str] = []
        curr_parts: list[str] = []
        curr_len = 0

        for unit in semantic_units:
            add_len = len(unit) + (2 if curr_parts else 0)
            if curr_len + add_len <= size or not curr_parts:
                curr_parts.append(unit)
                curr_len += add_len
            else:
                page_chunks.append("\n\n".join(curr_parts))
                curr_parts = [unit]
                curr_len = len(unit)

        if curr_parts:
            page_chunks.append("\n\n".join(curr_parts))

        # Apply overlap cautiously (do not cut across table boundaries)
        final_segments: list[str] = []
        if overlap > 0 and len(page_chunks) > 1:
            final_segments.append(page_chunks[0])
            for idx in range(1, len(page_chunks)):
                prev = page_chunks[idx - 1]
                curr = page_chunks[idx]
                if not curr.startswith("|") and not prev.endswith("|"):
                    tail = prev[-overlap:].strip()
                    if "\n" in tail:
                        tail = tail.split("\n", 1)[-1].strip()
                    if tail and len(tail) + 2 + len(curr) <= size:
                        final_segments.append(f"{tail}\n\n{curr}")
                        continue
                final_segments.append(curr)
        else:
            final_segments = page_chunks

        for seg in final_segments:
            cleaned = seg.strip()
            if not cleaned:
                continue
            section_title = _update_heading_state(active_headings, cleaned)
            chunks.append(
                PDFChunk(
                    chunk_index=global_idx,
                    page_number=page.page_number,
                    content=cleaned,
                    section_title=section_title,
                )
            )
            global_idx += 1

    return chunks


def extract_and_chunk_document_with_snapshots(
    file_path: str | Path,
    render_snapshots: bool = True,
) -> tuple[int, list[PDFChunk], dict[int, bytes]]:
    """Pipeline lengkap ekstraksi teks & render snapshot gambar per halaman untuk PDF dan DOCX."""
    page_count, pages, snapshots = extract_document_pages_and_snapshots(
        file_path, render_snapshots=render_snapshots
    )
    if not pages:
        raise ValueError(f"Dokumen '{Path(file_path).name}' tidak memiliki teks yang dapat diekstrak.")
    chunks = chunk_pdf_pages(pages)
    if not chunks:
        raise ValueError(f"Tidak ada chunk teks yang dihasilkan dari dokumen '{Path(file_path).name}'.")
    return page_count, chunks, snapshots


def extract_and_chunk_document(file_path: str | Path) -> tuple[int, list[PDFChunk]]:
    """Pipeline ekstraksi & chunking dokumen standar (tanpa snapshot)."""
    page_count, chunks, _ = extract_and_chunk_document_with_snapshots(
        file_path, render_snapshots=False
    )
    return page_count, chunks


# Aliases untuk backward compatibility
extract_and_chunk_pdf_with_snapshots = extract_and_chunk_document_with_snapshots
extract_and_chunk_pdf = extract_and_chunk_document
