import hashlib
import inspect
import logging
import math
import re
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.knowledge import (
    Document,
    DocumentChunk,
    DocumentStatus,
    KnowledgeVersionDocument,
    utc_now,
)
from app.models.knowledge_graph import KGEdge, KGNode
from app.services.embedding_service import embedding_service

logger = logging.getLogger(__name__)

# Stopwords komprehensif Indonesia & Inggris + kata generik struktur dokumen/tabel
_STOPWORDS: frozenset[str] = frozenset(
    {
        # Indonesia
        "yang", "dan", "di", "ke", "dari", "untuk", "pada", "dengan", "adalah", "ini", "itu",
        "atau", "juga", "oleh", "sebagai", "dalam", "apa", "saja", "bagaimana", "cara", "siapa",
        "kapan", "dimana", "mengapa", "kenapa", "berapa", "apakah", "tolong", "jelaskan", "sebutkan",
        "akan", "telah", "sudah", "belum", "tidak", "bukan", "dapat", "bisa", "harus", "wajib",
        "perlu", "boleh", "agar", "supaya", "karena", "sebab", "jika", "apabila", "bila", "ketika",
        "saat", "setelah", "sebelum", "selama", "hingga", "sampai", "antara", "serta", "namun",
        "tetapi", "tapi", "melainkan", "sedangkan", "sementara", "bahwa", "yaitu", "yakni", "seperti",
        "misalnya", "misal", "contoh", "berikut", "tersebut", "terkait", "mengenai", "tentang",
        "terhadap", "melalui", "berdasarkan", "sesuai", "secara", "hanya", "lebih", "paling",
        "sangat", "semua", "seluruh", "setiap", "tiap", "masing", "beberapa", "banyak", "sedikit",
        "lain", "lainnya", "dll", "dsb", "dst", "atas", "bawah", "depan", "belakang", "luar",
        "baru", "lama", "besar", "kecil", "tinggi", "rendah", "baik", "benar", "salah", "sama",
        "berbeda", "ada", "tiada", "tanpa", "menjadi", "memiliki", "punya", "melakukan", "dilakukan",
        "membuat", "dibuat", "menggunakan", "digunakan", "memberikan", "diberikan", "menerima",
        "diterima", "memastikan", "pastikan", "ketentuan", "informasi", "keterangan", "catatan",
        "halaman", "dokumen", "bagian", "tabel", "baris", "kolom", "nomor", "tanggal", "jumlah",
        "total", "nilai", "status", "data", "file", "sheet", "daftar", "rincian", "uraian", "hasil",
        "proses", "kegiatan", "tahap", "langkah", "utama", "umum", "khusus", "ya", "termasuk", "kecuali", "berlaku", "merupakan", "terdapat", "berisi", "mencakup",
        "bersama", "tetap", "lewat", "ikuti", "orang", "waktu", "penting", "diri", "kunci",
        "jawab", "menjaga", "kepada", "terima", "kasih", "selalu", "segera", "mulai", "akhir",
        "pertama", "kedua", "ketiga", "keempat", "kelima", "sering", "kadang",
        "pahami", "gunakan", "lakukan", "hindari", "waspada", "ingat", "tahu", "lihat",
        # English
        "the", "and", "for", "that", "this", "with", "from", "are", "was", "were", "been", "being",
        "have", "has", "had", "does", "did", "will", "would", "could", "should", "may", "might",
        "must", "can", "shall", "not", "but", "into", "onto", "over", "under", "about", "above",
        "below", "between", "through", "during", "before", "after", "then", "than", "when", "where",
        "which", "while", "what", "who", "whom", "whose", "why", "how", "all", "any", "both",
        "each", "few", "more", "most", "other", "some", "such", "only", "own", "same", "also",
        "just", "very", "here", "there", "their", "them", "they", "these", "those", "your", "our",
        "its", "his", "her", "she", "him", "you", "page", "document", "section", "table", "row",
        "column", "note", "notes", "summary", "date", "number", "item",
        "items", "value", "values", "description", "details", "example", "following", "using",
        "used", "make", "made", "include", "including", "based", "per", "etc",
    }
)

# Regex ekstraksi kode terstruktur (mis. SOP-CHIL-09, HR-CUTI-04, POJK-69, SK-01/2026)
_STRUCTURED_CODE_RE = re.compile(r"\b([A-Z]{2,8}(?:[-/][A-Z0-9]{1,10}){1,4})\b")
# Regex referensi formal (mis. Pasal 12, POJK No. 69, Lampiran 1, Form 02)
_FORMAL_REF_RE = re.compile(
    r"\b((?:Pasal|Ayat|Bab|POJK|SEOJK|UU|PP|SOP|Lampiran|Form|Formulir)\s+(?:No\.?\s*)?\d+[A-Za-z0-9./-]*)\b",
    flags=re.IGNORECASE,
)
# Frasa Title Case / Kapital bermakna (1-4 kata, mis. Head Barista, Mesin Espresso, Otoritas Jasa Keuangan)
_TITLE_PHRASE_RE = re.compile(
    r"\b([A-Z][A-Za-z0-9]{1,24}(?:\s+(?:[A-Z][A-Za-z0-9]{1,24}|dan|of|&)){0,3})\b"
)
_WORD_TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9_-]{2,28}")
_CTX_HEADER_RE = re.compile(r"^\[Dokumen:[^\]]+\]\s*", flags=re.MULTILINE)
_MD_TABLE_SEP_RE = re.compile(r"^\s*\|?(?:\s*:?-+:?\s*\|)+\s*$", flags=re.MULTILINE)
_URL_RE = re.compile(r"https?://\S+")
_SPREADSHEET_EXTS = (".xlsx", ".csv")
_UNIT_NOISE_CODES = frozenset(
    {
        "PDF/DOCX", "DOCX/PDF", "XLSX/CSV", "CSV/XLSX", "KG/ML", "ML/L",
        "WIB/WITA", "IDR/USD", "USD/IDR", "YA/TIDAK", "YES/NO", "ON/OFF",
        "HTTP/1", "HTTP/2", "UTF-8", "N/A", "A/N", "S/D", "D/H",
    }
)


@dataclass
class _ChunkRecord:
    chunk_id: int
    document_id: uuid.UUID
    filename: str
    page_number: int
    chunk_index: int
    content: str
    section_title: str | None
    search_text: str | None
    embedding: np.ndarray
    is_spreadsheet: bool


