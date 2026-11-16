import asyncio
import logging
import re
from dataclasses import dataclass, field

import httpx

from app.core.config import settings
from app.services.embedding_service import normalize_l2

logger = logging.getLogger(__name__)

_QUESTION_PREFIX_RE = re.compile(
    r"^(apa\s+saja|apa\s+itu|apa|bagaimana\s+cara|bagaimana|gimana|siapa\s+yang|siapa|kapan|dimana|di\s+mana|mengapa|kenapa|berapa|tolong\s+jelaskan|jelaskan|sebutkan|cari|what\s+is|what\s+are|how\s+to|how\s+do|how|when|where|who|why)\b[\s:,-]*",
    flags=re.IGNORECASE,
)

# Kamus ekspansi sinonim/singkatan ringan (zero-latency) untuk domain dokumen operasional & bisnis
_SYNONYM_EXPANSIONS: dict[str, list[str]] = {
    "sop": ["standar", "operasional", "prosedur"],
    "hr": ["human", "resources", "sdm", "kepegawaian"],
    "sdm": ["sumber", "daya", "manusia", "pegawai", "staf"],
    "klaim": ["pengajuan", "kompensasi", "ganti", "rugi"],
    "edc": ["mesin", "pembayaran", "kartu", "settlement"],
    "kasir": ["pembayaran", "transaksi", "uang", "settlement"],
    "cek": ["periksa", "pemeriksaan", "checklist", "verifikasi"],
    "checklist": ["daftar", "periksa", "harian", "pemeriksaan"],
    "suhu": ["temperatur", "derajat", "pendingin", "kulkas"],
    "syarat": ["persyaratan", "ketentuan", "dokumen", "kelengkapan"],
    "alur": ["prosedur", "tahapan", "diagram", "langkah"],
    "dokumen": ["berkas", "lampiran", "file", "formulir"],
    "tamu": ["pelanggan", "customer", "pengunjung", "guest"],
    "pelanggan": ["tamu", "customer", "pengunjung"],
    "presentasi": ["slide", "materi", "deck"],
    "kamar": ["room", "hotel", "housekeeping"],
}


@dataclass(frozen=True, slots=True)
class EnhancedQuery:
    original_query: str
    hyde_document: str | None = None
    expanded_terms: list[str] = field(default_factory=list)
    sparse_query: str = ""
    enhancement_used: str = "none"


def _expand_query_terms(query: str) -> list[str]:
    """Menambahkan sinonim dan kepanjangan singkatan yang relevan tanpa LLM."""
    tokens = re.findall(r"[0-9a-zA-Z]+", query.lower())
    seen = set(tokens)
    extras: list[str] = []
    for tok in tokens:
        for syn in _SYNONYM_EXPANSIONS.get(tok, ()):
            if syn not in seen:
                seen.add(syn)
                extras.append(syn)
    return extras[:8]


def _build_heuristic_hyde_passage(query: str) -> str:
    """Mengubah pertanyaan pendek menjadi teks deklaratif bergaya dokumen SOP/kebijakan tanpa latency LLM."""
    stripped = _QUESTION_PREFIX_RE.sub("", query.strip()).rstrip("?.! ").strip()
    core = stripped or query.strip()
    return (
        f"Standar prosedur, ketentuan, dan informasi lengkap mengenai {core}. "
        f"Dokumen ini menjelaskan langkah-langkah pelaksanaan, persyaratan, penanggung jawab, "
        f"serta rincian aturan terkait {core}."
    )


