import csv
import io
import logging
import math
import re
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

import openpyxl

from app.core.config import settings
from app.services.pdf_service import PDFChunk, PDFPageText

logger = logging.getLogger(__name__)

MAX_SPREADSHEET_ROWS = 50_000
MAX_SPREADSHEET_COLS = 200
_MULTI_SPACE_RE = re.compile(r"[ \t]+")


@dataclass(frozen=True, slots=True)
class _HeadingBlock:
    text: str


@dataclass(frozen=True, slots=True)
class _TableBlock:
    headers: list[str]
    rows: list[list[str]]


@dataclass(frozen=True, slots=True)
class _TextBlock:
    lines: list[str]


_SheetBlock = _HeadingBlock | _TableBlock | _TextBlock


@dataclass(frozen=True, slots=True)
class _ParsedSheet:
    sheet_number: int
    name: str
    is_csv: bool
    blocks: list[_SheetBlock]


def _format_cell_value(value: Any) -> str:
    """Memformat nilai sel Excel/CSV (angka, tanggal, boolean, teks) secara bersih dan manusiawi."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, datetime):
        if value.hour == 0 and value.minute == 0 and value.second == 0:
            return value.strftime("%Y-%m-%d")
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, time):
        return value.strftime("%H:%M:%S")
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return ""
        if value.is_integer():
            return str(int(value))
        return f"{value:.6f}".rstrip("0").rstrip(".")
    if isinstance(value, int):
        return str(value)

    text = str(value).replace("\x00", "").replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
    return _MULTI_SPACE_RE.sub(" ", text).strip()


def _escape_md_cell(text: str) -> str:
    return text.replace("|", "\\|").strip()


def _normalize_headers(raw_headers: list[str]) -> list[str]:
    """Memastikan setiap kolom memiliki nama header valid dan unik untuk verbalization key-value."""
    seen: dict[str, int] = {}
    normalized: list[str] = []
    for idx, raw in enumerate(raw_headers, start=1):
        base = raw.strip() or f"Kolom {idx}"
        count = seen.get(base, 0) + 1
        seen[base] = count
        normalized.append(base if count == 1 else f"{base} ({count})")
    return normalized


def _format_md_table(headers: list[str], data_rows: list[list[str]]) -> str:
    header_line = "| " + " | ".join(_escape_md_cell(h) for h in headers) + " |"
    sep_line = "| " + " | ".join(["---"] * len(headers)) + " |"
    lines = [header_line, sep_line]
    for row in data_rows:
        padded = row + [""] * (len(headers) - len(row))
        lines.append("| " + " | ".join(_escape_md_cell(c) for c in padded[: len(headers)]) + " |")
    return "\n".join(lines)


def _format_kv_row(row_num: int, headers: list[str], row: list[str]) -> str:
    """Mengonversi satu baris tabel ke format Key-Value semantik agar nilai sel menempel dengan nama kolom."""
    padded = row + [""] * (len(headers) - len(row))
    pairs = [
        f"{h}: {v}"
        for h, v in zip(headers, padded[: len(headers)], strict=True)
        if v.strip()
    ]
    if not pairs:
        return ""
    return f"Baris {row_num}: " + " | ".join(pairs)


def _segment_rows_into_blocks(rows: list[list[str]]) -> list[_SheetBlock]:
    """Memecah grid baris bebas (arbitrary layout) menjadi blok heading, tabel, atau teks."""
    groups: list[list[list[str]]] = []
    current_group: list[list[str]] = []

    for row in rows:
        if any(cell.strip() for cell in row):
            current_group.append(row)
        elif current_group:
            groups.append(current_group)
            current_group = []
    if current_group:
        groups.append(current_group)

    blocks: list[_SheetBlock] = []
    for group in groups:
        # Pisahkan baris judul / banner (hanya 1 sel terisi) di bagian paling atas blok
        leading_singles: list[str] = []
        start_idx = 0
        while start_idx < len(group):
            non_empty = [c.strip() for c in group[start_idx] if c.strip()]
            if len(non_empty) == 1:
                leading_singles.append(non_empty[0])
                start_idx += 1
            else:
                break

        # Pisahkan baris catatan kaki (hanya 1 sel terisi) di bagian paling bawah blok
        trailing_singles: list[str] = []
        end_idx = len(group)
        while end_idx > start_idx:
            non_empty = [c.strip() for c in group[end_idx - 1] if c.strip()]
            if len(non_empty) == 1:
                trailing_singles.insert(0, non_empty[0])
                end_idx -= 1
            else:
                break

        core_rows = group[start_idx:end_idx]

        if not core_rows:
            # Seluruh blok hanya berisi teks 1 kolom (daftar/catatan)
            all_lines = leading_singles + trailing_singles
            if len(all_lines) == 1 and len(all_lines[0]) < 140:
                blocks.append(_HeadingBlock(text=all_lines[0]))
            elif all_lines:
                blocks.append(_TextBlock(lines=all_lines))
            continue

        # Emit judul pembuka sebelum tabel
        for title_line in leading_singles:
            if len(title_line) < 160:
                blocks.append(_HeadingBlock(text=title_line))
            else:
                blocks.append(_TextBlock(lines=[title_line]))

        # Buang kolom kosong sepenuhnya agar tabel bersih dari spacer kolom Excel
        max_width = max(len(r) for r in core_rows)
        active_cols = [
            col_idx
            for col_idx in range(max_width)
            if any(col_idx < len(r) and r[col_idx].strip() for r in core_rows)
        ]

        trimmed_rows = [
            [r[c].strip() if c < len(r) else "" for c in active_cols]
            for r in core_rows
        ]

        if len(active_cols) >= 2 and len(trimmed_rows) >= 2:
            headers = _normalize_headers(trimmed_rows[0])
            data_rows = [r for r in trimmed_rows[1:] if any(c for c in r)]
            if data_rows:
                blocks.append(_TableBlock(headers=headers, rows=data_rows))
            else:
                blocks.append(_TextBlock(lines=[" | ".join(h for h in headers if h)]))
        else:
            text_lines = [
                " | ".join(cell for cell in r if cell)
                for r in trimmed_rows
                if any(r)
            ]
            if text_lines:
                blocks.append(_TextBlock(lines=text_lines))

        if trailing_singles:
            blocks.append(_TextBlock(lines=trailing_singles))

    return blocks


def _extract_xlsx_sheets_with_mode(path: Path, data_only: bool) -> list[_ParsedSheet]:
    wb = openpyxl.load_workbook(str(path), data_only=data_only, read_only=False)
    parsed_sheets: list[_ParsedSheet] = []
    try:
        sheet_counter = 0
        for ws in wb.worksheets:
            max_r = min(ws.max_row or 0, MAX_SPREADSHEET_ROWS)
            max_c = min(ws.max_column or 0, MAX_SPREADSHEET_COLS)
            if max_r == 0 or max_c == 0:
                continue

            # Kumpulkan sel terisi ke sparse grid (tahan terhadap bug 1.048.576 baris kosong Excel)
            grid: dict[int, dict[int, str]] = {}
            for r_idx, row_vals in enumerate(
                ws.iter_rows(min_row=1, max_row=max_r, min_col=1, max_col=max_c, values_only=True),
                start=1,
            ):
                row_map: dict[int, str] = {}
                for c_idx, val in enumerate(row_vals, start=1):
                    formatted = _format_cell_value(val)
                    if formatted:
                        row_map[c_idx] = formatted
                if row_map:
                    grid[r_idx] = row_map

            # Smart Auto-Unmerge: isi sel vertikal ke bawah, jangan ulangi judul banner horizontal
            for mrange in ws.merged_cells.ranges:
                r1, c1 = mrange.min_row, mrange.min_col
                r2 = min(mrange.max_row, max_r)
                c2 = min(mrange.max_col, max_c)
                if r1 > max_r or c1 > max_c:
                    continue
                anchor_val = grid.get(r1, {}).get(c1, "")
                if not anchor_val:
                    continue

                if r1 == r2:
                    other_cells = [
                        c for c in grid.get(r1, {}) if c < c1 or c > c2
                    ]
                    if not other_cells:
                        # Banner judul tunggal di baris ini -> jangan digandakan ke semua kolom
                        continue
                    row_map = grid.setdefault(r1, {})
                    for c in range(c1, c2 + 1):
                        row_map.setdefault(c, anchor_val)
                else:
                    for r in range(r1, r2 + 1):
                        row_map = grid.setdefault(r, {})
                        for c in range(c1, c2 + 1):
                            row_map.setdefault(c, anchor_val)

            if not grid:
                continue

            min_used_row = min(grid)
            max_used_row = max(grid)
            min_used_col = min(min(rm) for rm in grid.values())
            max_used_col = max(max(rm) for rm in grid.values())
            width = max_used_col - min_used_col + 1

            dense_rows: list[list[str]] = []
            for r in range(min_used_row, max_used_row + 1):
                rm = grid.get(r)
                if not rm:
                    dense_rows.append([])
                else:
                    dense_rows.append(
                        [rm.get(min_used_col + offset, "") for offset in range(width)]
                    )

            blocks = _segment_rows_into_blocks(dense_rows)
            if not blocks:
                continue

            sheet_counter += 1
            parsed_sheets.append(
                _ParsedSheet(
                    sheet_number=sheet_counter,
                    name=ws.title.strip() or f"Sheet {sheet_counter}",
                    is_csv=False,
                    blocks=blocks,
                )
            )
    finally:
        wb.close()

    return parsed_sheets


def _extract_xlsx_sheets(path: Path) -> list[_ParsedSheet]:
    """Ekstrak seluruh sheet non-kosong dari file .xlsx (utamakan nilai hasil formula data_only=True)."""
    sheets = _extract_xlsx_sheets_with_mode(path, data_only=True)
    if not sheets:
        # Fallback jika workbook hanya berisi formula yang belum pernah di-cache oleh Excel
        sheets = _extract_xlsx_sheets_with_mode(path, data_only=False)
    return sheets


def _decode_csv_bytes(raw: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _detect_csv_delimiter(text: str) -> str:
    """Mendeteksi pemisah kolom CSV (koma, titik koma Excel Indonesia, tab, atau pipe)."""
    sample_lines = [line for line in text.splitlines() if line.strip()][:20]
    sample = "\n".join(sample_lines)
    if not sample:
        return ","

    candidates = (",", ";", "\t", "|")
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters="".join(candidates))
        if dialect.delimiter in candidates:
            return dialect.delimiter
    except csv.Error:
        pass

    # Fallback deterministik: hitung rata-rata kemunculan delimiter per baris
    best_delim = ","
    best_score = 0
    for delim in candidates:
        counts = [line.count(delim) for line in sample_lines]
        non_zero = [c for c in counts if c > 0]
        if not non_zero:
            continue
        score = sum(non_zero)
        if score > best_score:
            best_score = score
            best_delim = delim
    return best_delim


def _extract_csv_sheets(path: Path) -> list[_ParsedSheet]:
    """Ekstrak file .csv dengan deteksi encoding dan delimiter otomatis."""
    text = _decode_csv_bytes(path.read_bytes())
    if not text.strip():
        return []

    delimiter = _detect_csv_delimiter(text)
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)

    rows: list[list[str]] = []
    for idx, raw_row in enumerate(reader):
        if idx >= MAX_SPREADSHEET_ROWS:
            break
        cleaned = [_format_cell_value(cell) for cell in raw_row[:MAX_SPREADSHEET_COLS]]
        rows.append(cleaned)

    blocks = _segment_rows_into_blocks(rows)
    if not blocks:
        return []

    return [
        _ParsedSheet(
            sheet_number=1,
            name=path.stem or "CSV",
            is_csv=True,
            blocks=blocks,
        )
    ]


def _render_sheet_to_markdown(sheet: _ParsedSheet) -> str:
    parts: list[str] = []
    if not sheet.is_csv:
        parts.append(f"# Sheet: {sheet.name}")
    for block in sheet.blocks:
        if isinstance(block, _HeadingBlock):
            parts.append(f"## {block.text}")
        elif isinstance(block, _TableBlock):
            parts.append(_format_md_table(block.headers, block.rows))
        elif isinstance(block, _TextBlock):
            parts.append("\n".join(block.lines))
    return "\n\n".join(parts).strip()


def _build_table_chunk(
    chunk_index: int,
    page_number: int,
    section_title: str,
    header_md: str,
    md_rows: list[str],
    kv_rows: list[str],
    headings_prefix: list[str] | None = None,
) -> PDFChunk:
    md_body = header_md + "\n" + "\n".join(md_rows)
    kv_body = "\n".join(kv_rows)
    if headings_prefix:
        md_prefix = "\n\n".join(f"## {h}" for h in headings_prefix)
        kv_prefix = " | ".join(headings_prefix)
        md_body = f"{md_prefix}\n\n{md_body}"
        kv_body = f"{kv_prefix}\n{kv_body}" if kv_body else kv_prefix
    return PDFChunk(
        chunk_index=chunk_index,
        page_number=page_number,
        content=md_body,
        section_title=section_title,
        search_text=kv_body or None,
    )


def _chunk_spreadsheet_sheets(
    sheets: list[_ParsedSheet],
    chunk_size: int | None = None,
) -> list[PDFChunk]:
    """Memecah sheet menjadi chunk Dual-Representation: Markdown Table (content) + Row Key-Value (search_text)."""
    size = chunk_size or settings.CHUNK_SIZE
    chunks: list[PDFChunk] = []
    global_idx = 0

    for sheet in sheets:
        base_section = f"Sheet: {sheet.name}" if not sheet.is_csv else sheet.name
        active_section = base_section[:240]
        pending_headings: list[str] = []

        for block in sheet.blocks:
            if isinstance(block, _HeadingBlock):
                pending_headings.append(block.text)
                active_section = " > ".join([base_section, *pending_headings])[:240]
                continue

            if isinstance(block, _TableBlock):
                headers = block.headers
                header_md = (
                    "| " + " | ".join(_escape_md_cell(h) for h in headers) + " |\n"
                    "| " + " | ".join(["---"] * len(headers)) + " |"
                )

                curr_md_rows: list[str] = []
                curr_kv_rows: list[str] = []
                is_first_table_chunk = True

                for row_num, row in enumerate(block.rows, start=1):
                    padded = row + [""] * (len(headers) - len(row))
                    md_row = (
                        "| "
                        + " | ".join(_escape_md_cell(c) for c in padded[: len(headers)])
                        + " |"
                    )
                    kv_row = _format_kv_row(row_num, headers, padded)
                    if not kv_row:
                        continue

                    cand_md_len = (
                        len(header_md)
                        + 1
                        + sum(len(r) + 1 for r in curr_md_rows)
                        + len(md_row)
                    )
                    cand_kv_len = sum(len(r) + 1 for r in curr_kv_rows) + len(kv_row)

                    # Pastikan BOTH Markdown & Key-Value muat dalam CHUNK_SIZE agar tidak terpotong Cross-Encoder 512 token
                    if curr_md_rows and max(cand_md_len, cand_kv_len) > size:
                        prefix = list(pending_headings) if is_first_table_chunk else None
                        if prefix:
                            pending_headings.clear()
                        chunks.append(
                            _build_table_chunk(
                                chunk_index=global_idx,
                                page_number=sheet.sheet_number,
                                section_title=active_section,
                                header_md=header_md,
                                md_rows=curr_md_rows,
                                kv_rows=curr_kv_rows,
                                headings_prefix=prefix,
                            )
                        )
                        global_idx += 1
                        is_first_table_chunk = False
                        curr_md_rows = [md_row]
                        curr_kv_rows = [kv_row]
                    else:
                        curr_md_rows.append(md_row)
                        curr_kv_rows.append(kv_row)

                if curr_md_rows:
                    prefix = list(pending_headings) if is_first_table_chunk else None
                    if prefix:
                        pending_headings.clear()
                    chunks.append(
                        _build_table_chunk(
                            chunk_index=global_idx,
                            page_number=sheet.sheet_number,
                            section_title=active_section,
                            header_md=header_md,
                            md_rows=curr_md_rows,
                            kv_rows=curr_kv_rows,
                            headings_prefix=prefix,
                        )
                    )
                    global_idx += 1
                continue

            if isinstance(block, _TextBlock):
                curr_lines: list[str] = []
                curr_len = 0
                for line in block.lines:
                    if not line.strip():
                        continue
                    add_len = len(line) + (1 if curr_lines else 0)
                    if curr_lines and curr_len + add_len > size:
                        body = "\n".join(curr_lines)
                        if pending_headings:
                            md_prefix = "\n\n".join(f"## {h}" for h in pending_headings)
                            body = f"{md_prefix}\n\n{body}"
                            pending_headings.clear()
                        chunks.append(
                            PDFChunk(
                                chunk_index=global_idx,
                                page_number=sheet.sheet_number,
                                content=body,
                                section_title=active_section,
                            )
                        )
                        global_idx += 1
                        curr_lines = [line]
                        curr_len = len(line)
                    else:
                        curr_lines.append(line)
                        curr_len += add_len

                if curr_lines:
                    body = "\n".join(curr_lines)
                    if pending_headings:
                        md_prefix = "\n\n".join(f"## {h}" for h in pending_headings)
                        body = f"{md_prefix}\n\n{body}"
                        pending_headings.clear()
                    chunks.append(
                        PDFChunk(
                            chunk_index=global_idx,
                            page_number=sheet.sheet_number,
                            content=body,
                            section_title=active_section,
                        )
                    )
                    global_idx += 1

        # Jika sebuah sheet hanya berisi heading tanpa blok lain
        if pending_headings:
            chunks.append(
                PDFChunk(
                    chunk_index=global_idx,
                    page_number=sheet.sheet_number,
                    content="\n\n".join(f"## {h}" for h in pending_headings),
                    section_title=active_section,
                )
            )
            global_idx += 1

    return chunks


def _parse_spreadsheet_file(file_path: str | Path) -> list[_ParsedSheet]:
    path = Path(file_path)
    ext = path.suffix.lower()
    if ext == ".xlsx":
        return _extract_xlsx_sheets(path)
    if ext == ".csv":
        return _extract_csv_sheets(path)
    raise ValueError(f"Format spreadsheet '{ext}' tidak didukung.")


def extract_spreadsheet_pages(file_path: str | Path) -> tuple[int, list[PDFPageText]]:
    """Ekstrak teks Markdown per sheet dari file .xlsx atau .csv tanpa snapshot gambar."""
    sheets = _parse_spreadsheet_file(file_path)
    pages = [
        PDFPageText(page_number=s.sheet_number, text=_render_sheet_to_markdown(s))
        for s in sheets
    ]
    return len(sheets), pages


def extract_and_chunk_spreadsheet(
    file_path: str | Path,
    chunk_size: int | None = None,
) -> tuple[int, list[PDFChunk]]:
    """Pipeline lengkap ekstraksi & Dual-Representation chunking untuk file Excel (.xlsx) dan CSV (.csv)."""
    path = Path(file_path)
    sheets = _parse_spreadsheet_file(path)
    if not sheets:
        raise ValueError(f"Dokumen '{path.name}' tidak memiliki data atau teks yang dapat diekstrak.")
    chunks = _chunk_spreadsheet_sheets(sheets, chunk_size=chunk_size)
    if not chunks:
        raise ValueError(f"Tidak ada chunk teks yang dihasilkan dari dokumen '{path.name}'.")
    return len(sheets), chunks