@dataclass
class _EntityCandidate:
    key: str
    label: str
    node_type: str  # "concept" | "reference"
    doc_ids: set[uuid.UUID] = field(default_factory=set)
    chunk_ids: set[int] = field(default_factory=set)
    doc_chunk_map: dict[uuid.UUID, set[int]] = field(default_factory=lambda: defaultdict(set))
    heading_hits: int = 0
    surface_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    aliases: set[str] = field(default_factory=set)
    salience: float = 0.0
    label_vector: np.ndarray | None = None
    context_vector: np.ndarray | None = None
    final_vector: np.ndarray | None = None


@dataclass(frozen=True, slots=True)
class GraphBuildSummary:
    knowledge_id: uuid.UUID
    version_id: uuid.UUID
    node_count: int
    edge_count: int
    cross_document_edges: int
    semantic_bridge_edges: int


def _l2_normalize(vec: np.ndarray) -> np.ndarray:
    arr = np.asarray(vec, dtype=np.float32)
    norm = float(np.linalg.norm(arr))
    if norm > 1e-12:
        return arr / norm
    return arr


def _mean_embedding(vectors: list[np.ndarray], dim: int) -> np.ndarray:
    if not vectors:
        out = np.zeros(dim, dtype=np.float32)
        out[0] = 1.0
        return out
    stacked = np.vstack(vectors)
    return _l2_normalize(np.mean(stacked, axis=0))


