import math
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class EvalCase:
    case_id: str
    query: str
    expected_keywords: tuple[str, ...]
    category: str = "general"


@dataclass(frozen=True, slots=True)
class CaseResult:
    case_id: str
    category: str
    hit_at_k: bool
    rr: float
    ndcg: float
    latency_ms: int


@dataclass(slots=True)
class RetrievalModeMetrics:
    mode_name: str
    total_cases: int
    hit_rate_at_k: float
    mrr: float
    ndcg: float
    avg_latency_ms: float
    per_case: list[CaseResult] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class EvalReport:
    k: int
    modes: list[RetrievalModeMetrics]


def _is_relevant_chunk(content: str, expected_keywords: tuple[str, ...]) -> bool:
    """Menentukan apakah chunk memuat seluruh kata kunci kunci jawaban yang diharapkan."""
    lower = content.lower()
    return all(kw.lower() in lower for kw in expected_keywords)


def reciprocal_rank(relevances: list[bool]) -> float:
    """Menghitung Reciprocal Rank (1 / rank pertama yang relevan)."""
    for idx, rel in enumerate(relevances, start=1):
        if rel:
            return 1.0 / idx
    return 0.0


def ndcg_at_k(relevances: list[bool], k: int) -> float:
    """Menghitung Normalized Discounted Cumulative Gain (NDCG@K) untuk relevansi biner."""
    if k <= 0 or not relevances:
        return 0.0
    rel_k = relevances[:k]
    dcg = sum((1.0 if r else 0.0) / math.log2(i + 2) for i, r in enumerate(rel_k))
    ideal_count = sum(1 for r in relevances if r)
    ideal_len = min(k, max(1, ideal_count))
    idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal_len))
    return round(dcg / idcg, 4) if idcg > 0 else 0.0


def evaluate_retrieval_case(
    case: EvalCase,
    retrieved_contents: list[str],
    latency_ms: int,
    k: int = 5,
) -> CaseResult:
    """Mengevaluasi satu kasus uji retrieval terhadap daftar konten hasil pencarian."""
    top_k_contents = retrieved_contents[:k]
    relevances = [_is_relevant_chunk(c, case.expected_keywords) for c in top_k_contents]
    return CaseResult(
        case_id=case.case_id,
        category=case.category,
        hit_at_k=any(relevances),
        rr=round(reciprocal_rank(relevances), 4),
        ndcg=ndcg_at_k(relevances, k=k),
        latency_ms=latency_ms,
    )


def summarize_mode_results(mode_name: str, results: list[CaseResult]) -> RetrievalModeMetrics:
    """Mengagregasi metrik Hit Rate, MRR, NDCG, dan rata-rata latency dari daftar CaseResult."""
    total = len(results)
    if total == 0:
        return RetrievalModeMetrics(
            mode_name=mode_name,
            total_cases=0,
            hit_rate_at_k=0.0,
            mrr=0.0,
            ndcg=0.0,
            avg_latency_ms=0.0,
            per_case=[],
        )
    return RetrievalModeMetrics(
        mode_name=mode_name,
        total_cases=total,
        hit_rate_at_k=round(sum(1 for r in results if r.hit_at_k) / total, 4),
        mrr=round(sum(r.rr for r in results) / total, 4),
        ndcg=round(sum(r.ndcg for r in results) / total, 4),
        avg_latency_ms=round(sum(r.latency_ms for r in results) / total, 1),
        per_case=results,
    )