async def _generate_hyde_via_llm(query: str) -> str | None:
    """Memanggil LLM eksternal/lokal (Gemini/OpenAI/Ollama) secara opsional untuk HyDE."""
    provider = settings.HYDE_LLM_PROVIDER.strip().lower()
    if provider in ("", "none", "heuristic"):
        return None

    prompt = (
        "Tuliskan 1 paragraf singkat (2-3 kalimat) bergaya dokumen standar operasional atau kebijakan "
        "yang secara langsung menjawab pertanyaan berikut dalam bahasa yang sama dengan pertanyaan. "
        "Jangan gunakan basa-basi pembuka.\n\n"
        f"Pertanyaan: {query}"
    )

    try:
        if provider == "gemini":
            if not settings.HYDE_API_KEY and not settings.GCP_PROJECT_ID:
                return None

            def _call_gemini() -> str | None:
                from google import genai

                if settings.HYDE_API_KEY:
                    client = genai.Client(api_key=settings.HYDE_API_KEY)
                else:
                    client = genai.Client(
                        vertexai=True,
                        project=settings.GCP_PROJECT_ID,
                        location=settings.GCP_LOCATION,
                    )
                resp = client.models.generate_content(
                    model=settings.HYDE_LLM_MODEL,
                    contents=prompt,
                )
                text = getattr(resp, "text", None)
                return text.strip() if isinstance(text, str) and text.strip() else None

            return await asyncio.wait_for(
                asyncio.to_thread(_call_gemini),
                timeout=settings.HYDE_TIMEOUT_SECONDS,
            )

        if provider in ("openai", "ollama"):
            base_url = settings.HYDE_BASE_URL.rstrip("/")
            if not base_url:
                base_url = (
                    "http://localhost:11434/v1"
                    if provider == "ollama"
                    else "https://api.openai.com/v1"
                )
            headers = {"Content-Type": "application/json"}
            if settings.HYDE_API_KEY:
                headers["Authorization"] = f"Bearer {settings.HYDE_API_KEY}"

            payload = {
                "model": settings.HYDE_LLM_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
                "max_tokens": 180,
            }
            async with httpx.AsyncClient(timeout=settings.HYDE_TIMEOUT_SECONDS) as client:
                resp = await client.post(f"{base_url}/chat/completions", json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                return content.strip() if isinstance(content, str) and content.strip() else None

    except Exception as exc:  # noqa: BLE001
        logger.warning("HyDE LLM provider '%s' gagal (%s), fallback ke heuristic HyDE.", provider, exc)

    return None


def blend_query_and_hyde_vectors(
    query_vector: list[float],
    hyde_vector: list[float],
    hyde_weight: float = 0.65,
) -> list[float]:
    """Menggabungkan vector query asli dengan vector HyDE lalu menormalisasi ke unit length L2."""
    q_weight = 1.0 - hyde_weight
    blended = [
        (q_weight * q) + (hyde_weight * h)
        for q, h in zip(query_vector, hyde_vector, strict=True)
    ]
    return normalize_l2(blended)


async def enhance_query(
    query: str,
    use_hyde: bool = False,
    use_query_expansion: bool = False,
) -> EnhancedQuery:
    """Menjalankan Query Enhancement (HyDE dan/atau Query Expansion) secara opsional dan aman."""
    expanded_terms = _expand_query_terms(query) if use_query_expansion else []
    sparse_query = f"{query} {' '.join(expanded_terms)}".strip() if expanded_terms else query

    if not use_hyde:
        return EnhancedQuery(
            original_query=query,
            hyde_document=None,
            expanded_terms=expanded_terms,
            sparse_query=sparse_query,
            enhancement_used="expansion" if expanded_terms else "none",
        )

    llm_passage = await _generate_hyde_via_llm(query)
    if llm_passage:
        used = "hyde_llm+expansion" if expanded_terms else "hyde_llm"
        hyde_doc = llm_passage
    else:
        used = "hyde_heuristic+expansion" if expanded_terms else "hyde_heuristic"
        hyde_doc = _build_heuristic_hyde_passage(query)

    return EnhancedQuery(
        original_query=query,
        hyde_document=hyde_doc,
        expanded_terms=expanded_terms,
        sparse_query=sparse_query,
        enhancement_used=used,
    )