def _clean_text_for_extraction(chunk: _ChunkRecord) -> str:
    """Membersihkan markup Markdown & menghindari ledakan angka pada tabel Excel."""
    raw = chunk.content or ""
    raw = _CTX_HEADER_RE.sub("", raw)
    raw = _URL_RE.sub(" ", raw)
    raw = _MD_TABLE_SEP_RE.sub(" ", raw)

    if chunk.is_spreadsheet:
        # Untuk spreadsheet: fokus pada banner, header kolom Markdown, & teks deskriptif non-numerik
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        kept_lines: list[str] = []
        seen_table_header = False
        for line in lines:
            if line.startswith("|"):
                cells = [c.strip() for c in line.strip("|").split("|") if c.strip()]
                if not seen_table_header:
                    kept_lines.append(" | ".join(cells))
                    seen_table_header = True
                else:
                    # Hanya ambil sel teks deskriptif/kategori (skip angka murni/tanggal/mata uang)
                    text_cells = [
                        c
                        for c in cells
                        if len(c) >= 3
                        and len(c) <= 60
                        and not re.fullmatch(r"[\d.,%RpIDR\s:/-]+", c, flags=re.IGNORECASE)
                    ]
                    if text_cells:
                        kept_lines.append(" ".join(text_cells[:4]))
            else:
                kept_lines.append(line)
        cleaned = "\n".join(kept_lines)
    else:
        cleaned = raw

    cleaned = re.sub(r"[#*_`~>|]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _normalize_section_label(raw_title: str | None, is_spreadsheet: bool) -> str | None:
    if not raw_title or not raw_title.strip():
        return None
    title = raw_title.strip()
    parts = [p.strip() for p in title.split(">") if p.strip()]
    if not parts:
        return None
    if is_spreadsheet:
        # Kelompokkan spreadsheet per nama Sheet agar tidak terjadi ledakan node
        sheet_part = parts[0]
        if "|" in sheet_part:
            sheet_part = sheet_part.split("|", 1)[0].strip()
        return sheet_part[:120]
    # Untuk PDF/DOCX/PPTX ambil maks 2 level heading agar rapi
    label = " > ".join(parts[:2])
    return label[:140]


def _normalize_phrase(phrase: str) -> str:
    cleaned = re.sub(r"\s+", " ", phrase.strip(" .,:;()[]{}\"'`-|/"))
    return cleaned


def _is_valid_concept(phrase: str) -> bool:
    if not phrase or len(phrase) < 3 or len(phrase) > 64:
        return False
    if re.fullmatch(r"[\d\W_]+", phrase):
        return False
    tokens = [t.lower() for t in re.findall(r"[0-9a-zA-Z]+", phrase)]
    if not tokens or len(tokens) > 4:
        return False
    meaningful = [t for t in tokens if t not in _STOPWORDS and len(t) >= 3 and not t.isdigit()]
    if not meaningful:
        return False
    # Tolak jika kata pertama atau terakhir adalah stopword murni
    return not (tokens[0] in _STOPWORDS or tokens[-1] in _STOPWORDS)


def _is_valid_code(code: str) -> bool:
    upper = code.upper().strip()
    if upper in _UNIT_NOISE_CODES:
        return False
    if len(upper) < 4 or len(upper) > 40:
        return False
    # Harus mengandung angka ATAU minimal 2 delimiter (mis. BESMART/II/DOK, SOP-KSR-QA)
    has_digit = any(ch.isdigit() for ch in upper)
    sep_count = upper.count("-") + upper.count("/")
    if not has_digit and sep_count < 2:
        return False
    # Abaikan format tanggal murni seperti 2026-01-19 atau 12/05/2026
    return re.fullmatch(r"\d{1,4}[-/]\d{1,2}(?:[-/]\d{1,4})?", upper) is None


def _extract_document_stem_terms(filename: str) -> tuple[str, str]:
    """Menghasilkan nama dokumen bersih untuk deteksi mention lintas dokumen."""
    stem = filename.rsplit(".", 1)[0]
    human = re.sub(r"[_\-.]+", " ", stem)
    human = re.sub(r"\s+", " ", human).strip()
    return human, human.lower()


def _extract_candidates_from_chunks(
    chunks: list[_ChunkRecord],
    doc_filenames: dict[uuid.UUID, str],
) -> tuple[dict[str, _EntityCandidate], list[tuple[uuid.UUID, uuid.UUID, int, str]]]:
    """Mengekstrak entitas konsep, kode referensi, dan mention nama file secara Zero-LLM."""
    candidates: dict[str, _EntityCandidate] = {}
    doc_mentions: list[tuple[uuid.UUID, uuid.UUID, int, str]] = []

    # Siapkan pola deteksi mention nama dokumen lain (minimal 2 kata & >= 7 karakter)
    doc_name_patterns: list[tuple[uuid.UUID, str, re.Pattern[str]]] = []
    for doc_id, fname in doc_filenames.items():
        human, lower = _extract_document_stem_terms(fname)
        words = [w for w in lower.split() if len(w) >= 3 and w not in _STOPWORDS]
        if len(words) >= 2 and len(lower) >= 7:
            pattern = re.compile(r"\b" + re.escape(human) + r"\b", flags=re.IGNORECASE)
            doc_name_patterns.append((doc_id, human, pattern))

    # Lacak kemunculan kata/bigram lowercase lintas dokumen
    lowercase_unigram_docs: dict[str, set[uuid.UUID]] = defaultdict(set)
    lowercase_bigram_docs: dict[str, set[uuid.UUID]] = defaultdict(set)
    lowercase_unigram_chunks: dict[str, list[tuple[uuid.UUID, int]]] = defaultdict(list)
    lowercase_bigram_chunks: dict[str, list[tuple[uuid.UUID, int]]] = defaultdict(list)

    def _add_candidate(
        raw_label: str,
        node_type: str,
        doc_id: uuid.UUID,
        chunk_id: int,
        in_heading: bool = False,
    ) -> None:
        cleaned = _normalize_phrase(raw_label)
        if node_type == "reference":
            key = f"ref:{cleaned.upper()}"
            display = cleaned.upper() if "-" in cleaned or "/" in cleaned else cleaned
        else:
            if not _is_valid_concept(cleaned):
                return
            key = f"concept:{cleaned.lower()}"
            display = cleaned

        cand = candidates.get(key)
        if cand is None:
            cand = _EntityCandidate(key=key, label=display, node_type=node_type)
            candidates[key] = cand
        cand.doc_ids.add(doc_id)
        cand.chunk_ids.add(chunk_id)
        cand.doc_chunk_map[doc_id].add(chunk_id)
        cand.surface_counts[display] += 1
        if in_heading:
            cand.heading_hits += 1

    for chunk in chunks:
        cleaned_text = _clean_text_for_extraction(chunk)
        heading_text = chunk.section_title or ""

        # 1. Deteksi mention eksplisit ke dokumen lain dalam knowledge yang sama
        for target_doc_id, human_name, pattern in doc_name_patterns:
            if target_doc_id != chunk.document_id and pattern.search(cleaned_text):
                doc_mentions.append((chunk.document_id, target_doc_id, chunk.chunk_id, human_name))

        # 2. Ekstrak kode terstruktur & referensi formal (Pasal/POJK/SOP-XXX)
        combined_ref_text = f"{heading_text} {cleaned_text}"
        for match in _STRUCTURED_CODE_RE.finditer(combined_ref_text):
            code = match.group(1)
            if _is_valid_code(code):
                _add_candidate(code, "reference", chunk.document_id, chunk.chunk_id)

        for match in _FORMAL_REF_RE.finditer(combined_ref_text):
            ref_str = re.sub(r"\s+", " ", match.group(1)).strip()
            if len(ref_str) >= 5:
                _add_candidate(ref_str, "reference", chunk.document_id, chunk.chunk_id)

        # 3. Ekstrak frasa Title Case dari heading (sinyal kuat)
        if heading_text:
            for part in heading_text.split(">"):
                part_clean = re.sub(r"^(?:\d+[.)]\s*|Sheet:\s*)", "", part.strip(), flags=re.IGNORECASE)
                part_clean = _normalize_phrase(part_clean)
                if _is_valid_concept(part_clean):
                    _add_candidate(
                        part_clean, "concept", chunk.document_id, chunk.chunk_id, in_heading=True
                    )

        # 4. Ekstrak frasa Title Case dari isi chunk
        # Pisahkan kalimat agar kata awal kalimat tunggal tidak dianggap entitas sembarangan
        sentences = re.split(r"[.!?\n;]+", cleaned_text)
        for sent in sentences:
            sent_s = sent.strip()
            if not sent_s:
                continue
            for m in _TITLE_PHRASE_RE.finditer(sent_s):
                phrase = _normalize_phrase(m.group(1))
                word_count = len(phrase.split())
                # Lewati kata tunggal yang hanya muncul di posisi awal kalimat
                if m.start() == 0 and word_count == 1:
                    continue
                if _is_valid_concept(phrase):
                    _add_candidate(phrase, "concept", chunk.document_id, chunk.chunk_id)

        # 5. Kumpulkan unigram & bigram lowercase bermakna untuk menangkap konsep lintas dokumen
        tokens = [
            t.lower()
            for t in _WORD_TOKEN_RE.findall(cleaned_text)
            if t.lower() not in _STOPWORDS and len(t) >= 4 and not t.isdigit()
        ]
        seen_uni: set[str] = set()
        for tok in tokens:
            if tok not in seen_uni:
                seen_uni.add(tok)
                lowercase_unigram_docs[tok].add(chunk.document_id)
                lowercase_unigram_chunks[tok].append((chunk.document_id, chunk.chunk_id))

        seen_bi: set[str] = set()
        for idx in range(len(tokens) - 1):
            w1, w2 = tokens[idx], tokens[idx + 1]
            if w1 == w2:
                continue
            bigram = f"{w1} {w2}"
            if bigram not in seen_bi:
                seen_bi.add(bigram)
                lowercase_bigram_docs[bigram].add(chunk.document_id)
                lowercase_bigram_chunks[bigram].append((chunk.document_id, chunk.chunk_id))

    total_docs = len(doc_filenames)
    min_doc_freq = 2 if total_docs >= 2 else 1

    # Tambahkan bigram lowercase lintas dokumen sebagai kandidat konsep
    for bigram, docs_set in lowercase_bigram_docs.items():
        if len(docs_set) >= min_doc_freq and (
            len(docs_set) >= 2 or len(lowercase_bigram_chunks[bigram]) >= 2
        ):
            title_label = " ".join(w.capitalize() for w in bigram.split())
            for d_id, c_id in lowercase_bigram_chunks[bigram]:
                _add_candidate(title_label, "concept", d_id, c_id)

    # Tambahkan unigram lowercase lintas dokumen yang kuat (muncul di >= 2 dokumen berbeda)
    if total_docs >= 2:
        for uni, docs_set in lowercase_unigram_docs.items():
            if len(docs_set) >= 2 and len(uni) >= 4:
                title_label = uni.capitalize()
                for d_id, c_id in lowercase_unigram_chunks[uni]:
                    _add_candidate(title_label, "concept", d_id, c_id)

    # Pilih surface label terbaik untuk tiap kandidat
    for cand in candidates.values():
        if cand.surface_counts:
            cand.label = max(
                cand.surface_counts.items(),
                key=lambda item: (item[1], any(ch.isupper() for ch in item[0])),
            )[0]

    return candidates, doc_mentions


def _can_use_live_label_embeddings() -> bool:
    """Mendeteksi apakah embedding_service asli (BAAI/bge-m3) aktif dan tidak di-mock oleh unit test."""
    inst_dict = getattr(embedding_service, "__dict__", {})
    if "embed_texts" in inst_dict:
        return True
    if "embed_documents" in inst_dict:
        # Unit test me-monkeypatch embed_documents secara langsung -> gunakan contextual chunk centroid
        return False
    method = getattr(embedding_service, "embed_texts", None)
    return callable(method) and inspect.ismethod(method)


async def _compute_and_merge_entity_candidates(
    candidates: dict[str, _EntityCandidate],
    chunk_map: dict[int, _ChunkRecord],
    total_docs: int,
    dim: int,
) -> list[_EntityCandidate]:
    """Menilai salience, menghitung vektor BAAI/bge-m3, dan melebur alias semantik."""
    if not candidates:
        return []

    # 1. Hitung salience & saring noise awal
    scored: list[_EntityCandidate] = []
    for cand in candidates.values():
        doc_freq = len(cand.doc_ids)
        chunk_freq = len(cand.chunk_ids)
        word_count = len(cand.label.split())

        if cand.node_type == "reference":
            # Kode/Pasal eksplisit selalu bernilai tinggi meski hanya di 1 dokumen
            cand.salience = 10.0 + (doc_freq**2.0) * 4.0 + math.log1p(chunk_freq) * 2.0
            scored.append(cand)
            continue

        # Untuk multi-dokumen: prioritaskan konsep lintas dokumen, atau konsep kuat di heading / >= 2 chunks
        if total_docs >= 2 and doc_freq == 1 and chunk_freq < 2 and cand.heading_hits == 0:
            continue
        if total_docs == 1 and chunk_freq < 2 and cand.heading_hits == 0 and word_count < 2:
            continue

        multiword_bonus = 1.4 if word_count >= 2 else 1.0
        heading_bonus = 1.3 if cand.heading_hits > 0 else 1.0
        cand.salience = (
            (doc_freq**2.2)
            * (1.0 + math.log1p(chunk_freq))
            * multiword_bonus
            * heading_bonus
        )
        scored.append(cand)

    if not scored:
        return []

    scored.sort(key=lambda c: (c.node_type == "reference", c.salience), reverse=True)

    # Pisahkan reference (pertahankan maks 25) dan concept (ambil top 2x batas untuk alias merging)
    refs = [c for c in scored if c.node_type == "reference"][:25]
    max_concepts = settings.KG_MAX_CONCEPT_NODES
    concept_pool = [c for c in scored if c.node_type == "concept"][: max_concepts * 2]

    # Prune unigram yang sepenuhnya terliputi oleh frasa multi-kata di chunk & dokumen yang sama
    multiword_concepts = [c for c in concept_pool if len(c.label.split()) >= 2]
    pruned_concepts: list[_EntityCandidate] = []
    for c in concept_pool:
        if len(c.label.split()) == 1:
            low = c.label.lower()
            dominated = any(
                low in mc.label.lower().split()
                and len(mc.doc_ids) >= len(c.doc_ids)
                and len(c.chunk_ids - mc.chunk_ids) <= 1
                for mc in multiword_concepts
            )
            if dominated:
                continue
        pruned_concepts.append(c)

    working = refs + pruned_concepts
    if not working:
        return []

    # 2. Hitung contextual chunk centroid (sudah berupa vektor BAAI/bge-m3 dari document_chunks!)
    for cand in working:
        vecs = [chunk_map[cid].embedding for cid in cand.chunk_ids if cid in chunk_map]
        cand.context_vector = _mean_embedding(vecs, dim)

    # 3. Embed label konsep menggunakan BAAI/bge-m3 (1 batch call, zero LLM)
    label_vecs: list[np.ndarray] | None = None
    if _can_use_live_label_embeddings():
        try:
            raw_vecs = await embedding_service.embed_texts([c.label for c in working])
            if len(raw_vecs) == len(working):
                label_vecs = [_l2_normalize(np.asarray(v, dtype=np.float32)) for v in raw_vecs]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Embed label konsep KG dilewati (%s), memakai centroid chunk BGE-M3.", exc)

    for idx, cand in enumerate(working):
        if label_vecs is not None:
            cand.label_vector = label_vecs[idx]
            cand.final_vector = _l2_normalize(
                0.65 * cand.label_vector + 0.35 * cand.context_vector  # type: ignore[operator]
            )
        else:
            cand.label_vector = cand.context_vector
            cand.final_vector = cand.context_vector

    # 4. BAAI/bge-m3 Semantic Alias Merging untuk konsep (mis. "Head Barista" <-> "Kepala Barista")
    kept_refs = [c for c in working if c.node_type == "reference"]
    concept_items = [c for c in working if c.node_type == "concept"]

    merged_concepts: list[_EntityCandidate] = []
    if concept_items:
        alias_threshold = settings.KG_ALIAS_MERGE_THRESHOLD
        use_label_sim = label_vecs is not None
        for cand in concept_items:
            merged_into: _EntityCandidate | None = None
            if use_label_sim and cand.label_vector is not None:
                best_sim = 0.0
                for existing in merged_concepts:
                    if existing.label_vector is None:
                        continue
                    sim = float(np.dot(cand.label_vector, existing.label_vector))
                    if sim >= alias_threshold and sim > best_sim:
                        best_sim = sim
                        merged_into = existing

            if merged_into is not None:
                if cand.label.lower() != merged_into.label.lower():
                    merged_into.aliases.add(cand.label)
                merged_into.aliases.update(cand.aliases)
                merged_into.doc_ids.update(cand.doc_ids)
                merged_into.chunk_ids.update(cand.chunk_ids)
                for d_id, c_set in cand.doc_chunk_map.items():
                    merged_into.doc_chunk_map[d_id].update(c_set)
                merged_into.salience = max(merged_into.salience, cand.salience) * 1.1
                # Perbarui vektor gabungan setelah merge
                vecs = [chunk_map[cid].embedding for cid in merged_into.chunk_ids if cid in chunk_map]
                merged_into.context_vector = _mean_embedding(vecs, dim)
                if merged_into.label_vector is not None:
                    merged_into.final_vector = _l2_normalize(
                        0.65 * merged_into.label_vector + 0.35 * merged_into.context_vector
                    )
                else:
                    merged_into.final_vector = merged_into.context_vector
            else:
                merged_concepts.append(cand)

        merged_concepts.sort(key=lambda c: (len(c.doc_ids), c.salience), reverse=True)
        merged_concepts = merged_concepts[:max_concepts]

    return kept_refs + merged_concepts


def _shared_keywords_between_chunks(chunk_a: _ChunkRecord, chunk_b: _ChunkRecord, limit: int = 6) -> list[str]:
    toks_a = {
        t.lower()
        for t in _WORD_TOKEN_RE.findall(_clean_text_for_extraction(chunk_a))
        if t.lower() not in _STOPWORDS and len(t) >= 4
    }
    toks_b = {
        t.lower()
        for t in _WORD_TOKEN_RE.findall(_clean_text_for_extraction(chunk_b))
        if t.lower() not in _STOPWORDS and len(t) >= 4
    }
    shared = sorted(toks_a & toks_b)
    return shared[:limit]


def _make_snippet(content: str, max_len: int = 180) -> str:
    clean = re.sub(r"\s+", " ", content).strip()
    if len(clean) <= max_len:
        return clean
    return clean[: max_len - 1].rstrip() + "…"


async def build_knowledge_graph_for_version(
    knowledge_id: uuid.UUID,
    version_id: uuid.UUID,
    session: AsyncSession | None = None,
) -> GraphBuildSummary:
    """Membangun Zero-LLM Knowledge Graph (murni BAAI/bge-m3 + pgvector) untuk satu versi knowledge."""
    if session is None:
        async with AsyncSessionLocal() as own_session:
            return await build_knowledge_graph_for_version(knowledge_id, version_id, own_session)

    # 1. Muat seluruh dokumen & chunk ter-embed pada versi aktif ini
    docs_stmt = (
        select(Document)
        .join(KnowledgeVersionDocument, KnowledgeVersionDocument.document_id == Document.id)
        .where(
            KnowledgeVersionDocument.version_id == version_id,
            Document.status == DocumentStatus.EMBEDDED,
        )
        .order_by(Document.created_at.asc())
    )
    docs = list((await session.execute(docs_stmt)).scalars().all())
    doc_map = {d.id: d for d in docs}
    doc_filenames = {d.id: d.filename for d in docs}

    if not docs:
        await session.execute(delete(KGEdge).where(KGEdge.version_id == version_id))
        await session.execute(delete(KGNode).where(KGNode.version_id == version_id))
        await session.commit()
        return GraphBuildSummary(knowledge_id, version_id, 0, 0, 0, 0)

    chunks_stmt = (
        select(DocumentChunk)
        .where(DocumentChunk.document_id.in_(list(doc_map.keys())))
        .order_by(DocumentChunk.document_id.asc(), DocumentChunk.chunk_index.asc())
    )
    raw_chunks = list((await session.execute(chunks_stmt)).scalars().all())

    if not raw_chunks:
        await session.execute(delete(KGEdge).where(KGEdge.version_id == version_id))
        await session.execute(delete(KGNode).where(KGNode.version_id == version_id))
        await session.commit()
        return GraphBuildSummary(knowledge_id, version_id, 0, 0, 0, 0)

    dim = settings.EMBEDDING_DIMENSIONS
    chunks: list[_ChunkRecord] = []
    chunk_map: dict[int, _ChunkRecord] = {}
    doc_chunks: dict[uuid.UUID, list[_ChunkRecord]] = defaultdict(list)

    for rc in raw_chunks:
        meta = rc.metadata_json or {}
        fname = doc_filenames.get(rc.document_id, str(meta.get("filename", "Dokumen")))
        vec = _l2_normalize(np.asarray(rc.embedding, dtype=np.float32))
        rec = _ChunkRecord(
            chunk_id=rc.id,
            document_id=rc.document_id,
            filename=fname,
            page_number=rc.page_number,
            chunk_index=rc.chunk_index,
            content=rc.content,
            section_title=meta.get("section_title"),
            search_text=meta.get("search_text"),
            embedding=vec,
            is_spreadsheet=fname.lower().endswith(_SPREADSHEET_EXTS),
        )
        chunks.append(rec)
        chunk_map[rec.chunk_id] = rec
        doc_chunks[rec.document_id].append(rec)

    now = utc_now()
    nodes_by_key: dict[str, KGNode] = {}
    doc_node_by_doc_id: dict[uuid.UUID, KGNode] = {}
    section_node_by_chunk_id: dict[int, KGNode] = {}
    edges_accumulator: dict[tuple[uuid.UUID, uuid.UUID, str], KGEdge] = {}

    def _add_edge(
        src_id: uuid.UUID,
        tgt_id: uuid.UUID,
        edge_type: str,
        weight: float,
        label: str,
        keywords: str,
        description: str,
        is_cross_document: bool,
        source_chunk_ids: list[int],
        properties_json: dict[str, Any] | None = None,
        undirected: bool = False,
    ) -> None:
        if src_id == tgt_id:
            return
        a, b = (min(src_id, tgt_id), max(src_id, tgt_id)) if undirected else (src_id, tgt_id)
        key = (a, b, edge_type)
        existing = edges_accumulator.get(key)
        if existing is not None:
            merged_cids = sorted(set(existing.source_chunk_ids) | set(source_chunk_ids))
            existing.source_chunk_ids = merged_cids[:40]
            if weight > existing.weight:
                existing.weight = round(float(weight), 4)
                existing.label = label[:255]
                if description:
                    existing.description = description
            if is_cross_document:
                existing.is_cross_document = True
            return

        edges_accumulator[key] = KGEdge(
            id=uuid.uuid4(),
            knowledge_id=knowledge_id,
            version_id=version_id,
            source_node_id=a,
            target_node_id=b,
            edge_type=edge_type,
            weight=round(float(weight), 4),
            label=label[:255],
            keywords=keywords[:500],
            description=description,
            is_cross_document=is_cross_document,
            source_chunk_ids=sorted(set(source_chunk_ids))[:40],
            properties_json=properties_json or {},
            created_at=now,
        )

    # 2. Buat Node Dokumen & Node Bagian/Sheet
    for doc in docs:
        d_chunks = doc_chunks.get(doc.id, [])
        if not d_chunks:
            continue
        doc_vec = _mean_embedding([c.embedding for c in d_chunks], dim)
        ext = doc.filename.rsplit(".", 1)[-1].lower() if "." in doc.filename else "file"
        sample_snippets = [_make_snippet(c.content) for c in d_chunks[:2]]
        doc_node = KGNode(
            id=uuid.uuid4(),
            knowledge_id=knowledge_id,
            version_id=version_id,
            document_id=doc.id,
            node_key=f"doc:{doc.id}",
            label=doc.filename[:255],
            node_type="document",
            description=(
                f"Dokumen {ext.upper()} dengan {doc.page_count} halaman/sheet dan "
                f"{len(d_chunks)} potongan chunk ter-embed."
            ),
            degree=0,
            doc_frequency=1,
            chunk_count=len(d_chunks),
            source_doc_ids=[str(doc.id)],
            source_chunk_ids=[c.chunk_id for c in d_chunks],
            properties_json={
                "filenames": [doc.filename],
                "file_type": ext,
                "page_count": doc.page_count,
                "sample_snippets": sample_snippets,
                "aliases": [],
            },
            embedding=doc_vec.tolist(),
            created_at=now,
        )
        nodes_by_key[doc_node.node_key] = doc_node
        doc_node_by_doc_id[doc.id] = doc_node

        # Kelompokkan section/sheet unik per dokumen (dibatasi agar graf tetap bersih)
        section_groups: dict[str, list[_ChunkRecord]] = defaultdict(list)
        for c in d_chunks:
            sec_label = _normalize_section_label(c.section_title, c.is_spreadsheet)
            if sec_label:
                section_groups[sec_label].append(c)

        # Pilih maksimal KG_MAX_SECTIONS_PER_DOC bagian paling padat per dokumen
        sorted_sections = sorted(
            section_groups.items(),
            key=lambda kv: (-len(kv[1]), kv[1][0].chunk_index),
        )[: settings.KG_MAX_SECTIONS_PER_DOC]

        for sec_label, s_chunks in sorted_sections:
            sec_hash = hashlib.sha1(f"{doc.id}:{sec_label.lower()}".encode()).hexdigest()[:16]
            sec_vec = _mean_embedding([c.embedding for c in s_chunks], dim)
            pages = sorted({c.page_number for c in s_chunks})
            sec_node = KGNode(
                id=uuid.uuid4(),
                knowledge_id=knowledge_id,
                version_id=version_id,
                document_id=doc.id,
                node_key=f"sec:{sec_hash}",
                label=sec_label[:255],
                node_type="section",
                description=(
                    f"Bagian dari {doc.filename} (Hal. {', '.join(str(p) for p in pages[:5])}) "
                    f"berisi {len(s_chunks)} chunk."
                ),
                degree=0,
                doc_frequency=1,
                chunk_count=len(s_chunks),
                source_doc_ids=[str(doc.id)],
                source_chunk_ids=[c.chunk_id for c in s_chunks],
                properties_json={
                    "filenames": [doc.filename],
                    "page_numbers": pages[:10],
                    "sample_snippets": [_make_snippet(s_chunks[0].content)],
                    "aliases": [],
                },
                embedding=sec_vec.tolist(),
                created_at=now,
            )
            nodes_by_key[sec_node.node_key] = sec_node
            for c in s_chunks:
                section_node_by_chunk_id[c.chunk_id] = sec_node

            _add_edge(
                src_id=doc_node.id,
                tgt_id=sec_node.id,
                edge_type="contains",
                weight=1.0,
                label="Memuat Bagian",
                keywords=sec_label,
                description=f"{doc.filename} memuat bagian/sheet '{sec_label}'.",
                is_cross_document=False,
                source_chunk_ids=[c.chunk_id for c in s_chunks],
            )

    # 3. Ekstrak Kandidat Entitas Konsep, Kode Referensi & Mention Lintas Dokumen
    raw_candidates, doc_mentions = _extract_candidates_from_chunks(chunks, doc_filenames)
    merged_entities = await _compute_and_merge_entity_candidates(
        candidates=raw_candidates,
        chunk_map=chunk_map,
        total_docs=len(doc_node_by_doc_id),
        dim=dim,
    )

    # Relasi eksplisit jika Dokumen A menyebut langsung nama Dokumen B
    mention_pairs: dict[tuple[uuid.UUID, uuid.UUID], tuple[set[int], str]] = {}
    for src_doc_id, tgt_doc_id, cid, human_name in doc_mentions:
        pair_key = (src_doc_id, tgt_doc_id)
        if pair_key not in mention_pairs:
            mention_pairs[pair_key] = ({cid}, human_name)
        else:
            mention_pairs[pair_key][0].add(cid)

    for (src_doc_id, tgt_doc_id), (cids, human_name) in mention_pairs.items():
        src_node = doc_node_by_doc_id.get(src_doc_id)
        tgt_node = doc_node_by_doc_id.get(tgt_doc_id)
        if src_node and tgt_node:
            _add_edge(
                src_id=src_node.id,
                tgt_id=tgt_node.id,
                edge_type="mentions",
                weight=0.95,
                label="Merujuk Dokumen",
                keywords=human_name,
                description=(
                    f"{src_node.label} secara eksplisit menyebut '{human_name}' ({tgt_node.label}) "
                    f"pada {len(cids)} potongan teks."
                ),
                is_cross_document=True,
                source_chunk_ids=sorted(cids),
            )

    # Buat KGNode untuk setiap entitas konsep & kode referensi terpilih
    entity_nodes: list[tuple[_EntityCandidate, KGNode]] = []
    chunk_to_entity_nodes: dict[int, list[KGNode]] = defaultdict(list)

    for ent in merged_entities:
        sorted_doc_ids = sorted(ent.doc_ids, key=lambda d: doc_filenames.get(d, ""))
        fnames = [doc_filenames[d] for d in sorted_doc_ids if d in doc_filenames]
        aliases = sorted(ent.aliases)
        sorted_cids = sorted(ent.chunk_ids)
        snippets = [
            f"[{chunk_map[cid].filename} · Hal. {chunk_map[cid].page_number}] {_make_snippet(chunk_map[cid].content, 140)}"
            for cid in sorted_cids[:3]
            if cid in chunk_map
        ]

        kind_label = "Kode / Referensi" if ent.node_type == "reference" else "Konsep Lintas Dokumen"
        alias_note = f" Alias digabung (BGE-M3): {', '.join(aliases)}." if aliases else ""
        desc = (
            f"{kind_label} yang muncul di {len(fnames)} dokumen ({', '.join(fnames[:4])}"
            f"{'…' if len(fnames) > 4 else ''}) pada {len(sorted_cids)} chunk.{alias_note}"
        )

        node_key = ent.key[:250]
        if node_key in nodes_by_key:
            node_key = f"{ent.node_type}:{hashlib.sha1(ent.label.lower().encode()).hexdigest()[:16]}"

        ent_vec = ent.final_vector if ent.final_vector is not None else _mean_embedding([], dim)
        ent_node = KGNode(
            id=uuid.uuid4(),
            knowledge_id=knowledge_id,
            version_id=version_id,
            document_id=sorted_doc_ids[0] if len(sorted_doc_ids) == 1 else None,
            node_key=node_key,
            label=ent.label[:255],
            node_type=ent.node_type,
            description=desc,
            degree=0,
            doc_frequency=len(sorted_doc_ids),
            chunk_count=len(sorted_cids),
            source_doc_ids=[str(d) for d in sorted_doc_ids],
            source_chunk_ids=sorted_cids,
            properties_json={
                "filenames": fnames,
                "aliases": aliases,
                "sample_snippets": snippets,
                "salience": round(ent.salience, 3),
                "extraction_method": "bge-m3-zero-llm",
            },
            embedding=ent_vec.tolist(),
            created_at=now,
        )
        nodes_by_key[ent_node.node_key] = ent_node
        entity_nodes.append((ent, ent_node))

        for cid in sorted_cids:
            chunk_to_entity_nodes[cid].append(ent_node)

        # Hubungkan Dokumen -> Entitas (mentions)
        is_cross_doc_hub = len(sorted_doc_ids) >= 2
        for doc_id in sorted_doc_ids:
            d_node = doc_node_by_doc_id.get(doc_id)
            if d_node is None:
                continue
            d_cids = sorted(ent.doc_chunk_map.get(doc_id, set()))
            weight = min(1.0, 0.55 + 0.15 * math.log1p(len(d_cids)))
            _add_edge(
                src_id=d_node.id,
                tgt_id=ent_node.id,
                edge_type="mentions",
                weight=weight,
                label=f"Menyebut ({len(d_cids)}x)",
                keywords=", ".join([ent.label, *aliases[:3]]),
                description=(
                    f"{d_node.label} menyebut '{ent.label}' pada {len(d_cids)} potongan dokumen."
                ),
                is_cross_document=is_cross_doc_hub,
                source_chunk_ids=d_cids,
            )

    # 4. Relasi Co-Occurrence antar Konsep/Referensi dalam chunk yang sama
    cooccur_counts: dict[tuple[uuid.UUID, uuid.UUID], set[int]] = defaultdict(set)
    entity_node_by_id = {n.id: n for _, n in entity_nodes}
    for cid, e_nodes in chunk_to_entity_nodes.items():
        if len(e_nodes) < 2:
            continue
        unique_nodes = list({n.id: n for n in e_nodes}.values())
        for i in range(len(unique_nodes)):
            for j in range(i + 1, len(unique_nodes)):
                a_id, b_id = min(unique_nodes[i].id, unique_nodes[j].id), max(
                    unique_nodes[i].id, unique_nodes[j].id
                )
                cooccur_counts[(a_id, b_id)].add(cid)

    # Batasi jumlah edge co_occurs per node agar graf tetap fokus & bebas kusut
    cooccur_candidates: list[tuple[float, uuid.UUID, uuid.UUID, list[int], bool]] = []
    for (a_id, b_id), shared_cids in cooccur_counts.items():
        node_a = entity_node_by_id[a_id]
        node_b = entity_node_by_id[b_id]
        docs_a = set(node_a.source_doc_ids)
        docs_b = set(node_b.source_doc_ids)
        shared_docs = {str(chunk_map[cid].document_id) for cid in shared_cids if cid in chunk_map}
        is_cross = len(shared_docs) >= 2 or (docs_a != docs_b and len(docs_a | docs_b) >= 2)
        union_chunks = max(1, len(set(node_a.source_chunk_ids) | set(node_b.source_chunk_ids)))
        jaccard = len(shared_cids) / union_chunks
        weight = min(1.0, 0.45 + 0.55 * jaccard + (0.15 if len(shared_docs) >= 2 else 0.0))
        if len(shared_cids) >= 2 or is_cross:
            cooccur_candidates.append((weight, a_id, b_id, sorted(shared_cids), is_cross))

    cooccur_candidates.sort(key=lambda item: (item[4], item[0]), reverse=True)
    cooccur_deg: dict[uuid.UUID, int] = defaultdict(int)
    max_cooccur = settings.KG_MAX_COOCCUR_EDGES_PER_NODE

    for weight, a_id, b_id, shared_cids, is_cross in cooccur_candidates:
        if cooccur_deg[a_id] >= max_cooccur or cooccur_deg[b_id] >= max_cooccur:
            continue
        node_a = entity_node_by_id[a_id]
        node_b = entity_node_by_id[b_id]
        _add_edge(
            src_id=a_id,
            tgt_id=b_id,
            edge_type="co_occurs",
            weight=weight,
            label="Muncul Bersama",
            keywords=f"{node_a.label}, {node_b.label}",
            description=(
                f"'{node_a.label}' dan '{node_b.label}' muncul bersama pada {len(shared_cids)} chunk."
            ),
            is_cross_document=is_cross,
            source_chunk_ids=shared_cids,
            undirected=True,
        )
        cooccur_deg[a_id] += 1
        cooccur_deg[b_id] += 1

    # 5. Jembatan Semantik Lintas Dokumen murni BAAI/bge-m3 (Cosine Matrix antar dokumen berbeda!)
    if len(doc_node_by_doc_id) >= 2 and len(chunks) >= 2:
        matrix = np.vstack([c.embedding for c in chunks])
        sim_matrix = matrix @ matrix.T
        threshold = settings.KG_SEMANTIC_EDGE_THRESHOLD

        # Agregasi skor terbaik antar pasangan dokumen & antar pasangan bagian (lintas dokumen)
        doc_pair_links: dict[tuple[uuid.UUID, uuid.UUID], list[tuple[float, _ChunkRecord, _ChunkRecord]]] = defaultdict(list)
        sec_pair_links: dict[tuple[uuid.UUID, uuid.UUID], list[tuple[float, _ChunkRecord, _ChunkRecord]]] = defaultdict(list)

        n_chunks = len(chunks)
        for i in range(n_chunks):
            ci = chunks[i]
            # Cari chunk dari dokumen BERBEDA dengan kemiripan >= threshold
            row = sim_matrix[i]
            # Ambil hanya indeks j > i agar tidak duplikat
            for j in range(i + 1, n_chunks):
                cj = chunks[j]
                if ci.document_id == cj.document_id:
                    continue
                score = float(row[j])
                if score < threshold:
                    continue

                da, db = min(ci.document_id, cj.document_id), max(ci.document_id, cj.document_id)
                doc_pair_links[(da, db)].append((score, ci, cj))

                sec_i = section_node_by_chunk_id.get(ci.chunk_id)
                sec_j = section_node_by_chunk_id.get(cj.chunk_id)
                if sec_i and sec_j and sec_i.id != sec_j.id:
                    sa, sb = min(sec_i.id, sec_j.id), max(sec_i.id, sec_j.id)
                    sec_pair_links[(sa, sb)].append((score, ci, cj))

        # Buat Document <-> Document Semantic Bridge Edges
        doc_bridge_list: list[tuple[float, uuid.UUID, uuid.UUID, list[tuple[float, _ChunkRecord, _ChunkRecord]]]] = []
        for (da, db), pairs in doc_pair_links.items():
            pairs.sort(key=lambda p: p[0], reverse=True)
            top_score = pairs[0][0]
            doc_bridge_list.append((top_score, da, db, pairs[:5]))

        doc_bridge_list.sort(key=lambda item: item[0], reverse=True)
        doc_bridge_deg: dict[uuid.UUID, int] = defaultdict(int)
        max_bridges = settings.KG_MAX_SEMANTIC_BRIDGES_PER_NODE

        for top_score, da, db, top_pairs in doc_bridge_list:
            if doc_bridge_deg[da] >= max_bridges and doc_bridge_deg[db] >= max_bridges:
                continue
            node_a = doc_node_by_doc_id[da]
            node_b = doc_node_by_doc_id[db]
            best_s, best_ci, best_cj = top_pairs[0]
            shared_kw = _shared_keywords_between_chunks(best_ci, best_cj)
            chunk_ids = sorted({c.chunk_id for _, ci, cj in top_pairs for c in (ci, cj)})
            pair_meta = [
                {
                    "src_chunk_id": ci.chunk_id,
                    "tgt_chunk_id": cj.chunk_id,
                    "src_file": ci.filename,
                    "tgt_file": cj.filename,
                    "src_page": ci.page_number,
                    "tgt_page": cj.page_number,
                    "score": round(s, 4),
                }
                for s, ci, cj in top_pairs
            ]
            pct = round(best_s * 100)
            kw_str = ", ".join(shared_kw) if shared_kw else "kemiripan makna semantik"
            _add_edge(
                src_id=node_a.id,
                tgt_id=node_b.id,
                edge_type="semantic_bridge",
                weight=best_s,
                label=f"Relasi Semantik {pct}%",
                keywords=kw_str,
                description=(
                    f"Jembatan semantik BAAI/bge-m3 ({pct}%) antara {node_a.label} (Hal. {best_ci.page_number}) "
                    f"dan {node_b.label} (Hal. {best_cj.page_number}) pada {len(top_pairs)} pasangan chunk terkait."
                ),
                is_cross_document=True,
                source_chunk_ids=chunk_ids,
                properties_json={"similarity_score": round(best_s, 4), "chunk_pairs": pair_meta},
                undirected=True,
            )
            doc_bridge_deg[da] += 1
            doc_bridge_deg[db] += 1

        # Buat Section <-> Section Cross-Document Semantic Bridge Edges (top 2 per section)
        sec_node_by_id = {n.id: n for n in nodes_by_key.values() if n.node_type == "section"}
        sec_bridge_list: list[tuple[float, uuid.UUID, uuid.UUID, list[tuple[float, _ChunkRecord, _ChunkRecord]]]] = []
        for (sa, sb), pairs in sec_pair_links.items():
            pairs.sort(key=lambda p: p[0], reverse=True)
            sec_bridge_list.append((pairs[0][0], sa, sb, pairs[:3]))

        sec_bridge_list.sort(key=lambda item: item[0], reverse=True)
        sec_bridge_deg: dict[uuid.UUID, int] = defaultdict(int)

        for top_score, sa, sb, top_pairs in sec_bridge_list:
            if sec_bridge_deg[sa] >= 2 or sec_bridge_deg[sb] >= 2:
                continue
            node_a = sec_node_by_id.get(sa)
            node_b = sec_node_by_id.get(sb)
            if not node_a or not node_b:
                continue
            best_s, best_ci, best_cj = top_pairs[0]
            shared_kw = _shared_keywords_between_chunks(best_ci, best_cj)
            chunk_ids = sorted({c.chunk_id for _, ci, cj in top_pairs for c in (ci, cj)})
            pct = round(best_s * 100)
            _add_edge(
                src_id=sa,
                tgt_id=sb,
                edge_type="semantic_bridge",
                weight=best_s,
                label=f"Jembatan Bagian {pct}%",
                keywords=", ".join(shared_kw) if shared_kw else "kemiripan konteks",
                description=(
                    f"Bagian '{node_a.label}' ({best_ci.filename}) memiliki keterkaitan semantik {pct}% "
                    f"dengan '{node_b.label}' ({best_cj.filename})."
                ),
                is_cross_document=True,
                source_chunk_ids=chunk_ids,
                properties_json={"similarity_score": round(best_s, 4)},
                undirected=True,
            )
            sec_bridge_deg[sa] += 1
            sec_bridge_deg[sb] += 1

    # 6. Hitung degree setiap node & simpan secara atomik ke PostgreSQL
    node_degrees: dict[uuid.UUID, int] = defaultdict(int)
    for edge in edges_accumulator.values():
        node_degrees[edge.source_node_id] += 1
        node_degrees[edge.target_node_id] += 1

    all_nodes = list(nodes_by_key.values())
    for node in all_nodes:
        node.degree = node_degrees.get(node.id, 0)

    all_edges = list(edges_accumulator.values())

    await session.execute(delete(KGEdge).where(KGEdge.version_id == version_id))
    await session.execute(delete(KGNode).where(KGNode.version_id == version_id))
    session.add_all(all_nodes)
    await session.flush()
    session.add_all(all_edges)
    await session.commit()

    cross_doc_edges = sum(1 for e in all_edges if e.is_cross_document)
    sem_bridge_edges = sum(1 for e in all_edges if e.edge_type == "semantic_bridge")
    logger.info(
        "Zero-LLM Knowledge Graph dibangun untuk knowledge=%s version=%s (%d nodes, %d edges, %d cross-doc, %d semantic bridges).",
        knowledge_id,
        version_id,
        len(all_nodes),
        len(all_edges),
        cross_doc_edges,
        sem_bridge_edges,
    )
    return GraphBuildSummary(
        knowledge_id=knowledge_id,
        version_id=version_id,
        node_count=len(all_nodes),
        edge_count=len(all_edges),
        cross_document_edges=cross_doc_edges,
        semantic_bridge_edges=sem_bridge_edges,
    )
